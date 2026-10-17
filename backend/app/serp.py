"""Cliente de búsqueda en Google. Intercambiable: cualquier objeto con `search(...)` sirve como SerpClient.

Uso:
    client = BrightDataSerpClient.from_env()
    results = client.search('site:instagram.com "ia" empresarios', hl="es")
"""
import logging
import os
import time
from typing import Protocol
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

BRIGHTDATA_URL = "https://api.brightdata.com/request"
logger = logging.getLogger(__name__)


class SerpError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SerpResult(BaseModel):
    link: str
    title: str = ""
    description: str = ""
    rank: int


class SerpClient(Protocol):
    def search(self, query: str, *, hl: str | None = None, gl: str | None = None) -> list[SerpResult]: ...


def google_url(query: str, *, hl: str | None = None, gl: str | None = None) -> str:
    # hl solo cambia el idioma de la interfaz; lr=lang_xx restringe los resultados a páginas en ese idioma.
    # Sin `num`: Bright Data lo elimina (x-brd-serp-warn) y Google devuelve ~10 resultados por página.
    lr = f"lang_{hl}" if hl else None
    params = {"q": query, "brd_json": 1} | {k: v for k, v in {"hl": hl, "lr": lr, "gl": gl}.items() if v}
    return "https://www.google.com/search?" + urlencode(params)


def parse_organic(data: dict) -> list[SerpResult]:
    # Los docs muestran `rank` y `global_rank` según la versión; se aceptan ambos.
    results = []
    for position, item in enumerate(data.get("organic") or [], start=1):
        link = item.get("link") or item.get("url")
        if not link:
            continue
        rank = item.get("rank") or item.get("global_rank") or position
        results.append(SerpResult(link=link, title=item.get("title") or "", description=item.get("description") or item.get("snippet") or "", rank=int(rank)))
    return results


class BrightDataSerpClient:
    def __init__(self, api_key: str, zone: str, *, timeout: float = 60.0, attempts: int = 3, backoff: float = 1.5, http: httpx.Client | None = None):
        # strip() evita el "\r" invisible de un .env guardado con saltos de línea de Windows.
        self.api_key = api_key.strip()
        self.zone = zone.strip()
        self.attempts, self.backoff = attempts, backoff
        self.http = http or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls):
        key = os.getenv("BRIGHT_DATA_API_KEY", "").strip()
        zone = os.getenv("BRIGHT_DATA_SERP_ZONE", "").strip()
        if not key or not zone:
            raise SerpError("Configura BRIGHT_DATA_API_KEY y BRIGHT_DATA_SERP_ZONE en el entorno del backend.")
        return cls(key, zone)

    def close(self):
        self.http.close()

    def search(self, query: str, *, hl: str | None = None, gl: str | None = None) -> list[SerpResult]:
        body = {"zone": self.zone, "url": google_url(query, hl=hl, gl=gl), "format": "raw"}
        # Bright Data devuelve de forma intermitente cuerpos no JSON o 5xx; se reintenta con espera creciente.
        for attempt in range(1, self.attempts + 1):
            try:
                return self.request(body)
            except SerpError as error:
                retryable = error.status is None or error.status >= 500 or error.status == 200
                if attempt == self.attempts or not retryable:
                    raise
                logger.info("Bright Data intento %d/%d falló (%s); reintento en %.1fs", attempt, self.attempts, error, self.backoff * attempt)
                time.sleep(self.backoff * attempt)

    def request(self, body: dict) -> list[SerpResult]:
        try:
            response = self.http.post(BRIGHTDATA_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
        except httpx.HTTPError as error:
            raise SerpError(f"No se pudo contactar a Bright Data: {error}") from error
        detail = response.headers.get("x-brd-error") or response.text[:200]
        if response.status_code == 401:
            raise SerpError(f"Bright Data rechazó la API key (401). {detail}", 401)
        if response.status_code >= 400:
            raise SerpError(f"Bright Data respondió {response.status_code}: {detail}", response.status_code)
        try:
            data = response.json()
        except ValueError:
            sample = response.text[:120].replace("\n", " ")
            raise SerpError(f"Bright Data no devolvió JSON ({response.headers.get('content-type')}, {len(response.content)} bytes): {sample!r}", response.status_code)
        return parse_organic(data)
