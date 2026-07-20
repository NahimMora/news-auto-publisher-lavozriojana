from __future__ import annotations

import os
import time

from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger

logger = setup_logger("manual_post_queue")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DRAFTS_PATH = os.path.join(DATA_DIR, "publicaciones_manuales_borradores.json")
PUBLISHED_PATH = os.path.join(DATA_DIR, "publicaciones_manuales_publicadas.json")


def save_post_draft(payload: dict) -> tuple[dict, bool]:
    from pipeline.custom_post import build_custom_noticia

    item = build_custom_noticia(payload, require_image=False)
    item["manual_status"] = "draft"
    item["draft_saved_at"] = int(time.time())

    drafts = load_json(DRAFTS_PATH, [])
    if not isinstance(drafts, list):
        drafts = []

    for index, existing in enumerate(drafts):
        if isinstance(existing, dict) and existing.get("dedup_key") == item["dedup_key"]:
            drafts[index] = item
            save_json(DRAFTS_PATH, drafts)
            logger.info("Borrador de publicacion actualizado: %s", item.get("titulo", "")[:70])
            return item, False

    drafts.append(item)
    save_json(DRAFTS_PATH, drafts)
    logger.info("Borrador de publicacion guardado: %s", item.get("titulo", "")[:70])
    return item, True


def record_published(item: dict, public_url: str) -> None:
    history = load_json(PUBLISHED_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append({**item, "web_url": public_url, "published_at_ts": int(time.time())})
    save_json(PUBLISHED_PATH, history)

    # Si esta publicacion venia de un borrador, sacarlo de la lista para
    # evitar que se pueda volver a publicar por error (duplicaria el articulo).
    dedup_key = item.get("dedup_key")
    if not dedup_key:
        return
    drafts = load_json(DRAFTS_PATH, [])
    if not isinstance(drafts, list):
        return
    remaining = [d for d in drafts if not (isinstance(d, dict) and d.get("dedup_key") == dedup_key)]
    if len(remaining) != len(drafts):
        save_json(DRAFTS_PATH, remaining)
        logger.info("Borrador removido tras publicar: %s", item.get("titulo", "")[:70])


def load_post_state() -> dict:
    drafts = load_json(DRAFTS_PATH, [])
    published = load_json(PUBLISHED_PATH, [])
    return {
        "drafts": drafts if isinstance(drafts, list) else [],
        "published": published if isinstance(published, list) else [],
    }
