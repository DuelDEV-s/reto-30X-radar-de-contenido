"""Tópicos en caliente, emergentes, consolidados, saturados y enfriándose a partir de los posts de una búsqueda.

1. Unificación (LLM): los subtemas que la revisión asignó a cada post son casi todos únicos ("Claude Cowork",
   "Ejecución de tareas con Claude"…). Se agrupan en tópicos canónicos con una sola llamada; se guarda por
   corrida y solo se repite si cambia el conjunto de subtemas.
2. Métricas (funciones puras), solo con posts sobre el tópico de la búsqueda y con rendimiento calculado.
   El rendimiento ya es relativo a cada creador, así que un tópico rinde si hace que los creadores superen
   su propia normalidad, no si lo publica una cuenta grande.
   - Tracción: media geométrica del rendimiento de sus posts, ponderada por recencia (vida media de 7 días).
   - Amplitud: creadores distintos que lo publicaron en los últimos 14 días. Separa tendencia de la
     estrategia de una sola cuenta.
   - Momentum: últimos 14 días frente a los 14 anteriores, en cuota de posts (adopción) y en rendimiento.
3. Estado, en este orden: emergente (solo publicado en la quincena reciente y con tracción alta),
   insuficiente (pocos posts), enfriándose (cae o dejó de publicarse), en caliente (tracción alta, al menos
   dos creadores recientes y momentum no negativo), en ascenso (gana adopción rápido con rendimiento al menos
   normal y dos creadores recientes), saturado (mucho volumen y rendimiento por debajo de lo normal),
   consolidado (rinde bien sin acelerar) o estable. "Otros temas" no recibe estado: es un cajón de sueltos.

Con 30 días y pocos creadores son indicios, no estadística: cada tópico lleva sus posts y creadores.
"""
import json
import logging
import math
import os
from datetime import datetime, timedelta
from statistics import median

import openai
from pydantic import BaseModel, Field, ValidationError

from .account_review import digest

logger = logging.getLogger(__name__)

HALF_LIFE_DAYS = 7.0
RECENT_DAYS = 14
HOT_TRACTION = 1.5
CONSOLIDATED_TRACTION = 1.2
SATURATED_SHARE = 0.12
MIN_POSTS = 3
MIN_CREATORS_HOT = 2
COOLING_MOMENTUM = -0.3
RISING_MOMENTUM = 0.5
# Pseudo-cuota que evita que un tópico pase de 1 a 2 posts y parezca que "se duplicó".
SHARE_SMOOTHING = 0.05
OTHER = "Otros temas"
STATE_ORDER = ["en_caliente", "emergente", "en_ascenso", "consolidado", "estable", "saturado", "enfriandose", "insuficiente", "otros"]
PROMPT_VERSION = 1

INSTRUCTIONS = """Agrupas subtemas de posts de Instagram en tópicos canónicos para un radar de tendencias de contenido.

Recibirás el tópico de la búsqueda y la lista de subtemas, cada uno con cuántos posts lo mencionan. Agrúpalos en entre 5 y 15 tópicos:
- Un tópico reúne subtemas que un creador trataría como el mismo tema al planear contenido (por ejemplo "Claude Cowork", "Configuración inicial de Claude" y "Cursos de Claude" → "Claude para el trabajo").
- Lo bastante específicos para inspirar contenido: nunca el tópico de la búsqueda tal cual ni categorías vacías como "Tecnología".
- name: 2 a 5 palabras en español. description: una frase que diga qué cubre.
- Cada subtema va exactamente en un tópico; copia los subtemas literalmente, sin cambiarlos.
- Los subtemas sueltos que no encajan en ningún grupo van a un tópico llamado "Otros temas"."""


class TopicGroup(BaseModel):
    name: str = Field(max_length=80)
    description: str = Field(max_length=300)
    labels: list[str]


class TopicMap(BaseModel):
    topics: list[TopicGroup]


class OpenAITopicGrouper:
    def __init__(self, client=None, model: str | None = None, effort: str | None = None):
        self.client = client or openai.AsyncOpenAI(timeout=120.0, max_retries=2)
        self.model = model or os.getenv("OPENAI_REVIEW_MODEL", "gpt-6-luna")
        self.effort = effort or os.getenv("OPENAI_REVIEW_EFFORT", "low")

    async def group(self, topic: str, labels: dict[str, int]) -> TopicMap | None:
        response = await self.client.responses.parse(
            model=self.model, instructions=INSTRUCTIONS,
            input=json.dumps({"topico": topic, "subtemas": labels}, ensure_ascii=False),
            text_format=TopicMap, reasoning={"effort": self.effort}, max_output_tokens=8000,
        )
        return response.output_parsed


def labels_digest(topic: str, labels: dict[str, int]) -> str:
    return digest({"topic": topic, "labels": sorted(labels), "prompt_version": PROMPT_VERSION})


def normalize_map(result: TopicMap, labels: dict[str, int]) -> list[dict]:
    """Tópicos con solo subtemas existentes, cada uno una vez; lo que el modelo no asignó va a "Otros temas"."""
    seen, topics = set(), []
    for group in result.topics:
        members = [label for label in group.labels if label in labels and label not in seen]
        seen.update(members)
        if members:
            topics.append({"name": group.name.strip(), "description": group.description.strip(), "labels": members})
    missing = [label for label in labels if label not in seen]
    if missing:
        other = next((t for t in topics if t["name"].lower() == OTHER.lower()), None)
        if other is None:
            other = {"name": OTHER, "description": "Subtemas sueltos que no forman un grupo.", "labels": []}
            topics.append(other)
        other["labels"] += missing
    return topics


async def group_labels(grouper, topic: str, labels: dict[str, int]) -> list[dict] | None:
    try:
        result = await grouper.group(topic, labels)
    except (openai.APIError, ValidationError) as error:
        logger.warning("Unificación de tópicos falló: %s", type(error).__name__)
        return None
    return normalize_map(result, labels) if result else None


def week_start(moment: datetime) -> datetime:
    day = moment - timedelta(days=moment.weekday())
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def geo_mean(values: list[float]) -> float | None:
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else None


def traction(posts: list[dict], ref: datetime) -> float | None:
    weights = [(0.5 ** ((ref - p["posted_at"]).total_seconds() / 86400 / HALF_LIFE_DAYS), p["performance"]) for p in posts]
    total = sum(w for w, _ in weights)
    return math.exp(sum(w * math.log(v) for w, v in weights) / total) if total else None


def state_of(stats: dict) -> str:
    if stats["previous_posts"] == 0 and stats["recent_posts"] >= 1 and (stats["traction"] or 0) >= HOT_TRACTION:
        return "emergente"
    if stats["posts"] < MIN_POSTS:
        return "insuficiente"
    if stats["previous_posts"] > 0 and (stats["recent_posts"] == 0 or (stats["momentum"] is not None and stats["momentum"] <= COOLING_MOMENTUM)):
        return "enfriandose"
    if stats["traction"] >= HOT_TRACTION and stats["recent_creators"] >= MIN_CREATORS_HOT and (stats["momentum"] or 0) >= 0:
        return "en_caliente"
    if (stats["momentum"] or 0) >= RISING_MOMENTUM and stats["traction"] >= 1.0 and stats["recent_creators"] >= MIN_CREATORS_HOT:
        return "en_ascenso"
    if stats["share"] >= SATURATED_SHARE and stats["traction"] < 1.0:
        return "saturado"
    if stats["traction"] >= CONSOLIDATED_TRACTION:
        return "consolidado"
    return "estable"


def analyze(posts: list[dict], topics: list[dict], ref: datetime, window_days: int) -> dict:
    """Métricas por tópico y matriz tópico × semana.

    `posts`: dicts con shortcode, username, posted_at, performance (> 0), subtopics, url, caption, content_type,
    label. Un post cuenta en cada tópico al que pertenece alguno de sus subtemas."""
    label_topic = {label: t["name"] for t in topics for label in t["labels"]}
    recent_from, previous_from = ref - timedelta(days=RECENT_DAYS), ref - timedelta(days=2 * RECENT_DAYS)
    recent_all = [p for p in posts if p["posted_at"] >= recent_from]
    previous_all = [p for p in posts if previous_from <= p["posted_at"] < recent_from]
    first = week_start(ref - timedelta(days=window_days))
    weeks = []
    while first <= ref:
        weeks.append(first)
        first += timedelta(days=7)
    results = []
    for topic in topics:
        members = [p for p in posts if any(label_topic.get(s) == topic["name"] for s in p["subtopics"])]
        if not members:
            continue
        recent = [p for p in members if p["posted_at"] >= recent_from]
        previous = [p for p in members if previous_from <= p["posted_at"] < recent_from]
        share_recent = len(recent) / len(recent_all) if recent_all else 0.0
        share_previous = len(previous) / len(previous_all) if previous_all else 0.0
        adoption = math.log((share_recent + SHARE_SMOOTHING) / (share_previous + SHARE_SMOOTHING)) if previous_all else None
        perf_recent, perf_previous = geo_mean([p["performance"] for p in recent]), geo_mean([p["performance"] for p in previous])
        performance_change = math.log(perf_recent / perf_previous) if perf_recent and perf_previous else None
        changes = [c for c in (adoption, performance_change) if c is not None]
        stats = {
            "posts": len(members), "creators": len({p["username"] for p in members}),
            "recent_posts": len(recent), "previous_posts": len(previous),
            "recent_creators": len({p["username"] for p in recent}),
            "traction": traction(members, ref), "share": len(members) / len(posts),
            "adoption_change": adoption, "performance_change": performance_change,
            "momentum": sum(changes) / len(changes) if changes else None,
        }
        cells = []
        for start in weeks:
            inside = [p for p in members if start <= p["posted_at"] < start + timedelta(days=7)]
            cells.append({"week": start, "posts": len(inside), "creators": len({p["username"] for p in inside}),
                          "median_performance": round(median(p["performance"] for p in inside), 2) if inside else None})
        top = sorted(members, key=lambda p: -p["performance"])[:3]
        formats = {kind: sum(p["content_type"] == kind for p in members) for kind in ("reel", "carousel", "image")}
        results.append({
            "name": topic["name"], "description": topic["description"], "subtopics": topic["labels"],
            "state": "otros" if topic["name"].lower() == OTHER.lower() else state_of(stats),
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in stats.items()},
            "cells": cells, "formats": formats,
            "evidence": [{k: p[k] for k in ("shortcode", "url", "username", "performance", "label", "content_type", "caption")} for p in top],
        })
    results.sort(key=lambda t: (STATE_ORDER.index(t["state"]), -(t["traction"] or 0)))
    return {"weeks": weeks, "topics": results, "post_count": len(posts), "reference": ref,
            "method": {"half_life_days": HALF_LIFE_DAYS, "recent_days": RECENT_DAYS, "hot_traction": HOT_TRACTION,
                       "consolidated_traction": CONSOLIDATED_TRACTION, "saturated_share": SATURATED_SHARE,
                       "min_posts": MIN_POSTS, "min_creators_hot": MIN_CREATORS_HOT, "cooling_momentum": COOLING_MOMENTUM,
                       "rising_momentum": RISING_MOMENTUM}}
