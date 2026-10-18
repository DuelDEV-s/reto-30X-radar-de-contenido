"""Videos de TikTok (Bright Data, scraper de posts) para la búsqueda por tópico y la línea base de cada creador.

El mismo scraper sirve para las dos cosas:
- discover by keyword: videos sobre las palabras clave de la búsqueda (ver `tiktok_search`).
- discover by profile_url: videos de los últimos POSTS_WINDOW_DAYS días de un creador, como mucho
  POSTS_PER_CREATOR, para su línea base. Un creador recogido hace menos de TIKTOK_POSTS_TTL_HOURS no se paga
  otra vez.

Cada video se guarda una vez por id con sus métricas más recientes y cada recolección añade una observación.
Los nombres de campo varían entre versiones del scraper (digg_count/likes, play_count/views…); se aceptan
todos y el registro completo se conserva en `raw`.
"""
import os
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .account_store import aware, now, trigger
from .brightdata import setting_int
from .database import TikTokAccount, TikTokPost, TikTokPostObservation
from .post_metrics import PostSample, format_group
from .post_store import first_number, parse_date
from .tiktok_accounts import profile_url, username_from

POSTS_DATASET_DEFAULT = "gd_lu702nij2f790tmv9h"
POSTS_PER_CREATOR = 30
POSTS_WINDOW_DAYS = 30
VIDEO_PATH = re.compile(r"/@([A-Za-z0-9._]{1,30})/(video|photo)/(\d{5,30})/?")
IMAGE_TYPES = {"photo", "image", "images", "carousel", "slideshow"}


def posts_dataset() -> str:
    return os.getenv("BRIGHT_DATA_TIKTOK_POSTS_DATASET_ID") or POSTS_DATASET_DEFAULT


def ttl() -> timedelta:
    return timedelta(hours=setting_int("TIKTOK_POSTS_TTL_HOURS", 24, 1, 24 * 30))


def timeout_seconds() -> int:
    return setting_int("TIKTOK_POSTS_TIMEOUT_SECONDS", 2700, 300, 7200)


def max_creators() -> int:
    return setting_int("BRIGHT_DATA_MAX_POST_CREATORS", 15, 1, 100)


def min_followers() -> int:
    """Debajo de este tamaño la línea base es ruido. En TikTok el alcance no depende tanto de los seguidores,
    pero una cuenta casi sin audiencia propia no es un creador de referencia."""
    return setting_int("TIKTOK_MIN_FOLLOWERS", 5000, 0, 10**9)


def stale(db: Session, usernames: list[str]) -> list[str]:
    """Creadores sin videos recogidos o con recolección vencida, en el orden recibido."""
    cutoff = now() - ttl()
    rows = db.scalars(select(TikTokAccount).where(TikTokAccount.username.in_(usernames))).all() if usernames else []
    fresh = {r.username for r in rows if r.posts_fetched_at and aware(r.posts_fetched_at) >= cutoff}
    return [u for u in dict.fromkeys(usernames) if u not in fresh]


async def trigger_posts(client, usernames: list[str]) -> str:
    end = now()
    start = end - timedelta(days=POSTS_WINDOW_DAYS)
    inputs = [{"url": profile_url(u), "num_of_posts": POSTS_PER_CREATOR,
               "start_date": start.strftime("%m-%d-%Y"), "end_date": end.strftime("%m-%d-%Y")} for u in usernames]
    return await trigger(client, posts_dataset(), inputs, type="discover_new", discover_by="profile_url", limit_per_input=POSTS_PER_CREATOR)


def text_value(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("title") or value.get("name") or value.get("original_sound_title")
    return value if isinstance(value, str) and value.strip() else None


def hashtag_names(values) -> list[str]:
    names = []
    for value in values if isinstance(values, list) else []:
        name = text_value(value) if isinstance(value, dict) else value
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names[:60]


def normalize_post(record: dict, requested: set[str] | None = None) -> dict | None:
    """Campos de un video en el formato de `tiktok_posts`, o None si no es un video válido.

    Con `requested`, solo videos de esos creadores (línea base por perfil). Sin él, cualquier autor
    (resultados de la búsqueda por palabra clave): el creador es quien lo publicó."""
    if not isinstance(record, dict) or record.get("error") or record.get("error_code"):
        return None
    url = record.get("url") or record.get("post_url")
    parsed = re.sub(r"^https://(www\.|m\.)?tiktok\.com", "", url.split("?")[0]) if isinstance(url, str) else ""
    match = VIDEO_PATH.fullmatch(parsed)
    video_id = str(record.get("post_id") or (match.group(3) if match else "")).strip()
    if not re.fullmatch(r"\d{5,30}", video_id):
        return None
    author = username_from(record.get("profile_username")) or username_from(record.get("profile_url")) or (match.group(1).lower() if match else None)
    source = record.get("discovery_input") or record.get("input") or {}
    creator = username_from(source.get("url")) if isinstance(source, dict) else None
    creator = creator or author
    posted_at = parse_date(record.get("create_time") or record.get("date_posted") or record.get("create_date"))
    if creator is None or posted_at is None or (requested is not None and creator not in requested):
        return None
    kind = str(record.get("post_type") or record.get("content_type") or "").strip().lower()
    image = kind in IMAGE_TYPES or (match and match.group(2) == "photo")
    duration = record.get("video_duration") or record.get("duration")
    return {
        "video_id": video_id,
        "username": creator,
        "author": author,
        "url": f"https://www.tiktok.com/@{author or creator}/{'photo' if image else 'video'}/{video_id}",
        "content_type": "image" if image else "video",
        "caption": record.get("description") or record.get("caption") or record.get("title") or None,
        "hashtags": hashtag_names(record.get("hashtags") or record.get("post_hashtags")),
        "posted_at": posted_at,
        "views": first_number(record, "play_count", "views", "view_count"),
        "likes": first_number(record, "digg_count", "likes", "like_count"),
        "comments": first_number(record, "comment_count", "comments", "num_comments"),
        "shares": first_number(record, "share_count", "shares"),
        "saves": first_number(record, "collect_count", "saves", "favorites_count"),
        "duration_seconds": float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        "followers": first_number(record, "profile_followers", "followers"),
        "audio": (text_value(record.get("original_sound")) or text_value(record.get("music")) or "")[:300] or None,
        "raw": record,
    }


def save(db: Session, rows: list[dict], observed: datetime) -> int:
    """Guarda los videos normalizados y una observación de sus métricas. Devuelve cuántos se guardaron."""
    for values in rows:
        post = db.get(TikTokPost, values["video_id"])
        if post is None:
            db.add(TikTokPost(**values, first_seen_at=observed, observed_at=observed))
        else:
            for key, value in values.items():
                # Un video encontrado en la búsqueda que luego llega por el perfil de un coautor conserva su creador.
                if key != "username":
                    setattr(post, key, value)
            post.observed_at = observed
        db.flush()
        db.add(TikTokPostObservation(video_id=values["video_id"], observed_at=observed,
                                     **{k: values[k] for k in ("views", "likes", "comments", "shares", "saves", "followers")}))
    return len(rows)


def store_posts(db: Session, records: list, requested: list[str]) -> int:
    """Guarda los videos recibidos de los perfiles pedidos y marca como recogidos a todos esos creadores,
    también a los que no publicaron en la ventana. Devuelve cuántos videos llegaron."""
    observed, wanted = now(), set(requested)
    rows = list({v["video_id"]: v for v in (normalize_post(r, wanted) for r in records) if v}.values())
    stored = save(db, rows, observed)
    for name in requested:
        account = db.get(TikTokAccount, name)
        if account is not None:
            account.posts_fetched_at = observed
    db.commit()
    return stored


def recent_posts(db: Session, usernames: list[str]) -> list[TikTokPost]:
    """Videos de cada creador dentro de la ventana que termina en su última recolección."""
    if not usernames:
        return []
    accounts = db.scalars(select(TikTokAccount).where(TikTokAccount.username.in_(usernames))).all()
    fetched = {a.username: aware(a.posts_fetched_at) for a in accounts if a.posts_fetched_at}
    rows = db.scalars(select(TikTokPost).where(TikTokPost.username.in_(list(fetched)))).all()
    window = timedelta(days=POSTS_WINDOW_DAYS)
    return [p for p in rows if aware(p.posted_at) >= fetched[p.username] - window]


def sample(post: TikTokPost, followers: int | None) -> PostSample:
    return PostSample(id=post.video_id, username=post.username, format=format_group(post.content_type),
                      posted_at=aware(post.posted_at), observed_at=aware(post.observed_at), likes=post.likes,
                      comments=post.comments, followers=post.followers or followers, views=post.views,
                      shares=post.shares, platform="tiktok")


def observations(db: Session, video_ids: list[str]) -> dict[str, list[tuple[datetime, int | None, int | None]]]:
    """Lecturas de likes y comentarios de cada video, para medir su velocidad."""
    if not video_ids:
        return {}
    rows = db.scalars(select(TikTokPostObservation).where(TikTokPostObservation.video_id.in_(video_ids))).all()
    readings: dict[str, list] = {}
    for row in rows:
        readings.setdefault(row.video_id, []).append((aware(row.observed_at), row.likes, row.comments))
    return readings

