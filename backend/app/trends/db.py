"""Engine working store (SQLite): search cache, items, YouTube snapshots and per-brand labels.
Content is global and shared by every brand; classification is per brand."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
  brand_id TEXT PRIMARY KEY, name TEXT, identity TEXT, resolved TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, brand_id TEXT, started_at TEXT, finished_at TEXT,
  status TEXT, stage TEXT, window_from TEXT, window_to TEXT,
  cost TEXT, report TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS queries (
  query_id TEXT PRIMARY KEY, run_id TEXT, text TEXT, lang TEXT, topic TEXT,
  persona_id TEXT, li_keywords TEXT);
CREATE TABLE IF NOT EXISTS creators (
  creator_id TEXT PRIMARY KEY,        -- yt:UC... | li-author:slug | li-company:slug
  platform TEXT, display_name TEXT, url TEXT, subscribers INTEGER,
  uploads_playlist TEXT, baseline TEXT, last_checked TEXT);
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,           -- yt:VIDEO_ID | li:ACTIVITY_ID | li:pulse-slug
  platform TEXT, url TEXT, creator_id TEXT, published_at TEXT,
  title TEXT, excerpt TEXT, description TEXT, lang TEXT, format TEXT,
  duration_s INTEGER, tags TEXT, evidence_level TEXT, first_seen TEXT);
CREATE TABLE IF NOT EXISTS item_query (
  item_id TEXT, query_id TEXT, provider TEXT, rank INTEGER,
  PRIMARY KEY (item_id, query_id, provider));
CREATE TABLE IF NOT EXISTS snapshots (
  item_id TEXT, captured_at TEXT, views INTEGER, likes INTEGER, comments INTEGER,
  PRIMARY KEY (item_id, captured_at));
CREATE TABLE IF NOT EXISTS item_class (
  item_id TEXT, brand_id TEXT, relevant INTEGER, topic_phrase TEXT,
  entities TEXT, hook TEXT, lang TEXT, classified_at TEXT,
  PRIMARY KEY (item_id, brand_id));
CREATE TABLE IF NOT EXISTS tracked (
  item_id TEXT, brand_id TEXT, until TEXT, PRIMARY KEY (item_id, brand_id));
CREATE TABLE IF NOT EXISTS search_cache (
  provider TEXT, cache_key TEXT, fetched_at TEXT, response TEXT,
  PRIMARY KEY (provider, cache_key));
CREATE INDEX IF NOT EXISTS idx_items_creator ON items(creator_id, published_at);
CREATE INDEX IF NOT EXISTS idx_snap_item ON snapshots(item_id, captured_at);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def connect(path=None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


# --- Cache for paid / quota-limited search calls -------------------------------
def cache_get(db, provider: str, key: str, max_age_h: float = config.SEARCH_CACHE_HOURS):
    row = db.execute("SELECT fetched_at, response FROM search_cache WHERE provider=? AND cache_key=?",
                     (provider, key)).fetchone()
    if row and now_utc() - parse_ts(row["fetched_at"]) < timedelta(hours=max_age_h):
        return json.loads(row["response"])
    return None


def cache_put(db, provider: str, key: str, response) -> None:
    db.execute("INSERT OR REPLACE INTO search_cache VALUES (?,?,?,?)",
               (provider, key, iso(now_utc()), json.dumps(response, ensure_ascii=False)))
    db.commit()


# --- Upserts ------------------------------------------------------------------
def upsert_creator(db, c: dict) -> None:
    db.execute(
        """INSERT INTO creators (creator_id, platform, display_name, url, subscribers, uploads_playlist)
           VALUES (:creator_id, :platform, :display_name, :url, :subscribers, :uploads_playlist)
           ON CONFLICT(creator_id) DO UPDATE SET
             display_name=COALESCE(excluded.display_name, display_name),
             subscribers=COALESCE(excluded.subscribers, subscribers),
             uploads_playlist=COALESCE(excluded.uploads_playlist, uploads_playlist)""",
        {"subscribers": None, "uploads_playlist": None, "url": None, **c})


def upsert_item(db, it: dict) -> None:
    row = {"title": None, "excerpt": None, "description": None, "lang": None, "duration_s": None,
           "tags": "[]", "published_at": None, "creator_id": None, **it}
    row.setdefault("first_seen", iso(now_utc()))
    db.execute(
        """INSERT INTO items (item_id, platform, url, creator_id, published_at, title, excerpt,
             description, lang, format, duration_s, tags, evidence_level, first_seen)
           VALUES (:item_id, :platform, :url, :creator_id, :published_at, :title, :excerpt,
             :description, :lang, :format, :duration_s, :tags, :evidence_level, :first_seen)
           ON CONFLICT(item_id) DO UPDATE SET
             title=COALESCE(excluded.title, title), excerpt=COALESCE(excluded.excerpt, excerpt),
             description=COALESCE(excluded.description, description),
             published_at=COALESCE(published_at, excluded.published_at),
             creator_id=COALESCE(creator_id, excluded.creator_id)""", row)


def add_snapshot(db, item_id: str, captured_at: str, views: int, likes: int, comments: int) -> None:
    db.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?)",
               (item_id, captured_at, views, likes, comments))


def latest_snapshot(db, item_id: str):
    return db.execute("SELECT * FROM snapshots WHERE item_id=? ORDER BY captured_at DESC LIMIT 1",
                      (item_id,)).fetchone()


def previous_snapshot(db, item_id: str, before: str):
    return db.execute("SELECT * FROM snapshots WHERE item_id=? AND captured_at<? "
                      "ORDER BY captured_at DESC LIMIT 1", (item_id, before)).fetchone()
