"""Etapa estructurada: recolecta estadísticas de Instagram (reach,
total_interactions) de publicaciones recientes y agrega tasa de interacción
por categoría, para que el router editorial pueda promover candidatas de
buen rendimiento en vez de esperar revisión manual siempre (ver
docs/DECISIONS.md, IG_STATS_PROMOTION_ENABLED). Solo lee de Graph API; nunca
publica ni modifica colas productivas.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

import requests

from meta.ig_client import GRAPH_API, IG_ACCESS_TOKEN, IG_ACCOUNT_ID
from utils.editorial_priority import normalize_category
from utils.file_manager import JsonStateError, load_json, save_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("ig_insights", "ig_insights.log")

IG_STATE_PATH = str(data_dir() / "ig_posted.json")
PERFORMANCE_PATH = str(data_dir() / "ig_category_performance.json")
MAX_POSTS_PER_RUN = int(os.getenv("IG_STATS_MAX_POSTS_PER_RUN", "30"))
REQUEST_TIMEOUT = int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "30"))


def _enabled() -> bool:
    return str(os.getenv("IG_STATS_ENABLED", "false")).strip().lower() in {
        "1", "true", "yes", "on", "si", "sí",
    }


def _recent_posted_items() -> list[dict]:
    state = load_json(IG_STATE_PATH, {"posted": {}}, expected_type=dict)
    posted = state.get("posted", {})
    if not isinstance(posted, dict):
        return []
    items = [value for value in posted.values() if isinstance(value, dict) and value.get("external_id")]
    items.sort(key=lambda item: int(item.get("posted_at") or 0), reverse=True)
    return items[:MAX_POSTS_PER_RUN]


def _fetch_insights(media_id: str) -> dict | None:
    try:
        response = requests.get(
            f"{GRAPH_API}/{media_id}/insights",
            params={"metric": "reach,total_interactions", "access_token": IG_ACCESS_TOKEN},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.info("Insights: error de red para %s: %s", media_id, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    values: dict = {}
    for entry in data.get("data") or []:
        name = entry.get("name")
        entry_values = entry.get("values") or []
        if name and entry_values and isinstance(entry_values[0], dict):
            values[name] = entry_values[0].get("value")
    return values or None


def _engagement_rate(bucket: dict) -> float | None:
    reach_sum = bucket.get("reach_sum") or 0
    if reach_sum <= 0:
        return None
    return bucket["interactions_sum"] / reach_sum


def main() -> StageResult:
    started = time.monotonic()
    if not _enabled():
        return StageResult("instagram_insights", StageStatus.NO_WORK, details={"disabled": True})
    if (
        not IG_ACCOUNT_ID
        or IG_ACCOUNT_ID == "PENDIENTE"
        or not IG_ACCESS_TOKEN
        or IG_ACCESS_TOKEN == "PENDIENTE"
    ):
        return StageResult(
            "instagram_insights",
            StageStatus.FAILED,
            failed=1,
            error_type="missing_configuration",
            duration_seconds=time.monotonic() - started,
        )

    try:
        items = _recent_posted_items()
    except JsonStateError as exc:
        logger.error("No se pudo leer ig_posted.json: %s", exc)
        return StageResult(
            "instagram_insights",
            StageStatus.FAILED,
            failed=1,
            error_type="state_read_error",
            duration_seconds=time.monotonic() - started,
        )

    if not items:
        return StageResult(
            "instagram_insights", StageStatus.NO_WORK, received=0,
            duration_seconds=time.monotonic() - started,
        )

    category_sums: dict[str, dict[str, float]] = {}
    overall = {"reach_sum": 0.0, "interactions_sum": 0.0, "sample_size": 0}
    succeeded = failed = 0

    for item in items:
        media_id = str(item.get("external_id") or "")
        category = normalize_category(item.get("seccion") or "desconocido")
        values = _fetch_insights(media_id) if media_id else None
        reach = values.get("reach") if values else None
        interactions = values.get("total_interactions") if values else None
        if reach is None or interactions is None:
            failed += 1
            continue
        succeeded += 1
        bucket = category_sums.setdefault(
            category, {"reach_sum": 0.0, "interactions_sum": 0.0, "sample_size": 0}
        )
        bucket["reach_sum"] += float(reach)
        bucket["interactions_sum"] += float(interactions)
        bucket["sample_size"] += 1
        overall["reach_sum"] += float(reach)
        overall["interactions_sum"] += float(interactions)
        overall["sample_size"] += 1

    categories_out = {
        category: {**bucket, "engagement_rate": _engagement_rate(bucket)}
        for category, bucket in category_sums.items()
    }
    overall_out = {**overall, "engagement_rate": _engagement_rate(overall)}

    snapshot = {
        "updated_at": int(time.time()),
        "overall": overall_out,
        "categories": categories_out,
    }
    try:
        save_json(PERFORMANCE_PATH, snapshot)
    except JsonStateError as exc:
        logger.error("No se pudo guardar %s: %s", PERFORMANCE_PATH, exc)
        return StageResult(
            "instagram_insights",
            StageStatus.FAILED,
            failed=1,
            error_type="state_write_error",
            duration_seconds=time.monotonic() - started,
        )

    logger.info(
        "Insights actualizados: %s posts consultados, %s ok, %s fallidos, %s categorías",
        len(items), succeeded, failed, len(categories_out),
    )
    return result_from_counts(
        "instagram_insights",
        received=len(items),
        selected=len(items),
        processed=len(items),
        succeeded=succeeded,
        failed=failed,
        duration_seconds=time.monotonic() - started,
        details={"categories": len(categories_out)},
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
