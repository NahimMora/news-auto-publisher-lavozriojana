"""Conexión y esquema del índice derivado de contexto editorial (SQLite).

Reconstruible desde cero en cualquier momento (``rebuild_database``): nunca es
la fuente autoritativa de nada. Si SQLite no soporta FTS5 en el host (se
verifica en runtime, nunca se asume), se usa una tabla plana con búsqueda
``LIKE`` como fallback (ver ``fts5_supported``).
"""
from __future__ import annotations

import contextlib
import sqlite3
import time
from pathlib import Path

from utils.logging_setup import setup_logger
from utils.paths import derived_dir

logger = setup_logger("editorial_context.db", "editorial_context.log")

DB_FILENAME = "editorial_context.sqlite3"
SCHEMA_VERSION = 1

_fts5_supported_cache: bool | None = None

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id TEXT NOT NULL UNIQUE,
        post_id TEXT,
        slug TEXT,
        canonical_url TEXT,
        title TEXT NOT NULL,
        excerpt TEXT,
        category TEXT,
        published_at TEXT,
        updated_at TEXT,
        author TEXT,
        tags_json TEXT,
        entities_json TEXT,
        localities_json TEXT,
        topic_key TEXT,
        story_key TEXT,
        content_summary TEXT,
        source_kind TEXT NOT NULL DEFAULT 'own_archive',
        created_at_ts REAL NOT NULL,
        updated_at_ts REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_archive_articles_published_at ON archive_articles(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_archive_articles_category ON archive_articles(category)",
    "CREATE INDEX IF NOT EXISTS idx_archive_articles_topic_key ON archive_articles(topic_key)",
    "CREATE INDEX IF NOT EXISTS idx_archive_articles_story_key ON archive_articles(story_key)",
    """
    CREATE TABLE IF NOT EXISTS stories (
        story_key TEXT PRIMARY KEY,
        category TEXT,
        title_hint TEXT,
        anchor_entities_json TEXT,
        anchor_terms_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS story_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id TEXT NOT NULL,
        story_key TEXT NOT NULL,
        relation_score REAL NOT NULL,
        relation_reason TEXT,
        matched_entities_json TEXT,
        matched_terms_json TEXT,
        time_distance_days REAL,
        confidence REAL,
        created_at TEXT NOT NULL,
        UNIQUE(article_id, story_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_story_relations_story_key ON story_relations(story_key)",
    """
    CREATE TABLE IF NOT EXISTS context_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_key TEXT NOT NULL,
        fact TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        fact_type TEXT NOT NULL DEFAULT 'default',
        source_url TEXT,
        source_article_id TEXT,
        observed_at TEXT NOT NULL,
        event_date TEXT,
        expires_at TEXT,
        confidence REAL NOT NULL DEFAULT 0.5,
        hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_context_facts_entity_key ON context_facts(entity_key)",
    "CREATE INDEX IF NOT EXISTS idx_context_facts_expires_at ON context_facts(expires_at)",
    """
    CREATE TABLE IF NOT EXISTS official_content_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        canonical_url TEXT,
        content_hash TEXT,
        etag TEXT,
        last_modified TEXT,
        fetched_at TEXT NOT NULL,
        title TEXT,
        published_at TEXT,
        excerpt TEXT,
        body_summary TEXT,
        category TEXT,
        entities_json TEXT,
        location TEXT,
        raw_metadata_json TEXT,
        duplicate_of_url TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_official_cache_source_id ON official_content_cache(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_official_cache_published_at ON official_content_cache(published_at)",
    """
    CREATE TABLE IF NOT EXISTS source_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        date TEXT NOT NULL,
        requests INTEGER NOT NULL DEFAULT 0,
        not_modified_304 INTEGER NOT NULL DEFAULT 0,
        items_discovered INTEGER NOT NULL DEFAULT 0,
        items_new INTEGER NOT NULL DEFAULT 0,
        parse_failures INTEGER NOT NULL DEFAULT 0,
        timeouts INTEGER NOT NULL DEFAULT 0,
        latency_ms_sum REAL NOT NULL DEFAULT 0,
        latency_ms_count INTEGER NOT NULL DEFAULT 0,
        last_success TEXT,
        last_item_date TEXT,
        UNIQUE(source_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_call_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT NOT NULL,
        model TEXT,
        attempt INTEGER NOT NULL DEFAULT 1,
        latency_ms REAL,
        input_chars INTEGER,
        output_chars INTEGER,
        tokens_in INTEGER,
        tokens_out INTEGER,
        tokens_estimated INTEGER NOT NULL DEFAULT 0,
        success INTEGER NOT NULL,
        article_id TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_call_metrics_stage ON ai_call_metrics(stage)",
    "CREATE INDEX IF NOT EXISTS idx_ai_call_metrics_created_at ON ai_call_metrics(created_at)",
    """
    CREATE TABLE IF NOT EXISTS bundle_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id TEXT,
        category TEXT,
        context_depth TEXT NOT NULL,
        archive_lookup_count INTEGER NOT NULL DEFAULT 0,
        archive_match_count INTEGER NOT NULL DEFAULT 0,
        story_assigned INTEGER NOT NULL DEFAULT 0,
        timeline_shown INTEGER NOT NULL DEFAULT 0,
        official_source_lookup_count INTEGER NOT NULL DEFAULT 0,
        official_source_hit_count INTEGER NOT NULL DEFAULT 0,
        context_store_hit_count INTEGER NOT NULL DEFAULT 0,
        context_store_miss_count INTEGER NOT NULL DEFAULT 0,
        context_chars INTEGER NOT NULL DEFAULT 0,
        related_articles_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bundle_events_created_at ON bundle_events(created_at)",
]

_FALLBACK_FTS_TABLE = """
    CREATE TABLE IF NOT EXISTS archive_fts_fallback (
        article_pk INTEGER PRIMARY KEY,
        title TEXT,
        excerpt TEXT,
        entities_text TEXT,
        localities_text TEXT,
        tags_text TEXT,
        content_summary TEXT,
        search_blob TEXT
    )
"""

_REAL_FTS_TABLE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(
        title, excerpt, entities_text, localities_text, tags_text, content_summary,
        article_pk UNINDEXED,
        tokenize = 'unicode61 remove_diacritics 2'
    )
"""


def db_path() -> Path:
    return derived_dir() / DB_FILENAME


def fts5_supported(conn: sqlite3.Connection) -> bool:
    """Prueba en runtime si el sqlite3 del proceso soporta FTS5.

    Nunca se asume por versión de Python: se prueba directamente, una sola
    vez por proceso (memoizado).
    """
    global _fts5_supported_cache
    if _fts5_supported_cache is not None:
        return _fts5_supported_cache
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        _fts5_supported_cache = True
    except sqlite3.OperationalError:
        logger.warning("FTS5 no soportado por este build de sqlite3; usando fallback LIKE")
        _fts5_supported_cache = False
    return _fts5_supported_cache


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    if fts5_supported(conn):
        conn.execute(_REAL_FTS_TABLE)
    else:
        conn.execute(_FALLBACK_FTS_TABLE)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


@contextlib.contextmanager
def connection(path: Path | str | None = None):
    """Context manager transaccional: commitea al salir, rollback si hay excepción."""
    resolved = Path(path) if path else db_path()
    conn = _connect(resolved)
    try:
        ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rebuild_database(path: Path | str | None = None) -> Path:
    """Borra el archivo derivado (si existe) y recrea el esquema vacío.

    Seguro por diseño: el índice es reconstruible; nunca toca colas JSON
    autoritativas. Usar seguido de un backfill (``editorial_context.archive_backfill``).
    """
    resolved = Path(path) if path else db_path()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(resolved) + suffix)
        if candidate.exists():
            candidate.unlink()
    with connection(resolved) as conn:
        ensure_schema(conn)
    logger.info("Índice de contexto editorial reconstruido en %s", resolved)
    return resolved


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
