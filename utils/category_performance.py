"""Rendimiento histórico de Instagram por categoría (agregado por
meta/ig_insights.py), usado por utils/editorial_router.py para promover
candidatas de buen desempeño en vez de esperar siempre revisión manual — ver
docs/DECISIONS.md. ``load_category_performance`` es la única función con I/O;
``is_strong_performing_category`` es pura (solo aritmética sobre el dict ya
cargado) para preservar el contrato "evaluate_routing no hace I/O".
"""
from __future__ import annotations

import os

from utils.file_manager import load_json
from utils.paths import data_dir

PERFORMANCE_PATH = str(data_dir() / "ig_category_performance.json")

MIN_SAMPLE_SIZE = int(os.getenv("IG_STATS_MIN_SAMPLE_SIZE", "5"))
PROMOTION_THRESHOLD_RATIO = float(os.getenv("IG_STATS_PROMOTION_THRESHOLD_RATIO", "1.0"))


def promotion_enabled() -> bool:
    return str(os.getenv("IG_STATS_PROMOTION_ENABLED", "false")).strip().lower() in {
        "1", "true", "yes", "on", "si", "sí",
    }


def load_category_performance() -> dict:
    """Lee el snapshot agregado por meta/ig_insights.py.

    Nunca lanza: con la promoción apagada, o un archivo ausente/corrupto,
    devuelve {} — mismo efecto que no tener datos todavía (el router
    conserva el comportamiento actual, sin promoción por rendimiento).
    """
    if not promotion_enabled():
        return {}
    try:
        data = load_json(PERFORMANCE_PATH, {}, expected_type=dict)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def is_strong_performing_category(category: str, performance: dict) -> bool:
    """True si ``category`` tiene suficiente muestra y una tasa de
    interacción (interacciones/alcance) igual o mejor que el promedio de la
    cuenta * PROMOTION_THRESHOLD_RATIO."""
    if not performance:
        return False
    overall = performance.get("overall")
    categories = performance.get("categories")
    if not isinstance(overall, dict) or not isinstance(categories, dict):
        return False
    entry = categories.get(category)
    if not isinstance(entry, dict):
        return False
    sample_size = int(entry.get("sample_size") or 0)
    if sample_size < MIN_SAMPLE_SIZE:
        return False
    rate = entry.get("engagement_rate")
    overall_rate = overall.get("engagement_rate")
    if rate is None or overall_rate is None or float(overall_rate) <= 0:
        return False
    return float(rate) >= float(overall_rate) * PROMOTION_THRESHOLD_RATIO
