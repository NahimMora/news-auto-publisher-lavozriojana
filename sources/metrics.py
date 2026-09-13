"""Métricas por fuente (Parte 55): un registro acumulado por source_id/día.

Permite eliminar fuentes inútiles con evidencia (parse_failures altos,
items_new siempre en cero, timeouts frecuentes) en vez de intuición.
"""
from __future__ import annotations

import time
from pathlib import Path

from editorial_context import db as ec_db


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def record_fetch(
    source_id: str,
    *,
    requests: int = 1,
    not_modified: bool = False,
    items_discovered: int = 0,
    items_new: int = 0,
    parse_failure: bool = False,
    timeout: bool = False,
    latency_ms: float = 0.0,
    success: bool = True,
    last_item_date: str | None = None,
    path: Path | str | None = None,
) -> None:
    date = _today()
    now_iso = ec_db.now_iso()
    with ec_db.connection(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO source_metrics (source_id, date) VALUES (?, ?)",
            (source_id, date),
        )
        conn.execute(
            """
            UPDATE source_metrics SET
                requests = requests + ?,
                not_modified_304 = not_modified_304 + ?,
                items_discovered = items_discovered + ?,
                items_new = items_new + ?,
                parse_failures = parse_failures + ?,
                timeouts = timeouts + ?,
                latency_ms_sum = latency_ms_sum + ?,
                latency_ms_count = latency_ms_count + 1,
                last_success = CASE WHEN ? THEN ? ELSE last_success END,
                last_item_date = CASE WHEN ? IS NOT NULL THEN ? ELSE last_item_date END
            WHERE source_id = ? AND date = ?
            """,
            (
                requests,
                int(not_modified),
                items_discovered,
                items_new,
                int(parse_failure),
                int(timeout),
                latency_ms,
                int(success),
                now_iso,
                last_item_date,
                last_item_date,
                source_id,
                date,
            ),
        )
