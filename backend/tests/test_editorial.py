"""Cross-engine read contract: no providers, frozen evidence, brand scoping and units."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event

from app import main, post_review, trend_runs
from app.database import Brand, DiscoveryCandidate, DiscoveryRun, InstagramAccount, InstagramPost, PostTopicReview, RunTopicMap, TikTokAccount, TikTokPost, TrendRun, get_session
from app.media import preview, stored_thumbnail
from app.trends.contracts import Report
from app.trends.mock import MOCK


def session():
    return next(main.app.dependency_overrides[get_session]())


def test_demo_is_frozen_and_never_embeds_or_links_fake_urls(client):
    demo = client.post("/api/demo").json()
    bid = demo["brand"]["id"]
    sources = client.get(f"/api/brands/{bid}/editorial-sources").json()
    response = client.get(f"/api/brands/{bid}/editorial-report", params={"source": sources[0]["id"]})
    assert response.status_code == 200
    report = response.json()
    assert report["source"]["demo"] and report["counts"]["posts"] == 18
    assert sources[0]["progress"]["ready"] and sources[0]["progress"]["counts"] == {"posts": 18}
    assert report["counts"]["topics"] == 6
    assert report["topics"][0]["proposals"][0]["hook"]
    assert all(e["url"] is None and e["preview"]["embed_url"] is None for t in report["topics"] for e in t["evidence"])
    assert report["topics"][0]["series"][0]["unit"] == "vistas"
    assert report == client.get(f"/api/brands/{bid}/editorial-report", params={"source": sources[0]["id"]}).json()
    other = client.post("/api/demo").json()["brand"]["id"]
    assert client.get(f"/api/brands/{other}/editorial-report", params={"source": sources[0]["id"]}).status_code == 404
    assert client.get(f"/api/brands/{bid}/editorial-report", params={"source": "bad:123"}).status_code == 404


@pytest.mark.parametrize("platforms", [["linkedin", "youtube"], ["linkedin"], ["youtube"]])
def test_engine_report_preserves_proposals_units_and_frozen_identity_without_side_effects(client, monkeypatch, platforms):
    bid = client.post("/api/demo").json()["brand"]["id"]
    with session() as db:
        brand = db.get(Brand, bid)
        saved = Report.model_validate(deepcopy(MOCK)).model_dump(mode="json", by_alias=True)
        run = TrendRun(brand_id=bid, status="done", stage="report", platforms=platforms, window_days=28,
                       identity=trend_runs.engine_identity(brand, platforms, 28).model_dump(mode="json"), report=saved)
        db.add(run); db.commit(); source = f"trend:{run.id}"
    def forbidden(*args, **kwargs):
        pytest.fail("Reading the editorial report must not invoke providers or execute writes")
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    statements = []
    engine = session().bind
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(f"/api/brands/{bid}/editorial-report", params={"source": source})
        inventory = client.get(f"/api/brands/{bid}/editorial-sources").json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    saved_source = next(s for s in inventory if s["id"] == source)
    assert saved_source["progress"]["ready"] and saved_source["progress"]["label"] == "Informe guardado"
    data = response.json()
    assert not data["identity_changed"] and data["identity"]["personas"][0]["role"]
    assert data["topics"][0]["priority"] == 61
    for topic in data["topics"]:
        assert {s["platform"] for s in topic["series"]} == set(platforms)
        assert all(e["platform"] in platforms for e in topic["evidence"])
    assert all(not s.startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    if "linkedin" in platforms:
        li = [e for t in data["topics"] for e in t["evidence"] if e["platform"] == "linkedin"]
        assert li and all(e["views"] is None for e in li)
        assert data["topics"][0]["proposals"][0]["hook"] == MOCK["opportunities"][0]["proposal"]["hook"]
    with session() as db:
        brand = db.get(Brand, bid)
        brand.identity = brand.identity | {"audience": "Otra audiencia confirmada"}
        db.commit()
    changed = client.get(f"/api/brands/{bid}/editorial-report", params={"source": source}).json()
    assert changed["identity_changed"] and changed["identity"] == data["identity"]


@pytest.mark.parametrize("platform", ["instagram", "tiktok"])
def test_creator_run_can_be_inspected_before_posts_exist(client, platform):
    bid = client.post("/api/demo").json()["brand"]["id"]
    with session() as db:
        brand = db.get(Brand, bid)
        run = DiscoveryRun(brand_id=bid, status="completed", topic="agentes de IA", platform=platform,
                           hl="es", countries=[], max_queries=1, profiles_only=False, resolve_posts=False,
                           identity=brand.identity, query_count=1, result_count=0, candidate_count=0,
                           discarded_count=0, unresolved_count=0)
        db.add(run); db.commit(); source = f"creator:{run.id}"
    response = client.get(f"/api/brands/{bid}/editorial-report", params={"source": source})
    assert response.status_code == 200, response.text
    assert response.json()["topics"] == [] and response.json()["warnings"]
    assert not response.json()["source"]["progress"]["ready"]


def test_inventory_distinguishes_search_profiles_and_posts_without_advancing_jobs(client):
    bid = client.post("/api/demo").json()["brand"]["id"]
    with session() as db:
        brand = db.get(Brand, bid)
        run = DiscoveryRun(brand_id=bid, status="completed", topic="IA", platform="instagram", hl="es", countries=[], max_queries=1,
                           profiles_only=False, resolve_posts=False, identity=brand.identity, query_count=1, result_count=5,
                           candidate_count=3, discarded_count=2, unresolved_count=0)
        db.add(run); db.commit(); source_id = f"creator:{run.id}"
        def source():
            return next(s for s in client.get(f"/api/brands/{bid}/editorial-sources").json() if s["id"] == source_id)
        progress = source()["progress"]
        assert not progress["ready"] and progress["label"] == "Búsqueda guardada"
        assert progress["counts"]["candidates"] == 3
        run.profiles_state = "pending"; db.commit()
        assert source()["progress"]["label"] == "Perfiles: en proceso"
        db.refresh(run)
        assert run.profiles_state == "pending" and run.profiles_snapshot_id is None
        run.posts_state = "failed"; db.commit()
        assert source()["progress"]["label"] == "Publicaciones: con error"
        run.posts_state = "ready"; db.commit()
        assert source()["progress"]["ready"]


@pytest.mark.parametrize("platform", ["instagram", "tiktok"])
def test_creator_report_uses_real_baselines_and_cached_reviews(client, platform):
    bid = client.post("/api/demo").json()["brand"]["id"]
    now = datetime.now(timezone.utc)
    with session() as db:
        brand = db.get(Brand, bid)
        run = DiscoveryRun(brand_id=bid, status="completed", topic="agentes de IA", platform=platform, hl="es", countries=[], max_queries=1,
                           profiles_only=False, resolve_posts=False, identity=brand.identity, query_count=1, result_count=1,
                           candidate_count=1, discarded_count=0, unresolved_count=0, profiles_state="ready", posts_state="ready")
        db.add(run); db.flush()
        db.add(DiscoveryCandidate(run_id=run.id, username="marca.qa", query_hits=1, best_rank=1))
        account_model = TikTokAccount if platform == "tiktok" else InstagramAccount
        post_model = TikTokPost if platform == "tiktok" else InstagramPost
        db.add(account_model(username="marca.qa", followers=10000, raw={}, fetch_status="ok", fetched_at=now, posts_fetched_at=now))
        for i in range(10):
            code = str(7412345678901234567 + i) if platform == "tiktok" else f"QA{i}"
            url = f"https://www.tiktok.com/@marca.qa/video/{code}" if platform == "tiktok" else f"https://www.instagram.com/reel/{code}/"
            p = post_model(shortcode=code, username="marca.qa", url=url, content_type="video" if platform == "tiktok" else "reel",
                           caption="Agentes de IA para equipos", likes=100 + i if i < 9 else 4000,
                           comments=5, views=(1000 + i * 10 if i < 9 else 80000) if platform == "tiktok" else None,
                           posted_at=now - timedelta(days=4 + i * 2), observed_at=now,
                           raw={"thumbnail_url": "https://p16.tiktokcdn.com/fixture.jpg" if platform == "tiktok" else "https://scontent.cdninstagram.com/fixture.jpg"})
            db.add(p); db.flush()
            db.add(PostTopicReview(platform=platform, shortcode=code, topic_key=post_review.topic_key(run.topic), topic=run.topic,
                                   relevance="alta", content_kind="educativo", subtopics=["Agentes para equipos"], needs_transcript=False,
                                   used_transcript=False, reason="Caso aplicado al trabajo", model="fixture", effort="low",
                                   input_digest=post_review.digest(post_review.evidence(p))))
        db.commit(); source = f"creator:{run.id}"; run_id = run.id
    data = client.get(f"/api/brands/{bid}/editorial-report", params={"source": source}).json()
    assert len(data["topics"]) == 1 and data["counts"]["posts"] == 10
    t = data["topics"][0]
    assert t["signals"][0]["unit"] == "×" and t["series"][0]["unit"] == "piezas"
    assert sum(p["value"] for p in t["series"][0]["points"]) == 10
    assert t["evidence"][0]["performance"] > 1 and t["evidence"][0]["preview"]["platform"] == platform
    assert t["evidence"][0]["preview"]["thumbnail_url"].endswith("/fixture.jpg")
    assert t["proposals"][0]["platform"] == platform and "agrupación semántica" in " ".join(data["warnings"])
    with session() as db:
        db.add(RunTopicMap(run_id=run_id, labels_digest="old", model="fixture", topics=[{"name": "Tema agrupado", "description": "Guardado", "labels": ["Agentes para equipos"]}]))
        db.commit()
    grouped = client.get(f"/api/brands/{bid}/editorial-report", params={"source": source}).json()
    assert grouped["topics"][0]["label"] == "Tema agrupado"
    assert "anterior" in " ".join(grouped["warnings"])


@pytest.mark.parametrize("url,platform", [
    ("https://youtu.be/abcdefghijk", "youtube"),
    ("https://youtube.com/shorts/abcdefghijk", "youtube"),
    ("https://instagram.com/reel/Example_123/", "instagram"),
    ("https://www.tiktok.com/@marca/video/7412345678901234567", "tiktok"),
    ("https://www.linkedin.com/posts/marca-ejemplo-activity-7385012345678901234-abcd", "linkedin"),
])
def test_official_media_descriptor(url, platform):
    p = preview(url)
    assert p["platform"] == platform and p["embed_url"].startswith("https://")
    assert preview(url, demo=True)["embed_url"] is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://evil.test/watch?v=abcdefghijk", "https://youtube.com.evil.test/watch?v=abcdefghijk", "https://user:pass@youtube.com/watch?v=abcdefghijk", "https://youtube.com:444/watch?v=abcdefghijk", "https://www.linkedin.com/in/persona", "https://youtu.be/invalid", "https://instagram.com/accounts/login/"])
def test_untrusted_or_unsupported_media_stays_unembedded(url):
    assert preview(url)["embed_url"] is None


def test_thumbnail_uses_saved_images_and_never_accepts_arbitrary_hosts():
    tt = "https://www.tiktok.com/@marca/video/7412345678901234567"
    cover = "https://p16.tiktokcdn.com/cover.jpeg?signature=fixture"
    assert stored_thumbnail({"video": {"cover": {"url_list": [cover]}}}, "tiktok") == cover
    assert preview(tt, thumbnail=cover)["thumbnail_url"] == cover
    assert preview(tt, demo=True, thumbnail=cover)["thumbnail_url"] is None
    assert preview("https://youtu.be/abcdefghijk")["thumbnail_url"] == "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"
    for bad in ["http://p16.tiktokcdn.com/a.jpg", "https://p16.tiktokcdn.com.evil.test/a.jpg", "https://127.0.0.1/a.jpg", "https://user:pass@p16.tiktokcdn.com/a.jpg", "https://p16.tiktokcdn.com:444/a.jpg", "data:image/png;base64,AAAA"]:
        assert stored_thumbnail({"thumbnail_url": bad}, "tiktok") is None
        assert preview(tt, thumbnail=bad)["thumbnail_url"] is None
    assert stored_thumbnail({"thumbnail_url": cover, "is_private": True}, "tiktok") is None
