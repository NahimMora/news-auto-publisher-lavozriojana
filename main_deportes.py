"""
Entry point: scraper de sección Deportes de tiempopopular.com.ar
Guarda noticias nuevas en data/noticias_norewrite_deportes.json
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from scraping.deportes.links_scraper import scrap_links
from scraping.deportes.noticia_scraper import scrap_noticia
from utils.url_normalization import canonical_url
from utils.news_filters import is_blocked
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger

logger = setup_logger("main_deportes", "main_deportes.log")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORICO = os.path.join(DATA_DIR, "noticias_ejecutadas_deportes.json")
OUTPUT = os.path.join(DATA_DIR, "noticias_norewrite_deportes.json")

ENABLED = os.getenv("SCRAPER_DEPORTES_ENABLED", "1") == "1"


def main():
    if not ENABLED:
        logger.info("Scraper Deportes deshabilitado (SCRAPER_DEPORTES_ENABLED=0)")
        return

    logger.info("=== Iniciando scraper Deportes ===")
    os.makedirs(DATA_DIR, exist_ok=True)

    historico = load_json(HISTORICO, [])
    known_urls = {canonical_url(n["url"]) for n in historico}

    links = scrap_links()
    nuevas = []

    for url in links:
        if canonical_url(url) in known_urls:
            logger.debug(f"Ya procesada: {url}")
            continue

        noticia = scrap_noticia(url)
        if not noticia:
            logger.warning(f"No se pudo scrapear: {url}")
            continue

        if is_blocked(noticia, stage="scrape_deportes"):
            continue

        nuevas.append(noticia)
        historico.append(noticia)
        known_urls.add(canonical_url(url))
        logger.info(f"Nueva noticia: {noticia['titulo'][:70]}")

    if nuevas:
        pending = load_json(OUTPUT, [])
        pending.extend(nuevas)
        save_json(OUTPUT, pending)
        save_json(HISTORICO, historico)
        logger.info(f"Guardadas {len(nuevas)} noticias nuevas de Deportes")
    else:
        logger.info("Sin noticias nuevas en Deportes")


if __name__ == "__main__":
    main()
