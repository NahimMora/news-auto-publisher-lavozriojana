"""
Entry point: publicación de noticias en Facebook.
Lee la cola social y publica las pendientes para Facebook.
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
from meta.fb_client import post_to_facebook
from utils.logging_setup import setup_logger

logger = setup_logger("run_fb", "run_fb.log")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
META_INPUT = os.path.join(DATA_DIR, "noticias_meta.json")
FB_STATE_PATH = os.path.join(DATA_DIR, "fb_posted.json")


def _bootstrap_queue():
    """Migra noticias_meta.json a la cola social si aún no están encoladas."""
    noticias = load_json(META_INPUT, [])
    for n in noticias:
        enqueue(n, platform="facebook")


def _sync_posted_state():
    state = load_json(FB_STATE_PATH, {"posted": {}})
    posted = state.get("posted") if isinstance(state, dict) else {}
    if isinstance(posted, dict):
        sync_done_from_posted_state("facebook", set(posted.keys()))


MAX_PER_RUN = int(os.getenv("PUBLISH_MAX_PER_RUN", "10"))


def main():
    logger.info("=== Iniciando publicación en Facebook ===")
    _bootstrap_queue()
    _sync_posted_state()

    todos = get_pending("facebook")
    pendientes = get_pending("facebook", max_items=MAX_PER_RUN)
    logger.info(f"Facebook: {len(todos)} en cola, publicando {len(pendientes)} en este ciclo")

    publicadas = 0
    for noticia in pendientes:
        ok = post_to_facebook(noticia)
        if ok:
            mark_done(noticia, "facebook")
            publicadas += 1
            throttle()
        else:
            time.sleep(random.uniform(5, 10))

    compact_queue()
    logger.info(f"Facebook: {publicadas}/{len(pendientes)} publicadas, {len(todos) - publicadas} restantes en cola")


if __name__ == "__main__":
    main()
