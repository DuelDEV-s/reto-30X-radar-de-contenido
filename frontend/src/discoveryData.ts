import type { CreatorPost, PostLabel } from "./types";

export const POST_LABELS: Record<PostLabel, string> = {
  viral: "Viral", sobresaliente: "Sobresaliente", normal: "Normal", bajo: "Bajo", sin_linea_base: "Sin línea base",
};
export const POST_COLORS: Record<PostLabel, string> = {
  viral: "#355f40", sobresaliente: "#72945c", normal: "#a6b8a0", bajo: "#b28a5e", sin_linea_base: "#d6ddd2",
};
export const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
export const metric = (n: number | null | undefined) => n == null ? "N/D" : new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 }).format(n);
export const relative = (n: number | null | undefined) => n == null ? "Sin base" : `${new Intl.NumberFormat("es", {maximumFractionDigits: 2}).format(n)}×`;
export const shortDate = (s: string) => new Date(s).toLocaleDateString("es", {day:"numeric",month:"short",timeZone:"UTC"});

export function postSummary(items: CreatorPost[]) {
  const comparable = items.filter(p => finite(p.performance) && p.performance >= 0);
  const values = comparable.map(p => p.performance!).sort((a,b) => a-b);
  const half = Math.floor(values.length / 2);
  return {
    pieces: items.length, creators: new Set(items.map(p => p.username)).size,
    comparable: values.length,
    median: !values.length ? null : values.length % 2 ? values[half] : (values[half-1] + values[half]) / 2,
    above: comparable.filter(p => p.performance! > 1).length,
    buckets: (Object.keys(POST_LABELS) as PostLabel[]).map(label => ({label, name:POST_LABELS[label], count:items.filter(p => p.label === label).length, color:POST_COLORS[label]})),
  };
}

/** Counts collected pieces by UTC week, never platform-wide publication volume. */
export function weeklyPosts(items: Pick<CreatorPost, "posted_at">[]) {
  const counts = new Map<number, number>();
  for (const item of items) {
    const date = new Date(item.posted_at);
    if (!Number.isFinite(date.getTime())) continue;
    date.setUTCHours(0,0,0,0);
    date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
    counts.set(date.getTime(), (counts.get(date.getTime()) || 0) + 1);
  }
  const weeks = [...counts.keys()].sort((a,b) => a-b);
  if (!weeks.length) return [];
  const span = (weeks[weeks.length-1] - weeks[0]) / 604800000;
  // An unexpectedly wide input stays bounded without silently discarding pieces.
  const bins = span <= 104 ? Array.from({length:span+1}, (_,i) => weeks[0]+i*604800000) : weeks;
  return bins.map(time => ({date:new Date(time).toISOString(), posts:counts.get(time) || 0}));
}

export type PostFilters = {creator:string; search:string; label:string; format:string; onlyTopic:boolean; sort:"performance" | "views" | "recent"};
export function filterPosts(items: CreatorPost[], filters: PostFilters) {
  const query = filters.search.trim().toLocaleLowerCase("es");
  const result = items.filter(p => (!filters.creator || p.username === filters.creator)
    && (!filters.label || p.label === filters.label) && (!filters.format || p.content_type === filters.format)
    && (!filters.onlyTopic || !p.topic_review || p.topic_review.on_topic)
    && (!query || `${p.caption} ${p.username} ${(p.topic_review?.subtopics || []).join(" ")}`.toLocaleLowerCase("es").includes(query)));
  return result.sort((a,b) => {
    if (filters.sort === "recent") return Date.parse(b.posted_at) - Date.parse(a.posted_at);
    const key = filters.sort === "views" ? "views" : "performance";
    const av = finite(a[key]) ? a[key]! : -Infinity, bv = finite(b[key]) ? b[key]! : -Infinity;
    return av === bv ? a.shortcode.localeCompare(b.shortcode) : bv - av;
  });
}
