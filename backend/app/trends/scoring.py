"""S7: plain-code metrics. YouTube demand, LinkedIn supply, li_gap, trend status, stage.

Weekly buckets are rolling 7-day windows ending at `now` (bucket 0 = last 7 days), labeled with
their start date, so growth never compares a partial calendar week with a full one.
"""
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

STATUS_WEIGHT = {"validated": 1.0, "stable": 0.8, "untested": 0.6, "hype_risk": 0.4}
STAGE_BONUS = {"emerging": 1.0, "growing": 0.8, "peak": 0.4, "saturated": 0.1, "declining": 0.0,
               "insufficient_data": 0.0}
AGE_BUCKETS = [(0, 48), (48, 168), (168, 336), (336, 10 ** 9)]   # hours
# Videos under 48 h have noisy view counts, so they count half in the weekly series.
AGE_BUCKET_WEIGHT = {0: 0.5}


# --- small helpers ------------------------------------------------------------
def pct_rank(values: dict) -> dict:
    """Percentile rank in [0, 1]; ties share their average rank."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    ranks, i = {}, 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = ((i + j) / 2) / (len(ordered) - 1)
        i = j + 1
    return ranks


def percentile(values, p: float) -> float:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def growth(cur: float, prev: float, k: float = 3) -> float:
    return (cur - prev) / (prev + k)


def bucket_index(published: datetime, now: datetime) -> int:
    return int((now - published).total_seconds() // (7 * 86400))


def bucket_labels(now: datetime, n: int) -> list[str]:
    """Oldest first, labeled by each bucket's start date."""
    return [(now - timedelta(days=7 * (i + 1))).strftime("%Y-%m-%d") for i in reversed(range(n))]


def age_bucket(age_h: float) -> int:
    return next(i for i, (lo, hi) in enumerate(AGE_BUCKETS) if lo <= age_h < hi)


# --- item level ---------------------------------------------------------------
@dataclass
class Item:
    item_id: str
    platform: str
    creator_id: str | None
    published: datetime | None
    format: str
    topic_id: str | None = None
    lang: str | None = None
    hook: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    baseline: dict = field(default_factory=dict)
    momentum_h: float | None = None      # Δviews/Δh between the last two snapshots
    attention: float = 0.0               # age-normalized views (1.0 = typical for its age)
    proxy: float = 0.0                   # LinkedIn visibility proxy

    def outlier(self) -> float | None:
        base = self.baseline.get(self.format) or self.baseline.get("all")
        return round(self.views / base, 2) if base else None

    def engagement(self) -> float:
        return round((self.likes + 2 * self.comments) / self.views, 4) if self.views else 0.0


def age_hours(it: Item, now: datetime) -> float:
    return max((now - it.published).total_seconds() / 3600, 1) if it.published else 24 * 14


def normalize_attention(items: list[Item], now: datetime) -> None:
    """attention = views / median views of YouTube items of the same age bucket,
    down-weighted for the youngest bucket (AGE_BUCKET_WEIGHT)."""
    by_bucket: dict[int, list[int]] = {}
    for it in items:
        by_bucket.setdefault(age_bucket(age_hours(it, now)), []).append(it.views)
    medians = {b: max(statistics.median(v), 1) for b, v in by_bucket.items()}
    for it in items:
        b = age_bucket(age_hours(it, now))
        it.attention = it.views / medians[b] * AGE_BUCKET_WEIGHT.get(b, 1.0)


# --- topic level --------------------------------------------------------------
@dataclass
class TopicStats:
    topic_id: str
    yt_items: int = 0
    yt_demand: float = 0.0
    yt_weekly: list[float] = field(default_factory=list)      # oldest first
    yt_momentum: float = 0.0
    yt_momentum_prev: float = 0.0
    yt_quality: float | None = None
    en_share: float = 0.0
    brand_lang_items: int = 0
    li_items: int = 0
    li_weekly: list[int] = field(default_factory=list)
    li_authors_7d: int = 0
    li_growth: float = 0.0
    li_growth_prev: float = 0.0
    creators_weekly: list[int] = field(default_factory=list)
    novelty: float = 0.0
    li_gap: float = 0.0
    trend_status: str = "stable"
    stage: str = "insufficient_data"
    growth_raw: float = 0.0
    growth_pct: float = 0.0
    growth_prev_raw: float = 0.0
    signal: float = 0.0          # mode-specific opportunity signal, 0..1 (see score_topics)
    demand_level: str = "low"
    confidence: float = 0.0


def topic_stats(items: list[Item], topic_ids: list[str], now: datetime, weeks: int,
                brand_lang: str) -> dict[str, TopicStats]:
    out = {t: TopicStats(t, yt_weekly=[0.0] * weeks, li_weekly=[0] * weeks) for t in topic_ids}
    creators = {t: [set() for _ in range(weeks)] for t in topic_ids}
    li_authors_7d: dict[str, set] = {t: set() for t in topic_ids}
    outliers: dict[str, list[float]] = {t: [] for t in topic_ids}
    recent: dict[str, int] = {t: 0 for t in topic_ids}
    total: dict[str, int] = {t: 0 for t in topic_ids}
    en_att: dict[str, float] = {t: 0.0 for t in topic_ids}
    for it in items:
        if it.topic_id not in out or it.published is None:
            continue
        b = bucket_index(it.published, now)
        if b >= weeks:
            continue
        s, slot = out[it.topic_id], weeks - 1 - b
        total[it.topic_id] += 1
        recent[it.topic_id] += (now - it.published) <= timedelta(days=14)
        if it.creator_id:
            creators[it.topic_id][slot].add(it.creator_id)
        if it.platform == "youtube":
            s.yt_items += 1
            s.yt_weekly[slot] += it.attention
            s.yt_demand += it.attention
            if it.lang == "en":
                en_att[it.topic_id] += it.attention
            if it.lang == brand_lang:
                s.brand_lang_items += 1
            o = it.outlier()
            if o is not None:
                outliers[it.topic_id].append(o)
        else:
            s.li_items += 1
            s.li_weekly[slot] += 1
            if b == 0 and it.creator_id:
                li_authors_7d[it.topic_id].add(it.creator_id)
    # Momentum is measured on each topic's share of the week's total, scaled so the average topic
    # is 1.0. Discovery finds fewer recent items for every topic (search favors older, bigger
    # videos), so raw weekly sums would make every topic look like it is declining.
    n = max(len(out), 1)
    yt_tot = [sum(s.yt_weekly[i] for s in out.values()) or 1 for i in range(weeks)]
    li_tot = [sum(s.li_weekly[i] for s in out.values()) or 1 for i in range(weeks)]
    for t, s in out.items():
        yt_share = [s.yt_weekly[i] / yt_tot[i] * n for i in range(weeks)]
        li_share = [s.li_weekly[i] / li_tot[i] * n for i in range(weeks)]
        s.yt_quality = round(statistics.median(outliers[t]), 2) if outliers[t] else None
        s.creators_weekly = [len(c) for c in creators[t]]
        s.li_authors_7d = len(li_authors_7d[t])
        s.novelty = recent[t] / total[t] if total[t] else 0.0
        s.en_share = en_att[t] / s.yt_demand if s.yt_demand else 0.0
        if weeks >= 2:
            s.yt_momentum = growth(yt_share[-1], yt_share[-2], k=0.5)
            s.li_growth = growth(li_share[-1], li_share[-2], k=0.5)
        if weeks >= 3:
            s.yt_momentum_prev = growth(yt_share[-2], yt_share[-3], k=0.5)
            s.li_growth_prev = growth(li_share[-2], li_share[-3], k=0.5)
    return out


MODES = ("both", "youtube", "linkedin")


def score_topics(stats: dict[str, TopicStats], mode: str = "both") -> None:
    """Trend status, growth, stage, demand level, confidence and the opportunity signal (in place).

    mode "both":     signal = li_gap = pct_rank(YouTube demand x quality) - pct_rank(LinkedIn supply)
    mode "youtube":  signal = pct_rank(YouTube demand x quality); no supply side, li_gap = 0
    mode "linkedin": signal = growing but not crowded: 0.5 pct_rank(LinkedIn growth) + 0.5 (1 - pct_rank(authors));
                     no demand side, so every topic is "untested"
    """
    if not stats:
        return
    use_yt, use_li = mode in ("both", "youtube"), mode in ("both", "linkedin")
    s_all = list(stats.values())
    dq = pct_rank({s.topic_id: s.yt_demand * max(s.yt_quality or 1.0, 0.1) for s in s_all})
    supply = pct_rank({s.topic_id: s.li_items for s in s_all})
    p_mom = pct_rank({s.topic_id: s.yt_momentum for s in s_all})
    p_lig = pct_rank({s.topic_id: s.li_growth for s in s_all})
    p_dem = pct_rank({s.topic_id: s.yt_demand for s in s_all})
    p_auth = pct_rank({s.topic_id: s.li_authors_7d for s in s_all})
    li_g60 = percentile([s.li_growth for s in s_all], 0.6)
    mom_50 = percentile([s.yt_momentum for s in s_all], 0.5)
    w_yt, w_li = (0.6, 0.4) if mode == "both" else (1.0, 0.0) if mode == "youtube" else (0.0, 1.0)
    for s in s_all:
        t = s.topic_id
        s.li_gap = round(dq[t] - supply[t], 3) if mode == "both" else 0.0
        s.signal = round((s.li_gap + 1) / 2 if mode == "both" else dq[t] if mode == "youtube"
                         else 0.5 * p_lig[t] + 0.5 * (1 - p_auth[t]), 3)
        s.growth_raw = w_yt * s.yt_momentum + w_li * s.li_growth
        s.growth_prev_raw = w_yt * s.yt_momentum_prev + w_li * s.li_growth_prev
        s.growth_pct = w_yt * p_mom[t] + w_li * p_lig[t]
        s.trend_status = (trend_status(s, li_g60, mom_50) if mode == "both"
                          else youtube_status(s, mom_50) if mode == "youtube" else "untested")
        s.demand_level = ("high" if p_dem[t] >= 0.67 else "medium" if p_dem[t] >= 0.33 else "low") if use_yt else "low"
        if mode == "linkedin":
            sample = math.sqrt(min(1, s.li_items / 20))
        else:
            # Floor of 0.2 in "both" so LinkedIn-only topics (no YouTube presence) still rank, just lower.
            sample = math.sqrt(min(1, s.yt_items / 30))
            sample = max(0.2, sample) if use_li else sample
        s.confidence = round(sample * STATUS_WEIGHT[s.trend_status], 3)
    th = {
        "nov75": percentile([s.novelty for s in s_all], 0.75),
        "g75": percentile([s.growth_pct for s in s_all], 0.75),
        "g60": percentile([s.growth_pct for s in s_all], 0.60),
        "g40": percentile([s.growth_pct for s in s_all], 0.40),
        "g25": percentile([s.growth_pct for s in s_all], 0.25),
        "c50": percentile([s.creators_weekly[-1] for s in s_all], 0.50),
        "c75": percentile([s.creators_weekly[-1] for s in s_all], 0.75),
        "q60": percentile([s.yt_quality for s in s_all], 0.60),
        "q40": percentile([s.yt_quality for s in s_all], 0.40),
    }
    for s in s_all:
        s.stage = stage(s, th, use_quality=use_yt)


def trend_status(s: TopicStats, li_growth_p60: float, momentum_p50: float) -> str:
    if s.yt_items < 5:
        return "untested"
    if s.li_growth >= li_growth_p60 and s.li_growth > 0:
        # Demand backs the LinkedIn growth when videos over-perform or YouTube attention is rising.
        if (s.yt_quality or 0) >= 1.5 or (s.yt_momentum > 0 and s.yt_momentum >= momentum_p50):
            return "validated"
        if (s.yt_quality or 0) < 1.0:
            return "hype_risk"
    return "stable"


def youtube_status(s: TopicStats, momentum_p50: float) -> str:
    """YouTube alone: validated when the audience over-rewards the topic or its attention is rising."""
    if s.yt_items < 5:
        return "untested"
    if (s.yt_quality or 0) >= 1.5 or (s.yt_momentum > 0 and s.yt_momentum >= momentum_p50):
        return "validated"
    return "stable"


def stage(s: TopicStats, th: dict, use_quality: bool = True) -> str:
    """Lifecycle stage. Without YouTube there is no quality signal, so its conditions are skipped."""
    items = s.yt_items + s.li_items
    creators_now = s.creators_weekly[-1] if s.creators_weekly else 0
    creators_prev = s.creators_weekly[-2] if len(s.creators_weekly) > 1 else 0
    quality = s.yt_quality or 0
    rewarded = quality >= th["q60"] if use_quality else True
    unrewarded = quality <= th["q40"] if use_quality else s.growth_pct <= th["g40"]
    if items < 5:
        return "insufficient_data"
    if (s.novelty >= th["nov75"] and s.growth_pct >= th["g75"] and creators_now <= th["c50"]
            and rewarded and s.growth_raw > 0.3):
        return "emerging"
    if s.growth_raw < 0 and s.growth_prev_raw < 0 and s.growth_pct <= th["g25"]:
        return "declining"
    if creators_now >= th["c75"] and unrewarded:
        return "saturated"
    if s.growth_pct >= th["g60"] and creators_now > creators_prev and s.growth_raw > 0.1:
        return "growing"
    if th["g40"] <= s.growth_pct <= th["g60"] and creators_now >= th["c75"]:
        return "peak"
    if s.growth_raw > 0.1:
        return "growing"
    if s.growth_raw < -0.1:
        return "declining"
    if not use_quality:
        return "peak"
    return "peak" if quality >= 1 else "saturated"


def opportunity_score(s: TopicStats, persona_rel: float, brand_fit: float, coverage_gap: float) -> float:
    raw = (0.25 * s.signal + 0.20 * s.growth_pct + 0.20 * persona_rel
           + 0.15 * brand_fit + 0.10 * STAGE_BONUS[s.stage] + 0.10 * coverage_gap)
    return round(raw * s.confidence, 4)
