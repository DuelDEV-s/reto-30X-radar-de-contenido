import hashlib
import json
import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Brand, ProfileAnalysis, TrendBatch, get_session
from .demo import demo_batch, demo_brief
from .schemas import BatchCreate, BrandCreate, Identity, Platform, ProfileAnalysisRequest
from .services import analyze, draft_identity
from .profiles import build_analysis, connector_status, TTL
from datetime import datetime, timezone

app = FastAPI(title="30X Radar de contenido", version="0.1.0", description="Pasos 1 y 3. Ingesta v1 para el equipo del paso 2. Sin scraping ni datos personales.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","), allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type"])
DB = Annotated[Session, Depends(get_session)]


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
        data["stale"] = datetime.now(timezone.utc) - datetime.fromisoformat(data["analyzed_at"]) > TTL
    return {"id": brand.id, "brief": brand.brief, "identity": brand.identity, "created_at": brand.created_at, "profile_analysis": data}


async def inspect_brand(brand, db, request):
    values = dict(brand.brief)
    if request.profiles is not None:
        values["profiles"] = [p.model_dump(mode="json") for p in request.profiles]
        values["brand_accounts_confirmed"] = request.brand_accounts_confirmed
    brief = BrandCreate.model_validate(values)
    fingerprint = hashlib.sha256(json.dumps({"brief": brief.model_dump(mode="json"), "connectors": connector_status()}, sort_keys=True).encode()).hexdigest()
    row = db.get(ProfileAnalysis, brand.id)
    fresh = row and datetime.now(timezone.utc) - datetime.fromisoformat(row.data["analyzed_at"]) < TTL
    if request.force or not fresh or row.data.get("input_fingerprint") != fingerprint:
        data = await build_analysis(brief)
        data["input_fingerprint"] = fingerprint
        if row:
            row.data = data
            row.analyzed_at = datetime.now(timezone.utc)
        else:
            row = ProfileAnalysis(brand_id=brand.id, data=data)
            db.add(row)
    brand.brief = brief.model_dump(mode="json")
    if request.apply_to_identity:
        brand.identity = row.data["suggested_identity"]
    db.commit()
    return brand_output(brand, db)


def save_brand(brief, db):
    brand = Brand(brief=brief.model_dump(mode="json"), identity=draft_identity(brief).model_dump(mode="json"))
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


def save_batch(brand_id, batch, db):
    data = batch.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = db.scalar(select(TrendBatch).where(TrendBatch.brand_id == brand_id, TrendBatch.fingerprint == fingerprint))
    if previous:
        return {"id": previous.id, "posts": len(data["posts"]), "deduplicated": True}
    row = TrendBatch(brand_id=brand_id, fingerprint=fingerprint, data=data)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(TrendBatch).where(TrendBatch.brand_id == brand_id, TrendBatch.fingerprint == fingerprint))
        if not previous:
            raise
        return {"id": previous.id, "posts": len(data["posts"]), "deduplicated": True}
    return {"id": row.id, "posts": len(data["posts"]), "deduplicated": False}


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


@app.post("/api/demo", status_code=201, tags=["demo"])
def demo(db: DB):
    brand = save_brand(demo_brief(), db)
    batch = save_batch(brand.id, demo_batch(), db)
    return {"brand": brand_output(brand, db), "batch_id": batch["id"]}
