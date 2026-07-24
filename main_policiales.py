"""Entry point estructurado del scraper Policiales de Tiempo Popular."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.policiales.links_scraper import scrap_links_result
from scraping.policiales.noticia_scraper import scrap_noticia_result
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import emit_stage_result

logger = setup_logger("main_policiales", "main_policiales.log")


def main():
    root = data_dir()
    result = run_section(
        stage="scrape_policiales",
        enabled=os.getenv("SCRAPER_POLICIALES_ENABLED", "1") == "1",
        history_path=str(root / "noticias_ejecutadas_policiales.json"),
        output_path=str(root / "noticias_norewrite_policiales.json"),
        fetch_links=scrap_links_result,
        fetch_article=scrap_noticia_result,
    )
    logger.info("Policiales status=%s %s/%s", result.status.value, result.succeeded, result.selected)
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
