"""Búsqueda de creadores de TikTok por tópico, directamente en Bright Data (discover by keyword).

En Instagram los creadores salen de Google (SERP); en TikTok el propio scraper de posts busca videos por
palabra clave y cada video trae a su autor y sus métricas. El riesgo es otro: cualquier video viral suelto
aparece en la búsqueda. Por eso un autor solo pasa a candidato si:

- no es una cuenta de la marca,
- no está por debajo de TIKTOK_MIN_FOLLOWERS (cuando el video trae los seguidores del autor),
- publicó algo en los últimos TIKTOK_MAX_VIDEO_AGE_DAYS (un autor que solo aparece con videos viejos
  ya no es una referencia de lo que funciona hoy),

y se ordenan primero los que aparecen en más palabras clave distintas (constancia en el tema), luego por
videos encontrados, vistas medianas y mejor posición. Solo los TIKTOK_MAX_CANDIDATES primeros pasan a la
etapa de perfiles, que es la que se paga por cuenta; el veredicto del LLM y la línea base filtran después.

Funciones puras salvo `trigger_search`; la persistencia de la corrida vive en `discovery_store`.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .account_store import trigger
from .brightdata import setting_int
from .query_builder import QueryIdea, QueryPlan
from .tiktok_posts import posts_dataset


@dataclass
class FoundVideo:
    keyword: str
    rank: int
    url: str
    author: str | None
    followers: int | None
    views: int | None
    posted_at: datetime | None


def videos_per_keyword() -> int:
    return setting_int("TIKTOK_VIDEOS_PER_KEYWORD", 20, 5, 100)


def max_candidates() -> int:
    return setting_int("TIKTOK_MAX_CANDIDATES", 20, 1, 100)


def max_video_age_days() -> int:
    return setting_int("TIKTOK_MAX_VIDEO_AGE_DAYS", 180, 7, 3650)


def timeout_seconds() -> int:
    return setting_int("TIKTOK_SEARCH_TIMEOUT_SECONDS", 2700, 300, 7200)


def keywords(plan: QueryPlan) -> list[tuple[str, QueryIdea]]:
    """Palabras clave de TikTok a partir del plan de búsqueda, con la idea de la que salen: los mismos términos
    que en Google, sin operadores ni comillas (la búsqueda de TikTok no los interpreta)."""
    found: dict[str, QueryIdea] = {}
    for idea in plan.queries:
        term = " ".join(idea.keywords.replace('"', " ").split())
        if term:
            found.setdefault(term, idea)
    return list(found.items())


async def trigger_search(client, terms: list[str], per_keyword: int) -> str:
    inputs = [{"search_keyword": term, "num_of_posts": per_keyword} for term in terms]
    return await trigger(client, posts_dataset(), inputs, type="discover_new", discover_by="keyword", limit_per_input=per_keyword)


def select_candidates(videos: list[FoundVideo], *, brand_handles: set[str], now: datetime, min_followers: int,
                      max_age_days: int, limit: int) -> tuple[list[dict], list[dict]]:
    """(candidatos, desenlace de cada video en el orden recibido).

    Candidato: {username, query_hits, best_rank, videos, median_views}. Desenlace: {outcome, username, reason}
    con outcome candidate o discarded."""
    by_author: dict[str, list[FoundVideo]] = {}
    reasons: dict[int, str] = {}
    for index, video in enumerate(videos):
        if not video.author:
            reasons[index] = "video sin autor identificable"
        elif video.author in brand_handles:
            reasons[index] = "cuenta de la marca"
        else:
            by_author.setdefault(video.author, []).append(video)
    excluded: dict[str, str] = {}
    oldest = now - timedelta(days=max_age_days)
    for author, items in by_author.items():
        followers = max((v.followers for v in items if v.followers is not None), default=None)
        newest = max((v.posted_at for v in items if v.posted_at), default=None)
        if followers is not None and followers < min_followers:
            excluded[author] = f"menos de {min_followers} seguidores"
        elif newest is None or newest < oldest:
            excluded[author] = f"solo videos de hace más de {max_age_days} días"
    ranked = []
    for author, items in by_author.items():
        if author in excluded:
            continue
        views = [v.views for v in items if v.views is not None]
        ranked.append({"username": author, "query_hits": len({v.keyword for v in items}), "best_rank": min(v.rank for v in items),
                       "videos": len(items), "median_views": round(median(views)) if views else None})
    ranked.sort(key=lambda c: (-c["query_hits"], -c["videos"], -(c["median_views"] or 0), c["best_rank"], c["username"]))
    candidates = ranked[:limit]
    for extra in ranked[limit:]:
        excluded[extra["username"]] = f"fuera del tope de {limit} candidatos"
    outcomes = []
    for index, video in enumerate(videos):
        reason = reasons.get(index) or excluded.get(video.author)
        outcomes.append({"outcome": "discarded" if reason else "candidate", "username": video.author, "reason": reason})
    return candidates, outcomes
