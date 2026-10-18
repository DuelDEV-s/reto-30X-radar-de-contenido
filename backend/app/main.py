import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .batches import save_batch
from .database import Brand, ProfileAnalysis, TrendBatch, get_session
from .demo import demo_batch, demo_brief
from .discovery import discover_creators, geo_targets
from . import discovery_store
from .query_builder import QueryContext, build_queries
from .schemas import BatchCreate, BrandCreate, CreatorSearchRequest, DiscoveryQueryRequest, Identity, Platform, ProfileAnalysisRequest, InterpretationRequest, ProfileResult, TikTokSearchRequest, TrendRunRequest
from .post_resolver import OEmbedResolver, PostResolver
from . import related_accounts
from . import account_review
from . import transcription
from . import post_review
from . import content_patterns, tiktok_accounts, topic_trends
from . import tiktok_search as tiktok_search_module
from .account_store import account_dict
from .database import DiscoveryRun, InstagramAccount, RelatedAccount, RelatedAccountRun, TikTokAccount
from .profile_common import ProviderError
from .serp import BrightDataSerpClient, SerpClient, SerpError
from .services import analyze, draft_identity
from .profiles import build_analysis, connector_status, TTL
from datetime import datetime, timezone
from .collection_jobs import DBJobStore
from .interpretation import interpret, VERSION as INTERPRETATION_VERSION
from . import trend_runs
from .database import TrendRun
from .trends import config as trends_config

# Uvicorn solo configura sus propios loggers; esto hace visibles los logs INFO de app.* en `docker compose logs api`.
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s:     %(name)s: %(message)s")
# httpx registra la URL completa de cada petición y las de YouTube llevan la API key.
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app):
    trend_runs.start_snapshot_scheduler()
    yield


app = FastAPI(title="30X Radar de contenido", version="0.1.0", lifespan=lifespan, description="Pasos 1 y 3. Perfiles públicos con Bright Data y APIs oficiales de respaldo. Ingesta v1 para el paso 2. Radar de tendencias LinkedIn + YouTube con APIs oficiales.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","), allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type"])
DB = Annotated[Session, Depends(get_session)]


def get_serp_client():
    try:
        client = BrightDataSerpClient.from_env()
    except SerpError as error:
        raise HTTPException(503, str(error))
    try:
        yield client
    finally:
        client.close()


SERP = Annotated[SerpClient, Depends(get_serp_client)]


def get_post_resolver():
    resolver = OEmbedResolver()
    try:
        yield resolver
    finally:
        resolver.close()


RESOLVER = Annotated[PostResolver, Depends(get_post_resolver)]


async def get_bright_data_client():
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=False, trust_env=False) as client:
        yield client


BRIGHT_DATA = Annotated[httpx.AsyncClient, Depends(get_bright_data_client)]


def get_reviewer():
    """Revisor LLM de cuentas, o None si no hay OPENAI_API_KEY: las cuentas quedan pendientes de revisión."""
    return account_review.OpenAIReviewer() if account_review.is_configured() else None


REVIEWER = Annotated[account_review.Reviewer | None, Depends(get_reviewer)]


def get_transcriber():
    """Transcriptor de reels, o None si no hay OPENAI_API_KEY: los reels quedan sin transcribir."""
    return transcription.OpenAITranscriber() if transcription.is_configured() else None


TRANSCRIBER = Annotated[transcription.Transcriber | None, Depends(get_transcriber)]


def get_post_reviewer():
    """Revisor de relevancia por post, o None sin OPENAI_API_KEY: sin revisión tampoco se transcribe."""
    return post_review.OpenAIPostReviewer() if account_review.is_configured() else None


POST_REVIEWER = Annotated[post_review.PostReviewer | None, Depends(get_post_reviewer)]


def get_video_analyzer():
    """Analizador de producción de reels (Gemini), o None sin GEMINI_API_KEY."""
    return content_patterns.GeminiAnalyzer() if content_patterns.is_configured() else None


VIDEO_ANALYZER = Annotated[content_patterns.VideoAnalyzer | None, Depends(get_video_analyzer)]


def get_topic_grouper():
    return topic_trends.OpenAITopicGrouper() if account_review.is_configured() else None


TOPIC_GROUPER = Annotated[topic_trends.OpenAITopicGrouper | None, Depends(get_topic_grouper)]


async def enrich_run_posts(db, run, post_reviewer, transcriber, media, analyzer=None):
    """Con los posts listos: una tanda de revisión de relevancia, otra de transcripción de reels relevantes y,
    cuando la revisión termina, otra de análisis de video. Todo antes de que venzan los enlaces del CDN."""
    if post_reviewer:
        await discovery_store.review_run_posts(db, run, post_reviewer)
    if post_reviewer and transcriber:
        await discovery_store.transcribe_run(db, run, transcriber, media)
    if analyzer:
        await discovery_store.analyze_run_content(db, run, analyzer, media)


async def get_media_client():
    """Descarga de videos del CDN de Instagram (no lleva credenciales)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=True, trust_env=False) as client:
        yield client


MEDIA = Annotated[httpx.AsyncClient, Depends(get_media_client)]


def get_brand(brand_id, db):
    brand = db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(404, "Marca no encontrada")
    return brand


def brand_output(brand, db):
    analysis = db.get(ProfileAnalysis, brand.id)
    data = dict(analysis.data) if analysis else None
    if data:
        data.pop("input_fingerprint", None)
        data.pop("auto_apply_digest", None)
        data["stale"] = datetime.now(timezone.utc) - datetime.fromisoformat(data["analyzed_at"]) > TTL
    return {"id": brand.id, "brief": brand.brief, "identity": brand.identity, "created_at": brand.created_at, "profile_analysis": data}


async def inspect_brand(brand, db, request):
    values = dict(brand.brief)
    if request.profiles is not None:
        values["profiles"] = [p.model_dump(mode="json") for p in request.profiles]
        values["brand_accounts_confirmed"] = request.brand_accounts_confirmed
    brief = BrandCreate.model_validate(values)
    fingerprint = hashlib.sha256(json.dumps({"brief": brief.model_dump(mode="json"), "connectors": connector_status(), "interpretation_version": INTERPRETATION_VERSION}, sort_keys=True).encode()).hexdigest()
    row = db.get(ProfileAnalysis, brand.id)
    identity_digest = hashlib.sha256(json.dumps(brand.identity, sort_keys=True).encode()).hexdigest()
    auto_apply = row and row.data.get("auto_apply_digest") == identity_digest and brand.identity.get("status") == "draft"
    fresh = row and row.data.get("status") != "pending" and datetime.now(timezone.utc) - datetime.fromisoformat(row.data["analyzed_at"]) < TTL
    if request.force or request.refresh_bright_data or not fresh or row.data.get("input_fingerprint") != fingerprint:
        allow_new_jobs = not (row and row.data.get("status") == "pending" and not request.force and not request.refresh_bright_data)
        data = await build_analysis(brief, job_store=DBJobStore(db, brand.id), refresh_bright_data=request.refresh_bright_data, allow_new_jobs=allow_new_jobs)
        # Another request may have confirmed or edited the identity while HTTP was pending.
        db.refresh(brand)
        current_digest = hashlib.sha256(json.dumps(brand.identity, sort_keys=True).encode()).hexdigest()
        auto_apply = bool(auto_apply and current_digest == identity_digest and brand.identity.get("status") == "draft")
        data["input_fingerprint"] = fingerprint
        if (request.apply_to_identity or auto_apply) and data["status"] == "pending":
            data["auto_apply_digest"] = hashlib.sha256(json.dumps(data["suggested_identity"], sort_keys=True).encode()).hexdigest()
        if row:
            row.data = data
            row.analyzed_at = datetime.now(timezone.utc)
        else:
            row = ProfileAnalysis(brand_id=brand.id, data=data)
            db.add(row)
    brand.brief = brief.model_dump(mode="json")
    if request.apply_to_identity or auto_apply:
        brand.identity = row.data["suggested_identity"]
    db.commit()
    return brand_output(brand, db)


def save_brand(brief, db):
    brand = Brand(brief=brief.model_dump(mode="json"), identity=draft_identity(brief).model_dump(mode="json"))
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


@app.get("/api/health", tags=["system"])
def health(db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/brands", status_code=201, tags=["step-1"])
async def create_brand(brief: BrandCreate, db: DB):
    brand = save_brand(brief, db)
    if brief.profiles:
        return await inspect_brand(brand, db, ProfileAnalysisRequest(apply_to_identity=True))
    return brand_output(brand, db)


@app.get("/api/brands", tags=["step-1"])
def list_brands(db: DB):
    return [brand_output(b, db) for b in db.scalars(select(Brand).order_by(Brand.created_at.desc())).all()]


@app.get("/api/brands/{brand_id}", tags=["step-1"])
def read_brand(brand_id: str, db: DB):
    return brand_output(get_brand(brand_id, db), db)


@app.put("/api/brands/{brand_id}/identity", tags=["step-1"])
def update_identity(brand_id: str, identity: Identity, db: DB):
    brand = get_brand(brand_id, db)
    brand.identity = identity.model_copy(update={"method": "human_review"}).model_dump(mode="json")
    db.commit()
    return brand_output(brand, db)


@app.get("/api/profile-connectors", tags=["step-1"])
def profile_connectors():
    return connector_status()


@app.post("/api/brands/{brand_id}/profiles/analyze", tags=["step-1"])
async def analyze_profiles(brand_id: str, request: ProfileAnalysisRequest, db: DB):
    brand = get_brand(brand_id, db)
    try:
        return await inspect_brand(brand, db, request)
    except ValueError:
        raise HTTPException(422, "Revisa los perfiles y confirma que son cuentas públicas de la marca.")


@app.post("/api/brands/{brand_id}/profiles/interpret", tags=["step-1"])
def reinterpret_profiles(brand_id: str, request: InterpretationRequest, db: DB):
    """Pure local reinterpretation of stored observations; never calls a provider."""
    brand = get_brand(brand_id, db)
    row = db.get(ProfileAnalysis, brand_id)
    if not row:
        raise HTTPException(409, "Primero guarda un análisis de perfiles para poder reinterpretarlo.")
    brief = BrandCreate.model_validate(brand.brief)
    profiles = [ProfileResult.model_validate(p) for p in row.data.get("profiles", [])]
    data = {**row.data, **interpret(brief, profiles)}
    data.pop("auto_apply_digest", None)
    row.data = data
    if request.apply_to_identity:
        brand.identity = data["suggested_identity"]
    db.commit()
    return brand_output(brand, db)


@app.post("/api/brands/{brand_id}/trend-batches", status_code=201, tags=["step-2-contract"])
def ingest(brand_id: str, batch: BatchCreate, db: DB):
    get_brand(brand_id, db)
    return save_batch(brand_id, batch, db)


@app.get("/api/brands/{brand_id}/trend-batches", tags=["step-2-contract"])
def batches(brand_id: str, db: DB):
    get_brand(brand_id, db)
    rows = db.scalars(select(TrendBatch).where(TrendBatch.brand_id == brand_id).order_by(TrendBatch.created_at.desc())).all()
    return [{"id": row.id, "mode": row.data["mode"], "source": row.data["source"], "posts": len(row.data["posts"]), "created_at": row.created_at} for row in rows]


@app.get("/api/brands/{brand_id}/report", tags=["step-3"])
def report(brand_id: str, db: DB, batch_id: str | None = None, platform: Platform | None = None, topic: str | None = Query(None, max_length=100), limit: int = Query(10, ge=1, le=50), window_days: int = Query(7, ge=1, le=90)):
    brand = get_brand(brand_id, db)
    query = select(TrendBatch).where(TrendBatch.brand_id == brand_id)
    if batch_id:
        query = query.where(TrendBatch.id == batch_id)
    rows = db.scalars(query.order_by(TrendBatch.created_at.desc())).all()
    # Public datasets are the default; a demo must be explicitly selected by id.
    row = next((r for r in rows if batch_id or r.data["mode"] == "public"), None)
    if not row:
        raise HTTPException(404, "No hay un lote público. Importa datos del paso 2 o selecciona explícitamente un lote demo.")
    return {"brand_id": brand_id, "batch_id": row.id, "identity_status": brand.identity["status"], **analyze(BatchCreate.model_validate(row.data), brand.identity, platform=platform, topic=topic, limit=limit, window_days=window_days)}


@app.post("/api/brands/{brand_id}/discovery-queries", tags=["step-2-discovery"])
def discovery_queries(brand_id: str, request: DiscoveryQueryRequest, db: DB):
    brand = get_brand(brand_id, db)
    ctx = QueryContext.from_identity(brand.identity, focus_topic=request.topic, platform=request.platform, max_queries=request.max_queries, profiles_only=request.profiles_only)
    return {"brand_id": brand_id, "identity_status": brand.identity["status"], **build_queries(ctx).model_dump()}


@app.post("/api/brands/{brand_id}/creator-search", tags=["step-2-discovery"])
def creator_search(brand_id: str, request: CreatorSearchRequest, db: DB, serp: SERP, resolver: RESOLVER):
    brand = get_brand(brand_id, db)
    plan = build_queries(QueryContext.from_identity(brand.identity, focus_topic=request.topic, max_queries=request.max_queries, profiles_only=request.profiles_only))
    countries = geo_targets(brand.identity["region"], request.countries)
    result = discover_creators(plan, serp, countries=countries, resolver=resolver if request.resolve_posts else None)
    # Toda corrida se guarda, también las fallidas: el historial de búsquedas no se pierde.
    run = discovery_store.save_run(db, brand, plan, result, topic=request.topic, countries=countries, max_queries=request.max_queries,
                                   profiles_only=request.profiles_only, resolve_posts=request.resolve_posts)
    if run.status == "failed":
        raise HTTPException(502, f"{result.queries[0].error} (corrida {run.id})")
    return {"run_id": run.id, "brand_id": brand_id, "identity_status": brand.identity["status"], **result.model_dump(exclude={"outcomes"})}


@app.post("/api/brands/{brand_id}/tiktok-search", status_code=202, tags=["step-2-discovery"])
async def tiktok_search(brand_id: str, request: TikTokSearchRequest, db: DB, client: BRIGHT_DATA):
    """Busca videos de TikTok por palabras clave de la identidad (Bright Data, discover by keyword) y crea la
    corrida. La búsqueda es asíncrona: GET /api/discovery-runs/{id} la avanza hasta tener candidatos."""
    brand = get_brand(brand_id, db)
    if not os.getenv("BRIGHT_DATA_API_KEY"):
        raise HTTPException(503, "Bright Data requiere BRIGHT_DATA_API_KEY.")
    plan = build_queries(QueryContext.from_identity(brand.identity, focus_topic=request.topic, platform="tiktok", max_queries=request.max_queries))
    run = await discovery_store.start_tiktok_search(db, brand, plan, client, topic=request.topic, max_queries=request.max_queries,
                                                    per_keyword=request.videos_per_keyword or tiktok_search_module.videos_per_keyword())
    return discovery_store.detail(db, run)


@app.get("/api/brands/{brand_id}/discovery-runs", tags=["step-2-discovery"])
def discovery_runs(brand_id: str, db: DB):
    """Historial de búsquedas por tópico de la marca, de la más reciente a la más antigua."""
    get_brand(brand_id, db)
    return discovery_store.list_runs(db, brand_id)


@app.get("/api/discovery-runs/{run_id}", tags=["step-2-discovery"])
async def discovery_run(run_id: str, db: DB, client: BRIGHT_DATA):
    """Detalle de una corrida: identidad usada, queries con sus resultados (Google o videos de TikTok) y candidatos.
    En TikTok consulta la búsqueda en curso sin iniciar otra."""
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    if run.search_state in discovery_store.PROFILES_ACTIVE and not discovery_store.missing_config(run):
        run = await discovery_store.advance_search(db, run, client)
    return discovery_store.detail(db, run)


@app.post("/api/brands/{brand_id}/related-accounts", tags=["step-1"])
async def start_related_accounts(brand_id: str, db: DB, client: BRIGHT_DATA, reviewer: REVIEWER):
    """Inicia la búsqueda de cuentas relacionadas (reels de la marca) o devuelve la que está en curso."""
    brand = get_brand(brand_id, db)
    if missing := related_accounts.missing_config():
        raise HTTPException(503, "Bright Data requiere " + ", ".join(missing) + ".")
    try:
        run = await related_accounts.start(db, brand, client)
    except ProviderError as error:
        raise HTTPException(400, error.message)
    run = await related_accounts.advance(db, run, client)
    await review_related(db, brand, run, reviewer)
    return related_accounts.output(db, brand_id, run)


async def review_related(db, brand, run, reviewer):
    if reviewer and run and run.state == "ready":
        names = [r.username for r in db.scalars(select(RelatedAccount).where(RelatedAccount.brand_id == brand.id)).all()]
        await account_review.review_accounts(db, brand, names, reviewer)


@app.get("/api/brands/{brand_id}/related-accounts", tags=["step-1"])
async def read_related_accounts(brand_id: str, db: DB, client: BRIGHT_DATA, reviewer: REVIEWER):
    """Cuentas guardadas con su veredicto. Consulta la búsqueda en curso sin iniciar extracciones nuevas
    y revisa con el LLM las cuentas que aún no tengan veredicto vigente."""
    brand = get_brand(brand_id, db)
    run = db.get(RelatedAccountRun, brand_id)
    if run and run.state in related_accounts.ACTIVE and not related_accounts.missing_config():
        run = await related_accounts.advance(db, run, client)
    await review_related(db, brand, run, reviewer)
    return related_accounts.output(db, brand_id, run)


@app.get("/api/instagram-accounts/{username}", tags=["step-1"])
def instagram_account(username: str, db: DB):
    """Ficha guardada de una cuenta de Instagram (compartida entre marcas y corridas)."""
    account = db.get(InstagramAccount, username.lower())
    if not account:
        raise HTTPException(404, "Cuenta no guardada")
    return account_dict(account.username, account)


@app.get("/api/instagram-accounts/{username}/avatar", tags=["step-1"])
def instagram_account_avatar(username: str, db: DB):
    account = db.get(InstagramAccount, username.lower())
    if not account or not account.avatar:
        raise HTTPException(404, "Sin foto guardada")
    return Response(account.avatar, media_type=account.avatar_type or "image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/tiktok-accounts/{username}", tags=["step-2-discovery"])
def tiktok_account(username: str, db: DB):
    """Ficha guardada de una cuenta de TikTok (compartida entre marcas y corridas)."""
    account = db.get(TikTokAccount, username.lower())
    if not account:
        raise HTTPException(404, "Cuenta no guardada")
    return tiktok_accounts.account_dict(account.username, account)


@app.get("/api/tiktok-accounts/{username}/avatar", tags=["step-2-discovery"])
def tiktok_account_avatar(username: str, db: DB):
    account = db.get(TikTokAccount, username.lower())
    if not account or not account.avatar:
        raise HTTPException(404, "Sin foto guardada")
    return Response(account.avatar, media_type=account.avatar_type or "image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/discovery-runs/{run_id}/profiles", tags=["step-2-discovery"])
async def start_run_profiles(run_id: str, db: DB, client: BRIGHT_DATA, reviewer: REVIEWER):
    """Trae la ficha de perfil de los candidatos de la corrida. Solo paga los que no estén guardados y vigentes."""
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    if missing := discovery_store.missing_config(run):
        raise HTTPException(503, "Bright Data requiere " + ", ".join(missing) + ".")
    try:
        run = await discovery_store.start_profiles(db, run, client)
    except ProviderError as error:
        raise HTTPException(409, error.message)
    await review_run(db, run, reviewer)
    return discovery_store.detail(db, run)


async def review_run(db, run, reviewer):
    if reviewer and run.profiles_state == "ready":
        # Por tandas: la vista consulta cada pocos segundos y la revisión avanza sin bloquear la respuesta.
        await account_review.review_accounts(db, db.get(Brand, run.brand_id), discovery_store.candidate_usernames(db, run), reviewer, limit=6,
                                             platform=run.platform)


@app.get("/api/discovery-runs/{run_id}/profiles", tags=["step-2-discovery"])
async def read_run_profiles(run_id: str, db: DB, client: BRIGHT_DATA, reviewer: REVIEWER):
    """Consulta el enriquecimiento en curso sin iniciar extracciones nuevas."""
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    if run.profiles_state in discovery_store.PROFILES_ACTIVE and not discovery_store.missing_config(run):
        run = await discovery_store.advance_profiles(db, run, client)
    await review_run(db, run, reviewer)
    return discovery_store.detail(db, run)


@app.get("/api/trend-engine", tags=["step-2-trends"])
def trend_engine_status():
    """Claves del radar LinkedIn + YouTube configuradas en el servidor y modelos en uso."""
    missing = trends_config.missing_keys()
    return {"configured": not missing, "missing": missing,
            "linkedin_providers": ["exa"] + (["brave"] if os.getenv("BRAVE_API_KEY") else []),
            "models": {"bulk": trends_config.HAIKU, "judgment": trends_config.judgment_model(), "top": trends_config.top_model()},
            "snapshot_hours": trends_config.snapshot_hours(), "run_budget_usd": trends_config.run_budget_usd()}


@app.post("/api/brands/{brand_id}/trend-runs", status_code=202, tags=["step-2-trends"])
def start_trend_run(brand_id: str, request: TrendRunRequest, db: DB, background: BackgroundTasks):
    """Inicia el radar LinkedIn + YouTube con la identidad guardada. Tarda unos minutos: consultar
    GET /api/trend-runs/{id}. Al terminar, los videos con vistas observadas quedan como lote v1 del paso 3."""
    brand = get_brand(brand_id, db)
    try:
        run = trend_runs.create_run(db, brand, request.platforms, request.window_days)
    except trend_runs.TrendRunError as error:
        raise HTTPException(error.status, error.message)
    background.add_task(trend_runs.execute, run.id)
    return trend_runs.summary(run)


@app.get("/api/brands/{brand_id}/trend-runs", tags=["step-2-trends"])
def list_trend_runs(brand_id: str, db: DB):
    get_brand(brand_id, db)
    return trend_runs.list_runs(db, brand_id)


@app.get("/api/trend-runs/{run_id}", tags=["step-2-trends"])
def read_trend_run(run_id: str, db: DB):
    """Avance de la corrida y, al terminar, el informe completo (tópicos, brecha, propuestas, evidencia)."""
    run = db.get(TrendRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    return trend_runs.detail(trend_runs.expire_stale(db, run))


@app.post("/api/discovery-runs/{run_id}/posts", tags=["step-2-discovery"])
async def start_run_posts(run_id: str, db: DB, client: BRIGHT_DATA, post_reviewer: POST_REVIEWER, transcriber: TRANSCRIBER, media: MEDIA,
                          analyzer: VIDEO_ANALYZER):
    """Trae los posts de los últimos 30 días (máx. 30 por creador) de los creadores que pasan la revisión.
    Solo paga los creadores cuyos posts no se hayan recogido dentro de la vigencia."""
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    if missing := discovery_store.missing_config(run):
        raise HTTPException(503, "Bright Data requiere " + ", ".join(missing) + ".")
    try:
        run = await discovery_store.start_posts(db, run, client)
    except ProviderError as error:
        raise HTTPException(409, error.message)
    await enrich_run_posts(db, run, post_reviewer, transcriber, media, analyzer)
    return discovery_store.posts_detail(db, run)


@app.get("/api/discovery-runs/{run_id}/posts", tags=["step-2-discovery"])
async def read_run_posts(run_id: str, db: DB, client: BRIGHT_DATA, post_reviewer: POST_REVIEWER, transcriber: TRANSCRIBER, media: MEDIA,
                         analyzer: VIDEO_ANALYZER):
    """Línea base por creador y relevancia de cada post. Consulta la recolección en curso sin iniciar otra y,
    con los posts listos, revisa una tanda de posts y transcribe una tanda de reels relevantes."""
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    if run.posts_state in discovery_store.PROFILES_ACTIVE and not discovery_store.missing_config(run):
        run = await discovery_store.advance_posts(db, run, client)
    await enrich_run_posts(db, run, post_reviewer, transcriber, media, analyzer)
    return discovery_store.posts_detail(db, run)


def get_run(run_id, db):
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Corrida no encontrada")
    return run


@app.get("/api/discovery-runs/{run_id}/trends", tags=["step-3"])
async def run_trends(run_id: str, db: DB, grouper: TOPIC_GROUPER, post_reviewer: POST_REVIEWER):
    """Tópicos de los posts sobre el tópico de la búsqueda: estado (en caliente, emergente, saturado…), tracción,
    amplitud, momentum y matriz por semana. Unifica los subtemas con el LLM cuando cambian. Mientras falten
    veredictos de relevancia, cada consulta revisa una tanda: la vista avanza aunque no esté en el paso de posts."""
    run = get_run(run_id, db)
    if post_reviewer:
        await discovery_store.review_run_posts(db, run, post_reviewer)
    return await discovery_store.trends_detail(db, run, grouper)


@app.get("/api/discovery-runs/{run_id}/content-patterns", tags=["step-3"])
async def run_content_patterns(run_id: str, db: DB, media: MEDIA, analyzer: VIDEO_ANALYZER):
    """Rasgos de producción de los primeros 30 s de los reels destacados frente a reels normales de los mismos
    creadores. Cada consulta analiza una tanda pendiente."""
    run = get_run(run_id, db)
    if run.platform == "tiktok":
        raise HTTPException(409, "Los patrones de producción no están disponibles para TikTok: su CDN no permite descargar los videos.")
    if analyzer:
        await discovery_store.analyze_run_content(db, run, analyzer, media)
    return discovery_store.patterns_detail(db, run)


@app.post("/api/demo", status_code=201, tags=["demo"])
def demo(db: DB):
    brand = save_brand(demo_brief(), db)
    batch = save_batch(brand.id, demo_batch(), db)
    return {"brand": brand_output(brand, db), "batch_id": batch["id"]}
