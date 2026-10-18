"""LinkedIn supply side: parse search results into posts, decode timestamps, compute proxies."""
import math
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

_ACTIVITY = re.compile(r"(?:activity|share|ugcPost)[-:](\d{19})")
_AUTHOR_IN_TITLE = re.compile(r"^(.{2,80}?)\s+(?:on|en|no|sur|auf)\s+LinkedIn\b", re.I)
EXCERPT_CHARS = 300   # data minimization: only a short excerpt is stored


def post_time(url: str) -> datetime | None:
    """Exact publish time from the activity ID: the first 41 bits are Unix time in ms."""
    m = _ACTIVITY.search(url)
    if not m:
        return None
    ms = int(m.group(1)) >> 22
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_url(url: str) -> dict | None:
    """-> {item_id, url, format, author_slug} for posts and articles; None for anything else."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if not host.endswith("linkedin.com"):
        return None
    path = unquote(parts.path).rstrip("/")   # slugs arrive URL-encoded (L%C3%B3pez -> López)
    clean = f"https://www.linkedin.com{path}"
    m = _ACTIVITY.search(url)
    if path.startswith("/posts/"):
        slug = path.split("/")[2]
        author_slug = slug.split("_", 1)[0] if "_" in slug else None
        item_id = f"li:{m.group(1)}" if m else f"li:post:{slug[:120]}"
        return {"item_id": item_id, "url": clean, "format": "post", "author_slug": author_slug}
    if path.startswith("/feed/update/") and m:
        return {"item_id": f"li:{m.group(1)}", "url": clean, "format": "post", "author_slug": None}
    if path.startswith("/pulse/"):
        slug = path.split("/")[2]
        return {"item_id": f"li:pulse:{slug[:120]}", "url": clean, "format": "article",
                "author_slug": None}
    return None


def author_name(title: str, author: str | None, author_slug: str | None) -> str | None:
    if author and author.strip() and "linkedin" not in author.lower():
        return author.strip()[:80]
    m = _AUTHOR_IN_TITLE.match(title or "")
    if m:
        return m.group(1).strip()
    if author_slug:
        words = [w for w in author_slug.split("-") if not re.fullmatch(r"[0-9a-f]{4,}|\d+", w)]
        return " ".join(words).title() or None
    return None


def to_item(result: dict) -> dict | None:
    """Search result -> item row (without rank). Full text is returned separately, never stored."""
    parsed = parse_url(result.get("url", ""))
    if not parsed:
        return None
    published = post_time(parsed["url"])
    if published is None and result.get("published"):
        try:
            published = datetime.fromisoformat(result["published"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            published = None
    text = (result.get("text") or "").strip()
    title = (result.get("title") or "").strip()
    author = author_name(title, result.get("author"), parsed["author_slug"])
    creator = parsed["author_slug"] or (re.sub(r"\W+", "-", author.lower()).strip("-") if author else None)
    return {
        "item_id": parsed["item_id"], "platform": "linkedin", "url": parsed["url"],
        "creator_id": f"li-author:{creator}" if creator else None, "author": author,
        "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ") if published else None,
        "title": title[:200] or None, "excerpt": (text or title)[:EXCERPT_CHARS],
        "format": parsed["format"], "evidence_level": "search_index",
        "_full_text": f"{title}\n{text}".strip(),
    }


# --- Visibility proxies (06.3) ------------------------------------------------
def visibility_proxies(hits: dict[str, list[tuple[str, str, int]]], author_counts: dict[str, int],
                       ages_days: dict[str, float], total_queries: int) -> dict[str, float]:
    """hits: item_id -> [(query_id, provider, rank)], ranks start at 1.
    author_counts: item_id -> posts by that item's author in this topic space and window.

    proxy = (0.4·rank_score + 0.3·multi_hit + 0.3·author_weight) × recency_decay
    """
    if not hits:
        return {}
    max_author = max(author_counts.values() or [1])
    max_slots = max(1, total_queries * 2)          # every query can hit on two providers
    out = {}
    for item_id, hs in hits.items():
        rank_score = sum(1 / r for _, _, r in hs) / len(hs)
        multi_hit = min(1.0, len({(q, p) for q, p, _ in hs}) / min(max_slots, 6))
        author_w = math.log1p(author_counts.get(item_id, 0)) / math.log1p(max_author) if max_author else 0
        decay = 0.5 ** (ages_days.get(item_id, 14) / 14)         # half-life two weeks
        out[item_id] = round((0.4 * rank_score + 0.3 * multi_hit + 0.3 * author_w) * decay, 4)
    return out
