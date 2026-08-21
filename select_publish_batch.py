"""Entry point: calcula el lote de publicación del ciclo (ver docs/DECISIONS.md).

Corre después de la reescritura y antes de los publishers de Web/Facebook/
Instagram — marca ``selected_for_publish`` en noticias_meta.json y
noticias_web_pending.json para que los 3 canales publiquen exactamente el
mismo lote (balde local + balde paparazzi + balde infobae).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.publish_selection import compute_next_batch
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("select_publish_batch", "select_publish_batch.log")


def main() -> StageResult:
    try:
        result = compute_next_batch()
    except JsonStateError as exc:
        logger.error("No se pudo calcular el lote de publicación: %s", exc)
        return StageResult(
            "select_publish_batch",
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            details={"message": str(exc)},
        )

    status = StageStatus.SUCCESS if result["selected"] else StageStatus.NO_WORK
    logger.info(
        "Lote calculado: batch_id=%s seleccionadas=%s (local=%s paparazzi=%s infobae=%s)",
        result.get("batch_id"),
        result["selected"],
        result["local"],
        result["paparazzi"],
        result["infobae"],
    )
    return StageResult(
        "select_publish_batch",
        status,
        succeeded=result["selected"],
        details=result,
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
