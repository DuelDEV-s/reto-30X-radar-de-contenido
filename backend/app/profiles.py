"""Official, bounded connectors. Never fetch a user-supplied URL or private insights."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
from urllib.parse import unquote, urlsplit

import httpx

from .schemas import BrandCreate, Identity, Persona, ProfileContent, ProfileMetric, ProfileResult
from .services import draft_identity, tokens

TIMEOUT = httpx.Timeout(8, connect=4)
TTL = timedelta(minutes=15)


def clean_text(value, limit=3000):
    text = str(value or "")[:limit]
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[correo omitido]", text)
    return re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[teléfono omitido]", text)


def number(value):
    if value is None:
        return None
    try:
        result = int(value)
        return result if result >= 0 else None
    except (ValueError, TypeError):
        return None


def connector_status():
    youtube = bool(os.getenv("YOUTUBE_API_KEY"))
    ig_vars = ["META_ACCESS_TOKEN", "META_IG_USER_ID", "META_GRAPH_VERSION"]
    missing = [key for key in ig_vars if not os.getenv(key)]
    return [
        {"platform": "youtube", "configured": youtube, "missing": [] if youtube else ["YOUTUBE_API_KEY"], "scope": "Canal público, contadores y hasta 8 videos públicos. La key no habilita por sí sola métricas derivadas.", "analysis_approved": os.getenv("YOUTUBE_ANALYTICS_APPROVED", "false").lower() == "true"},
        {"platform": "instagram", "configured": not missing, "missing": missing, "scope": "Business Discovery: descripción, contadores disponibles y hasta 8 publicaciones públicas de cuentas profesionales."},
        {"platform": "linkedin", "configured": False, "missing": [], "scope": "Conector no implementado. Se conserva el enlace y el texto aportado."},
        {"platform": "tiktok", "configured": False, "missing": [], "scope": "Conector no implementado. Se conserva el enlace y el texto aportado."},
    ]


class ProviderError(Exception):
    def __init__(self, message, status="error"):
        self.message, self.status = message, status


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
    parts = [unquote(p) for p in urlsplit(profile.url).path.strip("/").split("/")]
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
    config = next(c for c in connector_status() if c["platform"] == "instagram")
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


async def inspect_one(profile, client):
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


TOPIC_SIGNALS = {
    "agentes de IA": {"agentes", "agents"}, "automatización": {"automatizacion", "automation", "automatizar"},
    "IA en negocios": {"negocios", "empresas", "business"}, "productividad": {"productividad", "productivity"},
    "inteligencia artificial": {"inteligencia", "artificial", "ia", "ai"},
    "emprendimiento": {"emprendimiento", "emprendedores", "startup", "startups"},
    "marketing": {"marketing"}, "programación": {"programacion", "coding", "software"},
    "educación": {"educacion", "aprendizaje", "education"}, "finanzas": {"finanzas", "financiero", "finance"},
}


def enrich_identity(brief: BrandCreate, profiles: list[ProfileResult]):
    identity = draft_identity(brief)
    texts, references = [], []
    for p in profiles:
        if p.status == "ready" and p.usable_for_identity:
            texts.append(p.description)
            texts.extend(f"{c.title} {c.text}" for c in p.content_sample)
            references.append(p.url)
        if p.supplied_description:
            texts.append(p.supplied_description)
    combined = " ".join(texts)
    found = [topic for topic, signals in TOPIC_SIGNALS.items() if tokens(combined) & signals]
    if combined.strip():
        identity.summary = ((brief.description + "\n\n" if brief.description else "") + "Contexto de perfiles (descripciones y muestra disponible): " + clean_text(combined, 3500))[:5000]
        identity.topics = list(dict.fromkeys([*brief.topics, *found]))[:15] or ["por definir"]
        identity.method = "profile_rules" if references else "brief_rules"
        identity.personas = [Persona(role=identity.audience[:120], need="Hipótesis para validar con el equipo: encontrar aplicaciones concretas sobre " + ", ".join(identity.topics)[:350])]
    return Identity.model_validate(identity.model_dump()), references


async def build_analysis(brief: BrandCreate, client=None):
    async def collect(c):
        semaphore = asyncio.Semaphore(3)
        async def bounded(profile):
            async with semaphore:
                try:
                    return await asyncio.wait_for(inspect_one(profile, c), timeout=18)
                except TimeoutError:
                    return ProfileResult(platform=profile.platform, url=profile.url, status="error", provider="official_api", message="La consulta excedió el tiempo disponible. Reintenta más tarde.", observed_at=datetime.now(timezone.utc), supplied_description=clean_text(profile.description))
        return await asyncio.gather(*(bounded(p) for p in brief.profiles))
    if client is None:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as c:
            profiles = await collect(c)
    else:
        profiles = await collect(client)
    identity, references = enrich_identity(brief, profiles)
    opportunities = []
    for p in profiles:
        if p.status != "ready":
            opportunities.append({"platform": p.platform, "action": p.message, "basis": "Disponibilidad de la fuente; no se verificó este perfil."})
        elif p.usable_for_identity:
            observed = tokens(p.description + " " + " ".join(c.text + " " + c.title for c in p.content_sample))
            themes = [t for t, signals in TOPIC_SIGNALS.items() if observed & signals]
            formats = list(dict.fromkeys(c.format for c in p.content_sample))
            if not p.description:
                action = "Completar la biografía con la propuesta de valor de la marca, su audiencia y una acción concreta para el visitante."
            elif themes:
                action = f"Se detectan señales textuales de {', '.join(themes[:3])}. Probar una pieza con un caso concreto para {brief.audience or 'la audiencia que confirme el equipo'} y mantener esos pilares visibles en la biografía."
                if formats:
                    action += f" La muestra contiene estos formatos: {', '.join(formats)}; comparar alternativas mediante un experimento editorial."
            else:
                action = "Revisar con el equipo los pilares de contenido a partir de la biografía y la muestra; no hay coincidencias con el vocabulario temático actual."
            opportunities.append({"platform": p.platform, "action": action, "basis": "Descripción y muestra pública de " + p.url + ". Hipótesis por reglas; no atribuye resultados a un formato."})
        else:
            opportunities.append({"platform": p.platform, "action": "Completar la habilitación de uso analítico antes de incorporar estos datos a la identidad.", "basis": "Datos mostrados solo como información de la fuente."})
    now = datetime.now(timezone.utc)
    return {"schema_version": "1.0", "analyzed_at": now.isoformat(), "status": "complete" if profiles and all(p.status == "ready" for p in profiles) else "partial" if any(p.status == "ready" for p in profiles) else "unavailable", "profiles": [p.model_dump(mode="json") for p in profiles], "suggested_identity": identity.model_dump(mode="json"), "identity_evidence": references, "opportunities": opportunities, "method": "Reglas léxicas sobre textos disponibles. Las métricas se muestran con su procedencia y no se convierten en scores de perfil. Audiencia y personas requieren revisión humana."}
