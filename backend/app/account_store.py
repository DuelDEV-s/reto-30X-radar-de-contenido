"""Perfiles de Instagram guardados una sola vez y reutilizados entre marcas y corridas.

Antes de pedir perfiles a Bright Data se consulta `instagram_accounts`: solo se paga por las cuentas que
faltan o cuya ficha superó la vigencia (INSTAGRAM_PROFILE_TTL_DAYS, 30 días por defecto).
"""
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .brightdata import StartUnconfirmed, request, setting_int
from .creators import USERNAME
from .database import InstagramAccount
from .profile_common import ProviderError, number

MAX_AVATAR_BYTES = 1_000_000
RESTRICTED_CODES = {"private_profile", "requires_login", "login_required"}


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def ttl() -> timedelta:
    return timedelta(days=setting_int("INSTAGRAM_PROFILE_TTL_DAYS", 30, 1, 365))


def profile_dataset() -> str:
    return os.environ["BRIGHT_DATA_INSTAGRAM_DATASET_ID"]


def missing(db: Session, usernames: list[str]) -> list[str]:
    """Usuarios sin ficha guardada o con ficha vencida, en el orden recibido."""
    cutoff = now() - ttl()
    rows = db.scalars(select(InstagramAccount).where(InstagramAccount.username.in_(usernames))).all() if usernames else []
    fresh = {r.username for r in rows if aware(r.fetched_at) >= cutoff}
    return [u for u in dict.fromkeys(usernames) if u not in fresh]


def profile_username(record: dict) -> str | None:
    for value in (record.get("account"), record.get("profile_url"), record.get("url"), (record.get("input") or {}).get("url")):
        if isinstance(value, str) and value:
            name = value.rstrip("/").rsplit("/", 1)[-1].lower()
            if USERNAME.fullmatch(name):
                return name
    return None


def account_fields(record: dict) -> dict:
    """Campos públicos del perfil tal como los entrega Bright Data."""
    urls = record.get("external_url") or record.get("external_urls") or []
    urls = [urls] if isinstance(urls, str) else [u for u in urls if isinstance(u, str)] if isinstance(urls, list) else []
    category = record.get("category_name") or record.get("business_category_name")
    return {
        "full_name": record.get("full_name") or record.get("profile_name") or None,
        "biography": record.get("biography") or None,
        "followers": number(record.get("followers")),
        "following": number(record.get("following")),
        "posts_count": number(record.get("posts_count")),
        "is_verified": record.get("is_verified") if isinstance(record.get("is_verified"), bool) else None,
        "is_private": record.get("is_private") if isinstance(record.get("is_private"), bool) else None,
        "category": category if isinstance(category, str) else None,
        "external_urls": urls[:10],
    }


async def download_avatar(client: httpx.AsyncClient, url) -> tuple[bytes, str] | None:
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    try:
        response = await client.get(url, timeout=15)
    except httpx.HTTPError:
        return None
    kind = response.headers.get("content-type", "").split(";")[0].strip()
    if response.status_code != 200 or not kind.startswith("image/") or len(response.content) > MAX_AVATAR_BYTES:
        return None
    return response.content, kind


async def trigger(client, dataset: str, inputs: list[dict], **params) -> str:
    result = await request(client, "POST", "trigger", params={"dataset_id": dataset, "include_errors": "true", "notify": "false", **params}, json=inputs, timeout=httpx.Timeout(25, connect=5))
    snapshot = result.get("snapshot_id") if isinstance(result, dict) else None
    if not isinstance(snapshot, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot):
        raise StartUnconfirmed("Bright Data respondió sin un snapshot_id válido. Revisa las ejecuciones antes de reintentar.", code="missing_snapshot_id")
    return snapshot


async def trigger_profiles(client, usernames: list[str]) -> str:
    return await trigger(client, profile_dataset(), [{"url": f"https://www.instagram.com/{u}"} for u in usernames])


async def snapshot_records(client, snapshot: str) -> list | None:
    """Registros del trabajo, o None si sigue en proceso."""
    progress = await request(client, "GET", f"progress/{snapshot}")
    status = progress.get("status") if isinstance(progress, dict) else None
    if status in {"running", "starting", "pending", "building"}:
        return None
    if status != "ready":
        raise ProviderError("Bright Data indicó un fallo o un estado no reconocido del trabajo.", code="collection_failed")
    records = await request(client, "GET", f"snapshot/{snapshot}", params={"format": "json"})
    # Con progreso "ready", la descarga aún puede responder 202 {"status": "building"} mientras se arma el
    # archivo. No son registros: tratarlos como tales daría el trabajo por terminado y vacío.
    if isinstance(records, dict) and isinstance(records.get("status"), str) and not records.get("url"):
        return None
    return records if isinstance(records, list) else [records]


async def store_profiles(db: Session, client, records: list, requested: list[str]) -> int:
    """Guarda las fichas recibidas. Una cuenta pedida sin ficha queda marcada para no volver a pagarla
    durante la vigencia; si ya tenía una ficha válida, esa ficha se conserva. Devuelve cuántas llegaron."""
    received, failures = {}, {}
    for record in records:
        if not isinstance(record, dict):
            continue
        name = profile_username(record)
        if name not in requested:
            continue
        code = str(record.get("error_code") or record.get("error") or "").lower()
        if code:
            failures[name] = "private" if code in RESTRICTED_CODES else "not_found" if "not_found" in code or "dead" in code else "error"
        else:
            received[name] = record
    for name in requested:
        account = db.get(InstagramAccount, name)
        record = received.get(name)
        if record is None:
            if account is None:
                db.add(InstagramAccount(username=name, fetch_status=failures.get(name, "error"), external_urls=[], fetched_at=now()))
            continue
        avatar = await download_avatar(client, record.get("profile_image_link"))
        values = {**account_fields(record), "raw": record, "fetch_status": "private" if record.get("is_private") else "ok", "fetched_at": now()}
        if avatar or account is None:
            values.update(avatar=avatar[0] if avatar else None, avatar_type=avatar[1] if avatar else None)
        if account is None:
            db.add(InstagramAccount(username=name, **values))
        else:
            for key, value in values.items():
                setattr(account, key, value)
    db.commit()
    return len(received)


def account_dict(username: str, account: InstagramAccount | None) -> dict:
    """Ficha pública para la API; `profile_available` indica si hay datos del perfil."""
    has_profile = bool(account and account.raw is not None)
    return {
        "username": username, "profile_url": f"https://www.instagram.com/{username}",
        "full_name": account.full_name if account else None, "biography": account.biography if account else None,
        "followers": account.followers if account else None, "following": account.following if account else None,
        "posts_count": account.posts_count if account else None, "is_verified": account.is_verified if account else None,
        "is_private": account.is_private if account else None, "category": account.category if account else None,
        "external_urls": account.external_urls if account else [], "profile_available": has_profile,
        "fetch_status": account.fetch_status if account else None, "fetched_at": account.fetched_at if account else None,
        "avatar_url": f"/api/instagram-accounts/{username}/avatar" if account and account.avatar else None,
    }


def accounts_by_username(db: Session, usernames: list[str]) -> dict[str, InstagramAccount]:
    if not usernames:
        return {}
    return {a.username: a for a in db.scalars(select(InstagramAccount).where(InstagramAccount.username.in_(usernames))).all()}
