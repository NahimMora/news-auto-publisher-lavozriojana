"""Orquestador estructurado de scraping y reescritura."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from utils.config import validate_config
from utils.logging_setup import setup_logger
from utils.process_runner import run_stage_process
from utils.stage_result import (
    StageResult,
    StageStatus,
    aggregate_results,
    emit_stage_result,
)

logger = setup_logger("run_all", "run_all.log")

BASE_DIR = os.path.dirname(__file__)
TIMEOUTS = {
    "openIA/rewrite_news.py": 1800,
}
DEFAULT_TIMEOUT = 300


def run_script(script: str) -> StageResult:
    timeout = TIMEOUTS.get(script, DEFAULT_TIMEOUT)
    logger.info("Ejecutando %s (timeout=%ss)", script, timeout)
    result = run_stage_process(script, base_dir=BASE_DIR, timeout=timeout)
    logger.info(
        "Resultado %s status=%s recibidos=%s procesados=%s exitosos=%s fallidos=%s",
        script,
        result.status.value,
        result.received,
        result.processed,
        result.succeeded,
        result.failed,
    )
    return result


def main() -> StageResult:
    started = time.monotonic()
    report = validate_config(scope="core")
    if not report.ok:
        return StageResult(
            stage="scraping_rewrite",
            status=StageStatus.FAILED,
            failed=len(report.errors),
            duration_seconds=time.monotonic() - started,
            error_type="configuration_error",
            details={"config": report.to_dict()},
        )

    logger.info("=== Iniciando ciclo de scraping y reescritura ===")
    steps = [
        ("main_locales.py", os.getenv("SCRAPER_LOCALES_ENABLED", "1") == "1"),
        ("main_policiales.py", os.getenv("SCRAPER_POLICIALES_ENABLED", "1") == "1"),
        ("main_interior.py", os.getenv("SCRAPER_INTERIOR_ENABLED", "1") == "1"),
        ("main_deportes.py", os.getenv("SCRAPER_DEPORTES_ENABLED", "1") == "1"),
        ("main_nuevarioja.py", os.getenv("SCRAPER_NUEVARIOJA_ENABLED", "1") == "1"),
        ("openIA/rewrite_news.py", True),
    ]

    results: list[StageResult] = []
    for script, enabled in steps:
        if not enabled:
            results.append(
                StageResult(
                    stage=os.path.splitext(os.path.basename(script))[0],
                    status=StageStatus.NO_WORK,
                    details={"disabled": True, "script": script},
                )
            )
            logger.info("Saltando etapa deshabilitada: %s", script)
            continue
        results.append(run_script(script))

    aggregate = aggregate_results(
        "scraping_rewrite",
        results,
        duration_seconds=time.monotonic() - started,
    )
    logger.info(
        "Ciclo scraping/rewrite status=%s exitosos=%s fallidos=%s",
        aggregate.status.value,
        aggregate.succeeded,
        aggregate.failed,
    )
    return aggregate


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
