"""Observabilidad editorial y por fuente (Partes 54/55).

Cada bundle construido registra un evento liviano (sin texto completo, sólo
conteos) para poder reportar tasas de match/uso de contexto a lo largo del
tiempo sin recorrer las colas JSON.
"""
from __future__ import annotations

import time
from pathlib import Path

from editorial_context import db as ec_db
from utils.logging_setup import setup_logger

logger = setup_logger("editorial_context.metrics", "editorial_context.log")


def record_bundle_event(
    *,
    article_id: str = "",
    category: str = "",
    context_depth: str,
    archive_lookup_count: int = 0,
    archive_match_count: int = 0,
    story_assigned: bool = False,
    timeline_shown: bool = False,
    official_source_lookup_count: int = 0,
    official_source_hit_count: int = 0,
    context_store_hit_count: int = 0,
    context_store_miss_count: int = 0,
    context_chars: int = 0,
    related_articles_count: int = 0,
    path: Path | str | None = None,
) -> None:
    try:
        with ec_db.connection(path) as conn:
            conn.execute(
                """
                INSERT INTO bundle_events (
                    article_id, category, context_depth, archive_lookup_count, archive_match_count,
                    story_assigned, timeline_shown, official_source_lookup_count, official_source_hit_count,
                    context_store_hit_count, context_store_miss_count, context_chars, related_articles_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    category,
                    context_depth,
                    archive_lookup_count,
                    archive_match_count,
                    int(story_assigned),
                    int(timeline_shown),
                    official_source_lookup_count,
                    official_source_hit_count,
                    context_store_hit_count,
                    context_store_miss_count,
                    context_chars,
                    related_articles_count,
                    ec_db.now_iso(),
                ),
            )
    except Exception:
        logger.exception("No se pudo registrar bundle_event (article_id=%s)", article_id)


def editorial_metrics_summary(*, since_hours: int = 24, path: Path | str | None = None) -> dict:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - since_hours * 3600))
    with ec_db.connection(path) as conn:
        rows = conn.execute("SELECT * FROM bundle_events WHERE created_at >= ?", (cutoff,)).fetchall()

    total = len(rows)
    depth_counts = {"NONE": 0, "LIGHT": 0, "STANDARD": 0, "STORY": 0}
    archive_lookup = archive_match = story_assigned = story_timeline = 0
    official_lookup = official_hit = store_hit = store_miss = 0
    context_chars_sum = related_sum = 0

    for row in rows:
        depth_counts[row["context_depth"]] = depth_counts.get(row["context_depth"], 0) + 1
        archive_lookup += row["archive_lookup_count"]
        archive_match += row["archive_match_count"]
        story_assigned += row["story_assigned"]
        story_timeline += row["timeline_shown"]
        official_lookup += row["official_source_lookup_count"]
        official_hit += row["official_source_hit_count"]
        store_hit += row["context_store_hit_count"]
        store_miss += row["context_store_miss_count"]
        context_chars_sum += row["context_chars"]
        related_sum += row["related_articles_count"]

    return {
        "since_hours": since_hours,
        "articles_evaluated": total,
        "archive_lookup_count": archive_lookup,
        "archive_match_count": archive_match,
        "archive_match_rate": round(archive_match / archive_lookup, 3) if archive_lookup else 0.0,
        "story_assigned_count": story_assigned,
        "story_timeline_count": story_timeline,
        "context_depth_none": depth_counts.get("NONE", 0),
        "context_depth_light": depth_counts.get("LIGHT", 0),
        "context_depth_standard": depth_counts.get("STANDARD", 0),
        "context_depth_story": depth_counts.get("STORY", 0),
        "official_source_lookup_count": official_lookup,
        "official_source_hit_count": official_hit,
        "context_store_hit_count": store_hit,
        "context_store_miss_count": store_miss,
        "average_context_chars": round(context_chars_sum / total, 1) if total else 0.0,
        "average_related_articles": round(related_sum / total, 2) if total else 0.0,
    }


def source_metrics_summary(*, since_days: int = 7, path: Path | str | None = None) -> list[dict]:
    """Métricas por fuente (Parte 55): requests, 304, items, fallas, latencia."""
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - since_days * 86400))
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM source_metrics WHERE date >= ? ORDER BY source_id, date", (cutoff,)
        ).fetchall()

    per_source: dict[str, dict] = {}
    for row in rows:
        entry = per_source.setdefault(
            row["source_id"],
            {
                "source_id": row["source_id"],
                "requests": 0,
                "not_modified_304": 0,
                "items_discovered": 0,
                "items_new": 0,
                "parse_failures": 0,
                "timeouts": 0,
                "latency_ms_sum": 0.0,
                "latency_ms_count": 0,
                "last_success": None,
                "last_item_date": None,
            },
        )
        entry["requests"] += row["requests"]
        entry["not_modified_304"] += row["not_modified_304"]
        entry["items_discovered"] += row["items_discovered"]
        entry["items_new"] += row["items_new"]
        entry["parse_failures"] += row["parse_failures"]
        entry["timeouts"] += row["timeouts"]
        entry["latency_ms_sum"] += row["latency_ms_sum"]
        entry["latency_ms_count"] += row["latency_ms_count"]
        if row["last_success"] and (not entry["last_success"] or row["last_success"] > entry["last_success"]):
            entry["last_success"] = row["last_success"]
        if row["last_item_date"] and (not entry["last_item_date"] or row["last_item_date"] > entry["last_item_date"]):
            entry["last_item_date"] = row["last_item_date"]

    summaries = []
    for entry in per_source.values():
        avg_latency = (
            entry["latency_ms_sum"] / entry["latency_ms_count"] if entry["latency_ms_count"] else 0.0
        )
        summaries.append(
            {
                "source_id": entry["source_id"],
                "requests": entry["requests"],
                "not_modified_304": entry["not_modified_304"],
                "items_discovered": entry["items_discovered"],
                "items_new": entry["items_new"],
                "parse_failures": entry["parse_failures"],
                "timeouts": entry["timeouts"],
                "avg_latency_ms": round(avg_latency, 1),
                "last_success": entry["last_success"],
                "last_item_date": entry["last_item_date"],
            }
        )
    return sorted(summaries, key=lambda item: item["source_id"])
