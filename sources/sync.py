"""Orquestación por fuente: fetch → parse → caché → métricas (Partes 21-23, 56-57).

Un solo punto de entrada (``sync_source``) para el ciclo real
(``editorial_context/refresh_context.py``) y para el diagnóstico read-only
(``cli.py source-probe``, que llama esto con ``dry_run=True``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sources import cache as source_cache
from sources import fetch_state
from sources import http_client
from sources import metrics as source_metrics
from sources.contract import OfficialSourceItem
from sources.registry import SourceDefinition
from sources.strategies.html_index import parse_html_index
from sources.strategies.rss import parse_rss
from utils.logging_setup import setup_logger

logger = setup_logger("sources.sync", "official_sources.log")


@dataclass
class SyncReport:
    source_id: str
    reachable: bool
    strategy: str
    http_status: int | None = None
    items_found: int = 0
    items_new: int = 0
    newest_item_date: str = ""
    latency_ms: float = 0.0
    etag_available: bool = False
    last_modified_available: bool = False
    parse_status: str = "ok"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source_id,
            "reachable": self.reachable,
            "strategy": self.strategy,
            "http_status": self.http_status,
            "items_found": self.items_found,
            "items_new": self.items_new,
            "newest_item_date": self.newest_item_date,
            "latency_ms": round(self.latency_ms, 1),
            "etag_available": self.etag_available,
            "last_modified_available": self.last_modified_available,
            "parse_status": self.parse_status,
            "warnings": list(self.warnings),
        }


def _parse_items(source: SourceDefinition, text: str) -> list[OfficialSourceItem]:
    category = source.categories[0] if source.categories else ""
    if source.fetch_strategy == "rss":
        return parse_rss(text, source_id=source.source_id, category=category)
    if source.fetch_strategy == "html_index_generic":
        return parse_html_index(text, source_id=source.source_id, base_url=source.url, category=category)
    return []


def sync_source(
    source: SourceDefinition,
    *,
    dry_run: bool = False,
    force: bool = False,
    resolver=None,
    path: Path | str | None = None,
) -> SyncReport:
    """Descubre items nuevos de una fuente habilitada.

    ``dry_run=True`` no escribe caché/métricas/fetch-state (usado por el
    probe read-only, Parte 22): nunca publica nada, sólo diagnostica.
    ``force=True`` ignora ``source.enabled`` (el probe puede diagnosticar una
    fuente todavía deshabilitada antes de decidir activarla); el ciclo real
    (``refresh_context.py``) nunca debe pasar ``force=True``.
    """
    if source.fetch_strategy in {"none", ""} or (not source.enabled and not force):
        return SyncReport(
            source_id=source.source_id,
            reachable=False,
            strategy=source.discovery_strategy,
            parse_status="disabled",
            warnings=["source_disabled_or_no_strategy"],
        )

    state = fetch_state.get_fetch_state(source.source_id, path=path) if not dry_run else {"etag": "", "last_modified": ""}

    try:
        result = http_client.fetch(
            source, etag=state["etag"], last_modified=state["last_modified"], resolver=resolver
        )
    except http_client.SourceFetchError as exc:
        logger.warning("Fetch fallido para %s: %s", source.source_id, exc)
        if not dry_run:
            source_metrics.record_fetch(
                source.source_id, success=False, timeout="timeout" in str(exc).lower(), path=path
            )
        return SyncReport(
            source_id=source.source_id,
            reachable=False,
            strategy=source.discovery_strategy,
            parse_status="fetch_error",
            warnings=[str(exc)],
        )

    if result.not_modified:
        if not dry_run:
            source_metrics.record_fetch(source.source_id, not_modified=True, latency_ms=result.latency_ms, path=path)
        return SyncReport(
            source_id=source.source_id,
            reachable=True,
            strategy=source.discovery_strategy,
            http_status=304,
            latency_ms=result.latency_ms,
            parse_status="not_modified",
        )

    if not result.ok:
        if not dry_run:
            source_metrics.record_fetch(source.source_id, success=False, latency_ms=result.latency_ms, path=path)
        return SyncReport(
            source_id=source.source_id,
            reachable=True,
            strategy=source.discovery_strategy,
            http_status=result.status_code,
            latency_ms=result.latency_ms,
            parse_status="http_error",
            warnings=[f"http_status:{result.status_code}"],
        )

    items = _parse_items(source, result.text)[: source.max_items_per_cycle]
    warnings: list[str] = []
    parse_status = "ok" if items else "no_items_found"
    if not items:
        warnings.append("no_items_parsed")

    items_new = 0
    newest_date = ""
    for item in items:
        if item.published_at and item.published_at > newest_date:
            newest_date = item.published_at
        if dry_run:
            items_new += 1  # en dry-run no se escribe caché; se cuenta como candidato
            continue
        outcome = source_cache.upsert_cache_item(item, path=path)
        if outcome["is_new"]:
            items_new += 1
        if outcome["duplicate_of_url"]:
            warnings.append(f"republished_official_content:{item.url}->{outcome['duplicate_of_url']}")

    if not dry_run:
        fetch_state.set_fetch_state(
            source.source_id,
            etag=result.headers.get("ETag", ""),
            last_modified=result.headers.get("Last-Modified", ""),
            path=path,
        )
        source_metrics.record_fetch(
            source.source_id,
            items_discovered=len(items),
            items_new=items_new,
            latency_ms=result.latency_ms,
            last_item_date=newest_date or None,
            parse_failure=(parse_status == "no_items_found"),
            path=path,
        )

    return SyncReport(
        source_id=source.source_id,
        reachable=True,
        strategy=source.discovery_strategy,
        http_status=result.status_code,
        items_found=len(items),
        items_new=items_new,
        newest_item_date=newest_date,
        latency_ms=result.latency_ms,
        etag_available=bool(result.headers.get("ETag")),
        last_modified_available=bool(result.headers.get("Last-Modified")),
        parse_status=parse_status,
        warnings=warnings,
    )
