import asyncio
import math
from array import array
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import av
import httpx
import openai
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import transcription
from app.database import Base, InstagramPost
from app.transcription import expires_at, extract_audio, progress, transcribe_posts, video_url


def make_mp4(path, seconds=45, audio=True):
    """MP4 con video negro y, si se pide, un tono AAC: lo mínimo para ejercitar la extracción."""
    with av.open(str(path), "w", format="mp4") as out:
        video = out.add_stream("mpeg4", rate=10)
        video.width, video.height, video.pix_fmt = 64, 64, "yuv420p"
        sound = out.add_stream("aac", rate=16000) if audio else None
        for i in range(seconds * 10):
            frame = av.VideoFrame(64, 64, "yuv420p")
            frame.pts = i
            for packet in video.encode(frame):
                out.mux(packet)
        if sound:
            chunk = 1024
            for start in range(0, 16000 * seconds, chunk):
                block = av.AudioFrame(format="fltp", layout="mono", samples=chunk)
                tone = array("f", (0.3 * math.sin(2 * math.pi * 440 * (start + i) / 16000) for i in range(chunk)))
                block.planes[0].update(tone.tobytes())
                block.sample_rate, block.pts, block.time_base = 16000, start, Fraction(1, 16000)
                for packet in sound.encode(block):
                    out.mux(packet)
            for packet in sound.encode(None):
                out.mux(packet)
        for packet in video.encode(None):
            out.mux(packet)


def cdn_url(name, expiry=None):
    expiry = expiry or datetime.now(timezone.utc) + timedelta(days=1)
    return f"https://cdn.example.com/{name}.mp4?oe={int(expiry.timestamp()):X}&_nc_ht=x"


class FakeTranscriber:
    model = "fake-transcribe"

    def __init__(self, text="Hoy les muestro cómo usar agentes de IA", error=None):
        self.text, self.error, self.calls = text, error, []

    async def transcribe(self, audio_path):
        with av.open(audio_path) as audio:
            self.calls.append(audio.duration / 1e6)
        if self.error:
            raise self.error
        return self.text


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def reel(db, code, url, content_type="reel"):
    post = InstagramPost(shortcode=code, username="ana", url=f"https://www.instagram.com/reel/{code}/", content_type=content_type,
                         hashtags=[], posted_at=datetime.now(timezone.utc) - timedelta(days=2), coauthors=[], tagged_users=[],
                         raw={"videos": [url]} if url else {})
    db.add(post)
    db.commit()
    return post


def test_expiry_and_video_url():
    when = datetime(2026, 10, 19, 12, 8, 39, tzinfo=timezone.utc)
    assert expires_at(f"https://cdn/x.mp4?oe={int(when.timestamp()):X}") == when
    assert expires_at("https://cdn/x.mp4") is None
    post = InstagramPost(raw={"post_content": [{"type": "Video", "url": "https://cdn/v.mp4"}]})
    assert video_url(post) == "https://cdn/v.mp4" and video_url(InstagramPost(raw={})) is None


def test_extract_audio_keeps_only_the_first_seconds(tmp_path):
    make_mp4(tmp_path / "long.mp4", seconds=45)
    seconds = extract_audio(str(tmp_path / "long.mp4"), str(tmp_path / "a.m4a"), 30)
    assert 29.5 <= seconds <= 30.1
    with av.open(str(tmp_path / "a.m4a")) as audio:
        assert [s.type for s in audio.streams] == ["audio"] and 29 <= audio.duration / 1e6 <= 30.5
    make_mp4(tmp_path / "short.mp4", seconds=8)
    assert 7 <= extract_audio(str(tmp_path / "short.mp4"), str(tmp_path / "b.m4a"), 30) <= 8.2
    make_mp4(tmp_path / "mute.mp4", seconds=3, audio=False)
    assert extract_audio(str(tmp_path / "mute.mp4"), str(tmp_path / "c.m4a"), 30) is None


def test_transcribe_posts_end_to_end(db, tmp_path):
    make_mp4(tmp_path / "v.mp4", seconds=40)
    make_mp4(tmp_path / "mute.mp4", seconds=3, audio=False)
    files = {"ok": (tmp_path / "v.mp4").read_bytes(), "mute": (tmp_path / "mute.mp4").read_bytes()}
    downloads = []

    def cdn(request):
        name = request.url.path.strip("/").removesuffix(".mp4")
        downloads.append(name)
        return httpx.Response(200, content=files[name]) if name in files else httpx.Response(403)

    posts = [reel(db, "OK1", cdn_url("ok")), reel(db, "MUTE", cdn_url("mute")), reel(db, "GONE", cdn_url("gone")),
             reel(db, "OLD", cdn_url("ok", datetime.now(timezone.utc) - timedelta(hours=1))), reel(db, "NOURL", None),
             reel(db, "IMG", cdn_url("ok"), content_type="image")]
    fake = FakeTranscriber()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(cdn)) as client:
            return await transcribe_posts(db, posts, fake, client)

    assert asyncio.run(run()) == 5
    db.expire_all()
    status = {p.shortcode: (p.transcript_status, p.transcript) for p in db.query(InstagramPost).all()}
    assert status == {"OK1": ("ok", fake.text), "MUTE": ("no_audio", None), "GONE": ("unavailable", None),
                      "OLD": ("expired", None), "NOURL": ("unavailable", None), "IMG": (None, None)}
    # Al modelo solo le llegan los primeros 30 s; el enlace vencido no se descarga.
    assert len(fake.calls) == 1 and fake.calls[0] <= 30.5 and "ok" in downloads and downloads.count("ok") == 1
    assert db.get(InstagramPost, "OK1").transcript_seconds <= 30.1 and db.get(InstagramPost, "OK1").transcript_model == "fake-transcribe"
    # Lo terminado no se repite.
    assert asyncio.run(run()) == 0
    summary = progress(db.query(InstagramPost).all())
    assert (summary["reels"], summary["done"], summary["pending"], summary["failed"]) == (5, 2, 0, 3)


def test_transient_provider_errors_leave_the_reel_pending(db, tmp_path):
    make_mp4(tmp_path / "v.mp4", seconds=5)
    content = (tmp_path / "v.mp4").read_bytes()
    post = reel(db, "R1", cdn_url("ok"))
    limited = openai.RateLimitError("cuota", response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")), body=None)

    async def run(transcriber):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))) as client:
            return await transcribe_posts(db, [post], transcriber, client)

    assert asyncio.run(run(FakeTranscriber(error=limited))) == 0
    db.expire_all()
    assert db.get(InstagramPost, "R1").transcript_status is None
    assert asyncio.run(run(FakeTranscriber())) == 1
    db.expire_all()
    assert db.get(InstagramPost, "R1").transcript_status == "ok"


def test_claim_prevents_double_processing(db):
    post = reel(db, "R2", cdn_url("ok"))
    assert transcription.claim(db, post) and not transcription.claim(db, post)
