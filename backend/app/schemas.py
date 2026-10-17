from datetime import datetime, timezone, timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Platform = Literal["linkedin", "instagram", "tiktok", "youtube"]
HOSTS = {
    "linkedin": {"linkedin.com", "www.linkedin.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com"},
    "youtube": {"youtube.com", "www.youtube.com", "youtu.be"},
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def public_url(value: str, platform: str):
    url = urlsplit(value)
    if url.scheme != "https" or url.hostname not in HOSTS[platform] or url.username or url.password or url.port not in (None, 443) or not url.path.strip("/"):
        raise ValueError("Usa una URL https de la plataforma indicada, sin credenciales ni puertos especiales.")
    if url.query or url.fragment:
        raise ValueError("Elimina parámetros de seguimiento y fragmentos de la URL.")
    return value.rstrip("/")


class SocialProfile(StrictModel):
    platform: Platform
    url: str = Field(max_length=500)
    description: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def check_url(self):
        self.url = public_url(self.url, self.platform)
        return self


class Persona(StrictModel):
    role: str = Field(min_length=2, max_length=120)
    need: str = Field(min_length=5, max_length=500)


class BrandCreate(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=5000)
    audience: str = Field(default="", max_length=1000)
    region: str = Field(default="Latinoamérica", min_length=2, max_length=100)
    topics: list[str] = Field(default_factory=list, max_length=15)
    profiles: list[SocialProfile] = Field(default_factory=list, max_length=8)
    brand_accounts_confirmed: bool = False

    @field_validator("description", "audience")
    @classmethod
    def validate_optional_context(cls, value, info):
        minimum = 20 if info.field_name == "description" else 5
        if value and len(value) < minimum:
            raise ValueError(f"Si aportas {info.field_name}, escribe al menos {minimum} caracteres.")
        return value

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, values):
        values = list(dict.fromkeys(t.strip().lower() for t in values if t.strip()))
        if any(len(t) > 100 for t in values):
            raise ValueError("Indica entre 1 y 15 tópicos de máximo 100 caracteres.")
        return values

    @model_validator(mode="after")
    def check_context(self):
        if not self.profiles and len(self.description) < 20:
            raise ValueError("Agrega perfiles públicos de la marca o una descripción de al menos 20 caracteres.")
        if self.profiles and not self.brand_accounts_confirmed:
            raise ValueError("Confirma que son cuentas públicas de la marca, sin perfiles personales.")
        if len({(p.platform, p.url) for p in self.profiles}) != len(self.profiles):
            raise ValueError("No repitas un perfil en la marca.")
        return self


class Identity(StrictModel):
    summary: str = Field(min_length=10, max_length=5000)
    audience: str = Field(min_length=5, max_length=1000)
    region: str = Field(min_length=2, max_length=100)
    topics: list[str] = Field(min_length=1, max_length=15)
    personas: list[Persona] = Field(min_length=1, max_length=6)
    status: Literal["draft", "confirmed"] = "draft"
    method: Literal["brief_rules", "profile_rules", "human_review"] = "human_review"

    _clean_topics = field_validator("topics")(BrandCreate.clean_topics.__func__)

    @field_validator("topics")
    @classmethod
    def require_topics(cls, value):
        if not value:
            raise ValueError("Indica al menos un tópico.")
        return value


class ProfileAnalysisRequest(StrictModel):
    profiles: list[SocialProfile] | None = Field(default=None, max_length=8)
    brand_accounts_confirmed: bool = False
    force: bool = False
    apply_to_identity: bool = False
    refresh_bright_data: bool = False


class ProfileMetric(StrictModel):
    views: int | None = Field(default=None, ge=0)
    followers: int | None = Field(default=None, ge=0)
    posts: int | None = Field(default=None, ge=0)


class ProfileContent(StrictModel):
    url: str
    title: str = ""
    text: str = ""
    format: str
    published_at: str | None = None
    views: int | None = Field(default=None, ge=0)


class ProfileResult(StrictModel):
    platform: Platform
    url: str
    status: Literal["ready", "pending", "requires_configuration", "unsupported", "not_found", "error"]
    provider: str
    message: str
    observed_at: datetime
    title: str = ""
    description: str = ""
    metrics: ProfileMetric = Field(default_factory=ProfileMetric)
    metrics_notes: list[str] = Field(default_factory=list)
    content_sample: list[ProfileContent] = Field(default_factory=list)
    usable_for_identity: bool = False
    supplied_description: str = ""
    attempts: list[dict] = Field(default_factory=list)
    fallback_used: bool = False
    collection: dict | None = None


class Snapshot(StrictModel):
    observed_at: datetime
    views: int = Field(ge=0, le=10**12)

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("La fecha debe incluir zona horaria.")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("No se aceptan observaciones futuras.")
        return value


class ContentPiece(StrictModel):
    external_id: str = Field(min_length=1, max_length=150)
    platform: Platform
    url: str = Field(max_length=500)
    title: str = Field(min_length=3, max_length=300)
    topic: str = Field(min_length=2, max_length=100)
    format: Literal["video", "short", "carousel", "text", "article"]
    hook: str = Field(min_length=3, max_length=1000)
    published_at: datetime
    snapshots: list[Snapshot] = Field(min_length=1, max_length=60)
    source_method: Literal["official_api", "open_dataset", "manual_public", "demo"]
    source_reference: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def check_piece(self):
        self.url = public_url(self.url, self.platform)
        if self.published_at.tzinfo is None:
            raise ValueError("published_at debe incluir zona horaria.")
        self.topic = self.topic.strip().lower()
        for i, snapshot in enumerate(self.snapshots):
            if snapshot.observed_at < self.published_at:
                raise ValueError("Una observación no puede preceder la publicación.")
            if i and (snapshot.observed_at <= self.snapshots[i-1].observed_at or snapshot.views < self.snapshots[i-1].views):
                raise ValueError("Ordena observaciones por fecha creciente y vistas acumuladas no decrecientes.")
        return self


class BatchCreate(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["public", "demo"] = "public"
    source: str = Field(min_length=3, max_length=200)
    compliance_confirmed: bool
    posts: list[ContentPiece] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def check_batch(self):
        if not self.compliance_confirmed:
            raise ValueError("Confirma origen público, permiso de uso y ausencia de datos personales.")
        keys = [(p.platform, p.external_id) for p in self.posts]
        urls = [p.url for p in self.posts]
        if len(keys) != len(set(keys)) or len(urls) != len(set(urls)):
            raise ValueError("El lote contiene piezas duplicadas.")
        if any((p.source_method == "demo") != (self.mode == "demo") for p in self.posts):
            raise ValueError("No mezcles datos demo con datos públicos.")
        return self
