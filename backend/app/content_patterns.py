"""Patrones de contenido: cómo están hechos los reels que funcionan, por contraste con los que no.

Lo que se dice (tópicos) va aparte; aquí importa la producción: formato, encuadre, voz cerca del micrófono,
música, texto en pantalla, gancho, ritmo, tono, llamada a la acción.

- Muestra: los CONTENT_TOP_REELS (5) reels sobre el tópico de la búsqueda con mejor rendimiento, entre los
  virales y sobresalientes, para acotar el costo. Opcionalmente, CONTENT_CONTROL_REELS reels "normales" de
  esos mismos creadores como control: comparar contra el mismo creador aísla lo que cambió en el contenido.
  Sin control (lo predeterminado) solo se informan los rasgos que los destacados tienen en común, que
  inspiran pero no prueban qué explica el éxito.
- Solo los primeros CONTENT_CLIP_SECONDS (10 s) de cada video: el gancho y el arranque definen la producción y
  cada segundo de video consume tokens. Se recortan video y audio sin recodificar y se envían a Gemini sin
  razonamiento (los "thinking tokens" costaban más que la respuesta). El video no se guarda; solo los rasgos.
  Un análisis hecho con otro modelo o con un clip más largo se rehace solo.
- Patrones: rasgos bastante más frecuentes en los destacados que en el control. Lo que comparten ambos
  grupos (por ejemplo, subtítulos en todos) no explica la diferencia y se muestra como "común".
"""
import asyncio
import logging
import os
import tempfile
from collections import Counter
from datetime import timedelta
from typing import Literal, Protocol

import av
import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from .account_store import now
from .brightdata import setting_int
from .database import InstagramPost, PostContentAnalysis
from .transcription import download, expires_at, video_url

logger = logging.getLogger(__name__)

BATCH = 3
CONCURRENCY = 3
STALE_CLAIM = timedelta(minutes=10)
ANALYZE_TIMEOUT = 90
TOP_LABELS = {"viral", "sobresaliente"}
FINAL = {"ok", "expired", "too_large", "unavailable", "error"}
# Un rasgo es patrón si aparece en al menos esta fracción de los destacados y les saca esta ventaja al control.
MIN_SHARE = 0.4
MIN_LIFT = 0.2
COMMON_SHARE = 0.6

PROMPT = """Analiza el inicio de este reel de Instagram (sus primeros {seconds} segundos). Describe cómo está producido, no de qué tema habla.
Responde solo con lo que se ve y se oye. Si algo no se puede determinar, elige "otro" o la opción más neutra.
- formato: estructura dominante del video.
- encuadre: plano dominante de la persona principal; sin_persona si no aparece nadie.
- voz_cercana: true si la voz suena grabada cerca (micrófono de solapa, de mano o de estudio), sin eco de sala.
- microfono_visible: true si se ve un micrófono.
- musica: sin_musica, fondo_suave (acompaña por debajo de la voz) o protagonica (es lo principal o marca el ritmo). musica_estilo: 2 a 4 palabras ("lo-fi tranquilo", "electrónica enérgica") o vacío.
- texto_en_pantalla: subtítulos de lo que se dice, títulos o rótulos, ambos o ninguno.
- gancho: qué pasa en los primeros 3 segundos, en una frase. gancho_tipo: su tipo.
- ritmo_edicion: según la frecuencia de cortes y cambios de plano.
- tono, ambiente y llamada_a_la_accion (si el video pide algo explícitamente).
- descripcion: una frase en español que resuma la producción."""


class ContentFeatures(BaseModel):
    formato: Literal["persona_a_camara", "voz_en_off_con_imagenes", "pantalla_grabada", "texto_animado",
                     "entrevista_o_dialogo", "sketch_o_actuacion", "mixto", "otro"]
    encuadre: Literal["primer_plano", "plano_medio", "plano_general", "sin_persona"]
    voz_cercana: bool
    microfono_visible: bool
    musica: Literal["sin_musica", "fondo_suave", "protagonica"]
    musica_estilo: str = Field(max_length=60)
    texto_en_pantalla: Literal["ninguno", "subtitulos", "titulos", "subtitulos_y_titulos"]
    gancho: str = Field(max_length=250)
    gancho_tipo: Literal["pregunta", "afirmacion_fuerte", "resultado_o_promesa", "demostracion", "lista", "historia", "noticia", "otro"]
    ritmo_edicion: Literal["lento", "medio", "rapido"]
    tono: Literal["educativo", "entusiasta", "humor", "urgente", "conversacional", "inspiracional", "otro"]
    ambiente: Literal["oficina_o_estudio", "casa", "exterior", "evento", "pantalla", "otro"]
    llamada_a_la_accion: Literal["ninguna", "comentar", "seguir", "guardar_o_compartir", "link_o_dm", "otra"]
    descripcion: str = Field(max_length=300)


# Rasgos que se comparan entre grupos (los textos libres solo se muestran).
TRAITS = ["formato", "encuadre", "voz_cercana", "microfono_visible", "musica", "texto_en_pantalla", "gancho_tipo",
          "ritmo_edicion", "tono", "ambiente", "llamada_a_la_accion"]


class VideoAnalyzer(Protocol):
    model: str

    async def analyze(self, clip: bytes) -> ContentFeatures | None: ...


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def clip_seconds() -> int:
    return setting_int("CONTENT_CLIP_SECONDS", 10, 3, 60)


class GeminiAnalyzer:
    def __init__(self, client=None, model: str | None = None):
        from google import genai
        self.client = client or genai.Client()
        self.model = model or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"

    async def analyze(self, clip: bytes) -> ContentFeatures | None:
        from google.genai import types
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=clip, mime_type="video/mp4"), PROMPT.format(seconds=clip_seconds())],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=ContentFeatures,
                                               thinking_config=types.ThinkingConfig(thinking_budget=0)),
        )
        parsed = response.parsed
        return parsed if isinstance(parsed, ContentFeatures) else ContentFeatures.model_validate_json(response.text) if response.text else None


def clip_video(video_path: str, clip_path: str, seconds: float) -> float | None:
    """Copia los primeros `seconds` de video y audio a un MP4 nuevo, sin recodificar. None si no hay video."""
    with av.open(video_path) as source:
        streams = [s for s in source.streams if s.type in ("video", "audio")]
        if not any(s.type == "video" for s in streams):
            return None
        longest = 0.0
        with av.open(clip_path, "w", format="mp4") as target:
            outputs = {s.index: target.add_stream_from_template(s) for s in streams}
            starts: dict[int, float] = {}
            for packet in source.demux(streams):
                if packet.dts is None or packet.pts is None:
                    continue
                at = float(packet.pts * packet.stream.time_base)
                start = starts.setdefault(packet.stream.index, at)
                if at - start >= seconds:
                    continue
                longest = max(longest, at - start + float((packet.duration or 0) * packet.stream.time_base))
                packet.stream = outputs[packet.stream.index]
                target.mux(packet)
    return round(min(longest, seconds), 1)


def top_reels() -> int:
    return setting_int("CONTENT_TOP_REELS", 5, 1, 50)


def control_reels() -> int:
    return setting_int("CONTENT_CONTROL_REELS", 0, 0, 50)


def select(posts: list[dict]) -> tuple[list[str], list[str]]:
    """(destacados, control): los mejores reels sobre el tópico y, si se piden, controles normales de sus creadores
    (por cada creador, tantos como destacados suyos, los más cercanos a ×1), hasta CONTENT_CONTROL_REELS."""
    reels = [p for p in posts if p["content_type"] in ("reel", "video") and p["on_topic"]]
    top = sorted((p for p in reels if p["label"] in TOP_LABELS), key=lambda p: -p["performance"])[:top_reels()]
    control = []
    for username, count in Counter(p["username"] for p in top).items():
        normals = sorted((p for p in reels if p["username"] == username and p["label"] == "normal"),
                         key=lambda p: abs(p["performance"] - 1))
        control += normals[:count]
    return [p["shortcode"] for p in top], [p["shortcode"] for p in control[:control_reels()]]


def claim(db: Session, post: InstagramPost) -> bool:
    platform, shortcode = post.PLATFORM, post.shortcode
    row = db.get(PostContentAnalysis, (platform, shortcode))
    if row is None:
        db.add(PostContentAnalysis(platform=platform, shortcode=shortcode, status="processing", analyzed_at=now()))
        try:
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
    result = db.execute(update(PostContentAnalysis).where(
        PostContentAnalysis.platform == platform, PostContentAnalysis.shortcode == shortcode,
        or_(PostContentAnalysis.status.is_(None),
            (PostContentAnalysis.status == "processing") & (PostContentAnalysis.analyzed_at < now() - STALE_CLAIM)),
    ).values(status="processing", analyzed_at=now()).execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount == 1


async def process(client: httpx.AsyncClient, analyzer: VideoAnalyzer, post: InstagramPost):
    """(estado, rasgos, segundos). Cualquier fallo es final: el reel queda sin análisis y no se reintenta."""
    url = video_url(post)
    if url is None:
        return "unavailable", None, None
    expiry = expires_at(url)
    if expiry and expiry <= now():
        return "expired", None, None
    with tempfile.TemporaryDirectory() as folder:
        video, clip = os.path.join(folder, "reel.mp4"), os.path.join(folder, "clip.mp4")
        try:
            failure = await download(client, url, video)
        except httpx.HTTPError:
            return "unavailable", None, None
        if failure:
            return failure, None, None
        try:
            seconds = await asyncio.to_thread(clip_video, video, clip, clip_seconds())
        except av.error.FFmpegError:
            return "error", None, None
        if seconds is None:
            return "error", None, None
        with open(clip, "rb") as file:
            data = file.read()
    try:
        # El SDK de Gemini no fija un tiempo máximo: sin este límite una llamada colgada retiene la reserva.
        features = await asyncio.wait_for(analyzer.analyze(data), ANALYZE_TIMEOUT)
    except ValidationError:
        return "error", None, None
    except Exception as error:  # el SDK de Gemini no expone una jerarquía de errores estable entre versiones
        # Sin reintentos: el reel queda vacío y se sigue con los demás (cada intento consume tokens).
        logger.warning("Análisis de video falló para %s: %s", post.shortcode, type(error).__name__)
        return "error", None, None
    return ("ok", features, seconds) if features else ("error", None, None)


def analyses(db: Session, platform: str, shortcodes: list[str]) -> dict[str, PostContentAnalysis]:
    if not shortcodes:
        return {}
    rows = db.query(PostContentAnalysis).filter(PostContentAnalysis.platform == platform, PostContentAnalysis.shortcode.in_(shortcodes)).all()
    return {r.shortcode: r for r in rows}


async def analyze_posts(db: Session, posts: list[InstagramPost], analyzer: VideoAnalyzer, client: httpx.AsyncClient, limit: int = BATCH) -> int:
    if not posts:
        return 0
    platform = posts[0].PLATFORM
    done = analyses(db, platform, [p.shortcode for p in posts])
    outdated = [code for code, row in done.items() if row.status == "ok" and not current(row, analyzer.model)]
    if outdated:
        # Otro modelo o un clip más largo que el configurado: se vuelve a analizar.
        db.execute(update(PostContentAnalysis).where(PostContentAnalysis.platform == platform, PostContentAnalysis.shortcode.in_(outdated),
                                                     PostContentAnalysis.status == "ok")
                   .values(status=None).execution_options(synchronize_session=False))
        db.commit()
        db.expire_all()
        done = analyses(db, platform, list(done))
    # Lo que otra consulta tiene reservado se salta: no bloquea la cola.
    pending = [p for p in posts if not (done.get(p.shortcode) and done[p.shortcode].status in FINAL | {"processing"})]
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
            return await process(client, analyzer, post)

    try:
        results = await asyncio.gather(*(one(p) for p in claimed))
    except BaseException:
        # Petición cancelada (el cliente cerró la conexión) o error inesperado: se liberan las reservas.
        release(db, platform, [p.shortcode for p in claimed])
        raise
    for post, (status, features, seconds) in zip(claimed, results):
        db.execute(update(PostContentAnalysis).where(PostContentAnalysis.platform == platform, PostContentAnalysis.shortcode == post.shortcode).values(
            status=status, features=features.model_dump() if features else None, seconds=seconds,
            model=analyzer.model if features else None, analyzed_at=now()).execution_options(synchronize_session=False))
    db.commit()
    return sum(status is not None for status, _, _ in results)


def current(row: PostContentAnalysis, model: str) -> bool:
    return row.model == model and (row.seconds or 0) <= clip_seconds() + 0.5


def release(db: Session, platform: str, shortcodes: list[str]) -> None:
    db.rollback()
    db.execute(update(PostContentAnalysis).where(PostContentAnalysis.platform == platform, PostContentAnalysis.shortcode.in_(shortcodes),
                                                 PostContentAnalysis.status == "processing")
               .values(status=None).execution_options(synchronize_session=False))
    db.commit()


def contrast(top: list[dict], control: list[dict]) -> dict:
    """Frecuencia de cada rasgo en destacados y control, y los patrones que los separan."""
    traits = []
    for trait in TRAITS:
        values = Counter(f[trait] for f in top) + Counter(f[trait] for f in control)
        for value in values:
            share_top = sum(f[trait] == value for f in top) / len(top) if top else 0.0
            share_control = sum(f[trait] == value for f in control) / len(control) if control else 0.0
            traits.append({"trait": trait, "value": value, "top": round(share_top, 2), "control": round(share_control, 2),
                           "lift": round(share_top - share_control, 2)})
    traits.sort(key=lambda t: -t["lift"])
    # Sin control solo se puede decir qué comparten los destacados.
    shared = sorted((t for t in traits if t["top"] >= COMMON_SHARE), key=lambda t: -t["top"])
    if not control:
        return {"patterns": [], "common": [], "avoid": [], "shared": shared, "traits": traits}
    return {
        "shared": shared,
        "patterns": [t for t in traits if t["top"] >= MIN_SHARE and t["lift"] >= MIN_LIFT],
        "common": [t for t in traits if t["top"] >= COMMON_SHARE and t["control"] >= COMMON_SHARE],
        "avoid": [t for t in traits if t["control"] >= MIN_SHARE and t["lift"] <= -MIN_LIFT],
        "traits": traits,
    }
