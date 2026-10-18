"""Orquestación: plan de queries → búsquedas SERP → candidatos. Sin dependencias de API ni base de datos."""
import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from pydantic import BaseModel

from .creators import CreatorCandidate, HitOutcome, SearchHit, collect_candidates
from .post_resolver import PostResolver
from .query_builder import SITES, QueryPlan
from .serp import SerpClient, SerpError
from .services import normalize

COUNTRIES = {
    "mexico": "mx", "colombia": "co", "argentina": "ar", "chile": "cl", "peru": "pe", "ecuador": "ec",
    "venezuela": "ve", "uruguay": "uy", "paraguay": "py", "bolivia": "bo", "guatemala": "gt",
    "costa rica": "cr", "panama": "pa", "republica dominicana": "do", "espana": "es", "estados unidos": "us",
}
# Sin gl, Bright Data sale desde un país distinto en cada petición y los resultados varían entre corridas.
LATAM_REGIONS = {"latinoamerica", "latam", "america latina", "hispanoamerica", "iberoamerica"}
LATAM_COUNTRIES = ["co"]
# Si menos de esta fracción de resultados es del sitio pedido, Google ignoró `site:` y se usa la query de respaldo.
MIN_SITE_SHARE = 0.5
logger = logging.getLogger(__name__)


class QueryRun(BaseModel):
    query: str
    planned_query: str
    angle: str
    topic: str
    gl: str | None
    results: int
    fallback_used: bool = False
    error: str | None = None


class DiscoveryResult(BaseModel):
    hl: str
    queries: list[QueryRun]
    candidates: list[CreatorCandidate]
    outcomes: list[HitOutcome]
    discarded_results: int
    unresolved_posts: list[str]


def geo_targets(region: str, countries: list[str] | None = None) -> list[str | None]:
    """Países (gl) a consultar: los indicados, LATAM_COUNTRIES para Latinoamérica, el país de la región o, si no se reconoce, sin gl."""
    if countries:
        return list(dict.fromkeys(c.lower() for c in countries))
    key = normalize(region).strip()
    if key in LATAM_REGIONS:
        return list(LATAM_COUNTRIES)
    return [COUNTRIES.get(key)]


def site_share(results, site: str) -> float:
    hosts = [urlsplit(r.link).hostname or "" for r in results]
    return sum(h == site or h.endswith("." + site) for h in hosts) / len(hosts) if hosts else 0.0


def discover_creators(plan: QueryPlan, client: SerpClient, *, hl: str = "es", countries: list[str | None] | None = None, workers: int = 3, resolver: PostResolver | None = None) -> DiscoveryResult:
    jobs = [(idea, gl) for idea in plan.queries for gl in (countries or [None])]
    site = SITES[plan.platform]

    def run(job):
        idea, gl = job
        try:
            results = client.search(idea.query, hl=hl, gl=gl)
            if idea.fallback and site_share(results, site) < MIN_SITE_SHARE:
                logger.info("Google ignoró site: (%.0f%% del sitio); reintento sin filtros: %s", 100 * site_share(results, site), idea.fallback)
                return idea, gl, client.search(idea.fallback, hl=hl, gl=gl), True, None
            return idea, gl, results, False, None
        except SerpError as error:
            return idea, gl, [], False, str(error)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        responses = list(pool.map(run, jobs))
    runs, hits = [], []
    for idea, gl, results, fallback_used, error in responses:
        query = idea.fallback if fallback_used else idea.query
        if error:
            logger.warning("SERP falló gl=%s: %s | %s", gl, query, error)
        else:
            logger.info("SERP gl=%s → %d resultados: %s", gl, len(results), query)
        runs.append(QueryRun(query=query, planned_query=idea.query, angle=idea.angle, topic=idea.topic, gl=gl, results=len(results), fallback_used=fallback_used, error=error))
        # Si ni el respaldo respeta site:, los resultados ajenos se descartan después en collect_candidates.
        hits += [SearchHit(query=query, gl=gl, rank=r.rank, link=r.link, title=r.title, description=r.description) for r in results]
    candidates, outcomes = collect_candidates(hits, resolver)
    unresolved = list(dict.fromkeys(o.link for o in outcomes if o.outcome == "unresolved"))
    discarded = sum(o.outcome != "candidate" for o in outcomes)
    logger.info("Descubrimiento: %d candidatos, %d descartados, %d posts sin autor", len(candidates), discarded, len(unresolved))
    return DiscoveryResult(hl=hl, queries=runs, candidates=candidates, outcomes=outcomes, discarded_results=discarded, unresolved_posts=unresolved)
