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
