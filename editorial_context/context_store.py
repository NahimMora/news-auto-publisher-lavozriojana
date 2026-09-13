"""Context Store: hechos con provenance y TTL por tipo (Partes 15/16).

Sólo guarda hechos con fuente real (archivo propio o fuente oficial), nunca
"conocimiento general del modelo". Ante duda sobre vigencia, se prefiere no
reutilizar un dato vencido (Parte 16).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from editorial_context import db as ec_db
from editorial_context import entities as ec_entities

SOURCE_KIND_OWN_ARCHIVE = "OWN_ARCHIVE"
SOURCE_KIND_OFFICIAL_SOURCE = "OFFICIAL_SOURCE"

FACT_TYPE_HECHO_HISTORICO = "hecho_historico"
FACT_TYPE_PRECIO_MONTO = "precio_monto"
FACT_TYPE_CRONOGRAMA = "cronograma"
FACT_TYPE_FUNCIONARIO_CARGO = "funcionario_cargo"
FACT_TYPE_ALERTA_METEOROLOGICA = "alerta_meteorologica"
FACT_TYPE_RESULTADO_DEPORTIVO = "resultado_deportivo"
FACT_TYPE_DEFAULT = "default"

# TTL por tipo de dato/fuente (Parte 16). ``None`` = sin vencimiento fijo por
# TTL (hecho histórico estable, o resultado ya finalizado).
_FACT_TYPE_TTL_SECONDS: dict[str, int | None] = {
    FACT_TYPE_HECHO_HISTORICO: None,
    FACT_TYPE_PRECIO_MONTO: 3 * 24 * 3600,
    FACT_TYPE_CRONOGRAMA: None,  # se vence en ``event_date``, no por TTL fijo
    FACT_TYPE_FUNCIONARIO_CARGO: 90 * 24 * 3600,
    FACT_TYPE_ALERTA_METEOROLOGICA: 6 * 3600,
    FACT_TYPE_RESULTADO_DEPORTIVO: None,
    FACT_TYPE_DEFAULT: 30 * 24 * 3600,
}


@dataclass
class ContextFact:
    entity_key: str
    fact: str
    source_kind: str
    fact_type: str = FACT_TYPE_DEFAULT
    source_url: str = ""
    source_article_id: str = ""
    observed_at: str = ""
    event_date: str = ""
    expires_at: str | None = None
    confidence: float = 0.5


def _fact_hash(entity_key: str, fact: str, source_url: str) -> str:
    basis = "|".join([entity_key, fact, source_url])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def compute_expires_at(fact_type: str, event_date: str, observed_ts: float) -> str | None:
    if fact_type == FACT_TYPE_CRONOGRAMA and event_date:
        return event_date
    ttl = _FACT_TYPE_TTL_SECONDS.get(fact_type, _FACT_TYPE_TTL_SECONDS[FACT_TYPE_DEFAULT])
    if ttl is None:
        return None
    expires_ts = observed_ts + ttl
    return datetime.fromtimestamp(expires_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_fact(fact: ContextFact, *, path: Path | str | None = None) -> None:
    now_iso = ec_db.now_iso()
    observed_ts = time.time()
    expires_at = fact.expires_at if fact.expires_at is not None else compute_expires_at(
        fact.fact_type, fact.event_date, observed_ts
    )
    entity_key_norm = ec_entities.normalize_entity(fact.entity_key)
    fact_hash = _fact_hash(entity_key_norm, fact.fact, fact.source_url)
    with ec_db.connection(path) as conn:
        conn.execute(
            """
            INSERT INTO context_facts (
                entity_key, fact, source_kind, fact_type, source_url, source_article_id,
                observed_at, event_date, expires_at, confidence, hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash) DO UPDATE SET
                observed_at=excluded.observed_at,
                expires_at=excluded.expires_at,
                confidence=excluded.confidence
            """,
            (
                entity_key_norm,
                fact.fact,
                fact.source_kind,
                fact.fact_type,
                fact.source_url,
                fact.source_article_id,
                fact.observed_at or now_iso,
                fact.event_date,
                expires_at,
                fact.confidence,
                fact_hash,
                now_iso,
            ),
        )


def _row_to_fact(row) -> ContextFact:
    return ContextFact(
        entity_key=row["entity_key"],
        fact=row["fact"],
        source_kind=row["source_kind"],
        fact_type=row["fact_type"],
        source_url=row["source_url"] or "",
        source_article_id=row["source_article_id"] or "",
        observed_at=row["observed_at"] or "",
        event_date=row["event_date"] or "",
        expires_at=row["expires_at"],
        confidence=row["confidence"],
    )


def get_facts(
    entity_key: str, *, include_expired: bool = False, path: Path | str | None = None
) -> list[ContextFact]:
    """Ante duda sobre vigencia se prefiere NO reutilizar un dato vencido:
    por defecto ``include_expired=False`` filtra cualquier hecho con
    ``expires_at`` en el pasado."""
    entity_key_norm = ec_entities.normalize_entity(entity_key)
    now_iso = ec_db.now_iso()
    with ec_db.connection(path) as conn:
        if include_expired:
            rows = conn.execute(
                "SELECT * FROM context_facts WHERE entity_key = ? ORDER BY observed_at DESC",
                (entity_key_norm,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM context_facts WHERE entity_key = ? AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY observed_at DESC",
                (entity_key_norm, now_iso),
            ).fetchall()
    return [_row_to_fact(row) for row in rows]


def get_facts_for_entities(
    entity_keys: list[str], *, include_expired: bool = False, path: Path | str | None = None
) -> list[ContextFact]:
    facts: list[ContextFact] = []
    for entity_key in entity_keys:
        facts.extend(get_facts(entity_key, include_expired=include_expired, path=path))
    return facts
