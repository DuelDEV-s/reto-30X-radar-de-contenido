from datetime import datetime, timedelta, timezone

import httpx

from app.main import app, get_bright_data_client, get_media_client, get_post_reviewer, get_transcriber
from app.post_review import PostVerdict, wants_transcript
from app.database import InstagramPost, PostTopicReview
from tests.test_post_relevance import run_with_profiles  # noqa: F401  (fixture)
from tests.test_transcription import cdn_url, make_mp4


class FakePostReviewer:
    """Decide por palabras clave; con la transcripción, el reel ambiguo resulta ser del tema."""
    model, effort = "fake-review", "low"

    def __init__(self):
        self.calls = []

    async def review(self, topic, brand, post):
        self.calls.append((post["caption"][:12], bool(post["transcripcion_inicio"])))
        text = f"{post['caption']} {post['transcripcion_inicio'] or ''}".lower()
        if "agente" in text:
            return PostVerdict(relevance="alta", content_kind="educativo", subtopics=["agentes de IA para ventas"], needs_transcript=False, reason="Explica agentes.")
        if "comenta" in text:
            return PostVerdict(relevance="baja", content_kind="otro", subtopics=[], needs_transcript=True, reason="Solo una llamada a la acción.")
        return PostVerdict(relevance="ninguna", content_kind="noticia", subtopics=["sismo"], needs_transcript=False, reason="Habla de un temblor.")


class FakeTranscriber:
    model = "fake-transcribe"

    def __init__(self):
        self.calls = 0

    async def transcribe(self, audio_path):
        self.calls += 1
        return "Hoy te muestro un agente que responde a tus clientes"


def test_wants_transcript_only_for_relevant_or_undetermined_reels():
    reel = InstagramPost(content_type="reel", transcript_status=None)
    image = InstagramPost(content_type="image", transcript_status=None)
    review = lambda relevance, needs=False, used=False: PostTopicReview(relevance=relevance, needs_transcript=needs, used_transcript=used)
    assert wants_transcript(review("alta"), reel) and wants_transcript(review("baja", needs=True), reel)
    assert not wants_transcript(review("ninguna"), reel) and not wants_transcript(None, reel)
    assert not wants_transcript(review("alta"), image) and not wants_transcript(review("alta", used=True), reel)


def test_only_on_topic_reels_are_transcribed_and_then_reviewed_again(client, run_with_profiles, tmp_path):
    run_id, session = run_with_profiles
    client.post(f"/api/discovery-runs/{run_id}/profiles")
    make_mp4(tmp_path / "v.mp4", seconds=5)
    video = (tmp_path / "v.mp4").read_bytes()
    now = datetime.now(timezone.utc)
    base = {"user_posted": "ana", "discovery_input": {"url": "https://www.instagram.com/ana"}, "likes": 100, "num_comments": 5, "product_type": "clips"}
    captions = {"AGENTE": "Así funciona un agente de IA", "SISMO": "Temblor de 5.5 esta mañana", "CTA": "Comenta DINERO y te lo envío"}
    records = [{**base, "url": f"https://www.instagram.com/reel/{code}/", "description": caption, "videos": [cdn_url(code)],
                "date_posted": (now - timedelta(days=3)).isoformat()} for code, caption in captions.items()]
    downloads = []

    def bright(request):
        if request.url.path.endswith("/trigger"):
            return httpx.Response(200, json={"snapshot_id": "sd_posts"})
        if "/progress/" in request.url.path:
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json=records)

    def cdn(request):
        downloads.append(request.url.path.strip("/").removesuffix(".mp4"))
        return httpx.Response(200, content=video)

    async def bright_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(bright)) as http:
            yield http

    async def media_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cdn)) as http:
            yield http

    reviewer, transcriber = FakePostReviewer(), FakeTranscriber()
    app.dependency_overrides.update({get_bright_data_client: bright_client, get_media_client: media_client,
                                     get_post_reviewer: lambda: reviewer, get_transcriber: lambda: transcriber})
    client.post(f"/api/discovery-runs/{run_id}/posts")  # inicia la recolección
    client.get(f"/api/discovery-runs/{run_id}/posts")  # posts listos → revisa con caption → transcribe los relevantes
    data = client.get(f"/api/discovery-runs/{run_id}/posts").json()  # revisa de nuevo los transcritos

    # El reel del temblor no se descarga ni se transcribe; el del tema y el indeterminado sí.
    assert sorted(downloads) == ["AGENTE", "CTA"] and transcriber.calls == 2
    by_code = {p["shortcode"]: p for p in data["items"]}
    assert by_code["SISMO"]["topic_review"]["on_topic"] is False and by_code["SISMO"]["transcript_status"] is None
    # La transcripción reveló que el "comenta DINERO" hablaba de agentes.
    cta = by_code["CTA"]["topic_review"]
    assert cta["relevance"] == "alta" and cta["used_transcript"] and not cta["needs_transcript"]
    assert data["topic_review"]["on_topic"] == 2 and data["topic_review"]["off_topic"] == 1 and data["topic_review"]["pending"] == 0
    assert data["transcripts"]["reels"] == 2 and data["transcripts"]["done"] == 2
    # Nada cambió: otra consulta no vuelve a pagar revisiones ni transcripciones.
    calls = len(reviewer.calls)
    client.get(f"/api/discovery-runs/{run_id}/posts")
    assert len(reviewer.calls) == calls and transcriber.calls == 2
    assert ("Comenta DINE", True) in reviewer.calls and ("Temblor de 5", True) not in reviewer.calls
