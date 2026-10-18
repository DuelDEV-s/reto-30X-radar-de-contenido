import pytest
from datetime import datetime, timedelta, timezone

from app.trends import linkedin, scoring
from app.trends.mock import MOCK
from app.trends.contracts import Report
from app.trends.opportunities import numbers_ok, allowed_numbers, persona_relevance, TopicJudgment, PersonaFit

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def activity_id(dt: datetime) -> str:
    return str((int(dt.timestamp() * 1000) << 22) | 12345)


# --- LinkedIn -----------------------------------------------------------------
def test_post_time_round_trips():
    when = datetime(2026, 10, 14, 13, 5, 7, tzinfo=timezone.utc)
    aid = activity_id(when)
    assert len(aid) == 19
    url = f"https://mx.linkedin.com/posts/ana-perez-123abc_ia-ventas-activity-{aid}-AbCd?utm=x"
    assert linkedin.post_time(url) == when


def test_parse_url_kinds():
    aid = activity_id(NOW)
    post = linkedin.parse_url(f"https://www.linkedin.com/posts/ana-perez_ia-activity-{aid}-x")
    assert post == {"item_id": f"li:{aid}", "url": f"https://www.linkedin.com/posts/ana-perez_ia-activity-{aid}-x",
                    "format": "post", "author_slug": "ana-perez"}
    assert linkedin.parse_url(f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/")["item_id"] == f"li:{aid}"
    assert linkedin.parse_url("https://www.linkedin.com/pulse/como-usar-ia-ana-perez-abc")["format"] == "article"
    assert linkedin.parse_url("https://www.linkedin.com/in/ana-perez") is None
    assert linkedin.parse_url("https://example.com/posts/x") is None


def test_to_item_keeps_only_short_excerpt_and_author():
    aid = activity_id(NOW - timedelta(days=2))
    it = linkedin.to_item({"url": f"https://www.linkedin.com/posts/ana-perez_x-activity-{aid}-y",
                           "title": "Ana Pérez en LinkedIn: Mi agente vendió 40", "text": "x" * 2000,
                           "published": None, "author": None})
    assert it["author"] == "Ana Pérez"
    assert it["creator_id"] == "li-author:ana-perez"
    assert len(it["excerpt"]) == linkedin.EXCERPT_CHARS
    assert it["published_at"].startswith("2026-10-15")


def test_visibility_proxy_prefers_top_ranked_multi_hit_posts():
    hits = {"a": [("q1", "exa", 1), ("q2", "brave", 2)], "b": [("q1", "exa", 9)]}
    p = linkedin.visibility_proxies(hits, {"a": 3, "b": 1}, {"a": 1, "b": 1}, total_queries=10)
    assert p["a"] > p["b"] > 0


# --- Scoring ------------------------------------------------------------------
def test_pct_rank_handles_ties_and_single():
    assert scoring.pct_rank({"x": 5}) == {"x": 0.5}
    r = scoring.pct_rank({"a": 1, "b": 2, "c": 2, "d": 3})
    assert r["a"] == 0 and r["d"] == 1 and r["b"] == r["c"] == 0.5


def _item(i, platform, topic, days_ago, views=1000, creator=None, base=None, lang="es"):
    return scoring.Item(item_id=f"{platform[:2]}:{i}", platform=platform, creator_id=creator or f"c{i}",
                        published=NOW - timedelta(days=days_ago), format="long", topic_id=topic,
                        lang=lang, views=views, baseline={"long": base} if base else {})


def test_li_gap_rewards_high_demand_low_supply():
    items = []
    # t1: strong, growing YouTube demand, few LinkedIn posts
    items += [_item(f"a{i}", "youtube", "t1", d, views=50_000, base=10_000) for i, d in enumerate([1, 2, 3, 9, 10, 20])]
    items += [_item("la1", "linkedin", "t1", 2)]
    # t2: weak YouTube demand, crowded LinkedIn
    items += [_item(f"b{i}", "youtube", "t2", d, views=800, base=4_000) for i, d in enumerate([2, 12, 13, 19, 22])]
    items += [_item(f"lb{i}", "linkedin", "t2", d) for i, d in enumerate([1, 1, 2, 3, 4, 5, 6, 8, 9, 15])]
    scoring.normalize_attention([i for i in items if i.platform == "youtube"], NOW)
    stats = scoring.topic_stats(items, ["t1", "t2"], NOW, 4, "es")
    scoring.score_topics(stats)
    assert stats["t1"].li_gap > 0.3 > stats["t2"].li_gap
    assert stats["t1"].yt_quality == 5.0 and stats["t2"].yt_quality == 0.2
    assert stats["t2"].trend_status in ("hype_risk", "stable")
    assert stats["t1"].li_weekly[-1] == 1 and sum(stats["t2"].li_weekly) == 10


def test_attention_compares_same_age_and_halves_videos_under_48h():
    fresh = [_item("f1", "youtube", "t", 1, views=1000), _item("f2", "youtube", "t", 1, views=3000)]
    old = [_item("o1", "youtube", "t", 20, views=50_000), _item("o2", "youtube", "t", 20, views=150_000)]
    scoring.normalize_attention(fresh + old, NOW)
    # Each video is measured against its own age group, so old videos don't win for being old.
    assert old[0].attention == 0.5 and old[1].attention == 1.5
    # Same relative position, but videos under 48 h count half.
    assert fresh[0].attention == 0.25 and fresh[1].attention == 0.75


def test_haiku_only_mode_routes_every_call_to_haiku(monkeypatch):
    from app.trends import config
    monkeypatch.setenv("RADAR_LLM", "haiku")
    monkeypatch.setenv("RADAR_TOP_MODEL", "opus")
    assert config.judgment_model() == config.top_model() == config.HAIKU
    monkeypatch.setenv("RADAR_LLM", "")
    assert config.judgment_model() == config.SONNET and config.top_model() == config.OPUS


def test_brave_is_optional(monkeypatch):
    from app.trends.providers import search
    monkeypatch.setenv("BRAVE_API_KEY", "")
    assert search.enabled_providers() == ["exa"]
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    assert search.enabled_providers() == ["exa", "brave"]


def test_trend_status_untested_without_youtube():
    s = scoring.TopicStats("t", yt_items=2, li_growth=2.0)
    assert scoring.trend_status(s, 0.1, 0.0) == "untested"


def test_opportunity_score_is_zero_for_zero_confidence():
    s = scoring.TopicStats("t", li_gap=0.8, growth_pct=1, stage="emerging", confidence=0)
    assert scoring.opportunity_score(s, 1, 1, 1) == 0


# --- Validation ---------------------------------------------------------------
def test_numbers_ok_accepts_input_numbers_and_percentages():
    allowed = allowed_numbers({"growth": 0.85, "posts": 41, "views": 184000})
    assert numbers_ok("Creció 85% y hay 41 posts; 184.000 vistas", allowed)
    assert numbers_ok("3 ideas para 2026", allowed)
    assert not numbers_ok("Generó 999 leads", allowed)
    # "0.857" is a decimal, not 857 with a thousands separator
    assert numbers_ok("una brecha de 0.857 y -0.464", allowed_numbers({"gap": 0.857, "g": -0.464}))
    assert numbers_ok("la demanda baja 38%", allowed_numbers({"momentum": -0.38}))
    # Numbers quoted from an evidence title and large growth ratios are part of the input too.
    opp = {"metrics": {"youtube_demand_momentum_wow": 17.07},
           "evidence_items": [{"text": "5 clients in 30 days (no audience, no ads)", "views": 19000}]}
    assert numbers_ok("'5 clients in 30 days' creció 1707%", allowed_numbers(opp))
    assert not numbers_ok("llegó a 45 clientes", allowed_numbers(opp))


def test_persona_relevance_from_rubric():
    j = TopicJudgment(topic_id="t1", brand_fit=0.8, why_it_works=[],
                      personas=[PersonaFit(persona_id="exec", problem=3, actionable=3, level=3, market=3)])
    assert persona_relevance(j, ["exec", "dev"]) == {"exec": 1.0, "dev": 0.0}


def test_mock_report_matches_contract():
    report = Report.model_validate(MOCK)
    ids = {i.item_id for i in report.items}
    assert all(e in ids for o in report.opportunities for e in o.evidence)
    assert '"from"' in report.to_json()


# --- Platform modes -------------------------------------------------------------
def _yt_only_items():
    items = [_item(f"a{i}", "youtube", "t1", d, views=50_000, base=10_000) for i, d in enumerate([1, 2, 3, 9, 10, 20])]
    items += [_item(f"b{i}", "youtube", "t2", d, views=800, base=4_000) for i, d in enumerate([2, 12, 13, 19, 22])]
    scoring.normalize_attention(items, NOW)
    return items


def test_youtube_mode_ranks_by_demand_without_supply():
    stats = scoring.topic_stats(_yt_only_items(), ["t1", "t2"], NOW, 4, "es")
    scoring.score_topics(stats, "youtube")
    assert stats["t1"].li_gap == 0 == stats["t2"].li_gap
    assert stats["t1"].signal > stats["t2"].signal
    assert stats["t1"].trend_status == "validated" and stats["t2"].trend_status != "hype_risk"
    assert stats["t1"].confidence > 0


def test_linkedin_mode_uses_supply_growth_and_never_claims_validation():
    items = [_item(f"l{i}", "linkedin", "t1", d, creator=f"a{i}") for i, d in enumerate([1, 1, 2, 3, 5, 6, 9])]
    items += [_item(f"m{i}", "linkedin", "t2", d, creator="same") for i, d in enumerate([8, 9, 10, 12, 15, 16, 20])]
    stats = scoring.topic_stats(items, ["t1", "t2"], NOW, 4, "es")
    scoring.score_topics(stats, "linkedin")
    assert {s.trend_status for s in stats.values()} == {"untested"}
    assert stats["t1"].li_growth > stats["t2"].li_growth and stats["t1"].growth_pct > stats["t2"].growth_pct
    assert all(s.li_gap == 0 and s.stage != "insufficient_data" for s in stats.values())
    assert stats["t1"].confidence > 0


def test_youtube_quota_429_stops_further_searches(monkeypatch):
    import httpx
    from app.trends import db as store
    from app.trends.providers.youtube import QuotaExceeded, YouTube

    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, json={"error": {"message": "Quota exceeded for quota metric 'Search Queries'"}})

    yt = YouTube(store.connect(":memory:"), key="k")
    yt.http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(QuotaExceeded):
        yt.search("ia", "2026-10-01T00:00:00Z", "es", "MX")
    with pytest.raises(QuotaExceeded):
        yt.search("otra", "2026-10-01T00:00:00Z", "es", "MX")
    assert len(calls) == 1 and yt.search_blocked and not yt.quota_exhausted


def test_proposal_platform_and_format_follow_the_selection():
    from app.trends.opportunities import ProposalOut, validate
    opp = {"evidence_items": [{"item_id": "yt:a"}], "metrics": {}}
    base = dict(opportunity_id="op1", persona="exec", why_now="Crece", title_options=["a", "b", "c"],
                hook="h", outline=["x"], length="8 min", evidence=["yt:a"])
    ok = ProposalOut(platform="youtube", format="short", **base)
    assert validate(ok, opp, {"exec"}, ["youtube"]) is None
    assert "not valid for youtube" in validate(ProposalOut(platform="youtube", format="carousel", **base), opp, {"exec"}, ["youtube"])
    assert "was not selected" in validate(ProposalOut(platform="linkedin", format="post", **base), opp, {"exec"}, ["youtube"])
