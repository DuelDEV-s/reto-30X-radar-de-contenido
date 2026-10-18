import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.database import AccountReview, InstagramAccount
from app.main import app, get_bright_data_client, get_post_resolver, get_serp_client, get_session
from app.post_metrics import MIN_AGE_HOURS, PostSample, analyze, label, maturity, score_post, velocity
from app.post_store import normalize_post, parse_date
from tests.test_discovery import FakeResolver, FakeSerp, result

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def post(id, days_ago, likes=100, comments=10, fmt="video", followers=10_000, username="ana"):
    return PostSample(id=id, username=username, format=fmt, posted_at=NOW - timedelta(days=days_ago), observed_at=NOW,
                      likes=likes, comments=comments, followers=followers)


def steady(n=10, likes=200, comments=20):
    return [post(f"p{i}", 3 + i * 2, likes=likes + i * 2, comments=comments + i % 3) for i in range(n)]


def test_maturity_grows_with_age_and_is_floored():
    assert maturity(0, "video") == maturity(MIN_AGE_HOURS, "video")
    assert maturity(24, "static") < maturity(72, "static") < 1
    # A los 3 días un estático ya acumuló casi todo; un reel todavía no.
    assert maturity(72, "static") > 0.95 > maturity(72, "video")


def test_outlier_post_is_viral_and_normal_post_is_normal():
    peers = steady()
    hit = post("hit", 5, likes=1_500, comments=120)
    score = score_post(hit, peers + [hit])
    assert score["label"] == "viral" and score["performance"] > 3 and score["confidence"] == "alta"
    assert score["signals"]["likes"]["baseline_posts"] == 10 and not score["comment_bait"]
    assert score_post(peers[3], peers)["label"] == "normal"


def test_comment_bait_weighs_less_than_likes_and_is_flagged():
    peers = steady()
    # "Comenta IA y te lo envío": ×50 en comentarios, likes normales.
    bait = post("bait", 6, likes=210, comments=1_000)
    score = score_post(bait, peers + [bait])
    assert score["comment_bait"] and score["signals"]["comments"]["ratio"] > 30
    assert score["performance"] < 4 < score["signals"]["comments"]["ratio"]
    # El mismo pico en likes sí es viral.
    reach = post("reach", 6, likes=10_000, comments=20)
    assert score_post(reach, peers + [reach])["performance"] > score["performance"]


def test_young_post_is_compared_by_projection_not_raw_counts():
    peers = steady()
    # 1 día de vida con 150 likes: en bruto está por debajo de la base, proyectado está por encima.
    young = post("young", 1, likes=150, comments=15)
    score = score_post(young, peers + [young])
    assert score["signals"]["likes"]["observed"] < score["signals"]["likes"]["baseline"] < score["signals"]["likes"]["projected"]
    assert score["performance"] > 1 and not score["provisional"]
    fresh = post("fresh", 0.01, likes=1, comments=0)
    fresh_score = score_post(fresh, peers + [fresh])
    assert fresh_score["provisional"] and fresh_score["confidence"] == "baja"
    # Un post provisional no entra en la línea base de los demás.
    assert score_post(peers[0], peers + [fresh])["signals"]["likes"]["baseline_posts"] == 9


def test_hidden_likes_and_missing_baseline():
    peers = steady(3)
    assert score_post(peers[0], peers)["label"] == "sin_linea_base"
    hidden = post("hidden", 4, likes=None, comments=25)
    score = score_post(hidden, steady() + [hidden])
    assert set(score["signals"]) == {"comments"} and score["engagement_rate"] is None and score["confidence"] == "baja"
    assert label(None, None) == "sin_linea_base" and label(0.5, -1) == "bajo"


def test_static_posts_use_their_own_baseline_and_followers_only_inform():
    statics = [post(f"s{i}", 2 + i, likes=50, comments=5, fmt="static") for i in range(5)]
    target = post("s_hit", 3, likes=150, comments=10, fmt="static")
    score = score_post(target, steady() + statics + [target])
    assert score["baseline_scope"] == "formato"
    assert 50 <= score["signals"]["likes"]["baseline"] <= 52
    assert score["engagement_rate"] == round(160 / 10_000, 4)


def test_tiny_audiences_do_not_produce_virals():
    # Cuenta grande con likes casi nulos (audiencia inactiva u ocultos): 2 likes frente a una base de 0 no es viral.
    peers = [post(f"d{i}", 3 + i, likes=0, comments=0, fmt="static", followers=35_000) for i in range(15)]
    two = post("two", 4, likes=2, comments=0, fmt="static", followers=35_000)
    score = score_post(two, peers + [two])
    assert score["label"] == "normal" and score["confidence"] == "baja"


def test_analyze_groups_by_creator():
    small = [post(f"a{i}", 3 + i, likes=20, comments=2, followers=2_000, username="small") for i in range(6)]
    big = [post(f"b{i}", 3 + i, likes=20_000, comments=900, followers=2_000_000, username="big") for i in range(6)]
    scores, baselines = analyze(small + big, 30)
    # Cada creador se compara con sí mismo: el grande no es "mejor" por tamaño.
    assert scores["a0"]["label"] == scores["b0"]["label"] == "normal"
    assert baselines["big"]["median_likes"] > 19_000 and baselines["small"]["posts_per_week"] == 1.4


def test_velocity_needs_two_readings_apart():
    t = NOW
    assert velocity([(t, 100, 10)]) is None
    assert velocity([(t, 100, 10), (t + timedelta(hours=2), 120, 11)]) is None
    v = velocity([(t + timedelta(hours=12), 160, 13), (t, 100, 10), (t + timedelta(hours=6), 130, None)])
    assert v == {"hours": 12.0, "observations": 3, "likes_per_hour": 5.0, "comments_per_hour": 0.25}


def test_normalize_post_accepts_both_field_names():
    record = {"url": "https://www.instagram.com/reel/ABC123/?igsh=x", "user_posted": "Coautor", "discovery_input": {"url": "https://www.instagram.com/ana/"},
              "date_posted": "2026-10-10T10:00:00.000Z", "likes": -1, "num_comments": 12, "video_view_count": 900, "video_play_count": 1500,
              "product_type": "clips", "followers": 5000, "hashtags": ["#ia"], "coauthor_producers": ["ana"], "tagged_users": [{"username": "luis"}],
              "videos_duration": [{"url": "https://cdn.example.com/v.mp4", "video_duration": 31.5}], "is_paid_partnership": False}
    values = normalize_post(record, {"ana"})
    assert values["shortcode"] == "ABC123" and values["url"] == "https://www.instagram.com/reel/ABC123/"
    assert (values["username"], values["author"], values["content_type"]) == ("ana", "coautor", "reel")
    assert (values["likes"], values["comments"], values["views"], values["plays"]) == (None, 12, 900, 1500)
    assert values["duration_seconds"] == 31.5 and values["tagged_users"] == ["luis"] and values["raw"] is record
    other = {"url": "https://www.instagram.com/p/XYZ99/", "account": "ana", "datetime": "2026-10-01T00:00:00Z", "comments": 3, "content_type": "Carousel"}
    assert normalize_post(other, {"ana"})["content_type"] == "carousel"
    assert normalize_post(other, {"luis"}) is None
    assert normalize_post({"url": "https://www.instagram.com/ana/", "error": "x"}, {"ana"}) is None
    assert parse_date(1760000000) == datetime.fromtimestamp(1760000000, timezone.utc)


@pytest.fixture
def run_with_profiles(client, monkeypatch):
    brand_id = client.post("/api/demo").json()["brand"]["id"]
    serp = FakeSerp()
    app.dependency_overrides[get_serp_client] = lambda: serp
    app.dependency_overrides[get_post_resolver] = lambda: FakeResolver({})
    query = client.post(f"/api/brands/{brand_id}/discovery-queries", json={"max_queries": 1}).json()["queries"][0]["query"]
    serp.pages[query] = [result("https://www.instagram.com/ana/", rank=1), result("https://www.instagram.com/priv/", rank=2),
                         result("https://www.instagram.com/medio/", rank=3), result("https://www.instagram.com/mini/", rank=4)]
    run_id = client.post(f"/api/brands/{brand_id}/creator-search", json={"max_queries": 1}).json()["run_id"]
    session = next(app.dependency_overrides[get_session]())
    stamp = datetime.now(timezone.utc)
    session.add_all([
        InstagramAccount(username="ana", followers=10_000, external_urls=[], raw={}, fetch_status="ok", fetched_at=stamp),
        InstagramAccount(username="priv", external_urls=[], raw={}, fetch_status="private", fetched_at=stamp),
        InstagramAccount(username="medio", followers=90_000, external_urls=[], raw={}, fetch_status="ok", fetched_at=stamp),
        InstagramAccount(username="mini", followers=1_500, external_urls=[], raw={}, fetch_status="ok", fetched_at=stamp),
        AccountReview(brand_id=brand_id, username="medio", relevance="alta", account_type="medio", is_internal=False, reason="x",
                      model="m", effort="low", identity_digest="d", profile_digest="d"),
    ])
    session.commit()
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHT_DATA_INSTAGRAM_DATASET_ID", "gd_profiles")
    return run_id, session


def test_posts_flow_collects_once_and_ranks_against_baseline(client, run_with_profiles, monkeypatch):
    run_id, _ = run_with_profiles
    assert client.post(f"/api/discovery-runs/{run_id}/posts").status_code == 409  # perfiles sin pedir
    client.post(f"/api/discovery-runs/{run_id}/profiles")
    now = datetime.now(timezone.utc)
    records = [{"url": f"https://www.instagram.com/reel/R{i}/", "user_posted": "ana", "discovery_input": {"url": "https://www.instagram.com/ana"},
                "date_posted": (now - timedelta(days=7 + i)).isoformat(), "likes": 100 + i, "num_comments": 5,
                "product_type": "clips"} for i in range(8)]
    records.append({**records[0], "url": "https://www.instagram.com/reel/HIT/", "likes": 4_000, "num_comments": 60})
    records.append({"input": {"url": "https://www.instagram.com/ana"}, "error": "no posts"})
    triggers, ready, downloads = [], set(), []

    def bright(request):
        if request.url.path.endswith("/trigger"):
            triggers.append((dict(request.url.params), json.loads(request.content)))
            return httpx.Response(200, json={"snapshot_id": "sd_posts"})
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": "ready" if ready else "running"})
        downloads.append(1)
        # Como en Bright Data real: con progreso "ready" la primera descarga puede seguir armándose.
        if len(downloads) == 1:
            return httpx.Response(202, json={"status": "building", "message": "Snapshot is building, try again in 30s"})
        return httpx.Response(200, json=records)

    async def override():
        async with httpx.AsyncClient(transport=httpx.MockTransport(bright)) as http:
            yield http
    app.dependency_overrides[get_bright_data_client] = override

    started = client.post(f"/api/discovery-runs/{run_id}/posts").json()
    # Sin revisor LLM entran los perfiles públicos: @priv (privada) y @mini (menos de 2.000 seguidores) quedan fuera.
    assert [c["username"] for c in started["creators"]] == ["ana", "medio"]
    assert started["excluded_small"] == [{"username": "mini", "followers": 1500}] and started["min_followers"] == 2000
    assert started["items"] == [] and started["posts"]["state"] == "pending" and started["posts"]["requested"] == 2
    params, body = triggers[0]
    assert params["discover_by"] == "url" and params["limit_per_input"] == "30"
    assert [b["url"] for b in body] == ["https://www.instagram.com/ana", "https://www.instagram.com/medio"]
    assert body[0]["num_of_posts"] == 30 and len(body[0]["start_date"]) == 10
    assert client.get(f"/api/discovery-runs/{run_id}/posts").json()["items"] == []
    ready.add(True)
    building = client.get(f"/api/discovery-runs/{run_id}/posts").json()
    assert building["posts"]["state"] == "pending" and building["creators"][0]["posts_fetched_at"] is None
    done = client.get(f"/api/discovery-runs/{run_id}/posts").json()
    assert done["posts"]["state"] == "ready" and "9 posts recibidos de 2 creadores" in done["posts"]["message"]
    top = done["items"][0]
    assert top["shortcode"] == "HIT" and top["label"] == "viral"
    assert {p["label"] for p in done["items"][1:]} <= {"normal", "bajo"}
    ana = next(c for c in done["creators"] if c["username"] == "ana")
    assert ana["baseline"]["posts"] == 9 and ana["posts_fetched_at"]

    again = client.post(f"/api/discovery-runs/{run_id}/posts").json()
    assert len(triggers) == 1 and len(again["items"]) == 9 and "Sin costo" in again["posts"]["message"]


def test_llm_review_filters_post_creators(client, run_with_profiles, monkeypatch):
    run_id, session = run_with_profiles
    client.post(f"/api/discovery-runs/{run_id}/profiles")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    from app.main import get_reviewer
    app.dependency_overrides[get_reviewer] = lambda: None
    # Solo @medio tiene veredicto y es un medio: no pasa; sin creadores no se inicia nada.
    response = client.post(f"/api/discovery-runs/{run_id}/posts")
    assert response.status_code == 409 and "Ningún candidato" in response.json()["detail"]
