"""S2-S4: discovery, enrichment, creator baselines and snapshots."""
import json
import logging
import statistics
from datetime import timedelta

from . import config, db as store, linkedin
from .providers import search
from .providers.youtube import QuotaExceeded

log = logging.getLogger(__name__)


def record_hit(db, item_id: str, query_id: str, provider: str, rank: int) -> None:
    db.execute("INSERT OR REPLACE INTO item_query VALUES (?,?,?,?)", (item_id, query_id, provider, rank))


def save_videos(db, videos: dict, captured_at: str) -> None:
    for v in videos.values():
        store.upsert_creator(db, {"creator_id": f"yt:{v['channel_id']}", "platform": "youtube",
                                  "display_name": v["channel_title"],
                                  "url": f"https://www.youtube.com/channel/{v['channel_id']}"})
        store.upsert_item(db, {
            "item_id": f"yt:{v['id']}", "platform": "youtube", "url": f"https://youtu.be/{v['id']}",
            "creator_id": f"yt:{v['channel_id']}", "published_at": v["published_at"],
            "title": v["title"], "description": v["description"], "lang": v["lang"] or None,
            "format": v["format"], "duration_s": v["duration_s"],
            "tags": json.dumps(v["tags"][:20], ensure_ascii=False), "evidence_level": "api"})
        store.add_snapshot(db, f"yt:{v['id']}", captured_at, v["views"], v["likes"], v["comments"])
    db.commit()


# --- YouTube ------------------------------------------------------------------
def youtube_discovery(db, yt, queries, regions: list[str], since: str, date_order_queries: int) -> set[str]:
    """Search every query (viewCount order) plus the first N in date order. Returns item ids."""
    found: dict[str, None] = {}
    region_cycle = [r for r in regions if r] or [None]
    for i, (query_id, q) in enumerate(queries):
        region = region_cycle[i % len(region_cycle)] if q.lang != "en" else None
        orders = ["viewCount"] + (["date"] if i < date_order_queries else [])
        for order in orders:
            try:
                ids = yt.search(q.text, since, q.lang, region, order=order)
            except QuotaExceeded:      # cached searches keep working; the rest are skipped
                continue
            except Exception as e:      # one failed query must not stop the run
                log.warning("youtube search failed for %r: %s", q.text, e)
                continue
            for rank, vid in enumerate(ids, 1):
                record_hit(db, f"yt:{vid}", query_id, f"youtube:{order}", rank)
                found[vid] = None
    db.commit()
    if found:
        save_videos(db, yt.videos(found), store.iso(store.now_utc()))
    return {f"yt:{v}" for v in found}


def refresh_channels(db, yt, creator_ids: set[str]) -> None:
    missing = [c.removeprefix("yt:") for c in creator_ids if c.startswith("yt:") and not db.execute(
        "SELECT 1 FROM creators WHERE creator_id=? AND uploads_playlist IS NOT NULL", (c,)).fetchone()]
    for ch in yt.channels(ids=missing).values():
        store.upsert_creator(db, {"creator_id": f"yt:{ch['id']}", "platform": "youtube",
                                  "display_name": ch["title"], "subscribers": ch["subs"],
                                  "uploads_playlist": ch["uploads"],
                                  "url": f"https://www.youtube.com/channel/{ch['id']}"})
    db.commit()


def compute_baseline(db, creator_id: str) -> dict:
    """Median views of the creator's last uploads older than 3 days, per format, with a floor."""
    cutoff = store.iso(store.now_utc() - timedelta(days=3))
    rows = db.execute(
        """SELECT i.format, s.views FROM items i
           JOIN snapshots s ON s.item_id = i.item_id
            AND s.captured_at = (SELECT MAX(captured_at) FROM snapshots WHERE item_id = i.item_id)
           WHERE i.creator_id=? AND i.published_at < ? ORDER BY i.published_at DESC LIMIT ?""",
        (creator_id, cutoff, config.BASELINE_N)).fetchall()
    by_fmt: dict[str, list[int]] = {}
    for r in rows:
        by_fmt.setdefault(r["format"], []).append(r["views"])
        by_fmt.setdefault("all", []).append(r["views"])
    return {f: max(statistics.median(v), config.MIN_BASELINE) for f, v in by_fmt.items() if len(v) >= 3}


def youtube_baselines(db, yt, creator_ids: set[str], max_creators: int = 200) -> None:
    """Fill each creator's baseline from their recent uploads (1 unit per creator + 1 per 50 videos)."""
    stale = store.iso(store.now_utc() - timedelta(days=7))
    todo = []
    for cid in creator_ids:
        row = db.execute("SELECT uploads_playlist, baseline, last_checked FROM creators WHERE creator_id=?",
                         (cid,)).fetchone()
        if row and row["uploads_playlist"] and (not row["baseline"] or (row["last_checked"] or "") < stale):
            todo.append((cid, row["uploads_playlist"]))
    todo = todo[:max_creators]
    upload_ids: list[str] = []
    for _, playlist in todo:
        try:
            upload_ids += yt.recent_uploads(playlist, config.BASELINE_N)
        except Exception as e:
            log.warning("uploads failed for %s: %s", playlist, e)
    known = {r[0] for r in db.execute("SELECT item_id FROM items WHERE platform='youtube'")}
    new = [v for v in upload_ids if f"yt:{v}" not in known]
    if new:
        save_videos(db, yt.videos(new), store.iso(store.now_utc()))
    now = store.iso(store.now_utc())
    for cid, _ in todo:
        db.execute("UPDATE creators SET baseline=?, last_checked=? WHERE creator_id=?",
                   (json.dumps(compute_baseline(db, cid)), now, cid))
    db.commit()


def track(db, item_ids, brand_id: str, days: int) -> None:
    until = store.iso(store.now_utc() + timedelta(days=days))
    db.executemany("INSERT OR REPLACE INTO tracked VALUES (?,?,?)",
                   [(i, brand_id, until) for i in item_ids if i.startswith("yt:")])
    db.commit()


# --- LinkedIn -----------------------------------------------------------------
def linkedin_discovery(db, spend, queries, regions: list[str], since_dt, until_dt) -> dict[str, str]:
    """Exa (+ Brave when configured) for every query. Returns {item_id: full_text} (full text is never stored)."""
    providers = search.enabled_providers()
    texts: dict[str, str] = {}
    start = store.iso(since_dt)
    d_from, d_to = since_dt.strftime("%Y-%m-%d"), until_dt.strftime("%Y-%m-%d")
    region_cycle = [r for r in regions if r] or [None]
    for i, (query_id, q) in enumerate(queries):
        region = region_cycle[i % len(region_cycle)] if q.lang != "en" else "US"
        calls = [("exa", lambda: search.exa_search(db, spend, q.text, start)),
                 ("brave", lambda: search.brave_search(db, spend, q.li_keywords, q.lang, region, d_from, d_to))]
        calls = [c for c in calls if c[0] in providers]
        for provider, call in calls:
            try:
                results = call()
            except Exception as e:
                log.warning("%s failed for %r: %s", provider, q.text, e)
                continue
            rank = 0
            for r in results:
                it = linkedin.to_item(r)
                if not it:
                    continue
                if it["published_at"] and it["published_at"] < start:
                    continue
                rank += 1
                full = it.pop("_full_text")
                author = it.pop("author")
                if it["creator_id"]:
                    store.upsert_creator(db, {"creator_id": it["creator_id"], "platform": "linkedin",
                                              "display_name": author})
                store.upsert_item(db, it)
                record_hit(db, it["item_id"], query_id, provider, rank)
                if len(full) > len(texts.get(it["item_id"], "")):
                    texts[it["item_id"]] = full
    db.commit()
    return texts
