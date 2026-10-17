from datetime import datetime, timedelta, timezone
from .schemas import BatchCreate, BrandCreate


def demo_brief():
    return BrandCreate(name="30X · Demo", description="Ayudamos a líderes y equipos de Latinoamérica a convertir la inteligencia artificial en resultados de negocio, con ejemplos claros y aprendizaje práctico.", audience="Líderes y equipos que aprenden IA", region="Latinoamérica", topics=["agentes de IA", "automatización", "IA en negocios", "productividad"])


def demo_batch():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    topics = [("agentes de IA", 3.1, "Tu próximo equipo también tendrá agentes"), ("automatización", 2.2, "Este proceso te está robando cinco horas"), ("IA en negocios", 1.7, "Del piloto al resultado: un caso práctico"), ("productividad", 1.3, "Una tarea, tres formas de resolverla con IA"), ("video generativo", 1.1, "De una idea a un video en minutos"), ("modelos abiertos", .8, "¿Cuándo conviene un modelo abierto?")]
    posts = []
    for i, (topic, multiplier, hook) in enumerate(topics):
        for j in range(3):
            platform = ["linkedin", "instagram", "youtube"][j]
            base = 1000 + i * 300 + j * 400
            # Four days in each interval, so the multiplier equals the rate ratio.
            snapshots = [{"observed_at": (now-timedelta(days=9)).isoformat(), "views": base}, {"observed_at": (now-timedelta(days=5)).isoformat(), "views": base*2}, {"observed_at": (now-timedelta(days=1)).isoformat(), "views": base*2+int(base*multiplier)}]
            posts.append({"external_id": f"demo-{i}-{j}", "platform": platform, "url": f"https://www.{platform}.com/demo-30x-{i}-{j}", "title": hook, "topic": topic, "format": ["carousel", "short", "video"][j], "hook": hook, "published_at": (now-timedelta(days=10)).isoformat(), "snapshots": snapshots, "source_method": "demo", "source_reference": "Fixture sintético local; URL ficticia, no visitar."})
    return BatchCreate(mode="demo", source="Demo sintética 30X · sin observación de redes", compliance_confirmed=True, posts=posts)
