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
