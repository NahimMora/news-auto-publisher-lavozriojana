"""Estrategias JSON para fuentes oficiales cuyo listado HTML se arma con
JavaScript (el HTML estático no trae notas):

* ``wordpress_json``: API REST estándar de WordPress
  (``/wp-json/wp/v2/posts?_fields=date,link,title``), p. ej. Hacienda.
* ``neotec_json``: API del portal del Gobierno de La Rioja
  (``larioja.neotec.com.ar/api/v1/obtener_noticias.php``); el artículo se
  abre en ``larioja.gob.ar/noticias/noticia.php?idnoticia=<id>``.

Igual que HTML_INDEX: nunca lanzan por un JSON inválido (lista vacía) y no
inventan fechas ni textos.
"""
from __future__ import annotations

import html
import json
import re

from sources.contract import OfficialSourceItem
from utils.logging_setup import setup_logger

logger = setup_logger("sources.strategies.json_api", "official_sources.log")

GOBIERNO_ARTICLE_URL = "https://larioja.gob.ar/noticias/noticia.php?idnoticia={id}"


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def _load(text: str, source_id: str):
    try:
        return json.loads(text or "")
    except ValueError:
        logger.warning("JSON inválido para %s", source_id)
        return None


def parse_wordpress_json(text: str, *, source_id: str, category: str = "", max_items: int = 15) -> list[OfficialSourceItem]:
    data = _load(text, source_id)
    if not isinstance(data, list):
        return []
    items = []
    for post in data[:max_items]:
        if not isinstance(post, dict):
            continue
        title = _text((post.get("title") or {}).get("rendered") if isinstance(post.get("title"), dict) else post.get("title"))
        link = str(post.get("link") or "")
        if len(title) < 8 or not link.startswith("http"):
            continue
        items.append(OfficialSourceItem(source_id=source_id, title=title[:280], url=link, published_at=str(post.get("date") or ""), category=category))
    return items


def parse_neotec_json(text: str, *, source_id: str, category: str = "", max_items: int = 15) -> list[OfficialSourceItem]:
    data = _load(text, source_id)
    if not isinstance(data, dict) or str(data.get("estado")) != "1" or not isinstance(data.get("datos"), list):
        return []
    items = []
    for row in data["datos"][:max_items]:
        if not isinstance(row, dict) or not str(row.get("idnoticia") or "").isdigit():
            continue
        title = _text(row.get("titulo"))
        if len(title) < 8:
            continue
        items.append(
            OfficialSourceItem(
                source_id=source_id,
                title=title[:280],
                url=GOBIERNO_ARTICLE_URL.format(id=row["idnoticia"]),
                published_at=str(row.get("fecha_seteada") or ""),
                excerpt=_text(row.get("copete"))[:600],
                category=category,
            )
        )
    return items
