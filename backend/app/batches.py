import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .database import TrendBatch


def save_batch(brand_id, batch, db):
    """Guarda un lote v1 completo. Mismo JSON canónico para la misma marca devuelve el lote existente."""
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
