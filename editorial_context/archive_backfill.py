"""Backfill del archivo propio desde el CMS público (Parte 6).

``noticias_web_publicadas.json`` es sólo una ventana rodante de 7 días (ver
``pipeline/node_webapp/publisher.py::_load_published_history`` y
``docs/EDITORIAL_CONTEXT_PROGRESS.md``), no un histórico completo. El CMS
público (``GET /api/public/posts``, ya existente y de solo lectura) es la
fuente de backfill real para profundidad histórica: es nuestro propio sitio,
no cuenta como "scraping de otros medios".

Contrato real confirmado contra el repo ``LaVozRiojana``
(``app/api/public/posts/route.ts``, ``lib/http.ts::jsonOk``/``getPagination``,
``lib/posts.ts::publicPostInclude``):

    GET /api/public/posts?page=<n>&perPage=<n>   (perPage tope 50, ver lib/http.ts)

    {
      "ok": true,
      "data": {
        "items": [
          {
            "id": 123, "slug": "...", "title": "...", "excerpt": "...",
            "publishedAt": "...", "updatedAt": "...", "storyKey": null,
            "category": {"id": 1, "name": "...", "slug": "interior", ...},
            "author": {"id": 1, "name": "...", "slug": "...", ...},
            "tags": [{"postId": 1, "tagId": 2, "tag": {"id": 2, "name": "...", "slug": "..."}}],
            "sources": [{"id": 1, "postId": 123, "name": "...", "url": "...", "type": "OFICIAL"}]
          }
        ],
        "pagination": {"page": 1, "perPage": 50, "total": 137}
      }
    }

El modelo ``Post`` público **no** tiene un campo ``url``/``canonicalUrl``
propio (ver ``prisma/schema.prisma``): la URL de la nota se reconstruye a
partir de ``slug`` + ``WEBAPP_BASE_URL``. Nunca se inventa una URL sin slug.
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
# lib/http.ts::getPagination clampea perPage a este máximo; lo replicamos acá
# para no confundir el conteo de "página corta = última página" con un
# recorte silencioso del servidor.
MAX_PER_PAGE = 50
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


def _tag_names(post: dict) -> list[str]:
    """``post.tags[]`` real es ``PostTag`` con ``include: {tag: true}``:
    ``{postId, tagId, tag: {id, name, slug, ...}}`` (Parte confirmada contra
    ``lib/posts.ts::publicPostInclude``). Se tolera además una forma plana
    ``{"name": ...}`` o un string suelto como fallback legacy, por si algún
    consumidor futuro simplifica la forma — nunca se asume que el nombre
    está en el nivel superior del ``PostTag`` real."""
    names: list[str] = []
    for item in post.get("tags") or []:
        if isinstance(item, dict):
            nested = item.get("tag")
            if isinstance(nested, dict) and nested.get("name"):
                names.append(str(nested["name"]))
                continue
            if item.get("name"):
                names.append(str(item["name"]))
                continue
        elif isinstance(item, str) and item:
            names.append(item)
    return names


def _article_url(post: dict, *, base_url: str) -> str:
    """El ``Post`` público no tiene ``url``/``canonicalUrl`` propios; se
    reconstruye desde ``slug``. Se toleran ``url``/``canonicalUrl``
    explícitos por si una versión futura del endpoint los agrega, pero
    nunca se inventa una URL cuando no hay ``slug``."""
    explicit = _first(post, "url", "canonicalUrl")
    if explicit:
        return explicit
    slug = _first(post, "slug")
    if not slug or not base_url:
        return ""
    return f"{base_url}/noticias/{slug}"


def _post_to_article(post: dict, *, base_url: str) -> ai.ArchiveArticle:
    category = post.get("category")
    category_slug = (category.get("slug") if isinstance(category, dict) else "") or _first(post, "categorySlug")
    author = post.get("author")
    author_name = (author.get("name") if isinstance(author, dict) else "") or _first(post, "authorName")
    excerpt = _first(post, "excerpt")
    return ai.ArchiveArticle(
        article_id=_first(post, "id", "slug"),
        post_id=_first(post, "id"),
        slug=_first(post, "slug"),
        canonical_url=_article_url(post, base_url=base_url),
        title=_first(post, "title"),
        excerpt=excerpt,
        category=str(category_slug or ""),
        published_at=_first(post, "publishedAt"),
        updated_at=_first(post, "updatedAt"),
        author=str(author_name or ""),
        tags=_tag_names(post),
        story_key=_first(post, "storyKey"),
        content_summary=excerpt,
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

    Exige el contrato real (``{"ok": true, "data": {"items": [...],
    "pagination": {...}}}``) de forma estricta: una respuesta con otra forma
    se registra como error explícito y detiene el backfill, en vez de
    intentar adivinar una forma alternativa (Parte 60: "si no se pudo
    recuperar evidencia, no se escribe"). Se detiene en la primera página
    vacía, cuando ``pagination.total`` indica que no queda nada más, o al
    llegar a ``max_pages`` — no hace requests repetidos inútiles (Parte 23).
    """
    base_url = _webapp_base_url()
    report = BackfillReport()
    if not base_url or base_url == "PENDIENTE":
        report.errors.append("WEBAPP_BASE_URL no configurada")
        return report

    per_page = max(1, min(int(page_size), MAX_PER_PAGE))

    for page in range(1, max_pages + 1):
        endpoint = f"{base_url}/api/public/posts?page={page}&perPage={per_page}"
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

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            report.errors.append(f"page={page}: respuesta sin ok=true (contrato inesperado)")
            break

        data = payload.get("data")
        if not isinstance(data, dict):
            report.errors.append(f"page={page}: data no es un objeto (contrato inesperado)")
            break

        posts = data.get("items")
        if not isinstance(posts, list):
            report.errors.append(f"page={page}: data.items no es una lista (contrato inesperado)")
            break

        if not posts:
            break
        report.pages_fetched += 1

        for post in posts:
            report.articles_seen += 1
            if not isinstance(post, dict) or not (post.get("id") or post.get("slug")):
                report.errors.append("post sin id ni slug: se descarta")
                continue
            try:
                ai.upsert_article(_post_to_article(post, base_url=base_url), path=path)
                report.articles_upserted += 1
            except Exception as exc:
                report.errors.append(f"post={post.get('slug') or post.get('id')}: {exc}")

        pagination = data.get("pagination")
        total = pagination.get("total") if isinstance(pagination, dict) else None
        if isinstance(total, int) and page * per_page >= total:
            break
        if len(posts) < per_page:
            break

    logger.info(
        "Backfill CMS: %s páginas, %s posts vistos, %s indexados, %s errores",
        report.pages_fetched,
        report.articles_seen,
        report.articles_upserted,
        len(report.errors),
    )
    return report
