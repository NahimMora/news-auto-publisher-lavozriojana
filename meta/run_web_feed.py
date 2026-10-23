"""Etapa estructurada: publica los datos para la web (``utils/web_feed.py``)
como JSON en R2: lo más visto, servicios, actualizaciones y videos. Sólo lee
estado y fuentes oficiales (y la Graph API para los enlaces de Instagram);
nunca publica en redes ni toca colas. Apagada con ``WEB_FEED_ENABLED``.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import r2_storage, web_feed
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("web_feed", "web_feed.log")
STAGE = "web_feed"


def main() -> StageResult:
    started = time.monotonic()
    if os.getenv("WEB_FEED_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if not r2_storage.is_configured():
        return StageResult(STAGE, StageStatus.FAILED, failed=1, error_type="missing_configuration")
    try:
        docs, failed_sources = web_feed.collect()
    except JsonStateError as exc:
        logger.error("Estado del feed web ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, failed=1, error_type="state_error")
    uploaded, failed = web_feed.publish(docs)
    logger.info("Feed web: subidos %s, fallidos %s, fuentes sin dato %s", uploaded, failed, failed_sources)
    result = result_from_counts(
        STAGE,
        received=len(docs) + 1,
        selected=len(docs) + 1,
        processed=len(uploaded) + len(failed),
        succeeded=len(uploaded),
        failed=len(failed),
        duration_seconds=time.monotonic() - started,
        details={
            "uploaded": uploaded,
            "failed_sources": failed_sources,
            "most_viewed_24h": len(docs["mas-visto"]["ventanas"]["24h"]),
            "updates": len(docs["actualizaciones"]["items"]),
            "videos": len(docs["videos"]["items"]),
        },
    )
    # Una fuente caída (el SMN, Hacienda) no es una falla de la etapa: se
    # sirve el último dato bueno; se informa como degradado.
    if not failed and failed_sources and result.status == StageStatus.SUCCESS:
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
