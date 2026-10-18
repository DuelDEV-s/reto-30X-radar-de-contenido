"""Scheduled jobs: YouTube snapshots every 6 h, nightly purge (YouTube data older than 30 days)."""
from datetime import timedelta

from . import collect, db as store
from .providers.youtube import YouTube


def snapshot() -> dict:
    """Re-read stats of tracked YouTube items (1 quota unit per 50 videos)."""
    db = store.connect()
    now = store.iso(store.now_utc())
    ids = [r[0].removeprefix("yt:") for r in db.execute(
        "SELECT DISTINCT item_id FROM tracked WHERE until > ? AND item_id LIKE 'yt:%'", (now,))]
    if not ids:   # nothing tracked yet: refresh everything published in the last 30 days
        cutoff = store.iso(store.now_utc() - timedelta(days=30))
        ids = [r[0].removeprefix("yt:") for r in db.execute(
            "SELECT item_id FROM items WHERE platform='youtube' AND published_at > ?", (cutoff,))]
    yt = YouTube(db)
    collect.save_videos(db, yt.videos(ids), now)
    return {"videos": len(ids), "quota_units": yt.units, "captured_at": now}


def purge(days: int = 30) -> dict:
    """YouTube API data must be refreshed or deleted within 30 days (Developer Policies)."""
    db = store.connect()
    cutoff = store.iso(store.now_utc() - timedelta(days=days))
    n_snap = db.execute("DELETE FROM snapshots WHERE captured_at < ? AND item_id LIKE 'yt:%'", (cutoff,)).rowcount
    stale = [r[0] for r in db.execute(
        """SELECT i.item_id FROM items i WHERE i.platform='youtube'
           AND NOT EXISTS (SELECT 1 FROM snapshots s WHERE s.item_id=i.item_id)""")]
    db.executemany("DELETE FROM items WHERE item_id=?", [(i,) for i in stale])
    db.executemany("DELETE FROM item_class WHERE item_id=?", [(i,) for i in stale])
    db.execute("DELETE FROM tracked WHERE until < ?", (store.iso(store.now_utc()),))
    db.execute("DELETE FROM search_cache WHERE fetched_at < ?", (cutoff,))
    db.commit()
    return {"snapshots_deleted": n_snap, "items_deleted": len(stale)}
