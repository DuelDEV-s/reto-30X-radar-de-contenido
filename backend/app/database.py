import os
from typing import ClassVar

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, synonym
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
    """Relación de una cuenta de Instagram con una marca (colaboración, coautoría o etiqueta en sus reels).
    La ficha del perfil vive en `instagram_accounts`, compartida entre marcas."""
    __tablename__ = "related_accounts"
    __table_args__ = (UniqueConstraint("brand_id", "username", name="uq_brand_related_account"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(30))
    relations: Mapped[list] = mapped_column(JSON, default=list)
    reel_urls: Mapped[list] = mapped_column(JSON, default=list)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstagramAccount(Base):
    """Ficha pública de un perfil de Instagram obtenida con Bright Data; se reutiliza mientras esté vigente."""
    __tablename__ = "instagram_accounts"
    PLATFORM: ClassVar[str] = "instagram"
    username: Mapped[str] = mapped_column(String(30), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    following: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posts_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_urls: Mapped[list] = mapped_column(JSON, default=list)
    # Las URLs de imagen de Instagram caducan en días; se guarda una copia de la foto.
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ok, private, not_found o error: también se recuerdan los fallos para no pagarlos otra vez.
    fetch_status: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Última recolección de sus posts recientes; también se marca si no publicó nada en la ventana.
    posts_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstagramPost(Base):
    """Post de un creador con sus métricas más recientes. Compartido entre marcas, como la ficha del perfil."""
    __tablename__ = "instagram_posts"
    PLATFORM: ClassVar[str] = "instagram"
    shortcode: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Creador en cuyo perfil apareció; `author` es quien lo publicó (difiere en colaboraciones).
    username: Mapped[str] = mapped_column(String(30), index=True)
    author: Mapped[str | None] = mapped_column(String(30), nullable=True)
    url: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(20))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_paid_partnership: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_pinned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    coauthors: Mapped[list] = mapped_column(JSON, default=list)
    tagged_users: Mapped[list] = mapped_column(JSON, default=list)
    audio: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON)
    # Transcripción de los primeros segundos del audio (solo reels). Estado: processing, ok, no_speech,
    # no_audio, expired, too_large, unavailable o error; None si falta o falló de forma transitoria.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transcript_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PostTopicReview(Base):
    """Veredicto del LLM sobre si un post habla del tópico de una búsqueda, con su tipo y subtemas.
    Se reutiliza mientras no cambien el tópico (topic_key), el caption ni la transcripción (input_digest).
    `shortcode` es el shortcode de Instagram o el id del video de TikTok, según `platform`."""
    __tablename__ = "post_topic_reviews"
    __table_args__ = (UniqueConstraint("platform", "shortcode", "topic_key", name="uq_post_topic_review"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    platform: Mapped[str] = mapped_column(String(20), default="instagram")
    shortcode: Mapped[str] = mapped_column(String(64), index=True)
    topic_key: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(String(200))
    relevance: Mapped[str] = mapped_column(String(20))
    content_kind: Mapped[str] = mapped_column(String(30))
    subtopics: Mapped[list] = mapped_column(JSON, default=list)
    needs_transcript: Mapped[bool] = mapped_column(Boolean)
    used_transcript: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(100))
    effort: Mapped[str] = mapped_column(String(20))
    input_digest: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PostContentAnalysis(Base):
    """Rasgos de producción de los primeros segundos de un reel, según un modelo multimodal (Gemini)."""
    __tablename__ = "post_content_analyses"
    platform: Mapped[str] = mapped_column(String(20), primary_key=True, default="instagram")
    shortcode: Mapped[str] = mapped_column(String(64), primary_key=True)
    # processing, ok, expired, too_large, unavailable o error; None si falló de forma transitoria.
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunTopicMap(Base):
    """Subtemas de los posts de una búsqueda agrupados en tópicos canónicos. Se rehace si cambian los subtemas."""
    __tablename__ = "run_topic_maps"
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id", ondelete="CASCADE"), primary_key=True)
    labels_digest: Mapped[str] = mapped_column(String(64))
    topics: Mapped[list] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstagramPostObservation(Base):
    """Métricas de un post en cada recolección: el historial permite medir velocidad entre observaciones."""
    __tablename__ = "instagram_post_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    shortcode: Mapped[str] = mapped_column(ForeignKey("instagram_posts.shortcode", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AccountReview(Base):
    """Veredicto del LLM sobre la relación de una cuenta con lo que hace la marca.
    Se reutiliza mientras no cambien la identidad de la marca ni la ficha del perfil (digests)."""
    __tablename__ = "account_reviews"
    __table_args__ = (UniqueConstraint("brand_id", "platform", "username", name="uq_brand_account_review"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    # El mismo @usuario puede existir en Instagram y en TikTok y ser cuentas distintas.
    platform: Mapped[str] = mapped_column(String(20), default="instagram")
    username: Mapped[str] = mapped_column(String(30))
    relevance: Mapped[str] = mapped_column(String(20))
    account_type: Mapped[str] = mapped_column(String(30))
    # Cuenta de la propia marca, su equipo o su ecosistema: nunca se incluye para tendencias.
    is_internal: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(100))
    effort: Mapped[str] = mapped_column(String(20))
    identity_digest: Mapped[str] = mapped_column(String(64))
    profile_digest: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryRun(Base):
    """Una corrida de búsqueda de creadores por tópico: parámetros, identidad usada y totales."""
    __tablename__ = "discovery_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))
    hl: Mapped[str] = mapped_column(String(10))
    countries: Mapped[list] = mapped_column(JSON)
    max_queries: Mapped[int] = mapped_column(Integer)
    profiles_only: Mapped[bool] = mapped_column(Boolean)
    resolve_posts: Mapped[bool] = mapped_column(Boolean)
    # La identidad cambia con el tiempo; se conserva la que generó estas queries.
    identity: Mapped[dict] = mapped_column(JSON)
    query_count: Mapped[int] = mapped_column(Integer)
    result_count: Mapped[int] = mapped_column(Integer)
    candidate_count: Mapped[int] = mapped_column(Integer)
    discarded_count: Mapped[int] = mapped_column(Integer)
    unresolved_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Búsqueda asíncrona de videos por palabra clave (TikTok, Bright Data). En Instagram la búsqueda (SERP) es
    # inmediata y la etapa queda en not_started.
    search_state: Mapped[str] = mapped_column(String(30), default="not_started")
    search_generation: Mapped[str | None] = mapped_column(String(36), nullable=True)
    search_snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    search_message: Mapped[str] = mapped_column(String(500), default="")
    search_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Enriquecimiento con fichas de perfil (Bright Data) de los candidatos que faltan en instagram_accounts o tiktok_accounts.
    profiles_state: Mapped[str] = mapped_column(String(30), default="not_started")
    profiles_generation: Mapped[str | None] = mapped_column(String(36), nullable=True)
    profiles_snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profiles_requested: Mapped[list] = mapped_column(JSON, default=list)
    profiles_message: Mapped[str] = mapped_column(String(500), default="")
    profiles_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Posts recientes (Bright Data) de los creadores que pasan la revisión, para la línea base y la relevancia.
    posts_state: Mapped[str] = mapped_column(String(30), default="not_started")
    posts_generation: Mapped[str | None] = mapped_column(String(36), nullable=True)
    posts_snapshot_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    posts_requested: Mapped[list] = mapped_column(JSON, default=list)
    posts_message: Mapped[str] = mapped_column(String(500), default="")
    posts_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveryQuery(Base):
    __tablename__ = "discovery_queries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(String(500))
    planned_query: Mapped[str] = mapped_column(String(500))
    angle: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str] = mapped_column(String(100))
    gl: Mapped[str | None] = mapped_column(String(10), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean)
    results_count: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class DiscoveryHit(Base):
    """Un resultado de Google de una query y su desenlace: candidato, descartado o post sin autor."""
    __tablename__ = "discovery_hits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("discovery_queries.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    link: Mapped[str] = mapped_column(String(1000))
    outcome: Mapped[str] = mapped_column(String(20))
    username: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    author_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("run_id", "username", name="uq_run_candidate"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(30), index=True)
    query_hits: Mapped[int] = mapped_column(Integer)
    best_rank: Mapped[int] = mapped_column(Integer)


class TikTokAccount(Base):
    """Ficha pública de un perfil de TikTok obtenida con Bright Data; se reutiliza mientras esté vigente."""
    __tablename__ = "tiktok_accounts"
    PLATFORM: ClassVar[str] = "tiktok"
    username: Mapped[str] = mapped_column(String(30), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String(300), nullable=True)
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    following: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Likes acumulados por todos sus videos.
    likes_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    videos_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    region: Mapped[str | None] = mapped_column(String(10), nullable=True)
    external_urls: Mapped[list] = mapped_column(JSON, default=list)
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ok, private, not_found o error: también se recuerdan los fallos para no pagarlos otra vez.
    fetch_status: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    posts_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TikTokPost(Base):
    """Video de TikTok con sus métricas más recientes. A diferencia de Instagram, TikTok entrega vistas reales."""
    __tablename__ = "tiktok_posts"
    PLATFORM: ClassVar[str] = "tiktok"
    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Revisión, transcripción y análisis de video comparten código con Instagram, que identifica por shortcode.
    shortcode = synonym("video_id")
    # Creador en cuyo perfil se recogió o que lo publicó, si llegó por la búsqueda.
    username: Mapped[str] = mapped_column(String(30), index=True)
    author: Mapped[str | None] = mapped_column(String(30), nullable=True)
    url: Mapped[str] = mapped_column(String(300))
    # video o image (carrusel de fotos de TikTok).
    content_type: Mapped[str] = mapped_column(String(20))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transcript_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TikTokPostObservation(Base):
    """Métricas de un video en cada recolección, para medir su velocidad entre observaciones."""
    __tablename__ = "tiktok_post_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(ForeignKey("tiktok_posts.video_id", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TrendRun(Base):
    """Una corrida del radar de tendencias LinkedIn + YouTube (app/trends). Guarda la identidad usada,
    el avance por etapa, el informe completo y el lote v1 que generó para el paso 3."""
    __tablename__ = "trend_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    # queued, running, done o failed.
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    platforms: Mapped[list] = mapped_column(JSON)
    window_days: Mapped[int] = mapped_column(Integer)
    # Entrada exacta del motor (BrandIdentity), derivada de la identidad de la marca al iniciar.
    identity: Mapped[dict] = mapped_column(JSON)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(url: str):
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)


engine = make_engine(os.getenv("DATABASE_URL", "sqlite:///./radar.db"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session():
    with SessionLocal() as session:
        yield session
