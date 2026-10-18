"""Allowlisted public embeds. Never fetch an upstream URL or trust provider HTML."""
import re
from urllib.parse import parse_qs, urlsplit


IMAGE_HOSTS = {
    "youtube": ("ytimg.com", "img.youtube.com"),
    "instagram": ("cdninstagram.com", "fbcdn.net"),
    "tiktok": ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "ibytedtos.com", "byteoversea.com"),
    "linkedin": ("licdn.com",),
}


def thumbnail_url(value, platform):
    """Validate public image URLs without fetching them or accepting arbitrary hosts."""
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return None
        host = (p.hostname or "").lower()
        if any(host == suffix or host.endswith("." + suffix) for suffix in IMAGE_HOSTS.get(platform, ())):
            return value
    except ValueError:
        pass
    return None


def stored_thumbnail(record, platform):
    """Use only image fields in an already saved post. No scraping or new collection."""
    if not isinstance(record, dict) or record.get("is_private") is True or record.get("requires_login") is True:
        return None

    def candidates(value, depth=0):
        if isinstance(value, str):
            yield value
        elif depth < 3 and isinstance(value, dict):
            for key in ("cover", "origin_cover", "static_cover", "thumbnail", "url", "url_list"):
                yield from candidates(value.get(key), depth + 1)
        elif depth < 3 and isinstance(value, list):
            for item in value[:4]:
                yield from candidates(item, depth + 1)

    for key in ("thumbnail_url", "cover_url", "display_url", "preview_image", "image_url", "thumbnail", "cover", "video"):
        for value in candidates(record.get(key)):
            if safe := thumbnail_url(value, platform):
                return safe
    return None


def preview(url: str, *, demo: bool = False, thumbnail=None) -> dict:
    result = {"embed_url": None, "platform": None, "orientation": "landscape", "thumbnail_url": None}
    if demo:
        return result
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return result
        host, path = (p.hostname or "").lower(), p.path
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            code = (path.strip("/") if host == "youtu.be" else
                    path.split("/")[2] if path.startswith(("/shorts/", "/embed/")) else
                    parse_qs(p.query).get("v", [""])[0])
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", code):
                return {"platform": "youtube", "embed_url": f"https://www.youtube-nocookie.com/embed/{code}?autoplay=0", "orientation": "portrait" if path.startswith("/shorts/") else "landscape", "thumbnail_url": f"https://i.ytimg.com/vi/{code}/hqdefault.jpg"}
        if host in {"www.tiktok.com", "tiktok.com"} and (m := re.fullmatch(r"/@[\w.]+/video/(\d{15,25})/?", path)):
            return {"platform": "tiktok", "embed_url": f"https://www.tiktok.com/player/v1/{m[1]}?autoplay=0", "orientation": "portrait", "thumbnail_url": thumbnail_url(thumbnail, "tiktok")}
        if host in {"www.instagram.com", "instagram.com"} and (m := re.fullmatch(r"/(reel|p)/([A-Za-z0-9_-]{1,64})/?", path)):
            return {"platform": "instagram", "embed_url": f"https://www.instagram.com/{m[1]}/{m[2]}/embed/", "orientation": "portrait", "thumbnail_url": thumbnail_url(thumbnail, "instagram")}
        if host in {"www.linkedin.com", "linkedin.com"}:
            m = re.fullmatch(r"/feed/update/urn:li:activity:(\d{15,25})/?", path) or re.fullmatch(r"/posts/[^/]+-activity-(\d{15,25})-[^/]+/?", path)
            if m:
                return {"platform": "linkedin", "embed_url": f"https://www.linkedin.com/embed/feed/update/urn:li:activity:{m[1]}", "orientation": "portrait", "thumbnail_url": thumbnail_url(thumbnail, "linkedin")}
    except (ValueError, IndexError):
        pass
    return result


def public_url(url: str) -> str | None:
    """Source links also reject script schemes, credentials and unrelated hosts."""
    try:
        p = urlsplit(url)
        if p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and p.hostname in {
            "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "instagram.com", "www.instagram.com",
            "tiktok.com", "www.tiktok.com", "linkedin.com", "www.linkedin.com",
        }:
            return url
    except ValueError:
        pass
    return None
