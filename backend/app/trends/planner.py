"""S1: query matrix. One Sonnet call turns topics x personas x languages into search queries."""
import json
from typing import Literal

from pydantic import BaseModel

from .contracts import BrandIdentity


class PlannedQuery(BaseModel):
    text: str             # natural-language query for YouTube and Exa
    li_keywords: str      # short keyword string for Brave (quoted phrases allowed)
    lang: Literal["es", "en", "pt", "fr", "de", "it"]
    topic: str
    persona_id: str


class QueryPlan(BaseModel):
    queries: list[PlannedQuery]
    negative_keywords: list[str]


SYSTEM = """You plan search queries for a content-trend radar. The radar measures what the market
publishes and watches about a brand's topics on YouTube and LinkedIn, so queries must describe the
topic space the brand's audience cares about, not the brand itself. Write queries the way people in
each language actually search. Mix broad and specific queries, cover every persona and every specific
topic, and include English queries even when the brand's market speaks another language, because
topics usually surge in English first."""


def plan_queries(llm, identity: BrandIdentity, languages: list[str], n: int) -> QueryPlan:
    prompt = f"""Brand identity:
{identity.model_dump_json(include={'brand_name', 'description', 'general_topic', 'specific_topics', 'personas'}, indent=1)}

Languages to cover: {json.dumps(languages)} (about 70% of queries in the first language, at least 25% in English).
Return exactly {n} queries. For each one:
- text: the natural-language query (3 to 8 words), used for YouTube and semantic search.
- li_keywords: 2 to 5 keywords for a web search restricted to LinkedIn posts; quote multi-word phrases.
- lang, topic (one of the specific topics, or the general topic), persona_id (one of the persona ids).
Also return 5 to 15 negative_keywords: subjects that share words with this topic space but are off-topic for this audience."""
    plan = llm.sonnet(SYSTEM, prompt, QueryPlan, effort="medium", max_tokens=16000)
    persona_ids = {p.id for p in identity.personas}
    plan.queries = [q for q in plan.queries if q.persona_id in persona_ids][:n]
    return plan


def fallback_queries(identity: BrandIdentity, languages: list[str]) -> QueryPlan:
    """Model-free queries for smoke tests (e.g. the LinkedIn hit-rate test without an Anthropic key)."""
    qs = []
    for lang in languages:
        for topic in identity.specific_topics:
            for p in identity.personas:
                text = f"{identity.general_topic} {topic}"
                qs.append(PlannedQuery(text=text, li_keywords=f'"{identity.general_topic}" {topic}',
                                       lang=lang if lang in ("es", "en", "pt", "fr", "de", "it") else "es",
                                       topic=topic, persona_id=p.id))
                break
    return QueryPlan(queries=qs, negative_keywords=[])
