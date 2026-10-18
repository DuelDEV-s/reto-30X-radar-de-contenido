"""Frozen contracts: step 1 -> step 2 input, and step 2 -> step 3 report.

`python -m radar schemas` writes both as JSON Schema into contracts/.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["linkedin", "youtube"]
Stage = Literal["emerging", "growing", "peak", "saturated", "declining", "insufficient_data"]
TrendStatus = Literal["validated", "hype_risk", "untested", "stable"]
OpportunityType = Literal["linkedin_gap", "join_trend", "early_bet", "language_arbitrage", "audience_ask"]


# --- Input (from step 1) ------------------------------------------------------
class Persona(BaseModel):
    id: str
    name: str
    description: str
    pains: list[str] = []


class Handles(BaseModel):
    linkedin: str | None = None
    youtube: str | None = None
    website: str | None = None


class Markets(BaseModel):
    languages: list[str] = ["es"]
    regions: list[str] = ["MX", "CO", "AR", "CL", "PE"]


class BrandIdentity(BaseModel):
    brand_id: str
    brand_name: str
    description: str
    general_topic: str
    specific_topics: list[str] = Field(min_length=1)
    personas: list[Persona] = Field(min_length=1)
    handles: Handles = Handles()
    markets: Markets | None = None
    output_platforms: list[Platform] = ["linkedin", "youtube"]
    window_days: int = Field(28, ge=7, le=90)


# --- Output (to step 3) -------------------------------------------------------
class Window(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str


class YouTubeSource(BaseModel):
    items: int
    creators: int
    quota_used: int
    visibility: Literal["internal", "public"]


class LinkedInSource(BaseModel):
    items: int
    providers: list[str]
    evidence: Literal["search_index"] = "search_index"


class Sources(BaseModel):
    youtube: YouTubeSource
    linkedin: LinkedInSource


class Cost(BaseModel):
    search: float
    llm: float


class RunInfo(BaseModel):
    run_id: str
    brand_id: str
    generated_at: str
    window: Window
    output_platforms: list[Platform]
    sources: Sources
    cost_usd: Cost


class BrandInfo(BaseModel):
    coverage_source: str | None
    coverage_topics: list[str]
    voice: str | None
    languages: list[str]
    regions: list[str]


class WeekPosts(BaseModel):
    week: str
    posts: int


class WeekAttention(BaseModel):
    week: str
    attention: float


class LinkedInTopic(BaseModel):
    posts_7d: int
    authors_7d: int
    growth_wow: float
    li_gap: float = Field(description="pct_rank(YouTube demand x quality) - pct_rank(LinkedIn supply), -1..1")
    trend_status: TrendStatus
    timeseries: list[WeekPosts]


class Demand(BaseModel):
    level: Literal["low", "medium", "high"]
    momentum_wow: float
    median_outlier: float | None
    items: int
    timeseries: list[WeekAttention]


class Topic(BaseModel):
    topic_id: str
    label: str
    entities: list[str]
    maps_to: list[str]
    stage: Stage
    confidence: float
    linkedin: LinkedInTopic
    demand: Demand
    persona_relevance: dict[str, float]
    brand_fit: float
    coverage_gap: float
    opportunity_score: float
    why_it_works: list[str]
    top_items: list[str]


class ItemMetrics(BaseModel):
    views: int
    outlier: float | None
    engagement: float
    velocity_h: float


class Item(BaseModel):
    item_id: str
    platform: Platform
    url: str
    title: str | None = None
    excerpt: str | None = None
    author: str | None = None
    published_at: str | None = None
    format: str
    lang: str | None = None
    visibility: Literal["internal", "public"] = "public"
    metrics: ItemMetrics | None = None
    visibility_proxy: float | None = None
    hook: str | None = None
    evidence_level: Literal["api", "search_index"]


class Pattern(BaseModel):
    pattern: str
    label: str
    evidence: Literal["youtube_lift", "linkedin_usage"]
    lift: float | None
    support: int
    also_used_by_active_linkedin_voices: bool
    examples: list[str]


class AudienceTheme(BaseModel):
    theme: str
    mentions: int
    type: Literal["question", "objection", "request"]
    topic_id: str | None


class Proposal(BaseModel):
    title_options: list[str]
    hook: str
    outline: list[str]
    length: str


class Opportunity(BaseModel):
    id: str
    type: OpportunityType
    topic_id: str
    persona: str
    platform: Platform
    format: str
    score: float
    why_now: str
    proposal: Proposal
    evidence: list[str]
    chart_refs: list[str]


class DataQuality(BaseModel):
    calibration: Literal["run-local"] = "run-local"
    linkedin_engagement: Literal["not_available"] = "not_available"
    coverage_level: Literal["normal", "widened_56d", "widened_90d", "sparse"]
    warnings: list[str]


class Report(BaseModel):
    run: RunInfo
    brand: BrandInfo
    topics: list[Topic]
    items: list[Item]
    patterns: list[Pattern]
    audience_voice: list[AudienceTheme]
    opportunities: list[Opportunity]
    data_quality: DataQuality

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, indent=2)
