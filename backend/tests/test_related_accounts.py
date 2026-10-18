import json
from datetime import timedelta

import httpx
import pytest

from app.database import RelatedAccountRun
from app.main import app, get_bright_data_client, get_session
from app.related_accounts import MAX_ACCOUNTS, account_fields, extract_relations, profile_username

# Forma real de los reels de @crece30x devueltos por Bright Data (2026-10), reducida.
REELS = [
    {"url": "https://www.instagram.com/p/A/", "user_posted": "andresbilbao", "coauthor_producers": ["crece30x"],
     "tagged_users": [{"username": "andresbilbao", "full_name": "andresbilbao", "is_verified": True}]},
    {"url": "https://www.instagram.com/p/B/", "user_posted": "dylanrosemberg", "coauthor_producers": ["dylanrosemberg", "crece30x", "dbilbaoc"],
     "tagged_users": [{"username": "dylanrosemberg"}, {"username": "dbilbaoc"}, {"username": "crece30x"}]},
    {"url": "https://www.instagram.com/p/C/", "user_posted": "andresbilbao", "coauthor_producers": ["crece30x"], "tagged_users": []},
    {"url": "https://www.instagram.com/p/D/", "error": "dead_page"},
]
PROFILE = {"account": "andresbilbao", "full_name": "Andrés Bilbao", "biography": "Cofundador de Rappi y 30X", "followers": 1021224,
           "following": 500, "posts_count": 900, "is_verified": True, "is_private": False, "business_category_name": "Empresario",
           "external_url": ["https://30x.com"], "profile_image_link": "https://cdn.example.com/andres.jpg"}


def test_extract_relations_excludes_brand_and_ranks_by_presence():
    relations = extract_relations(REELS, "crece30x")
    # Primero quien aparece en más reels; luego quien tiene más tipos de relación.
    assert list(relations) == ["andresbilbao", "dylanrosemberg", "dbilbaoc"]
    assert relations["andresbilbao"] == {"relations": ["tagged", "posted"], "reel_urls": ["https://www.instagram.com/p/A/", "https://www.instagram.com/p/C/"]}
    assert relations["dylanrosemberg"]["relations"] == ["coauthor", "tagged", "posted"]
    assert "crece30x" not in relations
    many = [{"url": f"https://www.instagram.com/p/{i}/", "user_posted": f"user{i}"} for i in range(MAX_ACCOUNTS + 5)]
    assert len(extract_relations(many, "crece30x")) == MAX_ACCOUNTS
    assert extract_relations("no es una lista", "crece30x") == {}


def test_profile_fields_and_username():
    assert profile_username(PROFILE) == "andresbilbao"
    assert profile_username({"input": {"url": "https://www.instagram.com/DBilbaoC/"}}) == "dbilbaoc"
    fields = account_fields(PROFILE)
    assert fields == {"full_name": "Andrés Bilbao", "biography": "Cofundador de Rappi y 30X", "followers": 1021224, "following": 500,
                      "posts_count": 900, "is_verified": True, "is_private": False, "category": "Empresario", "external_urls": ["https://30x.com"]}
    assert account_fields({"external_url": "https://a.com", "followers": "1.2K"})["external_urls"] == ["https://a.com"]
    assert account_fields({"followers": "1.2K"})["followers"] is None


class FakeBrightData:
    """Simula los dos trabajos de Bright Data y el CDN de las fotos."""

    def __init__(self):
        self.triggers, self.ready = [], set()

    def __call__(self, request: httpx.Request):
        path = request.url.path
        if request.url.host == "cdn.example.com":
            return httpx.Response(200, content=b"JPEGDATA", headers={"content-type": "image/jpeg"})
        if path.endswith("/trigger"):
            self.triggers.append((dict(request.url.params), json.loads(request.content)))
            return httpx.Response(200, json={"snapshot_id": f"sd_{len(self.triggers)}"})
        if "/progress/" in path:
            snapshot = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"status": "ready" if snapshot in self.ready else "running"})
        if "/snapshot/" in path:
            return httpx.Response(200, json=REELS if path.endswith("sd_1") else [PROFILE, {"input": {"url": "https://www.instagram.com/dbilbaoc"}, "error": "not_found"}])
        return httpx.Response(404)


@pytest.fixture
def bright(client, monkeypatch):
    brand = client.post("/api/brands", json={"name": "30X", "brand_accounts_confirmed": True,
                                             "profiles": [{"platform": "instagram", "url": "https://www.instagram.com/crece30x"}]}).json()
    fake = FakeBrightData()

    async def override():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
            yield http
    app.dependency_overrides[get_bright_data_client] = override
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "test-key")
    monkeypatch.setenv("BRIGHT_DATA_INSTAGRAM_DATASET_ID", "gd_profiles")
    return brand["id"], fake


def test_full_flow_reels_then_profiles_then_avatar(client, bright):
    brand_id, fake = bright
    assert client.get(f"/api/brands/{brand_id}/related-accounts").json()["state"] == "not_started"

    first = client.post(f"/api/brands/{brand_id}/related-accounts").json()
    assert first["state"] == "reels_pending" and first["brand_account"] == "crece30x"
    params, body = fake.triggers[0]
    assert params["dataset_id"] == "gd_lyclm20il4r5helnj" and params["type"] == "discover_new" and params["limit_per_input"] == "5"
    assert body == [{"url": "https://www.instagram.com/crece30x", "num_of_posts": 5}]

    # Consultar mientras Bright Data trabaja no inicia otro trabajo.
    assert client.post(f"/api/brands/{brand_id}/related-accounts").json()["state"] == "reels_pending"
    assert client.get(f"/api/brands/{brand_id}/related-accounts").json()["state"] == "reels_pending"
    assert len(fake.triggers) == 1

    fake.ready.add("sd_1")
    second = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    assert second["state"] == "profiles_pending" and len(fake.triggers) == 2
    params, body = fake.triggers[1]
    assert params["dataset_id"] == "gd_profiles" and "type" not in params
    assert body == [{"url": "https://www.instagram.com/andresbilbao"}, {"url": "https://www.instagram.com/dylanrosemberg"}, {"url": "https://www.instagram.com/dbilbaoc"}]

    fake.ready.add("sd_2")
    done = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    assert done["state"] == "ready" and "3 cuentas relacionadas; 1 con ficha" in done["message"]
    andres, *others = done["accounts"]
    assert andres["username"] == "andresbilbao" and andres["followers"] == 1021224 and andres["profile_available"]
    assert andres["relations"] == ["tagged", "posted"] and len(andres["reel_urls"]) == 2
    assert andres["avatar_url"] == f"/api/brands/{brand_id}/related-accounts/andresbilbao/avatar"
    assert {a["username"] for a in others} == {"dbilbaoc", "dylanrosemberg"}
    assert all(not a["profile_available"] and a["avatar_url"] is None and a["followers"] is None for a in others)

    avatar = client.get(andres["avatar_url"])
    assert avatar.status_code == 200 and avatar.content == b"JPEGDATA" and avatar.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/brands/{brand_id}/related-accounts/dbilbaoc/avatar").status_code == 404
    assert len(fake.triggers) == 2


def test_requires_configuration_and_instagram_profile(client, monkeypatch):
    demo = client.post("/api/demo").json()["brand"]["id"]
    assert client.post(f"/api/brands/{demo}/related-accounts").status_code == 503
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHT_DATA_INSTAGRAM_DATASET_ID", "gd_profiles")
    response = client.post(f"/api/brands/{demo}/related-accounts")
    assert response.status_code == 400 and "Instagram" in response.json()["detail"]
    assert client.post("/api/brands/missing/related-accounts").status_code == 404


def test_rejected_start_is_not_resubmitted(client, bright):
    brand_id, fake = bright
    calls = []

    def unauthorized(request):
        calls.append(request.url.path)
        return httpx.Response(401)

    async def override():
        async with httpx.AsyncClient(transport=httpx.MockTransport(unauthorized)) as http:
            yield http
    app.dependency_overrides[get_bright_data_client] = override
    failed = client.post(f"/api/brands/{brand_id}/related-accounts").json()
    assert failed["state"] == "failed" and "credenciales" in failed["message"]
    assert client.get(f"/api/brands/{brand_id}/related-accounts").json()["state"] == "failed"
    assert len(calls) == 1


def test_stale_pending_job_times_out(client, bright):
    brand_id, fake = bright
    client.post(f"/api/brands/{brand_id}/related-accounts")
    session = next(app.dependency_overrides[get_session]())
    run = session.get(RelatedAccountRun, brand_id)
    run.updated_at = run.updated_at - timedelta(hours=2)
    session.commit()
    stale = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    assert stale["state"] == "failed" and "excedió el tiempo" in stale["message"]
    assert len(fake.triggers) == 1


def test_late_poll_still_collects_a_finished_job(client, bright):
    # Caso real: Bright Data terminó en ~4 min pero nadie consultó hasta 28 min después.
    brand_id, fake = bright
    client.post(f"/api/brands/{brand_id}/related-accounts")
    session = next(app.dependency_overrides[get_session]())
    run = session.get(RelatedAccountRun, brand_id)
    run.updated_at = run.updated_at - timedelta(minutes=28)
    session.commit()
    fake.ready.add("sd_1")
    late = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    assert late["state"] == "profiles_pending" and len(fake.triggers) == 2
