"""Ubicación de Instagram (``location_id``) según la localidad de la nota.

La localidad sale del campo ``locality`` que completa la reescritura sólo si
el texto la nombra (nunca se infiere). Se busca en ``config/ig_locations.json``;
sin ID cargado, la publicación sale sin ubicación, como antes. La API de
búsqueda de lugares de Meta está deprecada: los IDs se cargan a mano desde
``instagram.com/explore/locations/<ID>/``.

Apagado por defecto: ``IG_LOCATION_ENABLED``. Las historias no admiten ubicación.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache

from utils.logging_setup import setup_logger

logger = setup_logger("ig_location", "gov_tags.log")

LOCATIONS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "ig_locations.json")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def enabled() -> bool:
    return str(os.getenv("IG_LOCATION_ENABLED", "false")).strip().lower() in _TRUE


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(c) != "Mn"
    ).lower().strip()


@lru_cache(maxsize=1)
def _locations(path: str = LOCATIONS_PATH) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle).get("locations") or {}
    except (OSError, ValueError) as exc:
        logger.error("Tabla de ubicaciones ilegible (%s): sin ubicación", type(exc).__name__)
        return {}
    return {_fold(name): str(value).strip() for name, value in raw.items() if re.fullmatch(r"\d{5,20}", str(value).strip())}


def location_id_for(noticia: dict) -> str:
    if not enabled():
        return ""
    locality = str(noticia.get("locality") or "")
    # "Capital · Chilecito": se usa la primera.
    first = locality.split("·", 1)[0]
    return _locations().get(_fold(first), "")
