"""Revisión con LLM de cada post: ¿habla del tópico de la búsqueda?

Que un creador sea relevante no hace relevantes todos sus posts: el mismo creador de IA publica la noticia
de un temblor o la promoción de su evento. Por post se pide, en una sola llamada:

- relevancia para el tópico de la búsqueda (la identidad de la marca solo como contexto para desempatar),
- tipo de contenido (educativo, noticia, promoción…),
- 1–3 subtemas específicos, insumo para detectar tópicos en caliente,
- si el texto disponible no alcanza para saber de qué trata el video (`needs_transcript`).

Flujo con los reels: primero se clasifican con el caption; solo los relevantes o indeterminados se
transcriben, y al tener transcripción se reclasifican (la transcripción cambia el digest de entrada).
Así no se paga por transcribir lo que claramente está fuera de tema.

El veredicto se guarda por post y tópico y solo se vuelve a pedir si cambian el tópico, el caption, la
transcripción o las instrucciones.
"""
import asyncio
import json
import logging
import os
from typing import Literal, Protocol

import openai
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .account_review import digest
from .account_store import now
from .database import InstagramPost, PostTopicReview
from .transcription import VIDEO_TYPES

logger = logging.getLogger(__name__)

Relevance = Literal["alta", "media", "baja", "ninguna"]
ContentKind = Literal["educativo", "noticia", "promocion_evento", "venta", "opinion", "entretenimiento", "personal", "otro"]
ON_TOPIC = {"alta", "media"}
BATCH = 12
MAX_CONCURRENCY = 4
MAX_CAPTION = 2000
PROMPT_VERSION = 2

INSTRUCTIONS = """Eres analista de contenido en redes sociales. Decides si un post de Instagram habla de un tópico concreto, para un radar de tendencias de contenido.

Recibirás el tópico de la búsqueda, el contexto de la marca (solo para desempatar casos dudosos) y el post: tipo, caption, hashtags y, si existe, la transcripción del inicio del video.

El tópico es un paraguas amplio, no una palabra clave: incluye sus subtemas, herramientas, productos, casos de uso y aplicaciones a cualquier dominio. El post no tiene que hablar exclusivamente del tópico ni nombrarlo literalmente. Por ejemplo, para "inteligencia artificial", "IA aplicada a la contabilidad", "usar ChatGPT para aprender inglés" o "automatizar ventas con un agente" son relevantes.

relevance (qué tanto el contenido del post trata el tópico de la búsqueda; no el creador ni su cuenta):
- alta: el tópico o una aplicación concreta de él es el eje del post, aunque se combine con otro dominio (negocios, salud, educación…).
- media: el tópico aparece de forma significativa pero no es el eje, o el post trata un tema muy cercano.
- baja: mención de pasada o solo en hashtags; el contenido trata otra cosa.
- ninguna: el post trata otra cosa.

Una llamada a la acción ("comenta X y te envío…") no es el tema: juzga de qué trata el contenido. Promocionar un evento, un curso o un producto solo es relevante si el post explica algo del tópico.

content_kind: educativo (enseña o explica), noticia, promocion_evento (anuncia un evento, sesión o lanzamiento propio), venta (vende un producto o servicio), opinion, entretenimiento, personal (vida del creador), otro.

subtopics: de 1 a 3 temas específicos de los que trata el post, en español, de 2 a 5 palabras, concretos (por ejemplo "Claude Cowork", "IA para conciliación contable"), nunca genéricos como "inteligencia artificial" o "tecnología". Lista vacía si no hay contenido identificable.

needs_transcript: true si es un video y el texto recibido no permite saber de qué habla (caption vacío, solo una llamada a la acción o solo hashtags). false si ya hay transcripción o el caption basta.

reason: una frase en español con la evidencia que decidió la relevancia."""


class PostVerdict(BaseModel):
    relevance: Relevance
    content_kind: ContentKind
    subtopics: list[str] = Field(max_length=3)
    needs_transcript: bool
    reason: str = Field(max_length=400)


class PostReviewer(Protocol):
    model: str
    effort: str

    async def review(self, topic: str, brand: dict, post: dict) -> PostVerdict | None: ...


class OpenAIPostReviewer:
    def __init__(self, client=None, model: str | None = None, effort: str | None = None):
        self.client = client or openai.AsyncOpenAI(timeout=60.0, max_retries=2)
        self.model = model or os.getenv("OPENAI_REVIEW_MODEL", "gpt-6-luna")
        self.effort = effort or os.getenv("OPENAI_REVIEW_EFFORT", "low")

    async def review(self, topic: str, brand: dict, post: dict) -> PostVerdict | None:
        response = await self.client.responses.parse(
            model=self.model,
            instructions=INSTRUCTIONS,
            input=json.dumps({"topico": topic, "marca": brand, "post": post}, ensure_ascii=False),
            text_format=PostVerdict,
            reasoning={"effort": self.effort},
            max_output_tokens=2000,
        )
        return response.output_parsed


def evidence(post: InstagramPost) -> dict:
    """Lo que ve el LLM del post. La transcripción solo cuenta si salió bien."""
    return {
        "tipo": post.content_type,
        "caption": (post.caption or "")[:MAX_CAPTION],
        "hashtags": post.hashtags[:20],
        "transcripcion_inicio": post.transcript if post.transcript_status == "ok" else None,
    }


def topic_key(topic: str) -> str:
    return digest({"topic": topic.strip().lower(), "prompt_version": PROMPT_VERSION})


def reviews_by_shortcode(db: Session, shortcodes: list[str], topic: str) -> dict[str, PostTopicReview]:
    if not shortcodes:
        return {}
    rows = db.scalars(select(PostTopicReview).where(PostTopicReview.topic_key == topic_key(topic),
                                                    PostTopicReview.shortcode.in_(shortcodes))).all()
    return {r.shortcode: r for r in rows}


def current(review: PostTopicReview | None, post: InstagramPost) -> bool:
    return bool(review and review.input_digest == digest(evidence(post)))


def wants_transcript(review: PostTopicReview | None, post: InstagramPost) -> bool:
    """Reel que vale la pena transcribir: relevante o indeterminado según su caption, y aún sin transcripción."""
    return bool(post.content_type in VIDEO_TYPES and review and not review.used_transcript
                and (review.relevance in ON_TOPIC or review.needs_transcript))


async def review_posts(db: Session, posts: list[InstagramPost], topic: str, brand: dict, reviewer: PostReviewer,
                       limit: int = BATCH) -> int:
    """Revisa como mucho `limit` posts sin veredicto vigente para `topic`. Devuelve cuántos se revisaron.

    Un reel con la transcripción en curso espera a que termine para no pagar dos revisiones seguidas."""
    existing = reviews_by_shortcode(db, [p.shortcode for p in posts], topic)
    pending = [p for p in posts if not current(existing.get(p.shortcode), p) and p.transcript_status != "processing"]
    pending = pending[:limit]
    if not pending:
        return 0
    slots = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(post):
        async with slots:
            try:
                return await reviewer.review(topic, brand, evidence(post))
            except (openai.APIError, ValidationError) as error:
                # Un fallo del proveedor deja el post pendiente; no rompe la consulta.
                logger.warning("Revisión LLM del post %s falló: %s", post.shortcode, type(error).__name__)
                return None

    verdicts = await asyncio.gather(*(one(p) for p in pending))
    key, reviewed = topic_key(topic), 0
    for post, verdict in zip(pending, verdicts):
        if verdict is None:
            continue
        row = existing.get(post.shortcode) or PostTopicReview(shortcode=post.shortcode, topic_key=key, topic=topic[:200])
        row.relevance, row.content_kind, row.reason = verdict.relevance, verdict.content_kind, verdict.reason
        row.subtopics = [s.strip()[:80] for s in verdict.subtopics if s.strip()][:3]
        row.used_transcript = post.transcript_status == "ok"
        # Con transcripción ya no hay nada más que pedir, diga lo que diga el modelo.
        row.needs_transcript = verdict.needs_transcript and not row.used_transcript
        row.model, row.effort = reviewer.model, reviewer.effort
        row.input_digest, row.reviewed_at = digest(evidence(post)), now()
        db.add(row)
        reviewed += 1
    db.commit()
    return reviewed


def review_dict(review: PostTopicReview | None) -> dict:
    if review is None:
        return {"topic_review": None}
    return {"topic_review": {"relevance": review.relevance, "on_topic": review.relevance in ON_TOPIC, "content_kind": review.content_kind,
                             "subtopics": review.subtopics, "reason": review.reason, "used_transcript": review.used_transcript,
                             "needs_transcript": review.needs_transcript}}


def progress(posts: list[InstagramPost], reviews: dict[str, PostTopicReview], enabled: bool) -> dict:
    verdicts = [reviews.get(p.shortcode) for p in posts]
    return {
        "enabled": enabled,
        "reviewed": sum(current(r, p) for r, p in zip(verdicts, posts)),
        "pending": sum(not current(r, p) for r, p in zip(verdicts, posts)),
        "on_topic": sum(bool(r and r.relevance in ON_TOPIC) for r in verdicts),
        "off_topic": sum(bool(r and r.relevance not in ON_TOPIC) for r in verdicts),
    }
