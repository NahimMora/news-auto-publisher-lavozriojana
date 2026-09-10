"""Backfill del archivo propio desde el CMS público (Parte 6).

``noticias_web_publicadas.json`` es sólo una ventana rodante de 7 días (ver
``pipeline/node_webapp/publisher.py::_load_published_history`` y
``docs/EDITORIAL_CONTEXT_PROGRESS.md``), no un histórico completo. El CMS
público (``GET /api/public/posts``, ya existente y de solo lectura) es la
fuente de backfill real para profundidad histórica: es nuestro propio sitio,
no cuenta como "scraping de otros medios".

Nota de implementación: los nombres de campo exactos del endpoint se
tomaron de la auditoría del repo ``LaVozRiojana`` con fallbacks razonables;
confirmar contra una respuesta real antes de depender de esto en producción
(ver docs/DECISIONS.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import requests

from editorial_context import archive_index as ai
from utils.logging_setup import setup_logger
from utils.safe_http import UnsafeURLError, safe_get

logger = setup_logger("editorial_context.archive_backfill", "editorial_context.log")

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 50


@dataclass
class BackfillReport:
    pages_fetched: int = 0
    articles_seen: int = 0
    articles_upserted: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pages_fetched": self.pages_fetched,
            "articles_seen": self.articles_seen,
            "articles_upserted": self.articles_upserted,
            "errors": list(self.errors),
        }


def _webapp_base_url() -> str:
    return os.getenv("WEBAPP_BASE_URL", "").strip().rstrip("/")


def _first(post: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = post.get(key)
        if value:
            return str(value)
    return default


def _post_to_article(post: dict) -> ai.ArchiveArticle:
    category = post.get("category")
    category_slug = _first(post, "categorySlug") or (category.get("slug") if isinstance(category, dict) else "")
    author = post.get("author")
    author_name = _first(post, "authorName") or (author.get("name") if isinstance(author, dict) else "")
    tags = post.get("tags") or []
    tag_names = [
        str(tag.get("name") if isinstance(tag, dict) else tag) for tag in tags if tag
    ]
    return ai.ArchiveArticle(
        article_id=_first(post, "id", "slug"),
        post_id=_first(post, "id"),
        slug=_first(post, "slug"),
        canonical_url=_first(post, "url", "canonicalUrl"),
        title=_first(post, "title"),
        excerpt=_first(post, "excerpt"),
        category=str(category_slug or ""),
        published_at=_first(post, "publishedAt"),
        updated_at=_first(post, "updatedAt"),
        author=str(author_name or ""),
        tags=tag_names,
        story_key=_first(post, "storyKey"),
        content_summary=_first(post, "excerpt"),
        source_kind="own_archive",
    )


def backfill_from_cms_api(
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
    path: Path | str | None = None,
    resolver=None,
) -> BackfillReport:
    """Pagina el endpoint público existente e ingesta cada post.

    Se detiene en la primera página vacía o al llegar a ``max_pages``: no
    hace requests repetidos inútiles (Parte 23).
    """
    base_url = _webapp_base_url()
    report = BackfillReport()
    if not base_url or base_url == "PENDIENTE":
        report.errors.append("WEBAPP_BASE_URL no configurada")
        return report

    for page in range(1, max_pages + 1):
        endpoint = f"{base_url}/api/public/posts?page={page}&pageSize={page_size}"
        try:
            response = safe_get(endpoint, timeout=20, resolver=resolver)
        except (UnsafeURLError, requests.RequestException) as exc:
            report.errors.append(f"page={page}: {exc}")
            break
        if response.status_code != 200:
            report.errors.append(f"page={page}: http_status={response.status_code}")
            break
        try:
            payload = response.json()
        except ValueError:
            report.errors.append(f"page={page}: respuesta no es JSON válido")
            break

        posts = payload.get("data") or payload.get("posts") or payload.get("items") or []
        if not posts:
            break
        report.pages_fetched += 1

        for post in posts:
            report.articles_seen += 1
            if not (post.get("id") or post.get("slug")):
                report.errors.append("post sin id ni slug: se descarta")
                continue
            try:
                ai.upsert_article(_post_to_article(post), path=path)
                report.articles_upserted += 1
            except Exception as exc:
                report.errors.append(f"post={post.get('slug') or post.get('id')}: {exc}")

        if len(posts) < page_size:
            break

    logger.info(
        "Backfill CMS: %s páginas, %s posts vistos, %s indexados, %s errores",
        report.pages_fetched,
        report.articles_seen,
        report.articles_upserted,
        len(report.errors),
    )
    return report
