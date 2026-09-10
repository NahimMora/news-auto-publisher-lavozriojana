"""Índice del archivo propio de La Voz Riojana (ingesta + búsqueda determinística).

Implementa el contrato de dominio ``ArchiveSearchProvider`` (Parte 48 del
plan) pensado para poder soportar más adelante un buscador de noticias sin
reconstruir nada: ``search``, ``related``, ``story``.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from editorial_context import db as ec_db
from editorial_context import entities as ec_entities
from utils.logging_setup import setup_logger

logger = setup_logger("editorial_context.archive_index", "editorial_context.log")

MAX_CONTENT_SUMMARY_CHARS = 600


@dataclass
class ArchiveArticle:
    article_id: str
    title: str
    post_id: str = ""
    slug: str = ""
    canonical_url: str = ""
    excerpt: str = ""
    category: str = ""
    published_at: str = ""
    updated_at: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    localities: list[str] = field(default_factory=list)
    topic_key: str = ""
    story_key: str = ""
    content_summary: str = ""
    source_kind: str = "own_archive"

    def searchable_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.title,
                self.excerpt,
                " ".join(self.entities),
                " ".join(self.localities),
                " ".join(self.tags),
                self.content_summary,
            )
            if part
        )


def _row_to_article(row: sqlite3.Row) -> ArchiveArticle:
    return ArchiveArticle(
        article_id=row["article_id"],
        title=row["title"] or "",
        post_id=row["post_id"] or "",
        slug=row["slug"] or "",
        canonical_url=row["canonical_url"] or "",
        excerpt=row["excerpt"] or "",
        category=row["category"] or "",
        published_at=row["published_at"] or "",
        updated_at=row["updated_at"] or "",
        author=row["author"] or "",
        tags=json.loads(row["tags_json"] or "[]"),
        entities=json.loads(row["entities_json"] or "[]"),
        localities=json.loads(row["localities_json"] or "[]"),
        topic_key=row["topic_key"] or "",
        story_key=row["story_key"] or "",
        content_summary=row["content_summary"] or "",
        source_kind=row["source_kind"] or "own_archive",
    )


def _derive_entities_and_localities(article: ArchiveArticle) -> ArchiveArticle:
    if not article.entities:
        article.entities = ec_entities.extract_entities(article.title, article.excerpt)
    if not article.localities:
        article.localities = ec_entities.extract_localities(article.title, article.excerpt)
    return article


def _sync_fts_row(conn: sqlite3.Connection, article_pk: int, article: ArchiveArticle) -> None:
    entities_text = " ".join(article.entities)
    localities_text = " ".join(article.localities)
    tags_text = " ".join(article.tags)
    if ec_db.fts5_supported(conn):
        conn.execute("DELETE FROM archive_fts WHERE article_pk = ?", (article_pk,))
        conn.execute(
            "INSERT INTO archive_fts "
            "(title, excerpt, entities_text, localities_text, tags_text, content_summary, article_pk) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                article.title,
                article.excerpt,
                entities_text,
                localities_text,
                tags_text,
                article.content_summary,
                article_pk,
            ),
        )
    else:
        search_blob = ec_entities.ascii_lower(
            " ".join(
                [article.title, article.excerpt, entities_text, localities_text, tags_text, article.content_summary]
            )
        )
        conn.execute("DELETE FROM archive_fts_fallback WHERE article_pk = ?", (article_pk,))
        conn.execute(
            "INSERT INTO archive_fts_fallback "
            "(article_pk, title, excerpt, entities_text, localities_text, tags_text, content_summary, search_blob) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                article_pk,
                article.title,
                article.excerpt,
                entities_text,
                localities_text,
                tags_text,
                article.content_summary,
                search_blob,
            ),
        )


def upsert_article(article: ArchiveArticle, *, path: Path | str | None = None) -> None:
    """Inserta o actualiza un artículo del archivo propio (idempotente por ``article_id``)."""
    article = _derive_entities_and_localities(article)
    now = time.time()
    with ec_db.connection(path) as conn:
        existing = conn.execute(
            "SELECT id, created_at_ts, story_key FROM archive_articles WHERE article_id = ?",
            (article.article_id,),
        ).fetchone()
        # No pisar un story_key ya asignado por el Story Engine si el llamador
        # no manda uno explícito (evita que una re-ingesta rutinaria borre una
        # asignación de historia hecha después de la publicación original).
        story_key = article.story_key or (existing["story_key"] if existing else "")
        created_at_ts = existing["created_at_ts"] if existing else now
        conn.execute(
            """
            INSERT INTO archive_articles (
                article_id, post_id, slug, canonical_url, title, excerpt, category,
                published_at, updated_at, author, tags_json, entities_json,
                localities_json, topic_key, story_key, content_summary, source_kind,
                created_at_ts, updated_at_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                post_id=excluded.post_id, slug=excluded.slug, canonical_url=excluded.canonical_url,
                title=excluded.title, excerpt=excluded.excerpt, category=excluded.category,
                published_at=excluded.published_at, updated_at=excluded.updated_at,
                author=excluded.author, tags_json=excluded.tags_json,
                entities_json=excluded.entities_json, localities_json=excluded.localities_json,
                topic_key=excluded.topic_key, story_key=excluded.story_key,
                content_summary=excluded.content_summary, source_kind=excluded.source_kind,
                updated_at_ts=excluded.updated_at_ts
            """,
            (
                article.article_id,
                article.post_id,
                article.slug,
                article.canonical_url,
                article.title,
                article.excerpt,
                article.category,
                article.published_at,
                article.updated_at,
                article.author,
                json.dumps(article.tags, ensure_ascii=False),
                json.dumps(article.entities, ensure_ascii=False),
                json.dumps(article.localities, ensure_ascii=False),
                article.topic_key,
                story_key,
                article.content_summary[:MAX_CONTENT_SUMMARY_CHARS],
                article.source_kind,
                created_at_ts,
                now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM archive_articles WHERE article_id = ?", (article.article_id,)
        ).fetchone()
        _sync_fts_row(conn, row["id"], article)


def get_by_article_id(article_id: str, *, path: Path | str | None = None) -> ArchiveArticle | None:
    with ec_db.connection(path) as conn:
        row = conn.execute(
            "SELECT * FROM archive_articles WHERE article_id = ?", (article_id,)
        ).fetchone()
    return _row_to_article(row) if row else None


def set_story_key(article_id: str, story_key: str, *, path: Path | str | None = None) -> None:
    with ec_db.connection(path) as conn:
        conn.execute(
            "UPDATE archive_articles SET story_key = ?, updated_at_ts = ? WHERE article_id = ?",
            (story_key, time.time(), article_id),
        )


def upsert_story(
    story_key: str,
    *,
    category: str = "",
    title_hint: str = "",
    anchor_entities: list[str] | None = None,
    anchor_terms: list[str] | None = None,
    path: Path | str | None = None,
) -> None:
    now = ec_db.now_iso()
    with ec_db.connection(path) as conn:
        conn.execute(
            """
            INSERT INTO stories (story_key, category, title_hint, anchor_entities_json, anchor_terms_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_key) DO UPDATE SET
                category=excluded.category,
                title_hint=CASE WHEN stories.title_hint = '' THEN excluded.title_hint ELSE stories.title_hint END,
                anchor_entities_json=excluded.anchor_entities_json,
                anchor_terms_json=excluded.anchor_terms_json,
                updated_at=excluded.updated_at
            """,
            (
                story_key,
                category,
                title_hint,
                json.dumps(anchor_entities or [], ensure_ascii=False),
                json.dumps(anchor_terms or [], ensure_ascii=False),
                now,
                now,
            ),
        )


def add_story_relation(
    article_id: str,
    story_key: str,
    *,
    relation_score: float,
    relation_reason: str,
    matched_entities: list[str],
    matched_terms: list[str],
    time_distance_days: float | None,
    confidence: str,
    path: Path | str | None = None,
) -> None:
    with ec_db.connection(path) as conn:
        conn.execute(
            """
            INSERT INTO story_relations (
                article_id, story_key, relation_score, relation_reason,
                matched_entities_json, matched_terms_json, time_distance_days, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id, story_key) DO UPDATE SET
                relation_score=excluded.relation_score, relation_reason=excluded.relation_reason,
                matched_entities_json=excluded.matched_entities_json,
                matched_terms_json=excluded.matched_terms_json,
                time_distance_days=excluded.time_distance_days, confidence=excluded.confidence
            """,
            (
                article_id,
                story_key,
                relation_score,
                relation_reason,
                json.dumps(matched_entities, ensure_ascii=False),
                json.dumps(matched_terms, ensure_ascii=False),
                time_distance_days,
                confidence,
                ec_db.now_iso(),
            ),
        )


def get_story_relations(story_key: str, *, path: Path | str | None = None) -> list[dict]:
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM story_relations WHERE story_key = ? ORDER BY created_at ASC",
            (story_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_story_articles(
    story_key: str, *, exclude_article_id: str | None = None, limit: int = 5, path: Path | str | None = None
) -> list[ArchiveArticle]:
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM archive_articles WHERE story_key = ? ORDER BY published_at ASC",
            (story_key,),
        ).fetchall()
    articles = [_row_to_article(row) for row in rows]
    if exclude_article_id:
        articles = [item for item in articles if item.article_id != exclude_article_id]
    return articles[:limit]


def _fts_query_terms(*texts: str) -> str:
    tokens: list[str] = []
    for text in texts:
        for word in str(text or "").split():
            cleaned = "".join(ch for ch in word if ch.isalnum())
            if len(cleaned) >= 3:
                tokens.append(f'"{cleaned}"')
    return " OR ".join(tokens[:24])


def candidate_retrieval(
    *,
    title: str,
    excerpt: str = "",
    entities: list[str] | None = None,
    localities: list[str] | None = None,
    category: str = "",
    tags: list[str] | None = None,
    exclude_article_id: str | None = None,
    limit: int = 20,
    path: Path | str | None = None,
) -> list[ArchiveArticle]:
    """Paso A (barato): candidatos por título/entidades/localidad/categoría/tags.

    Nunca busca por palabra suelta genérica sola: usa entidades/localidades ya
    extraídas y el título completo como bolsa de términos para FTS/LIKE.
    """
    entities = entities or ec_entities.extract_entities(title, excerpt)
    localities = localities or ec_entities.extract_localities(title, excerpt)
    query_text = " ".join([title, excerpt, " ".join(entities), " ".join(localities), " ".join(tags or [])])

    with ec_db.connection(path) as conn:
        if ec_db.fts5_supported(conn):
            match_expr = _fts_query_terms(query_text)
            if not match_expr:
                rows = []
            else:
                try:
                    rows = conn.execute(
                        """
                        SELECT aa.* FROM archive_fts
                        JOIN archive_articles aa ON aa.id = archive_fts.article_pk
                        WHERE archive_fts MATCH ?
                        ORDER BY bm25(archive_fts)
                        LIMIT ?
                        """,
                        (match_expr, limit * 3),
                    ).fetchall()
                except sqlite3.OperationalError:
                    logger.warning("Consulta FTS inválida, se usa fallback vacío: %s", match_expr)
                    rows = []
        else:
            blob = ec_entities.ascii_lower(query_text)
            terms = [t for t in blob.split() if len(t) >= 4][:12]
            if not terms:
                rows = []
            else:
                clauses = " OR ".join("search_blob LIKE ?" for _ in terms)
                params = [f"%{term}%" for term in terms]
                rows = conn.execute(
                    f"""
                    SELECT aa.* FROM archive_fts_fallback aff
                    JOIN archive_articles aa ON aa.id = aff.article_pk
                    WHERE {clauses}
                    LIMIT ?
                    """,
                    (*params, limit * 3),
                ).fetchall()

    articles = [_row_to_article(row) for row in rows]
    if exclude_article_id:
        articles = [item for item in articles if item.article_id != exclude_article_id]
    return articles[:limit]


class ArchiveSearchProvider:
    """Interfaz de dominio estable (Parte 48): pensada para un futuro buscador
    de noticias sin reescribir la capa de almacenamiento."""

    def search(self, query: str, filters: dict | None = None, *, limit: int = 20) -> list[ArchiveArticle]:
        filters = filters or {}
        return candidate_retrieval(
            title=query,
            category=str(filters.get("category") or ""),
            tags=filters.get("tags") or [],
            limit=limit,
        )

    def related(self, article: dict, *, limit: int = 20) -> list[ArchiveArticle]:
        return candidate_retrieval(
            title=str(article.get("titulo") or article.get("title") or ""),
            excerpt=str(article.get("excerpt") or ""),
            entities=article.get("entities"),
            localities=article.get("localities"),
            category=str(article.get("category") or article.get("categoria") or ""),
            tags=article.get("tags"),
            exclude_article_id=article.get("article_id"),
            limit=limit,
        )

    def story(self, story_key: str, *, exclude_article_id: str | None = None, limit: int = 5) -> list[ArchiveArticle]:
        return get_story_articles(story_key, exclude_article_id=exclude_article_id, limit=limit)
