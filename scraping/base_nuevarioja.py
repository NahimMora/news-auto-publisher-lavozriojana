"""
Shared scraping logic for nuevarioja.com.ar.

The site exposes article links as relative URLs such as
/policiales/titulo-de-la-nota.htm. The scraper also accepts dated
WordPress-style URLs as a fallback.
"""
import os
import re
import shutil
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from utils.image_processor import FOTOS_DIR, optimize_image, process_image
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get
from utils.url_normalization import canonical_url, url_hash
from utils.scraper_contract import (
    ArticleScrapeResult,
    LinkScrapeResult,
    request_error_details,
)
from utils.stage_result import StageStatus

BASE_SITE = "https://nuevarioja.com.ar"
BASE_HOST = "nuevarioja.com.ar"

ARTICLE_URL_RE = re.compile(
    r"^/\d{4}/\d{2}/\d{2}/[^?#]+/?$"
    r"|^/[a-z][a-z0-9-]+/[a-z0-9-]{15,}(?:\.html?)?/?$",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))


def scrap_links_result(section_url: str, section_name: str) -> LinkScrapeResult:
    """Extract article URLs from a Nueva Rioja section."""
    logger = setup_logger(f"scraper.nuevarioja.{section_name}.links", "scrapers.log")
    try:
        r = requests.get(section_url, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {section_url}: {e}")
        error_type, http_status = request_error_details(e)
        return LinkScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    links = []

    selectors = [
        f'a[href^="/{section_name}/"]',
        f'a[href*="{BASE_HOST}/{section_name}/"]',
        "article a[href]",
        "h2 a[href], h3 a[href], .titulo a[href]",
        "a[href]",
    ]
    for selector in selectors:
        for a in soup.select(selector):
            href = a.get("href", "").strip()
            if not _is_article_url(href, section_name):
                continue
            url = canonical_url(_absolute_url(href))
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= MAX_LINKS:
                logger.info(f"Nueva Rioja {section_name}: {len(links)} articulos encontrados")
                return LinkScrapeResult(status=StageStatus.SUCCESS, links=links)

    logger.info(f"Nueva Rioja {section_name}: {len(links)} articulos encontrados")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def scrap_links(section_url: str, section_name: str) -> list[str]:
    """Compatibilidad: nuevos consumidores deben usar ``scrap_links_result``."""
    return scrap_links_result(section_url, section_name).links


def _absolute_url(href: str) -> str:
    return urljoin(BASE_SITE + "/", href)


def _is_article_url(href: str, section_name: str | None = None) -> bool:
    """Return True for article URLs, not section/tag/social URLs."""
    if not href:
        return False

    url = _absolute_url(href)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if parsed.scheme not in {"http", "https"} or host != BASE_HOST:
        return False

    path = parsed.path.rstrip("/")
    if not path or not ARTICLE_URL_RE.search(path):
        return False

    if re.match(r"^/\d{4}/\d{2}/\d{2}/", path):
        return True

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return False
    if section_name and segments[0].lower() != section_name.lower():
        return False

    slug = segments[1].lower().removesuffix(".html").removesuffix(".htm")
    return len(slug) >= 15


def scrap_noticia_result(url: str, section_name: str) -> ArticleScrapeResult:
    """Extract title, body, image and date from a Nueva Rioja article."""
    logger = setup_logger(f"scraper.nuevarioja.{section_name}.noticia", "scrapers.log")
    url = canonical_url(_absolute_url(url))
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
    if not titulo:
        logger.warning(f"Sin titulo en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="title_missing",
        )

    parrafos = _extract_paragraphs(soup)
    if not parrafos:
        logger.warning(f"Sin contenido en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="body_missing",
        )

    imagen_url = _extract_image(soup)
    fecha = _extract_date(soup, url)
    imagen_local, imagen_optimizada = _download_image(imagen_url, section_name, url, logger)

    article = {
        "titulo": titulo,
        "url": url,
        "canonical_url": canonical_url(url),
        "seccion": section_name,
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": fecha,
        "source": f"nuevarioja_{section_name}",
    }
    warnings = []
    if imagen_url and not imagen_optimizada:
        warnings.append("image_download_failed")
    return ArticleScrapeResult(
        status=StageStatus.DEGRADED if warnings else StageStatus.SUCCESS,
        article=article,
        warnings=warnings,
    )


def scrap_noticia(url: str, section_name: str) -> dict | None:
    """Compatibilidad: nuevos consumidores deben usar ``scrap_noticia_result``."""
    return scrap_noticia_result(url, section_name).article


def _extract_title(soup: BeautifulSoup) -> str | None:
    for selector in ("h1.entry-title", "h1.post-title", "h1"):
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return _clean_text(text)

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return _clean_text(og["content"])
    return None


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    content = (
        soup.select_one("article.cont-cuerpo")
        or soup.select_one(".cont-cuerpo")
        or soup.select_one("div.entry-content")
        or soup.select_one("div.post-content")
        or soup.select_one("div.td-post-content")
        or soup.select_one("article")
    )
    if not content:
        return []

    parrafos = []
    for p in content.find_all("p"):
        text = _clean_text(p.get_text(" ", strip=True))
        if len(text) < 40:
            continue
        lower = text.lower()
        if any(
            kw in lower
            for kw in (
                "foto:",
                "fuente:",
                "credito:",
                "cr\u00e9dito:",
                "unirme al canal",
                "agrandar imagen",
                "enviar",
                "imprimir",
            )
        ):
            continue
        parrafos.append(text)

    return parrafos


def _extract_image(soup: BeautifulSoup) -> str | None:
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    content = soup.select_one("article.cont-cuerpo, .cont-cuerpo, div.entry-content, div.post-content, article")
    if content:
        img = content.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                return _absolute_url(src)

    img = soup.select_one(".post-thumbnail img, .wp-post-image, .featured-image img")
    if img:
        src = img.get("src") or img.get("data-src")
        if src:
            return _absolute_url(src)

    return None


def _extract_date(soup: BeautifulSoup, url: str) -> str | None:
    for prop in ("article:published_time", "og:updated_time", "article:modified_time"):
        meta = soup.find("meta", property=prop)
        if meta and meta.get("content"):
            return meta["content"][:10]

    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def _download_image(
    imagen_url: str | None, section_name: str, article_url: str, logger
) -> tuple[str | None, str | None]:
    if not imagen_url:
        return None, None

    uid = url_hash(article_url)
    raw_path = os.path.join(FOTOS_DIR, f"nuevarioja_{section_name}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"nuevarioja_{section_name}_{uid}_opt.jpg")

    try:
        resp = safe_get(
            imagen_url,
            requester=requests.get,
            headers=HEADERS,
            timeout=20,
        )
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
    return " ".join(value.split())
