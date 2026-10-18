"""No provider calls. Synthetic text fixtures exercise evidence and uncertainty."""
from datetime import datetime, timezone
import json

import pytest

from app import main
from app.database import ProfileAnalysis, get_session
from app.interpretation import interpret, VERSION
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
    assert {"helados", "postres", "pedidos y domicilios"} <= set(identity["topics"])
    assert "planes para compartir" in {p["topic"] for p in detail["pillars"]}
    assert not {"planes para compartir", "historia de la marca"} & set(identity["topics"])
    assert "agentes de ia" not in identity["topics"]
    assert "cucharada" not in identity["summary"]  # Summary is not a caption dump.
    assert detail["local_focus"] == "Ibagué"
    assert detail["audience_hypotheses"]
    assert [p["need"] for p in identity["personas"]] == [p["need"] for p in detail["audience_hypotheses"]]
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


@pytest.mark.parametrize("description,posts", [
    ("Tienda de figuras de colección y decoración.", [
        "Comparte este video con amigos y familia. La historia de este personaje.",
        "Descubre la historia de los cómics. Comparte con tus amigos y crea una conexión.",
    ]),
    ("Creamos software y automatización para empresas.", [
        "Aprende a compartir archivos con tu equipo. Trabajamos juntos.",
        "La historia de internet y las familias de protocolos de conexión.",
    ]),
    ("Contenido sobre series de animación y teorías.", [
        "La historia de Dipper nació de una idea. Comparte con amigos.",
        "Una familia de personajes que viven juntos: la historia continúa.",
    ]),
])
def test_generic_story_and_share_words_do_not_create_business_angles(description, posts):
    out = interpret(brand(), [profile(description, posts)])
    unwanted = {"planes para compartir", "historia de la marca"}
    assert not unwanted & set(out["suggested_identity"]["topics"])
    assert not unwanted & {p["topic"] for p in out["interpretation"]["pillars"]}
    assert all(p["role"] != "Personas que buscan planes para compartir" for p in out["suggested_identity"]["personas"])


def test_editorial_angles_require_profile_context_or_repeated_explicit_posts():
    isolated = interpret(brand(), [profile("Vendemos ropa vintage.", ["Un plan en pareja para este fin de semana."])])
    assert "planes para compartir" not in {p["topic"] for p in isolated["interpretation"]["pillars"]}
    explicit = interpret(brand(), [profile("Nuestra historia como tienda de ropa vintage. Organizamos planes en familia.")])
    angles = {"planes para compartir", "historia de la marca"}
    assert angles <= {p["topic"] for p in explicit["interpretation"]["pillars"]}
    assert not angles & set(explicit["suggested_identity"]["topics"])
    repeated = interpret(brand(), [profile("Vendemos ropa vintage.", ["Organizamos un plan en pareja.", "Reserva otro plan en pareja para el viernes."])])
    assert "planes para compartir" in {p["topic"] for p in repeated["interpretation"]["pillars"]}


def test_explicit_team_topics_are_preserved_including_editorial_angles():
    brief = brand(topics=["historia de la marca", "planes para compartir", "coleccionables"])
    out = interpret(brief, [profile("Tienda de figuras y decoración.")])
    assert set(brief.topics) <= set(out["suggested_identity"]["topics"])


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
    assert data["profile_analysis"]["interpretation"]["version"] == VERSION
    assert "helados" in data["profile_analysis"]["suggested_identity"]["topics"]
    applied = client.post(path + "/profiles/interpret", json={"apply_to_identity": True}).json()
    assert applied["identity"]["status"] == "draft" and "helados" in applied["identity"]["topics"]


def test_interpretation_requires_saved_observations(client):
    data = client.post("/api/brands", json=brand().model_dump(mode="json")).json()
    assert client.post(f"/api/brands/{data['id']}/profiles/interpret", json={}).status_code == 409


def test_sparse_tiktok_bio_offers_exploratory_persona_without_invented_interests():
    p = profile("Me apoyarías siguiéndome. Me ayudan a llegar a los 10k.")
    p.platform = "tiktok"
    p.url = "https://www.tiktok.com/@fixture"
    p.metrics.followers, p.metrics.posts = 8106, 34
    result = interpret(BrandCreate(name="Fixture", profiles=[{"platform": "tiktok", "url": p.url}], brand_accounts_confirmed=True), [p])
    detail = result["interpretation"]
    assert detail["audience_readiness"] == "exploratory"
    assert len(detail["audience_hypotheses"]) == 1
    h = detail["audience_hypotheses"][0]
    assert h["basis"] == "exploratory" and h["goal"] and h["barriers"] and h["validation_question"]
    assert "series" not in json.dumps(h).lower()
    assert detail["content_snapshot"][0]["sample_size"] == 0
    assert detail["content_snapshot"][0]["median_views"] is None
    assert detail["missing_context"]


@pytest.mark.parametrize("franchise", ["Gravity Falls", "Serie Ficticia QA"])
def test_declared_entertainment_topics_create_specific_rich_personas(franchise):
    brief = BrandCreate(name="Comunidad QA", description=f"Publicamos contenido sobre la serie {franchise}.", audience=f"Personas interesadas en series y en {franchise}.", topics=["series y animación", franchise])
    result = interpret(brief, [profile("Me apoyarías siguiéndome.")])
    people = result["interpretation"]["audience_hypotheses"]
    assert any(franchise.casefold() in h["role"].casefold() for h in people)
    assert any(h["basis"] == "declared" for h in people)
    assert all(h["evidence"] and h["goal"] and h["barriers"] and h["content_angles"] and h["validation_question"] for h in people)
    assert all("age" not in h and "gender" not in h and "income" not in h for h in people)
    assert result["suggested_identity"]["personas"][0]["content_angles"]


def test_sample_summary_deduplicates_and_preserves_unknown_and_zero():
    p = profile("Una heladería.", ["Helados para compartir", "Preparamos helados", "Otro post"])
    p.content_sample[0].views = 0
    p.content_sample[1].views = 100
    duplicate = p.model_copy(deep=True)
    summary = interpret(brand(), [p, duplicate])["interpretation"]["content_snapshot"][0]
    assert summary["sample_size"] == 3 and summary["with_views"] == 2
    assert summary["median_views"] == 50
    assert summary["top_content"][0]["views"] == 100
    assert summary["formats"] == []


def test_context_update_reinterprets_without_collecting_or_changing_identity(client, monkeypatch):
    created = client.post("/api/brands", json=brand().model_dump(mode="json")).json()
    bid = created["id"]
    stream = main.app.dependency_overrides[get_session]()
    db = next(stream)
    saved = {"analyzed_at": "2026-10-01T12:00:00+00:00", "profiles": [profile("Me apoyarías siguiéndome.").model_dump(mode="json")]}
    try:
        db.add(ProfileAnalysis(brand_id=bid, data=saved))
        db.commit()
    finally:
        stream.close()
    async def forbidden(*args, **kwargs):
        pytest.fail("Saving declared context must not make provider calls")
    monkeypatch.setattr(main, "build_analysis", forbidden)
    identity = created["identity"] | {"status": "confirmed"}
    client.put(f"/api/brands/{bid}/identity", json=identity)
    context = {"description": "Contenido sobre la serie Gravity Falls. Contacto qa@example.org", "audience": "Personas interesadas en series y Gravity Falls", "topics": ["series y animación", "Gravity Falls"]}
    response = client.put(f"/api/brands/{bid}/context", json=context)
    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["status"] == "confirmed" and body["identity"]["summary"] == identity["summary"]
    assert "qa@example.org" not in json.dumps(body)
    assert body["profile_analysis"]["profiles"] == saved["profiles"]
    assert body["profile_analysis"]["analyzed_at"] == saved["analyzed_at"]
    assert body["profile_analysis"]["suggested_identity"]["personas"][0]["goal"]
    assert client.put(f"/api/brands/{bid}/context", json=context | {"description": "corta"}).status_code == 422
