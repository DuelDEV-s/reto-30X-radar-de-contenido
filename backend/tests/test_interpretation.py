"""No provider calls. Synthetic text fixtures exercise evidence and uncertainty."""
from datetime import datetime, timezone
import json

import pytest

from app import main
from app.database import ProfileAnalysis, get_session
from app.interpretation import interpret
from app.schemas import BrandCreate, ProfileContent, ProfileResult


def brand(**kwargs):
    return BrandCreate(name="Marca QA", description="Una marca con una propuesta por confirmar.", **kwargs)


def profile(description="", posts=(), usable=True):
    return ProfileResult(platform="instagram", url="https://instagram.com/marcaqa", status="ready", provider="fixture", message="Synthetic fixture", observed_at=datetime.now(timezone.utc), description=description, usable_for_identity=usable,
                         content_sample=[ProfileContent(url=f"https://instagram.com/p/fixture{i}", title=text[:120], text=text, format="unknown") for i, text in enumerate(posts)])


def sweet_profile():
    return profile("Domicilios Ibagué\nVisítanos en nuestras sedes.", [
        "La historia de nuestra heladería nació de un sueño: helados para compartir juntos.",
        "Tres postres y crepes para compartir con tus personas favoritas. Un lugar instagrameable.",
        "Conoce los ingredientes y la preparación de nuestros helados.",
    ])


def test_ice_cream_identity_is_concise_local_and_evidence_backed():
    brief = BrandCreate(name="Dulce QA", description="Vender helados y una experiencia para compartir.", topics=["comida", "dulces", "pasión"])
    out = interpret(brief, [sweet_profile()])
    identity, detail = out["suggested_identity"], out["interpretation"]
    assert len(identity["summary"]) < 700
    assert "Ibagué" in identity["summary"] and identity["region"] == "Ibagué"
    assert {"helados", "postres", "planes para compartir", "pedidos y domicilios"} <= set(identity["topics"])
    assert "agentes de ia" not in identity["topics"]
    assert "cucharada" not in identity["summary"]  # Summary is not a caption dump.
    assert detail["local_focus"] == "Ibagué"
    assert detail["audience_hypotheses"] and all(p["need"].startswith("Hipótesis por validar:") for p in identity["personas"])
    assert detail["coverage"]["pieces_with_views"] == 0 and detail["coverage"]["pieces_with_known_format"] == 0
    assert any("no se clasifican" in text for text in detail["limitations"])
    assert all(p["evidence"] and p["measurement"] for p in detail["pillars"])


def test_repeated_title_caption_and_cross_posted_text_count_once():
    value = profile("Somos una heladería con domicilios.", ["Nuestros helados para compartir", "Nuestros helados para compartir"])
    out = interpret(brand(), [value])
    assert out["interpretation"]["coverage"]["unique_texts"] == 3  # brief, bio, one caption
    assert out["suggested_identity"]["summary"].count("Nuestros helados") == 0


@pytest.mark.parametrize("description,expected", [
    ("Ropa vintage y prendas de segunda mano para elegir un outfit.", "moda vintage"),
    ("Enseñamos agentes de IA y automatización para empresas.", "automatización"),
    ("Floristería: flores y plantas para regalar.", "plantas y flores"),
    ("Diseño de interiores, muebles y decoración para tu hogar.", "hogar y decoración"),
])
def test_interpretation_supports_multiple_sectors(description, expected):
    out = interpret(brand(), [profile(description)])
    assert expected in out["suggested_identity"]["topics"]
    assert "helados" not in out["suggested_identity"]["topics"]


def test_one_off_topic_post_does_not_redefine_the_business():
    value = profile("Ropa vintage y prendas de segunda mano.", ["Probamos helados en vacaciones."])
    out = interpret(brand(), [value])
    assert "helados" not in out["suggested_identity"]["topics"]
    assert "moda vintage" in out["suggested_identity"]["topics"]


def test_non_usable_source_does_not_feed_identity_or_audience():
    out = interpret(brand(), [profile("Heladería con domicilios Ibagué", usable=False)])
    assert "helados" not in out["suggested_identity"]["topics"]
    assert out["identity_evidence"] == [] and out["interpretation"]["local_focus"] is None
    assert out["interpretation"]["audience_hypotheses"] == []


def test_profile_with_only_counts_does_not_claim_textual_identity_evidence():
    value = profile()
    value.metrics.followers = 10000
    out = interpret(brand(), [value])
    assert out["identity_evidence"] == []
    assert out["suggested_identity"]["method"] == "brief_rules"
    assert "10000" not in out["suggested_identity"]["summary"]


def test_declared_region_and_audience_are_preserved_with_conflicting_local_signal():
    value = brand(region="Colombia", audience="Equipos de compras empresariales")
    out = interpret(value, [sweet_profile()])
    assert out["suggested_identity"]["region"] == "Colombia"
    assert out["suggested_identity"]["audience"] == value.audience
    assert any("Se conserva la región declarada" in line for line in out["interpretation"]["limitations"])


def test_street_address_is_not_treated_as_city_and_single_travel_post_is_not_coverage():
    out = interpret(brand(), [profile("Visítanos en Calle 64", ["Visítanos en Bogotá durante este evento."])])
    assert out["interpretation"]["local_focus"] is None


def test_interpretation_evidence_is_grounded_and_contacts_are_redacted():
    text = "Vendemos helados. Escríbenos a test@example.org o +57 300 123 4567."
    out = interpret(brand(), [profile(text)])
    encoded = json.dumps(out)
    assert "test@example.org" not in encoded and "300 123 4567" not in encoded
    evidence = out["interpretation"]["facts"][0]["evidence"][0]
    assert evidence["excerpt"] in text and evidence["source_url"] == "https://instagram.com/marcaqa"


def test_unsupported_sector_is_explicit_and_does_not_invent_audience():
    out = interpret(brand(), [profile("Propuesta inusual sin vocabulario especializado reconocible.")])
    assert any("No se identificó un sector" in line for line in out["interpretation"]["limitations"])
    assert out["interpretation"]["audience_hypotheses"] == []


def test_saved_interpretation_never_fetches_and_preserves_confirmed_identity(client, monkeypatch):
    created = client.post("/api/brands", json=brand().model_dump(mode="json")).json()
    path = f"/api/brands/{created['id']}"
    # Seed a stored observation directly; fail on any call to the collectors.
    override = main.app.dependency_overrides[get_session]
    stream = override()
    db = next(stream)
    old_time = "2026-10-01T12:00:00+00:00"
    try:
        db.add(ProfileAnalysis(brand_id=created["id"], data={"analyzed_at": old_time, "status": "complete", "profiles": [sweet_profile().model_dump(mode="json")]}))
        db.commit()
    finally:
        stream.close()
    async def forbidden(*args, **kwargs):
        pytest.fail("Interpretation must never collect from providers")
    monkeypatch.setattr(main, "build_analysis", forbidden)
    confirmed = created["identity"] | {"status": "confirmed", "summary": "Identidad revisada y confirmada por el equipo."}
    client.put(path + "/identity", json=confirmed)
    revised = client.post(path + "/profiles/interpret", json={})
    assert revised.status_code == 200
    data = revised.json()
    assert data["identity"]["summary"] == confirmed["summary"] and data["identity"]["status"] == "confirmed"
    assert data["profile_analysis"]["analyzed_at"] == old_time  # Reinterpreting is not a fresh observation.
    assert data["profile_analysis"]["interpretation"]["version"] == "2.0"
    assert "helados" in data["profile_analysis"]["suggested_identity"]["topics"]
    applied = client.post(path + "/profiles/interpret", json={"apply_to_identity": True}).json()
    assert applied["identity"]["status"] == "draft" and "helados" in applied["identity"]["topics"]


def test_interpretation_requires_saved_observations(client):
    data = client.post("/api/brands", json=brand().model_dump(mode="json")).json()
    assert client.post(f"/api/brands/{data['id']}/profiles/interpret", json={}).status_code == 409
