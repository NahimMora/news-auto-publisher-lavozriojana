"""Parser genérico de RSS 2.0 / Atom (stdlib, sin dependencias nuevas).

Estrategia A del orden de preferencia de la Parte 21: la más barata, rápida y
estable cuando existe.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from sources.contract import OfficialSourceItem
from utils.logging_setup import setup_logger

logger = setup_logger("sources.strategies.rss", "official_sources.log")

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", text or "")).strip()


def _text(element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def parse_rss(xml_text: str, *, source_id: str, category: str = "", max_items: int = 20) -> list[OfficialSourceItem]:
    """Nunca lanza por XML inválido: devuelve lista vacía y loguea (Parte 60)."""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("RSS/Atom inválido para %s: %s", source_id, exc)
        return []

    items: list[OfficialSourceItem] = []

    # RSS 2.0: rss/channel/item
    for item in root.findall("./channel/item")[:max_items]:
        title = _text(item, "title")
        link = _text(item, "link")
        if not title or not link:
            continue
        items.append(
            OfficialSourceItem(
                source_id=source_id,
                title=title,
                url=link,
                published_at=_text(item, "pubDate"),
                excerpt=_strip_html(_text(item, "description"))[:500],
                category=category,
                raw_metadata={"guid": _text(item, "guid")},
            )
        )

    if items:
        return items[:max_items]

    # Atom: feed/entry
    for entry in root.findall("atom:entry", _ATOM_NS)[:max_items]:
        title_el = entry.find("atom:title", _ATOM_NS)
        title = (title_el.text or "").strip() if title_el is not None else ""
        link_el = entry.find("atom:link", _ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        if not title or not link:
            continue
        summary_el = entry.find("atom:summary", _ATOM_NS)
        updated_el = entry.find("atom:updated", _ATOM_NS)
        items.append(
            OfficialSourceItem(
                source_id=source_id,
                title=title,
                url=link,
                published_at=(updated_el.text or "").strip() if updated_el is not None else "",
                excerpt=_strip_html(summary_el.text or "")[:500] if summary_el is not None else "",
                category=category,
            )
        )

    return items[:max_items]
