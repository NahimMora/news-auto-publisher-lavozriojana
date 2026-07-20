"""
Entry point: publicación de noticias en Instagram.
Lee la cola social y publica las pendientes para Instagram.
"""
import os
import sys
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from utils.social_queue import get_pending, mark_done, compact_queue, enqueue, sync_done_from_posted_state
from utils.file_manager import load_json
from utils.publish_throttle import throttle
from utils.editorial_priority import item_category, item_is_breaking
from meta.ig_client import post_to_instagram, is_rate_limited, IGRateLimitError
from utils.logging_setup import setup_logger

logger = setup_logger("run_ig", "run_ig.log")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
META_INPUT = os.path.join(DATA_DIR, "noticias_meta.json")
IG_STATE_PATH = os.path.join(DATA_DIR, "ig_posted.json")

# Instagram no publica todas las categorías (evita "explotar" el feed):
# solo Interior, Sociedad y Política salen de forma rutinaria. Cualquier
# noticia marcada como "Último Momento" (utils.editorial_priority.is_breaking)
# se publica igual, sin importar su categoría.
IG_ALLOWED_CATEGORIES = {
    c.strip() for c in os.getenv(
        "IG_ALLOWED_CATEGORIES", "interior,sociedad,politica"
    ).lower().split(",") if c.strip()
}


def _allowed_for_instagram(noticia: dict) -> bool:
    if item_category(noticia) in IG_ALLOWED_CATEGORIES:
        return True
    return item_is_breaking(noticia)


def _bootstrap_queue():
    noticias = load_json(META_INPUT, [])
    omitidas = 0
    for n in noticias:
        if not _allowed_for_instagram(n):
            omitidas += 1
            continue
        enqueue(n, platform="instagram")
    if omitidas:
        logger.info(
            f"Instagram: {omitidas} noticias omitidas por categoría "
            f"(fuera de {sorted(IG_ALLOWED_CATEGORIES)} y sin marca de Último Momento)"
        )


def _sync_posted_state():
    state = load_json(IG_STATE_PATH, {"posted": {}})
    posted = state.get("posted") if isinstance(state, dict) else {}
    if isinstance(posted, dict):
        sync_done_from_posted_state("instagram", set(posted.keys()))


MAX_PER_RUN = int(os.getenv("IG_MAX_PER_RUN", "1"))


def main():
    logger.info("=== Iniciando publicación en Instagram ===")

    _sync_posted_state()

    if is_rate_limited():
        logger.warning("Instagram: publicación omitida por backoff de rate limit activo")
        return

    _bootstrap_queue()
    _sync_posted_state()

    todos = get_pending("instagram")
    pendientes = get_pending("instagram", max_items=MAX_PER_RUN)
    logger.info(f"Instagram: {len(todos)} en cola, publicando {len(pendientes)} en este ciclo")

    publicadas = 0
    for noticia in pendientes:
        try:
            ok = post_to_instagram(noticia)
        except IGRateLimitError:
            logger.warning("Instagram: rate limit alcanzado, deteniendo ciclo actual")
            break
        if ok:
            mark_done(noticia, "instagram")
            publicadas += 1
            throttle()
        else:
            time.sleep(random.uniform(10, 20))

    compact_queue()
    logger.info(f"Instagram: {publicadas}/{len(pendientes)} publicadas, {len(todos) - publicadas} restantes en cola")


if __name__ == "__main__":
    main()
