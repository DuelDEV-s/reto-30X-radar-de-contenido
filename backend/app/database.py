import os

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from datetime import datetime, timezone
from uuid import uuid4


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brief: Mapped[dict] = mapped_column(JSON)
    identity: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendBatch(Base):
    __tablename__ = "trend_batches"
    __table_args__ = (UniqueConstraint("brand_id", "fingerprint", name="uq_brand_batch"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileAnalysis(Base):
    __tablename__ = "profile_analyses"
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileCollectionJob(Base):
    __tablename__ = "profile_collection_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    generation: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(20))
    snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RelatedAccountRun(Base):
    """Última búsqueda de cuentas relacionadas de una marca: dos trabajos de Bright Data (reels y perfiles)."""
    __tablename__ = "related_account_runs"
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True)
    generation: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(30))
    brand_account: Mapped[str] = mapped_column(String(30))
    reels_snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profiles_snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    relations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RelatedAccount(Base):
    """Cuenta de Instagram relacionada con una marca (colaboración, coautoría o etiqueta en sus reels)."""
    __tablename__ = "related_accounts"
    __table_args__ = (UniqueConstraint("brand_id", "username", name="uq_brand_related_account"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(30))
    full_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    following: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posts_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_urls: Mapped[list] = mapped_column(JSON, default=list)
    relations: Mapped[list] = mapped_column(JSON, default=list)
    reel_urls: Mapped[list] = mapped_column(JSON, default=list)
    # Las URLs de imagen de Instagram caducan en días; se guarda una copia de la foto.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str):
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)


engine = make_engine(os.getenv("DATABASE_URL", "sqlite:///./radar.db"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session():
    with SessionLocal() as session:
        yield session
