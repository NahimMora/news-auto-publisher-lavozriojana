"""
Entry point: scraper for nuevarioja.com.ar sections.
Stores all new articles in data/noticias_norewrite_nuevarioja.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_nuevarioja import scrap_links, scrap_noticia
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger
from utils.news_filters import is_blocked
from utils.url_normalization import canonical_url

logger = setup_logger("main_nuevarioja", "main_nuevarioja.log")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT = os.path.join(DATA_DIR, "noticias_norewrite_nuevarioja.json")

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

ENABLED = os.getenv("SCRAPER_NUEVARIOJA_ENABLED", "1") == "1"


def _history_path(section_name: str) -> str:
    return os.path.join(DATA_DIR, f"noticias_ejecutadas_nuevarioja_{section_name}.json")


def _section_enabled(env_key: str) -> bool:
    return os.getenv(env_key, "1") == "1"


def main():
    if not ENABLED:
        logger.info("Scraper Nueva Rioja deshabilitado (SCRAPER_NUEVARIOJA_ENABLED=0)")
        return

    logger.info("=== Iniciando scraper Nueva Rioja ===")
    os.makedirs(DATA_DIR, exist_ok=True)

    nuevas_total = []
    for section_name, section_url, env_key in SECTIONS:
        if not _section_enabled(env_key):
            logger.info(f"Saltando Nueva Rioja {section_name} ({env_key}=0)")
            continue

        historico_path = _history_path(section_name)
        historico = load_json(historico_path, [])
        known_urls = {
            canonical_url(n["url"])
            for n in historico
            if isinstance(n, dict) and n.get("url")
        }

        links = scrap_links(section_url, section_name)
        nuevas_seccion = []

        for url in links:
            normalized_url = canonical_url(url)
            if normalized_url in known_urls:
                logger.debug(f"Ya procesada Nueva Rioja {section_name}: {url}")
                continue

            noticia = scrap_noticia(url, section_name)
            if not noticia:
                logger.warning(f"No se pudo scrapear Nueva Rioja {section_name}: {url}")
                continue

            if is_blocked(noticia, stage=f"scrape_nuevarioja_{section_name}"):
                continue

            nuevas_seccion.append(noticia)
            historico.append(noticia)
            known_urls.add(normalized_url)
            logger.info(f"Nueva Rioja {section_name}: {noticia['titulo'][:70]}")

        if nuevas_seccion:
            save_json(historico_path, historico)
            nuevas_total.extend(nuevas_seccion)
            logger.info(f"Guardadas {len(nuevas_seccion)} noticias nuevas de Nueva Rioja {section_name}")
        else:
            logger.info(f"Sin noticias nuevas en Nueva Rioja {section_name}")

    if nuevas_total:
        pending = load_json(OUTPUT, [])
        pending.extend(nuevas_total)
        save_json(OUTPUT, pending)
        logger.info(f"Guardadas {len(nuevas_total)} noticias nuevas de Nueva Rioja en cola unificada")
    else:
        logger.info("Sin noticias nuevas en Nueva Rioja")


if __name__ == "__main__":
    main()
