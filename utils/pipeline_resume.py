import os
from datetime import datetime
from utils.file_manager import load_json, save_json

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
RESUME_PATH = os.path.join(DATA_DIR, "pipeline_resume_state.json")


def _load() -> dict:
    return load_json(RESUME_PATH, {"stages": {}})


def _save(state: dict) -> None:
    save_json(RESUME_PATH, state)


def is_done(article_id: str, stage: str) -> bool:
    state = _load()
    return stage in state.get("stages", {}).get(article_id, {})


def mark_stage(article_id: str, stage: str, meta: dict = None) -> None:
    state = _load()
    state.setdefault("stages", {}).setdefault(article_id, {})[stage] = {
        "ts": datetime.now().isoformat(),
        **(meta or {}),
    }
    _save(state)


def clear_article(article_id: str) -> None:
    state = _load()
    state.get("stages", {}).pop(article_id, None)
    _save(state)
