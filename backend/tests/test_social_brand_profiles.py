import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app import main
from app.brightdata import canonical_profile
from app.collection_jobs import DBJobStore, MemoryJobStore
from app.database import TikTokAccount, get_session
from app.profiles import build_analysis, inspect_one
from app.schemas import BrandCreate
from tests.test_brightdata import Vendor, analyze


@pytest.mark.parametrize("platform,path,record", [
    ("tiktok", "@marca.qa", {"nickname": "Marca QA", "signature": "Formación para equipos de IA", "followers": 5000, "videos_count": 40, "is_private": False, "likes": 900000}),
    ("linkedin", "company/marca-qa", {"name": "Marca QA", "about": "Formación para equipos de IA", "followers": 1500, "employees": ["PERSONAL_FIELD"], "employee_contacts": "PRIVATE_FIELD"}),
])
def test_new_connectors_use_published_datasets_and_public_aggregate_fields(monkeypatch, platform, path, record):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fixture-bright-secret")
    url = f"https://www.{platform}.com/{path}"
    value = BrandCreate(name="Marca QA", brand_accounts_confirmed=True, profiles=[{"platform": platform, "url": url}])
    vendor, store = Vendor(platform, rows=[{**record, "url": url}]), MemoryJobStore()
    assert analyze(value, vendor, store)["status"] == "pending"
    result = analyze(value, vendor, store)
    profile = result["profiles"][0]
    assert profile["status"] == "ready" and profile["metrics"]["followers"] == record["followers"]
    assert profile["metrics"]["views"] is None and profile["description"] == record.get("signature", record.get("about"))
    assert vendor.posts == 1
    assert "PERSONAL_FIELD" not in json.dumps(result) and "PRIVATE_FIELD" not in json.dumps(result)
    assert "employees" not in vendor.requests[0].url.params["custom_output_fields"]
    assert analyze(value, vendor, store)["profiles"][0]["status"] == "ready" and vendor.posts == 1


@pytest.mark.parametrize("private", [True, None])
def test_tiktok_requires_explicit_public_confirmation(monkeypatch, private):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fixture-bright-secret")
    value = BrandCreate(name="Marca QA", brand_accounts_confirmed=True, profiles=[{"platform": "tiktok", "url": "https://www.tiktok.com/@marca.qa"}])
    vendor = Vendor("tiktok", rows=[{"url": value.profiles[0].url, "signature": "No usar", "is_private": private}])
    store = MemoryJobStore()
    analyze(value, vendor, store)
    result = analyze(value, vendor, store)
    assert result["profiles"][0]["status"] != "ready" and not result["profiles"][0]["usable_for_identity"]
    assert len([r for r in vendor.requests if r.method == "POST"]) == 1


def test_linkedin_personal_profiles_are_never_requested():
    from app.profile_common import ProviderError
    with pytest.raises(ProviderError):
        canonical_profile("https://www.linkedin.com/in/persona", "linkedin")
    assert canonical_profile("https://linkedin.com/company/Marca-QA/about/", "linkedin") == "https://www.linkedin.com/company/marca-qa"


def test_ready_progress_with_snapshot_still_building_is_resumable(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "fixture-bright-secret")
    url = "https://www.tiktok.com/@marca.qa"
    value = BrandCreate(name="Marca QA", brand_accounts_confirmed=True, profiles=[{"platform": "tiktok", "url": url}])
    vendor = Vendor("tiktok", rows=[{"url": url, "biography": "IA para empresas", "is_private": False}])
    store = MemoryJobStore()
    def building(request):
        if "/snapshot/" in request.url.path:
            return httpx.Response(202, json={"status": "building"})
        return vendor(request)
    assert analyze(value, building, store)["status"] == "pending"
    assert analyze(value, building, store)["status"] == "pending"
    assert analyze(value, vendor, store)["profiles"][0]["status"] == "ready" and vendor.posts == 1


def test_step_one_reuses_fresh_public_tiktok_profile_from_step_two(client):
    bid = client.post("/api/demo").json()["brand"]["id"]
    db = next(main.app.dependency_overrides[get_session]())
    raw = {"url": "https://www.tiktok.com/@marca.qa", "nickname": "Marca QA", "biography": "IA aplicada en equipos", "followers": 5500, "is_private": False, "videos_count": 12}
    db.add(TikTokAccount(username="marca.qa", raw=raw, is_private=False, fetch_status="ok", fetched_at=datetime.now(timezone.utc)))
    db.commit()
    value = BrandCreate(name="Marca QA", brand_accounts_confirmed=True, profiles=[{"platform": "tiktok", "url": raw["url"]}])
    def forbidden(request):
        pytest.fail("A fresh public profile must be reused without a remote request")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
            return await inspect_one(value.profiles[0], http, store=DBJobStore(db, bid))
    result = asyncio.run(run())
    assert result.status == "ready" and result.metrics.followers == 5500 and result.collection is None
    assert "caché" in result.message
