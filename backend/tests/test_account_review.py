import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.account_review import OpenAIReviewer, Verdict, evidence, included, review_accounts
from app.database import AccountReview, Brand, InstagramAccount, RelatedAccount, RelatedAccountRun
from app.main import app, get_bright_data_client, get_reviewer, get_session, get_serp_client, get_post_resolver

VERDICTS = {
    "andresbilbao": Verdict(relevance="alta", account_type="creador", is_internal=False, reason="Emprendedor que habla de escalar negocios."),
    "dylanrosemberg": Verdict(relevance="media", account_type="creador", is_internal=False, reason="Emprendimiento, menos foco en IA."),
    "ishopcolombia": Verdict(relevance="baja", account_type="promocion_comercial", is_internal=False, reason="Distribuidor de Apple; colaboración promocional."),
    "mintic": Verdict(relevance="alta", account_type="gobierno_institucion", is_internal=False, reason="Ministerio TIC."),
    "guillermojaramillo.30x": Verdict(relevance="alta", account_type="creador", is_internal=True, reason="El usuario lleva el nombre de la marca: equipo de 30X."),
}


class FakeReviewer:
    model, effort = "gpt-6-luna", "low"

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    async def review(self, brand, evidence):
        self.calls.append(evidence["username"])
        self.brand = brand
        if evidence["username"] in self.fail:
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        return VERDICTS[evidence["username"]]


def session():
    return next(app.dependency_overrides[get_session]())


def account(name, **values):
    return InstagramAccount(username=name, full_name=name.title(), external_urls=[], fetch_status="ok", fetched_at=datetime.now(timezone.utc),
                            raw={"posts": [{"caption": f"Post de {name}"}]}, **values)


def seed_related(brand_id, names):
    db = session()
    db.add(RelatedAccountRun(brand_id=brand_id, generation="g", state="ready", brand_account="crece30x", message="",
                             created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    for name in names:
        db.add(account(name))
        db.add(RelatedAccount(brand_id=brand_id, username=name, relations=["coauthor"], reel_urls=["https://www.instagram.com/p/X/"]))
    db.commit()


def test_topic_inclusion_rule():
    def v(relevance, kind, internal=False):
        return AccountReview(relevance=relevance, account_type=kind, is_internal=internal)
    assert included(v("alta", "creador")) and included(v("media", "empresa_afin"))
    assert not included(v("baja", "creador")) and not included(v("ninguna", "empresa_afin"))
    # Una cuenta interna nunca pasa, aunque sea un creador de relevancia alta.
    assert not included(v("alta", "creador", internal=True))
    for kind in ("promocion_comercial", "gobierno_institucion", "medio", "otro"):
        assert not included(v("alta", kind))
    assert not included(None)


def test_evidence_uses_profile_and_recent_captions():
    a = account("ana", biography="IA para pymes", category="Creador digital", followers=12000)
    a.raw = {"posts": [{"caption": "x" * 1000}, {"caption": ""}, {"description": "Reel sobre agentes"}] + [{"caption": f"p{i}"} for i in range(20)], "bio_hashtags": ["#ia"]}
    e = evidence(a)
    assert e["biography"] == "IA para pymes" and e["category"] == "Creador digital" and e["bio_hashtags"] == ["#ia"]
    assert len(e["recent_captions"][0]) == 400 and e["recent_captions"][1] == "Reel sobre agentes" and len(e["recent_captions"]) == 7


@pytest.fixture
def brand_id(client):
    return client.post("/api/demo").json()["brand"]["id"]


def test_reviews_are_cached_until_identity_or_profile_changes(client, brand_id):
    seed_related(brand_id, ["andresbilbao", "ishopcolombia"])
    db = session()
    db.add(InstagramAccount(username="sinficha", external_urls=[], fetch_status="not_found", fetched_at=datetime.now(timezone.utc)))
    db.commit()
    reviewer = FakeReviewer()
    brand = db.get(Brand, brand_id)
    assert asyncio.run(review_accounts(db, brand, ["andresbilbao", "ishopcolombia", "sinficha", "nadie"], reviewer)) == 2
    assert asyncio.run(review_accounts(db, brand, ["andresbilbao", "ishopcolombia"], reviewer)) == 0
    assert reviewer.calls == ["andresbilbao", "ishopcolombia"]

    profile = db.get(InstagramAccount, "andresbilbao")
    profile.biography = "Nueva bio"
    db.commit()
    assert asyncio.run(review_accounts(db, brand, ["andresbilbao", "ishopcolombia"], reviewer)) == 1
    brand.identity = {**brand.identity, "topics": ["otro tema"]}
    db.commit()
    assert asyncio.run(review_accounts(db, brand, ["andresbilbao", "ishopcolombia"], reviewer)) == 2


def test_related_accounts_show_verdicts_without_filtering(client, brand_id):
    seed_related(brand_id, ["andresbilbao", "dylanrosemberg", "ishopcolombia", "mintic", "guillermojaramillo.30x"])
    reviewer = FakeReviewer(fail={"mintic"})
    app.dependency_overrides[get_reviewer] = lambda: reviewer
    body = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    by_user = {a["username"]: a for a in body["accounts"]}
    # Todas se muestran; el veredicto es informativo.
    assert set(by_user) == {"andresbilbao", "dylanrosemberg", "ishopcolombia", "mintic", "guillermojaramillo.30x"}
    assert all("included" not in a for a in body["accounts"]) and "review_summary" not in body
    assert by_user["ishopcolombia"]["review"]["account_type"] == "promocion_comercial"
    assert by_user["guillermojaramillo.30x"]["review"]["is_internal"]
    assert by_user["mintic"]["review_status"] == "pending" and by_user["mintic"]["review"] is None
    # El LLM recibe el nombre y las cuentas propias de la marca para reconocer cuentas internas.
    assert reviewer.brand["name"] == "30X · Demo" and "topics" in reviewer.brand

    # Sin OPENAI_API_KEY no se revisa nada; los veredictos guardados se siguen mostrando.
    app.dependency_overrides[get_reviewer] = lambda: None
    again = client.get(f"/api/brands/{brand_id}/related-accounts").json()
    assert sum(a["review_status"] == "reviewed" for a in again["accounts"]) == 4 and len(reviewer.calls) == 5


def test_topic_candidates_include_medium_relevance(client, brand_id, monkeypatch):
    from tests.test_discovery import FakeResolver, FakeSerp, result
    serp = FakeSerp()
    app.dependency_overrides[get_serp_client] = lambda: serp
    app.dependency_overrides[get_post_resolver] = lambda: FakeResolver({})
    query = client.post(f"/api/brands/{brand_id}/discovery-queries", json={"max_queries": 1}).json()["queries"][0]["query"]
    names = ["andresbilbao", "dylanrosemberg", "ishopcolombia", "guillermojaramillo.30x"]
    serp.pages[query] = [result(f"https://www.instagram.com/{n}/", rank=i) for i, n in enumerate(names, 1)]
    run_id = client.post(f"/api/brands/{brand_id}/creator-search", json={"max_queries": 1}).json()["run_id"]
    db = session()
    for name in names:
        db.add(account(name))
    db.commit()

    async def no_network():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
            yield http
    app.dependency_overrides[get_bright_data_client] = no_network
    app.dependency_overrides[get_reviewer] = lambda: FakeReviewer()
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHT_DATA_INSTAGRAM_DATASET_ID", "gd_profiles")
    body = client.post(f"/api/discovery-runs/{run_id}/profiles").json()  # todo guardado: sin costo y revisado
    assert body["profiles"]["state"] == "ready"
    included_users = {c["username"] for c in body["candidates"] if c["included"]}
    assert included_users == {"andresbilbao", "dylanrosemberg"}  # media sí cuenta; promoción e interna no
    assert body["review_summary"] == {"included": 2, "internal": 1, "excluded": 2, "pending": 0}


def test_openai_reviewer_sends_model_effort_and_schema():
    seen = {}

    async def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_parsed=VERDICTS["andresbilbao"])

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    reviewer = OpenAIReviewer(client=client)
    verdict = asyncio.run(reviewer.review({"name": "30X", "instagram_accounts": ["crece30x"]}, {"username": "andresbilbao"}))
    assert verdict.account_type == "creador"
    assert seen["model"] == "gpt-6-luna" and seen["reasoning"] == {"effort": "low"} and seen["text_format"] is Verdict
    assert "temperature" not in seen
    payload = json.loads(seen["input"])
    assert payload == {"marca": {"name": "30X", "instagram_accounts": ["crece30x"]}, "cuenta": {"username": "andresbilbao"}}
    assert "is_internal" in seen["instructions"]
    assert "promocion_comercial" in seen["instructions"] and "gobierno_institucion" in seen["instructions"]


def test_brand_context_has_name_handles_and_identity(client, brand_id):
    from app.account_review import brand_context
    db = session()
    brand = db.get(Brand, brand_id)
    brand.brief = {**brand.brief, "profiles": [{"platform": "instagram", "url": "https://www.instagram.com/Crece30X/"}, {"platform": "youtube", "url": "https://youtube.com/@x"}]}
    db.commit()
    context = brand_context(brand)
    assert context["name"] == "30X · Demo" and context["instagram_accounts"] == ["crece30x"]
    assert set(context) == {"name", "instagram_accounts", "summary", "audience", "region", "topics", "personas"}


def test_reviews_run_in_batches_when_limited(client, brand_id):
    seed_related(brand_id, ["andresbilbao", "dylanrosemberg", "ishopcolombia", "mintic"])
    db = session()
    brand = db.get(Brand, brand_id)
    reviewer = FakeReviewer()
    names = ["andresbilbao", "dylanrosemberg", "ishopcolombia", "mintic"]
    assert asyncio.run(review_accounts(db, brand, names, reviewer, limit=3)) == 3
    assert asyncio.run(review_accounts(db, brand, names, reviewer, limit=3)) == 1
    assert asyncio.run(review_accounts(db, brand, names, reviewer, limit=3)) == 0
    assert sorted(reviewer.calls) == sorted(names)
