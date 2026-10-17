"""Local, evidence-backed interpretation. No network or model calls.

Concepts help organize explicit wording across sectors. Unsupported concepts are
left unknown; editorial ideas and audiences are proposals, never performance facts.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata

from .profile_common import clean_text
from .schemas import (
    AudienceHypothesis, ContentPillar, Identity, InterpretationEvidence,
    InterpretationFact, Persona, ProfileInterpretation,
)
from .services import draft_identity

VERSION = "2.0"


def normalized(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def has(text, expressions):
    value = normalized(text)
    return any(re.search(r"(?<!\w)" + re.escape(normalized(term)) + r"(?!\w)", value) for term in expressions)


# Concepts are labels for explicit text, not a classifier of the business itself.
CONCEPTS = {
    "helados": ("helado", "helados", "heladería", "heladerías", "ice cream"),
    "postres": ("postre", "postres", "crepe", "crepes", "pastelería", "tortas", "repostería"),
    "gastronomía": ("restaurante", "restaurantes", "gastronomía", "menú", "comida"),
    "café": ("cafetería", "café de especialidad", "coffee", "café"),
    "moda": ("ropa", "moda", "vestuario", "prendas", "outfits"),
    "moda vintage": ("vintage", "segunda mano", "ropa usada", "thrift"),
    "belleza y cuidado": ("maquillaje", "cosmética", "skincare", "peluquería", "cuidado facial"),
    "actividad física": ("gimnasio", "entrenamiento", "fitness", "ejercicio"),
    "viajes": ("viajes", "turismo", "hotel", "hospedaje"),
    "hogar y decoración": ("decoración", "muebles", "diseño de interiores"),
    "plantas y flores": ("plantas", "floristería", "flores", "jardinería"),
    "mascotas": ("mascotas", "veterinaria", "alimento para perros"),
    "inmuebles": ("inmuebles", "inmobiliaria", "apartamentos", "venta de casas"),
    "agentes de IA": ("agentes", "agents", "agente de ia", "ai agent"),
    "automatización": ("automatización", "automation", "automatizar"),
    "inteligencia artificial": ("inteligencia artificial", "ia", "ai"),
    "IA en negocios": ("ia en empresas", "ia para empresas", "ai for business"),
    "productividad": ("productividad", "productivity"),
    "emprendimiento": ("emprendimiento", "emprendedores", "startup", "startups"),
    "marketing": ("marketing", "publicidad", "posicionamiento"),
    "programación": ("programación", "coding", "software", "desarrollo web"),
    "educación": ("educación", "aprendizaje", "education", "enseñamos", "cursos"),
    "finanzas": ("finanzas", "financiero", "finance", "contabilidad"),
}
RELATED = (
    {"helados", "postres", "gastronomía", "café"},
    {"moda", "moda vintage"},
    {"agentes de IA", "automatización", "inteligencia artificial", "IA en negocios", "productividad", "programación"},
)

# Editorial intentions work across sectors. Match evidence before proposing them.
INTENTS = {
    "experiencia del lugar": (("visítanos", "visitanos", "ambiente", "instagrameable", "nuestro local", "nuestras sedes"), "Mostrar qué puede esperar una persona al visitar el lugar y cerrar con una invitación concreta.", "Visitas o consultas sobre cómo llegar, registradas por el equipo."),
    "planes para compartir": (("compartir", "juntos", "amigos", "familia", "pareja", "personas favoritas", "conexión"), "Proponer una ocasión para compartir vinculada a la oferta de la marca y preguntar con quién la disfrutarían.", "Respuestas sobre la ocasión propuesta y consultas atribuibles a la pieza."),
    "historia de la marca": (("nuestra historia", "la historia", "tradición", "todo comenzó", "nació de", "nuestros inicios"), "Contar un momento de la historia de la marca que esté documentado y conectarlo con su propuesta actual.", "Preguntas sobre la marca y respuestas al relato; no asumir intención de compra."),
    "pedidos y domicilios": (("domicilios", "delivery", "pedidos", "pide", "envíos", "envío", "a domicilio"), "Explicar cómo realizar un pedido, indicando que horarios, cobertura y condiciones deben confirmarse con la marca.", "Consultas y pedidos atribuidos al enlace o código de la publicación."),
    "aprendizaje práctico": (("aprende", "aprender", "tutorial", "paso a paso", "cómo usar", "guía", "enseñamos"), "Resolver una pregunta concreta con un ejemplo verificable y proponer que la audiencia lo pruebe.", "Preguntas resueltas y resultados de la prueba reportados por la audiencia."),
    "proceso y elaboración": (("preparamos", "elaboración", "preparación", "detrás de", "hecho a mano", "fabricamos", "ingredientes"), "Mostrar una etapa del proceso real y explicar una decisión, sin atribuir cualidades que no estén verificadas.", "Preguntas sobre el proceso y consultas sobre el producto mostrado."),
}


@dataclass
class Document:
    text: str
    kind: str
    url: str | None

    def evidence(self, expressions=()):
        # Quote a short matching sentence, rather than the whole caption or title.
        parts = re.split(r"[\n.!?]+", self.text)
        snippet = next((p.strip() for p in parts if p.strip() and has(p, expressions)), self.text)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        return InterpretationEvidence(source_url=self.url, source_kind=self.kind, excerpt=snippet[:240])


def documents(brief, profiles):
    result, seen, references = [], set(), []

    def add(text, kind, url=None):
        text = clean_text(text).strip()
        key = re.sub(r"\W+", " ", normalized(text)).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(Document(text, kind, url))

    add(brief.description, "brief")
    for p in profiles:
        if p.status == "ready" and p.usable_for_identity:
            if p.description.strip() or any((post.title + post.text).strip() for post in p.content_sample):
                references.append(p.url)
            add(p.description, "profile", p.url)
            for post in p.content_sample:
                # A caption frequently appears both as title (prefix) and body.
                title, body = clean_text(post.title), clean_text(post.text)
                if not title or normalized(title) in normalized(body):
                    text = body
                elif not body or normalized(body) in normalized(title):
                    text = title
                else:
                    text = title + "\n" + body
                add(text, "post", post.url)
        add(p.supplied_description, "manual", p.url)
    return result, list(dict.fromkeys(references))


def evidence_for(docs, expressions):
    matched = [doc for doc in docs if has(doc.text, expressions)]
    return matched, [doc.evidence(expressions) for doc in matched[:3]]


def location_signals(docs):
    # Restrict to service/location statements, not arbitrary mentions in viral posts.
    names = {}
    for doc in docs:
        for match in re.finditer(r"(?i:domicilios|delivery|ubicad[oa]s? en|visítanos en|visitanos en|sede en)\s*[:|\-]?\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:[ \t]+(?:de|del|[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)){0,3})", doc.text):
            city = match.group(1).strip()
            if normalized(city).startswith(("calle", "carrera", "cra", "barrio", "sede", "nuestro", "nuestra")):
                continue
            names.setdefault(normalized(city), (city, []))[1].append(doc)
    eligible = [(city, matches) for city, matches in names.values() if any(d.kind in {"profile", "brief", "manual"} for d in matches) or len({d.url for d in matches}) >= 2]
    return eligible


def interpret(brief, profiles):
    docs, references = documents(brief, profiles)
    identity = draft_identity(brief)
    facts, pillars, hypotheses, limitations = [], [], [], []
    concepts = []
    for label, expressions in CONCEPTS.items():
        matches, evidence = evidence_for(docs, expressions)
        if matches:
            # An isolated unrelated post should not redefine what a brand offers.
            anchored = any(d.kind in {"profile", "brief", "manual"} for d in matches) or len(matches) >= 2
            concepts.append((label, matches, evidence, anchored))
    core = {c[0] for c in concepts if c[3]}
    anchored = [c for c in concepts if c[3] or any(c[0] in family and core & family for family in RELATED)]
    if anchored:
        labels = [c[0] for c in anchored[:4]]
        evidence = [c[2][0] for c in anchored[:3]]
        facts.append(InterpretationFact(label="Oferta o temas comunicados", value=", ".join(labels), evidence=evidence))
        pillars.append(ContentPillar(topic=" y ".join(labels[:2]), rationale="Hay menciones explícitas en el brief, la biografía, varias piezas o una pieza relacionada con la oferta identificada.", idea=f"Mostrar un ejemplo concreto de {labels[0]} presente en la muestra y explicar qué ofrece; cerrar con una pregunta o una acción que pueda medirse.", measurement="Consultas o acciones atribuidas a la pieza, medidas en una prueba nueva.", evidence=evidence))
    for label, (expressions, idea, measure) in INTENTS.items():
        matches, evidence = evidence_for(docs, expressions)
        if matches:
            pillars.append(ContentPillar(topic=label, rationale="Intención editorial identificada en el texto disponible; no prueba que este contenido rinda mejor.", idea=idea, measurement=measure, evidence=evidence))
    if not pillars and docs:
        evidence = [docs[0].evidence()]
        pillars.append(ContentPillar(topic="propuesta de valor", rationale="El texto no coincide con conceptos específicos del vocabulario actual. Se conserva la evidencia para revisión.", idea="Explicar qué ofrece la marca, a quién busca ayudar y qué acción espera del visitante; validar esas respuestas con el equipo.", measurement="Consultas que permitan comprobar si se entendió la propuesta.", evidence=evidence))
        limitations.append("No se identificó un sector con evidencia suficiente en el vocabulario actual; requiere revisión del equipo.")
    locations = location_signals(docs)
    local_focus = " / ".join(city for city, _ in locations)[:100] or None
    if local_focus:
        geo_evidence = [matches[0].evidence((city,)) for city, matches in locations[:3]]
        facts.append(InterpretationFact(label="Foco local comunicado", value=local_focus, evidence=geo_evidence))
        if normalized(brief.region) in {"latinoamerica", "latam", "america latina"}:
            identity.region = local_focus
            limitations.append("El foco local proviene del texto de la marca; confirmar cobertura y conservar una región más amplia si corresponde.")
        elif normalized(brief.region) != normalized(local_focus):
            limitations.append(f"Se conserva la región declarada ({brief.region}); el texto también comunica {local_focus}. Confirmar el alcance real.")

    by_topic = {p.topic: p for p in pillars}
    if "planes para compartir" in by_topic:
        p = by_topic["planes para compartir"]
        hypotheses.append(AudienceHypothesis(role="Personas que buscan planes para compartir", need="Encontrar una ocasión y una oferta adecuada para disfrutar con otras personas.", evidence=p.evidence))
    if "pedidos y domicilios" in by_topic:
        p = by_topic["pedidos y domicilios"]
        hypotheses.append(AudienceHypothesis(role="Personas interesadas en pedir a domicilio", need="Conocer productos, cobertura y pasos para hacer un pedido.", evidence=p.evidence))
    if "aprendizaje práctico" in by_topic:
        p = by_topic["aprendizaje práctico"]
        hypotheses.append(AudienceHypothesis(role="Personas que buscan aprender mediante ejemplos", need="Resolver una tarea concreta y comprobar si el ejemplo les sirve.", evidence=p.evidence))
    if not hypotheses and anchored:
        hypotheses.append(AudienceHypothesis(role=("Personas interesadas en " + anchored[0][0])[:120], need="Comprender la oferta y evaluar si responde a una necesidad propia.", evidence=anchored[0][2]))
    if docs:
        offering = " y ".join(c[0] for c in anchored[:2])
        if offering:
            summary = f"La comunicación de {brief.name} se centra en {offering}."
        elif brief.description:
            # One cleaned statement instead of concatenated captions; no superlatives.
            statement = re.split(r"[\n.!?]", clean_text(brief.description))[0].strip()
            summary = f"Propuesta declarada de {brief.name}: {statement[:300]}."
        else:
            summary = f"La propuesta de {brief.name} requiere revisión a partir de los textos disponibles."
        if local_focus:
            summary += f" El perfil comunica un foco local en {local_focus}."
        intentions = [p.topic for p in pillars if p.topic in INTENTS][:3]
        if intentions:
            summary += " Sus textos destacan " + ", ".join(intentions) + "."
        if "pedidos y domicilios" in by_topic:
            summary += " También comunica un servicio de pedidos o domicilios."
        identity.summary = summary
        topic_candidates = [c[0] for c in anchored] + [p.topic for p in pillars] + brief.topics
        unique_topics = {}
        for topic in topic_candidates:
            if topic:
                unique_topics.setdefault(normalized(topic), topic.lower())
        identity.topics = list(unique_topics.values())[:15] or ["por definir"]
        identity.method = "profile_rules" if references else "brief_rules"
        if not brief.audience and hypotheses:
            identity.audience = "Por validar: " + "; ".join(h.role for h in hypotheses[:3])
        if hypotheses:
            identity.personas = [Persona(role=h.role, need=("Hipótesis por validar: " + h.need)[:500]) for h in hypotheses[:3]]

    eligible_profiles = [p for p in profiles if p.status == "ready" and p.usable_for_identity]
    samples = {c.url: c for p in eligible_profiles for c in p.content_sample}
    coverage = {"usable_profiles": len(eligible_profiles), "unique_texts": len(docs), "sample_size": len(samples), "pieces_with_views": sum(c.views is not None for c in samples.values()), "pieces_with_known_format": sum(c.format != "unknown" for c in samples.values())}
    if profiles and not eligible_profiles:
        limitations.append("No hay textos de proveedores habilitados para interpretar; solo puede usarse el contexto aportado por el equipo.")
    if samples and coverage["pieces_with_views"] < len(samples):
        limitations.append(f"Solo {coverage['pieces_with_views']} de {len(samples)} piezas tienen vistas disponibles; no se clasifican contenidos por rendimiento ni se afirma qué formato funciona mejor.")
    if samples and coverage["pieces_with_known_format"] < len(samples):
        limitations.append(f"Solo {coverage['pieces_with_known_format']} de {len(samples)} piezas tienen formato conocido; no se deducen los formatos ausentes del texto ni del enlace.")
    limitations.extend(["Las audiencias propuestas son hipótesis editoriales, sin evidencia demográfica ni datos de compradores.", "La muestra no representa todo el perfil ni demuestra crecimiento, causalidad o saturación. Las ideas requieren un experimento nuevo.", "Interpretación local por reglas y evidencia textual. El vocabulario es ampliable y puede omitir matices; no se ejecuta un modelo de IA."])
    detail = ProfileInterpretation(version=VERSION, local_focus=local_focus, facts=facts, pillars=pillars[:6], audience_hypotheses=hypotheses, coverage=coverage, limitations=limitations)
    opportunities = []
    for p in profiles:
        if p.status != "ready" or not p.usable_for_identity:
            opportunities.append({"platform": p.platform, "action": p.message if p.status != "ready" else "Esta fuente no está habilitada para alimentar la interpretación.", "basis": "Disponibilidad y condiciones de uso de la fuente."})
            continue
        own = [pillar for pillar in detail.pillars if any(e.source_url == p.url or any(e.source_url == c.url for c in p.content_sample) for e in pillar.evidence)]
        for pillar in (own or detail.pillars)[:3]:
            opportunities.append({"platform": p.platform, "action": pillar.idea, "basis": f"Pilar propuesto: {pillar.topic}. " + pillar.rationale})
    return {"suggested_identity": Identity.model_validate(identity.model_dump()).model_dump(mode="json"), "identity_evidence": references, "interpretation": detail.model_dump(mode="json"), "interpreted_at": datetime.now(timezone.utc).isoformat(), "opportunities": opportunities, "method": "Interpretación v2: síntesis local, textos deduplicados, conceptos e intenciones con referencias. Audiencias e ideas por validar; los contadores no se convierten en conclusiones de rendimiento."}
