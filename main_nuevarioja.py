"""Entry point estructurado de las secciones de Nueva Rioja."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_nuevarioja import scrap_links_result, scrap_noticia_result
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import (
    StageResult,
    StageStatus,
    aggregate_results,
    emit_stage_result,
)

logger = setup_logger("main_nuevarioja", "main_nuevarioja.log")

SECTIONS = [
    ("politica", "https://nuevarioja.com.ar/politica", "SCRAPER_NR_POLITICA_ENABLED"),
    ("sociedad", "https://nuevarioja.com.ar/sociedad", "SCRAPER_NR_SOCIEDAD_ENABLED"),
    ("policiales", "https://nuevarioja.com.ar/policiales", "SCRAPER_NR_POLICIALES_ENABLED"),
    ("deportes", "https://nuevarioja.com.ar/deportes", "SCRAPER_NR_DEPORTES_ENABLED"),
    ("interior", "https://nuevarioja.com.ar/interior", "SCRAPER_NR_INTERIOR_ENABLED"),
    (
        "internacionales",
        "https://nuevarioja.com.ar/internacionales",
        "SCRAPER_NR_INTERNACIONALES_ENABLED",
    ),
]


def main() -> StageResult:
    started = time.monotonic()
    if os.getenv("SCRAPER_NUEVARIOJA_ENABLED", "1") != "1":
        return StageResult("scrape_nuevarioja", StageStatus.NO_WORK, details={"disabled": True})

    root = data_dir()
    output = str(root / "noticias_norewrite_nuevarioja.json")
    results: list[StageResult] = []
    for section_name, section_url, env_key in SECTIONS:
        result = run_section(
            stage=f"scrape_nuevarioja_{section_name}",
            enabled=os.getenv(env_key, "1") == "1",
            history_path=str(root / f"noticias_ejecutadas_nuevarioja_{section_name}.json"),
            output_path=output,
            fetch_links=lambda url=section_url, name=section_name: scrap_links_result(url, name),
            fetch_article=lambda article_url, name=section_name: scrap_noticia_result(article_url, name),
        )
        results.append(result)

    aggregate = aggregate_results(
        "scrape_nuevarioja",
        results,
        duration_seconds=time.monotonic() - started,
    )
    logger.info(
        "Nueva Rioja status=%s exitosas=%s fallidas=%s",
        aggregate.status.value,
        aggregate.succeeded,
        aggregate.failed,
    )
    return aggregate


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
