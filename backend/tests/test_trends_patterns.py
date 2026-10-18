import asyncio
from datetime import datetime, timedelta, timezone

import av
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.content_patterns import ContentFeatures, analyze_posts, clip_video, contrast, select
from app.database import Base, InstagramPost, PostContentAnalysis
from app.topic_trends import OTHER, TopicGroup, TopicMap, analyze, normalize_map, state_of
from tests.test_transcription import cdn_url, make_mp4, reel

REF = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def item(code, user, days, perf, subtopics, kind="reel"):
    return {"shortcode": code, "username": user, "posted_at": REF - timedelta(days=days), "performance": perf, "label": "normal",
            "subtopics": subtopics, "url": f"https://www.instagram.com/reel/{code}/", "caption": "", "content_type": kind}


def test_normalize_map_keeps_every_label_once():
    labels = {"Claude Cowork": 2, "Cursos de Claude": 1, "CRM con IA": 1, "Suelto": 1}
    result = TopicMap(topics=[TopicGroup(name="Claude para el trabajo", description="d", labels=["Claude Cowork", "Cursos de Claude", "Inventado"]),
                              TopicGroup(name="Ventas con IA", description="d", labels=["CRM con IA", "Claude Cowork"])])
    topics = normalize_map(result, labels)
    assert [t["labels"] for t in topics] == [["Claude Cowork", "Cursos de Claude"], ["CRM con IA"], ["Suelto"]]
    assert topics[-1]["name"] == OTHER


def test_states_and_matrix():
    topics = [{"name": n, "description": "", "labels": [n]} for n in ("Caliente", "Emergente", "Ascenso", "Saturado", "Enfriando", "Poco", OTHER)]
    posts = [
        # Varios creadores, reciente y por encima de lo normal.
        item("c1", "ana", 2, 3.0, ["Caliente"]), item("c2", "luis", 4, 2.5, ["Caliente"]), item("c3", "eva", 18, 1.4, ["Caliente"]),
        # Solo en la quincena reciente, con tracción alta.
        item("e1", "ana", 1, 4.0, ["Emergente"]),
        # Mucho volumen y rendimiento bajo lo normal.
        *[item(f"s{i}", "luis", 3 + i * 3, 0.6, ["Saturado"]) for i in range(8)],
        # Publicado antes y abandonado.
        item("f1", "eva", 20, 1.3, ["Enfriando"]), item("f2", "ana", 22, 1.6, ["Enfriando"]), item("f3", "luis", 25, 1.2, ["Enfriando"]),
        item("p1", "eva", 10, 1.0, ["Poco"]),
        # Nuevo en la quincena, dos creadores, rendimiento algo por encima de lo normal.
        item("a1", "ana", 3, 1.3, ["Ascenso"]), item("a2", "luis", 5, 1.2, ["Ascenso"]), item("a3", "luis", 9, 1.4, ["Ascenso"]),
        item("o1", "eva", 5, 2.0, [OTHER]),
    ]
    result = analyze(posts, topics, REF, 30)
    states = {t["name"]: t["state"] for t in result["topics"]}
    assert states == {"Caliente": "en_caliente", "Emergente": "emergente", "Ascenso": "en_ascenso", "Saturado": "saturado",
                      "Enfriando": "enfriandose", "Poco": "insuficiente", OTHER: "otros"}
    hot = next(t for t in result["topics"] if t["name"] == "Caliente")
    assert hot["recent_creators"] == 2 and hot["creators"] == 3 and hot["traction"] > 1.5 and hot["momentum"] > 0
    # Ordenados por estado: lo caliente primero; matriz semanal que cubre la ventana.
    assert result["topics"][0]["name"] == "Caliente" and len(result["weeks"]) >= 5
    assert sum(c["posts"] for c in hot["cells"]) == 3 and hot["evidence"][0]["shortcode"] == "c1"
    assert state_of({"previous_posts": 0, "recent_posts": 1, "traction": 1.0, "posts": 1}) == "insuficiente"


def features(**overrides):
    base = dict(formato="persona_a_camara", encuadre="plano_medio", voz_cercana=True, microfono_visible=False, musica="fondo_suave",
                musica_estilo="", texto_en_pantalla="subtitulos", gancho="g", gancho_tipo="pregunta", ritmo_edicion="medio",
                tono="educativo", ambiente="casa", llamada_a_la_accion="ninguna", descripcion="d")
    return ContentFeatures(**{**base, **overrides}).model_dump()


def test_contrast_separates_patterns_from_common_traits():
    top = [features(ritmo_edicion="rapido", microfono_visible=True) for _ in range(4)]
    control = [features(ritmo_edicion="lento") for _ in range(3)] + [features(ritmo_edicion="rapido")]
    result = contrast(top, control)
    patterns = {(t["trait"], t["value"]) for t in result["patterns"]}
    assert ("ritmo_edicion", "rapido") in patterns and ("microfono_visible", True) in patterns
    # Todos usan subtítulos: es común, no explica la diferencia.
    assert ("texto_en_pantalla", "subtitulos") in {(t["trait"], t["value"]) for t in result["common"]}
    assert ("texto_en_pantalla", "subtitulos") not in patterns
    assert ("ritmo_edicion", "lento") in {(t["trait"], t["value"]) for t in result["avoid"]}
    # Sin control no hay patrones: solo lo que los destacados comparten.
    alone = contrast(top, [])
    assert alone["patterns"] == [] and ("ritmo_edicion", "rapido") in {(t["trait"], t["value"]) for t in alone["shared"]}


def test_select_pairs_controls_from_the_same_creator():
    post = lambda code, user, label, perf, on=True, kind="reel": {"shortcode": code, "username": user, "label": label, "performance": perf,
                                                                 "on_topic": on, "content_type": kind}
    posts = [post("v1", "ana", "viral", 5), post("v2", "ana", "sobresaliente", 2), post("n1", "ana", "normal", 1.0),
             post("n2", "ana", "normal", 0.8), post("n3", "ana", "normal", 1.3), post("off", "ana", "viral", 9, on=False),
             post("img", "ana", "viral", 6, kind="image"), post("v3", "luis", "viral", 4)]
    # Por defecto: top 5 por rendimiento y sin control.
    top, control = select(posts)
    assert top == ["v1", "v3", "v2"] and control == []


def test_select_caps_top_and_adds_controls_when_asked(monkeypatch):
    post = lambda code, user, label, perf: {"shortcode": code, "username": user, "label": label, "performance": perf,
                                            "on_topic": True, "content_type": "reel"}
    posts = [post(f"v{i}", "ana", "viral", 10 - i) for i in range(7)] + [post("n1", "ana", "normal", 1.0), post("n2", "ana", "normal", 0.8),
                                                                        post("n3", "ana", "normal", 1.3)]
    top, control = select(posts)
    assert top == ["v0", "v1", "v2", "v3", "v4"] and control == []
    monkeypatch.setenv("CONTENT_CONTROL_REELS", "2")
    assert select(posts)[1] == ["n1", "n2"]  # los más cercanos a ×1


def test_clip_keeps_video_and_audio_first_seconds(tmp_path):
    make_mp4(tmp_path / "v.mp4", seconds=40)
    assert clip_video(str(tmp_path / "v.mp4"), str(tmp_path / "c.mp4"), 30) == 30
    with av.open(str(tmp_path / "c.mp4")) as clip:
        assert sorted(s.type for s in clip.streams) == ["audio", "video"] and clip.duration / 1e6 <= 30.5


class FakeAnalyzer:
    model = "fake-gemini"

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def analyze(self, clip):
        self.calls.append(len(clip))
        if self.fail:
            raise RuntimeError("503 UNAVAILABLE")
        return ContentFeatures(**features())


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_failed_analysis_is_left_empty_and_not_retried(db, tmp_path):
    make_mp4(tmp_path / "v.mp4", seconds=35)
    content = (tmp_path / "v.mp4").read_bytes()
    posts = [reel(db, "A1", cdn_url("ok")), reel(db, "OLD", cdn_url("ok", datetime.now(timezone.utc) - timedelta(hours=1)))]

    async def run(analyzer):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
            return await analyze_posts(db, posts, analyzer, client)

    assert asyncio.run(run(FakeAnalyzer(fail=True))) == 2
    db.expire_all()
    assert db.get(PostContentAnalysis, ("instagram", "A1")).status == "error" and db.get(PostContentAnalysis, ("instagram", "OLD")).status == "expired"
    # El fallido queda vacío: otra consulta no lo reintenta.
    fake = FakeAnalyzer()
    assert asyncio.run(run(fake)) == 0 and fake.calls == []
    posts.append(reel(db, "A2", cdn_url("ok")))
    assert asyncio.run(run(fake)) == 1 and len(fake.calls) == 1
    db.expire_all()
    row = db.get(PostContentAnalysis, ("instagram", "A2"))
    assert row.status == "ok" and row.seconds == 10 and row.features["formato"] == "persona_a_camara"
    assert asyncio.run(run(fake)) == 0
    # Con otro modelo, el análisis guardado queda desactualizado y se rehace (el fallido sigue vacío).
    other = FakeAnalyzer()
    other.model = "fake-gemini-2"
    assert asyncio.run(run(other)) == 1 and len(other.calls) == 1


def test_cancelled_request_releases_its_claims(db, tmp_path):
    make_mp4(tmp_path / "v.mp4", seconds=5)
    content = (tmp_path / "v.mp4").read_bytes()
    posts = [reel(db, "C1", cdn_url("ok")), reel(db, "C2", cdn_url("ok"))]

    class Hanging(FakeAnalyzer):
        async def analyze(self, clip):
            await asyncio.sleep(60)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
            task = asyncio.create_task(analyze_posts(db, posts, Hanging(), client))
            await asyncio.sleep(0.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    db.expire_all()
    assert [db.get(PostContentAnalysis, ("instagram", c)).status for c in ("C1", "C2")] == [None, None]
