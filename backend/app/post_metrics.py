"""Relevancia de un post para su propio creador. Funciones puras, sin base de datos.

Un post es relevante cuando rinde por encima de lo que ese creador consigue normalmente, no cuando tiene
muchos likes en absoluto: así una cuenta de 5 mil seguidores y una de 2 millones se comparan en la misma
escala. En Instagram, Bright Data no entrega vistas (ni en posts ni en reels), así que todo se mide con likes
y comentarios. En TikTok sí hay vistas reales, y además compartidos. Pasos para cada post:

1. Madurez: un post acumula interacciones en sus primeras horas o días y luego se estanca. Se aproxima
   con una curva de saturación f(edad) = 1 − e^(−edad/τ), con τ distinto para video y estático, y el
   valor observado se proyecta a su total esperado: valor / f(edad). La edad se mide en el momento de la
   observación, no ahora. Un post con menos de MIN_AGE_HOURS queda como provisional y no entra en
   ninguna línea base.
2. Línea base del creador: mediana de los valores proyectados de sus otros posts maduros del mismo
   formato (video o estático), sin contar el propio post. Si no hay MIN_BASELINE posts de ese formato,
   se usan todos sus posts y la confianza baja.
3. Señales: en Instagram, likes (la mejor aproximación al alcance que tenemos) y comentarios
   (resonancia); en TikTok, vistas (alcance), likes, compartidos y comentarios. Cada una da un múltiplo
   frente a su línea base y el rendimiento es su media geométrica ponderada: un pico de comentarios
   inducido ("comenta X y te lo envío") pesa, pero no domina.
4. Rareza: z robusto en escala logarítmica (mediana y MAD) para distinguir un ×2 de un creador muy
   constante de un ×2 de un creador que siempre oscila.

El engagement sobre seguidores se informa para comparar creadores, pero no puntúa: el número de
seguidores no dice cuántos lo vieron. Con dos o más observaciones de un post se informa su velocidad
(likes y comentarios por hora entre lecturas); todavía no puntúa, falta historial para su línea base.
"""
import math
from dataclasses import dataclass
from datetime import datetime
from statistics import median

# Horas hasta alcanzar ~63% del total (a 3τ, ~95%). Los reels siguen sumando durante días; un post
# estático se concentra en el primer día. Son supuestos iniciales: el historial de observaciones
# (`instagram_post_observations`) permite calibrarlos con datos propios.
TAU_HOURS = {"video": 48.0, "static": 18.0}
MIN_AGE_HOURS = 12.0
MIN_BASELINE = 4
WEIGHTS = {"likes": 0.7, "comments": 0.3}
# TikTok: las vistas miden el alcance directamente; compartir es la señal de resonancia más fuerte.
PLATFORM_WEIGHTS = {"instagram": WEIGHTS, "tiktok": {"views": 0.5, "likes": 0.25, "shares": 0.15, "comments": 0.1}}
# Señal que decide si hay evidencia suficiente para confiar en el puntaje.
PRIMARY = {"instagram": "likes", "tiktok": "views"}
# MAD mínimo (en log natural) para que un creador muy constante no convierta cualquier diferencia en rareza.
MIN_MAD = 0.15
# Pseudo-cuenta que suaviza el múltiplo: con una base de 0–2 likes, 2 likes no son "el triple de lo normal".
# Apenas mueve a creadores con bases de cientos o miles.
SMOOTHING = 10
LABELS = (("viral", 3.0, 2.0), ("sobresaliente", 1.5, 1.0))
LOW_PERFORMANCE = 0.67
# Comentarios ≥ la mitad de los likes: patrón típico de "comenta X". Solo se marca; no cambia la etiqueta.
COMMENT_BAIT_RATIO = 0.5
COMMENT_BAIT_MIN = 20
MIN_VELOCITY_HOURS = 6.0


@dataclass
class PostSample:
    id: str
    username: str
    format: str  # "video" o "static"
    posted_at: datetime
    observed_at: datetime
    likes: int | None
    comments: int | None
    followers: int | None
    views: int | None = None
    shares: int | None = None
    platform: str = "instagram"


def format_group(content_type: str | None) -> str:
    return "video" if content_type in {"reel", "video"} else "static"


def age_hours(post: PostSample) -> float:
    return max((post.observed_at - post.posted_at).total_seconds() / 3600, 0.0)


def maturity(hours: float, fmt: str) -> float:
    """Fracción esperada del total acumulada a esa edad. Con suelo en MIN_AGE_HOURS para no dividir por casi cero."""
    return 1 - math.exp(-max(hours, MIN_AGE_HOURS) / TAU_HOURS[fmt])


def signals(post: PostSample) -> dict[str, int]:
    """Valores observados disponibles de las señales de su red. Likes ocultos (None) dejan fuera esa señal."""
    return {name: getattr(post, name) for name in PLATFORM_WEIGHTS[post.platform] if getattr(post, name) is not None}


def projected(post: PostSample) -> dict[str, float]:
    factor = maturity(age_hours(post), post.format)
    return {name: value / factor for name, value in signals(post).items()}


def robust_z(value: float, others: list[float]) -> float:
    logs = [math.log1p(v) for v in others]
    center = median(logs)
    mad = max(median(abs(x - center) for x in logs), MIN_MAD)
    return (math.log1p(value) - center) / (1.4826 * mad)


def label(performance: float | None, z: float | None) -> str:
    if performance is None:
        return "sin_linea_base"
    for name, min_performance, min_z in LABELS:
        if performance >= min_performance and (z or 0) >= min_z:
            return name
    return "bajo" if performance < LOW_PERFORMANCE else "normal"


def comment_bait(post: PostSample) -> bool:
    return bool(post.likes and post.comments and post.comments >= COMMENT_BAIT_MIN
                and post.comments >= COMMENT_BAIT_RATIO * post.likes)


def score_post(post: PostSample, peers: list[PostSample]) -> dict:
    """Rendimiento de `post` frente a `peers` (los demás posts del mismo creador)."""
    hours = age_hours(post)
    mature = [p for p in peers if p.id != post.id and age_hours(p) >= MIN_AGE_HOURS]
    same = [p for p in mature if p.format == post.format]
    pool, scope = (same, "formato") if len(same) >= MIN_BASELINE else (mature, "todos")
    values = projected(post)
    weights = PLATFORM_WEIGHTS[post.platform]
    breakdown, log_sum, z_sum, weight_sum = {}, 0.0, 0.0, 0.0
    for name, value in values.items():
        history = [v for v in (projected(p).get(name) for p in pool) if v is not None]
        if len(history) < MIN_BASELINE:
            continue
        base = median(history)
        ratio = (value + SMOOTHING) / (base + SMOOTHING)
        z = robust_z(value, history)
        breakdown[name] = {"observed": signals(post)[name], "projected": round(value), "baseline": round(base),
                           "ratio": round(ratio, 2), "z": round(z, 2), "baseline_posts": len(history)}
        log_sum += weights[name] * math.log(ratio)
        z_sum += weights[name] * z
        weight_sum += weights[name]
    performance = math.exp(log_sum / weight_sum) if weight_sum else None
    z = z_sum / weight_sum if weight_sum else None
    provisional = hours < MIN_AGE_HOURS
    smallest = min((b["baseline_posts"] for b in breakdown.values()), default=0)
    # Sin la señal principal (likes en Instagram, vistas en TikTok), o con su base por debajo de la pseudo-cuenta
    # (audiencia que casi no interactúa), hay poca evidencia. Los comentarios suelen ser pocos y no cuentan para esto.
    primary = PRIMARY[post.platform]
    weak = primary not in breakdown or breakdown[primary]["baseline"] < SMOOTHING
    if provisional or scope == "todos" or weak:
        confidence = "baja"
    elif smallest < MIN_BASELINE * 2 or len(breakdown) < len(values):
        confidence = "media"
    else:
        confidence = "alta"
    followers = post.followers
    return {
        "performance": round(performance, 2) if performance is not None else None,
        "z": round(z, 2) if z is not None else None,
        "label": label(performance, z),
        "confidence": confidence,
        "provisional": provisional,
        "comment_bait": comment_bait(post),
        "age_hours": round(hours, 1),
        "maturity": round(maturity(hours, post.format), 2),
        "baseline_scope": scope,
        "signals": breakdown,
        "engagement_rate": round((post.likes + (post.comments or 0)) / followers, 4) if followers and post.likes is not None else None,
    }


def creator_baseline(posts: list[PostSample], window_days: int) -> dict:
    """Lo que el creador publica normalmente: frecuencia, mezcla de formatos y medianas proyectadas."""
    mature = [p for p in posts if age_hours(p) >= MIN_AGE_HOURS]

    def med(name):
        values = [v for v in (projected(p).get(name) for p in mature) if v is not None]
        return round(median(values)) if values else None

    followers = next((p.followers for p in posts if p.followers), None)
    rates = [(p.likes + (p.comments or 0)) / followers for p in mature if followers and p.likes is not None]
    return {
        "posts": len(posts),
        "mature_posts": len(mature),
        "posts_per_week": round(len(posts) / window_days * 7, 1),
        "formats": {fmt: sum(p.format == fmt for p in posts) for fmt in ("video", "static")},
        "median_views": med("views"),
        "median_likes": med("likes"),
        "median_comments": med("comments"),
        "median_shares": med("shares"),
        "median_engagement_rate": round(median(rates), 4) if rates else None,
        "followers": followers,
    }


def velocity(observations: list[tuple[datetime, int | None, int | None]]) -> dict | None:
    """Likes y comentarios ganados por hora entre la primera y la última observación de un post.

    `observations`: (observed_at, likes, comments). None si las lecturas están a menos de MIN_VELOCITY_HOURS."""
    readings = sorted(observations)
    if len(readings) < 2:
        return None
    (start, likes0, comments0), (end, likes1, comments1) = readings[0], readings[-1]
    hours = (end - start).total_seconds() / 3600
    if hours < MIN_VELOCITY_HOURS:
        return None
    rate = lambda a, b: round((b - a) / hours, 2) if a is not None and b is not None else None
    return {"hours": round(hours, 1), "observations": len(readings),
            "likes_per_hour": rate(likes0, likes1), "comments_per_hour": rate(comments0, comments1)}


def analyze(posts: list[PostSample], window_days: int) -> tuple[dict[str, dict], dict[str, dict]]:
    """Puntaje por post y línea base por creador."""
    by_creator: dict[str, list[PostSample]] = {}
    for post in posts:
        by_creator.setdefault(post.username, []).append(post)
    scores = {p.id: score_post(p, by_creator[p.username]) for p in posts}
    baselines = {name: creator_baseline(items, window_days) for name, items in by_creator.items()}
    return scores, baselines


def method(platform: str = "instagram") -> dict:
    """Parámetros del cálculo, para mostrarlos junto al resultado."""
    return {"tau_hours": TAU_HOURS, "min_age_hours": MIN_AGE_HOURS, "min_baseline_posts": MIN_BASELINE, "weights": PLATFORM_WEIGHTS[platform],
            "smoothing": SMOOTHING, "labels": {name: {"min_performance": p, "min_z": z} for name, p, z in LABELS},
            "low_performance": LOW_PERFORMANCE, "comment_bait": {"ratio": COMMENT_BAIT_RATIO, "min_comments": COMMENT_BAIT_MIN},
            "min_velocity_hours": MIN_VELOCITY_HOURS}
