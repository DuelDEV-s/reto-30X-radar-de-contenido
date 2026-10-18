"""Posts recientes de creadores de Instagram (Bright Data, discover by URL) para medir su línea base.

Por creador se piden como mucho POSTS_PER_CREATOR posts de los últimos POSTS_WINDOW_DAYS días. Los posts
se guardan una vez por shortcode con sus métricas más recientes y cada recolección añade una observación
al historial. Un creador cuyos posts se recogieron hace menos de INSTAGRAM_POSTS_TTL_HOURS no se paga otra vez.
"""
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .account_store import aware, now, trigger
from .brightdata import setting_int
from .creators import USERNAME
from .database import InstagramAccount, InstagramPost, InstagramPostObservation
from .post_metrics import PostSample, format_group
from .profile_common import number

POSTS_DATASET_DEFAULT = "gd_lk5ns7kz21pck8jpis"
POSTS_PER_CREATOR = 30
POSTS_WINDOW_DAYS = 30
POST_PATH = re.compile(r"/(?:[A-Za-z0-9._]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]{2,64})/?")
CONTENT_TYPES = {
    "reel": "reel", "reels": "reel", "clips": "reel", "video": "video", "igtv": "video",
    "carousel": "carousel", "carousel_container": "carousel", "sidecar": "carousel", "graphsidecar": "carousel",
    "image": "image", "photo": "image", "post": "image", "feed": "image", "graphimage": "image",
}


def posts_dataset() -> str:
    return os.getenv("BRIGHT_DATA_INSTAGRAM_POSTS_DATASET_ID") or POSTS_DATASET_DEFAULT


def ttl() -> timedelta:
    return timedelta(hours=setting_int("INSTAGRAM_POSTS_TTL_HOURS", 24, 1, 24 * 30))


def max_creators() -> int:
    return setting_int("BRIGHT_DATA_MAX_POST_CREATORS", 15, 1, 100)


def min_followers() -> int:
    """Debajo de este tamaño la línea base es ruido: pocas vistas y muy variables."""
    return setting_int("INSTAGRAM_MIN_FOLLOWERS", 2000, 0, 10**9)


def stale(db: Session, usernames: list[str]) -> list[str]:
    """Creadores sin posts recogidos o con recolección vencida, en el orden recibido."""
    cutoff = now() - ttl()
    rows = db.scalars(select(InstagramAccount).where(InstagramAccount.username.in_(usernames))).all() if usernames else []
    fresh = {r.username for r in rows if r.posts_fetched_at and aware(r.posts_fetched_at) >= cutoff}
    return [u for u in dict.fromkeys(usernames) if u not in fresh]


async def trigger_posts(client, usernames: list[str]) -> str:
    end = now()
    start = end - timedelta(days=POSTS_WINDOW_DAYS)
    inputs = [{"url": f"https://www.instagram.com/{u}", "num_of_posts": POSTS_PER_CREATOR,
               "start_date": start.strftime("%m-%d-%Y"), "end_date": end.strftime("%m-%d-%Y")} for u in usernames]
    return await trigger(client, posts_dataset(), inputs, type="discover_new", discover_by="url", limit_per_input=POSTS_PER_CREATOR)


def username_from(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    name = value.rstrip("/").rsplit("/", 1)[-1].lower().lstrip("@")
    return name if USERNAME.fullmatch(name) else None


def parse_date(value) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc)
    if isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return aware(parsed)
    return None


def content_type(record: dict) -> str:
    for key in ("product_type", "content_type", "type", "media_type"):
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower() in CONTENT_TYPES:
            return CONTENT_TYPES[value.strip().lower()]
    return "reel" if "/reel" in str(record.get("url", "")) else "unknown"


def handles(values) -> list[str]:
    names = []
    for value in values if isinstance(values, list) else []:
        name = username_from(value.get("username") if isinstance(value, dict) else value)
        if name and name not in names:
            names.append(name)
    return names


def first_number(record: dict, *keys) -> int | None:
    for key in keys:
        value = number(record.get(key))
        if value is not None:
            return value
    return None


def normalize_post(record: dict, requested: set[str]) -> dict | None:
    """Campos de un post en el formato de `instagram_posts`, o None si no es un post válido de un creador pedido.

    Los nombres varían entre versiones del scraper (comments/num_comments, datetime/date_posted…); se aceptan
    todos y el registro completo se conserva en `raw`."""
    if not isinstance(record, dict) or record.get("error") or record.get("error_code"):
        return None
    url = record.get("url")
    match = POST_PATH.fullmatch(re.sub(r"^https://(www\.)?instagram\.com", "", url.split("?")[0])) if isinstance(url, str) else None
    if not match:
        return None
    author = username_from(record.get("user_posted") or record.get("account") or record.get("owner_username"))
    source = (record.get("discovery_input") or record.get("input") or {})
    creator = username_from(source.get("url")) if isinstance(source, dict) else None
    creator = creator or author
    posted_at = parse_date(record.get("date_posted") or record.get("datetime") or record.get("timestamp"))
    if creator not in requested or posted_at is None:
        return None
    hashtags = record.get("hashtags") or record.get("post_hashtags") or []
    audio = record.get("audio")
    audio = audio.get("original_audio_title") or audio.get("title") if isinstance(audio, dict) else audio
    duration = record.get("videos_duration") or record.get("video_duration") or record.get("length")
    if isinstance(duration, list):
        # Cada elemento puede ser un número o {"url": …, "video_duration": 65.3}.
        values = [d.get("video_duration") if isinstance(d, dict) else d for d in duration]
        duration = next((d for d in values if isinstance(d, (int, float)) and not isinstance(d, bool)), None)
    return {
        "shortcode": match.group(2),
        "username": creator,
        "author": author,
        "url": f"https://www.instagram.com/{'reel' if match.group(1) in {'reel', 'reels'} else 'p'}/{match.group(2)}/",
        "content_type": content_type(record),
        "caption": record.get("description") or record.get("caption") or None,
        "hashtags": [h for h in hashtags if isinstance(h, str)][:60] if isinstance(hashtags, list) else [],
        "posted_at": posted_at,
        # Instagram devuelve -1 en likes ocultos; number() lo deja como desconocido.
        "likes": first_number(record, "likes", "num_likes"),
        "comments": first_number(record, "num_comments", "comments"),
        "views": first_number(record, "video_view_count", "views"),
        "plays": first_number(record, "video_play_count", "play_count", "plays"),
        "duration_seconds": float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        "followers": first_number(record, "followers"),
        "is_paid_partnership": record.get("is_paid_partnership") if isinstance(record.get("is_paid_partnership"), bool) else None,
        "is_pinned": record.get("is_pinned") if isinstance(record.get("is_pinned"), bool) else None,
        "coauthors": handles(record.get("coauthor_producers")),
        "tagged_users": handles(record.get("tagged_users")),
        "audio": audio[:300] if isinstance(audio, str) else None,
        "raw": record,
    }


def store_posts(db: Session, records: list, requested: list[str]) -> int:
    """Guarda los posts recibidos y una observación de sus métricas. Marca como recogidos a todos los
    creadores pedidos, también a los que no publicaron en la ventana. Devuelve cuántos posts llegaron."""
    observed = now()
    wanted = set(requested)
    stored = 0
    for record in records:
        values = normalize_post(record, wanted)
        if values is None:
            continue
        post = db.get(InstagramPost, values["shortcode"])
        if post is None:
            db.add(InstagramPost(**values, first_seen_at=observed, observed_at=observed))
        else:
            for key, value in values.items():
                setattr(post, key, value)
            post.observed_at = observed
        db.flush()
        db.add(InstagramPostObservation(shortcode=values["shortcode"], observed_at=observed,
                                        **{k: values[k] for k in ("likes", "comments", "views", "plays", "followers")}))
        stored += 1
    for name in requested:
        account = db.get(InstagramAccount, name)
        if account is not None:
            account.posts_fetched_at = observed
    db.commit()
    return stored


def recent_posts(db: Session, usernames: list[str]) -> list[InstagramPost]:
    """Posts de cada creador dentro de la ventana que termina en su última recolección."""
    if not usernames:
        return []
    accounts = db.scalars(select(InstagramAccount).where(InstagramAccount.username.in_(usernames))).all()
    fetched = {a.username: aware(a.posts_fetched_at) for a in accounts if a.posts_fetched_at}
    rows = db.scalars(select(InstagramPost).where(InstagramPost.username.in_(list(fetched)))).all()
    window = timedelta(days=POSTS_WINDOW_DAYS)
    return [p for p in rows if aware(p.posted_at) >= fetched[p.username] - window]


def sample(post: InstagramPost, followers: int | None) -> PostSample:
    return PostSample(id=post.shortcode, username=post.username, format=format_group(post.content_type),
                      posted_at=aware(post.posted_at), observed_at=aware(post.observed_at), likes=post.likes,
                      comments=post.comments, followers=post.followers or followers)


def observations(db: Session, shortcodes: list[str]) -> dict[str, list[tuple[datetime, int | None, int | None]]]:
    """Lecturas de likes y comentarios de cada post, para medir su velocidad."""
    if not shortcodes:
        return {}
    rows = db.scalars(select(InstagramPostObservation).where(InstagramPostObservation.shortcode.in_(shortcodes))).all()
    readings: dict[str, list] = {}
    for row in rows:
        readings.setdefault(row.shortcode, []).append((aware(row.observed_at), row.likes, row.comments))
    return readings
