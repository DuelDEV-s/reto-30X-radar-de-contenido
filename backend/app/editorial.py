"""Step 3: a read-only presentation contract over the two step-2 engines and v1 batches.

No HTTP client, job submission, model call, or database write belongs in this module.
Scores are run-local editorial priorities, never probabilities or global trend ranks.
"""
from collections import Counter
from datetime import datetime, timezone
import math
import re

from sqlalchemy import select

from . import discovery_store, topic_trends
from .database import DiscoveryRun, RunTopicMap, TrendBatch, TrendRun
from .media import preview, public_url
from .schemas import BatchCreate
from .services import analyze

NETWORKS = {"instagram": "Instagram", "tiktok": "TikTok", "linkedin": "LinkedIn", "youtube": "YouTube"}
STAGES = {"en_caliente": "En caliente", "emergente": "Emergente", "en_ascenso": "En ascenso", "consolidado": "Consolidado", "estable": "Estable", "saturado": "Saturado", "enfriandose": "En descenso", "insuficiente": "Por validar", "otros": "Otros", "emerging": "Emergente", "growing": "En ascenso", "peak": "En su pico", "saturated": "Saturado", "declining": "En descenso", "insufficient_data": "Por validar"}


def stamp(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def display_topic(value):
    return re.sub(r"\bia\b", "IA", value[:1].upper() + value[1:], flags=re.I)


def evidence(item, platform, *, demo=False):
    url = public_url(item.get("url", "")) if not demo else None
    metrics = item.get("metrics") or {}
    return {"id": str(item.get("item_id") or item.get("shortcode") or item.get("external_id") or item.get("url", "")),
            "url": url, "platform": platform, "title": item.get("title") or item.get("caption") or item.get("excerpt") or "Publicación de referencia",
            "excerpt": item.get("excerpt") or item.get("caption") or "", "author": item.get("author") or item.get("username"),
            "published_at": stamp(item.get("published_at") or item.get("posted_at")),
            "format": item.get("format") or item.get("content_type") or "unknown",
            "views": metrics.get("views", item.get("views")), "performance": item.get("performance", metrics.get("outlier")),
            "evidence_level": item.get("evidence_level", "demo" if demo else "public_snapshot"),
            "preview": preview(url or "", demo=demo)}


def source_summary(row, kind):
    networks = [row.platform] if kind == "creator" else row.platforms if kind == "trend" else sorted({p["platform"] for p in row.data.get("posts", [])})
    return {"id": f"{kind}:{row.id}", "kind": kind, "created_at": stamp(row.created_at), "networks": networks,
            "status": row.status if kind != "batch" else "completed",
            "label": (row.topic or "Creadores") if kind == "creator" else "Tendencias y oportunidades" if kind == "trend" else row.data.get("source", "Lote importado"),
            "demo": kind == "batch" and row.data.get("mode") == "demo", "progress": source_progress(row, kind)}


def source_progress(row, kind):
    """Stored pipeline state, not a live check or a claim that all reviews finished."""
    if kind == "batch":
        return {"stage": "imported", "ready": True, "label": "Lote disponible", "counts": {"posts": len(row.data.get("posts", []))},
                "description": "Observaciones del lote listas para consultar en el informe."}
    if kind == "trend":
        if row.report:
            return {"stage": "report", "ready": True, "label": "Informe guardado",
                    "counts": {"posts": len(row.report.get("items", [])), "topics": len(row.report.get("topics", []))},
                    "description": "El motor terminó y guardó temas, evidencia y propuestas."}
        label = {"failed": "Corrida fallida", "queued": "En cola", "running": "Análisis en curso"}.get(row.status, "Sin informe guardado")
        return {"stage": row.stage, "ready": False, "label": label,
                "counts": {}, "description": "Revisa el avance en Descubrimiento. Aquí solo se consulta el estado guardado."}
    counts = {"candidates": row.candidate_count, "results": row.result_count}
    if row.posts_state == "ready":
        return {"stage": "posts", "ready": True, "label": "Publicaciones guardadas", "counts": counts,
                "description": "El informe muestra las revisiones y líneas base disponibles. Puede haber análisis temático pendiente."}
    for key, label in (("posts", "Publicaciones"), ("profiles", "Perfiles"), ("search", "Búsqueda")):
        state = getattr(row, f"{key}_state")
        if state == "not_started":
            continue
        state_label = {"ready": "guardados", "pending": "en proceso", "requesting": "iniciando", "unknown": "sin confirmar", "failed": "con error"}.get(state, state)
        if key == "search" and state == "ready":
            state_label = "guardada"
        return {"stage": key, "ready": False, "label": f"{label}: {state_label}", "counts": counts,
                "description": "Continúa las etapas pendientes en Descubrimiento para completar el informe."}
    return {"stage": "search", "ready": False, "label": "Búsqueda fallida" if row.status == "failed" else "Búsqueda guardada", "counts": counts,
            "description": "Falta completar perfiles, publicaciones y revisión temática en Descubrimiento."}


def sources(db, brand_id):
    rows = []
    for model, kind in ((DiscoveryRun, "creator"), (TrendRun, "trend"), (TrendBatch, "batch")):
        for row in db.scalars(select(model).where(model.brand_id == brand_id).order_by(model.created_at.desc())):
            rows.append(source_summary(row, kind))
    return sorted(rows, key=lambda r: (r["demo"], -(datetime.fromisoformat(r["created_at"]).replace(tzinfo=timezone.utc).timestamp())))


def base(brand, source, identity):
    return {"schema_version": "editorial-v1", "source": source, "brand_name": brand.brief["name"], "identity": identity,
            "identity_changed": identity != brand.identity, "observed_at": source["created_at"],
            "topics": [], "patterns": [], "format_insights": [], "cost_usd": None, "audience_voice": [], "warnings": [], "counts": {"posts": 0, "creators": None, "topics": 0},
            "methodology": "La prioridad ordena oportunidades dentro de esta corrida. Es una regla editorial; no una probabilidad de éxito. La muestra no representa toda la red. Las explicaciones son hipótesis, no conclusiones causales."}


def plan(identity, label, format_, hook=None):
    label = display_topic(label)
    people = identity.get("personas") or []
    persona = people[0].get("role") if people else identity.get("audience", "la audiencia de la marca")
    need = people[0].get("need", "").rstrip(". ") if people else "resolver un problema concreto con una acción aplicable"
    region = identity.get("region", "su contexto")
    return {"persona": persona, "format": format_, "platform": None,
            "title": f"{label}: del interés a una decisión concreta",
            "hook": hook or f"¿Qué cambia en tu trabajo cuando aplicas {label.lower()}? Veámoslo con un caso.",
            "outline": [f"Abrir con una situación que reconozca {persona}.", f"Mostrar un caso de {label.lower()} situado en {region}, con pasos y límites claros.", f"Conectar el ejemplo con esta necesidad: {need}.", "Cerrar con una acción pequeña y una pregunta concreta para la audiencia."],
            "why_now": "Propuesta editorial para contrastar con la evidencia de esta muestra.",
            "measurement": "Comparar la pieza con las últimas publicaciones del mismo formato y cuenta; revisar retención y respuestas útiles cuando estén disponibles. Cambiar una sola variable en la siguiente prueba."}


def creator_report(db, brand, run, source):
    result = base(brand, source, run.identity)
    posts = discovery_store.posts_detail(db, run)
    _, _, _, rows, scores, _, reviews = discovery_store.scored(db, run)
    items = discovery_store.trend_inputs(rows, scores, reviews)
    labels = Counter(s for p in items for s in p["subtopics"])
    stored = db.get(RunTopicMap, run.id)
    # Exact labels are a transparent provisional fallback, never another LLM request.
    groups = stored.topics if stored else [{"name": s, "description": "Subtema de las revisiones guardadas; agrupación provisional.", "labels": [s]} for s in labels]
    reference = max((discovery_store.aware(p.observed_at) for p in rows), default=discovery_store.aware(run.created_at))
    trends = topic_trends.analyze(items, groups, reference, posts["window_days"], run.platform)
    result["observed_at"] = stamp(reference)
    result["counts"] = {"posts": len(items), "creators": len({p["username"] for p in items}), "topics": len(trends["topics"])}
    by_code = {p["shortcode"]: p for p in posts["items"]}
    for index, t in enumerate(trends["topics"]):
        traction = t["traction"] or 0
        # Bounded, explicit components; don't interpret log momentum as a percent.
        performance_score = min(1, math.log1p(traction) / math.log(4))
        momentum_score = max(0, min(1, ((t["momentum"] or 0) + 1) / 2))
        support_score = min(t["creators"] / 4, 1) * min(t["posts"] / 6, 1)
        priority = round(50 * performance_score + 25 * momentum_score + 25 * support_score)
        dominant = max(t["formats"], key=t["formats"].get) if any(t["formats"].values()) else "video"
        format_ = {"reel": "reel", "carousel": "carrusel", "image": "publicación visual", "video": "video"}.get(dominant, dominant)
        proposal = plan(run.identity, t["name"], format_)
        proposal["platform"] = run.platform
        proposal["why_now"] = f"En los últimos 7 días observados aparecen {t['recent_posts']} piezas, frente a {t['previous_posts']} en los 7 anteriores. Validar la señal antes de ampliar la producción."
        result["topics"].append({"id": f"creator-topic-{index}", "label": display_topic(t["name"]), "description": t["description"], "stage": STAGES.get(t["state"], t["state"]),
            "priority": priority, "confidence": "media" if t["posts"] >= 6 and t["creators"] >= 3 else "baja", "networks": [run.platform],
            "fit": f"El paso 2 encontró este subtema al revisar contenido sobre {posts['topic']}. Contrastar su utilidad para {run.identity.get('audience', 'la audiencia definida')} antes de publicarlo.",
            "why": [f"{t['posts']} piezas de {t['creators']} cuentas superan el filtro temático y tienen una línea base calculable.", f"Tracción de {traction:.2f}× frente al rendimiento habitual de sus creadores. Un valor de 1× equivale a esa base; el formato por sí solo no explica el resultado."],
            "signals": [{"label": "Tracción relativa", "value": traction, "unit": "×"}, {"label": "Piezas recientes", "value": t["recent_posts"], "unit": "piezas / 7 d"}, {"label": "Cuentas", "value": t["creators"], "unit": "cuentas"}],
            "series": [{"label": "Publicaciones en la muestra", "unit": "piezas", "platform": run.platform, "points": [{"date": stamp(c["week"]), "value": c["posts"]} for c in t["cells"]]}],
            "evidence": [evidence(by_code[e["shortcode"]], run.platform) for e in t["evidence"] if e["shortcode"] in by_code], "proposals": [proposal]})
    result["topics"].sort(key=lambda t: -t["priority"])
    result["methodology"] += " Creadores: 50 puntos por tracción logarítmica (tope 3×), 25 por momentum acotado entre −1 y 1 y 25 por soporte (4 cuentas y 6 piezas). Tracción y momentum conservan el método del paso 2."
    if posts["topic_review"]["pending"]:
        result["warnings"].append(f"Faltan {posts['topic_review']['pending']} revisiones de relevancia; las prioridades pueden cambiar.")
    if not stored:
        result["warnings"].append("Los subtemas se muestran por su etiqueta exacta: todavía no existe una agrupación semántica guardada.")
    elif stored.labels_digest != topic_trends.labels_digest(posts["topic"], labels):
        result["warnings"].append("La agrupación guardada es anterior a algunas revisiones. Los subtemas nuevos pueden no estar incluidos.")
    if run.posts_state != "ready":
        result["warnings"].append("La recolección de publicaciones aún no está completa. Este informe solo lee lo que ya está guardado.")
    if run.platform == "instagram":
        patterns = discovery_store.patterns_detail(db, run)
        result["patterns"] = [{"label": f"{p['trait']}: {p['value']}", "top": p["top"], "control": p["control"], "difference": p["lift"], "top_n": patterns["groups"]["top"], "control_n": patterns["groups"]["control"]} for p in patterns["patterns"][:6]]
        if not patterns["groups"]["control"]:
            result["warnings"].append("No hay grupo de control de producción analizado: no se atribuye el rendimiento al montaje o al gancho visual.")
    else:
        result["warnings"].append("TikTok: sin análisis audiovisual descargado. La preview oficial permite inspeccionar la pieza; no aporta métricas nuevas.")
    return result


def trend_report(brand, run, source):
    # TrendRun stores the engine's BrandIdentity, not the step-1 Identity schema.
    frozen = run.identity
    personas = [{"role": p["name"], "need": p["description"]} for p in frozen.get("personas", [])]
    identity = {"summary": frozen.get("description", ""), "audience": ", ".join(p["role"] for p in personas),
                "personas": personas, "region": ", ".join((frozen.get("markets") or {}).get("regions", [])),
                "topics": list(dict.fromkeys([frozen.get("general_topic", "")] + frozen.get("specific_topics", []))),
                "status": "draft", "method": "step_2_snapshot"}
    result = base(brand, source, identity)
    from .trend_runs import engine_identity, TrendRunError
    try:
        result["identity_changed"] = frozen != engine_identity(brand, run.platforms, run.window_days).model_dump(mode="json")
    except TrendRunError:
        result["identity_changed"] = True
    report = run.report
    if not report:
        result["warnings"] = ["Esta corrida aún no tiene un informe guardado. Revisa su avance en el paso 2."]
        return result
    result["observed_at"] = report["run"]["generated_at"]
    items = {i["item_id"]: i for i in report["items"] if i["platform"] in run.platforms}
    result["counts"] = {"posts": len(items), "creators": len({i.get("author") for i in items.values() if i.get("author")}), "topics": len(report["topics"])}
    result["warnings"] = list(report["data_quality"]["warnings"])
    if "linkedin" in run.platforms:
        result["warnings"].append("LinkedIn: publicaciones encontradas en un índice de búsqueda; no hay vistas ni engagement observados. El crecimiento describe esta muestra.")
    for t in report["topics"]:
        series, signals = [], []
        if "linkedin" in run.platforms:
            series.append({"label": "Publicaciones encontradas · LinkedIn", "unit": "piezas", "platform": "linkedin", "points": [{"date": p["week"], "value": p["posts"]} for p in t["linkedin"]["timeseries"]]})
            signals.append({"label": "LinkedIn · últimos 7 d", "value": t["linkedin"]["posts_7d"], "unit": "piezas"})
        if "youtube" in run.platforms:
            series.append({"label": "Atención relativa · YouTube", "unit": "índice de atención", "platform": "youtube", "points": [{"date": p["week"], "value": p["attention"]} for p in t["demand"]["timeseries"]]})
            signals.append({"label": "YouTube · rendimiento", "value": t["demand"]["median_outlier"], "unit": "× base del canal"})
        proposals = []
        evidence_ids = list(t["top_items"])
        for o in report["opportunities"]:
            if o["topic_id"] != t["topic_id"]:
                continue
            p = o["proposal"]
            if o["platform"] not in run.platforms:
                continue
            persona = next((p["name"] for p in frozen.get("personas", []) if p["id"] == o["persona"]), o["persona"])
            proposals.append({**plan(identity, t["label"], o["format"]), "persona": persona, "platform": o["platform"], "title": next(iter(p["title_options"]), t["label"]), "hook": p["hook"], "outline": p["outline"], "why_now": o["why_now"], "length": p["length"]})
            evidence_ids += o["evidence"]
        score = t["opportunity_score"]
        # Engine scores are in [0,1] (contract leaves range unconstrained).
        priority = round(max(0, min(100, score * 100)))
        result["topics"].append({"id": t["topic_id"], "label": t["label"], "description": ", ".join(t["entities"]), "stage": STAGES.get(t["stage"], t["stage"]),
            "priority": priority, "confidence": "alta" if t["confidence"] >= .75 else "media" if t["confidence"] >= .45 else "baja", "networks": run.platforms,
            "fit": f"El análisis vincula este tema con {', '.join(t['maps_to']) or 'los intereses de la marca'}. Audiencia: {identity['audience']}.",
            "why": t["why_it_works"], "signals": signals, "series": series,
            "evidence": [evidence(items[k], items[k]["platform"]) for k in dict.fromkeys(evidence_ids) if k in items],
            "proposals": proposals or [plan(identity, t["label"], "video explicativo")]})
    result["topics"].sort(key=lambda t: -t["priority"])
    result["audience_voice"] = report["audience_voice"]
    result["format_insights"] = [{"label": p["label"], "basis": "Patrón con apoyo en YouTube" if p["evidence"] == "youtube_lift" else "Uso observado en LinkedIn", "support": p["support"], "lift": p["lift"]} for p in report["patterns"]]
    result["cost_usd"] = round(sum(report["run"].get("cost_usd", {}).values()), 4) if report["run"].get("cost_usd") else None
    result["methodology"] += " Radar LinkedIn/YouTube: conserva opportunity_score del motor del paso 2, reescalado a 100. LinkedIn y YouTube usan series separadas con unidades distintas."
    return result


def batch_report(brand, row, source):
    result = base(brand, source, brand.identity)
    batch = BatchCreate.model_validate(row.data)
    # A frozen imported snapshot remains inspectable later; do not silently age all rows out.
    old = analyze(batch, brand.identity, window_days=36500, limit=100)
    result["warnings"] = old["limitations"]
    result["methodology"] += " " + old["methodology"]
    result["counts"] = {"posts": len(batch.posts), "creators": None, "topics": len(old["topics"])}
    result["observed_at"] = max((stamp(p.snapshots[-1].observed_at) for p in batch.posts), default=source["created_at"])
    for index, t in enumerate(old["topics"]):
        members = sorted((x.model_dump(mode="json") for x in batch.posts if x.topic == t["topic"]), key=lambda x: -x["snapshots"][-1]["views"])
        examples = [evidence({**x, "metrics": {"views": x["snapshots"][-1]["views"]}}, x["platform"], demo=source["demo"]) for x in members[:6]]
        series, proposals = [], []
        for platform in dict.fromkeys(x["platform"] for x in members):
            sample = next(x for x in members if x["platform"] == platform)
            proposal = plan(brand.identity, t["topic"], sample["format"], sample["hook"])
            proposal["platform"] = platform
            proposals.append(proposal)
            series.append({"label": f"Vistas acumuladas · referencia de {NETWORKS[platform]}", "unit": "vistas", "platform": platform,
                           "points": [{"date": s["observed_at"], "value": s["views"]} for s in sample["snapshots"]]})
        result["topics"].append({"id": f"batch-topic-{index}", "label": display_topic(t["topic"]), "description": "Serie de observaciones del lote importado.", "stage": t["stage"], "priority": t["score"], "confidence": t["confidence"],
            "networks": sorted({x.platform for x in batch.posts if x.topic == t["topic"]}), "fit": t["why_relevant"], "why": t["why_it_may_work"],
            "signals": [{"label": "Piezas", "value": t["sample_size"], "unit": "piezas"}, {"label": "Vistas por día", "value": t["views_per_day"], "unit": "vistas / día"}],
            "series": series, "evidence": examples, "proposals": proposals})
    return result


def report(db, brand, source_id):
    kind, _, row_id = source_id.partition(":")
    model = {"creator": DiscoveryRun, "trend": TrendRun, "batch": TrendBatch}.get(kind)
    row = db.get(model, row_id) if model and row_id else None
    if row is None or row.brand_id != brand.id:
        raise LookupError("Fuente no encontrada para esta marca")
    source = source_summary(row, kind)
    if kind == "creator":
        return creator_report(db, brand, row, source)
    if kind == "trend":
        return trend_report(brand, row, source)
    return batch_report(brand, row, source)
