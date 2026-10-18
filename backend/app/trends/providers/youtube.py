"""YouTube Data API v3: the audience-demand sensor. Official API only."""
import re
import time

import httpx

from .. import config, db as store

API = "https://www.googleapis.com/youtube/v3"
COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1, "commentThreads": 1}


class QuotaExceeded(RuntimeError):
    pass


def iso_duration_s(iso: str | None) -> int:
    """'PT1H2M3S' -> 3723."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def video_format(duration_s: int, title: str, description: str) -> str:
    # Shorts can run up to 3 minutes; the API has no orientation field.
    text = f"{title} {description}".lower()
    return "short" if duration_s <= 180 or "#shorts" in text else "long"


def chunks(seq, n=50):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class YouTube:
    def __init__(self, db, key: str | None = None):
        self.db = db
        self.key = key or config.secret("YOUTUBE_API_KEY")
        self.units = 0
        self.http = httpx.Client(timeout=30)

    def _get(self, endpoint: str, **params) -> dict:
        self.units += COST[endpoint]
        for attempt in range(4):          # transient disconnects happen on long runs
            try:
                r = self.http.get(f"{API}/{endpoint}", params={**params, "key": self.key})
                break
            except httpx.TransportError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if r.status_code == 404:
            return {}
        if r.status_code == 403 and "quota" in r.text.lower():
            raise QuotaExceeded("YouTube daily quota exhausted")
        if r.status_code >= 400:
            msg = r.json().get("error", {}).get("message", r.text[:200]) if r.text else r.reason_phrase
            raise RuntimeError(f"YouTube {endpoint} {r.status_code}: {msg}")
        return r.json()

    # --- discovery --------------------------------------------------------
    def search(self, query: str, published_after: str, lang: str, region: str | None,
               order: str = "viewCount", max_results: int = 50) -> list[str]:
        """Video IDs in rank order. Cached 24 h because each call costs 100 units."""
        key = f"{query}|{published_after[:10]}|{lang}|{region}|{order}|{max_results}"
        cached = store.cache_get(self.db, "youtube_search", key)
        if cached is not None:
            return cached
        params = dict(part="id", q=query, type="video", order=order, maxResults=max_results,
                      publishedAfter=published_after, relevanceLanguage=lang)
        if region:
            params["regionCode"] = region
        data = self._get("search", **params)
        ids = [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        store.cache_put(self.db, "youtube_search", key, ids)
        return ids

    # --- enrichment -------------------------------------------------------
    def videos(self, ids) -> dict[str, dict]:
        out = {}
        for batch in chunks(ids):
            data = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(batch))
            for v in data.get("items", []):
                s, st = v["snippet"], v.get("statistics", {})
                if s.get("liveBroadcastContent") == "upcoming":
                    continue
                dur = iso_duration_s(v["contentDetails"].get("duration"))
                desc = s.get("description", "")[:1000]
                out[v["id"]] = {
                    "id": v["id"], "channel_id": s["channelId"], "channel_title": s["channelTitle"],
                    "title": s["title"], "description": desc, "tags": s.get("tags", []),
                    "lang": (s.get("defaultAudioLanguage") or s.get("defaultLanguage") or "")[:2],
                    "published_at": s["publishedAt"], "duration_s": dur,
                    "format": video_format(dur, s["title"], desc),
                    "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                }
        return out

    def channels(self, ids=(), handle: str | None = None) -> dict[str, dict]:
        out = {}

        def add(items):
            for c in items:
                out[c["id"]] = {
                    "id": c["id"], "title": c["snippet"]["title"],
                    "description": c["snippet"].get("description", "")[:500],
                    "subs": int(c["statistics"].get("subscriberCount", 0)),
                    "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"],
                }

        part = "snippet,statistics,contentDetails"
        if handle:
            add(self._get("channels", part=part, forHandle=handle).get("items", []))
        for batch in chunks(ids):
            add(self._get("channels", part=part, id=",".join(batch)).get("items", []))
        return out

    def recent_uploads(self, uploads_playlist: str, n: int = 50) -> list[str]:
        data = self._get("playlistItems", part="contentDetails",
                         playlistId=uploads_playlist, maxResults=min(n, 50))
        return [it["contentDetails"]["videoId"] for it in data.get("items", [])]

    def top_comments(self, video_id: str, n: int = 100) -> list[str]:
        """Comment text only. Author fields are never read."""
        data = self._get("commentThreads", part="snippet", videoId=video_id,
                         order="relevance", maxResults=min(n, 100), textFormat="plainText")
        return [it["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:500]
                for it in data.get("items", [])]
