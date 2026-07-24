"""Dispatcher seguro de publicación web."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("publish_web", "publish_web.log")


def main() -> StageResult:
    target = str(os.getenv("WEB_PUBLISH_TARGET", "off")).strip().lower()
    logger.info("Publicación web: target=%s", target)

    if target == "node_webapp":
        from pipeline.node_webapp.publisher import publish_pending

        return publish_pending()

    if target == "off":
        logger.info("Publicación web deshabilitada")
        return StageResult(
            "web",
            StageStatus.NO_WORK,
            details={"disabled": True, "target": target},
        )

    logger.error("WEB_PUBLISH_TARGET desconocido: %s", target)
    return StageResult(
        "web",
        StageStatus.FAILED,
        failed=1,
        error_type="invalid_configuration",
        details={"target": target},
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
