"""
Scraping de las notas locales de mediosrioja.com.ar (Medios Rioja).

WordPress con RSS en ``/feed/`` (unas 20 notas por día). El feed mezcla
locales, departamentales, nacionales, internacionales y deportes: cada ítem trae
sus categorías y sólo se piden las notas de ``Locales`` o ``Departamentales``
que no estén marcadas como ``Nacionales``/``Internacionales``. Aporta sobre
todo policiales y sucesos de Capital y del interior (choques, incendios,
causas) que Nueva Rioja y Tiempo Popular no siempre cubren.

La nota completa está en ``div.entry-content`` con ``og:image`` y
``article:published_time``. La categoría del RSS basta como vínculo riojano
(ver ``main_mediosrioja``).
"""
import os
import re
import shutil
import xml.etree.ElementTree as ET
import unicodedata
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from utils.image_processor import FOTOS_DIR, optimize_image, process_image
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get
from utils.scraper_contract import (
    ArticleScrapeResult,
    LinkScrapeResult,
    request_error_details,
)
from utils.stage_result import StageStatus
from utils.url_normalization import canonical_url, url_hash

FEED_URL = "https://mediosrioja.com.ar/feed/"
HOST = "mediosrioja.com.ar"
SOURCE_PREFIX = "mediosrioja"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))

# Categorías del feed (sin tildes, en minúscula).
LOCAL_CATEGORIES = {"locales", "departamentales"}
NON_LOCAL_CATEGORIES = {"nacionales", "internacionales"}

# Datos del RSS por URL canónica: la categoría decide la sección y el
# ``pubDate`` cubre una nota sin ``article:published_time``.
_FEED_INFO: dict[str, dict] = {}


def scrap_links_result() -> LinkScrapeResult:
    """URLs de las últimas notas locales y departamentales del RSS."""
    logger = setup_logger("scraper.mediosrioja.links", "scrapers.log")
    try:
        r = requests.get(FEED_URL, headers=HEADERS, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        logger.error(f"RSS ilegible en {FEED_URL}: {e}")
        return LinkScrapeResult(status=StageStatus.FAILED, error_type="parse_error", message=str(e))
    except Exception as e:
        logger.error(f"Error accediendo a {FEED_URL}: {e}")
        error_type, http_status = request_error_details(e)
        return LinkScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    links: list[str] = []
    skipped = 0
    for item in root.iter("item"):
        url = str(item.findtext("link") or "").strip()
        if not _is_article_url(url):
            continue
        categories = {_ascii_lower(c.text or "").strip() for c in item.findall("category")}
        if not (categories & LOCAL_CATEGORIES) or categories & NON_LOCAL_CATEGORIES:
            skipped += 1
            continue
        key = canonical_url(url)
        if key in links:
            continue
        links.append(key)
        _FEED_INFO[key] = {
            "departamental": "departamentales" in categories,
            "fecha": _feed_date(item.findtext("pubDate")),
        }
        if len(links) >= MAX_LINKS:
            break

    logger.info(f"Medios Rioja: {len(links)} notas locales en el RSS ({skipped} no locales)")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def _is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    return parsed.scheme in {"http", "https"} and netloc == HOST and len(parsed.path.strip("/")) > 10


def scrap_noticia_result(url: str) -> ArticleScrapeResult:
    """Título, cuerpo, foto y fecha de una nota de Medios Rioja."""
    logger = setup_logger("scraper.mediosrioja.noticia", "scrapers.log")
    if not _is_article_url(url):
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="url_outside_site",
        )
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {url}: {e}")
        error_type, http_status = request_error_details(e)
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    soup = BeautifulSoup(r.text, "html.parser")
    titulo = _extract_title(soup)
    parrafos = _extract_paragraphs(soup.select_one("div.entry-content"))
    if not titulo or not parrafos:
        logger.warning(f"Sin {'título' if not titulo else 'cuerpo'} en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="title_missing" if not titulo else "body_missing",
        )

    key = canonical_url(url)
    info = _FEED_INFO.get(key, {})
    seccion = "interior" if info.get("departamental") else "locales"
    imagen_url = _extract_image(soup)
    imagen_local, imagen_optimizada = _download_image(imagen_url, key, logger)
    article = {
        "titulo": titulo,
        "url": url,
        "canonical_url": key,
        "seccion": seccion,
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": _extract_date(soup) or info.get("fecha"),
        "source": f"{SOURCE_PREFIX}_{seccion}",
    }
    warnings = []
    if imagen_url and not imagen_optimizada:
        warnings.append("image_download_failed")
    return ArticleScrapeResult(
        status=StageStatus.DEGRADED if warnings else StageStatus.SUCCESS,
        article=article,
        warnings=warnings,
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    for selector in ("h1.entry-title", "article h1", "h1"):
        el = soup.select_one(selector)
        text = _clean_text(el.get_text(" ", strip=True)) if el else ""
        if text:
            return text
    return None


def _extract_paragraphs(content) -> list[str]:
    if content is None:
        return []
    parrafos = []
    for p in content.find_all("p"):
        text = _clean_text(p.get_text(" ", strip=True))
        if len(text) >= 40 and not text.lower().startswith(("compartir", "fuente:", "foto:", "te puede interesar")):
            parrafos.append(text)
    return parrafos


def _extract_image(soup: BeautifulSoup) -> str | None:
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_date(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        return meta["content"][:10]
    return None


def _feed_date(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(str(value or "")).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _download_image(imagen_url: str | None, article_url: str, logger) -> tuple[str | None, str | None]:
    if not imagen_url:
        return None, None
    uid = url_hash(article_url)
    raw_path = os.path.join(FOTOS_DIR, f"{SOURCE_PREFIX}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"{SOURCE_PREFIX}_{uid}_opt.jpg")
    try:
        resp = safe_get(imagen_url, requester=requests.get, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        if not process_image(resp.content, raw_path):
            return None, None
        shutil.copy2(raw_path, opt_path)
        optimize_image(opt_path)
        return raw_path, opt_path
    except Exception as e:
        logger.warning(f"Error descargando imagen {imagen_url}: {e}")
        return None, None


def _ascii_lower(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
