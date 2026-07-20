"""
Gestión de flags editoriales (isBreaking, isFeatured) para la WebApp.

Solo puede haber un breaking activo y un featured activo a la vez.
Antes de activar uno nuevo, llama PATCH para desactivar el anterior.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from utils.editorial_priority import is_breaking as _is_breaking
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger

logger = setup_logger("editorial_flags", "publish_web.log")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
FLAGS_PATH = os.path.join(DATA_DIR, "editorial_flags.json")

# Solo estas categorías pueden activar featured
_FEATURED_CATEGORIES = {"politica", "economia", "interior", "sociedad", "policiales"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def detect_breaking(titulo: str, category_slug: str) -> bool:
    """True si el título contiene una keyword de urgencia y la categoría lo permite.

    Delega en utils.editorial_priority.is_breaking, el modelo único de
    "Último Momento" compartido con la cola social (social_queue.py/run_ig.py).
    """
    return _is_breaking(titulo, category_slug)


def detect_featured(category_slug: str, quality_score: float) -> bool:
    """True si la nota tiene calidad suficiente para ser el destacado del ciclo."""
    min_score = _env_float("FEATURED_MIN_QUALITY_SCORE", 0.88)
    if category_slug not in _FEATURED_CATEGORIES:
        return False
    return quality_score >= min_score


def load_flags() -> dict:
    return load_json(FLAGS_PATH, {"breaking": None, "featured": None})


def save_flags(flags: dict) -> None:
    save_json(FLAGS_PATH, flags)


def _webapp_config() -> tuple[str, str, int]:
    base_url = os.getenv("WEBAPP_BASE_URL", "").strip()
    api_key = (
        os.getenv("PRIVATE_API_KEY", "").strip()
        or os.getenv("WEBAPP_API_KEY", "").strip()
    )
    timeout = int(os.getenv("WEBAPP_REQUEST_TIMEOUT", "30"))
    return base_url, api_key, timeout


def _patch_post(post_id: str, fields: dict) -> bool:
    """Llama PATCH /api/private/posts/{id} con los campos dados."""
    base_url, api_key, timeout = _webapp_config()
    if not base_url or base_url == "PENDIENTE" or not api_key or api_key == "PENDIENTE":
        logger.warning("WebApp no configurada, omitiendo PATCH del post %s", post_id)
        return False

    endpoint = f"{base_url.rstrip('/')}/api/private/posts/{post_id}"
    headers = {"Content-Type": "application/json", "x-api-key": api_key}
    try:
        response = requests.patch(endpoint, json=fields, headers=headers, timeout=timeout)
        if response.status_code in (200, 204):
            logger.info("PATCH /posts/%s %s → OK", post_id, fields)
            return True
        logger.warning(
            "PATCH /posts/%s devolvió HTTP %s: %s",
            post_id, response.status_code, response.text[:200],
        )
        return False
    except requests.RequestException as exc:
        logger.error("Error de red en PATCH /posts/%s: %s", post_id, exc)
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clear_breaking(flags: dict) -> dict:
    """Desactiva isBreaking en el post anterior y limpia el registro."""
    prev = flags.get("breaking")
    if prev and prev.get("post_id"):
        _patch_post(prev["post_id"], {"isBreaking": False})
    flags["breaking"] = None
    return flags


def clear_featured(flags: dict) -> dict:
    """Desactiva isFeatured en el post anterior y limpia el registro."""
    prev = flags.get("featured")
    if prev and prev.get("post_id"):
        _patch_post(prev["post_id"], {"isFeatured": False, "editorialPriority": 0})
    flags["featured"] = None
    return flags


def register_breaking(flags: dict, post_id: str) -> dict:
    flags["breaking"] = {"post_id": post_id, "activated_at": _now_iso()}
    return flags


def register_featured(flags: dict, post_id: str) -> dict:
    flags["featured"] = {"post_id": post_id, "activated_at": _now_iso()}
    return flags


def resolve_post_id(response_data: dict | None) -> str:
    """Extrae el ID del post de la respuesta de la WebApp."""
    if not isinstance(response_data, dict):
        return ""
    data = response_data.get("data") or response_data
    if not isinstance(data, dict):
        return ""
    for key in ("id", "postId", "post_id"):
        value = data.get(key)
        if value:
            return str(value)
        nested = data.get("post") or data.get("article") or data.get("news")
        if isinstance(nested, dict):
            value = nested.get(key)
            if value:
                return str(value)
    return ""
