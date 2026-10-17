"""Extracción de perfiles de Instagram a partir de resultados de búsqueda. Funciones puras.

Solo descubrimiento: quién aparece y en qué resultado. El texto de Google se usa únicamente para
encontrar el @usuario y no se conserva; seguidores, contenido o tipo de cuenta se obtienen en una etapa
posterior con datos del perfil.
"""
import logging
import re
from urllib.parse import urlsplit

from pydantic import BaseModel

from .post_resolver import PostResolver

INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
CONTENT_PATHS = {"p", "reel", "reels", "tv"}
RESERVED_PATHS = CONTENT_PATHS | {"explore", "stories", "accounts", "about", "legal", "direct", "tags", "locations", "developer", "web", "challenge", "privacy", "api", "popular"}
USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")
HANDLE = re.compile(r"@([A-Za-z0-9._]{1,30})")
logger = logging.getLogger(__name__)


class SearchHit(BaseModel):
    """Resultado de búsqueda de entrada. title y description solo sirven para extraer el usuario."""
    query: str
    rank: int
    link: str
    title: str = ""
    description: str = ""


class Source(BaseModel):
    query: str
    link: str
    rank: int


class CreatorCandidate(BaseModel):
    username: str
    profile_url: str
    query_hits: int
    best_rank: int
    sources: list[Source]


def extract_username(link: str, title: str = "", description: str = "") -> str | None:
    url = urlsplit(link)
    if url.hostname not in INSTAGRAM_HOSTS:
        return None
    parts = [p for p in url.path.split("/") if p]
    if not parts:
        return None
    first = parts[0].lower()
    if first not in RESERVED_PATHS:
        return first if USERNAME.match(first) else None
    if first in CONTENT_PATHS:
        # Posts y reels no llevan el usuario en la URL; Google suele mostrarlo como (@usuario).
        match = HANDLE.search(f"{title} {description}")
        if match:
            return match.group(1).lower().rstrip(".")
    return None


def discard_reason(link: str) -> str:
    """Motivo legible por el que extract_username no obtuvo un perfil."""
    url = urlsplit(link)
    if url.hostname not in INSTAGRAM_HOSTS:
        return "otro dominio"
    first = next((p for p in url.path.split("/") if p), "").lower()
    if first in CONTENT_PATHS:
        return "post/reel sin @usuario en título o descripción"
    if not first or first in RESERVED_PATHS:
        return "ruta que no es perfil"
    return "usuario no válido"


def collect_candidates(hits: list[SearchHit], resolver: PostResolver | None = None) -> tuple[list[CreatorCandidate], int, list[str]]:
    """Agrupa resultados por usuario. Los posts sin usuario en la SERP se resuelven con `resolver` si se indica.

    Devuelve los candidatos, cuántos resultados se descartaron y los posts que quedaron sin autor.
    """
    groups: dict[str, list[SearchHit]] = {}
    discarded, unresolved = 0, []
    for item in hits:
        username = extract_username(item.link, item.title, item.description)
        reason = None if username else discard_reason(item.link)
        if not username and resolver and reason.startswith("post/reel"):
            author = resolver.resolve(item.link)
            username = author.username if author else None
        if not username:
            discarded += 1
            if reason.startswith("post/reel"):
                unresolved.append(item.link)
            logger.info("Descartado (%s): %s | %s | query=%s", reason, item.link, item.title, item.query)
            continue
        groups.setdefault(username, []).append(item)
    candidates = []
    for username, items in groups.items():
        candidates.append(CreatorCandidate(
            username=username, profile_url=f"https://www.instagram.com/{username}",
            query_hits=len({i.query for i in items}), best_rank=min(i.rank for i in items),
            sources=[Source(query=i.query, link=i.link, rank=i.rank) for i in items],
        ))
    candidates.sort(key=lambda c: (-c.query_hits, c.best_rank, c.username))
    return candidates, discarded, list(dict.fromkeys(unresolved))
