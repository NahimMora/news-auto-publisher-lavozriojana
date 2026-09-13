"""ETag/Last-Modified por fuente (Parte 23): condicional a nivel de feed/índice.

Distinto de ``sources/cache.py`` (caché de artículos individuales): esto
guarda el estado condicional de la URL de descubrimiento de la fuente
(feed RSS o página de índice), una fila por ``source_id``.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from editorial_context import db as ec_db


def get_fetch_state(source_id: str, *, path: Path | str | None = None) -> dict:
    with ec_db.connection(path) as conn:
        row = conn.execute(
            "SELECT * FROM source_fetch_state WHERE source_id = ?", (source_id,)
        ).fetchone()
    if row is None:
        return {"etag": "", "last_modified": "", "last_fetched_at": ""}
    return {
        "etag": row["etag"] or "",
        "last_modified": row["last_modified"] or "",
        "last_fetched_at": row["last_fetched_at"] or "",
    }


def set_fetch_state(
    source_id: str, *, etag: str = "", last_modified: str = "", path: Path | str | None = None
) -> None:
    with ec_db.connection(path) as conn:
        conn.execute(
            """
            INSERT INTO source_fetch_state (source_id, etag, last_modified, last_fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                etag=excluded.etag, last_modified=excluded.last_modified, last_fetched_at=excluded.last_fetched_at
            """,
            (source_id, etag, last_modified, ec_db.now_iso()),
        )


def seconds_since_last_fetch(source_id: str, *, path: Path | str | None = None) -> float | None:
    """``None`` si nunca se sincronizó (siempre se considera "vencida" en ese caso)."""
    state = get_fetch_state(source_id, path=path)
    raw = state.get("last_fetched_at") or ""
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0.0, time.time() - parsed.timestamp())


def is_due(source_id: str, *, poll_ttl: int, path: Path | str | None = None) -> bool:
    elapsed = seconds_since_last_fetch(source_id, path=path)
    return elapsed is None or elapsed >= poll_ttl
