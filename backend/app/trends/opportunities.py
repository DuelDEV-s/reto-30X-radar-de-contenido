"""S7 judgment + S9: persona rubric and why-it-works (Sonnet), opportunity typing and scoring,
proposals (top model) with evidence and number validation, one regeneration, then drop."""
import json
import re
from typing import Literal

from pydantic import BaseModel

from .contracts import BrandIdentity, Opportunity, Proposal
from .scoring import STAGE_BONUS, TopicStats


# --- Rubric + why it works (one Sonnet call for the top topics) ----------------
class PersonaFit(BaseModel):
    persona_id: str
    problem: int        # 0-3: does it address this persona's real problems?
    actionable: int     # 0-3: can the persona act on it?
    level: int          # 0-3: right depth for this persona?
    market: int         # 0-3: fits the brand's market and language?


class TopicJudgment(BaseModel):
    topic_id: str
    personas: list[PersonaFit]
    brand_fit: float            # 0-1
    why_it_works: list[str]     # 3 bullets that cite only numbers given in the input


class Judgments(BaseModel):
    topics: list[TopicJudgment]


JUDGE_SYSTEM = """You evaluate content topics for a brand's content team. Score honestly; most topics
should not score 3 everywhere. Every number you write must come from the input metrics. Never invent
engagement numbers for LinkedIn: LinkedIn data is post counts and author counts only."""


def judge_topics(llm, identity: BrandIdentity, payload: list[dict], main_lang: str) -> dict[str, TopicJudgment]:
    personas = "\n".join(f"- {p.id}: {p.name}. {p.description}. Pains: {', '.join(p.pains)}"
                         for p in identity.personas)
    prompt = f"""Brand: {identity.brand_name}. {identity.description}
Personas:
{personas}

Topics with their metrics (YouTube = audience demand; LinkedIn = how many people post about it):
{json.dumps(payload, ensure_ascii=False, indent=1)}

For every topic: score each persona 0-3 on problem, actionable, level, market; give brand_fit 0-1; and
write 3 short why_it_works bullets in {main_lang} explaining why the topic works with this audience,
citing the metrics given."""
    res = llm.sonnet(JUDGE_SYSTEM, prompt, Judgments, effort="medium", max_tokens=32000)
    return {j.topic_id: j for j in res.topics}


def persona_relevance(j: TopicJudgment | None, persona_ids: list[str]) -> dict[str, float]:
    if not j:
        return {p: 0.0 for p in persona_ids}
    fits = {f.persona_id: f for f in j.personas}
    return {p: round(sum(min(max(x, 0), 3) for x in (fits[p].problem, fits[p].actionable,
                                                      fits[p].level, fits[p].market)) / 12, 3)
            if p in fits else 0.0 for p in persona_ids}


# --- Typing -------------------------------------------------------------------
def opportunity_type(s: TopicStats, max_rel: float, brand_lang: str, has_audience_ask: bool) -> str | None:
    if s.li_gap > 0.3:
        return "linkedin_gap"
    if s.stage == "emerging" and max_rel >= 0.5:
        return "early_bet"
    if s.trend_status == "validated" and s.stage in ("emerging", "growing"):
        return "join_trend"
    if brand_lang != "en" and s.en_share >= 0.6 and s.brand_lang_items < 5 and s.yt_momentum > 0:
        return "language_arbitrage"
    if has_audience_ask:
        return "audience_ask"
    if s.growth_raw > 0 and STAGE_BONUS[s.stage] > 0:
        return "join_trend"
    return None


# --- Number and evidence validation -------------------------------------------
_NUM = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?![\d.,])|\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> list[tuple[float, ...]]:
    """Each number with its possible readings: "0.857" is a decimal, "184.000" is a thousands
    separator in Spanish, and "1.731" could be either."""
    out = []
    for tok in _NUM.findall(text or ""):
        readings = set()
        if re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", tok):
            readings.add(float(re.sub(r"[.,]", "", tok)))
        if re.fullmatch(r"\d+(?:[.,]\d+)?", tok):
            readings.add(float(tok.replace(",", ".")))
        out.append(tuple(readings))
    return out


def allowed_numbers(obj) -> set[float]:
    vals: set[float] = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            for v in (x, abs(x)):                 # "baja 20%" cites -0.2 without the sign
                vals.update({float(v), round(float(v), 1), float(round(v))})
                if v <= 10:                       # ratios also appear as percentages
                    vals.update({round(v * 100, 1), float(round(v * 100))})
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(obj)
    return vals


def numbers_ok(text: str, allowed: set[float]) -> bool:
    def ok(n: float) -> bool:
        if n <= 10 or 2020 <= n <= 2035:          # counts like "3 ideas", "8 slides", years
            return True
        return any(abs(n - a) <= max(0.5, 0.02 * abs(a)) for a in allowed)
    return all(any(ok(n) for n in readings) for readings in numbers_in(text))


# --- Proposals ----------------------------------------------------------------
class ProposalOut(BaseModel):
    opportunity_id: str
    persona: str
    format: Literal["post", "carousel", "video", "article", "poll", "document"]
    why_now: str
    title_options: list[str]
    hook: str
    outline: list[str]
    length: str
    evidence: list[str]


class Proposals(BaseModel):
    proposals: list[ProposalOut]


PROPOSE_SYSTEM = """You are a senior content strategist writing LinkedIn content proposals for a brand.
Each proposal must be specific, publishable this week, written in the brand's voice and language, and
justified only with the metrics and evidence items provided. Every number in why_now must appear in
the input. evidence may only contain item ids listed for that opportunity. Never claim LinkedIn
engagement numbers: LinkedIn data is post and author counts only; audience demand comes from YouTube.
Write why_now for a marketer: express growth as percentages (0.85 -> "85%"), outliers as "4.1x lo
normal del canal", and never name internal metrics such as li_gap, outlier or demand_momentum."""


def propose(llm, identity: BrandIdentity, voice: str | None, opps: list[dict], patterns: list[dict],
            main_lang: str, feedback: str = "") -> dict[str, ProposalOut]:
    personas = [{"id": p.id, "name": p.name, "description": p.description} for p in identity.personas]
    prompt = f"""Brand: {identity.brand_name}. {identity.description}
Voice: {voice or "not available; write clearly and practically"}
Language: {main_lang}
Personas: {json.dumps(personas, ensure_ascii=False)}
Winning patterns: {json.dumps(patterns, ensure_ascii=False)}

Opportunities:
{json.dumps(opps, ensure_ascii=False, indent=1)}
{feedback}
Return one proposal per opportunity id: persona (one of the persona ids), LinkedIn format, why_now
(1-2 sentences with numbers from the input), 3 title_options, the hook (first line), an outline of 4-8
points, the length (e.g. "8 slides", "250 words"), and evidence (2-4 item ids from that opportunity)."""
    res = llm.top(PROPOSE_SYSTEM, prompt, Proposals, effort="high", max_tokens=32000)
    return {p.opportunity_id: p for p in res.proposals}


def validate(p: ProposalOut, opp: dict, persona_ids: set[str]) -> str | None:
    """None when valid, else the reason."""
    allowed_ids = {e["item_id"] for e in opp["evidence_items"]}
    bad = [e for e in p.evidence if e not in allowed_ids]
    if bad or not p.evidence:
        return f"evidence ids not allowed or missing: {bad}"
    if p.persona not in persona_ids:
        return f"unknown persona {p.persona}"
    if not numbers_ok(p.why_now, allowed_numbers(opp)):
        return f"why_now has numbers not in the input: {p.why_now}"
    if len(p.title_options) < 3:
        return "fewer than 3 titles"
    return None


def build_opportunities(llm, identity, voice, opps: list[dict], patterns: list[dict], main_lang: str,
                        warnings: list[str]) -> list[Opportunity]:
    persona_ids = {p.id for p in identity.personas}
    by_id = {o["id"]: o for o in opps}
    props = propose(llm, identity, voice, opps, patterns, main_lang)
    failed = {oid: validate(props[oid], o, persona_ids) if oid in props else "missing"
              for oid, o in by_id.items()}
    failed = {k: v for k, v in failed.items() if v}
    if failed:
        retry = propose(llm, identity, voice, [by_id[k] for k in failed], patterns, main_lang,
                        feedback="\nFix these problems from your previous attempt:\n"
                                 + "\n".join(f"- {k}: {v}" for k, v in failed.items()))
        for k in list(failed):
            if k in retry and not validate(retry[k], by_id[k], persona_ids):
                props[k] = retry[k]
                del failed[k]
    for k, reason in failed.items():
        warnings.append(f"Dropped proposal {k} after one regeneration: {reason}")
    out = []
    for oid, o in by_id.items():
        if oid in failed or oid not in props:
            continue
        p = props[oid]
        out.append(Opportunity(
            id=oid, type=o["type"], topic_id=o["topic_id"], persona=p.persona, platform="linkedin",
            format=p.format, score=o["score"], why_now=p.why_now,
            proposal=Proposal(title_options=p.title_options[:3], hook=p.hook, outline=p.outline,
                              length=p.length),
            evidence=p.evidence,
            chart_refs=[f"topics.{o['topic_id']}.linkedin.timeseries", f"topics.{o['topic_id']}.demand.timeseries"]))
    return out
