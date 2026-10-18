"""Persistencia de corridas de búsqueda por tópico: queries, resultados de Google y candidatos.

Los candidatos de una corrida se pueden enriquecer con su ficha de perfil. Solo se piden a Bright Data
las cuentas que no estén vigentes en `instagram_accounts`; el resto se reutiliza sin costo.
"""
from uuid import uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .account_review import included, is_configured, review_dict, reviews_by_username
from .account_store import account_dict, accounts_by_username, aware, missing, now, snapshot_records, store_profiles, trigger_profiles
from .brightdata import StartUnconfirmed, setting_int
from .database import Brand, DiscoveryCandidate, DiscoveryHit, DiscoveryQuery, DiscoveryRun
from .discovery import DiscoveryResult
from .profile_common import ProviderError
from .query_builder import QueryPlan

PROFILES_ACTIVE = {"requesting", "pending"}


def run_status(result: DiscoveryResult) -> str:
    failed = sum(bool(q.error) for q in result.queries)
    return "failed" if failed == len(result.queries) else "partial" if failed else "completed"


def save_run(db: Session, brand: Brand, plan: QueryPlan, result: DiscoveryResult, *, topic, countries, max_queries, profiles_only, resolve_posts) -> DiscoveryRun:
    run = DiscoveryRun(
        brand_id=brand.id, status=run_status(result), topic=topic, platform=plan.platform, hl=result.hl,
        countries=[c for c in countries if c], max_queries=max_queries, profiles_only=profiles_only, resolve_posts=resolve_posts,
        identity=brand.identity, query_count=len(result.queries), result_count=len(result.outcomes),
        candidate_count=len(result.candidates), discarded_count=sum(o.outcome == "discarded" for o in result.outcomes),
        unresolved_count=sum(o.outcome == "unresolved" for o in result.outcomes),
    )
    db.add(run)
    db.flush()
    query_ids = {}
    for position, q in enumerate(result.queries):
        row = DiscoveryQuery(run_id=run.id, position=position, query=q.query, planned_query=q.planned_query, angle=q.angle,
                             topic=q.topic, gl=q.gl, fallback_used=q.fallback_used, results_count=q.results, error=q.error)
        db.add(row)
        db.flush()
        query_ids[(q.query, q.gl)] = row.id
    for o in result.outcomes:
        db.add(DiscoveryHit(run_id=run.id, query_id=query_ids[(o.query, o.gl)], rank=o.rank, link=o.link, outcome=o.outcome,
                            username=o.username, author_source=o.author_source, reason=o.reason))
    for c in result.candidates:
        db.add(DiscoveryCandidate(run_id=run.id, username=c.username, query_hits=c.query_hits, best_rank=c.best_rank))
    db.commit()
    return run


def summary(run: DiscoveryRun) -> dict:
    return {
        "id": run.id, "brand_id": run.brand_id, "status": run.status, "created_at": run.created_at, "topic": run.topic,
        "platform": run.platform, "hl": run.hl, "countries": run.countries, "max_queries": run.max_queries,
        "profiles_only": run.profiles_only, "resolve_posts": run.resolve_posts,
        "totals": {"queries": run.query_count, "results": run.result_count, "candidates": run.candidate_count,
                   "discarded": run.discarded_count, "unresolved": run.unresolved_count},
        "profiles": {"state": run.profiles_state, "message": run.profiles_message, "requested": len(run.profiles_requested or []),
                     "updated_at": run.profiles_updated_at},
    }


def list_runs(db: Session, brand_id: str) -> list[dict]:
    rows = db.scalars(select(DiscoveryRun).where(DiscoveryRun.brand_id == brand_id).order_by(DiscoveryRun.created_at.desc())).all()
    return [summary(r) for r in rows]


def detail(db: Session, run: DiscoveryRun) -> dict:
    queries = db.scalars(select(DiscoveryQuery).where(DiscoveryQuery.run_id == run.id).order_by(DiscoveryQuery.position)).all()
    hits = db.scalars(select(DiscoveryHit).where(DiscoveryHit.run_id == run.id).order_by(DiscoveryHit.rank)).all()
    candidates = db.scalars(select(DiscoveryCandidate).where(DiscoveryCandidate.run_id == run.id)).all()
    by_query, by_user = {}, {}
    for h in hits:
        by_query.setdefault(h.query_id, []).append(h)
        if h.username and h.outcome == "candidate":
            by_user.setdefault(h.username, []).append(h)
    text = {q.id: q.query for q in queries}
    profiles = accounts_by_username(db, [c.username for c in candidates])
    reviews = reviews_by_username(db, run.brand_id, [c.username for c in candidates])
    hit = lambda h: {"rank": h.rank, "link": h.link, "outcome": h.outcome, "username": h.username, "author_source": h.author_source, "reason": h.reason}
    verdicts = [reviews.get(c.username) for c in candidates]
    return {
        **summary(run),
        "identity": run.identity,
        "review_enabled": is_configured(),
        # Regla para tendencias: externas, relevancia alta o media, creador o empresa afín.
        "review_summary": {"included": sum(included(v) for v in verdicts), "internal": sum(bool(v and v.is_internal) for v in verdicts),
                           "excluded": sum(bool(v) and not included(v) for v in verdicts), "pending": sum(v is None for v in verdicts)},
        "queries": [{"position": q.position, "query": q.query, "planned_query": q.planned_query, "angle": q.angle, "topic": q.topic,
                     "gl": q.gl, "fallback_used": q.fallback_used, "results": q.results_count, "error": q.error,
                     "hits": [hit(h) for h in by_query.get(q.id, [])]} for q in queries],
        "candidates": [{**account_dict(c.username, profiles.get(c.username)),
                        **review_dict(reviews.get(c.username), bool(profiles.get(c.username) and profiles[c.username].raw is not None)),
                        **candidate_status(run, profiles.get(c.username)),
                        "included": included(reviews.get(c.username)),
                        "query_hits": c.query_hits,
                        "best_rank": c.best_rank, "sources": [{"query": text[h.query_id], "link": h.link, "rank": h.rank, "author_source": h.author_source}
                                                              for h in by_user.get(c.username, [])]}
                       for c in sorted(candidates, key=lambda c: (-c.query_hits, c.best_rank, c.username))],
    }


def candidate_status(run: DiscoveryRun, account) -> dict:
    """Sin ficha todavía: aclara si falta pedirla o si Bright Data la está descargando."""
    if account is not None:
        return {}
    if run.profiles_state in PROFILES_ACTIVE:
        return {"review_status": "awaiting_profile"}
    if run.profiles_state == "not_started":
        return {"review_status": "not_requested"}
    return {}


def candidate_usernames(db: Session, run: DiscoveryRun) -> list[str]:
    rows = db.scalars(select(DiscoveryCandidate).where(DiscoveryCandidate.run_id == run.id)).all()
    return [c.username for c in sorted(rows, key=lambda c: (-c.query_hits, c.best_rank, c.username))]


def profiles_transition(db: Session, run: DiscoveryRun, expected: str, **values) -> bool:
    """Cambio condicional del enriquecimiento: solo quien gana la transición puede hacer el POST facturable."""
    generation = DiscoveryRun.profiles_generation
    result = db.execute(update(DiscoveryRun).where(
        DiscoveryRun.id == run.id, DiscoveryRun.profiles_state == expected,
        generation.is_(None) if run.profiles_generation is None else generation == run.profiles_generation,
    ).values(**values, profiles_updated_at=now()))
    db.commit()
    db.expire_all()
    return result.rowcount == 1


async def start_profiles(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    if run.profiles_state in PROFILES_ACTIVE:
        return await advance_profiles(db, run, client)
    usernames = candidate_usernames(db, run)
    need = missing(db, usernames)
    reused = len(usernames) - len(need)
    values = {"profiles_generation": str(uuid4()), "profiles_snapshot_id": None, "profiles_requested": need}
    if not need:
        profiles_transition(db, run, run.profiles_state, profiles_state="ready", profiles_message=f"Sin costo: los {reused} perfiles ya estaban guardados.", **values)
        return db.get(DiscoveryRun, run.id)
    if not profiles_transition(db, run, run.profiles_state, profiles_state="requesting", profiles_message=f"{len(need)} perfiles nuevos; {reused} reutilizados.", **values):
        return db.get(DiscoveryRun, run.id)
    run = db.get(DiscoveryRun, run.id)
    try:
        snapshot = await trigger_profiles(client, need)
        profiles_transition(db, run, "requesting", profiles_state="pending", profiles_snapshot_id=snapshot)
    except ProviderError as error:
        profiles_transition(db, run, "requesting", profiles_state="unknown" if isinstance(error, StartUnconfirmed) else "failed", profiles_message=error.message[:500])
    except (httpx.HTTPError, ValueError, TypeError):
        profiles_transition(db, run, "requesting", profiles_state="unknown", profiles_message="El inicio no se pudo confirmar; revisa Bright Data antes de reintentar.")
    return db.get(DiscoveryRun, run.id)


async def advance_profiles(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    if run.profiles_state not in PROFILES_ACTIVE:
        return run
    age = (now() - aware(run.profiles_updated_at)).total_seconds()
    if run.profiles_state == "requesting":
        if age > 30:
            profiles_transition(db, run, "requesting", profiles_state="unknown", profiles_message="El inicio quedó sin confirmar. Revisa Bright Data; no se repetirá automáticamente.")
        return db.get(DiscoveryRun, run.id)
    try:
        records = await snapshot_records(client, run.profiles_snapshot_id)
        if records is None:
            # El tope solo aplica mientras Bright Data siga trabajando; un trabajo listo se recoge aunque se consulte tarde.
            if age > setting_int("BRIGHT_DATA_JOB_TIMEOUT_SECONDS", 900, 30, 3600):
                profiles_transition(db, run, "pending", profiles_state="failed", profiles_message="La recolección excedió el tiempo configurado. No se inició otra extracción.")
            return db.get(DiscoveryRun, run.id)
        found = await store_profiles(db, client, records, run.profiles_requested)
        profiles_transition(db, run, "pending", profiles_state="ready",
                            profiles_message=f"{found} de {len(run.profiles_requested)} perfiles nuevos recibidos; el resto reutilizados.")
    except ProviderError as error:
        profiles_transition(db, run, "pending", profiles_state="failed", profiles_message=error.message[:500])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        profiles_transition(db, run, "pending", profiles_state="failed", profiles_message="No fue posible consultar o descargar el trabajo de Bright Data. No se reenvió la extracción.")
    return db.get(DiscoveryRun, run.id)
