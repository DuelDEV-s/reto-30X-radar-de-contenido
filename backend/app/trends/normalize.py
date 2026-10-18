"""S5: dedupe, then Haiku classifies every item: relevance, language, topic phrase, entities, hook."""
import json
import re
from typing import Literal

from pydantic import BaseModel

from . import db as store
from .contracts import BrandIdentity

Hook = Literal["question", "number", "result_first", "how_to", "contrarian", "news",
               "story", "list", "tutorial", "other"]
BATCH = 25


class ItemLabel(BaseModel):
    idx: int
    relevant: bool
    lang: str             # ISO 639-1
    topic_phrase: str     # 2-6 words in the brand's main language
    entities: list[str]   # products, tools, companies, events named in the item
    hook: Hook            # how the title or first line opens


class LabelBatch(BaseModel):
    labels: list[ItemLabel]


SYSTEM = """You label social media items for a content-trend radar. An item is relevant when its
subject belongs to the brand's topic space and would interest at least one of the brand's personas.
Generic news, entertainment, gaming, music or anything matching a negative keyword is not relevant.
topic_phrase names the item's specific subject in 2-6 words, written in {lang}, generic enough that
items about the same subject get the same phrase (for example "agentes de IA para ventas", not the
video's title). hook classifies how the title or first line opens."""


def dedupe_key(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()[:120]


def classify(db, llm, identity: BrandIdentity, item_ids: list[str], full_texts: dict[str, str],
             negative_keywords: list[str], main_lang: str) -> None:
    """Writes item_class rows for items this brand hasn't classified yet."""
    done = {r[0] for r in db.execute("SELECT item_id FROM item_class WHERE brand_id=?", (identity.brand_id,))}
    todo = [i for i in item_ids if i not in done]
    if not todo:
        return
    rows = {r["item_id"]: r for r in db.execute(
        f"SELECT * FROM items WHERE item_id IN ({','.join('?' * len(todo))})", todo)}

    # Near-duplicate LinkedIn posts (copy-paste reposts) are labeled once.
    seen: dict[str, str] = {}
    dupes: dict[str, str] = {}
    unique = []
    for i in todo:
        r = rows.get(i)
        if not r:
            continue
        key = dedupe_key(full_texts.get(i) or r["excerpt"] or r["title"])
        if r["platform"] == "linkedin" and key and key in seen:
            dupes[i] = seen[key]
            continue
        seen.setdefault(key, i)
        unique.append(i)

    personas = "; ".join(f"{p.id}: {p.description}" for p in identity.personas)
    brief = (f"Brand: {identity.brand_name} ({identity.description}). General topic: {identity.general_topic}. "
             f"Specific topics: {', '.join(identity.specific_topics)}. Personas: {personas}. "
             f"Negative keywords: {', '.join(negative_keywords) or 'none'}.")
    prompts, batches = [], []
    for b in range(0, len(unique), BATCH):
        batch = unique[b:b + BATCH]
        lines = []
        for idx, i in enumerate(batch):
            r = rows[i]
            body = full_texts.get(i) or "\n".join(x for x in (r["title"], r["description"] or r["excerpt"]) if x)
            lines.append(json.dumps({"idx": idx, "platform": r["platform"], "text": body[:700]}, ensure_ascii=False))
        prompts.append(f"{brief}\n\nLabel every item (return one label per idx):\n" + "\n".join(lines))
        batches.append(batch)

    results = llm.haiku_many(SYSTEM.format(lang=main_lang), prompts, LabelBatch, max_tokens=8000)
    now = store.iso(store.now_utc())
    labels: dict[str, ItemLabel] = {}
    for batch, res in zip(batches, results):
        for lab in (res.labels if res else []):
            if 0 <= lab.idx < len(batch):
                labels[batch[lab.idx]] = lab
    for dup, original in dupes.items():
        if original in labels:
            labels[dup] = labels[original]
    db.executemany(
        "INSERT OR REPLACE INTO item_class VALUES (?,?,?,?,?,?,?,?)",
        [(i, identity.brand_id, int(l.relevant), l.topic_phrase.strip().lower(),
          json.dumps(l.entities[:8], ensure_ascii=False), l.hook, l.lang[:2].lower(), now)
         for i, l in labels.items()])
    db.commit()
