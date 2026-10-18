export type Persona = { role: string; need: string };
export type Identity = {
  summary: string;
  audience: string;
  region: string;
  topics: string[];
  personas: Persona[];
  status: "draft" | "confirmed";
  method: string;
};
export type Brand = {
  id: string;
  brief: {
    name: string;
    profiles: { platform: string; url: string; description: string }[];
  };
  identity: Identity;
  profile_analysis?: ProfileAnalysis | null;
};
export type SocialProfile = {
  platform: string;
  url: string;
  description: string;
};
export type ProfileResult = {
  platform: string;
  url: string;
  status: string;
  provider: string;
  message: string;
  observed_at: string;
  attempts?: {
    provider: string;
    status: string;
    message: string;
    code?: string;
  }[];
  fallback_used?: boolean;
  collection?: {
    provider: string;
    state: string;
    snapshot_id: string | null;
    requested_at: string;
  } | null;
  title: string;
  description: string;
  supplied_description: string;
  metrics: {
    views: number | null;
    followers: number | null;
    posts: number | null;
  };
  metrics_notes: string[];
  usable_for_identity: boolean;
  content_sample: {
    url: string;
    title: string;
    text: string;
    format: string;
    views: number | null;
    published_at: string | null;
  }[];
};
export type ProfileAnalysis = {
  schema_version: string;
  analyzed_at: string;
  status: string;
  stale: boolean;
  profiles: ProfileResult[];
  suggested_identity: Identity;
  identity_evidence: string[];
  opportunities: { platform: string; action: string; basis: string }[];
  method: string;
  interpreted_at?: string;
  interpretation?: {
    version: string;
    method: string;
    local_focus: string | null;
    facts: {
      label: string;
      value: string;
      evidence: InterpretationEvidence[];
    }[];
    pillars: {
      topic: string;
      rationale: string;
      idea: string;
      measurement: string;
      evidence: InterpretationEvidence[];
    }[];
    audience_hypotheses: {
      role: string;
      need: string;
      evidence: InterpretationEvidence[];
    }[];
    coverage: Record<string, number>;
    limitations: string[];
  };
};
export type InterpretationEvidence = {
  source_url: string | null;
  source_kind: "brief" | "profile" | "post" | "manual";
  excerpt: string;
};
export type Connector = {
  platform: string;
  configured: boolean;
  missing: string[];
  scope: string;
  analysis_approved?: boolean;
  primary?: { provider: string; configured: boolean; missing: string[] };
  fallback?: { provider: string; configured: boolean; missing: string[] };
};
export type Batch = {
  id: string;
  mode: "public" | "demo";
  source: string;
  posts: number;
  created_at: string;
};
export type Point = { observed_at: string; views: number };
export type Topic = {
  topic: string;
  score: number;
  relevance: number;
  acceleration_pct: number | null;
  views_per_day: number | null;
  stage: string;
  confidence: string;
  sample_size: number;
  series_count: number;
  why_relevant: string;
  why_it_may_work: string[];
  adaptation: string;
  top_content: {
    title: string;
    hook: string;
    format: string;
    platform: string;
    url: string;
    source_reference: string;
    snapshots: Point[];
  };
  timeline: { url: string; points: Point[] }[];
};
export type Report = {
  mode: string;
  window_days: number;
  generated_at: string;
  total_topics: number;
  topics: Topic[];
  methodology: string;
  limitations: string[];
};

export type RelatedAccount = {
  username: string;
  profile_url: string;
  full_name: string | null;
  biography: string | null;
  followers: number | null;
  following: number | null;
  posts_count: number | null;
  is_verified: boolean | null;
  is_private: boolean | null;
  category: string | null;
  external_urls: string[];
  relations: ("coauthor" | "tagged" | "posted")[];
  reel_urls: string[];
  profile_available: boolean;
  avatar_url: string | null;
  collected_at: string;
  fetch_status: string | null;
  review: AccountVerdict | null;
  review_status: "reviewed" | "pending" | "no_profile";
};
export type AccountVerdict = {
  relevance: "alta" | "media" | "baja" | "ninguna";
  account_type:
    | "creador"
    | "empresa_afin"
    | "promocion_comercial"
    | "gobierno_institucion"
    | "medio"
    | "otro";
  is_internal: boolean;
  reason: string;
  model: string;
  effort: string;
  reviewed_at: string;
};
export type RelatedAccounts = {
  state:
    | "not_started"
    | "reels_requesting"
    | "reels_pending"
    | "profiles_requesting"
    | "profiles_pending"
    | "ready"
    | "failed"
    | "unknown";
  message: string;
  brand_account: string | null;
  requested_at: string | null;
  updated_at: string | null;
  accounts: RelatedAccount[];
};
export type DiscoveryHit = {
  rank: number;
  link: string;
  outcome: "candidate" | "discarded" | "unresolved";
  username: string | null;
  author_source: "url" | "snippet" | "oembed" | null;
  reason: string | null;
};
export type DiscoveryQueryRun = {
  position: number;
  query: string;
  planned_query: string;
  angle: string;
  topic: string;
  gl: string | null;
  fallback_used: boolean;
  results: number;
  error: string | null;
  hits: DiscoveryHit[];
};
export type DiscoveryCandidate = Omit<
  RelatedAccount,
  "relations" | "reel_urls" | "collected_at" | "review_status"
> & {
  review_status:
    | "reviewed"
    | "pending"
    | "no_profile"
    | "awaiting_profile"
    | "not_requested";
  included: boolean;
  query_hits: number;
  best_rank: number;
  sources: { query: string; link: string; rank: number; author_source: string }[];
};
export type DiscoveryRunSummary = {
  id: string;
  brand_id: string;
  status: "completed" | "partial" | "failed";
  created_at: string;
  topic: string | null;
  countries: string[];
  max_queries: number;
  totals: {
    queries: number;
    results: number;
    candidates: number;
    discarded: number;
    unresolved: number;
  };
  profiles: {
    state: "not_started" | "requesting" | "pending" | "ready" | "failed" | "unknown";
    message: string;
    requested: number;
    updated_at: string | null;
  };
};
export type DiscoveryRunDetail = DiscoveryRunSummary & {
  identity: Identity;
  review_enabled: boolean;
  review_summary: { included: number; internal: number; excluded: number; pending: number };
  queries: DiscoveryQueryRun[];
  candidates: DiscoveryCandidate[];
};
export type QueryPreview = {
  queries: { query: string; keywords: string; angle: string; topic: string }[];
};
// Radar de tendencias LinkedIn + YouTube (backend app/trends).
export type TrendPlatform = "linkedin" | "youtube";
export type TrendEngineStatus = {
  configured: boolean;
  missing: string[];
  linkedin_providers: string[];
  models: { bulk: string; judgment: string; top: string };
  snapshot_hours: number;
  run_budget_usd: number;
};
export type TrendStage = "emerging" | "growing" | "peak" | "saturated" | "declining" | "insufficient_data";
export type TrendStatus = "validated" | "hype_risk" | "untested" | "stable";
export type TrendTopic = {
  topic_id: string;
  label: string;
  entities: string[];
  maps_to: string[];
  stage: TrendStage;
  confidence: number;
  linkedin: {
    posts_7d: number;
    authors_7d: number;
    growth_wow: number;
    li_gap: number;
    trend_status: TrendStatus;
    timeseries: { week: string; posts: number }[];
  };
  demand: {
    level: "low" | "medium" | "high";
    momentum_wow: number;
    median_outlier: number | null;
    items: number;
    timeseries: { week: string; attention: number }[];
  };
  persona_relevance: Record<string, number>;
  brand_fit: number;
  coverage_gap: number;
  opportunity_score: number;
  why_it_works: string[];
  top_items: string[];
};
export type TrendItem = {
  item_id: string;
  platform: TrendPlatform;
  url: string;
  title: string | null;
  excerpt: string | null;
  author: string | null;
  published_at: string | null;
  format: string;
  lang: string | null;
  visibility: "internal" | "public";
  metrics: { views: number; outlier: number | null; engagement: number; velocity_h: number } | null;
  visibility_proxy: number | null;
  hook: string | null;
  evidence_level: "api" | "search_index";
};
export type TrendOpportunity = {
  id: string;
  type: "linkedin_gap" | "join_trend" | "early_bet" | "language_arbitrage" | "audience_ask";
  topic_id: string;
  persona: string;
  platform: TrendPlatform;
  format: string;
  score: number;
  why_now: string;
  proposal: { title_options: string[]; hook: string; outline: string[]; length: string };
  evidence: string[];
};
export type TrendReport = {
  run: {
    run_id: string;
    generated_at: string;
    window: { from: string; to: string };
    output_platforms: TrendPlatform[];
    sources: {
      youtube: { items: number; creators: number; quota_used: number; visibility: string };
      linkedin: { items: number; providers: string[] };
    };
    cost_usd: { search: number; llm: number };
  };
  brand: { coverage_source: string | null; coverage_topics: string[]; voice: string | null; languages: string[]; regions: string[] };
  topics: TrendTopic[];
  items: TrendItem[];
  patterns: { pattern: string; label: string; evidence: "youtube_lift" | "linkedin_usage"; lift: number | null; support: number; examples: string[] }[];
  audience_voice: { theme: string; mentions: number; type: "question" | "objection" | "request"; topic_id: string | null }[];
  opportunities: TrendOpportunity[];
  data_quality: { coverage_level: string; warnings: string[] };
};
export type TrendRunSummary = {
  id: string;
  brand_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  platforms: TrendPlatform[];
  window_days: number;
  batch_id: string | null;
  cost: { search: number; llm: number; youtube_units: number } | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  totals: { topics: number; opportunities: number } | null;
};
export type TrendRunDetail = TrendRunSummary & {
  identity: { personas: { id: string; name: string }[] };
  report: TrendReport | null;
};
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const data = await response.json();
      detail = Array.isArray(data.detail)
        ? data.detail
            .map(
              (e: { loc: string[]; msg: string }) =>
                `${e.loc.join(".")}: ${e.msg}`,
            )
            .join("\n")
        : data.detail || detail;
    } catch {
      /* Preserve HTTP error if the response is not JSON. */
    }
    throw new Error(detail);
  }
  return response.json();
}
