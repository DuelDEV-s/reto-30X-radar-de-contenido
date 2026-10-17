from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest
from app.demo import demo_batch, demo_brief
from app.schemas import BatchCreate
from app.services import analyze, draft_identity


def test_end_to_end_identity_ingest_report_and_dedup(client):
    response = client.post("/api/brands", json=demo_brief().model_dump(mode="json"))
    assert response.status_code == 201
    brand = response.json()
    assert brand["identity"]["status"] == "draft"
    brand_id = brand["id"]
    identity = brand["identity"] | {"status": "confirmed"}
    assert client.put(f"/api/brands/{brand_id}/identity", json=identity).status_code == 200
    batch = demo_batch().model_dump(mode="json")
    batch["mode"] = "public"
    for post in batch["posts"]:
        post["source_method"] = "manual_public"
    url = f"/api/brands/{brand_id}/trend-batches"
    first = client.post(url, json=batch)
    assert first.status_code == 201
    second = client.post(url, json=batch)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["deduplicated"] is True
    assert len(client.get(url).json()) == 1
    result = client.get(f"/api/brands/{brand_id}/report").json()
    assert result["mode"] == "public"
    assert result["identity_status"] == "confirmed"
    assert result["topics"][0]["topic"] == "agentes de ia"
    assert result["topics"][0]["acceleration_pct"] == 210.0
    assert result["topics"][0]["score"] == 100
    filtered = client.get(f"/api/brands/{brand_id}/report?platform=tiktok").json()
    assert filtered["topics"] == []
    assert client.get(f"/api/brands/{brand_id}/report?limit=0").status_code == 422


def test_demo_never_selected_implicitly_and_batches_are_brand_scoped(client):
    demo = client.post("/api/demo").json()
    brand_id = demo["brand"]["id"]
    assert client.get(f"/api/brands/{brand_id}/report").status_code == 404
    assert client.get(f"/api/brands/{brand_id}/report?batch_id={demo['batch_id']}").json()["mode"] == "demo"
    other = client.post("/api/brands", json=demo_brief().model_dump(mode="json")).json()
    assert client.get(f"/api/brands/{other['id']}/report?batch_id={demo['batch_id']}").status_code == 404


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(compliance_confirmed=False),
    lambda b: b["posts"][0].update(url="https://127.0.0.1/private"),
    lambda b: b["posts"][0].update(url="https://linkedin.com.evil.test/post"),
    lambda b: b["posts"][0].update(url="https://www.linkedin.com/post?token=secret"),
    lambda b: b["posts"][0].update(author_email="personal@example.com"),
    lambda b: b["posts"][0]["snapshots"][1].update(views=0),
    lambda b: b["posts"][0]["snapshots"][1].update(observed_at="2099-01-01T00:00:00Z"),
    lambda b: b["posts"][0]["snapshots"][1].update(observed_at="2020-01-01T00:00:00"),
    lambda b: b["posts"].append(deepcopy(b["posts"][0])),
    lambda b: b.update(mode="public"),
])
def test_ingest_rejects_invalid_or_noncompliant_input(client, mutate):
    demo = client.post("/api/demo").json()
    batch = demo_batch().model_dump(mode="json")
    mutate(batch)
    assert client.post(f"/api/brands/{demo['brand']['id']}/trend-batches", json=batch).status_code == 422


def test_rate_uses_elapsed_time_and_zeros_are_unknown():
    batch = demo_batch().model_dump(mode="json")
    batch["posts"] = batch["posts"][:1]
    p = batch["posts"][0]
    now = datetime.now(timezone.utc)
    p["published_at"] = (now-timedelta(days=11)).isoformat()
    p["snapshots"] = [
        {"observed_at":(now-timedelta(days=10)).isoformat(),"views":100},
        {"observed_at":(now-timedelta(days=8)).isoformat(),"views":300},
        {"observed_at":(now-timedelta(days=2)).isoformat(),"views":900},
    ]
    identity = draft_identity(demo_brief()).model_dump()
    result = analyze(BatchCreate.model_validate(batch), identity)["topics"][0]
    assert result["acceleration_pct"] == 0  # 100/day in both unequal intervals
    assert result["confidence"] == "baja"
    p["snapshots"][1]["views"] = 100
    result = analyze(BatchCreate.model_validate(batch), identity)["topics"][0]
    assert result["acceleration_pct"] is None
    assert result["stage"] == "Sin serie suficiente"
    p["snapshots"] = p["snapshots"][-1:]
    result = analyze(BatchCreate.model_validate(batch), identity)["topics"][0]
    assert result["views_per_day"] is None


def test_stale_evidence_is_not_included():
    batch = demo_batch()
    old = batch.model_dump(mode="json")
    for post in old["posts"]:
        post["published_at"] = (datetime.fromisoformat(post["published_at"])-timedelta(days=40)).isoformat()
        for snapshot in post["snapshots"]:
            snapshot["observed_at"] = (datetime.fromisoformat(snapshot["observed_at"])-timedelta(days=40)).isoformat()
    assert analyze(BatchCreate.model_validate(old), draft_identity(demo_brief()).model_dump())["topics"] == []
