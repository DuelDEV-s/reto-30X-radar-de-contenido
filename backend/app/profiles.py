"""Bright Data first, with bounded official API fallbacks for public profiles."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
from urllib.parse import unquote, urlsplit

import httpx

from .schemas import BrandCreate, ProfileContent, ProfileMetric, ProfileResult
from .interpretation import interpret
from .profile_common import ProviderError, clean_text, number
from . import brightdata
from .collection_jobs import MemoryJobStore

TIMEOUT = httpx.Timeout(8, connect=4)
TTL = timedelta(minutes=15)


def official_connector_status():
    youtube = bool(os.getenv("YOUTUBE_API_KEY"))
    ig_vars = ["META_ACCESS_TOKEN", "META_IG_USER_ID", "META_GRAPH_VERSION"]
    missing = [key for key in ig_vars if not os.getenv(key)]
    return [
        {"platform": "youtube", "configured": youtube, "missing": [] if youtube else ["YOUTUBE_API_KEY"], "scope": "Canal público, contadores y hasta 8 videos públicos. La key no habilita por sí sola métricas derivadas.", "analysis_approved": os.getenv("YOUTUBE_ANALYTICS_APPROVED", "false").lower() == "true"},
        {"platform": "instagram", "configured": not missing, "missing": missing, "scope": "Business Discovery: descripción, contadores disponibles y hasta 8 publicaciones públicas de cuentas profesionales."},
        {"platform": "linkedin", "configured": False, "missing": [], "scope": "Bright Data: páginas públicas de empresa, descripción y seguidores. No perfiles personales. Sin API oficial de respaldo configurada."},
        {"platform": "tiktok", "configured": False, "missing": [], "scope": "Bright Data: cuentas públicas de marca, biografía, seguidores y total de videos. Sin API oficial de respaldo configurada."},
    ]


def connector_status():
    result = []
    for fallback in official_connector_status():
        primary = brightdata.config(fallback["platform"])
        supported = fallback["platform"] in brightdata.DATASET_ENV
        result.append({**fallback,
            "configured": primary["configured"] or fallback["configured"],
            "missing": [] if primary["configured"] or fallback["configured"] else list(dict.fromkeys(primary["missing"] + fallback["missing"])),
            "preferred_provider": "bright_data" if supported else "not_implemented",
            "primary": {"provider": "bright_data", **primary},
            "fallback": {"provider": {"youtube": "youtube_data_api", "instagram": "meta_business_discovery"}.get(fallback["platform"], "not_implemented"), "configured": fallback["configured"], "missing": fallback["missing"]},
            "scope": ("Bright Data primero; API oficial como respaldo. " if fallback["platform"] in {"instagram", "youtube"} else "") + fallback["scope"],
        })
    return result


async def get_json(client, url, params=None, headers=None):
    response = await client.get(url, params=params, headers=headers)
    if response.status_code in (401, 403):
        raise ProviderError("La fuente rechazó el acceso. Revisa permisos, credenciales y cuota en el servidor.")
    if response.status_code == 429:
        raise ProviderError("Se alcanzó el límite de consultas. Reintenta más tarde.")
    if response.status_code == 404:
        raise ProviderError("La fuente no encontró este perfil.", "not_found")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("error"):
        raise ProviderError("La fuente devolvió una respuesta no válida o un error de permisos.")
    return data


async def youtube(profile, client):
    brightdata.canonical_profile(profile.url, "youtube")  # Validate supported channel paths.
    path = re.sub(r"/(about|videos|shorts|featured)/?$", "", urlsplit(profile.url).path)
    parts = [unquote(p) for p in path.strip("/").split("/")]
    query = {}
    if len(parts) == 1 and re.fullmatch(r"@[\w.\-\u00c0-\uffff]{3,30}", parts[0]):
        query["forHandle"] = parts[0]
    elif len(parts) == 2 and parts[0] == "channel" and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", parts[1]):
        query["id"] = parts[1]
    elif len(parts) == 2 and parts[0] == "user" and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", parts[1]):
        query["forUsername"] = parts[1]
    else:
        raise ProviderError("Usa el enlace del canal: youtube.com/@handle o youtube.com/channel/UC…; no un video.", "unsupported")
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise ProviderError("Configura YOUTUBE_API_KEY en el backend para consultar este canal automáticamente.", "requires_configuration")
    data = await get_json(client, "https://www.googleapis.com/youtube/v3/channels", {
        **query, "key": key, "part": "snippet,statistics,contentDetails",
        "fields": "items(id,snippet(title,description),statistics(viewCount,subscriberCount,hiddenSubscriberCount,videoCount),contentDetails/relatedPlaylists/uploads)",
    })
    if not data.get("items"):
        raise ProviderError("No se encontró un canal público con ese identificador.", "not_found")
    channel = data["items"][0]
    snippet, stats = channel.get("snippet", {}), channel.get("statistics", {})
    result = {"title": clean_text(snippet.get("title"), 300), "description": clean_text(snippet.get("description")),
        "metrics": ProfileMetric(views=number(stats.get("viewCount")), followers=None if stats.get("hiddenSubscriberCount") else number(stats.get("subscriberCount")), posts=number(stats.get("videoCount"))),
        "metrics_notes": ["Vistas acumuladas del canal, no velocidad ni promedio por publicación. Suscriptores pueden estar redondeados u ocultos."],
        "usable_for_identity": os.getenv("YOUTUBE_ANALYTICS_APPROVED", "false").lower() == "true", "content_sample": []}
    if not result["usable_for_identity"]:
        result["metrics_notes"].append("Se muestran datos fuente; no alimentan la identidad ni scores. La analítica derivada requiere las condiciones/aprobación aplicables antes de configurar YOUTUBE_ANALYTICS_APPROVED=true.")
    playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if playlist:
        try:
            listing = await get_json(client, "https://www.googleapis.com/youtube/v3/playlistItems", {"key": key, "part": "contentDetails", "playlistId": playlist, "maxResults": 8, "fields": "items/contentDetails/videoId"})
            ids = [p["contentDetails"]["videoId"] for p in listing.get("items", []) if re.fullmatch(r"[A-Za-z0-9_-]{11}", p.get("contentDetails", {}).get("videoId", ""))]
            if ids:
                videos = await get_json(client, "https://www.googleapis.com/youtube/v3/videos", {"key": key, "part": "snippet,statistics,status", "id": ",".join(ids), "fields": "items(id,snippet(title,description,publishedAt),statistics/viewCount,status/privacyStatus)"})
                for item in videos.get("items", [])[:8]:
                    if item.get("status", {}).get("privacyStatus") != "public":
                        continue
                    s = item.get("snippet", {})
                    result["content_sample"].append(ProfileContent(url=f"https://youtu.be/{item['id']}", title=clean_text(s.get("title"), 300), text=clean_text(s.get("description"), 1000), format="video", published_at=s.get("publishedAt"), views=number(item.get("statistics", {}).get("viewCount"))))
        except (httpx.HTTPError, ValueError, KeyError, ProviderError):
            result["metrics_notes"].append("Se obtuvo el canal, pero no fue posible obtener sus videos recientes.")
    return result


async def instagram(profile, client):
    handle = urlsplit(profile.url).path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", handle) or handle in {"p", "reel", "reels", "stories", "explore", "accounts"}:
        raise ProviderError("Usa instagram.com/usuario de la marca; no una publicación o historia.", "unsupported")
    config = next(c for c in official_connector_status() if c["platform"] == "instagram")
    if not config["configured"]:
        raise ProviderError("Configura " + ", ".join(config["missing"]) + ". Business Discovery requiere acceso profesional autorizado; no usa sesiones de visitantes.", "requires_configuration")
    account, version = os.environ["META_IG_USER_ID"], os.environ["META_GRAPH_VERSION"]
    if not re.fullmatch(r"[0-9]+", account) or not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise ProviderError("Revisa META_IG_USER_ID y META_GRAPH_VERSION en el servidor.", "requires_configuration")
    fields = f"business_discovery.username({handle}){{biography,followers_count,media_count,media.limit(8){{caption,media_type,permalink,timestamp}}}}"
    data = await get_json(client, f"https://graph.facebook.com/{version}/{account}", {"fields": fields}, {"Authorization": f"Bearer {os.environ['META_ACCESS_TOKEN']}"})
    public = data.get("business_discovery")
    if not isinstance(public, dict):
        raise ProviderError("El perfil no está disponible por Business Discovery. Comprueba que sea profesional y accesible con los permisos concedidos.", "not_found")
    media = []
    for item in public.get("media", {}).get("data", [])[:8]:
        url = item.get("permalink", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.instagram.com", "instagram.com"} or parsed.query or parsed.fragment:
            continue
        caption = clean_text(item.get("caption"), 1000)
        media.append(ProfileContent(url=url, title=caption[:120], text=caption, format={"VIDEO": "video", "CAROUSEL_ALBUM": "carousel", "IMAGE": "image"}.get(item.get("media_type"), "unknown"), published_at=item.get("timestamp")))
    return {"description": clean_text(public.get("biography")), "metrics": ProfileMetric(followers=number(public.get("followers_count")), posts=number(public.get("media_count"))), "metrics_notes": ["Esta consulta pública no proporciona vistas: se muestran como no disponibles. No se consultan Insights privados ni usuarios individuales."], "content_sample": media, "usable_for_identity": True}


async def inspect_official(profile, client):
    provider = {"youtube": "youtube_data_api", "instagram": "meta_business_discovery"}.get(profile.platform, "not_implemented")
    base = {"platform": profile.platform, "url": profile.url, "provider": provider, "observed_at": datetime.now(timezone.utc), "supplied_description": clean_text(profile.description)}
    try:
        if profile.platform == "youtube":
            values = await youtube(profile, client)
        elif profile.platform == "instagram":
            values = await instagram(profile, client)
        else:
            raise ProviderError("Conector automático aún no implementado para esta red. Puedes aportar una descripción pública como contexto manual.", "unsupported")
        return ProfileResult(**base, status="ready", message="Información pública obtenida mediante la API oficial.", **values)
    except ProviderError as exc:
        return ProfileResult(**base, status=exc.status, message=exc.message)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        # Never persist exception text or upstream responses: they may contain credentials.
        return ProfileResult(**base, status="error", message="No fue posible consultar la fuente. Comprueba su disponibilidad y la configuración del servidor.")


async def inspect_one(profile, client, store=None, budget=None, refresh_bright_data=False, allow_new_jobs=True):
    if profile.platform not in brightdata.DATASET_ENV:
        return await inspect_official(profile, client)
    base = {"platform": profile.platform, "url": profile.url, "observed_at": datetime.now(timezone.utc), "supplied_description": clean_text(profile.description)}
    try:
        if profile.platform == "tiktok" and not refresh_bright_data and getattr(store, "session", None) is not None:
            # Reuse step-2 public profiles without submitting a second paid collection.
            from . import tiktok_accounts
            from .database import TikTokAccount
            canonical = brightdata.canonical_profile(profile.url, "tiktok")
            username = tiktok_accounts.username_from(canonical)
            account = store.session.get(TikTokAccount, username)
            if account and account.fetch_status == "ok" and account.raw and account.is_private is False and tiktok_accounts.aware(account.fetched_at) >= tiktok_accounts.now() - tiktok_accounts.ttl():
                raw = account.raw
                cached = {"url": canonical, "is_private": False, "nickname": account.nickname or raw.get("nickname"),
                          "biography": account.biography or raw.get("biography") or raw.get("signature"),
                          "followers": account.followers if account.followers is not None else raw.get("followers"),
                          "videos_count": account.videos_count if account.videos_count is not None else raw.get("videos_count"),
                          "likes": account.likes_total if account.likes_total is not None else raw.get("likes"),
                          "following": account.following if account.following is not None else raw.get("following"),
                          "is_verified": account.is_verified if account.is_verified is not None else raw.get("is_verified")}
                value = brightdata.normalize([cached], profile, {"state": "ready", "snapshot_id": None, "created_at": tiktok_accounts.aware(account.fetched_at)})
                value.observed_at = tiktok_accounts.aware(account.fetched_at)
                value.collection = None
                value.message = "Perfil público reutilizado de la caché del paso 2, sin una nueva extracción."
                value.attempts = [{"provider": "bright_data", "status": "ready", "message": value.message}]
                return value
        primary = await brightdata.collect(profile, client, store=store, budget=budget, refresh=refresh_bright_data, allow_new_jobs=allow_new_jobs)
        primary.attempts = [{"provider": "bright_data", "status": primary.status, "message": primary.message}]
        return primary
    except ProviderError as exc:
        attempt = {"provider": "bright_data", "status": exc.status, "code": exc.code, "message": exc.message}
        collection = getattr(exc, "collection", None)
        if exc.code in {"restricted", "invalid_profile"}:
            return ProfileResult(**base, provider="bright_data", status=exc.status, message=exc.message, attempts=[attempt], collection=collection)
        if profile.platform in {"tiktok", "linkedin"}:
            return ProfileResult(**base, provider="bright_data", status=exc.status, message=exc.message, attempts=[attempt], collection=collection)
        fallback = await inspect_official(profile, client)
        fallback.attempts = [attempt, {"provider": fallback.provider, "status": fallback.status, "message": fallback.message}]
        fallback.collection = collection
        fallback.fallback_used = fallback.status == "ready"
        fallback.message = ("Se usó el respaldo oficial. " + exc.message) if fallback.fallback_used else ("Bright Data: " + exc.message + " Respaldo: " + fallback.message)
        return fallback


def enrich_identity(brief, profiles):
    """Compatibility helper; the complete result also includes evidence and pillars."""
    from .schemas import Identity
    data = interpret(brief, profiles)
    return Identity.model_validate(data["suggested_identity"]), data["identity_evidence"]


async def build_analysis(brief: BrandCreate, client=None, job_store=None, refresh_bright_data=False, allow_new_jobs=True):
    job_store = job_store or MemoryJobStore()
    budget = brightdata.CollectionBudget()
    async def collect(c):
        semaphore = asyncio.Semaphore(3)
        async def bounded(profile):
            async with semaphore:
                try:
                    return await asyncio.wait_for(inspect_one(profile, c, store=job_store, budget=budget, refresh_bright_data=refresh_bright_data, allow_new_jobs=allow_new_jobs), timeout=55)
                except TimeoutError:
                    return ProfileResult(platform=profile.platform, url=profile.url, status="error", provider="official_api", message="La consulta excedió el tiempo disponible. Reintenta más tarde.", observed_at=datetime.now(timezone.utc), supplied_description=clean_text(profile.description))
        return await asyncio.gather(*(bounded(p) for p in brief.profiles))
    if client is None:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as c:
            profiles = await collect(c)
    else:
        profiles = await collect(client)
    now = datetime.now(timezone.utc)
    return {"schema_version": "1.0", "analyzed_at": now.isoformat(), "status": "pending" if any(p.status == "pending" for p in profiles) else "complete" if profiles and all(p.status == "ready" for p in profiles) else "partial" if any(p.status == "ready" for p in profiles) else "unavailable", "profiles": [p.model_dump(mode="json") for p in profiles], **interpret(brief, profiles)}
