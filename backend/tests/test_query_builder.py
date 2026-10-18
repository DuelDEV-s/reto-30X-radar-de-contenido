import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.demo import demo_brief
from app.main import app
from app.query_builder import QueryContext, QueryPlan, RuleQueryBuilder, build_queries, context_terms, is_ambiguous, keywords, phrases
from app.services import draft_identity


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


@pytest.fixture
def identity():
    return draft_identity(demo_brief()).model_dump(mode="json")


def test_rules_build_diverse_unique_site_queries(identity):
    plan = build_queries(QueryContext.from_identity(identity, max_queries=6))
    queries = [q.query for q in plan.queries]
    assert plan.method == "rules" and len(queries) == 6
    assert all(q.startswith("site:instagram.com ") for q in queries)
    assert len(set(queries)) == len(queries)
    assert len({q.angle for q in plan.queries}) >= 2
    assert len({q.topic for q in plan.queries}) >= 2
    assert all(not q.keywords.startswith("site:") for q in plan.queries)


def test_focus_topic_and_platform(identity):
    plan = build_queries(QueryContext.from_identity(identity, focus_topic="Automatización", platform="tiktok", max_queries=20))
    assert {q.topic for q in plan.queries} == {"automatización"}
    assert all(q.query.startswith('site:tiktok.com "automatización"') for q in plan.queries)
    # Contexto de la identidad intercalado con los demás tópicos de la marca; la región va al final.
    assert [q.angle for q in plan.queries] == ["topic", "context", "cross", "context", "cross", "context", "cross", "region"]
    assert [q.keywords for q in plan.queries if q.angle == "context"] == ['"automatización" líderes', '"automatización" equipos', '"automatización" aprenden ia']
    assert [q.keywords for q in plan.queries if q.angle == "cross"] == ['"automatización" agentes de ia', '"automatización" ia en negocios', '"automatización" productividad']


def test_ambiguous_topic_never_searched_alone_and_cross_not_mirrored():
    ctx = QueryContext(
        topics=["IA", "empresarios", "líderes"], region="Latinoamérica", focus_topic="IA",
        summary="Formamos empresarios y líderes corporativos en inteligencia artificial",
        audience="empresarios y líderes corporativos", personas=["Líderes corporativos. Aplicar inteligencia artificial en su empresa"],
    )
    plan = build_queries(ctx)
    assert all(q.angle != "topic" for q in plan.queries)  # "ia" solo es ambiguo para Google
    assert [q.keywords for q in plan.queries[:2]] == ['"ia" líderes corporativos', '"ia" empresarios']
    assert '"ia" inteligencia artificial' in {q.keywords for q in plan.queries}
    assert is_ambiguous("IA") and is_ambiguous("seo") and not is_ambiguous("ventas") and not is_ambiguous("agentes de ia")
    unfocused = build_queries(QueryContext(topics=["ia", "empresarios"], region="Chile", max_queries=20))
    pairs = [q.keywords for q in unfocused.queries if q.angle == "cross"]
    assert len(pairs) == 1  # "ia" empresarios y "empresarios" ia son la misma búsqueda


def test_minimal_context_without_personas_or_audience():
    plan = build_queries(QueryContext(topics=["recetas veganas"], region="Chile"))
    assert [q.angle for q in plan.queries] == ["topic", "region"]


def test_keywords_keep_order_and_skip_stopwords():
    assert keywords("Líderes y equipos que aprenden IA") == ["Líderes", "equipos", "aprenden"]
    assert keywords("Equipos que aprenden IA en empresas", exclude="agentes de IA", n=5) == ["Equipos", "aprenden", "empresas"]


def test_custom_builder_plugs_into_build_queries(identity):
    class Fixed:
        def build(self, ctx):
            return QueryPlan(method="rules", platform=ctx.platform, queries=[])
    assert build_queries(QueryContext.from_identity(identity), Fixed()).queries == []
    assert isinstance(RuleQueryBuilder().build(QueryContext.from_identity(identity)), QueryPlan)


def test_discovery_queries_endpoint(client):
    assert client.post("/api/brands/missing/discovery-queries", json={}).status_code == 404
    brand_id = client.post("/api/demo").json()["brand"]["id"]
    response = client.post(f"/api/brands/{brand_id}/discovery-queries", json={"topic": "agentes de IA", "max_queries": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["identity_status"] == "draft" and body["platform"] == "instagram"
    assert len(body["queries"]) == 2 and all(q["topic"] == "agentes de ia" for q in body["queries"]) and all("agentes de ia" in q["query"] for q in body["queries"])
    assert client.post(f"/api/brands/{brand_id}/discovery-queries", json={"max_queries": 0}).status_code == 422


def test_queries_have_no_signals_and_profile_filters_have_fallback(identity):
    default = build_queries(QueryContext.from_identity(identity))
    assert all(q.query == f"site:instagram.com {q.keywords}" and q.fallback is None for q in default.queries)
    assert all("seguidores" not in q.query and "followers" not in q.query for q in default.queries)
    profiles = build_queries(QueryContext.from_identity(identity, profiles_only=True))
    assert all(q.query.endswith(" -inurl:reel -inurl:explore -inurl:tags") for q in profiles.queries)
    assert all(q.fallback == f"site:instagram.com {q.keywords}" for q in profiles.queries)
    tiktok = build_queries(QueryContext.from_identity(identity, platform="tiktok", profiles_only=True))
    assert all("inurl" not in q.query for q in tiktok.queries)


def test_context_terms_keep_repeated_phrases_whole():
    ctx = QueryContext(
        topics=["escalar negocios", "inteligencia artificial para empresas", "ventas"], region="Latinoamérica",
        summary="Escuela para escalar negocios con ventas e inteligencia artificial. Inscríbete en nuestros programas.",
        audience="Fundadores que quieren aplicar inteligencia artificial y ventas",
    )
    terms = context_terms(ctx)
    assert terms[:3] == ["inteligencia artificial", "ventas", "escalar negocios"]
    # Ni medias frases ("inteligencia", "escalar"), ni fragmentos solapados ("aplicar inteligencia"), ni palabras de un solo campo.
    assert not {"inteligencia", "artificial", "escalar", "aplicar inteligencia", "programas", "inscríbete"} & set(terms)
    assert "latinoamérica" not in terms  # la región ya la cubre gl
    assert context_terms(ctx, exclude="ventas")[:2] == ["inteligencia artificial", "escalar negocios"]
    assert phrases("inteligencia artificial para empresas, ventas") == ["inteligencia", "artificial", "inteligencia artificial", "empresas", "ventas"]
