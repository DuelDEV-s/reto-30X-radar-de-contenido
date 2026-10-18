"""Persistencia de corridas de búsqueda por tópico: queries, resultados y candidatos, en Instagram o TikTok.

Instagram busca en Google (SERP, inmediato); TikTok busca videos por palabra clave en Bright Data, un trabajo
asíncrono que se avanza con las consultas de la vista (etapa `search`). Desde ahí el flujo es el mismo: los
candidatos se enriquecen con su ficha de perfil (solo se piden a Bright Data las cuentas que no estén vigentes
en `instagram_accounts` o `tiktok_accounts`), el LLM revisa las cuentas y se recogen los posts de los que pasan.
"""
import os
from collections import Counter
from uuid import uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .account_review import brand_context, brand_handles, included, is_configured, review_dict, reviews_by_username
from .account_store import aware, now, snapshot_records
from . import account_store, content_patterns, post_metrics, post_review, post_store, tiktok_accounts, tiktok_posts, tiktok_search, topic_trends, transcription
from .brightdata import StartUnconfirmed, setting_int
from .database import Brand, DiscoveryCandidate, DiscoveryHit, DiscoveryQuery, DiscoveryRun, RunTopicMap
from .discovery import DiscoveryResult
from .profile_common import ProviderError
from .query_builder import QueryPlan

PROFILES_ACTIVE = {"requesting", "pending"}


def accounts_of(run: DiscoveryRun):
    """Módulo de perfiles de la red de la corrida: account_store (Instagram) o tiktok_accounts."""
    return tiktok_accounts if run.platform == "tiktok" else account_store


def posts_of(run: DiscoveryRun):
    """Módulo de posts de la red de la corrida: post_store (Instagram) o tiktok_posts."""
    return tiktok_posts if run.platform == "tiktok" else post_store


def missing_config(run: DiscoveryRun) -> list[str]:
    """Variables que faltan para las etapas de Bright Data. Los scrapers de TikTok tienen ID por defecto."""
    keys = ("BRIGHT_DATA_API_KEY",) if run.platform == "tiktok" else ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_INSTAGRAM_DATASET_ID")
    return [key for key in keys if not os.getenv(key)]


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


async def start_tiktok_search(db: Session, brand: Brand, plan: QueryPlan, client, *, topic: str | None, max_queries: int,
                              per_keyword: int) -> DiscoveryRun:
    """Crea la corrida de TikTok con sus palabras clave e inicia la búsqueda de videos en Bright Data.
    El POST se hace una sola vez: la corrida nace reservada (requesting) y solo esta llamada la avanza."""
    terms = tiktok_search.keywords(plan)
    run = DiscoveryRun(
        brand_id=brand.id, status="pending", topic=topic, platform="tiktok", hl="", countries=[], max_queries=max_queries,
        profiles_only=False, resolve_posts=False, identity=brand.identity, query_count=len(terms), result_count=0,
        candidate_count=0, discarded_count=0, unresolved_count=0, search_state="requesting", search_generation=str(uuid4()),
        search_message=f"{len(terms)} palabras clave, hasta {per_keyword} videos por palabra.", search_updated_at=now(),
    )
    db.add(run)
    db.flush()
    for position, (term, idea) in enumerate(terms):
        db.add(DiscoveryQuery(run_id=run.id, position=position, query=term, planned_query=idea.query, angle=idea.angle,
                              topic=idea.topic, gl=None, fallback_used=False, results_count=0))
    db.commit()
    try:
        snapshot = await tiktok_search.trigger_search(client, [term for term, _ in terms], per_keyword)
        stage_transition(db, run, "search", "requesting", state="pending", snapshot_id=snapshot)
    except ProviderError as error:
        search_failed(db, run, "requesting", "unknown" if isinstance(error, StartUnconfirmed) else "failed", error.message)
    except (httpx.HTTPError, ValueError, TypeError):
        search_failed(db, run, "requesting", "unknown", "El inicio no se pudo confirmar; revisa Bright Data antes de reintentar.")
    return db.get(DiscoveryRun, run.id)


def search_failed(db: Session, run: DiscoveryRun, expected: str, state: str, message: str) -> None:
    if stage_transition(db, run, "search", expected, state=state, message=message[:500]):
        db.execute(update(DiscoveryRun).where(DiscoveryRun.id == run.id).values(status="failed"))
        db.commit()


async def advance_search(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    """Consulta la búsqueda de videos en curso; cuando Bright Data termina, guarda videos, resultados y candidatos."""
    if run.search_state not in PROFILES_ACTIVE:
        return run
    age = (now() - aware(run.search_updated_at)).total_seconds()
    if run.search_state == "requesting":
        if age > 30:
            search_failed(db, run, "requesting", "unknown", "El inicio quedó sin confirmar. Revisa Bright Data; no se repetirá automáticamente.")
        return db.get(DiscoveryRun, run.id)
    try:
        records = await snapshot_records(client, run.search_snapshot_id)
        if records is None:
            # Buscar por palabra clave tarda bastante más que traer un perfil: tiene su propio tope.
            if age > tiktok_search.timeout_seconds():
                search_failed(db, run, "pending", "failed", "La búsqueda excedió el tiempo configurado. No se inició otra extracción.")
            return db.get(DiscoveryRun, run.id)
        message = save_search(db, run, records)
        stage_transition(db, run, "search", "pending", state="ready", message=message)
    except ProviderError as error:
        db.rollback()
        search_failed(db, run, "pending", "failed", error.message)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        db.rollback()
        search_failed(db, run, "pending", "failed", "No fue posible consultar o descargar la búsqueda de Bright Data. No se reenvió la extracción.")
    return db.get(DiscoveryRun, run.id)


def save_search(db: Session, run: DiscoveryRun, records: list) -> str:
    """Videos de la búsqueda → videos guardados, un resultado por video y palabra clave, y candidatos."""
    queries = {q.query: q for q in db.scalars(select(DiscoveryQuery).where(DiscoveryQuery.run_id == run.id)).all()}
    found, rows, ranks = [], {}, Counter()
    for record in records:
        values = tiktok_posts.normalize_post(record)
        if values is None:
            continue
        source = record.get("discovery_input") or record.get("input") or {}
        keyword = " ".join(str(source.get("search_keyword") or "").split()) if isinstance(source, dict) else ""
        # Sin la palabra clave en el registro solo se puede asignar si hubo una sola.
        query = queries.get(keyword) or (next(iter(queries.values())) if len(queries) == 1 else None)
        if query is None:
            continue
        ranks[query.query] += 1
        rows.setdefault(values["video_id"], values)
        found.append((query, tiktok_search.FoundVideo(keyword=query.query, rank=ranks[query.query], url=values["url"], author=values["author"],
                                                      followers=values["followers"], views=values["views"], posted_at=values["posted_at"])))
    tiktok_posts.save(db, list(rows.values()), now())
    brand = db.get(Brand, run.brand_id)
    candidates, outcomes = tiktok_search.select_candidates(
        [video for _, video in found], brand_handles=set(brand_handles(brand, "tiktok")), now=now(),
        min_followers=tiktok_posts.min_followers(), max_age_days=tiktok_search.max_video_age_days(), limit=tiktok_search.max_candidates())
    for (query, video), outcome in zip(found, outcomes):
        db.add(DiscoveryHit(run_id=run.id, query_id=query.id, rank=video.rank, link=video.url, outcome=outcome["outcome"],
                            username=outcome["username"], author_source="video", reason=outcome["reason"]))
    for candidate in candidates:
        db.add(DiscoveryCandidate(run_id=run.id, username=candidate["username"], query_hits=candidate["query_hits"], best_rank=candidate["best_rank"]))
    for query in queries.values():
        query.results_count = ranks[query.query]
    empty = sum(not ranks[q] for q in queries)
    run.status = "failed" if not found else "partial" if empty else "completed"
    run.result_count, run.candidate_count = len(found), len(candidates)
    run.discarded_count = sum(o["outcome"] == "discarded" for o in outcomes)
    db.commit()
    return (f"{len(rows)} videos de {len(queries)} palabras clave; {len(candidates)} candidatos"
            + (f"; {empty} palabras clave sin videos." if empty else "."))


def summary(run: DiscoveryRun) -> dict:
    return {
        "id": run.id, "brand_id": run.brand_id, "status": run.status, "created_at": run.created_at, "topic": run.topic,
        "platform": run.platform, "hl": run.hl, "countries": run.countries, "max_queries": run.max_queries,
        "profiles_only": run.profiles_only, "resolve_posts": run.resolve_posts,
        "totals": {"queries": run.query_count, "results": run.result_count, "candidates": run.candidate_count,
                   "discarded": run.discarded_count, "unresolved": run.unresolved_count},
        "search": {"state": run.search_state, "message": run.search_message, "updated_at": run.search_updated_at},
        "profiles": {"state": run.profiles_state, "message": run.profiles_message, "requested": len(run.profiles_requested or []),
                     "updated_at": run.profiles_updated_at},
        "posts": {"state": run.posts_state, "message": run.posts_message, "requested": len(run.posts_requested or []),
                  "updated_at": run.posts_updated_at},
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
    accounts = accounts_of(run)
    profiles = accounts.accounts_by_username(db, [c.username for c in candidates])
    reviews = reviews_by_username(db, run.brand_id, [c.username for c in candidates], run.platform)
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
        "candidates": [{**accounts.account_dict(c.username, profiles.get(c.username)),
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


def stage_transition(db: Session, run: DiscoveryRun, stage: str, expected: str, **values) -> bool:
    """Cambio condicional de una etapa (profiles o posts): solo quien gana la transición puede hacer el POST facturable."""
    generation, current = getattr(DiscoveryRun, f"{stage}_generation"), getattr(run, f"{stage}_generation")
    result = db.execute(update(DiscoveryRun).where(
        DiscoveryRun.id == run.id, getattr(DiscoveryRun, f"{stage}_state") == expected,
        generation.is_(None) if current is None else generation == current,
    ).values(**{f"{stage}_{k}": v for k, v in values.items()}, **{f"{stage}_updated_at": now()}))
    db.commit()
    db.expire_all()
    return result.rowcount == 1


def profiles_transition(db: Session, run: DiscoveryRun, expected: str, **values) -> bool:
    return stage_transition(db, run, "profiles", expected, **{k.removeprefix("profiles_"): v for k, v in values.items()})


async def start_profiles(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    if run.profiles_state in PROFILES_ACTIVE:
        return await advance_profiles(db, run, client)
    if run.platform == "tiktok" and run.search_state != "ready":
        raise ProviderError("La búsqueda de videos en TikTok aún no termina; los candidatos salen de ella.", code="search_not_ready")
    usernames = candidate_usernames(db, run)
    need = accounts_of(run).missing(db, usernames)
    reused = len(usernames) - len(need)
    values = {"profiles_generation": str(uuid4()), "profiles_snapshot_id": None, "profiles_requested": need}
    if not need:
        profiles_transition(db, run, run.profiles_state, profiles_state="ready", profiles_message=f"Sin costo: los {reused} perfiles ya estaban guardados.", **values)
        return db.get(DiscoveryRun, run.id)
    if not profiles_transition(db, run, run.profiles_state, profiles_state="requesting", profiles_message=f"{len(need)} perfiles nuevos; {reused} reutilizados.", **values):
        return db.get(DiscoveryRun, run.id)
    run = db.get(DiscoveryRun, run.id)
    try:
        snapshot = await accounts_of(run).trigger_profiles(client, need)
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
        found = await accounts_of(run).store_profiles(db, client, records, run.profiles_requested)
        profiles_transition(db, run, "pending", profiles_state="ready",
                            profiles_message=f"{found} de {len(run.profiles_requested)} perfiles nuevos recibidos; el resto reutilizados.")
    except ProviderError as error:
        profiles_transition(db, run, "pending", profiles_state="failed", profiles_message=error.message[:500])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        profiles_transition(db, run, "pending", profiles_state="failed", profiles_message="No fue posible consultar o descargar el trabajo de Bright Data. No se reenvió la extracción.")
    return db.get(DiscoveryRun, run.id)


def post_selection(db: Session, run: DiscoveryRun) -> tuple[list[str], list[str]]:
    """Creadores cuyos posts entran en la línea base y los que quedan fuera por tamaño.

    Entran los que pasan la revisión LLM o, sin revisor configurado, todos los perfiles públicos, con al menos
    INSTAGRAM_MIN_FOLLOWERS seguidores (sin dato de seguidores no se puede verificar y quedan fuera). Nunca
    cuentas privadas ni sin ficha. Con tope para acotar el costo."""
    usernames = candidate_usernames(db, run)
    accounts = accounts_of(run).accounts_by_username(db, usernames)
    reviews = reviews_by_username(db, run.brand_id, usernames, run.platform) if is_configured() else {}
    eligible = [u for u in usernames if accounts.get(u) and accounts[u].raw is not None and accounts[u].fetch_status == "ok"
                and (included(reviews.get(u)) if is_configured() else True)]
    store = posts_of(run)
    minimum = store.min_followers()
    small = [u for u in eligible if (accounts[u].followers or 0) < minimum]
    return [u for u in eligible if u not in small][:store.max_creators()], small


def post_creators(db: Session, run: DiscoveryRun) -> list[str]:
    return post_selection(db, run)[0]


async def start_posts(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    if run.posts_state in PROFILES_ACTIVE:
        return await advance_posts(db, run, client)
    if run.profiles_state != "ready":
        raise ProviderError("Primero trae los perfiles de los candidatos.", code="profiles_not_ready")
    creators = post_creators(db, run)
    if not creators:
        raise ProviderError(f"Ningún candidato pasa al análisis: revisa los perfiles, la revisión LLM y el mínimo de {posts_of(run).min_followers()} seguidores.", code="no_creators")
    need = posts_of(run).stale(db, creators)
    reused = len(creators) - len(need)
    values = {"generation": str(uuid4()), "snapshot_id": None, "requested": need}
    if not need:
        stage_transition(db, run, "posts", run.posts_state, state="ready", message=f"Sin costo: los posts de los {reused} creadores ya estaban recogidos.", **values)
        return db.get(DiscoveryRun, run.id)
    if not stage_transition(db, run, "posts", run.posts_state, state="requesting", message=f"{len(need)} creadores nuevos; {reused} reutilizados.", **values):
        return db.get(DiscoveryRun, run.id)
    run = db.get(DiscoveryRun, run.id)
    try:
        snapshot = await posts_of(run).trigger_posts(client, need)
        stage_transition(db, run, "posts", "requesting", state="pending", snapshot_id=snapshot)
    except ProviderError as error:
        stage_transition(db, run, "posts", "requesting", state="unknown" if isinstance(error, StartUnconfirmed) else "failed", message=error.message[:500])
    except (httpx.HTTPError, ValueError, TypeError):
        stage_transition(db, run, "posts", "requesting", state="unknown", message="El inicio no se pudo confirmar; revisa Bright Data antes de reintentar.")
    return db.get(DiscoveryRun, run.id)


async def advance_posts(db: Session, run: DiscoveryRun, client) -> DiscoveryRun:
    if run.posts_state not in PROFILES_ACTIVE:
        return run
    age = (now() - aware(run.posts_updated_at)).total_seconds()
    if run.posts_state == "requesting":
        if age > 30:
            stage_transition(db, run, "posts", "requesting", state="unknown", message="El inicio quedó sin confirmar. Revisa Bright Data; no se repetirá automáticamente.")
        return db.get(DiscoveryRun, run.id)
    try:
        records = await snapshot_records(client, run.posts_snapshot_id)
        if records is None:
            # En TikTok, recoger los videos de varios perfiles tarda más que el tope general: tiene el suyo.
            limit = tiktok_posts.timeout_seconds() if run.platform == "tiktok" else setting_int("BRIGHT_DATA_JOB_TIMEOUT_SECONDS", 900, 30, 3600)
            if age > limit:
                stage_transition(db, run, "posts", "pending", state="failed", message="La recolección excedió el tiempo configurado. No se inició otra extracción.")
            return db.get(DiscoveryRun, run.id)
        found = posts_of(run).store_posts(db, records, run.posts_requested)
        stage_transition(db, run, "posts", "pending", state="ready",
                         message=f"{found} posts recibidos de {len(run.posts_requested)} creadores; el resto reutilizados.")
    except ProviderError as error:
        stage_transition(db, run, "posts", "pending", state="failed", message=error.message[:500])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        stage_transition(db, run, "posts", "pending", state="failed", message="No fue posible consultar o descargar el trabajo de Bright Data. No se reenvió la extracción.")
    return db.get(DiscoveryRun, run.id)


def run_topic(run: DiscoveryRun) -> str:
    """Tópico contra el que se juzgan los posts: el de la búsqueda o, sin tópico, los de la identidad usada."""
    return run.topic or ", ".join(run.identity.get("topics") or []) or "temas de la marca"


async def review_run_posts(db: Session, run: DiscoveryRun, reviewer) -> int:
    """Una tanda de revisiones de relevancia de los posts de la corrida."""
    if run.posts_state != "ready":
        return 0
    brand = brand_context(db.get(Brand, run.brand_id), run.platform)
    return await post_review.review_posts(db, posts_of(run).recent_posts(db, post_creators(db, run)), run_topic(run), brand, reviewer)


async def transcribe_run(db: Session, run: DiscoveryRun, transcriber, client) -> int:
    """Una tanda de transcripciones, solo de los reels que la revisión marcó relevantes o indeterminados.
    Sin revisión todavía no se transcribe nada: lo que está fuera de tema no se paga."""
    if run.posts_state != "ready":
        return 0
    posts = posts_of(run).recent_posts(db, post_creators(db, run))
    reviews = post_review.reviews_by_shortcode(db, [p.shortcode for p in posts], run_topic(run), run.platform)
    wanted = [p for p in posts if post_review.wants_transcript(reviews.get(p.shortcode), p)]
    return await transcription.transcribe_posts(db, wanted, transcriber, client)


def post_dict(post, score: dict, velocity: dict | None, review) -> dict:
    # Campos que solo existen en una de las dos redes quedan en None o vacíos en la otra.
    extra = lambda key, default=None: getattr(post, key, default)
    from .media import stored_thumbnail
    return {
        "shortcode": post.shortcode, "url": post.url, "username": post.username, "author": post.author,
        "thumbnail_url": stored_thumbnail(post.raw, post.PLATFORM),
        "content_type": post.content_type, "caption": (post.caption or "")[:500], "hashtags": post.hashtags,
        "posted_at": post.posted_at, "observed_at": post.observed_at, "likes": post.likes, "comments": post.comments,
        "views": post.views, "plays": extra("plays"), "shares": extra("shares"), "saves": extra("saves"),
        "duration_seconds": post.duration_seconds, "is_paid_partnership": extra("is_paid_partnership"),
        "is_pinned": extra("is_pinned"), "coauthors": extra("coauthors", []), "audio": post.audio, "velocity": velocity, "transcript": post.transcript, "transcript_status": post.transcript_status,
        "transcript_seconds": post.transcript_seconds, **post_review.review_dict(review), **score,
    }


def scored(db: Session, run: DiscoveryRun):
    """Posts de la corrida con su rendimiento y su veredicto de relevancia: base de posts, tendencias y patrones."""
    creators, small = post_selection(db, run)
    store = posts_of(run)
    accounts = accounts_of(run).accounts_by_username(db, creators + small)
    rows = store.recent_posts(db, creators)
    samples = [store.sample(p, accounts[p.username].followers) for p in rows]
    scores, baselines = post_metrics.analyze(samples, store.POSTS_WINDOW_DAYS)
    reviews = post_review.reviews_by_shortcode(db, [p.shortcode for p in rows], run_topic(run), run.platform)
    return creators, small, accounts, rows, scores, baselines, reviews


def posts_detail(db: Session, run: DiscoveryRun) -> dict:
    """Línea base de cada creador y posts ordenados por rendimiento frente a esa línea base."""
    creators, small, accounts, rows, scores, baselines, reviews = scored(db, run)
    store = posts_of(run)
    readings = store.observations(db, [p.shortcode for p in rows])
    topic = run_topic(run)
    posts = sorted((post_dict(p, scores[p.shortcode], post_metrics.velocity(readings.get(p.shortcode, [])), reviews.get(p.shortcode)) for p in rows),
                   key=lambda p: (p["performance"] is None, -(p["performance"] or 0), p["shortcode"]))
    return {
        **summary(run),
        "window_days": store.POSTS_WINDOW_DAYS, "posts_per_creator": store.POSTS_PER_CREATOR,
        "method": post_metrics.method(run.platform),
        "creators": [{**accounts_of(run).account_dict(u, accounts.get(u)), "posts_fetched_at": accounts[u].posts_fetched_at if u in accounts else None,
                      "baseline": baselines.get(u)} for u in creators],
        "topic": topic,
        "topic_review": post_review.progress(rows, reviews, is_configured()),
        # Solo cuentan los reels que la revisión manda a transcribir; el resto no se transcribe.
        "transcripts": transcription.progress([p for p in rows if post_review.wants_transcript(reviews.get(p.shortcode), p)
                                               or p.transcript_status is not None]),
        "min_followers": store.min_followers(),
        "excluded_small": [{"username": u, "followers": accounts[u].followers} for u in small],
        "items": posts,
    }


def trend_inputs(rows, scores, reviews) -> list[dict]:
    """Posts sobre el tópico con rendimiento: los únicos que cuentan para tendencias."""
    items = []
    for post in rows:
        review, score = reviews.get(post.shortcode), scores[post.shortcode]
        if not review or review.relevance not in post_review.ON_TOPIC or score["performance"] is None:
            continue
        items.append({"shortcode": post.shortcode, "username": post.username, "posted_at": aware(post.posted_at),
                      "performance": score["performance"], "label": score["label"], "subtopics": review.subtopics,
                      "url": post.url, "caption": (post.caption or "")[:200], "content_type": post.content_type})
    return items


async def trends_detail(db: Session, run: DiscoveryRun, grouper) -> dict:
    """Tópicos en caliente, emergentes, saturados… y su matriz por semana. Unifica los subtemas si hace falta."""
    _, _, _, rows, scores, _, reviews = scored(db, run)
    pending = post_review.progress(rows, reviews, is_configured())["pending"]
    items = trend_inputs(rows, scores, reviews)
    labels = Counter(s for p in items for s in p["subtopics"])
    topic = run_topic(run)
    stored = db.get(RunTopicMap, run.id)
    wanted = topic_trends.labels_digest(topic, labels)
    # Con revisiones pendientes los subtemas aún cambian: se espera a que terminen para no unificar dos veces.
    if labels and grouper and pending == 0 and (stored is None or stored.labels_digest != wanted):
        topics = await topic_trends.group_labels(grouper, topic, dict(labels))
        if topics:
            stored = stored or RunTopicMap(run_id=run.id)
            stored.labels_digest, stored.topics, stored.model, stored.created_at = wanted, topics, grouper.model, now()
            db.add(stored)
            db.commit()
    base = {**summary(run), "topic": topic, "reviews_pending": pending, "grouping_enabled": grouper is not None}
    if stored is None or not items:
        return {**base, "state": "waiting" if pending or not stored else "ready", "weeks": [], "topics": [], "stale": False}
    reference = max((aware(p.observed_at) for p in rows), default=now())
    result = topic_trends.analyze(items, stored.topics, reference, posts_of(run).POSTS_WINDOW_DAYS, run.platform)
    formats = content_formats(db, run.platform, result["topics"])
    for item in result["topics"]:
        item["production"] = formats.get(item["name"])
    return {**base, "state": "ready", "stale": stored.labels_digest != wanted, "grouped_at": stored.created_at, **result}


def content_formats(db: Session, platform: str, topics: list[dict]) -> dict[str, dict]:
    """Cruce en la presentación: formato dominante de los posts más fuertes de cada tópico, si ya se analizaron."""
    codes = [e["shortcode"] for t in topics for e in t["evidence"]]
    analyses = {code: a.features for code, a in content_patterns.analyses(db, platform, codes).items() if a.status == "ok"}
    result = {}
    for topic in topics:
        features = [analyses[e["shortcode"]] for e in topic["evidence"] if e["shortcode"] in analyses]
        if features:
            result[topic["name"]] = {"analyzed": len(features), **{trait: Counter(f[trait] for f in features).most_common(1)[0][0]
                                                                    for trait in ("formato", "encuadre", "musica", "texto_en_pantalla", "gancho_tipo")}}
    return result


def pattern_targets(rows, scores, reviews) -> tuple[list[str], list[str]]:
    posts = [{"shortcode": p.shortcode, "username": p.username, "content_type": p.content_type,
              "label": scores[p.shortcode]["label"], "performance": scores[p.shortcode]["performance"] or 0,
              "on_topic": bool(reviews.get(p.shortcode) and reviews[p.shortcode].relevance in post_review.ON_TOPIC)} for p in rows]
    return content_patterns.select(posts)


async def analyze_run_content(db: Session, run: DiscoveryRun, analyzer, client) -> int:
    """Una tanda de análisis de video. Espera a que termine la revisión de relevancia: define la muestra.
    No aplica a TikTok: su CDN no deja descargar el video sin sesión."""
    if run.posts_state != "ready" or run.platform == "tiktok":
        return 0
    _, _, _, rows, scores, _, reviews = scored(db, run)
    if post_review.progress(rows, reviews, is_configured())["pending"]:
        return 0
    top, control = pattern_targets(rows, scores, reviews)
    by_code = {p.shortcode: p for p in rows}
    # Destacados primero: si los enlaces vencen a mitad, lo más valioso ya quedó analizado.
    return await content_patterns.analyze_posts(db, [by_code[c] for c in top + control], analyzer, client)


def patterns_detail(db: Session, run: DiscoveryRun) -> dict:
    _, _, _, rows, scores, _, reviews = scored(db, run)
    pending_reviews = post_review.progress(rows, reviews, is_configured())["pending"]
    top, control = pattern_targets(rows, scores, reviews)
    analyses = content_patterns.analyses(db, run.platform, top + control) if top else {}
    ok = lambda codes: [analyses[c].features for c in codes if c in analyses and analyses[c].status == "ok"]
    by_code = {p.shortcode: p for p in rows}
    statuses = [analyses[c].status if c in analyses else None for c in top + control]
    expiries = [e for e in (transcription.expires_at(u) for u in (transcription.video_url(by_code[c]) for c in top + control
                                                                    if (analyses.get(c) is None or analyses[c].status not in content_patterns.FINAL)) if u) if e]
    item = lambda c, group: {"shortcode": c, "group": group, "url": by_code[c].url, "username": by_code[c].username,
                             "performance": scores[c]["performance"], "label": scores[c]["label"],
                             "status": analyses[c].status if c in analyses else None,
                             "features": analyses[c].features if c in analyses else None,
                             "seconds": analyses[c].seconds if c in analyses else None}
    return {
        **summary(run),
        "enabled": content_patterns.is_configured(), "clip_seconds": content_patterns.clip_seconds(),
        "reviews_pending": pending_reviews,
        "progress": {"targets": len(top) + len(control), "done": sum(s == "ok" for s in statuses),
                     "pending": sum(s not in content_patterns.FINAL for s in statuses),
                     "failed": sum(s in content_patterns.FINAL - {"ok"} for s in statuses),
                     "expires_at": min(expiries) if expiries else None},
        "groups": {"top": len(ok(top)), "control": len(ok(control))},
        **content_patterns.contrast(ok(top), ok(control)),
        "items": [item(c, "top") for c in top] + [item(c, "control") for c in control],
    }
