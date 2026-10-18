"""Local, evidence-backed interpretation. No network or model calls.

Concepts help organize explicit wording across sectors. Unsupported concepts are
left unknown; editorial ideas and audiences are proposals, never performance facts.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata
from statistics import median

from .profile_common import clean_text
from .schemas import (
    AudienceHypothesis, ContentPillar, Identity, InterpretationEvidence,
    InterpretationFact, Persona, ProfileInterpretation,
)
from .services import draft_identity

VERSION = "3.1"


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
    "series y animación": ("series", "animación", "anime", "gravity falls", "caricaturas", "cartoons"),
    "videojuegos": ("videojuegos", "gaming", "gameplay", "gamers"),
    "música": ("música", "canciones", "conciertos", "music"),
    "deportes": ("deportes", "fútbol", "baloncesto", "sports"),
}
RELATED = (
    {"helados", "postres", "gastronomía", "café"},
    {"moda", "moda vintage"},
    {"agentes de IA", "automatización", "inteligencia artificial", "IA en negocios", "productividad", "programación"},
)

# Editorial intentions work across sectors. Match evidence before proposing them.
INTENTS = {
    "experiencia del lugar": (("visítanos", "visitanos", "ambiente", "instagrameable", "nuestro local", "nuestras sedes"), "Mostrar qué puede esperar una persona al visitar el lugar y cerrar con una invitación concreta.", "Visitas o consultas sobre cómo llegar, registradas por el equipo."),
    "planes para compartir": (("planes para compartir", "experiencia para compartir", "para compartir juntos", "para compartir con tus personas favoritas", "plan en familia", "planes en familia", "plan en pareja", "planes en pareja", "plan con amigos", "planes con amigos", "disfrutar en familia", "disfrutar con amigos", "salir con amigos", "celebrar en familia"), "Proponer una ocasión para compartir vinculada a la oferta de la marca y preguntar con quién la disfrutarían.", "Respuestas sobre la ocasión propuesta y consultas atribuibles a la pieza."),
    "historia de la marca": (("nuestra historia", "nuestros inicios", "historia de nuestra marca", "historia de nuestra empresa", "historia de nuestro negocio", "fundamos nuestra", "fundamos nuestro", "así nació nuestra marca", "así nació nuestro negocio"), "Contar un momento de la historia de la marca que esté documentado y conectarlo con su propuesta actual.", "Preguntas sobre la marca y respuestas al relato; no asumir intención de compra."),
    "pedidos y domicilios": (("domicilios", "delivery", "pedidos", "pide", "envíos", "envío", "a domicilio"), "Explicar cómo realizar un pedido, indicando que horarios, cobertura y condiciones deben confirmarse con la marca.", "Consultas y pedidos atribuidos al enlace o código de la publicación."),
    "aprendizaje práctico": (("aprende", "aprender", "tutorial", "paso a paso", "cómo usar", "guía", "enseñamos"), "Resolver una pregunta concreta con un ejemplo verificable y proponer que la audiencia lo pruebe.", "Preguntas resueltas y resultados de la prueba reportados por la audiencia."),
    "proceso y elaboración": (("preparamos", "elaboración", "preparación", "detrás de", "hecho a mano", "fabricamos", "ingredientes"), "Mostrar una etapa del proceso real y explicar una decisión, sin atribuir cualidades que no estén verificadas.", "Preguntas sobre el proceso y consultas sobre el producto mostrado."),
    "conversación con la comunidad": (("sígueme", "siguiéndome", "seguirnos", "comunidad", "fans", "fandom", "qué opinas", "teorías"), "Proponer una pregunta sobre un tema ya presente en la cuenta y dar una razón concreta para volver.", "Respuestas que desarrollan la conversación y seguimiento de la cuenta en una prueba nueva."),
}
# These describe editorial angles, not what the business offers. Only an explicit
# team topic can promote them to the brand's search topics.
EDITORIAL_ANGLES = {"planes para compartir", "historia de la marca"}


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
    # Declared audience is context, never evidence of actual follower demographics.
    add(brief.audience, "brief")
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


def build_audiences(brief, docs, pillars, anchored):
    """Segments describe jobs and editorial experiments, not inferred demographics."""
    result = []
    offering = " y ".join(c[0] for c in anchored[:2])

    def add(role, need, goal, barriers, angles, question, evidence, basis="textual"):
        if evidence and not any(normalized(h.role) == normalized(role) for h in result):
            result.append(AudienceHypothesis(role=role[:120], need=need[:500], goal=goal,
                barriers=barriers, content_angles=angles, validation_question=question,
                evidence=evidence[:3], basis=basis))

    # Explicit franchises produce a specific segment; their presence does not prove
    # interests of followers, ages, purchasing power or where they live.
    entertainment = {"series y animación", "videojuegos", "música", "deportes"}
    fandoms = [(topic.title(), (topic,)) for topic in brief.topics
        if normalized(topic) not in {normalized(t) for t in CONCEPTS}
        and any(c[0] in entertainment for c in anchored)]
    for name, terms in fandoms:
        matches, evidence = evidence_for(docs, terms)
        if matches and (any(d.kind != "post" for d in matches) or len(matches) >= 2):
            add(f"Fans de {name}", f"Explorar y conversar sobre contenido, referencias y detalles de {name}.",
                "Encontrar una perspectiva que aporte a un tema que ya conocen.",
                ["Las ideas repetidas o sin una referencia clara pueden no aportar valor."],
                [f"Un detalle de {name} con una referencia verificable y una pregunta abierta.", "Comparar dos interpretaciones y distinguir hechos de teorías."],
                "¿Qué referencias, detalles o conversaciones les interesan más?", evidence,
                "declared" if all(e.source_kind in {"brief", "manual"} for e in evidence) else "textual")
    if brief.audience and not any(h.role.startswith("Fans de ") for h in result):
        text = clean_text(brief.audience)
        add(text, f"Encontrar contenido relevante sobre {offering or 'la propuesta declarada de la cuenta'} y decidir si seguir explorando.",
            "Reconocer rápidamente si la cuenta responde a sus intereses.",
            ["La promesa del perfil puede no explicar qué encontrarán al seguirlo."],
            [f"Una pieza de bienvenida que explique la propuesta de {brief.name} con un ejemplo.", "Una pregunta para priorizar los intereses de este segmento."],
            "¿Qué esperaban encontrar aquí y qué tema les haría volver?",
            [Document(text, "brief", None).evidence()], "declared")
    by_topic = {p.topic: p for p in pillars}
    templates = {
        "planes para compartir": ("Personas que buscan planes para compartir", "Encontrar una ocasión y una oferta adecuada para disfrutar con otras personas.", "Elegir un plan con información útil para organizarlo.", "La pieza puede no resolver qué incluye el plan o cómo realizarlo.", "Mostrar una ocasión concreta, qué ofrece la marca y cómo consultarlo.", "¿Qué información necesitan antes de proponer este plan a alguien?"),
        "pedidos y domicilios": ("Personas interesadas en pedir a domicilio", "Conocer productos, cobertura y pasos para hacer un pedido.", "Resolver un pedido sin dudas sobre el proceso.", "Cobertura, condiciones o pasos de compra poco claros.", "Explicar el recorrido de un pedido con condiciones verificadas por la marca.", "¿Qué duda les impide completar un pedido?"),
        "aprendizaje práctico": ("Personas que buscan aprender mediante ejemplos", "Resolver una tarea concreta y comprobar si el ejemplo les sirve.", "Aplicar una explicación a una situación propia.", "Ejemplos sin contexto o con pasos que no se pueden reproducir.", "Un tutorial corto con requisitos, pasos y resultado verificable.", "¿Qué paso no pudieron aplicar y en qué contexto lo intentaron?"),
    }
    for topic, values in templates.items():
        if topic in by_topic:
            role, need, goal, barrier, angle, question = values
            add(role, need, goal, [barrier], [angle], question, by_topic[topic].evidence)
    series = next((c for c in anchored if c[0] == "series y animación"), None)
    if series:
        add("Personas que buscan descubrir series de animación", "Evaluar si una serie encaja con sus gustos antes de dedicarle tiempo.",
            "Entender la premisa y qué la hace interesante sin spoilers no anunciados.",
            ["Spoilers sin aviso o referencias que requieren conocer toda la serie."],
            ["Una recomendación sin spoilers con una razón concreta para verla.", "Explicar una referencia para quien empieza a conocer la serie."],
            "¿Ya conocían la serie o la descubrieron a partir de esta pieza?", series[2], "exploratory")
    if not result and anchored:
        label, _, evidence, _ = anchored[0]
        add("Personas interesadas en " + label, f"Comprender la oferta de {label} y evaluar si responde a una necesidad propia.",
            "Comparar un ejemplo concreto con lo que están buscando.",
            ["Información demasiado general para decidir si les sirve."],
            [f"Responder una pregunta frecuente sobre {label} con un ejemplo real."],
            "¿Qué problema esperan resolver y qué información les falta?", evidence)
    if not result and "conversación con la comunidad" in by_topic:
        add("Visitantes que consideran seguir la cuenta", "Entender qué encontrarán y por qué les convendría volver.",
            "Reconocer una propuesta de contenido antes de seguir la cuenta.",
            ["La biografía pide apoyo, pero puede no describir el contenido."],
            ["Explicar qué publica la cuenta y mostrar un ejemplo representativo."],
            "¿Qué contenido esperan recibir al seguir la cuenta?",
            by_topic["conversación con la comunidad"].evidence, "exploratory")
    return result[:4]


def sample_snapshot(profiles):
    result = []
    for platform in dict.fromkeys(p.platform for p in profiles):
        samples = {c.url: c for p in profiles if p.platform == platform for c in p.content_sample}
        known = [c for c in samples.values() if c.views is not None]
        dates = []
        for c in samples.values():
            try:
                d = datetime.fromisoformat(c.published_at.replace("Z", "+00:00")) if c.published_at else None
                if d and d.tzinfo:
                    dates.append(d)
            except ValueError:
                pass
        result.append({"platform": platform, "sample_size": len(samples), "with_views": len(known),
            "median_views": median(c.views for c in known) if known else None,
            "formats": list(dict.fromkeys(c.format for c in samples.values() if c.format != "unknown")),
            "latest_published_at": max(dates).isoformat() if dates else None,
            "top_content": [{"url": c.url, "title": c.title or c.text[:100] or "Publicación de la muestra", "views": c.views}
                for c in sorted(known, key=lambda c: c.views, reverse=True)[:3]]})
    return result


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
        pillars.append(ContentPillar(topic=" y ".join(labels[:2]), rationale="Hay menciones explícitas en el brief, la biografía, varias piezas o una pieza relacionada con la oferta identificada.", idea=f"Mostrar un ejemplo concreto de {labels[0]} comunicado por la marca y explicar qué ofrece; cerrar con una pregunta o una acción que pueda medirse.", measurement="Consultas o acciones atribuidas a la pieza, medidas en una prueba nueva.", evidence=evidence))
    for label, (expressions, idea, measure) in INTENTS.items():
        if label == "historia de la marca":
            expressions = (*expressions, f"historia de {brief.name}", f"inicios de {brief.name}")
        matches, evidence = evidence_for(docs, expressions)
        if label in EDITORIAL_ANGLES and not (any(d.kind != "post" for d in matches) or len(matches) >= 2):
            continue
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
    hypotheses = build_audiences(brief, docs, pillars, anchored)
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
        topic_candidates = brief.topics + [c[0] for c in anchored] + [p.topic for p in pillars if p.topic not in EDITORIAL_ANGLES]
        unique_topics = {}
        for topic in topic_candidates:
            if topic:
                unique_topics.setdefault(normalized(topic), topic.lower())
        identity.topics = list(unique_topics.values())[:15] or ["por definir"]
        identity.method = "profile_rules" if references else "brief_rules"
        if not brief.audience and hypotheses:
            identity.audience = "Por validar: " + "; ".join(h.role for h in hypotheses[:3])
        if hypotheses:
            identity.personas = [Persona(**h.model_dump()) for h in hypotheses]

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
    missing, next_steps = [], []
    if not anchored:
        missing.append("Qué publica u ofrece la cuenta y qué la hace útil o distinta.")
    if not brief.audience:
        missing.append("A quién busca llegar la marca y qué necesidad quiere resolver.")
    if not samples:
        missing.append("Una muestra de publicaciones con descripción, fecha y métricas disponibles.")
        next_steps.append({"title": "Contrastar con publicaciones de la cuenta", "reason": "El contador de publicaciones no incluye sus textos ni demuestra sus resultados.", "action": "Compara estas propuestas con publicaciones públicas de la cuenta. Si ya hay piezas guardadas en Descubrimiento, revisa sus textos y resultados antes de validar las personas."})
    if not anchored or not brief.audience:
        next_steps.append({"title": "Precisar la propuesta y la audiencia", "reason": "Los seguidores y la biografía no describen por sí solos los intereses de la comunidad.", "action": "Completa el contexto de marca de esta pantalla y regenera las personas sin una nueva extracción."})
    next_steps.append({"title": "Validar las personas propuestas", "reason": "Son segmentos editoriales hipotéticos, no perfiles observados de seguidores.", "action": "Prueba una idea por segmento y registra las respuestas a su pregunta de validación antes de confirmar la identidad."})
    readiness = "text_supported" if any(h.basis != "exploratory" for h in hypotheses) else "exploratory" if hypotheses else "needs_context"
    detail = ProfileInterpretation(version=VERSION, local_focus=local_focus, facts=facts, pillars=pillars[:6], audience_hypotheses=hypotheses, coverage=coverage, limitations=limitations,
        audience_readiness=readiness, missing_context=missing, next_steps=next_steps, content_snapshot=sample_snapshot(eligible_profiles))
    opportunities = []
    for p in profiles:
        if p.status != "ready" or not p.usable_for_identity:
            opportunities.append({"platform": p.platform, "action": p.message if p.status != "ready" else "Esta fuente no está habilitada para alimentar la interpretación.", "basis": "Disponibilidad y condiciones de uso de la fuente."})
            continue
        own = [pillar for pillar in detail.pillars if any(e.source_url == p.url or any(e.source_url == c.url for c in p.content_sample) for e in pillar.evidence)]
        for pillar in (own or detail.pillars)[:3]:
            opportunities.append({"platform": p.platform, "action": pillar.idea, "basis": f"Pilar propuesto: {pillar.topic}. " + pillar.rationale})
    return {"suggested_identity": Identity.model_validate(identity.model_dump()).model_dump(mode="json"), "identity_evidence": references, "interpretation": detail.model_dump(mode="json"), "interpreted_at": datetime.now(timezone.utc).isoformat(), "opportunities": opportunities, "method": "Interpretación v3: reglas locales y evidencia textual. Personas con objetivo, barreras, ideas y validación. Contexto declarado separado de datos del proveedor; sin inferir demografía ni ejecutar modelos."}
