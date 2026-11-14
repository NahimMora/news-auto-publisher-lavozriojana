"""Entry point estructurado de las fuentes judiciales oficiales (MPF y Función Judicial)."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_judiciales import SOURCES, scrap_links_result, scrap_noticia_result
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import (
    StageResult,
    StageStatus,
    aggregate_results,
    emit_stage_result,
)

logger = setup_logger("main_judiciales", "main_judiciales.log")


def main() -> StageResult:
    started = time.monotonic()
    if os.getenv("SCRAPER_JUDICIALES_ENABLED", "0") != "1":
        return StageResult("scrape_judiciales", StageStatus.NO_WORK, details={"disabled": True})

    root = data_dir()
    results: list[StageResult] = []
    for key in SOURCES:
        results.append(
            run_section(
                stage=f"scrape_judiciales_{key}",
                enabled=True,
                history_path=str(root / f"noticias_ejecutadas_judiciales_{key}.json"),
                output_path=str(root / "noticias_norewrite_judiciales.json"),
                fetch_links=lambda key=key: scrap_links_result(key),
                fetch_article=lambda url, key=key: scrap_noticia_result(url, key),
            )
        )

    aggregate = aggregate_results("scrape_judiciales", results, duration_seconds=time.monotonic() - started)
    logger.info(
        "Judiciales status=%s exitosas=%s fallidas=%s",
        aggregate.status.value,
        aggregate.succeeded,
        aggregate.failed,
    )
    return aggregate


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
