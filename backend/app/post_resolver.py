"""Resolución del autor de un post de Instagram cuando la URL no incluye el usuario (/p/código, /reel/código).

Uso:
    resolver = OEmbedResolver()
    author = resolver.resolve("https://www.instagram.com/reel/DemK_I4FH49/")  # PostAuthor | None

Usa el oEmbed público de Instagram (sin token). No es una API oficial con garantías: se limita el ritmo,
se cachea por código de post y ante un 429 se deja de consultar durante el resto de la corrida.
"""
import logging
import re
import time
from typing import Protocol

import httpx
from pydantic import BaseModel

OEMBED_URL = "https://www.instagram.com/api/v1/oembed/"
SHORTCODE = re.compile(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
logger = logging.getLogger(__name__)


class PostAuthor(BaseModel):
    username: str
    author_id: str | None = None
    caption: str = ""


class PostResolver(Protocol):
    def resolve(self, url: str) -> PostAuthor | None: ...


def shortcode(url: str) -> str | None:
    match = SHORTCODE.search(url)
    return match.group(1) if match else None


class OEmbedResolver:
    def __init__(self, *, delay: float = 0.5, max_requests: int = 60, timeout: float = 10.0, http: httpx.Client | None = None):
        self.delay, self.max_requests = delay, max_requests
        self.http = http or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self.cache: dict[str, PostAuthor | None] = {}
        self.requests = 0
        self.blocked = False

    def close(self):
        self.http.close()

    def resolve(self, url: str) -> PostAuthor | None:
        code = shortcode(url)
        if not code:
            return None
        if code in self.cache:
            return self.cache[code]
        if self.blocked:
            return None
        if self.requests >= self.max_requests:
            if self.requests == self.max_requests:
                logger.warning("oEmbed alcanzó el máximo de %d consultas por corrida; el resto de posts queda pendiente", self.max_requests)
                self.requests += 1  # avisa una sola vez
            return None
        if self.requests:
            time.sleep(self.delay)
        self.requests += 1
        author = self.fetch(code, f"https://www.instagram.com{SHORTCODE.search(url).group(0)}/")
        self.cache[code] = author
        return author

    def fetch(self, code: str, post_url: str) -> PostAuthor | None:
        try:
            response = self.http.get(OEMBED_URL, params={"url": post_url})
        except httpx.HTTPError as error:
            logger.warning("oEmbed sin conexión para %s: %s", code, error)
            return None
        if response.status_code == 429:
            self.blocked = True
            logger.warning("oEmbed limitado por Instagram (429); el resto de posts queda pendiente")
            return None
        if response.status_code != 200:
            logger.info("oEmbed %s para %s", response.status_code, code)
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        username = (data.get("author_name") or "").strip().lower()
        if not username:
            return None
        author_id = data.get("author_id")
        return PostAuthor(username=username, author_id=str(author_id) if author_id else None, caption=data.get("title") or "")
