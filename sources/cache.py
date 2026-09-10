"""Caché local de artículos oficiales (Parte 57) + dedup entre fuentes (Parte 51).

Una misma comunicación puede aparecer en el organismo y en su superior
(ej. Gobierno + Ministerio subordinado): se marca ``duplicate_of_url``, no se
cuenta como una segunda confirmación independiente.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from editorial_context import db as ec_db
from sources.contract import OfficialSourceItem
from utils.news_dedup import duplicate_reason

RECENT_WINDOW_ROWS = 300


def content_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def get_cache_entry(url: str, *, path: Path | str | None = None) -> dict | None:
    with ec_db.connection(path) as conn:
        row = conn.execute("SELECT * FROM official_content_cache WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def _recent_entries(*, exclude_url: str = "", path: Path | str | None = None) -> list[dict]:
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM official_content_cache ORDER BY id DESC LIMIT ?", (RECENT_WINDOW_ROWS,)
        ).fetchall()
    return [dict(row) for row in rows if row["url"] != exclude_url]


def find_duplicate_url(item: OfficialSourceItem, *, path: Path | str | None = None) -> str | None:
    """Nunca compara sólo dentro de la misma fuente: una comunicación puede
    republicarse en un organismo distinto (Parte 51). Devuelve la URL del
    duplicado más reciente encontrado, o ``None``."""
    probe = {"title": item.title, "url": item.url}
    for entry in _recent_entries(exclude_url=item.url, path=path):
        candidate = {"title": entry["title"] or "", "url": entry["url"]}
        if duplicate_reason(probe, [candidate], key_fields=("url",), threshold=0.75):
            return candidate["url"]
    return None


def upsert_cache_item(
    item: OfficialSourceItem,
    *,
    etag: str = "",
    last_modified: str = "",
    mark_duplicates: bool = True,
    path: Path | str | None = None,
) -> dict:
    """Idempotente por URL. Devuelve ``{"is_new": bool, "duplicate_of_url": str|None}``."""
    existing = get_cache_entry(item.url, path=path)
    duplicate_of_url = find_duplicate_url(item, path=path) if mark_duplicates else None
    body_hash = content_hash(item.title + item.excerpt)

    with ec_db.connection(path) as conn:
        conn.execute(
            """
            INSERT INTO official_content_cache (
                source_id, url, canonical_url, content_hash, etag, last_modified, fetched_at,
                title, published_at, excerpt, body_summary, category, entities_json, location,
                raw_metadata_json, duplicate_of_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                content_hash=excluded.content_hash, etag=excluded.etag,
                last_modified=excluded.last_modified, fetched_at=excluded.fetched_at,
                title=excluded.title, published_at=excluded.published_at,
                excerpt=excluded.excerpt, body_summary=excluded.body_summary,
                category=excluded.category, entities_json=excluded.entities_json,
                location=excluded.location, raw_metadata_json=excluded.raw_metadata_json,
                duplicate_of_url=excluded.duplicate_of_url
            """,
            (
                item.source_id,
                item.url,
                item.url,
                body_hash,
                etag,
                last_modified,
                ec_db.now_iso(),
                item.title,
                item.published_at,
                item.excerpt,
                item.body[:1000] if item.body else "",
                item.category,
                json.dumps(item.entities, ensure_ascii=False),
                item.location,
                json.dumps(item.raw_metadata, ensure_ascii=False),
                duplicate_of_url,
            ),
        )
    return {"is_new": existing is None, "duplicate_of_url": duplicate_of_url}


def recent_items_for_source(
    source_id: str, *, limit: int = 20, path: Path | str | None = None
) -> list[dict]:
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM official_content_cache WHERE source_id = ? ORDER BY id DESC LIMIT ?",
            (source_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
