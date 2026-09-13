"""Etapa de ciclo: refresca fuentes oficiales habilitadas (Parte 56).

``ciclo → actualizar fuentes oficiales una vez → normalizar caché → todas
las noticias del ciclo consultan caché local``. Respeta ``poll_ttl`` por
fuente: no vuelve a pegarle a una fuente que no venció su caché. Se
registra como paso propio de ``run_24x7.py`` entre ``run_all.py`` y
``pipeline/publish_web.py``.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from sources.fetch_state import is_due
from sources.registry import enabled_sources
from sources.sync import sync_source
from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("editorial_context.refresh_context", "official_sources.log")


def run() -> StageResult:
    started = time.monotonic()
    sources = enabled_sources()
    if not sources:
        return StageResult("official_sources_refresh", StageStatus.NO_WORK, duration_seconds=time.monotonic() - started)

    processed = succeeded = failed = 0
    for source in sources:
        if not is_due(source.source_id, poll_ttl=source.poll_ttl):
            continue
        processed += 1
        try:
            report = sync_source(source)
        except Exception:
            logger.exception("Fallo inesperado sincronizando %s; no rompe el ciclo", source.source_id)
            failed += 1
            continue
        time.sleep(max(0.0, source.request_delay))
        if report.reachable or report.parse_status == "not_modified":
            succeeded += 1
        else:
            failed += 1
        logger.info(
            "Fuente %s: reachable=%s status=%s items_new=%s parse_status=%s warnings=%s",
            source.source_id,
            report.reachable,
            report.http_status,
            report.items_new,
            report.parse_status,
            report.warnings,
        )

    return result_from_counts(
        "official_sources_refresh",
        received=len(sources),
        selected=processed,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        duration_seconds=time.monotonic() - started,
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(run()))
