"""Entry point estructurado de las notas locales de mediosrioja.com.ar.

A diferencia de Fénix, Medios Rioja separa en el RSS lo nacional de lo local:
la categoría del editor (Locales/Departamentales) decide qué entra. Un filtro
por palabras descartaba notas hiperlocales que no nombran "La Rioja" (p. ej.
un incendio "en el barrio Las Talas").
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_mediosrioja import scrap_links_result, scrap_noticia_result
from scraping.runner import run_section
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import emit_stage_result

logger = setup_logger("main_mediosrioja", "main_mediosrioja.log")


def main():
    root = data_dir()
    result = run_section(
        stage="scrape_mediosrioja",
        enabled=os.getenv("SCRAPER_MEDIOSRIOJA_ENABLED", "0") == "1",
        history_path=str(root / "noticias_ejecutadas_mediosrioja.json"),
        output_path=str(root / "noticias_norewrite_mediosrioja.json"),
        fetch_links=scrap_links_result,
        fetch_article=scrap_noticia_result,
    )
    logger.info("Medios Rioja status=%s %s/%s", result.status.value, result.succeeded, result.selected)
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
