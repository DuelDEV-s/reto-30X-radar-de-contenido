"""Cuentas de Instagram relacionadas con una marca (un nivel), a partir de sus reels en Bright Data.

Dos trabajos asíncronos de Bright Data, avanzados por consultas sucesivas (no hay worker):
1. reels: discover by URL del perfil de la marca → quién publicó la colaboración, coautores y etiquetados.
2. profiles: ficha de las cuentas que no estén en `instagram_accounts` (o estén vencidas), en un solo
   trabajo. Si todas están guardadas, no se llama a Bright Data.

Cada POST facturable se reserva antes en la base de datos con una transición condicional, de modo que
consultas concurrentes nunca inician dos veces el mismo trabajo, y un inicio sin confirmar no se reenvía.
"""
import os
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .account_review import review_dict, reviews_by_username
from .account_store import account_dict, accounts_by_username, aware, missing, now, snapshot_records, store_profiles, trigger, trigger_profiles
from .brightdata import StartUnconfirmed, canonical_profile, setting_int
from .creators import USERNAME
from .database import Brand, RelatedAccount, RelatedAccountRun
from .profile_common import ProviderError

REELS_DATASET_DEFAULT = "gd_lyclm20il4r5helnj"
REELS_PER_RUN = 5
MAX_ACCOUNTS = 10
RELATION_ORDER = ("coauthor", "tagged", "posted")
ACTIVE = {"reels_requesting", "reels_pending", "profiles_requesting", "profiles_pending"}
FINISHED = {"ready", "failed", "unknown"}


def missing_config() -> list[str]:
    return [key for key in ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_INSTAGRAM_DATASET_ID") if not os.getenv(key)]


def brand_instagram(brand: Brand) -> str | None:
    """Usuario de Instagram de la marca según los perfiles de su brief."""
    for profile in brand.brief.get("profiles", []):
        if profile.get("platform") == "instagram":
            return canonical_profile(profile["url"], "instagram").rsplit("/", 1)[-1]
    return None


def extract_relations(records: list, brand: str) -> dict[str, dict]:
    """Cuentas que aparecen en los reels de la marca, sin la propia marca, ordenadas por presencia.

    posted: publicó una colaboración que aparece en el perfil de la marca; coauthor: coautor del reel;
    tagged: etiquetado en el reel.
    """
    found: dict[str, dict] = {}

    def add(username, kind, reel_url):
        name = (username or "").strip().lower().lstrip("@") if isinstance(username, str) else ""
        if not USERNAME.fullmatch(name) or name == brand:
            return
        entry = found.setdefault(name, {"relations": [], "reel_urls": []})
        if kind not in entry["relations"]:
            entry["relations"].append(kind)
        if isinstance(reel_url, str) and reel_url not in entry["reel_urls"]:
            entry["reel_urls"].append(reel_url)

    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict) or record.get("error") or record.get("error_code"):
            continue
        url = record.get("url")
        add(record.get("user_posted"), "posted", url)
        for coauthor in record.get("coauthor_producers") or []:
            add(coauthor, "coauthor", url)
        for tagged in record.get("tagged_users") or []:
            add(tagged.get("username") if isinstance(tagged, dict) else None, "tagged", url)
    for entry in found.values():
        entry["relations"].sort(key=RELATION_ORDER.index)
    ranked = sorted(found.items(), key=lambda kv: (-len(kv[1]["reel_urls"]), -len(kv[1]["relations"]), kv[0]))
    return dict(ranked[:MAX_ACCOUNTS])


def transition(db: Session, run: RelatedAccountRun, expected: str, **values) -> bool:
    """Cambia de estado solo si nadie más lo hizo antes; quien gana es quien puede hacer el POST."""
    result = db.execute(update(RelatedAccountRun).where(
        RelatedAccountRun.brand_id == run.brand_id,
        RelatedAccountRun.generation == run.generation,
        RelatedAccountRun.state == expected,
    ).values(**{"updated_at": now(), **values}))
    db.commit()
    db.expire_all()
    return result.rowcount == 1


def fail(db, run, expected, error):
    state = "unknown" if isinstance(error, StartUnconfirmed) else "failed"
    message = error.message if isinstance(error, ProviderError) else "No fue posible comunicarse con Bright Data. No se reenvió ninguna extracción."
    transition(db, run, expected, state=state, message=message[:500])


async def start(db: Session, brand: Brand, client) -> RelatedAccountRun:
    username = brand_instagram(brand)
    if not username:
        raise ProviderError("La marca no tiene un perfil de Instagram en su brief.", code="no_instagram")
    run = db.get(RelatedAccountRun, brand.id)
    if run and run.state in ACTIVE:
        return run
    values = {"generation": str(uuid4()), "state": "reels_requesting", "brand_account": username, "reels_snapshot_id": None,
              "profiles_snapshot_id": None, "relations": None, "message": "", "created_at": now(), "updated_at": now()}
    if run:
        if not transition(db, run, run.state, **values):
            return db.get(RelatedAccountRun, brand.id)
    else:
        db.add(RelatedAccountRun(brand_id=brand.id, **values))
        db.commit()
    run = db.get(RelatedAccountRun, brand.id)
    try:
        dataset = os.getenv("BRIGHT_DATA_INSTAGRAM_REELS_DATASET_ID") or REELS_DATASET_DEFAULT
        snapshot = await trigger(client, dataset, [{"url": f"https://www.instagram.com/{username}", "num_of_posts": REELS_PER_RUN}],
                                 type="discover_new", discover_by="url", limit_per_input=REELS_PER_RUN)
        transition(db, run, "reels_requesting", state="reels_pending", reels_snapshot_id=snapshot)
    except (ProviderError, httpx.HTTPError, ValueError, TypeError) as error:
        fail(db, run, "reels_requesting", error if isinstance(error, ProviderError) else StartUnconfirmed("El inicio no se pudo confirmar; revisa Bright Data antes de reintentar."))
    return db.get(RelatedAccountRun, brand.id)


def save_relations(db: Session, run: RelatedAccountRun) -> None:
    db.execute(delete(RelatedAccount).where(RelatedAccount.brand_id == run.brand_id))
    for name, link in (run.relations or {}).items():
        db.add(RelatedAccount(brand_id=run.brand_id, username=name, relations=link["relations"], reel_urls=link["reel_urls"], collected_at=now()))
    db.commit()


async def advance(db: Session, run: RelatedAccountRun, client) -> RelatedAccountRun:
    """Consulta el trabajo en curso y avanza al siguiente paso cuando Bright Data termina."""
    if run.state in FINISHED:
        return run
    age = (now() - aware(run.updated_at)).total_seconds()
    if run.state.endswith("_requesting"):
        if age > 30:
            transition(db, run, run.state, state="unknown", message="El inicio quedó sin confirmar. Revisa Bright Data; no se repetirá automáticamente.")
        return db.get(RelatedAccountRun, run.brand_id)

    def still_running():
        # El tope solo aplica si Bright Data sigue trabajando: un trabajo ya listo se recoge aunque nadie consultara a tiempo.
        if age > setting_int("BRIGHT_DATA_JOB_TIMEOUT_SECONDS", 900, 30, 3600):
            transition(db, run, state, state="failed", message="La recolección excedió el tiempo configurado. No se inició otra extracción.")
        return db.get(RelatedAccountRun, run.brand_id)

    state = run.state
    try:
        if state == "reels_pending":
            records = await snapshot_records(client, run.reels_snapshot_id)
            if records is None:
                return still_running()
            relations = extract_relations(records, run.brand_account)
            if not relations:
                db.execute(delete(RelatedAccount).where(RelatedAccount.brand_id == run.brand_id))
                transition(db, run, state, state="ready", relations={}, message=f"Los últimos {REELS_PER_RUN} reels no tienen colaboraciones ni etiquetas.")
                return db.get(RelatedAccountRun, run.brand_id)
            need = missing(db, list(relations))
            reused = len(relations) - len(need)
            if not need:
                if transition(db, run, state, state="ready", relations=relations, message=f"{len(relations)} cuentas relacionadas; todos los perfiles ya estaban guardados."):
                    save_relations(db, db.get(RelatedAccountRun, run.brand_id))
                return db.get(RelatedAccountRun, run.brand_id)
            if not transition(db, run, state, state="profiles_requesting", relations=relations, message=f"{len(need)} perfiles nuevos; {reused} reutilizados."):
                return db.get(RelatedAccountRun, run.brand_id)
            run, state = db.get(RelatedAccountRun, run.brand_id), "profiles_requesting"
            snapshot = await trigger_profiles(client, need)
            transition(db, run, state, state="profiles_pending", profiles_snapshot_id=snapshot)
        elif state == "profiles_pending":
            records = await snapshot_records(client, run.profiles_snapshot_id)
            if records is None:
                return still_running()
            found = await store_profiles(db, client, records, missing(db, list(run.relations or {})))
            save_relations(db, run)
            transition(db, run, state, state="ready", message=f"{len(run.relations or {})} cuentas relacionadas; {found} perfiles nuevos de Bright Data, el resto reutilizados.")
    except (ProviderError, httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        fail(db, run, state, error if isinstance(error, ProviderError) or state != "profiles_requesting" else StartUnconfirmed("El inicio no se pudo confirmar; revisa Bright Data antes de reintentar."))
    return db.get(RelatedAccountRun, run.brand_id)


def output(db: Session, brand_id: str, run: RelatedAccountRun | None) -> dict:
    links = db.scalars(select(RelatedAccount).where(RelatedAccount.brand_id == brand_id)).all()
    names = [link.username for link in links]
    profiles, reviews = accounts_by_username(db, names), reviews_by_username(db, brand_id, names)
    accounts = []
    for link in links:
        account = account_dict(link.username, profiles.get(link.username))
        # El veredicto del LLM aquí es informativo: no filtra las cuentas relacionadas.
        accounts.append({**account, **review_dict(reviews.get(link.username), account["profile_available"]),
                         "relations": link.relations, "reel_urls": link.reel_urls, "collected_at": link.collected_at})
    accounts.sort(key=lambda a: (-len(a["reel_urls"]), -(a["followers"] or 0), a["username"]))
    return {
        "state": run.state if run else "not_started",
        "message": run.message if run else "",
        "brand_account": run.brand_account if run else None,
        "requested_at": run.created_at if run else None,
        "updated_at": run.updated_at if run else None,
        "accounts": accounts,
    }
