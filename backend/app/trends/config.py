"""Engine settings. Secrets come from the server environment (Compose interpolates them from .env)."""
import os
from pathlib import Path

# Working store of the engine: search cache, collected items, YouTube snapshots and per-brand labels.
# Run summaries and reports live in the application database (`trend_runs`).
DB_PATH = Path(os.environ.get("TRENDS_DB_PATH", "trends.db"))

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
# USD per million tokens (input, output), Anthropic first-party rates, Oct 2026.
PRICES = {HAIKU: (0.10, 0.50), SONNET: (2.00, 10.00), OPUS: (4.00, 20.00)}
EXA_USD_PER_SEARCH = 7 / 1000
BRAVE_USD_PER_QUERY = 5 / 1000

YT_DAILY_QUOTA = 10_000
SEARCH_CACHE_HOURS = 24
BASELINE_N = 30          # last N uploads define a creator's normal views
MIN_BASELINE = 1000      # floor so a 40-view channel with one 60k hit isn't "1,500x"
SPARSE_ITEMS = 150       # fewer relevant items than this widens the window

REQUIRED_KEYS = ("YOUTUBE_API_KEY", "EXA_API_KEY", "ANTHROPIC_API_KEY")
OPTIONAL_KEYS = ("BRAVE_API_KEY",)


def secret(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name) or None
    if required and not value:
        raise RuntimeError(f"Falta {name} en el entorno del servidor (.env de Compose).")
    return value


def missing_keys() -> list[str]:
    return [k for k in REQUIRED_KEYS if not os.environ.get(k)]


def haiku_only() -> bool:
    """RADAR_LLM=haiku runs every model call on Haiku 5.5: cheap test runs, lower output quality."""
    return os.environ.get("RADAR_LLM", "").lower() == "haiku"


def judgment_model() -> str:
    """Model for routine judgment (queries, persona rubric, comment themes)."""
    return HAIKU if haiku_only() else SONNET


def top_model() -> str:
    """Model for the topic taxonomy and the content proposals.
    RADAR_TOP_MODEL=opus switches back to Opus 5.5 if Sonnet's output isn't good enough."""
    if haiku_only():
        return HAIKU
    return OPUS if os.environ.get("RADAR_TOP_MODEL", "sonnet").lower() == "opus" else SONNET


def run_budget_usd() -> float:
    return float(os.environ.get("RUN_BUDGET_USD", "6"))


def snapshot_hours() -> float:
    """Interval of the in-process YouTube snapshot job; 0 disables it."""
    return float(os.environ.get("TRENDS_SNAPSHOT_HOURS", "6"))
