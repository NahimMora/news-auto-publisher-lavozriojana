"""Estrategia genérica HTML_INDEX (Parte 21, opción D): sin RSS/JSON disponible.

Heurística deliberadamente conservadora: mejor devolver menos items reales
que inventar estructura. Cada fuente puede no tener fecha visible en el
listado; en ese caso ``published_at`` queda vacío (nunca se inventa).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from sources.contract import OfficialSourceItem
from utils.logging_setup import setup_logger

logger = setup_logger("sources.strategies.html_index", "official_sources.log")

MIN_LINK_TEXT_CHARS = 15
MIN_PATH_SEGMENTS = 2

_DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?)\b",
    re.IGNORECASE,
)
_NAV_WORDS = {
    "inicio", "contacto", "nosotros", "institucional", "buscar", "menu",
    "iniciar sesion", "acceder", "mapa del sitio", "accesibilidad",
}


def _looks_like_article_path(path: str) -> bool:
    segments = [segment for segment in path.strip("/").split("/") if segment]
    return len(segments) >= MIN_PATH_SEGMENTS


def parse_html_index(
    html_text: str,
    *,
    source_id: str,
    base_url: str,
    category: str = "",
    max_items: int = 15,
) -> list[OfficialSourceItem]:
    """Nunca lanza por HTML inválido: devuelve lista vacía y loguea (Parte 60)."""
    if not html_text or not html_text.strip():
        return []
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception as exc:  # BeautifulSoup rara vez lanza, pero no debe tumbar el ciclo
        logger.warning("HTML inválido para %s: %s", source_id, exc)
        return []

    base_host = urlsplit(base_url).hostname or ""
    items: list[OfficialSourceItem] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if len(text) < MIN_LINK_TEXT_CHARS or text.lower() in _NAV_WORDS:
            continue

        absolute_url = urljoin(base_url, anchor["href"])
        parsed = urlsplit(absolute_url)
        if parsed.hostname != base_host or parsed.scheme not in {"http", "https"}:
            continue
        if not _looks_like_article_path(parsed.path):
            continue
        if absolute_url in seen_urls:
            continue

        published_at = ""
        container = anchor.find_parent(["article", "li", "div"]) or anchor.parent
        if container is not None:
            match = _DATE_RE.search(container.get_text(" ", strip=True))
            if match:
                published_at = match.group(0)

        seen_urls.add(absolute_url)
        items.append(
            OfficialSourceItem(
                source_id=source_id,
                title=text[:280],
                url=absolute_url,
                published_at=published_at,
                category=category,
            )
        )
        if len(items) >= max_items:
            break

    return items
