"""Entry point estructurado de la sección Locales de fenix951.com.ar."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_fenix import (
    SECTION_NAME,
    has_riojan_link,
    scrap_links_result,
    scrap_noticia_result,
)
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import emit_stage_result

logger = setup_logger("main_fenix", "main_fenix.log")


def _discard(article: dict) -> tuple[bool, str]:
    """Fénix mezcla en Locales entrevistas nacionales: sólo entra lo riojano."""
    if article.get("categoria_origen") and article["categoria_origen"] != SECTION_NAME:
        return True, "fenix_fuera_de_locales"
    if not has_riojan_link(article):
        return True, "fenix_sin_vinculo_riojano"
    return False, ""


def main():
    root = data_dir()
    result = run_section(
        stage="scrape_fenix",
        enabled=os.getenv("SCRAPER_FENIX_ENABLED", "0") == "1",
        history_path=str(root / "noticias_ejecutadas_fenix.json"),
        output_path=str(root / "noticias_norewrite_fenix.json"),
        fetch_links=scrap_links_result,
        fetch_article=scrap_noticia_result,
        extra_discard=_discard,
    )
    logger.info("Fénix status=%s %s/%s", result.status.value, result.succeeded, result.selected)
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
