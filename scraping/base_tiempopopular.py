"""
Lógica compartida de scraping para tiempopopular.com.ar.
Todas las secciones tienen la misma estructura WordPress, solo cambia la URL base.
"""
import os
import re
import shutil
import requests
from bs4 import BeautifulSoup
from utils.url_normalization import canonical_url, url_hash
from utils.image_processor import process_image, optimize_image, FOTOS_DIR
from utils.logging_setup import setup_logger

BASE_SITE = "https://www.tiempopopular.com.ar"

# Patrón de URL de artículo: /YYYY/MM/DD/slug/
ARTICLE_URL_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/.+/$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))


# ── LINKS SCRAPER ────────────────────────────────────────────────────────────

def scrap_links(section_url: str, section_name: str) -> list[str]:
    """
    Extrae URLs de artículos de una sección de tiempopopular.com.ar.
    Selector principal: li > h3 > a (estructura estándar del sitio).
    """
    logger = setup_logger(f"scraper.{section_name}.links")
    try:
        r = requests.get(section_url, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {section_url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    links = []

    # Selector principal: li > h3 > a (estructura confirmada del sitio)
    for a in soup.select("li h3 a[href]"):
        href = a.get("href", "").strip()
        if _is_article_url(href) and href not in seen:
            seen.add(href)
            links.append(canonical_url(href))
        if len(links) >= MAX_LINKS:
            break

    # Fallback: cualquier link con patrón de fecha /YYYY/MM/DD/
    if not links:
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if _is_article_url(href) and href not in seen:
                seen.add(href)
                links.append(canonical_url(href))
            if len(links) >= MAX_LINKS:
                break

    logger.info(f"{section_name.capitalize()}: {len(links)} artículos encontrados")
    return links


def _is_article_url(href: str) -> bool:
    """Valida que la URL sea un artículo (no una sección ni página de categoría)."""
    if not href or not href.startswith("http"):
        return False
    if BASE_SITE not in href:
        return False
    path = href.replace(BASE_SITE, "")
    return bool(ARTICLE_URL_RE.search(path))


# ── NOTICIA SCRAPER ──────────────────────────────────────────────────────────

def scrap_noticia(url: str, section_name: str) -> dict | None:
    """
    Extrae título, párrafos e imagen de un artículo de tiempopopular.com.ar.
    Estructura WordPress: h1 para título, .entry-content para cuerpo, og:image para imagen.
    """
    logger = setup_logger(f"scraper.{section_name}.noticia")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {url}: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # ── Título ───────────────────────────────────────────────
    titulo = _extract_title(soup, url)
    if not titulo:
        logger.warning(f"Sin título en: {url}")
        return None

    # ── Párrafos del cuerpo ──────────────────────────────────
    parrafos = _extract_paragraphs(soup)
    if not parrafos:
        logger.warning(f"Sin contenido en: {url}")
        return None

    # ── Imagen destacada ─────────────────────────────────────
    imagen_url = _extract_image(soup)

    # ── Fecha de publicación ─────────────────────────────────
    fecha = _extract_date(soup, url)

    # ── Descarga y optimización ──────────────────────────────
    imagen_local, imagen_optimizada = _download_image(imagen_url, section_name, url, logger)

    return {
        "titulo": titulo,
        "url": url,
        "canonical_url": canonical_url(url),
        "seccion": section_name,
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": fecha,
        "source": f"tiempopopular_{section_name}",
    }


def _extract_title(soup: BeautifulSoup, url: str) -> str | None:
    # 1. h1.entry-title (WordPress estándar)
    for sel in ["h1.entry-title", "h1.post-title", "h1"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text:
                return text
    # 2. og:title como último recurso
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    # Contenedor principal del artículo en WordPress
    content = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.post-content")
        or soup.select_one("div.td-post-content")
        or soup.select_one("article")
    )
    if not content:
        return []

    parrafos = []
    for p in content.find_all("p"):
        # Ignorar párrafos cortos, vacíos o de publicidad/créditos
        text = p.get_text(separator=" ", strip=True)
        if len(text) < 40:
            continue
        # Filtrar párrafos de créditos de foto y similares
        lower = text.lower()
        if any(kw in lower for kw in ["foto:", "fuente:", "crédito:", "credito:"]):
            continue
        parrafos.append(text)

    return parrafos


def _extract_image(soup: BeautifulSoup) -> str | None:
    # 1. og:image (más confiable, siempre apunta a la imagen destacada)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    # 2. Imagen dentro del contenido del artículo
    content = soup.select_one("div.entry-content, div.post-content, article")
    if content:
        img = content.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src and src.startswith("http"):
                return src

    # 3. Post thumbnail / featured image
    img = soup.select_one(".post-thumbnail img, .wp-post-image, .featured-image img")
    if img:
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            return src

    return None


def _extract_date(soup: BeautifulSoup, url: str) -> str | None:
    # Intentar desde el meta og:article:published_time
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        return meta["content"][:10]  # YYYY-MM-DD

    # Extraer desde la URL /YYYY/MM/DD/
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
    raw_path = os.path.join(FOTOS_DIR, f"{section_name}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"{section_name}_{uid}_opt.jpg")

    try:
        resp = requests.get(imagen_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        if not process_image(resp.content, raw_path):
            return None, None
        shutil.copy2(raw_path, opt_path)
        optimize_image(opt_path)
        return raw_path, opt_path
    except Exception as e:
        logger.warning(f"Error descargando imagen {imagen_url}: {e}")
        return None, None
