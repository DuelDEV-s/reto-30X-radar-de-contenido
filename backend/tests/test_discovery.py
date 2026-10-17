import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.creators import CreatorCandidate, SearchHit, Source, collect_candidates, discard_reason, extract_username
from app.database import Base, get_session
from app.discovery import discover_creators, geo_targets, site_share
from app.main import app, get_post_resolver, get_serp_client
from app.post_resolver import OEmbedResolver, PostAuthor, shortcode
from app.query_builder import QueryContext, build_queries
from app.serp import BrightDataSerpClient, SerpError, SerpResult, parse_organic


class FakeSerp:
    def __init__(self, pages=None, fail=()):
        self.pages, self.fail, self.calls = pages or {}, set(fail), []

    def search(self, query, *, hl=None, gl=None):
        self.calls.append((query, hl, gl))
        if query in self.fail or "*" in self.fail:
            raise SerpError("Bright Data rechazó la API key (401).", 401)
        return self.pages.get(query, [])


class FakeResolver:
    def __init__(self, authors):
        self.authors, self.calls = authors, []

    def resolve(self, url):
        self.calls.append(url)
        return self.authors.get(url)


def result(link, title="", description="", rank=1):
    return SerpResult(link=link, title=title, description=description, rank=rank)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def override():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.mark.parametrize("link,title,expected", [
    ("https://www.instagram.com/crece30x/", "", "crece30x"),
    ("https://instagram.com/Ana.IA_tips?hl=es", "", "ana.ia_tips"),
    ("https://www.instagram.com/p/C1abc/", "Ana Pérez (@ana.ia) • Instagram", "ana.ia"),
    ("https://www.instagram.com/reel/C1abc/", "Video sin usuario", None),
    ("https://www.instagram.com/explore/tags/ia/", "", None),
    ("https://www.instagram.com/", "", None),
    ("https://www.tiktok.com/@ana", "", None),
])
def test_extract_username(link, title, expected):
    assert extract_username(link, title) == expected


def test_collect_candidates_dedupes_and_ranks():
    def ev(query, link, rank, title="", description=""):
        return SearchHit(query=query, rank=rank, link=link, title=title, description=description)
    candidates, discarded, unresolved = collect_candidates([
        ev("q1", "https://www.instagram.com/ana.ia/", 3, "Ana (@ana.ia)", "45K Followers"),
        ev("q2", "https://www.instagram.com/p/X/", 1, "Ana (@ana.ia) en Instagram", "50K Followers"),
        ev("q1", "https://www.instagram.com/tienda.ia/", 1, "Tienda oficial IA", "8K seguidores"),
        ev("q1", "https://www.instagram.com/explore/", 2),
    ])
    assert discarded == 1 and unresolved == []
    ana, store = candidates
    assert (ana.username, ana.query_hits, ana.best_rank) == ("ana.ia", 2, 1)
    assert ana.sources == [Source(query="q1", link="https://www.instagram.com/ana.ia/", rank=3), Source(query="q2", link="https://www.instagram.com/p/X/", rank=1)]
    assert (store.username, store.query_hits, store.best_rank) == ("tienda.ia", 1, 1)
    # Descubrimiento no infiere seguidores, tamaño ni tipo de cuenta, ni conserva el texto de Google.
    assert set(CreatorCandidate.model_fields) == {"username", "profile_url", "query_hits", "best_rank", "sources"}
    assert set(Source.model_fields) == {"query", "link", "rank"}


def test_geo_targets():
    assert geo_targets("Latinoamérica") == ["co"]
    assert geo_targets("LATAM") == ["co"]
    assert geo_targets("Europa") == [None]
    assert geo_targets("México") == ["mx"]
    assert geo_targets("Latinoamérica", ["MX", "co", "mx"]) == ["mx", "co"]


def test_discover_creators_survives_partial_failures():
    plan = build_queries(QueryContext(topics=["ia", "empresarios"], region="Chile", max_queries=2))
    ok, bad = plan.queries[0].query, plan.queries[1].query
    serp = FakeSerp({ok: [result("https://www.instagram.com/ana.ia/", "Ana (@ana.ia)", "12K Followers")]}, fail={bad})
    found = discover_creators(plan, serp, countries=["cl", "mx"])
    assert len(serp.calls) == 4 and {c[2] for c in serp.calls} == {"cl", "mx"} and all(hl == "es" for _, hl, _ in serp.calls)
    assert [c.username for c in found.candidates] == ["ana.ia"]
    assert sum(1 for q in found.queries if q.error) == 2


def test_brightdata_client_request_and_parsing():
    seen = {}
    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"organic": [{"link": "https://www.instagram.com/ana/", "title": "Ana", "description": "1K followers", "global_rank": 4}, {"title": "sin link"}]})
    client = BrightDataSerpClient(" key123\r", "serp_api1", http=httpx.Client(transport=httpx.MockTransport(handler)))
    results = client.search('site:instagram.com "ia"', hl="es", gl=None)
    assert seen["auth"] == "Bearer key123"
    assert seen["body"]["zone"] == "serp_api1" and seen["body"]["format"] == "raw"
    assert "brd_json=1" in seen["body"]["url"] and "num=" not in seen["body"]["url"] and "hl=es" in seen["body"]["url"] and "lr=lang_es" in seen["body"]["url"] and "gl=" not in seen["body"]["url"]
    assert results == [SerpResult(link="https://www.instagram.com/ana/", title="Ana", description="1K followers", rank=4)]


def test_brightdata_client_errors():
    def unauthorized(request):
        return httpx.Response(401, headers={"x-brd-error": "invalid token"})
    client = BrightDataSerpClient("bad", "zone", http=httpx.Client(transport=httpx.MockTransport(unauthorized)))
    with pytest.raises(SerpError, match="401") as error:
        client.search("q")
    assert error.value.status == 401
    assert parse_organic({}) == []


def test_creator_search_endpoint(client, monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
    app.dependency_overrides[get_post_resolver] = lambda: FakeResolver({})
    brand_id = client.post("/api/demo").json()["brand"]["id"]
    assert client.post(f"/api/brands/{brand_id}/creator-search", json={}).status_code == 503

    serp = FakeSerp()
    app.dependency_overrides[get_serp_client] = lambda: serp
    plan_query = client.post(f"/api/brands/{brand_id}/discovery-queries", json={"max_queries": 1}).json()["queries"][0]["query"]
    serp.pages[plan_query] = [result("https://www.instagram.com/ana.ia/", "Ana (@ana.ia)", "12K Followers")]
    response = client.post(f"/api/brands/{brand_id}/creator-search", json={"max_queries": 1, "countries": ["mx"]})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["username"] == "ana.ia" and body["queries"][0]["gl"] == "mx" and body["unresolved_posts"] == []
    assert client.post(f"/api/brands/{brand_id}/creator-search", json={"countries": ["mexico"]}).status_code == 422

    app.dependency_overrides[get_serp_client] = lambda: FakeSerp(fail={"*"})
    failed = client.post(f"/api/brands/{brand_id}/creator-search", json={"max_queries": 1})
    assert failed.status_code == 502 and "401" in failed.json()["detail"]


def test_discarded_results_are_logged_with_reason(caplog):
    def ev(link, title=""):
        return SearchHit(query="q1", rank=1, link=link, title=title)
    with caplog.at_level("INFO", logger="app.creators"):
        candidates, discarded, unresolved = collect_candidates([ev("https://www.instagram.com/reel/X/", "Video"), ev("https://www.instagram.com/explore/tags/ia/"), ev("https://example.com/ana")])
    assert candidates == [] and discarded == 3 and unresolved == ["https://www.instagram.com/reel/X/"]
    assert "post/reel sin @usuario" in caplog.text and "ruta que no es perfil" in caplog.text and "otro dominio" in caplog.text
    assert "https://www.instagram.com/reel/X/ | Video | query=q1" in caplog.text
    assert discard_reason("https://www.instagram.com/ana-maria/") == "usuario no válido"


def test_posts_without_user_are_resolved_with_resolver():
    def ev(link, query="q1"):
        return SearchHit(query=query, rank=2, link=link, title="Caption sin usuario")
    resolver = FakeResolver({"https://www.instagram.com/reel/AAA/": PostAuthor(username="miguebaenaia", author_id="7547", caption="3 herramientas de IA")})
    candidates, discarded, unresolved = collect_candidates([
        ev("https://www.instagram.com/reel/AAA/"), ev("https://www.instagram.com/p/BBB/"),
        ev("https://www.instagram.com/miguebaenaia/reel/CCC/", "q2"), ev("https://www.instagram.com/explore/"),
    ], resolver)
    assert resolver.calls == ["https://www.instagram.com/reel/AAA/", "https://www.instagram.com/p/BBB/"]  # explore y URLs con usuario no se consultan
    assert [c.username for c in candidates] == ["miguebaenaia"] and candidates[0].query_hits == 2
    assert [src.link for src in candidates[0].sources] == ["https://www.instagram.com/reel/AAA/", "https://www.instagram.com/miguebaenaia/reel/CCC/"]
    assert discarded == 2 and unresolved == ["https://www.instagram.com/p/BBB/"]


def test_oembed_resolver_parses_caches_and_stops_on_429():
    calls = []
    def handler(request):
        calls.append(request.url.params["url"])
        if "LIMIT" in request.url.params["url"]:
            return httpx.Response(429)
        return httpx.Response(200, json={"author_name": "MigueBaenaIA", "author_id": 75470897005, "title": "Caption"})
    resolver = OEmbedResolver(delay=0, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert shortcode("https://www.instagram.com/reel/DemK_I4FH49/?igsh=x") == "DemK_I4FH49"
    author = resolver.resolve("https://www.instagram.com/reel/DemK_I4FH49/?igsh=x")
    assert author == PostAuthor(username="miguebaenaia", author_id="75470897005", caption="Caption")
    assert calls == ["https://www.instagram.com/reel/DemK_I4FH49/"]
    resolver.resolve("https://www.instagram.com/reel/DemK_I4FH49/")
    assert len(calls) == 1  # caché por código
    assert resolver.resolve("https://www.instagram.com/p/LIMIT/") is None and resolver.blocked
    assert resolver.resolve("https://www.instagram.com/p/OTHER/") is None and len(calls) == 2
    assert resolver.resolve("https://www.instagram.com/ana/") is None


def test_oembed_resolver_respects_request_budget(caplog):
    calls = []
    resolver = OEmbedResolver(delay=0, max_requests=1, http=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(404))))
    assert resolver.resolve("https://www.instagram.com/p/A/") is None
    with caplog.at_level("WARNING", logger="app.post_resolver"):
        assert resolver.resolve("https://www.instagram.com/p/B/") is None
        assert resolver.resolve("https://www.instagram.com/p/C/") is None
    assert len(calls) == 1 and caplog.text.count("máximo de 1 consultas") == 1


def test_fallback_when_google_ignores_site():
    plan = build_queries(QueryContext(topics=["inteligencia artificial"], region="Chile", max_queries=1, profiles_only=True))
    idea = plan.queries[0]
    serp = FakeSerp({
        idea.query: [result("https://www.youtube.com/watch?v=1"), result("https://blog.example.com/ia"), result("https://www.instagram.com/ana/")],
        idea.fallback: [result("https://www.instagram.com/ana/", "Ana (@ana)"), result("https://www.instagram.com/luis/")],
    })
    found = discover_creators(plan, serp)
    assert [c[0] for c in serp.calls] == [idea.query, idea.fallback]
    assert found.queries[0].fallback_used and found.queries[0].query == idea.fallback
    assert sorted(c.username for c in found.candidates) == ["ana", "luis"]
    assert site_share([result("https://help.instagram.com/x"), result("https://notinstagram.com/")], "instagram.com") == 0.5


def test_no_fallback_when_site_is_respected():
    plan = build_queries(QueryContext(topics=["inteligencia artificial"], region="Chile", max_queries=1, profiles_only=True))
    serp = FakeSerp({plan.queries[0].query: [result("https://www.instagram.com/ana/")]})
    found = discover_creators(plan, serp)
    assert len(serp.calls) == 1 and not found.queries[0].fallback_used


def test_brightdata_client_retries_non_json_once():
    responses = iter([httpx.Response(200, text="<html>oops</html>"), httpx.Response(200, json={"organic": [{"link": "https://www.instagram.com/ana/"}]})])
    client = BrightDataSerpClient("k", "z", backoff=0, http=httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))))
    assert [r.link for r in client.search("q")] == ["https://www.instagram.com/ana/"]
    calls = []
    always_bad = BrightDataSerpClient("k", "z", backoff=0, http=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(200, text="x"))))
    with pytest.raises(SerpError, match="JSON"):
        always_bad.search("q")
    assert len(calls) == 3
