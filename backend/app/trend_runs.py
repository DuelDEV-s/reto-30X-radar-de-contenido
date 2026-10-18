"""Puente entre la identidad de marca (paso 1), el motor LinkedIn + YouTube (`app/trends`) y el paso 3.

- Traduce la identidad guardada a la entrada del motor (`BrandIdentity`).
- Ejecuta el motor en segundo plano (tarda minutos) y refleja su avance por etapa en `trend_runs`.
- Exporta los videos de YouTube con vistas observadas como un lote v1 para el radar del paso 3.
  Los posts de LinkedIn no van al lote: los índices de búsqueda no exponen vistas y no se inventan.
"""
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select

from .batches import save_batch
from .database import Brand, SessionLocal, TrendRun
from .schemas import BatchCreate
from .trends import config as engine_config
from .trends.contracts import BrandIdentity, Markets

log = logging.getLogger(__name__)
ACTIVE = ("queued", "running")
STALE_AFTER = timedelta(minutes=45)     # el proceso se reinició a mitad de una corrida
MIN_SNAPSHOT_GAP = timedelta(hours=3)   # separación mínima entre observaciones exportadas al paso 3
PLACEHOLDER_TOPICS = {"por definir"}

# Región libre de la identidad -> idiomas y países de búsqueda.
REGIONS = {
    "latinoamerica": (["es"], ["MX", "CO", "AR", "CL", "PE"]),
    "latam": (["es"], ["MX", "CO", "AR", "CL", "PE"]),
    "mexico": (["es"], ["MX"]), "colombia": (["es"], ["CO"]), "argentina": (["es"], ["AR"]),
    "chile": (["es"], ["CL"]), "peru": (["es"], ["PE"]), "ecuador": (["es"], ["EC"]),
    "uruguay": (["es"], ["UY"]), "venezuela": (["es"], ["VE"]), "espana": (["es"], ["ES"]),
    "brasil": (["pt"], ["BR"]), "brazil": (["pt"], ["BR"]),
    "estados unidos": (["en"], ["US"]), "usa": (["en"], ["US"]),
}


class TrendRunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def markets_for(region: str) -> Markets:
    plain = _plain(region)
    langs: list[str] = []
    countries: list[str] = []
    for name, (lang, regions) in REGIONS.items():
        if re.search(rf"\b{re.escape(name)}\b", plain):
            langs += [l for l in lang if l not in langs]
            countries += [r for r in regions if r not in countries]
    return Markets(languages=langs, regions=countries[:6]) if langs else Markets()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _plain(text)).strip("-")[:40] or "persona"


def _youtube_handle(url: str) -> str | None:
    m = re.search(r"youtube\.com/(@[\w.\-]+)", url)
    return m.group(1) if m else None


def engine_identity(brand: Brand, platforms: list[str], window_days: int) -> BrandIdentity:
    """Entrada del motor a partir de la identidad guardada de la marca (borrador o confirmada)."""
    identity, brief = brand.identity, brand.brief
    topics = [t for t in identity.get("topics", []) if t and t.strip().lower() not in PLACEHOLDER_TOPICS]
    if not topics:
        raise TrendRunError(409, "Define al menos un tópico real en la identidad de la marca antes de buscar tendencias.")
    personas, seen = [], set()
    for p in identity["personas"]:
        pid = _slug(p["role"])
        while pid in seen:
            pid += "-2"
        seen.add(pid)
        personas.append({"id": pid, "name": p["role"][:120], "description": p["need"], "pains": []})
    handles = {"linkedin": None, "youtube": None, "website": None}
    for profile in brief.get("profiles", []):
        if profile["platform"] == "linkedin":
            handles["linkedin"] = profile["url"]
        elif profile["platform"] == "youtube":
            handles["youtube"] = _youtube_handle(profile["url"])
    summary = identity["summary"].strip()
    audience = identity.get("audience", "").strip()
    return BrandIdentity(
        brand_id=brand.id, brand_name=brief["name"],
        description=f"{summary} Audiencia: {audience}." if audience else summary,
        general_topic=topics[0], specific_topics=topics[1:7] or topics[:1],
        personas=personas, handles=handles, markets=markets_for(identity.get("region", "")),
        output_platforms=platforms, window_days=window_days)


# --- Runs ---------------------------------------------------------------------------
def summary(run: TrendRun) -> dict:
    report = run.report or {}
    return {
        "id": run.id, "brand_id": run.brand_id, "status": run.status, "stage": run.stage,
        "platforms": run.platforms, "window_days": run.window_days, "batch_id": run.batch_id,
        "cost": run.cost, "error": run.error, "created_at": run.created_at, "updated_at": run.updated_at,
        "finished_at": run.finished_at,
        "totals": {"topics": len(report.get("topics", [])), "opportunities": len(report.get("opportunities", []))}
        if report else None,
    }


def detail(run: TrendRun) -> dict:
    return {**summary(run), "identity": run.identity, "report": run.report}


def expire_stale(db, run: TrendRun) -> TrendRun:
    updated = run.updated_at if run.updated_at.tzinfo else run.updated_at.replace(tzinfo=timezone.utc)
    if run.status in ACTIVE and datetime.now(timezone.utc) - updated > STALE_AFTER:
        run.status, run.error = "failed", "La corrida se interrumpió (reinicio del servidor). Vuelve a ejecutarla."
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    return run


def list_runs(db, brand_id: str) -> list[dict]:
    rows = db.scalars(select(TrendRun).where(TrendRun.brand_id == brand_id).order_by(TrendRun.created_at.desc())).all()
    return [summary(expire_stale(db, r)) for r in rows]


def create_run(db, brand: Brand, platforms: list[str], window_days: int) -> TrendRun:
    if missing := engine_config.missing_keys():
        raise TrendRunError(503, "El radar LinkedIn + YouTube requiere " + ", ".join(missing) + " en el servidor.")
    for run in db.scalars(select(TrendRun).where(TrendRun.brand_id == brand.id, TrendRun.status.in_(ACTIVE))).all():
        if expire_stale(db, run).status in ACTIVE:
            raise TrendRunError(409, "Ya hay una corrida en curso para esta marca. Espera a que termine.")
    identity = engine_identity(brand, platforms, window_days)
    run = TrendRun(brand_id=brand.id, status="queued", stage="queued", platforms=platforms,
                   window_days=window_days, identity=identity.model_dump(mode="json"))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def make_engine_run(identity: BrandIdentity, run_id: str, on_stage):
    """Punto de sustitución en pruebas: devuelve un objeto con execute() y youtube_pieces()."""
    from .trends.pipeline import Run
    return Run(identity, run_id, on_stage)


def execute(run_id: str, session_factory=None) -> None:
    """Corre el motor completo. Se llama en segundo plano; todo error queda registrado en la corrida."""
    with (session_factory or SessionLocal)() as db:
        run = db.get(TrendRun, run_id)
        if not run:
            return

        def on_stage(name: str):
            run.status, run.stage, run.updated_at = "running", name[:40], datetime.now(timezone.utc)
            db.commit()

        try:
            on_stage("start")
            engine_run = make_engine_run(BrandIdentity.model_validate(run.identity), run.id, on_stage)
            report = engine_run.execute()
            run.report = report.model_dump(mode="json", by_alias=True)
            run.cost = report.run.cost_usd.model_dump() | {"youtube_units": report.run.sources.youtube.quota_used}
            on_stage("batch")
            batch = to_batch(engine_run.youtube_pieces(), run.id, db.get(Brand, run.brand_id).brief["name"])
            if batch:
                run.batch_id = save_batch(run.brand_id, batch, db)["id"]
            run.status, run.stage = "done", "done"
        except Exception as error:     # el informe de error es parte del historial de corridas
            log.exception("trend run %s failed", run_id)
            db.rollback()
            run = db.get(TrendRun, run_id)
            run.status, run.error = "failed", (str(error) or repr(error))[:1000]
        run.finished_at = run.updated_at = datetime.now(timezone.utc)
        db.commit()


# --- Lote v1 para el paso 3 ---------------------------------------------------------
def _piece(p: dict, run_id: str) -> dict | None:
    published = datetime.fromisoformat(p["published_at"].replace("Z", "+00:00"))
    points = sorted((datetime.fromisoformat(c.replace("Z", "+00:00")), v) for c, v in p["snapshots"])
    # El contrato exige vistas acumuladas no decrecientes: se omite el punto que lo rompe (YouTube a veces
    # descuenta vistas) en vez de corregir su valor.
    monotonic: list[tuple[datetime, int]] = []
    for observed, views in points:
        if observed >= published and (not monotonic or views >= monotonic[-1][1]):
            monotonic.append((observed, views))
    # Desde la más reciente hacia atrás, observaciones separadas al menos MIN_SNAPSHOT_GAP: dos lecturas
    # a minutos de distancia dan velocidades sin sentido.
    kept: list[tuple[datetime, int]] = []
    for observed, views in reversed(monotonic):
        if not kept or kept[-1][0] - observed >= MIN_SNAPSHOT_GAP:
            kept.append((observed, views))
    snapshots = [{"observed_at": o.isoformat(), "views": int(v)} for o, v in reversed(kept)]
    title = (p["title"] or "").strip()
    topic = p["topic"].strip().lower()[:100]
    if not snapshots or len(title) < 3 or len(topic) < 2:
        return None
    return {
        "external_id": p["video_id"], "platform": "youtube", "url": f"https://youtu.be/{p['video_id']}",
        "title": title[:300], "topic": topic, "format": "short" if p["format"] == "short" else "video",
        "hook": title[:1000], "published_at": published.isoformat(), "snapshots": snapshots[-60:],
        "source_method": "official_api",
        "source_reference": f"YouTube Data API v3 · videos.list (estadísticas públicas) · corrida de tendencias {run_id}",
    }


def to_batch(pieces: list[dict], run_id: str, brand_name: str) -> BatchCreate | None:
    """Hasta 500 videos, primero los que tienen más observaciones (permiten medir aceleración)."""
    posts = [x for x in (_piece(p, run_id) for p in pieces) if x]
    posts.sort(key=lambda x: (-len(x["snapshots"]), -x["snapshots"][-1]["views"]))
    if not posts:
        return None
    try:
        return BatchCreate(mode="public", source=f"Radar LinkedIn + YouTube · {brand_name}"[:200],
                           compliance_confirmed=True, posts=posts[:500])
    except ValidationError:
        log.exception("trend run %s produced an invalid batch", run_id)
        return None


# --- Observaciones periódicas de YouTube ----------------------------------------------
def start_snapshot_scheduler() -> threading.Thread | None:
    """Vuelve a leer las vistas de los videos seguidos cada TRENDS_SNAPSHOT_HOURS (1 unidad de cuota
    por cada 50 videos) para que el motor mida momentum real. Sin clave de YouTube no se inicia."""
    hours = engine_config.snapshot_hours()
    if hours <= 0 or not engine_config.secret("YOUTUBE_API_KEY", required=False):
        return None
    from .trends import jobs

    def loop():
        while True:
            time.sleep(hours * 3600)
            try:
                log.info("trend snapshot: %s", jobs.snapshot())
                log.info("trend purge: %s", jobs.purge())
            except Exception:
                log.exception("trend snapshot failed")

    thread = threading.Thread(target=loop, name="trend-snapshots", daemon=True)
    thread.start()
    return thread
