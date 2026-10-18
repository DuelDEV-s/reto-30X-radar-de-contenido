"""S0: markets, optional brand coverage (what the brand already posts) and brand voice."""
from datetime import timedelta

from pydantic import BaseModel

from . import config, db as store, linkedin
from .contracts import BrandIdentity, Markets
from .providers import search


class Voice(BaseModel):
    voice: str


def markets(identity: BrandIdentity) -> Markets:
    return identity.markets or Markets()


def query_languages(m: Markets) -> list[str]:
    """Brand languages plus English as the early-signal language."""
    langs = list(dict.fromkeys(m.languages))
    if "en" not in langs:
        langs.append("en")
    return langs


def coverage(db, identity: BrandIdentity, yt, spend, use_linkedin: bool = True) -> tuple[str | None, list[str]]:
    """Titles or excerpts of the brand's own recent content. Stops at the first source that works."""
    texts: list[str] = []
    source = None
    if use_linkedin and config.secret("EXA_API_KEY", required=False):
        start = store.iso(store.now_utc() - timedelta(days=180))
        results = search.exa_search(db, spend, f"{identity.brand_name} {identity.general_topic}", start, 25)
        name = identity.brand_name.lower()
        for r in results:
            it = linkedin.to_item(r)
            if it and it["author"] and name in it["author"].lower():
                texts.append(it["excerpt"][:200])
        if texts:
            source = "linkedin_search"
    if identity.handles.youtube and yt is not None:
        chans = yt.channels(handle=identity.handles.youtube)
        for ch in chans.values():
            vids = yt.videos(yt.recent_uploads(ch["uploads"], 30))
            texts += [v["title"] for v in vids.values()]
            source = source or "youtube_channel"
    return source, texts[:60]


def voice(llm, identity: BrandIdentity, samples: list[str]) -> str | None:
    if not samples:
        return None
    out = llm.haiku_many(
        "Describe a brand's writing voice in one short sentence in the brand's language.",
        [f"Brand: {identity.brand_name}. {identity.description}\nSamples:\n- " + "\n- ".join(samples[:20])],
        Voice, max_tokens=2000)[0]
    return out.voice if out else None
