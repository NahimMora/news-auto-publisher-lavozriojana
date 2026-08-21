"""Entry point estructurado del scraper de paparazzi.com.ar."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_paparazzi import scrap_links_result, scrap_noticia_result
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import emit_stage_result

logger = setup_logger("main_paparazzi", "main_paparazzi.log")


def main():
    root = data_dir()
    result = run_section(
        stage="scrape_paparazzi",
        enabled=os.getenv("SCRAPER_PAPARAZZI_ENABLED", "0") == "1",
        history_path=str(root / "noticias_ejecutadas_paparazzi.json"),
        output_path=str(root / "noticias_norewrite_paparazzi.json"),
        fetch_links=scrap_links_result,
        fetch_article=scrap_noticia_result,
    )
    logger.info("Paparazzi status=%s %s/%s", result.status.value, result.succeeded, result.selected)
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
