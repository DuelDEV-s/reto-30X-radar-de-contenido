"""Revisión con LLM: ¿una cuenta de Instagram tiene relación real con lo que hace la marca?

El veredicto (relevancia, tipo de cuenta, si es interna y motivo) se guarda por marca y cuenta, y solo se
vuelve a pedir si cambia la identidad de la marca o la ficha del perfil.

Vale igual para cuentas de Instagram y de TikTok (`platform`). Solo filtra en la búsqueda por tópico: se incluyen cuentas externas de relevancia alta o media que sean
creadores o empresas afines; promociones, gobierno, instituciones, medios y cuentas internas quedan fuera.
En las cuentas relacionadas el veredicto es informativo.
"""
import asyncio
import hashlib
import json
import logging
import os
from typing import Literal, Protocol

import openai
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import tiktok_accounts
from .account_store import accounts_by_username, now
from .database import AccountReview, Brand, InstagramAccount, TikTokAccount

logger = logging.getLogger(__name__)

Relevance = Literal["alta", "media", "baja", "ninguna"]
AccountType = Literal["creador", "empresa_afin", "promocion_comercial", "gobierno_institucion", "medio", "otro"]
INCLUDED_TYPES = {"creador", "empresa_afin"}
INCLUDED_RELEVANCE = {"alta", "media"}
MAX_POSTS = 8
MAX_CONCURRENCY = 4
# Cambiar las instrucciones o el esquema invalida los veredictos guardados: se re-revisan solos.
PROMPT_VERSION = 2

INSTRUCTIONS = """Eres analista de marketing de influencia. Decides si una cuenta de Instagram tiene una relación real con lo que hace una marca, para usarla como referencia en un análisis de tendencias de contenido.

Recibirás la marca (nombre, cuentas propias e identidad) y la ficha pública de la cuenta (bio, categoría, enlaces y captions recientes). Basa tu juicio solo en esa evidencia; si es escasa, sé conservador.

is_internal: true si la cuenta pertenece a la marca o a su entorno directo: cuentas oficiales o de sus programas, podcast o comunidades; fundadores, socios, empleados o miembros del equipo; personas cuya bio, usuario o enlaces las presentan como parte de la marca (por ejemplo, el nombre de la marca en el usuario o enlaces al dominio de la marca). Colaborar o promocionar una vez a la marca no basta para ser interna.

account_type:
- creador: persona o creador de contenido que publica sobre temas propios (incluye fundadores y expertos con marca personal).
- empresa_afin: empresa, comunidad o proyecto cuyo contenido trata temas cercanos a los de la marca.
- promocion_comercial: cuenta cuya presencia es comercial o promocional (tiendas, retail, patrocinadores, distribuidores, ofertas) sin afinidad temática real.
- gobierno_institucion: gobierno, entidad pública, cámara de comercio, universidad u otra institución.
- medio: medio de comunicación, revista, periódico, radio o TV.
- otro: nada de lo anterior o evidencia insuficiente.

relevance (qué tanto su contenido se relaciona con lo que hace la marca y con su audiencia):
- alta: temas centrales de la marca y audiencia compatible.
- media: temas cercanos o parciales.
- baja: coincidencia superficial.
- ninguna: sin relación.

reason: una frase en español, concreta, citando la evidencia que decidió el veredicto (incluida la que la hace interna, si aplica)."""

# En TikTok la evidencia trae, en vez de categoría, los videos de la cuenta que aparecieron al buscar el tópico.
TIKTOK_NOTE = """

La cuenta es de TikTok. recent_captions son descripciones de sus videos que aparecieron al buscar el tópico; videos_count y likes_total ayudan a distinguir a un creador constante de una cuenta con un video viral suelto. Un video viral aislado de una cuenta sin contenido propio sobre el tema no la convierte en creador relevante."""


def instructions(platform: str = "instagram") -> str:
    return INSTRUCTIONS.replace("Instagram", "TikTok") + TIKTOK_NOTE if platform == "tiktok" else INSTRUCTIONS


class Verdict(BaseModel):
    relevance: Relevance
    account_type: AccountType
    is_internal: bool
    reason: str = Field(max_length=400)


class Reviewer(Protocol):
    model: str
    effort: str

    async def review(self, brand: dict, evidence: dict) -> Verdict | None: ...


def is_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def included(verdict: AccountReview | None) -> bool:
    """Regla de la búsqueda por tópico para pasar al análisis de tendencias."""
    return bool(verdict and not verdict.is_internal and verdict.account_type in INCLUDED_TYPES and verdict.relevance in INCLUDED_RELEVANCE)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def brand_handles(brand: Brand, platform: str = "instagram") -> list[str]:
    """Usuarios propios de la marca en la red, según los perfiles de su brief."""
    urls = [p["url"] for p in brand.brief.get("profiles", []) if p.get("platform") == platform]
    if platform == "tiktok":
        return [name for name in map(tiktok_accounts.username_from, urls) if name]
    return [url.rstrip("/").rsplit("/", 1)[-1].lower() for url in urls]


def brand_context(brand: Brand, platform: str = "instagram") -> dict:
    """Lo que ve el LLM de la marca: nombre y cuentas propias en la red (para reconocer cuentas internas) e identidad."""
    return {"name": brand.brief.get("name"), f"{platform}_accounts": brand_handles(brand, platform),
            **{k: brand.identity.get(k) for k in ("summary", "audience", "region", "topics", "personas")}}


def evidence(account: InstagramAccount) -> dict:
    """Lo que ve el LLM de la cuenta: ficha pública y captions recientes, recortados."""
    raw = account.raw or {}
    posts = [p for p in raw.get("posts") or [] if isinstance(p, dict)]
    return {
        "username": account.username, "full_name": account.full_name, "biography": account.biography,
        "category": account.category, "external_urls": account.external_urls[:5], "is_verified": account.is_verified,
        "followers": account.followers,
        "bio_hashtags": raw.get("bio_hashtags") if isinstance(raw.get("bio_hashtags"), list) else [],
        "recent_captions": [(p.get("caption") or p.get("description") or "")[:400] for p in posts[:MAX_POSTS] if p.get("caption") or p.get("description")],
    }


class OpenAIReviewer:
    def __init__(self, client=None, model: str | None = None, effort: str | None = None):
        self.client = client or openai.AsyncOpenAI(timeout=60.0, max_retries=2)
        self.model = model or os.getenv("OPENAI_REVIEW_MODEL", "gpt-6-luna")
        self.effort = effort or os.getenv("OPENAI_REVIEW_EFFORT", "low")

    async def review(self, brand: dict, evidence: dict) -> Verdict | None:
        response = await self.client.responses.parse(
            model=self.model,
            instructions=instructions(evidence.get("platform", "instagram")),
            input=json.dumps({"marca": brand, "cuenta": evidence}, ensure_ascii=False),
            text_format=Verdict,
            reasoning={"effort": self.effort},
            max_output_tokens=2000,
        )
        # Una negativa del modelo no sigue el esquema: output_parsed queda vacío y la cuenta sigue sin revisar.
        return response.output_parsed


def evidences(db: Session, accounts: dict, platform: str) -> dict[str, dict]:
    if platform == "tiktok":
        return tiktok_accounts.review_evidence(db, accounts)
    return {name: evidence(account) for name, account in accounts.items()}


async def review_accounts(db: Session, brand: Brand, usernames: list[str], reviewer: Reviewer, limit: int | None = None,
                          platform: str = "instagram") -> int:
    """Revisa las cuentas con ficha cuyo veredicto falte o esté desactualizado. Devuelve cuántas se revisaron.

    Con `limit` revisa como mucho esa cantidad por llamada, para que cada consulta responda rápido;
    las siguientes consultas continúan con el resto."""
    context = brand_context(brand, platform)
    identity_digest = digest({"brand": context, "prompt_version": PROMPT_VERSION})
    model = TikTokAccount if platform == "tiktok" else InstagramAccount
    accounts = {name: a for name, a in accounts_by_username(db, usernames, model=model).items() if a.raw is not None}
    found = evidences(db, accounts, platform)
    existing = reviews_by_username(db, brand.id, usernames, platform)
    pending = []
    for name in dict.fromkeys(usernames):
        account = accounts.get(name)
        if not account:
            continue
        profile_digest = digest(found[name])
        current = existing.get(name)
        if current and current.identity_digest == identity_digest and current.profile_digest == profile_digest:
            continue
        pending.append((name, found[name], profile_digest))
    pending = pending[:limit] if limit else pending
    if not pending:
        return 0
    slots = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(item):
        name, facts, _ = item
        async with slots:
            try:
                return await reviewer.review(context, facts)
            except (openai.APIError, ValidationError) as error:
                # Un fallo del proveedor deja la cuenta pendiente de revisión; no rompe la consulta.
                logger.warning("Revisión LLM falló para @%s: %s", name, type(error).__name__)
                return None

    verdicts = await asyncio.gather(*(one(item) for item in pending))
    reviewed = 0
    for (name, _, profile_digest), verdict in zip(pending, verdicts):
        if verdict is None:
            continue
        row = existing.get(name) or AccountReview(brand_id=brand.id, platform=platform, username=name)
        row.relevance, row.account_type, row.reason = verdict.relevance, verdict.account_type, verdict.reason
        row.is_internal = verdict.is_internal
        row.model, row.effort = reviewer.model, reviewer.effort
        row.identity_digest, row.profile_digest, row.reviewed_at = identity_digest, profile_digest, now()
        db.add(row)
        reviewed += 1
    db.commit()
    return reviewed


def reviews_by_username(db: Session, brand_id: str, usernames: list[str], platform: str = "instagram") -> dict[str, AccountReview]:
    if not usernames:
        return {}
    return {r.username: r for r in db.scalars(select(AccountReview).where(
        AccountReview.brand_id == brand_id, AccountReview.platform == platform, AccountReview.username.in_(usernames))).all()}


def review_dict(review: AccountReview | None, has_profile: bool) -> dict:
    if review is None:
        return {"review": None, "review_status": "pending" if has_profile else "no_profile"}
    return {
        "review": {"relevance": review.relevance, "account_type": review.account_type, "is_internal": review.is_internal, "reason": review.reason,
                   "model": review.model, "effort": review.effort, "reviewed_at": review.reviewed_at},
        "review_status": "reviewed",
    }
