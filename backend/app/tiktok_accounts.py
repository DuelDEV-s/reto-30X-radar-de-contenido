"""Perfiles de TikTok guardados una sola vez y reutilizados entre marcas y corridas, como `instagram_accounts`.

Antes de pedir perfiles a Bright Data se consulta `tiktok_accounts`: solo se paga por las cuentas que faltan o
cuya ficha superó la vigencia (TIKTOK_PROFILE_TTL_DAYS, 30 días por defecto).

Los nombres de campo del scraper de perfiles varían entre versiones (followers/follower_count,
biography/signature…); se aceptan los conocidos y el registro completo queda en `raw`.
"""
import os
import re
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import account_store
from .account_store import aware, now, trigger
from .brightdata import setting_int
from .database import TikTokAccount, TikTokPost
from .profile_common import number

PROFILES_DATASET_DEFAULT = "gd_l1villgoiiidt09ci"
USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")
TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
MAX_CAPTIONS = 8


def profile_url(username: str) -> str:
    return f"https://www.tiktok.com/@{username}"


def username_from(value) -> str | None:
    """Usuario a partir de "@ana", "ana" o un enlace de TikTok (perfil o video)."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith(("http://", "https://")):
        url = urlsplit(value)
        if url.hostname not in TIKTOK_HOSTS:
            return None
        first = next((p for p in url.path.split("/") if p), "")
        if not first.startswith("@"):
            return None
        value = first
    name = value.lstrip("@").lower()
    return name if USERNAME.fullmatch(name) else None


def ttl() -> timedelta:
    return timedelta(days=setting_int("TIKTOK_PROFILE_TTL_DAYS", 30, 1, 365))


def profile_dataset() -> str:
    return os.getenv("BRIGHT_DATA_TIKTOK_PROFILES_DATASET_ID") or PROFILES_DATASET_DEFAULT


def missing(db: Session, usernames: list[str]) -> list[str]:
    """Usuarios sin ficha guardada o con ficha vencida, en el orden recibido."""
    cutoff = now() - ttl()
    rows = db.scalars(select(TikTokAccount).where(TikTokAccount.username.in_(usernames))).all() if usernames else []
    fresh = {r.username for r in rows if aware(r.fetched_at) >= cutoff}
    return [u for u in dict.fromkeys(usernames) if u not in fresh]


async def trigger_profiles(client, usernames: list[str]) -> str:
    return await trigger(client, profile_dataset(), [{"url": profile_url(u)} for u in usernames])


def profile_username(record: dict) -> str | None:
    source = record.get("input") or record.get("discovery_input") or {}
    for value in (record.get("url"), record.get("profile_url"), record.get("account_id"), record.get("username"),
                  source.get("url") if isinstance(source, dict) else None):
        name = username_from(value)
        if name:
            return name
    return None


def first(record: dict, *keys):
    return next((record[k] for k in keys if record.get(k) not in (None, "")), None)


def account_fields(record: dict) -> dict:
    """Campos públicos del perfil tal como los entrega Bright Data."""
    links = first(record, "bio_link", "external_url", "external_urls", "links") or []
    links = [links] if isinstance(links, str) else [u if isinstance(u, str) else u.get("url") for u in links if isinstance(u, (str, dict))] if isinstance(links, list) else []
    private = first(record, "is_private", "private_account")
    verified = record.get("is_verified")
    region = record.get("region")
    return {
        "nickname": (first(record, "nickname", "profile_name", "full_name") or None),
        "biography": first(record, "biography", "signature", "description"),
        "followers": number(first(record, "followers", "follower_count", "followers_count")),
        "following": number(first(record, "following", "following_count")),
        "likes_total": number(first(record, "likes", "heart_count", "likes_count", "total_likes")),
        "videos_count": number(first(record, "videos_count", "video_count", "posts_count")),
        "is_verified": verified if isinstance(verified, bool) else None,
        "is_private": private if isinstance(private, bool) else None,
        "region": region[:10] if isinstance(region, str) else None,
        "external_urls": [u for u in links if isinstance(u, str)][:10],
    }


async def store_profiles(db: Session, client, records: list, requested: list[str]) -> int:
    return await account_store.store_profiles(db, client, records, requested, model=TikTokAccount, fields=account_fields,
                                              username_of=profile_username, avatar_key="profile_pic_url")


def account_dict(username: str, account: TikTokAccount | None) -> dict:
    """Ficha pública para la API, con las mismas claves que la de Instagram más las propias de TikTok."""
    has_profile = bool(account and account.raw is not None)
    value = lambda key: getattr(account, key) if account else None
    return {
        "platform": "tiktok", "username": username, "profile_url": profile_url(username),
        "full_name": value("nickname"), "biography": value("biography"), "followers": value("followers"),
        "following": value("following"), "posts_count": value("videos_count"), "likes_total": value("likes_total"),
        "is_verified": value("is_verified"), "is_private": value("is_private"), "category": None,
        "region": value("region"), "external_urls": account.external_urls if account else [], "profile_available": has_profile,
        "fetch_status": value("fetch_status"), "fetched_at": value("fetched_at"),
        "avatar_url": f"/api/tiktok-accounts/{username}/avatar" if account and account.avatar else None,
    }


def accounts_by_username(db: Session, usernames: list[str]) -> dict[str, TikTokAccount]:
    return account_store.accounts_by_username(db, usernames, model=TikTokAccount)


def review_evidence(db: Session, accounts: dict[str, TikTokAccount]) -> dict[str, dict]:
    """Lo que ve el LLM de cada cuenta: ficha pública y descripciones de sus videos ya guardados.

    Solo cuentan los videos vistos antes de traer la ficha (los de la búsqueda por tópico): los que llegan
    después con la línea base no cambian la evidencia ni obligan a revisar la cuenta otra vez."""
    names = list(accounts)
    rows = db.scalars(select(TikTokPost).where(TikTokPost.username.in_(names)).order_by(TikTokPost.posted_at.desc())).all() if names else []
    captions: dict[str, list[str]] = {}
    for post in rows:
        account = accounts[post.username]
        if post.caption and aware(post.first_seen_at) <= aware(account.fetched_at) and len(captions.get(post.username, [])) < MAX_CAPTIONS:
            captions.setdefault(post.username, []).append(post.caption[:400])
    return {name: {
        "platform": "tiktok", "username": name, "full_name": a.nickname, "biography": a.biography,
        "external_urls": a.external_urls[:5], "is_verified": a.is_verified, "followers": a.followers,
        "videos_count": a.videos_count, "likes_total": a.likes_total, "region": a.region,
        "recent_captions": captions.get(name, []),
    } for name, a in accounts.items()}
