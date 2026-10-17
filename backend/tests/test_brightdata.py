"""Synthetic HTTP fixtures only. Never submit a real paid collection in tests."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import main
from app.brightdata import canonical_profile
from app.collection_jobs import DBJobStore, MemoryJobStore
from app.database import Base, Brand
from app.profiles import build_analysis
from app.schemas import BrandCreate


def brief(platform="instagram"):
    return BrandCreate(name="Marca QA sintética", brand_accounts_confirmed=True,
                       profiles=[{"platform": platform, "url": f"https://www.{platform}.com/" + ("marca.qa" if platform == "instagram" else "@marcaQA")}])


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fixture-bright-secret")
    monkeypatch.setenv("BRIGHT_DATA_INSTAGRAM_DATASET_ID", "gd_fixtureIG")
    monkeypatch.setenv("BRIGHT_DATA_YOUTUBE_DATASET_ID", "gd_fixtureYT")


class Vendor:
    def __init__(self, platform="instagram", rows=None):
        self.platform = platform
        self.posts = 0
        self.requests = []
        self.progress = "ready"
        self.rows = rows if rows is not None else ([{
            "url": "https://www.instagram.com/marca.qa/", "is_private": False,
            "biography": "Agentes de IA y automatización para empresas test@example.org +57 300 123 4567",
            "followers": 250, "posts_count": 12,
            "email_address": "secret@example.org", "full_name": "PERSONAL_FIELD",
            "posts": [{"url": "https://www.instagram.com/p/fixture/", "caption": "Automatizar negocios", "media_type": "VIDEO", "views": 123,
                       "comments": ["PERSONAL_FIELD"], "author": "PERSONAL_FIELD"}],
        }] if platform == "instagram" else [{
            "url": "https://www.youtube.com/@marcaQA/about", "name": "Marca de prueba",
            "Description": "Agentes de IA para empresas", "subscribers": "100", "videos_count": 9, "views": "12345",
            "top_videos": [{"url": "https://youtu.be/abcdefghijk", "title": "Un agente", "views": "500"}],
        }])

    def __call__(self, request):
        self.requests.append(request)
        assert request.url.host == "api.brightdata.com", "Primary success must not call official APIs"
        assert request.headers["Authorization"] == "Bearer fixture-bright-secret"
        if request.method == "POST":
            self.posts += 1
            body = json.loads(request.content)
            assert body["limit_per_input"] == 1
            assert set(body) == {"input", "limit_per_input"}  # No cookies, session or login.
            assert len(body["input"]) == 1
            assert request.url.params["include_errors"] == "true"
            fields = request.url.params["custom_output_fields"]
            assert "email_address" not in fields and "full_name" not in fields
            return httpx.Response(200, json={"snapshot_id": f"sd_fixture{self.posts}"})
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": self.progress})
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json=self.rows)


def analyze(value, handler, store, refresh=False):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await build_analysis(value, client=client, job_store=store, refresh_bright_data=refresh)
    return asyncio.run(execute())


@pytest.mark.parametrize("platform", ["instagram", "youtube"])
def test_primary_pending_ready_reuse_and_explicit_new_job(configured, platform):
    vendor, store, value = Vendor(platform), MemoryJobStore(), brief(platform)
    first = analyze(value, vendor, store)
    assert first["status"] == "pending"
    assert first["profiles"][0]["metrics"]["views"] is None
    vendor.progress = "running"
    assert analyze(value, vendor, store, refresh=True)["status"] == "pending"
    assert vendor.posts == 1  # Even explicit refresh cannot duplicate active work.
    vendor.progress = "ready"
    done = analyze(value, vendor, store)
    p = done["profiles"][0]
    assert p["status"] == "ready" and p["provider"] == "bright_data"
    assert not p["fallback_used"] and len(p["attempts"]) == 1
    assert p["metrics"]["views"] == (None if platform == "instagram" else 12345)
    assert p["metrics"]["followers"] == (250 if platform == "instagram" else 100)
    assert p["content_sample"][0]["views"] == (123 if platform == "instagram" else 500)
    assert "agentes de ia" in done["suggested_identity"]["topics"]
    calls = len(vendor.requests)
    assert analyze(value, vendor, store)["profiles"][0]["observed_at"] == p["observed_at"]
    assert len(vendor.requests) == calls  # Stored observation, not falsely refreshed.
    encoded = json.dumps(done) + json.dumps(next(iter(store.jobs.values()))["result"])
    assert all(s not in encoded for s in ["fixture-bright-secret", "test@example.org", "secret@example.org", "300 123 4567", "PERSONAL_FIELD"])
    assert analyze(value, vendor, store, refresh=True)["status"] == "pending"
    assert vendor.posts == 2


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
def test_primary_failure_uses_youtube_fallback_without_resubmitting(configured, monkeypatch, status):
    monkeypatch.setenv("YOUTUBE_API_KEY", "fixture-google-secret")
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "api.brightdata.com":
            return httpx.Response(status, json={"error": "fixture-bright-secret"})
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(200, json={"items": [{"snippet": {"description": "Empresa de prueba"}, "statistics": {"viewCount": "42"}}]})
    store = MemoryJobStore()
    for _ in range(2):
        p = analyze(brief("youtube"), handler, store)["profiles"][0]
        assert p["fallback_used"] and p["provider"] == "youtube_data_api"
        assert len(p["attempts"]) == 2 and p["metrics"]["views"] == 42
        assert "fixture-bright-secret" not in json.dumps(p)
    assert sum(r.method == "POST" for r in calls) == 1


def test_unconfigured_primary_uses_meta(monkeypatch):
    for key, value in {"META_ACCESS_TOKEN": "fixture-meta", "META_IG_USER_ID": "123", "META_GRAPH_VERSION": "v99.0"}.items():
        monkeypatch.setenv(key, value)
    def handler(request):
        assert request.url.host == "graph.facebook.com"
        return httpx.Response(200, json={"business_discovery": {"biography": "Empresa de prueba", "followers_count": 50}})
    p = analyze(brief(), handler, MemoryJobStore())["profiles"][0]
    assert p["provider"] == "meta_business_discovery" and p["fallback_used"]
    assert p["attempts"][0]["code"] == "not_configured"


def test_ambiguous_timeout_is_not_automatically_resubmitted(configured):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("contains fixture-bright-secret", request=request)
    store = MemoryJobStore()
    for _ in range(3):
        p = analyze(brief(), handler, store)["profiles"][0]
        assert p["collection"]["state"] == "unknown"
        assert "fixture-bright-secret" not in json.dumps(p)
    assert len(calls) == 1


@pytest.mark.parametrize("rows", [
    [{"url": "https://instagram.com/marca.qa", "is_private": True}],
    [{"error_code": "login_required", "error": "private upstream text"}],
])
def test_restricted_content_never_uses_fallback_even_on_resume(configured, monkeypatch, rows):
    monkeypatch.setenv("META_ACCESS_TOKEN", "fixture-meta")
    monkeypatch.setenv("META_IG_USER_ID", "123")
    monkeypatch.setenv("META_GRAPH_VERSION", "v99.0")
    vendor, store = Vendor(rows=rows), MemoryJobStore()
    analyze(brief(), vendor, store)
    for _ in range(2):
        p = analyze(brief(), vendor, store)["profiles"][0]
        assert p["provider"] == "bright_data" and p["status"] == "error"
        assert p["collection"]["state"] == "restricted" and len(p["attempts"]) == 1
    assert vendor.posts == 1


@pytest.mark.parametrize("rows", [[], {}, [{}], [{"url": "https://instagram.com/another", "is_private": False}],
    [{"url": "https://instagram.com/marca.qa", "biography": "Not verified public"}]])
def test_unverifiable_rows_are_discarded(configured, rows):
    vendor, store = Vendor(rows=rows), MemoryJobStore()
    analyze(brief(), vendor, store)
    p = analyze(brief(), vendor, store)["profiles"][0]
    assert p["status"] == "requires_configuration"  # Official fallback is not configured.
    assert p["collection"]["state"] == "failed"
    assert not p["description"] and p["metrics"]["followers"] is None


def test_budget_and_expired_job_do_not_submit_extra_posts(configured, monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_MAX_NEW_JOBS_PER_ANALYSIS", "1")
    value = brief()
    value.profiles.extend(brief("youtube").profiles)
    vendor, store = Vendor(), MemoryJobStore()
    first = analyze(value, vendor, store)
    assert vendor.posts == 1
    assert first["profiles"][1]["attempts"][0]["code"] == "local_limit"
    job = next(iter(store.jobs.values()))
    store.save(job, created_at=datetime.now(timezone.utc) - timedelta(hours=2))
    p = analyze(brief(), vendor, store)["profiles"][0]
    assert p["collection"]["state"] == "failed" and vendor.posts == 1


def test_null_metrics_are_not_guessed(configured):
    vendor = Vendor(rows=[{"url": "https://instagram.com/marca.qa", "is_private": False,
                           "biography": "Empresa de prueba", "followers": "1.2K", "posts_count": -1}])
    store = MemoryJobStore()
    analyze(brief(), vendor, store)
    assert analyze(brief(), vendor, store)["profiles"][0]["metrics"] == {"views": None, "followers": None, "posts": None}


def test_durable_job_claims_and_old_generation_cannot_overwrite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Brand(id="qa", brief={}, identity={}))
        session.commit()
        one = DBJobStore(session, "qa")
        job, claimed = one.claim("key")
        assert claimed
        one.save(job, state="pending", snapshot_id="sd_existing")
    with Session(engine) as session:
        two = DBJobStore(session, "qa")
        resumed, claimed = two.claim("key", refresh=True)
        assert not claimed and resumed["snapshot_id"] == "sd_existing"
        two.save(resumed, state="failed")
        newer, claimed = two.claim("key", refresh=True)
        assert claimed and newer["generation"] != job["generation"]
        assert two.save(job, state="ready", result={"old": True})["state"] == "requesting"
    engine.dispose()


@pytest.mark.parametrize("confirm", [False, True])
def test_api_persists_pending_and_only_enriches_unedited_draft(client, monkeypatch, configured, confirm):
    vendor = Vendor()
    async def fake(value, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(vendor)) as transport:
            return await build_analysis(value, client=transport, **kwargs)
    monkeypatch.setattr(main, "build_analysis", fake)
    data = client.post("/api/brands", json=brief().model_dump(mode="json")).json()
    assert data["profile_analysis"]["status"] == "pending"
    path = f"/api/brands/{data['id']}"
    if confirm:
        identity = data["identity"] | {"status": "confirmed", "summary": "Identidad validada por el equipo."}
        client.put(path + "/identity", json=identity)
    done = client.post(path + "/profiles/analyze", json={}).json()
    assert done["profile_analysis"]["status"] == "complete" and vendor.posts == 1
    assert done["identity"]["method"] == ("human_review" if confirm else "profile_rules")
    assert "auto_apply_digest" not in done["profile_analysis"]
    # A forced analysis and a fresh request Session reuse the durable normalized result.
    again = client.post(path + "/profiles/analyze", json={"force": True}).json()
    assert vendor.posts == 1 and again["profile_analysis"]["profiles"][0]["provider"] == "bright_data"


def test_configuration_exposes_both_routes_without_secrets(client, configured):
    data = client.get("/api/profile-connectors").json()
    ig = next(c for c in data if c["platform"] == "instagram")
    assert ig["configured"] and ig["primary"]["configured"]
    assert not ig["fallback"]["configured"] and "META_ACCESS_TOKEN" in ig["fallback"]["missing"]
    assert "fixture-bright-secret" not in json.dumps(data)


def test_automatic_poll_does_not_start_profiles_deferred_by_budget(client, configured, monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_MAX_NEW_JOBS_PER_ANALYSIS", "1")
    vendor = Vendor()
    vendor.progress = "running"
    async def fake(value, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(vendor)) as transport:
            return await build_analysis(value, client=transport, **kwargs)
    monkeypatch.setattr(main, "build_analysis", fake)
    value = brief()
    value.profiles.extend(brief("youtube").profiles)
    data = client.post("/api/brands", json=value.model_dump(mode="json")).json()
    assert data["profile_analysis"]["status"] == "pending" and vendor.posts == 1
    path = f"/api/brands/{data['id']}/profiles/analyze"
    for _ in range(2):
        assert client.post(path, json={}).json()["profile_analysis"]["status"] == "pending"
    assert vendor.posts == 1


def test_failed_progress_uses_fallback_without_download_or_new_post(configured):
    vendor, store = Vendor(), MemoryJobStore()
    analyze(brief(), vendor, store)
    vendor.progress = "failed"
    p = analyze(brief(), vendor, store)["profiles"][0]
    assert p["collection"]["state"] == "failed" and len(p["attempts"]) == 2
    assert len(vendor.requests) == 2 and vendor.posts == 1


def test_sample_urls_keep_only_public_content_identifiers(configured):
    vendor, store = Vendor("youtube"), MemoryJobStore()
    vendor.rows[0]["top_videos"] = [
        {"url": "https://youtube.com/watch?v=abcdefghijk&tracking=PERSONAL_FIELD#PERSONAL_FIELD", "title": "Contenido público"},
        {"url": "https://youtube.com/@personal", "title": "Otro perfil"},
        {"url": "https://evil.test/abcdefghijk", "title": "Destino externo"},
    ]
    analyze(brief("youtube"), vendor, store)
    p = analyze(brief("youtube"), vendor, store)["profiles"][0]
    assert len(p["content_sample"]) == 1
    assert p["content_sample"][0]["url"] == "https://youtu.be/abcdefghijk"
    assert "PERSONAL_FIELD" not in json.dumps(p)


@pytest.mark.parametrize("url", ["https://instagram.com/accounts/login", "https://instagram.com/p/123", "https://instagram.com.evil.test/marca.qa"])
def test_invalid_profile_never_reaches_vendor(url):
    from app.profile_common import ProviderError
    with pytest.raises(ProviderError):
        canonical_profile(url, "instagram")
