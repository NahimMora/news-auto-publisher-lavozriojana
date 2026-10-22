"""
Scraping de las fuentes judiciales oficiales de La Rioja.

- Ministerio Público Fiscal (mpflarioja.gob.ar): RSS de WordPress en ``/feed/``;
  la nota completa y su foto están en ``div.entry-content`` (sin ``og:image``).
- Función Judicial (justicialarioja.gob.ar): RSS de Joomla de la categoría de
  noticias. El ``<link>`` de todos los ítems apunta a la categoría: la URL
  propia de cada nota está en ``<guid>``. El cuerpo está en ``article``.

Ambas publican casi todos los días y repiten casos entre sí y con los medios:
el puntaje y el control de mismo caso viven en ``utils/judicial_sources.py``.
"""
import os
import re
import shutil
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from utils.image_processor import FOTOS_DIR, optimize_image, process_image
from utils.judicial_sources import JUDICIAL_SOURCE_PREFIX
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get
from utils.scraper_contract import (
    ArticleScrapeResult,
    LinkScrapeResult,
    request_error_details,
)
from utils.stage_result import StageStatus
from utils.url_normalization import canonical_url, url_hash

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

SOURCES = {
    "mpf": {
        "feed": "https://www.mpflarioja.gob.ar/feed/",
        "host": "mpflarioja.gob.ar",
        "url_field": "link",
        "body": "div.entry-content, article",
    },
    "justicia": {
        "feed": (
            "https://www.justicialarioja.gob.ar/index.php/typography/"
            "noticias-e-informacion-general?format=feed&type=rss"
        ),
        "host": "justicialarioja.gob.ar",
        "url_field": "guid",
        "body": 'div[itemprop="articleBody"], article',
    },
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))
# Fecha del ``pubDate`` del RSS por URL: la página de la Función Judicial no
# trae fecha y sin fecha la reescritura descarta la nota por el corte operativo.
_FEED_DATES: dict[str, str] = {}

# Logos e íconos del sitio: no sirven como foto de la nota. El fondo
# institucional de la Función Judicial sí (sin foto la Web no publica).
_GENERIC_IMAGE_RE = re.compile(r"logo|escudo|icono|icon|banner", re.IGNORECASE)


def scrap_links_result(key: str) -> LinkScrapeResult:
    """URLs de las últimas notas del RSS de la fuente ``key``."""
    config = SOURCES[key]
    logger = setup_logger(f"scraper.judicial.{key}.links", "scrapers.log")
    try:
        r = requests.get(config["feed"], headers=HEADERS, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        logger.error(f"RSS ilegible en {config['feed']}: {e}")
        return LinkScrapeResult(status=StageStatus.FAILED, error_type="parse_error", message=str(e))
    except Exception as e:
        logger.error(f"Error accediendo a {config['feed']}: {e}")
        error_type, http_status = request_error_details(e)
        return LinkScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    links: list[str] = []
    for item in root.iter("item"):
        url = str(item.findtext(config["url_field"]) or "").strip()
        if not _is_article_url(url, config["host"]) or canonical_url(url) in links:
            continue
        links.append(canonical_url(url))
        published = _feed_date(item.findtext("pubDate"))
        if published:
            _FEED_DATES[canonical_url(url)] = published
        if len(links) >= MAX_LINKS:
            break

    logger.info(f"Judicial {key}: {len(links)} notas en el RSS")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def _is_article_url(url: str, host: str) -> bool:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    return parsed.scheme in {"http", "https"} and netloc == host and len(parsed.path.strip("/")) > 10


def scrap_noticia_result(url: str, key: str) -> ArticleScrapeResult:
    """Título, cuerpo, foto y fecha de una nota judicial."""
    config = SOURCES[key]
    logger = setup_logger(f"scraper.judicial.{key}.noticia", "scrapers.log")
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
    content = soup.select_one(config["body"])
    parrafos = _extract_paragraphs(content)
    if not titulo or not parrafos:
        logger.warning(f"Sin {'título' if not titulo else 'cuerpo'} en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="title_missing" if not titulo else "body_missing",
        )

    imagen_url = _extract_image(content, url)
    imagen_local, imagen_optimizada = _download_image(imagen_url, key, url, logger)
    article = {
        "titulo": titulo,
        "url": url,
        "canonical_url": canonical_url(url),
        "seccion": "policiales",
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": _extract_date(soup, url) or _FEED_DATES.get(canonical_url(url)),
        "source": f"{JUDICIAL_SOURCE_PREFIX}{key}",
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
    for selector in ("h1.entry-title", "article h1", "h1", "article h2"):
        el = soup.select_one(selector)
        text = _clean_text(el.get_text(" ", strip=True)) if el else ""
        if text:
            # La Función Judicial titula en mayúsculas: se normaliza a oración.
            return text[:1] + text[1:].lower() if text.isupper() else text
    return None


def _extract_paragraphs(content) -> list[str]:
    if content is None:
        return []
    parrafos = []
    for p in content.find_all("p"):
        text = _clean_text(p.get_text(" ", strip=True))
        if len(text) >= 40 and not text.lower().startswith(("compartir", "fuente:", "foto:")):
            parrafos.append(text)
    return parrafos


def _extract_image(content, url: str) -> str | None:
    if content is None:
        return None
    for img in content.find_all("img"):
        src = str(img.get("src") or img.get("data-src") or "").strip()
        if src and not _GENERIC_IMAGE_RE.search(src):
            return urljoin(url, src)
    return None


def _extract_date(soup: BeautifulSoup, url: str) -> str | None:
    for prop in ("article:published_time", "og:updated_time"):
        meta = soup.find("meta", property=prop)
        if meta and meta.get("content"):
            return meta["content"][:10]
    el = soup.find("time", attrs={"datetime": True})
    if el:
        return str(el["datetime"])[:10]
    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def _feed_date(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(str(value or "")).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _download_image(imagen_url: str | None, key: str, article_url: str, logger) -> tuple[str | None, str | None]:
    if not imagen_url:
        return None, None
    uid = url_hash(article_url)
    raw_path = os.path.join(FOTOS_DIR, f"{JUDICIAL_SOURCE_PREFIX}{key}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"{JUDICIAL_SOURCE_PREFIX}{key}_{uid}_opt.jpg")
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


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
