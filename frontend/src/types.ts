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
  author_source: "url" | "snippet" | "oembed" | "video" | null;
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
  // Solo TikTok: likes acumulados por todos sus videos.
  likes_total?: number | null;
  query_hits: number;
  best_rank: number;
  sources: { query: string; link: string; rank: number; author_source: string }[];
};
export type DiscoveryPlatform = "instagram" | "tiktok";
export type DiscoveryRunSummary = {
  id: string;
  brand_id: string;
  status: "completed" | "partial" | "failed" | "pending";
  created_at: string;
  topic: string | null;
  platform: DiscoveryPlatform;
  countries: string[];
  max_queries: number;
  totals: {
    queries: number;
    results: number;
    candidates: number;
    discarded: number;
    unresolved: number;
  };
  // TikTok: búsqueda asíncrona de videos por palabra clave. Instagram queda en not_started.
  search: { state: StageState; message: string; updated_at: string | null };
  profiles: { state: StageState; message: string; requested: number; updated_at: string | null };
  posts: { state: StageState; message: string; requested: number; updated_at: string | null };
};
export type StageState = "not_started" | "requesting" | "pending" | "ready" | "failed" | "unknown";
export type PostLabel = "viral" | "sobresaliente" | "normal" | "bajo" | "sin_linea_base";
export type PostSignal = {
  observed: number;
  projected: number;
  baseline: number;
  ratio: number;
  z: number;
  baseline_posts: number;
};
export type CreatorPost = {
  shortcode: string;
  url: string;
  username: string;
  author: string | null;
  content_type: "reel" | "video" | "carousel" | "image" | "unknown";
  caption: string;
  hashtags: string[];
  posted_at: string;
  observed_at: string;
  likes: number | null;
  comments: number | null;
  views: number | null;
  plays: number | null;
  shares: number | null;
  saves: number | null;
  duration_seconds: number | null;
  is_paid_partnership: boolean | null;
  is_pinned: boolean | null;
  coauthors: string[];
  audio: string | null;
  performance: number | null;
  z: number | null;
  label: PostLabel;
  confidence: "alta" | "media" | "baja";
  provisional: boolean;
  age_hours: number;
  maturity: number;
  baseline_scope: "formato" | "todos";
  signals: Partial<Record<"views" | "likes" | "shares" | "comments", PostSignal>>;
  comment_bait: boolean;
  engagement_rate: number | null;
  velocity: { hours: number; observations: number; likes_per_hour: number | null; comments_per_hour: number | null } | null;
  transcript: string | null;
  transcript_status: string | null;
  transcript_seconds: number | null;
  topic_review: {
    relevance: "alta" | "media" | "baja" | "ninguna";
    on_topic: boolean;
    content_kind: string;
    subtopics: string[];
    reason: string;
    used_transcript: boolean;
    needs_transcript: boolean;
  } | null;
};
export type CreatorBaseline = {
  posts: number;
  mature_posts: number;
  posts_per_week: number;
  formats: { video: number; static: number };
  median_views: number | null;
  median_likes: number | null;
  median_comments: number | null;
  median_shares: number | null;
  median_engagement_rate: number | null;
  followers: number | null;
};
export type RunPosts = DiscoveryRunSummary & {
  window_days: number;
  posts_per_creator: number;
  method: {
    tau_hours: { video: number; static: number };
    min_age_hours: number;
    min_baseline_posts: number;
    weights: Partial<Record<"views" | "likes" | "shares" | "comments", number>>;
  };
  creators: (Pick<DiscoveryCandidate, "username" | "profile_url" | "full_name" | "followers" | "avatar_url" | "is_verified"> & { posts_fetched_at: string | null; baseline: CreatorBaseline | null })[];
  topic: string;
  topic_review: { enabled: boolean; reviewed: number; pending: number; on_topic: number; off_topic: number };
  transcripts: { enabled: boolean; reels: number; done: number; pending: number; failed: number; expires_at: string | null };
  min_followers: number;
  excluded_small: { username: string; followers: number | null }[];
  items: CreatorPost[];
};
export type TrendState =
  | "en_caliente" | "emergente" | "en_ascenso" | "consolidado" | "estable" | "saturado" | "enfriandose" | "insuficiente" | "otros";
export type InstagramTrendTopic = {
  name: string;
  description: string;
  subtopics: string[];
  state: TrendState;
  posts: number;
  creators: number;
  recent_posts: number;
  previous_posts: number;
  recent_creators: number;
  traction: number | null;
  share: number;
  adoption_change: number | null;
  performance_change: number | null;
  momentum: number | null;
  cells: { week: string; posts: number; creators: number; median_performance: number | null }[];
  formats: { reel: number; video?: number; carousel: number; image: number };
  evidence: { shortcode: string; url: string; username: string; performance: number; label: PostLabel; content_type: string; caption: string }[];
  production: Record<string, string | number> | null;
};
export type RunTrends = DiscoveryRunSummary & {
  topic: string;
  state: "waiting" | "ready";
  reviews_pending: number;
  grouping_enabled: boolean;
  stale: boolean;
  weeks: string[];
  topics: InstagramTrendTopic[];
  post_count?: number;
};
export type PatternTrait = { trait: string; value: string | boolean; top: number; control: number; lift: number };
export type RunPatterns = DiscoveryRunSummary & {
  enabled: boolean;
  clip_seconds: number;
  reviews_pending: number;
  progress: { targets: number; done: number; pending: number; failed: number; expires_at: string | null };
  groups: { top: number; control: number };
  patterns: PatternTrait[];
  common: PatternTrait[];
  avoid: PatternTrait[];
  shared: PatternTrait[];
  items: {
    shortcode: string;
    group: "top" | "control";
    url: string;
    username: string;
    performance: number | null;
    label: PostLabel;
    status: string | null;
    features: Record<string, string | boolean> | null;
    seconds: number | null;
  }[];
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
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    // El navegador solo dice "Failed to fetch": la API no responde (detenida o reiniciándose).
    throw new Error("No hay conexión con la API. Verifica que el backend esté en marcha y vuelve a intentarlo.");
  }
  // La sesión del PIN expiró o cambió: recargar vuelve a mostrar la pantalla de acceso.
  if (response.status === 401 && !path.startsWith("/auth/")) {
    window.location.reload();
  }
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
