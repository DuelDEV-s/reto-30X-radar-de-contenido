"""Bright Data public profile collection. One claimed POST, resumable snapshots."""
import asyncio
from datetime import datetime, timezone
import hashlib
import os
import re
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from .collection_jobs import MemoryJobStore
from .profile_common import ProviderError, clean_text, number
from .schemas import ProfileContent, ProfileMetric, ProfileResult

API = "https://api.brightdata.com/datasets/v3"
TRIGGER_TIMEOUT = httpx.Timeout(25, connect=5)
DATASET_ENV = {"instagram": "BRIGHT_DATA_INSTAGRAM_DATASET_ID", "youtube": "BRIGHT_DATA_YOUTUBE_DATASET_ID",
               "tiktok": "BRIGHT_DATA_TIKTOK_PROFILES_DATASET_ID", "linkedin": "BRIGHT_DATA_LINKEDIN_COMPANIES_DATASET_ID"}
DATASET_DEFAULTS = {"tiktok": "gd_l1villgoiiidt09ci", "linkedin": "gd_l1vikfnt1wgvvqz95w"}
OUTPUT_FIELDS = {
    "instagram": "url|profile_url|account|biography|followers|posts_count|is_private|posts",
    "youtube": "url|name|Description|subscribers|videos_count|views|top_videos",
    "tiktok": "url|account_id|nickname|biography|signature|followers|following|likes|videos_count|is_verified|is_private",
    "linkedin": "url|name|about|description|slogan|specialties|industries|followers",
}


def setting_int(name, default, minimum, maximum):
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


def config(platform):
    name = DATASET_ENV.get(platform)
    if not name:
        return {"configured": False, "missing": [], "dataset_id": None}
    dataset = os.getenv(name) or DATASET_DEFAULTS.get(platform, "")
    missing = [] if os.getenv("BRIGHT_DATA_API_KEY") else ["BRIGHT_DATA_API_KEY"]
    if not dataset:
        missing.append(name)
    if dataset and not re.fullmatch(r"gd_[A-Za-z0-9]+", dataset):
        missing.append(name + " (formato gd_…)")
    return {"configured": not missing, "missing": missing, "dataset_id": dataset}


def canonical_profile(url, platform):
    parsed = urlsplit(url)
    hosts = {"instagram": {"www.instagram.com", "instagram.com"}, "youtube": {"www.youtube.com", "youtube.com"},
             "tiktok": {"www.tiktok.com", "tiktok.com"}, "linkedin": {"www.linkedin.com", "linkedin.com"}}
    if parsed.scheme != "https" or parsed.hostname not in hosts.get(platform, set()) or parsed.username or parsed.password or parsed.port not in (443, None):
        raise ProviderError("El enlace no corresponde a un perfil público admitido.", "unsupported", "invalid_profile")
    path = unquote(parsed.path).strip("/")
    if platform == "instagram":
        if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", path) or path.lower() in {"accounts", "explore", "p", "reel", "reels", "stories", "direct"}:
            raise ProviderError("Usa el enlace de un perfil de Instagram, no una publicación o acceso de login.", "unsupported", "invalid_profile")
        path = path.lower()
    elif platform == "tiktok":
        if not re.fullmatch(r"@[A-Za-z0-9_.]{1,30}", path):
            raise ProviderError("Usa tiktok.com/@cuenta de la marca, sin enlaces de video ni de login.", "unsupported", "invalid_profile")
        path = path.lower()
    elif platform == "linkedin":
        path = re.sub(r"/about$", "", path)
        if not re.fullmatch(r"company/[A-Za-z0-9_-]{1,100}", path):
            raise ProviderError("Para LinkedIn usa una página pública de empresa: linkedin.com/company/nombre. Los perfiles personales no se recolectan.", "unsupported", "invalid_profile")
        path = path.lower()
    else:
        path = re.sub(r"/(about|videos|shorts|featured)$", "", path)
        if path.startswith("@") and re.fullmatch(r"@[\w.\-\u00c0-\uffff]{3,30}", path):
            path = path.lower()
        elif not re.fullmatch(r"channel/UC[A-Za-z0-9_-]{22}|user/[A-Za-z0-9_-]{1,100}", path):
            raise ProviderError("Usa youtube.com/@handle o /channel/UC…; no un video.", "unsupported", "invalid_profile")
    return f"https://www.{platform}.com/{path}"


class CollectionBudget:
    def __init__(self):
        self.remaining = setting_int("BRIGHT_DATA_MAX_NEW_JOBS_PER_ANALYSIS", 4, 1, 8)
        self.lock = asyncio.Lock()

    async def take(self):
        async with self.lock:
            if self.remaining <= 0:
                raise ProviderError("Se alcanzó el límite local de nuevas recolecciones por análisis. No se inició otro trabajo.", code="local_limit")
            self.remaining -= 1


def collection_info(job):
    failure = job.get("result") or {}
    return {"provider": "bright_data", "state": job["state"], "snapshot_id": job["snapshot_id"], "requested_at": job["created_at"].isoformat(), "error_code": failure.get("failure_code")}


def pending_result(profile, job):
    return ProfileResult(platform=profile.platform, url=profile.url, status="pending", provider="bright_data", message="Bright Data está recolectando el perfil. Se consultará el mismo trabajo, sin iniciar otra extracción.", observed_at=job["created_at"], collection=collection_info(job), supplied_description=clean_text(profile.description))


async def request(client, method, path, **kwargs):
    response = await client.request(method, f"{API}/{path}", headers={"Authorization": f"Bearer {os.environ['BRIGHT_DATA_API_KEY']}"}, **kwargs)
    if response.status_code in (401, 403):
        raise ProviderError("Bright Data rechazó las credenciales o el acceso al scraper.", code="access_denied")
    if response.status_code == 402:
        raise ProviderError("Bright Data requiere saldo o un plan habilitado.", code="balance")
    if response.status_code == 429:
        raise ProviderError("Bright Data alcanzó su límite de consultas o cuota.", code="quota")
    if response.status_code in (400, 422):
        # Expose only known schema field names; never upstream text, inputs or tokens.
        fields = set()
        try:
            data = response.json()
            errors = data.get("errors", []) if isinstance(data, dict) else []
            for item in errors if isinstance(errors, list) else []:
                if isinstance(item, list) and item and isinstance(item[0], str) and item[0] in {"url", "input", "dataset_id", "limit_per_input", "custom_output_fields"}:
                    fields.add(item[0])
        except ValueError:
            pass
        suffix = " Campos señalados: " + ", ".join(sorted(fields)) + "." if fields else ""
        raise ProviderError(f"Bright Data rechazó el formato o los parámetros (HTTP {response.status_code}). Revisa el scraper, la URL y el contrato de entrada del conector." + suffix, code=f"http_{response.status_code}")
    if response.status_code == 404:
        raise ProviderError("Bright Data no encontró el scraper (HTTP 404). Revisa BRIGHT_DATA_INSTAGRAM_DATASET_ID o BRIGHT_DATA_YOUTUBE_DATASET_ID y su disponibilidad.", code="dataset_not_found")
    if response.status_code >= 500 or response.status_code == 408:
        raise StartUnconfirmed(f"Bright Data respondió HTTP {response.status_code}; no se puede confirmar si inició el trabajo. Revisa las ejecuciones antes de solicitar otra recolección.", code=f"http_{response.status_code}")
    if not 200 <= response.status_code < 300:
        raise ProviderError(f"Bright Data rechazó la solicitud (HTTP {response.status_code}). Revisa la configuración del proveedor.", code=f"http_{response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise StartUnconfirmed("Bright Data respondió sin JSON válido. No se pudo confirmar el trabajo; revisa las ejecuciones antes de solicitar otro.", code="invalid_json")


def public_record(records, profile):
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ProviderError("Bright Data no devolvió exactamente un perfil verificable para esta URL.", code="unexpected_schema")
    record = records[0]
    # Never retain upstream error text: it can contain credentials or personal data.
    if record.get("is_private") is True or record.get("is_public") is False or record.get("requires_login") is True:
        raise ProviderError("El proveedor indica contenido privado o que requiere login. No se utilizará ni se intentará otro proveedor para ese contenido.", "error", "restricted")
    if record.get("error") or record.get("error_code"):
        if str(record.get("error_code", "")).lower() in {"private_profile", "requires_login", "login_required"}:
            raise ProviderError("La fuente requiere login o es privada; no se utilizará.", "error", "restricted")
        raise ProviderError("Bright Data no pudo obtener el perfil solicitado.", code="collection_failed")
    source = record.get("profile_url") or record.get("url")
    if not isinstance(source, str) or canonical_profile(source, profile.platform) != canonical_profile(profile.url, profile.platform):
        raise ProviderError("El resultado no coincide con el perfil solicitado. Se descartó.", code="profile_mismatch")
    if profile.platform in {"instagram", "tiktok"} and record.get("is_private") is not False:
        raise ProviderError("La respuesta no confirma que el perfil sea público. Se descartó.", code="public_unverified")
    return record


def normalize(records, profile, job):
    record = public_record(records, profile)
    if profile.platform in {"tiktok", "linkedin"}:
        tiktok = profile.platform == "tiktok"
        description = (record.get("biography") or record.get("signature")) if tiktok else (record.get("about") or record.get("description") or record.get("slogan"))
        if not tiktok:
            details = [clean_text(record.get(k), 500) for k in ("specialties", "industries") if isinstance(record.get(k), str)]
            description = "\n".join([clean_text(description), *details]).strip()
        metrics = ProfileMetric(followers=number(record.get("followers")), posts=number(record.get("videos_count")) if tiktok else None)
        if not clean_text(description) and all(v is None for v in metrics.model_dump().values()):
            raise ProviderError("El scraper no devolvió descripción ni contadores reconocibles.", code="unexpected_schema")
        return ProfileResult(platform=profile.platform, url=profile.url, provider="bright_data", status="ready",
                             message="Perfil público de la marca obtenido con Bright Data.", observed_at=datetime.now(timezone.utc),
                             title=clean_text(record.get("nickname") if tiktok else record.get("name"), 300), description=clean_text(description),
                             metrics=metrics, usable_for_identity=True, supplied_description=clean_text(profile.description),
                             account_details=({"likes_total": number(record.get("likes")), "following": number(record.get("following")),
                                               "is_verified": record.get("is_verified") if isinstance(record.get("is_verified"), bool) else None} if tiktok else {}),
                             metrics_notes=["Se conserva información pública de la cuenta de marca. No se recolectan empleados, contactos ni datos personales.",
                                            "Las vistas acumuladas del perfil no están disponibles; los likes de TikTok no se sustituyen por vistas. No se inicia otro scraper para obtener publicaciones."],
                             collection=collection_info({**job, "state": "ready"}))
    instagram = profile.platform == "instagram"
    description = record.get("biography") if instagram else record.get("Description", record.get("description"))
    metrics = ProfileMetric(views=None if instagram else number(record.get("views")), followers=number(record.get("followers") if instagram else record.get("subscribers")), posts=number(record.get("posts_count") if instagram else record.get("videos_count")))
    samples = []
    rows = record.get("posts" if instagram else "top_videos", [])
    for item in rows[:8] if isinstance(rows, list) else []:
        if not isinstance(item, dict) or item.get("is_private") is True or item.get("privacy_status") in {"private", "unlisted"}:
            continue
        url = item.get("url") or item.get("post_url") or item.get("video_url")
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        allowed = {"www.instagram.com", "instagram.com"} if instagram else {"www.youtube.com", "youtube.com", "youtu.be"}
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password:
            continue
        if parsed.port not in (443, None):
            continue
        if instagram:
            if not re.fullmatch(r"/(p|reel)/[A-Za-z0-9_-]+/?", parsed.path):
                continue
            url = "https://www.instagram.com" + parsed.path
        else:
            video_id = (parse_qs(parsed.query).get("v", [""])[0] if parsed.path == "/watch"
                        else parsed.path.removeprefix("/shorts/") if parsed.path.startswith("/shorts/")
                        else parsed.path.strip("/") if parsed.hostname == "youtu.be" else "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            url = "https://youtu.be/" + video_id
        # Keep only text and aggregate counters; discard authors, comments, contacts and images.
        text = clean_text(item.get("caption") or item.get("description"), 1000)
        title = clean_text(item.get("title") or text, 300)
        media_type = str(item.get("media_type", "")).upper()
        format_ = {"VIDEO": "video", "CAROUSEL_ALBUM": "carousel", "IMAGE": "image"}.get(media_type, "unknown" if instagram else "video")
        date = item.get("timestamp") or item.get("date_posted") or item.get("published_at")
        try:
            parsed_date = datetime.fromisoformat(date) if isinstance(date, str) and len(date) <= 64 else None
            date = parsed_date.isoformat() if parsed_date and parsed_date.tzinfo else None
        except ValueError:
            date = None
        samples.append(ProfileContent(url=url, title=title, text=text, format=format_, views=number(item.get("views")), published_at=date))
    title = "" if instagram else clean_text(record.get("name"), 300)
    if not clean_text(description).strip() and not title and all(v is None for v in metrics.model_dump().values()) and not samples:
        raise ProviderError("La respuesta no contiene campos de perfil reconocibles; revisa el scraper configurado.", code="unexpected_schema")
    notes = ["Datos obtenidos mediante Bright Data. Los contadores ausentes son desconocidos y no se sustituyen por cero.", "La muestra incluida depende del scraper; los videos destacados no equivalen necesariamente a publicaciones recientes."]
    if instagram:
        notes.append("El scraper de perfiles no proporciona vistas acumuladas del perfil. No se inician extracciones adicionales de Reels.")
    return ProfileResult(platform=profile.platform, url=profile.url, provider="bright_data", status="ready", message="Perfil obtenido con Bright Data.", observed_at=datetime.now(timezone.utc), description=clean_text(description), title=title, metrics=metrics, content_sample=samples, metrics_notes=notes, usable_for_identity=True, supplied_description=clean_text(profile.description), collection=collection_info({**job, "state": "ready"}))


async def collect(profile, client, store=None, budget=None, refresh=False, allow_new_jobs=True):
    store = store or MemoryJobStore()
    budget = budget or CollectionBudget()
    canonical = canonical_profile(profile.url, profile.platform)
    settings = config(profile.platform)
    if not settings["configured"]:
        raise ProviderError("Bright Data requiere " + ", ".join(settings["missing"]) + ".", "requires_configuration", "not_configured")
    dataset = settings["dataset_id"]
    key = hashlib.sha256(f"v1:{profile.platform}:{canonical}:{dataset}".encode()).hexdigest()
    current = store.get(key)
    if current is None and not allow_new_jobs:
        raise ProviderError("No hay un trabajo iniciado para este perfil. Usa Consultar análisis para solicitarlo; la consulta automática solo retoma trabajos existentes.", code="job_not_started")
    if current is None or (refresh and current["state"] not in {"pending", "requesting"}):
        await budget.take()
    job, claimed = store.claim(key, refresh=refresh)
    if claimed:
        target = canonical + "/about" if profile.platform == "youtube" else canonical
        try:
            result = await request(client, "POST", "trigger", params={"dataset_id": dataset, "include_errors": "true", "notify": "false", "custom_output_fields": OUTPUT_FIELDS[profile.platform]}, json={"input": [{"url": target}], "limit_per_input": 1}, timeout=TRIGGER_TIMEOUT)
            snapshot = result.get("snapshot_id") if isinstance(result, dict) else None
            if not isinstance(snapshot, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot):
                raise StartUnconfirmed("Bright Data respondió sin un snapshot_id válido. Revisa las ejecuciones antes de solicitar otra recolección.", code="missing_snapshot_id")
            job = store.save(job, state="pending", snapshot_id=snapshot)
            return pending_result(profile, job)
        except StartUnconfirmed as exc:
            job = store.save(job, state="unknown", message=exc.message, result={"failure_code": exc.code})
        except ProviderError as exc:
            job = store.save(job, state="failed", message=exc.message, result={"failure_code": exc.code})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            job = store.save(job, state="failed", message="No se pudo establecer conexión con Bright Data. Revisa la salida a Internet, DNS y certificados del contenedor API.", result={"failure_code": "connection_failed"})
        except httpx.TimeoutException:
            job = store.save(job, state="unknown", message="Se agotó el tiempo de respuesta al iniciar Bright Data. El trabajo podría haberse creado; revisa las ejecuciones antes de solicitar otra recolección.", result={"failure_code": "trigger_timeout"})
        except (httpx.HTTPError, ValueError, TypeError):
            # The request may have reached the provider. Never submit it again automatically.
            job = store.save(job, state="unknown", message="La conexión se interrumpió sin confirmar el inicio de la extracción. Revisa Bright Data antes de solicitar otra; no se reenviará automáticamente.", result={"failure_code": "transport_error"})
    if job["state"] == "requesting":
        if (datetime.now(timezone.utc) - job["created_at"]).total_seconds() <= 30:
            return pending_result(profile, job)
        job = store.save(job, state="unknown", message="El inicio quedó sin confirmar. Revisa Bright Data; no se repetirá automáticamente.")
    if job["state"] == "ready":
        return ProfileResult.model_validate(job["result"])
    if job["state"] != "pending":
        code = (job.get("result") or {}).get("failure_code", "restricted" if job["state"] == "restricted" else "collection_failed")
        if job["state"] == "unknown" and not (job.get("result") or {}).get("failure_code"):
            raise CollectionFailure("El intento anterior quedó sin confirmar y esta versión no dispone de su causa técnica. Consultar análisis no lo reenvía. Revisa las ejecuciones en Bright Data y, si corresponde, solicita Nueva recolección para obtener un diagnóstico actualizado.", job, code="legacy_unknown")
        raise CollectionFailure(job["message"] or "La recolección falló.", job, code=code)
    if (datetime.now(timezone.utc) - job["created_at"]).total_seconds() > setting_int("BRIGHT_DATA_JOB_TIMEOUT_SECONDS", 600, 30, 3600):
        job = store.save(job, state="failed", message="La recolección excedió el tiempo configurado. No se inició otra extracción.")
        raise CollectionFailure(job["message"], job)
    try:
        progress = await request(client, "GET", f"progress/{job['snapshot_id']}")
        status = progress.get("status") if isinstance(progress, dict) else None
        if status in {"running", "starting", "pending"}:
            return pending_result(profile, job)
        if status != "ready":
            raise ProviderError("Bright Data indicó un fallo o un estado no reconocido del trabajo.", code="collection_failed")
        records = await request(client, "GET", f"snapshot/{job['snapshot_id']}", params={"format": "json"})
        if isinstance(records, dict) and records.get("status") in {"building", "running", "pending"}:
            return pending_result(profile, job)
        value = normalize(records, profile, job)
        store.save(job, state="ready", result=value.model_dump(mode="json"))
        return value
    except ProviderError as exc:
        state = "restricted" if exc.code == "restricted" else "failed"
        job = store.save(job, state=state, message=exc.message, result={"failure_code": exc.code})
        raise CollectionFailure(exc.message, job, code=exc.code)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        job = store.save(job, state="failed", message="No fue posible consultar o descargar el trabajo de Bright Data. No se volvió a enviar la extracción.")
        raise CollectionFailure(job["message"], job)


class StartUnconfirmed(ProviderError):
    """HTTP/server ambiguity must never result in an automatic new POST."""


class CollectionFailure(ProviderError):
    def __init__(self, message, job, code="collection_failed"):
        super().__init__(message, code=code)
        self.collection = collection_info(job)
