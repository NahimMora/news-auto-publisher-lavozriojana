"""Etapa estructurada: respuestas concretas a preguntas en publicaciones
informativas (ver ``utils/comment_replies.py``).

``COMMENT_REPLIES_MODE=suggest`` sólo guarda las respuestas propuestas;
``auto`` las publica con tope diario. Fuera de horario (0–7) no corre.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import comment_replies as cr
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.social_time import quiet_hours
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_comment_replies", "comment_replies.log")

STAGE = "comment_replies"


def main() -> StageResult:
    started = time.monotonic()
    current = cr.mode()
    plan = deployment_plan()
    if current == "off" or not (plan.channel_enabled("instagram") or plan.channel_enabled("facebook")):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True, "mode": current})
    if quiet_hours():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"quiet_hours": True})
    try:
        candidates = cr.collect()
    except JsonStateError as exc:
        logger.error("Estado de comentarios ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    limit = int(os.getenv("COMMENT_REPLIES_MAX_PER_CYCLE", "10"))
    selected = [
        c for c in candidates
        if (c["platform"] == "instagram" and plan.channel_enabled("instagram")) or (c["platform"] == "facebook" and plan.channel_enabled("facebook"))
    ][:limit]
    counts = cr.process(selected, publish=current == "auto")
    logger.info("Comentarios: modo=%s %s", current, counts)
    # Declinar una pregunta (la nota no lo dice) es un resultado sano.
    succeeded = counts["replied"] + counts["proposed"] + counts["declined"]
    return result_from_counts(
        STAGE,
        received=len(candidates),
        selected=len(selected),
        processed=counts["evaluated"],
        succeeded=succeeded,
        failed=counts["failed"],
        deferred=max(0, len(candidates) - len(selected)),
        duration_seconds=time.monotonic() - started,
        details={"mode": current, **counts},
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
