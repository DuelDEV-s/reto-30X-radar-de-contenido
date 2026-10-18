"""Reglas explícitas y auditables. No scraping ni inferencias causales."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
import re
import unicodedata

from .schemas import BatchCreate, BrandCreate, Identity


def draft_identity(brief: BrandCreate) -> Identity:
    topics = brief.topics or ["por definir"]
    audience = brief.audience or "Audiencia por confirmar"
    return Identity(
        summary=brief.description or "Identidad pendiente de información pública del perfil y revisión del equipo.",
        audience=audience,
        region=brief.region,
        topics=topics,
        personas=[{"role": audience[:120], "need": f"Validar necesidades de esta audiencia sobre {', '.join(topics)} en {brief.region}."[:500]}],
        status="draft", method="brief_rules",
    )


STOPWORDS = {"de", "la", "el", "en", "para", "con", "los", "las", "del", "una", "por"}


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def tokens(text):
    return set(re.findall(r"[a-z0-9]{2,}", normalize(text))) - STOPWORDS


def relevance(topic: str, identity: dict):
    a = tokens(topic)
    candidates = [tokens(t) for t in identity["topics"]]
    return round(100 * max((len(a & b) / max(len(a | b), 1) for b in candidates), default=0))


def analyze(batch: BatchCreate, identity: dict, *, platform=None, topic=None, limit=10, window_days=7):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    groups = defaultdict(list)
    for post in batch.posts:
        if platform and post.platform != platform:
            continue
        if topic and topic.casefold() not in post.topic.casefold():
            continue
        if post.snapshots[-1].observed_at < cutoff:
            continue
        groups[post.topic].append(post)
    rows = []
    for name, posts in groups.items():
        accelerations, rates = [], []
        for post in posts:
            s = post.snapshots
            if len(s) >= 2:
                days = (s[-1].observed_at - s[-2].observed_at).total_seconds() / 86400
                current = (s[-1].views - s[-2].views) / days
                rates.append(current)
                if len(s) >= 3:
                    previous_days = (s[-2].observed_at - s[-3].observed_at).total_seconds() / 86400
                    previous = (s[-2].views - s[-3].views) / previous_days
                    # A zero baseline is insufficient to estimate a percentage.
                    if previous > 0:
                        accelerations.append((current / previous - 1) * 100)
        acceleration = round(median(accelerations), 1) if accelerations else None
        fit = relevance(name, identity)
        evidence = min(len(posts) / 3, 1) * min(len(accelerations) / 3, 1)
        momentum = min(max((acceleration or 0) / 200, 0), 1)
        score = round(0.45 * fit + 35 * momentum + 20 * evidence)
        stage = "Sin serie suficiente" if acceleration is None else "En aceleración" if acceleration >= 25 else "Estable" if acceleration >= -10 else "Desacelerando"
        top = max(posts, key=lambda p: p.snapshots[-1].views)
        rows.append({
            "topic": name, "score": score, "relevance": fit,
            "acceleration_pct": acceleration, "views_per_day": round(median(rates)) if rates else None,
            "stage": stage, "confidence": "media" if len(posts) >= 3 and len(accelerations) >= 3 else "baja",
            "sample_size": len(posts), "series_count": len(accelerations),
            "why_relevant": f"Coincidencia léxica de {fit}% con los tópicos declarados. Validar pertinencia con {identity['audience']} ({identity['region']}).",
            "why_it_may_work": [f"Hipótesis de gancho: «{top.hook}» presenta una promesa que conviene contrastar.", f"Formato de la pieza con más vistas en esta muestra: {top.format}. No demuestra que el formato cause el resultado."],
            "adaptation": f"Probar un {top.format} sobre {name} para {identity['audience']}, con un caso de {identity['region']}. Abrir con un problema concreto, mostrar un ejemplo y cerrar con una acción medible.",
            "top_content": top.model_dump(mode="json"),
            "timeline": [{"url": p.url, "points": [s.model_dump(mode="json") for s in p.snapshots]} for p in posts],
        })
    rows.sort(key=lambda row: (-row["score"], row["topic"]))
    return {
        "generated_at": now.isoformat(), "mode": batch.mode, "source": batch.source,
        "window_days": window_days, "topics": rows[:limit], "total_topics": len(rows),
        "methodology": "score-v1: 45% coincidencia de tópicos + 35% aceleración positiva (tope 200%) + 20% evidencia (3 piezas con 3 observaciones y base positiva). Aceleración = mediana del cambio relativo entre las dos últimas velocidades de vistas/día de cada pieza.",
        "limitations": ["La muestra no representa toda la red. No permite afirmar cuáles son las tendencias globales.", "Las explicaciones son hipótesis editoriales de reglas, no causalidad ni análisis con IA.", "La ventana filtra la última observación; los intervalos pueden comenzar antes. No se infiere saturación ni diversidad de autores.", "La relevancia es coincidencia léxica, no una predicción de rendimiento para la audiencia."],
    }
