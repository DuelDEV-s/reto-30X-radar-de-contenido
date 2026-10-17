"""Construcción de búsquedas para descubrir creadores. Sin dependencias de API ni base de datos.

Uso:
    ctx = QueryContext.from_identity(brand.identity, focus_topic="automatización")
    plan = build_queries(ctx)  # QueryPlan con queries "site:instagram.com ..."

Un builder alternativo (p. ej. con LLM) solo necesita implementar `build(ctx) -> QueryPlan`.
"""
import re
from collections import Counter
from typing import Literal, Protocol

from pydantic import Field, field_validator

from .schemas import Platform, StrictModel
from .services import STOPWORDS, normalize

SITES = {"instagram": "instagram.com", "tiktok": "tiktok.com", "youtube": "youtube.com", "linkedin": "linkedin.com"}
# Solo con profiles_only: excluye rutas que no son perfiles.
PROFILE_FILTERS = {"instagram": "-inurl:reel -inurl:explore -inurl:tags"}
Angle = Literal["topic", "context", "cross", "region"]
# Un tópico de una sola palabra corta ("ia", "seo") es ambiguo para Google: nunca se busca sin contexto.
AMBIGUOUS_MAX_CHARS = 4
MAX_CONTEXT_TERMS = 3
# Palabras vacías adicionales para frases de audiencia; no alteran el cálculo de relevancia.
QUERY_STOPWORDS = STOPWORDS | {"que", "sus", "su", "al", "como", "mas", "sobre", "entre", "sin", "son", "es", "un", "lo", "se"}


class QueryContext(StrictModel):
    topics: list[str] = Field(min_length=1, max_length=15)
    region: str = Field(min_length=2, max_length=100)
    summary: str = Field(default="", max_length=5000)
    audience: str = Field(default="", max_length=1000)
    personas: list[str] = Field(default_factory=list, max_length=6)
    focus_topic: str | None = Field(default=None, min_length=2, max_length=100)
    platform: Platform = "instagram"
    max_queries: int = Field(default=6, ge=1, le=20)
    profiles_only: bool = False

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, values):
        values = list(dict.fromkeys(t.strip().lower() for t in values if t.strip()))
        if not values:
            raise ValueError("Indica al menos un tópico.")
        return values

    @classmethod
    def from_identity(cls, identity: dict, **overrides):
        data = {
            "topics": identity["topics"], "region": identity["region"], "summary": identity.get("summary", ""),
            "audience": identity.get("audience", ""),
            "personas": [f"{p['role']}. {p.get('need', '')}" for p in identity.get("personas", [])],
        }
        return cls(**data | {k: v for k, v in overrides.items() if v is not None})


class QueryIdea(StrictModel):
    query: str
    keywords: str
    angle: Angle
    topic: str
    # Versión sin filtros, para reintentar si Google ignora `site:` con la query completa.
    fallback: str | None = None


class QueryPlan(StrictModel):
    method: Literal["rules"]
    platform: Platform
    queries: list[QueryIdea]


class QueryBuilder(Protocol):
    def build(self, ctx: QueryContext) -> QueryPlan: ...


def keywords(text: str, n: int = 3, exclude: str = "") -> list[str]:
    """Primeras n palabras significativas de text, en orden y con su ortografía original."""
    skip = {normalize(w) for w in re.findall(r"\w+", exclude)}
    seen, words = set(), []
    for word in re.findall(r"\w+", text):
        key = normalize(word)
        if len(key) < 2 or key in QUERY_STOPWORDS or key in skip or key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) == n:
            break
    return words


def is_ambiguous(topic: str) -> bool:
    words = re.findall(r"\w+", normalize(topic))
    return len(words) == 1 and len(words[0]) <= AMBIGUOUS_MAX_CHARS


def phrases(text: str) -> list[str]:
    """Palabras significativas y pares consecutivos de ellas, sin cruzar palabras vacías ni puntuación."""
    found = []
    for chunk in re.split(r"[^\w\s]", text):
        previous = None
        for word in re.findall(r"\w+", chunk):
            key = normalize(word)
            if len(key) < 2 or key in QUERY_STOPWORDS:
                previous = None
                continue
            found.append(word.lower())
            if previous:
                found.append(f"{previous} {word.lower()}")
            previous = word.lower()
    return found


def context_terms(ctx: QueryContext, exclude: str = "") -> list[str]:
    """Términos que la identidad repite en al menos dos campos (resumen, audiencia, cada persona, tópicos).

    La repetición entre campos indica de qué trata la marca y descarta palabras sueltas del resumen.
    Las frases de dos palabras ("inteligencia artificial") se conservan completas y sus palabras ya no
    cuentan por separado, para no buscar medio concepto.
    """
    skip = {normalize(w) for w in re.findall(r"\w+", f"{exclude} {ctx.region}")}
    counts, spelling = Counter(), {}
    for field in [[ctx.summary], [ctx.audience], *([p] for p in ctx.personas), ctx.topics]:
        # Cada tópico se procesa aparte para no formar pares entre tópicos distintos.
        terms = {normalize(term): term for text in field for term in phrases(text)}
        for key, term in terms.items():
            words = key.split()
            if any(w in skip for w in words) or (len(words) == 1 and len(key) <= AMBIGUOUS_MAX_CHARS):
                continue
            counts[key] += 1
            spelling.setdefault(key, term)
    repeated = [key for key, count in counts.most_common() if count >= 2]
    covered = {word for key in repeated if " " in key for word in key.split()}
    selected, used = [], set()
    for key in sorted(repeated, key=lambda key: (-counts[key], -len(key.split()))):
        words = set(key.split())
        if len(words) == 1 and key in covered:
            continue
        # Un par que se solapa con una frase más fuerte ("aplicar inteligencia") es un fragmento.
        if len(words) > 1 and words & used:
            continue
        selected.append(spelling[key])
        if len(words) > 1:
            used |= words
    return selected


class RuleQueryBuilder:
    """Plantillas determinísticas a partir de la identidad, intercaladas para variar tópicos y ángulos.

    Cada query es corta: el tópico tal como lo escribió la marca, entre comillas, más como mucho un término
    de contexto de la identidad o un tópico cruzado. Con más términos Google tiende a ignorar `site:`.
    """

    def candidates(self, topic: str, topics: list[str], ctx: QueryContext) -> list[tuple[Angle, str]]:
        context = [("context", term) for term in context_terms(ctx, exclude=topic)[:MAX_CONTEXT_TERMS]]
        cross = [("cross", other) for other in topics if normalize(other) != normalize(topic)]
        mixed = [c for pair in zip(context, cross) for c in pair] + context[len(cross):] + cross[len(context):]
        solo = [] if is_ambiguous(topic) else [("topic", "")]
        return solo + mixed + [("region", ctx.region)]

    def build(self, ctx: QueryContext) -> QueryPlan:
        topics = [ctx.focus_topic.strip().lower()] if ctx.focus_topic else ctx.topics
        site = SITES[ctx.platform]
        filters = PROFILE_FILTERS.get(ctx.platform) if ctx.profiles_only else None
        suffix = f" {filters}" if filters else ""
        options = [self.candidates(topic, ctx.topics, ctx) for topic in topics]
        seen, ideas = set(), []
        for round_ in range(max(map(len, options))):
            for topic, opts in zip(topics, options):
                if round_ >= len(opts):
                    continue
                angle, extra = opts[round_]
                terms = f'"{topic}" {extra}'.strip()
                # Mismas palabras en otro orden ("ia" empresarios / "empresarios" ia) cuentan como duplicado.
                key = frozenset(re.findall(r"\w+", normalize(terms)))
                if key in seen:
                    continue
                seen.add(key)
                base = f"site:{site} {terms}"
                ideas.append(QueryIdea(query=base + suffix, keywords=terms, angle=angle, topic=topic, fallback=base if suffix else None))
        return QueryPlan(method="rules", platform=ctx.platform, queries=ideas[:ctx.max_queries])


def build_queries(ctx: QueryContext, builder: QueryBuilder | None = None) -> QueryPlan:
    return (builder or RuleQueryBuilder()).build(ctx)
