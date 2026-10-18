"""S6: topic taxonomy (top model) over the classified topic phrases, then phrase -> topic mapping (Haiku).

Model-based clustering replaces BERTopic here: no local embedding model to install, labels come out
in the brand's language, and items from both platforms land in the same topic.
"""
import json
from collections import Counter

from pydantic import BaseModel

from .contracts import BrandIdentity


class TaxTopic(BaseModel):
    topic_id: str          # t01, t02, ...
    label: str             # in the brand's main language
    description: str
    maps_to: list[str]     # brand specific topics it belongs to (may be empty = adjacent)
    entities: list[str]
    covered_by_brand: float  # 0..1, how much the brand's own content already covers it


class Taxonomy(BaseModel):
    topics: list[TaxTopic]


class PhraseMap(BaseModel):
    idx: int
    topic_id: str          # "none" when no topic fits


class PhraseMapBatch(BaseModel):
    mappings: list[PhraseMap]


TAX_SYSTEM = """You build the topic taxonomy for a content-trend radar. Group subject phrases taken
from YouTube videos and LinkedIn posts into distinct, specific topics a content team could publish
about (for example "agentes de IA para atención por WhatsApp", not "inteligencia artificial").
Topics must not overlap. Merge phrases that mean the same thing across languages."""


def build_taxonomy(llm, identity: BrandIdentity, phrase_counts: Counter, coverage_texts: list[str],
                   main_lang: str, max_topics: int = 20) -> Taxonomy:
    phrases = [f"{p} ({n})" for p, n in phrase_counts.most_common(400)]
    cov = "\n- ".join(coverage_texts[:40]) or "(none found)"
    prompt = f"""Brand: {identity.brand_name}. {identity.description}
Specific topics: {json.dumps(identity.specific_topics, ensure_ascii=False)}

Subject phrases with item counts:
{chr(10).join(phrases)}

The brand's own recent content:
- {cov}

Return 10 to {max_topics} topics with ids t01, t02, ... in descending order of item count. Write labels
and descriptions in {main_lang}. maps_to lists which of the brand's specific topics each topic belongs to.
covered_by_brand is 0 when none of the brand's own content covers the topic, 1 when it clearly does."""
    return llm.top(TAX_SYSTEM, prompt, Taxonomy, effort="medium", max_tokens=16000)


def map_phrases(llm, taxonomy: Taxonomy, phrases: list[str]) -> dict[str, str]:
    """phrase -> topic_id (phrases that fit nothing are left out)."""
    catalog = "\n".join(f"{t.topic_id}: {t.label} - {t.description}" for t in taxonomy.topics)
    system = ("Assign each subject phrase to the single best topic id from this catalog, "
              "or 'none' if no topic fits:\n" + catalog)
    batches = [phrases[i:i + 60] for i in range(0, len(phrases), 60)]
    prompts = ["\n".join(json.dumps({"idx": k, "phrase": p}, ensure_ascii=False) for k, p in enumerate(b))
               for b in batches]
    valid = {t.topic_id for t in taxonomy.topics}
    out = {}
    for batch, res in zip(batches, llm.haiku_many(system, prompts, PhraseMapBatch, max_tokens=6000)):
        for m in (res.mappings if res else []):
            if 0 <= m.idx < len(batch) and m.topic_id in valid:
                out[batch[m.idx]] = m.topic_id
    return out
