import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.account_review import Verdict, brand_handles
from app.database import AccountReview, Brand, TikTokAccount, TikTokPost
from app.main import app, get_bright_data_client, get_reviewer, get_session
from app.post_metrics import PostSample, score_post
from app.query_builder import QueryContext, build_queries
from app.tiktok_accounts import account_fields, profile_username, username_from
from app.tiktok_posts import normalize_post
from app.tiktok_search import FoundVideo, keywords, select_candidates
from app.transcription import expires_at

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def found(author, keyword="ia", rank=1, followers=50_000, views=10_000, days_ago=3):
    return FoundVideo(keyword=keyword, rank=rank, url=f"https://www.tiktok.com/@{author}/video/{rank}", author=author,
                      followers=followers, views=views, posted_at=NOW - timedelta(days=days_ago))


def select(videos, limit=10):
    return select_candidates(videos, brand_handles={"crece30x"}, now=NOW, min_followers=5000, max_age_days=180, limit=limit)


def test_candidates_prefer_creators_constant_on_the_topic():
    videos = [
        found("viral", "ia", 1, views=5_000_000),             # un solo video, muy visto
        found("ana", "ia", 4, views=20_000), found("ana", "agentes de ia", 2, views=30_000),
        found("luis", "ia", 2, views=40_000), found("luis", "ia", 3, views=10_000),
    ]
    candidates, outcomes = select(videos)
    # Aparecer en dos palabras clave pesa más que un viral suelto o dos videos de la misma búsqueda.
    assert [c["username"] for c in candidates] == ["ana", "luis", "viral"]
    assert candidates[0] == {"username": "ana", "query_hits": 2, "best_rank": 2, "videos": 2, "median_views": 25_000}
    assert all(o["outcome"] == "candidate" for o in outcomes)


def test_candidates_discard_brand_small_stale_and_beyond_cap():
    videos = [
        found("crece30x"), found(None), found("mini", followers=800), found("viejo", days_ago=400),
        found("sin_dato", rank=3, followers=None), found("a", rank=1), found("b", rank=2),
    ]
    candidates, outcomes = select(videos, limit=2)
    assert [c["username"] for c in candidates] == ["a", "b"]
    reasons = [o["reason"] for o in outcomes]
    assert reasons[:4] == ["cuenta de la marca", "video sin autor identificable", "menos de 5000 seguidores", "solo videos de hace más de 180 días"]
    # Sin dato de seguidores no se descarta por tamaño: se decide con su perfil. Aquí queda fuera por el tope.
    assert reasons[4] == "fuera del tope de 2 candidatos" and reasons[5:] == [None, None]


def test_keywords_drop_google_operators_and_duplicates():
    plan = build_queries(QueryContext(topics=["agentes de IA", "automatización"], region="Latinoamérica", platform="tiktok", max_queries=6))
    terms = keywords(plan)
    assert terms and all('"' not in t and "site:" not in t for t, _ in terms)
    assert len({t for t, _ in terms}) == len(terms) and terms[0][1].query.startswith("site:tiktok.com")


def test_normalize_video_accepts_scraper_variants():
    record = {"url": "https://www.tiktok.com/@Ana.IA/video/7412345678901234567?is_from_webapp=1", "post_id": "7412345678901234567",
              "description": "Agentes de IA para ventas", "create_time": "2026-10-10T10:00:00.000Z", "digg_count": 900,
              "comment_count": 40, "share_count": 120, "collect_count": 300, "play_count": 25_000, "video_duration": 42,
              "hashtags": ["ia", {"name": "agentes"}], "profile_username": "ana.ia", "profile_followers": 80_000,
              "original_sound": {"title": "sonido original"}, "video_url": "https://v16.tiktokcdn.com/x.mp4?x-expires=1760000000",
              "discovery_input": {"search_keyword": "agentes de ia"}}
    values = normalize_post(record)
    assert values["video_id"] == "7412345678901234567" and values["username"] == values["author"] == "ana.ia"
    assert values["url"] == "https://www.tiktok.com/@ana.ia/video/7412345678901234567" and values["content_type"] == "video"
    assert (values["views"], values["likes"], values["comments"], values["shares"], values["saves"]) == (25_000, 900, 40, 120, 300)
    assert values["hashtags"] == ["ia", "agentes"] and values["audio"] == "sonido original" and values["followers"] == 80_000
    # Por perfil: el creador es el perfil pedido.
    by_profile = {**record, "discovery_input": {"url": "https://www.tiktok.com/@ana.ia"}}
    assert normalize_post(by_profile, {"ana.ia"})["username"] == "ana.ia" and normalize_post(by_profile, {"luis"}) is None
    photo = {"url": "https://www.tiktok.com/@luis/photo/7400000000000000001", "create_time": 1760000000, "likes": 5}
    assert normalize_post(photo)["content_type"] == "image" and normalize_post(photo)["author"] == "luis"
    assert normalize_post({"url": "https://www.tiktok.com/@luis", "error": "not found"}) is None
    assert normalize_post({"url": "https://www.tiktok.com/@luis/video/123", "create_time": 1760000000}) is None  # id no válido
    assert expires_at(record["video_url"]) == datetime.fromtimestamp(1760000000, timezone.utc)


def test_profile_fields_and_usernames():
    assert username_from("@Ana.IA") == "ana.ia" and username_from("https://www.tiktok.com/@luis?lang=es") == "luis"
    assert username_from("https://www.instagram.com/@luis") is None and username_from("https://www.tiktok.com/video/1") is None
    record = {"url": "https://www.tiktok.com/@ana.ia", "nickname": "Ana", "signature": "IA para pymes", "follower_count": 80_000,
              "likes": 3_000_000_000, "videos_count": 210, "is_verified": False, "private_account": False, "region": "CO",
              "bio_link": "https://ana.ai"}
    assert profile_username(record) == "ana.ia" and profile_username({"input": {"url": "https://www.tiktok.com/@x"}}) == "x"
    fields = account_fields(record)
    assert (fields["nickname"], fields["biography"], fields["followers"], fields["likes_total"]) == ("Ana", "IA para pymes", 80_000, 3_000_000_000)
    assert fields["is_private"] is False and fields["external_urls"] == ["https://ana.ai"] and fields["region"] == "CO"


def test_brand_handles_by_platform():
    brand = Brand(brief={"profiles": [{"platform": "instagram", "url": "https://www.instagram.com/crece30x/"},
                                      {"platform": "tiktok", "url": "https://www.tiktok.com/@Crece30X"}]}, identity={})
    assert brand_handles(brand, "instagram") == ["crece30x"] and brand_handles(brand, "tiktok") == ["crece30x"]


def tiktok_video(id, days_ago, views, likes, shares=10, comments=5):
    return PostSample(id=id, username="ana", format="video", posted_at=NOW - timedelta(days=days_ago), observed_at=NOW,
                      likes=likes, comments=comments, followers=50_000, views=views, shares=shares, platform="tiktok")


def test_tiktok_scores_on_views_first():
    peers = [tiktok_video(f"v{i}", 3 + i, views=10_000 + i * 100, likes=500 + i * 5) for i in range(10)]
    reach = tiktok_video("reach", 5, views=200_000, likes=520)
    score = score_post(reach, peers + [reach])
    assert set(score["signals"]) == {"views", "likes", "shares", "comments"}
    assert score["label"] == "viral" and score["confidence"] == "alta"
    # Los mismos likes extra sin vistas pesan mucho menos.
    likes_only = tiktok_video("likes", 5, views=10_100, likes=10_000)
    assert score_post(likes_only, peers + [likes_only])["performance"] < score["performance"]


VIDEOS = [
    ("7400000000000000001", "ana.ia", 80_000, "Agentes de IA para ventas"),
    ("7400000000000000002", "ana.ia", 80_000, "Automatiza tu CRM con IA"),
    ("7400000000000000003", "mini", 900, "IA"),
    ("7400000000000000004", "luis", None, "Cómo usar agentes"),
]


def search_records(terms):
    now = datetime.now(timezone.utc)
    records = []
    for i, (video_id, author, followers, text) in enumerate(VIDEOS):
        records.append({"url": f"https://www.tiktok.com/@{author}/video/{video_id}", "post_id": video_id, "description": text,
                        "create_time": (now - timedelta(days=2 + i)).isoformat(), "play_count": 10_000 * (i + 1), "digg_count": 300,
                        "comment_count": 10, "share_count": 5, "profile_username": author, "profile_followers": followers,
                        # ana aparece en las dos palabras clave; el resto en la primera.
                        "discovery_input": {"search_keyword": terms[i % 2] if author == "ana.ia" else terms[0]}})
    records.append({"discovery_input": {"search_keyword": terms[0]}, "error": "no results", "error_code": "no_results"})
    return records


class FakeAccountReviewer:
    model, effort = "fake", "low"

    def __init__(self):
        self.calls = []

    async def review(self, brand, evidence):
        self.calls.append((brand, evidence))
        return Verdict(relevance="alta", account_type="creador", is_internal=False, reason="Videos sobre agentes de IA.")


@pytest.fixture
def bright(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k")
    state = {"triggers": [], "ready": set(), "records": {}}

    def handler(request):
        if request.url.path.endswith("/trigger"):
            params, body = dict(request.url.params), json.loads(request.content)
            snapshot = f"sd_{params['discover_by'] if 'discover_by' in params else 'profiles'}"
            state["triggers"].append((params, body))
            return httpx.Response(200, json={"snapshot_id": snapshot})
        snapshot = request.url.path.rsplit("/", 1)[-1]
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": "ready" if snapshot in state["ready"] else "running"})
        return httpx.Response(200, json=state["records"][snapshot])

    async def override():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield http
    app.dependency_overrides[get_bright_data_client] = override
    return state


def test_tiktok_flow_search_profiles_review_and_posts(client, bright, monkeypatch):
    brand_id = client.post("/api/demo").json()["brand"]["id"]
    started = client.post(f"/api/brands/{brand_id}/tiktok-search", json={"max_queries": 2, "videos_per_keyword": 10})
    assert started.status_code == 202
    run = started.json()
    terms = [q["query"] for q in run["queries"]]
    params, body = bright["triggers"][0]
    assert params["discover_by"] == "keyword" and params["type"] == "discover_new" and params["dataset_id"] == "gd_lu702nij2f790tmv9h"
    assert body == [{"search_keyword": t, "num_of_posts": 10} for t in terms] and len(terms) == 2
    assert run["platform"] == "tiktok" and run["search"]["state"] == "pending" and run["candidates"] == []
    assert client.post(f"/api/discovery-runs/{run['id']}/profiles").status_code == 409  # la búsqueda no terminó

    bright["records"]["sd_keyword"] = search_records(terms)
    bright["ready"].add("sd_keyword")
    done = client.get(f"/api/discovery-runs/{run['id']}").json()
    assert done["search"]["state"] == "ready" and done["status"] == "completed"
    assert "4 videos de 2 palabras clave; 2 candidatos" in done["search"]["message"]
    assert [c["username"] for c in done["candidates"]] == ["ana.ia", "luis"]
    assert done["candidates"][0]["query_hits"] == 2 and done["candidates"][0]["profile_url"] == "https://www.tiktok.com/@ana.ia"
    hits = {h["link"].rsplit("/", 1)[-1]: h for q in done["queries"] for h in q["hits"]}
    assert hits["7400000000000000003"]["reason"] == "menos de 5000 seguidores"
    assert done["totals"] == {"queries": 2, "results": 4, "candidates": 2, "discarded": 1, "unresolved": 0}

    # Perfiles: @luis ya está guardado, solo se paga @ana.ia.
    db = next(app.dependency_overrides[get_session]())
    db.add(TikTokAccount(username="luis", followers=20_000, external_urls=[], raw={}, fetch_status="ok", fetched_at=datetime.now(timezone.utc)))
    db.commit()
    reviewer = FakeAccountReviewer()
    app.dependency_overrides[get_reviewer] = lambda: reviewer
    profiles = client.post(f"/api/discovery-runs/{run['id']}/profiles").json()
    assert bright["triggers"][1][1] == [{"url": "https://www.tiktok.com/@ana.ia"}] and profiles["profiles"]["requested"] == 1
    bright["records"]["sd_profiles"] = [{"url": "https://www.tiktok.com/@ana.ia", "nickname": "Ana", "biography": "IA para pymes",
                                         "followers": 80_000, "videos_count": 120, "is_private": False}]
    bright["ready"].add("sd_profiles")
    reviewed = client.get(f"/api/discovery-runs/{run['id']}/profiles").json()
    by_user = {c["username"]: c for c in reviewed["candidates"]}
    assert by_user["ana.ia"]["followers"] == 80_000 and by_user["ana.ia"]["review_status"] == "reviewed" and by_user["ana.ia"]["included"]
    brand_seen, evidence = next(call for call in reviewer.calls if call[1]["username"] == "ana.ia")
    assert evidence["platform"] == "tiktok" and evidence["recent_captions"] == ["Agentes de IA para ventas", "Automatiza tu CRM con IA"]
    assert "tiktok_accounts" in brand_seen and "instagram_accounts" not in brand_seen
    # El veredicto de TikTok no se confunde con uno de Instagram del mismo usuario.
    assert db.query(AccountReview).filter_by(username="ana.ia").one().platform == "tiktok"

    # Posts por perfil para la línea base.
    posts = client.post(f"/api/discovery-runs/{run['id']}/posts").json()
    params, body = bright["triggers"][2]
    assert params["discover_by"] == "profile_url" and [b["url"] for b in body] == ["https://www.tiktok.com/@ana.ia", "https://www.tiktok.com/@luis"]
    assert body[0]["num_of_posts"] == 30 and len(body[0]["start_date"]) == 10 and posts["posts"]["state"] == "pending"
    now = datetime.now(timezone.utc)
    bright["records"]["sd_profile_url"] = [
        {"url": f"https://www.tiktok.com/@ana.ia/video/75000000000000000{i:02d}", "description": f"video {i}",
         "create_time": (now - timedelta(days=3 + i)).isoformat(), "play_count": 20_000 + i * 100, "digg_count": 800,
         "comment_count": 20, "share_count": 30, "discovery_input": {"url": "https://www.tiktok.com/@ana.ia"}} for i in range(8)
    ] + [{"url": "https://www.tiktok.com/@ana.ia/video/7599999999999999999", "description": "agentes", "create_time": (now - timedelta(days=4)).isoformat(),
          "play_count": 900_000, "digg_count": 900, "comment_count": 20, "share_count": 30, "discovery_input": {"url": "https://www.tiktok.com/@ana.ia"}}]
    bright["ready"].add("sd_profile_url")
    ready = client.get(f"/api/discovery-runs/{run['id']}/posts").json()
    assert ready["posts"]["state"] == "ready" and ready["method"]["weights"]["views"] == 0.5
    top = ready["items"][0]
    assert top["shortcode"] == "7599999999999999999" and top["label"] == "viral" and top["views"] == 900_000 and top["shares"] == 30
    ana = next(c for c in ready["creators"] if c["username"] == "ana.ia")
    assert ana["baseline"]["median_views"] and ana["posts_fetched_at"]
    assert db.get(TikTokPost, "7599999999999999999").username == "ana.ia"
    assert client.get("/api/tiktok-accounts/ana.ia").json()["full_name"] == "Ana"
    # Sin patrones de producción en TikTok: el CDN no deja descargar los videos.
    assert client.get(f"/api/discovery-runs/{run['id']}/content-patterns").status_code == 409


def test_tiktok_search_requires_api_key(client):
    brand_id = client.post("/api/demo").json()["brand"]["id"]
    assert client.post(f"/api/brands/{brand_id}/tiktok-search", json={}).status_code == 503


VTT = """WEBVTT


00:00:00.000 --> 00:00:02.880
I'm going to show you how to build an AI employee

00:00:03.060 --> 00:00:06.060 align:start
one that works for you 24 7

00:00:06.061 --> 00:00:09.041
one that works for you 24 7

00:00:31.000 --> 00:00:33.000
después del corte
"""


def test_tiktok_subtitles_replace_transcription():
    import asyncio
    from types import SimpleNamespace
    from app.transcription import parse_vtt, subtitles

    text, seconds = parse_vtt(VTT, 30)
    assert text == "I'm going to show you how to build an AI employee one that works for you 24 7" and seconds == 9.0

    def handler(request):
        return httpx.Response(200, content=VTT.encode()) if request.url.path == "/ok.vtt" else httpx.Response(403)

    async def run(raw):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await subtitles(http, SimpleNamespace(raw=raw))
    assert asyncio.run(run({"subtitle_url": "https://v16m.tiktokcdn-us.com/ok.vtt"}))[0] == "ok"
    assert asyncio.run(run({"subtitle_url": "https://v16m.tiktokcdn-us.com/denied.vtt"}))[0] == "unavailable"
    assert asyncio.run(run({}))[0] == "no_speech"


def test_tiktok_trends_need_more_traction_to_be_hot():
    from app.topic_trends import state_of
    stats = {"posts": 6, "creators": 3, "recent_posts": 3, "previous_posts": 3, "recent_creators": 3,
             "traction": 2.0, "share": 0.05, "momentum": 0.1}
    assert state_of(stats) == "en_caliente"
    # El mismo ×2 en TikTok está dentro de su dispersión normal: rinde bien, pero no está en caliente.
    assert state_of(stats, "tiktok") == "consolidado"
    assert state_of({**stats, "traction": 3.0}, "tiktok") == "en_caliente"
