"""Transcripción de reels con OpenAI para saber de qué hablan, más allá del caption.

Por reel: se descarga el MP4 del CDN de Instagram, se extraen los primeros TRANSCRIPT_MAX_SECONDS (30 s) de
la pista de audio sin recodificar (M4A, menos de 1 MB frente a 6–35 MB del video) y se envían a OpenAI. Todos
los reels se cortan igual: el inicio lleva el gancho y el planteamiento del tema, y así virales y normales
se comparan sobre el mismo tramo. El video no se guarda; solo el texto.

Los enlaces del CDN caducan (parámetro `oe`, ~1–2 días después de la recolección): la transcripción corre
justo después de recoger los posts y un enlace vencido se marca como tal sin descargar nada.

Se procesa por tandas en cada consulta de la vista, como la revisión LLM de cuentas. Cada reel se reserva
con una transición condicional para que dos consultas simultáneas no lo paguen dos veces.
"""
import asyncio
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import av
import httpx
import openai
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from .account_store import aware, now
from .database import InstagramPost

logger = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 100_000_000
BATCH = 6
CONCURRENCY = 3
# Una reserva que no terminó (proceso caído a mitad) se puede retomar pasado este tiempo.
STALE_CLAIM = timedelta(minutes=10)
VIDEO_TYPES = {"reel", "video"}
# Fallos que no cambian al reintentar; los transitorios (cuota, red) dejan el reel pendiente.
FINAL = {"ok", "no_speech", "no_audio", "expired", "too_large", "unavailable", "error"}


class Transcriber(Protocol):
    model: str

    async def transcribe(self, audio_path: str) -> str: ...


def max_seconds() -> int:
    return int(os.getenv("TRANSCRIPT_MAX_SECONDS", "30") or 30)


def is_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


class OpenAITranscriber:
    def __init__(self, client=None, model: str | None = None):
        self.client = client or openai.AsyncOpenAI(timeout=120.0, max_retries=2)
        self.model = model or os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

    async def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as audio:
            result = await self.client.audio.transcriptions.create(model=self.model, file=audio, response_format="text")
        return result if isinstance(result, str) else getattr(result, "text", "") or ""


def video_url(post: InstagramPost) -> str | None:
    raw = post.raw or {}
    for value in raw.get("videos") or []:
        url = value if isinstance(value, str) else value.get("url") if isinstance(value, dict) else None
        if isinstance(url, str) and url.startswith("https://"):
            return url
    for item in raw.get("post_content") or []:
        if isinstance(item, dict) and item.get("type") == "Video" and str(item.get("url", "")).startswith("https://"):
            return item["url"]
    return raw.get("video_url") if str(raw.get("video_url", "")).startswith("https://") else None


def expires_at(url: str) -> datetime | None:
    """Vencimiento firmado por el CDN de Instagram: `oe` es un timestamp Unix en hexadecimal."""
    try:
        return datetime.fromtimestamp(int(parse_qs(urlsplit(url).query)["oe"][0], 16), timezone.utc)
    except (KeyError, IndexError, ValueError, OverflowError):
        return None


async def download(client: httpx.AsyncClient, url: str, path: str) -> str | None:
    """Descarga el video a `path`. Devuelve un estado final si no se pudo, o None si quedó descargado."""
    async with client.stream("GET", url, timeout=httpx.Timeout(60, connect=10)) as response:
        if response.status_code in (403, 404, 410):
            return "unavailable"
        response.raise_for_status()
        if int(response.headers.get("content-length") or 0) > MAX_VIDEO_BYTES:
            return "too_large"
        size = 0
        with open(path, "wb") as file:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    return "too_large"
                file.write(chunk)
    return None


def extract_audio(video_path: str, audio_path: str, seconds: float) -> float | None:
    """Copia los primeros `seconds` de la primera pista de audio a un M4A sin recodificar.

    Devuelve los segundos copiados, o None si el video no tiene audio."""
    with av.open(video_path) as source:
        stream = next((s for s in source.streams if s.type == "audio"), None)
        if stream is None:
            return None
        start, copied = None, 0.0
        with av.open(audio_path, "w", format="mp4") as target:
            output = target.add_stream_from_template(stream)
            for packet in source.demux(stream):
                if packet.dts is None or packet.pts is None:
                    continue
                at = float(packet.pts * stream.time_base)
                start = at if start is None else start
                if at - start >= seconds:
                    break
                copied = at - start + float((packet.duration or 0) * stream.time_base)
                packet.stream = output
                target.mux(packet)
    return round(copied, 1) if copied else None


def claim(db: Session, post: InstagramPost) -> bool:
    stale = now() - STALE_CLAIM
    result = db.execute(update(InstagramPost).where(
        InstagramPost.shortcode == post.shortcode,
        or_(InstagramPost.transcript_status.is_(None),
            (InstagramPost.transcript_status == "processing") & (InstagramPost.transcribed_at < stale)),
    ).values(transcript_status="processing", transcribed_at=now()).execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount == 1


def finish(db: Session, shortcode: str, status: str | None, text: str | None, seconds: float | None, model: str | None) -> None:
    db.execute(update(InstagramPost).where(InstagramPost.shortcode == shortcode).values(
        transcript_status=status, transcript=text, transcript_seconds=seconds, transcript_model=model, transcribed_at=now(),
    ).execution_options(synchronize_session=False))
    db.commit()


async def process(client: httpx.AsyncClient, transcriber: Transcriber, post: InstagramPost) -> tuple[str | None, str | None, float | None]:
    """(estado, texto, segundos transcritos) de un reel. Estado None: fallo transitorio, se reintenta después."""
    url = video_url(post)
    if url is None:
        return "unavailable", None, None
    expiry = expires_at(url)
    if expiry and expiry <= now():
        return "expired", None, None
    with tempfile.TemporaryDirectory() as folder:
        video, audio = os.path.join(folder, "reel.mp4"), os.path.join(folder, "audio.m4a")
        try:
            failure = await download(client, url, video)
        except httpx.HTTPError:
            return None, None, None
        if failure:
            return failure, None, None
        try:
            seconds = await asyncio.to_thread(extract_audio, video, audio, max_seconds())
        except av.error.FFmpegError:
            return "error", None, None
        if seconds is None:
            return "no_audio", None, None
        try:
            text = (await transcriber.transcribe(audio)).strip()
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError):
            return None, None, None
        except openai.APIError as error:
            logger.warning("Transcripción falló para %s: %s", post.shortcode, type(error).__name__)
            return "error", None, None
    return ("ok", text, seconds) if text else ("no_speech", None, seconds)


async def transcribe_posts(db: Session, posts: list[InstagramPost], transcriber: Transcriber, client: httpx.AsyncClient,
                           limit: int = BATCH) -> int:
    """Transcribe como mucho `limit` reels pendientes de `posts`. Devuelve cuántos terminaron."""
    # Lo que otra consulta tiene reservado se salta: no bloquea la cola.
    pending = [p for p in posts if p.content_type in VIDEO_TYPES and p.transcript_status not in FINAL | {"processing"}]
    pending.sort(key=lambda p: aware(p.posted_at), reverse=True)
    claimed = []
    for post in pending:
        if len(claimed) == limit:
            break
        if claim(db, post):
            claimed.append(post)
    if not claimed:
        return 0
    slots = asyncio.Semaphore(CONCURRENCY)

    async def one(post):
        async with slots:
            return await process(client, transcriber, post)

    try:
        results = await asyncio.gather(*(one(p) for p in claimed))
    except BaseException:
        # Petición cancelada (el cliente cerró la conexión) o error inesperado: se liberan las reservas.
        db.rollback()
        db.execute(update(InstagramPost).where(InstagramPost.shortcode.in_([p.shortcode for p in claimed]), InstagramPost.transcript_status == "processing")
                   .values(transcript_status=None).execution_options(synchronize_session=False))
        db.commit()
        raise
    for post, (status, text, seconds) in zip(claimed, results):
        finish(db, post.shortcode, status, text, seconds, transcriber.model if status == "ok" else None)
    return sum(status is not None for status, _, _ in results)


def progress(posts: list[InstagramPost]) -> dict:
    reels = [p for p in posts if p.content_type in VIDEO_TYPES]
    statuses = [p.transcript_status for p in reels]
    expiries = [e for e in (expires_at(u) for u in (video_url(p) for p in reels if p.transcript_status not in FINAL) if u) if e]
    return {
        "enabled": is_configured(),
        "reels": len(reels),
        "done": sum(s in {"ok", "no_speech", "no_audio"} for s in statuses),
        "pending": sum(s not in FINAL for s in statuses),
        "failed": sum(s in {"expired", "too_large", "unavailable", "error"} for s in statuses),
        # El primer enlace pendiente que vence: pasado ese momento ya no se puede transcribir sin recolectar de nuevo.
        "expires_at": min(expiries) if expiries else None,
    }
