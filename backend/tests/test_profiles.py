"""Provider responses are synthetic fixtures, never presented as live validation."""
import asyncio
import json

import httpx
import pytest

from app import main
from app.profiles import build_analysis, connector_status
from app.schemas import BrandCreate
from app.services import relevance


@pytest.fixture(autouse=True)
def clean_credentials(monkeypatch):
    for key in ("YOUTUBE_API_KEY", "YOUTUBE_ANALYTICS_APPROVED", "META_ACCESS_TOKEN", "META_IG_USER_ID", "META_GRAPH_VERSION"):
        monkeypatch.delenv(key, raising=False)


def brief(platform="youtube", url="https://www.youtube.com/@marcaQA"):
    return BrandCreate(name="Marca QA sintética", profiles=[{"platform": platform, "url": url}], brand_accounts_confirmed=True)


def yt_fixture(request):
    assert request.url.host == "www.googleapis.com"  # No user-supplied host is ever fetched.
    assert request.url.params["key"] == "fixture-secret"
    if request.url.path.endswith("/channels"):
        assert request.url.params["forHandle"] == "@marcaQA"
        return httpx.Response(200, json={"items": [{"id": "UC"+"a"*22, "snippet": {"title": "Marca QA", "description": "Agentes de IA y automatización para empresas. Contacto test@example.org +57 300 123 4567"}, "statistics": {"viewCount": "12345", "subscriberCount": "100", "videoCount": "9"}, "contentDetails": {"relatedPlaylists": {"uploads": "UUfixture"}}}]})
    if request.url.path.endswith("/playlistItems"):
        return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "abcdefghijk"}}, {"contentDetails": {"videoId": "lmnopqrstuv"}}]})
    if request.url.path.endswith("/videos"):
        return httpx.Response(200, json={"items": [
            {"id": "abcdefghijk", "snippet": {"title": "Un agente de IA", "description": "Caso de productividad y software", "publishedAt": "2026-10-01T12:00:00Z"}, "statistics": {"viewCount": "500"}, "status": {"privacyStatus": "public"}},
            {"id": "lmnopqrstuv", "snippet": {"title": "Private video"}, "status": {"privacyStatus": "private"}},
        ]})
    raise AssertionError("Unexpected provider route")


def run_analysis(value, handler):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await build_analysis(value, client=c)
    return asyncio.run(execute())


def test_missing_credentials_are_actionable_and_never_fabricate_metrics(client):
    response = client.post("/api/brands", json=brief().model_dump(mode="json"))
    assert response.status_code == 201
    data = response.json()
    analysis = data["profile_analysis"]
    assert analysis["status"] == "unavailable"
    p = analysis["profiles"][0]
    assert p["status"] == "requires_configuration"
    assert "YOUTUBE_API_KEY" in p["message"]
    assert p["metrics"] == {"views": None, "followers": None, "posts": None}
    assert data["identity"]["audience"] == "Audiencia por confirmar"
    assert data["identity"]["topics"] == ["por definir"]
    assert client.get(f"/api/brands/{data['id']}").json()["profile_analysis"]["profiles"] == analysis["profiles"]


def test_youtube_metadata_recent_public_videos_and_identity_enrichment(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    monkeypatch.setenv("YOUTUBE_ANALYTICS_APPROVED", "true")
    data = run_analysis(brief(), yt_fixture)
    p = data["profiles"][0]
    assert data["status"] == "complete"
    assert p["metrics"]["views"] == 12345
    assert p["metrics"]["followers"] == 100
    assert len(p["content_sample"]) == 1
    assert p["content_sample"][0]["views"] == 500
    assert p["content_sample"][0]["url"] == "https://youtu.be/abcdefghijk"
    assert data["suggested_identity"]["method"] == "profile_rules"
    assert "agentes de ia" in data["suggested_identity"]["topics"]
    assert relevance("automatización", data["suggested_identity"]) == 100
    encoded = json.dumps(data)
    assert "fixture-secret" not in encoded
    assert "test@example.org" not in encoded
    assert "300 123 4567" not in encoded
    assert data["identity_evidence"] == [brief().profiles[0].url]


def test_youtube_without_analytics_permission_does_not_feed_identity(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    data = run_analysis(brief(), yt_fixture)
    assert data["profiles"][0]["status"] == "ready"
    assert data["profiles"][0]["metrics"]["views"] == 12345
    assert data["profiles"][0]["usable_for_identity"] is False
    assert data["identity_evidence"] == []
    assert data["suggested_identity"]["topics"] == ["por definir"]


def test_instagram_public_biography_and_null_views(monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "fixture-meta-secret")
    monkeypatch.setenv("META_IG_USER_ID", "123456")
    monkeypatch.setenv("META_GRAPH_VERSION", "v99.0")
    def handler(request):
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == "/v99.0/123456"
        assert "business_discovery.username(marca.qa)" in request.url.params["fields"]
        assert request.headers["Authorization"] == "Bearer fixture-meta-secret"
        return httpx.Response(200, json={"business_discovery": {"biography": "Automatización y educación para empresas", "followers_count": 250, "media_count": 12, "media": {"data": [{"caption": "Un agente para tu empresa", "media_type": "CAROUSEL_ALBUM", "permalink": "https://www.instagram.com/p/fixture/", "timestamp": "2026-10-01T10:00:00+0000"}]}}})
    data = run_analysis(brief("instagram", "https://www.instagram.com/marca.qa"), handler)
    p = data["profiles"][0]
    assert p["status"] == "ready"
    assert p["metrics"] == {"views": None, "followers": 250, "posts": 12}
    assert p["content_sample"][0]["format"] == "carousel"
    assert p["content_sample"][0]["views"] is None
    assert "fixture-meta-secret" not in json.dumps(data)
    assert "automatización" in data["suggested_identity"]["topics"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_errors_are_sanitized(monkeypatch, status):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    data = run_analysis(brief(), lambda request: httpx.Response(status, json={"error": "fixture-secret"}))
    assert data["profiles"][0]["status"] == "error"
    assert "fixture-secret" not in json.dumps(data)


def test_hidden_counts_and_recent_video_failure_preserve_profile(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    def handler(request):
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"snippet": {"description": "Una empresa de software"}, "statistics": {"hiddenSubscriberCount": True, "subscriberCount": "100"}, "contentDetails": {"relatedPlaylists": {"uploads": "UUfixture"}}}]})
        raise httpx.ReadTimeout("private error containing fixture-secret", request=request)
    data = run_analysis(brief(), handler)
    assert data["profiles"][0]["status"] == "ready"
    assert data["profiles"][0]["metrics"]["followers"] is None
    assert data["profiles"][0]["metrics"]["views"] is None
    assert data["profiles"][0]["content_sample"] == []
    assert "fixture-secret" not in json.dumps(data)


def test_confirmed_identity_is_preserved_and_cache_is_used(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    monkeypatch.setenv("YOUTUBE_ANALYTICS_APPROVED", "true")
    calls = []
    async def fake(brief):
        calls.append(True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(yt_fixture)) as c:
            return await build_analysis(brief, client=c)
    monkeypatch.setattr(main, "build_analysis", fake)
    data = client.post("/api/brands", json=brief().model_dump(mode="json")).json()
    url = f"/api/brands/{data['id']}"
    confirmed = data["identity"] | {"summary": "Texto revisado y confirmado por el equipo.", "status": "confirmed"}
    assert client.put(url+"/identity", json=confirmed).status_code == 200
    refreshed = client.post(url+"/profiles/analyze", json={}).json()
    assert len(calls) == 1
    assert refreshed["identity"]["summary"] == confirmed["summary"]
    assert refreshed["identity"]["status"] == "confirmed"
    applied = client.post(url+"/profiles/analyze", json={"apply_to_identity": True}).json()
    assert applied["identity"]["status"] == "draft"
    assert applied["identity"]["method"] == "profile_rules"
    assert len(calls) == 1
    assert client.post(url+"/profiles/analyze", json={"force": True}).status_code == 200
    assert len(calls) == 2


def test_configuration_only_returns_key_names_not_credentials(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    data = client.get("/api/profile-connectors").json()
    assert next(c for c in data if c["platform"] == "youtube")["configured"] is True
    assert "fixture-secret" not in json.dumps(data)
    assert "META_ACCESS_TOKEN" in next(c for c in data if c["platform"] == "instagram")["missing"]


@pytest.mark.parametrize("payload", [
    {"name": "QA", "profiles": [{"platform": "youtube", "url": "https://www.youtube.com/@marcaQA"}]},
    {"name": "QA", "description": "abc"},
    {"name": "QA", "description": "Una descripción válida de la empresa", "audience": "ab"},
    {"name": "QA", "brand_accounts_confirmed": True, "profiles": [{"platform": "youtube", "url": "https://youtube.com.evil.test/@marcaQA"}]},
])
def test_incomplete_context_or_nonpublic_profile_is_rejected(client, payload):
    assert client.post("/api/brands", json=payload).status_code == 422


def test_multiple_networks_partial_success_and_unsupported_profile_paths(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-secret")
    value = brief()
    from app.schemas import SocialProfile
    value.profiles.extend([SocialProfile(platform="instagram", url="https://instagram.com/marcaQA"), SocialProfile(platform="linkedin", url="https://linkedin.com/company/marcaQA")])
    data = run_analysis(value, yt_fixture)
    assert data["status"] == "partial"
    assert [p["status"] for p in data["profiles"]] == ["ready", "requires_configuration", "unsupported"]
    invalid_path = brief("instagram", "https://instagram.com/p/not-a-profile")
    result = run_analysis(invalid_path, lambda request: pytest.fail("Must not request invalid profile paths"))
    assert result["profiles"][0]["status"] == "unsupported"
