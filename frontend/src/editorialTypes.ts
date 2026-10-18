import type { Identity } from "./types";
export type EditorialSource = {
  id: string;
  kind: string;
  label: string;
  networks: string[];
  created_at: string;
  status: string;
  demo: boolean;
  progress: {
    stage: string;
    ready: boolean;
    label: string;
    description: string;
    counts: Record<string, number>;
  };
};
export type Preview = {
  embed_url: string | null;
  platform: string | null;
  orientation: string;
  thumbnail_url?: string | null;
};
export type EditorialEvidence = {
  id: string;
  url: string | null;
  platform: string;
  title: string;
  excerpt: string;
  author: string | null;
  published_at: string | null;
  format: string;
  views: number | null;
  performance: number | null;
  evidence_level: string;
  preview: Preview;
};
export type EditorialProposal = {
  title: string;
  persona: string;
  platform: string | null;
  format: string;
  hook: string;
  outline: string[];
  why_now: string;
  measurement: string;
  length?: string;
};
export type EditorialTopic = {
  id: string;
  label: string;
  description: string;
  stage: string;
  priority: number;
  confidence: string;
  networks: string[];
  fit: string;
  why: string[];
  signals: { label: string; value: number | null; unit: string }[];
  series: {
    label: string;
    unit: string;
    platform: string;
    points: { date: string; value: number | null }[];
  }[];
  evidence: EditorialEvidence[];
  proposals: EditorialProposal[];
};
export type EditorialReport = {
  schema_version: string;
  source: EditorialSource;
  brand_name: string;
  identity: Identity;
  identity_changed: boolean;
  observed_at: string;
  topics: EditorialTopic[];
  warnings: string[];
  methodology: string;
  counts: { posts: number; creators: number | null; topics: number };
  cost_usd: number | null;
  format_insights: {
    label: string;
    basis: string;
    support: number;
    lift: number | null;
  }[];
  patterns: {
    label: string;
    top: number;
    control: number;
    difference: number;
    top_n: number;
    control_n: number;
  }[];
  audience_voice: {
    theme: string;
    mentions: number;
    type: string;
    topic_id: string | null;
  }[];
};
