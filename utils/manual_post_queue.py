from __future__ import annotations

import time

from utils.file_manager import load_json, update_json, update_json_files
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("manual_post_queue", "manual_post_queue.log")

DRAFTS_PATH = str(data_dir() / "publicaciones_manuales_borradores.json")
PUBLISHED_PATH = str(data_dir() / "publicaciones_manuales_publicadas.json")


def save_post_draft(payload: dict) -> tuple[dict, bool]:
    from pipeline.custom_post import build_custom_noticia

    item = build_custom_noticia(payload, require_image=False)
    item["manual_status"] = "draft"
    item["draft_saved_at"] = int(time.time())

    added = {"value": True}

    def upsert(drafts):
        for index, existing in enumerate(drafts):
            if isinstance(existing, dict) and existing.get("dedup_key") == item["dedup_key"]:
                drafts[index] = item
                added["value"] = False
                return drafts
        drafts.append(item)
        return drafts

    update_json(DRAFTS_PATH, upsert, [], expected_type=list)
    logger.info(
        "Borrador de publicación %s: %s",
        "guardado" if added["value"] else "actualizado",
        item.get("titulo", "")[:70],
    )
    return item, added["value"]


def record_published(item: dict, public_url: str) -> None:
    dedup_key = item.get("dedup_key")
    removed = {"value": False}

    def persist(files):
        history = files[PUBLISHED_PATH]
        if not any(
            isinstance(existing, dict)
            and dedup_key
            and existing.get("dedup_key") == dedup_key
            for existing in history
        ):
            history.append(
                {**item, "web_url": public_url, "published_at_ts": int(time.time())}
            )
        drafts = files[DRAFTS_PATH]
        remaining = [
            draft
            for draft in drafts
            if not (
                dedup_key
                and isinstance(draft, dict)
                and draft.get("dedup_key") == dedup_key
            )
        ]
        removed["value"] = len(remaining) != len(drafts)
        files[PUBLISHED_PATH] = history
        files[DRAFTS_PATH] = remaining
        return files

    update_json_files(
        {
            PUBLISHED_PATH: ([], list),
            DRAFTS_PATH: ([], list),
        },
        persist,
        save_order=[PUBLISHED_PATH, DRAFTS_PATH],
    )
    if removed["value"]:
        logger.info("Borrador removido tras publicar: %s", item.get("titulo", "")[:70])


def load_post_state() -> dict:
    drafts = load_json(DRAFTS_PATH, [])
    published = load_json(PUBLISHED_PATH, [])
    return {
        "drafts": drafts if isinstance(drafts, list) else [],
        "published": published if isinstance(published, list) else [],
    }
