from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import trend_runs
from app.database import Base, Brand, TrendRun, get_session
from app.main import app
from app.trends.contracts import Report
from app.trends.mock import MOCK

KEYS = {"YOUTUBE_API_KEY": "yt", "EXA_API_KEY": "exa", "ANTHROPIC_API_KEY": "anthropic"}
NOW = datetime.now(timezone.utc).replace(microsecond=0)
BRIEF = {"name": "30X", "description": "Educación en IA para líderes y equipos de Latinoamérica.",
         "audience": "Líderes", "region": "Latinoamérica", "topics": ["inteligencia artificial", "negocios"]}


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def piece(video_id, views, fmt="long", topic="Agentes de IA para ventas en pymes"):
    times = [NOW - timedelta(days=3), NOW - timedelta(days=2), NOW - timedelta(hours=2)]
    return {"video_id": video_id, "title": f"Video {video_id} sobre agentes", "topic": topic, "format": fmt,
            "published_at": iso(NOW - timedelta(days=5)), "snapshots": [(iso(t), v) for t, v in zip(times, views)]}


class FakeRun:
    def __init__(self, identity, run_id, on_stage, pieces=None, fail=False):
        self.identity, self.run_id, self.on_stage, self.fail = identity, run_id, on_stage, fail
        self.pieces = pieces if pieces is not None else [piece("aaa", [100, 300, 900]), piece("bbb", [50, 60, 61], "short")]

    def execute(self):
        for stage in ("bootstrap", "queries", "youtube (28d)", "linkedin (28d)", "report"):
            self.on_stage(stage)
        if self.fail:
            raise RuntimeError("Exa devolvió 401")
        return Report.model_validate(MOCK)

    def youtube_pieces(self):
        return self.pieces


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = override
    monkeypatch.setattr(trend_runs, "SessionLocal", factory)
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def brand(client, **identity):
    data = client.post("/api/brands", json=BRIEF).json()
    if identity:
        current = {k: v for k, v in data["identity"].items() if k != "status"} | identity
        data = client.put(f"/api/brands/{data['id']}/identity", json=current).json()
    return data


def test_markets_from_free_region():
    assert trend_runs.markets_for("Latinoamérica").regions == ["MX", "CO", "AR", "CL", "PE"]
    m = trend_runs.markets_for("México y Colombia")
    assert m.languages == ["es"] and m.regions == ["MX", "CO"]
    assert trend_runs.markets_for("Brasil").languages == ["pt"]
    assert trend_runs.markets_for("Global").regions == ["MX", "CO", "AR", "CL", "PE"]    # default


def test_engine_identity_maps_brand(setup):
    client, factory = setup
    b = brand(client, personas=[{"role": "Líder de equipo", "need": "Adoptar IA sin perder foco"},
                                {"role": "Líder de equipo", "need": "Medir resultados de la IA"}])
    with factory() as db:
        row = db.get(Brand, b["id"])
        row.brief = row.brief | {"profiles": [{"platform": "youtube", "url": "https://www.youtube.com/@crece30x", "description": ""},
                                              {"platform": "linkedin", "url": "https://www.linkedin.com/company/30x", "description": ""}]}
        idn = trend_runs.engine_identity(row, ["linkedin"], 28)
    assert idn.brand_name == "30X" and idn.general_topic == "inteligencia artificial"
    assert idn.specific_topics == ["negocios"]
    assert [p.id for p in idn.personas] == ["lider-de-equipo", "lider-de-equipo-2"]
    assert idn.handles.youtube == "@crece30x" and idn.handles.linkedin.endswith("/company/30x")
    assert idn.output_platforms == ["linkedin"] and "Audiencia: Líderes" in idn.description


def test_requires_server_keys(setup):
    client, _ = setup
    b = brand(client)
    r = client.post(f"/api/brands/{b['id']}/trend-runs", json={"platforms": ["linkedin"]})
    assert r.status_code == 503 and "EXA_API_KEY" in r.json()["detail"]
    assert client.get("/api/trend-engine").json()["configured"] is False


def test_rejects_placeholder_topics(setup, monkeypatch):
    client, _ = setup
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    b = client.post("/api/brands", json=BRIEF | {"topics": []}).json()
    r = client.post(f"/api/brands/{b['id']}/trend-runs", json={})
    assert r.status_code == 409 and "tópico" in r.json()["detail"]


def test_full_run_feeds_step_3(setup, monkeypatch):
    client, _ = setup
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(trend_runs, "make_engine_run", lambda idn, rid, cb: FakeRun(idn, rid, cb))
    b = brand(client)
    started = client.post(f"/api/brands/{b['id']}/trend-runs", json={"platforms": ["linkedin", "youtube"], "window_days": 28})
    assert started.status_code == 202
    run = client.get(f"/api/trend-runs/{started.json()['id']}").json()
    assert run["status"] == "done" and run["stage"] == "done" and run["error"] is None
    assert run["report"]["opportunities"][0]["type"] == "linkedin_gap"
    assert run["report"]["run"]["window"]["from"] == "2026-09-19"       # alias kept in the stored report
    assert run["identity"]["output_platforms"] == ["linkedin", "youtube"]
    assert run["totals"] == {"topics": 2, "opportunities": 1}
    # The YouTube evidence lands as a public v1 batch that the step 3 radar analyzes.
    batches = client.get(f"/api/brands/{b['id']}/trend-batches").json()
    assert batches[0]["id"] == run["batch_id"] and batches[0]["mode"] == "public" and batches[0]["posts"] == 2
    report = client.get(f"/api/brands/{b['id']}/report", params={"batch_id": run["batch_id"]}).json()
    topic = report["topics"][0]
    assert topic["topic"] == "agentes de ia para ventas en pymes" and topic["acceleration_pct"] is not None
    assert topic["top_content"]["url"] == "https://youtu.be/aaa"
    assert client.get(f"/api/brands/{b['id']}/trend-runs").json()[0]["status"] == "done"


def test_failed_run_is_recorded(setup, monkeypatch):
    client, _ = setup
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(trend_runs, "make_engine_run", lambda idn, rid, cb: FakeRun(idn, rid, cb, fail=True))
    b = brand(client)
    run_id = client.post(f"/api/brands/{b['id']}/trend-runs", json={}).json()["id"]
    run = client.get(f"/api/trend-runs/{run_id}").json()
    assert run["status"] == "failed" and "401" in run["error"] and run["batch_id"] is None
    # A failed run doesn't block a new one.
    assert client.post(f"/api/brands/{b['id']}/trend-runs", json={}).status_code == 202


def test_one_active_run_per_brand_and_stale_runs_expire(setup, monkeypatch):
    client, factory = setup
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(trend_runs, "execute", lambda run_id, session_factory=None: None)    # stays queued
    b = brand(client)
    first = client.post(f"/api/brands/{b['id']}/trend-runs", json={}).json()
    second = client.post(f"/api/brands/{b['id']}/trend-runs", json={})
    assert second.status_code == 409
    with factory() as db:
        db.get(TrendRun, first["id"]).updated_at = NOW - timedelta(hours=2)
        db.commit()
    assert client.get(f"/api/trend-runs/{first['id']}").json()["status"] == "failed"
    assert client.post(f"/api/brands/{b['id']}/trend-runs", json={}).status_code == 202


def test_batch_skips_points_that_break_the_contract():
    pieces = [piece("ok1", [100, 90, 200]), piece("nosnap", []), piece("x", [5, 6, 7]) | {"title": "ab"}]
    batch = trend_runs.to_batch(pieces, "run-1", "30X")
    assert [p.external_id for p in batch.posts] == ["ok1"]
    assert [s.views for s in batch.posts[0].snapshots] == [100, 200]      # the decreasing point is dropped
    assert batch.posts[0].source_method == "official_api"
    assert trend_runs.to_batch([], "run-1", "30X") is None


def test_batch_spaces_out_close_observations():
    # Readings minutes apart (reruns) would give meaningless velocities: keep >= 3 h apart, latest first.
    times = [NOW - timedelta(hours=h) for h in (30, 29.9, 12, 11.95, 2, 1.9)]
    p = piece("close", []) | {"snapshots": [(iso(t), v) for t, v in zip(times, [100, 101, 300, 301, 900, 910])]}
    snaps = trend_runs.to_batch([p], "run-1", "30X").posts[0].snapshots
    assert [s.views for s in snaps] == [101, 301, 910]


def test_request_validation(setup):
    client, _ = setup
    b = brand(client)
    assert client.post(f"/api/brands/{b['id']}/trend-runs", json={"platforms": ["instagram"]}).status_code == 422
    assert client.post(f"/api/brands/{b['id']}/trend-runs", json={"window_days": 3}).status_code == 422
    assert client.get("/api/trend-runs/missing").status_code == 404
