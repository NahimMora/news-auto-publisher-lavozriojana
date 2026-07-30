"""Runner compartido para secciones con persistencia segura y resultado estructurado."""
from __future__ import annotations

import os
import time
from typing import Callable

from utils.file_manager import JsonStateError, append_json_items, load_json
from utils.logging_setup import setup_logger
from utils.news_filters import is_blocked
from utils.queue_events import record_queue_event
from utils.scraper_contract import ArticleScrapeResult, LinkScrapeResult
from utils.stage_result import StageResult, StageStatus, result_from_counts
from utils.url_normalization import canonical_url

logger = setup_logger("scraping.runner", "scrapers.log")


def _url_key(item: dict) -> str:
    return canonical_url(str(item.get("canonical_url") or item.get("url") or ""))


def run_section(
    *,
    stage: str,
    enabled: bool,
    history_path: str,
    output_path: str,
    fetch_links: Callable[[], LinkScrapeResult],
    fetch_article: Callable[[str], ArticleScrapeResult],
) -> StageResult:
    started = time.monotonic()
    if not enabled:
        return StageResult(stage, StageStatus.NO_WORK, details={"disabled": True})

    try:
        history = load_json(history_path, [], expected_type=list)
    except JsonStateError as exc:
        logger.error("%s no puede leer histórico: %s", stage, exc)
        return StageResult(
            stage,
            StageStatus.FAILED,
            failed=1,
            duration_seconds=time.monotonic() - started,
            error_type="state_read_error",
            details={"path": history_path, "message": str(exc)},
        )

    known_urls = {
        _url_key(item)
        for item in history
        if isinstance(item, dict) and (item.get("canonical_url") or item.get("url"))
    }
    links_result = fetch_links()
    if links_result.status == StageStatus.FAILED:
        return StageResult(
            stage,
            StageStatus.FAILED,
            failed=1,
            duration_seconds=time.monotonic() - started,
            error_type=links_result.error_type or "source_access_error",
            error_code=links_result.http_status,
            details={"message": links_result.message},
        )
    if not links_result.links:
        return StageResult(
            stage,
            StageStatus.NO_WORK,
            received=0,
            duration_seconds=time.monotonic() - started,
            details={"source_status": links_result.status.value},
        )

    candidates = [
        url for url in links_result.links
        if canonical_url(url) not in known_urls
    ]
    processed = 0
    succeeded = 0
    failed = 0
    discarded = 0
    warnings: list[str] = []

    for url in candidates:
        processed += 1
        article_result = fetch_article(url)
        if article_result.status == StageStatus.FAILED or not article_result.article:
            failed += 1
            record_queue_event(
                stage=stage,
                status="failed",
                reason=article_result.error_type or "article_scrape_failed",
                item={"url": url},
                metadata={
                    "http_status": article_result.http_status,
                    "message": article_result.message,
                },
            )
            continue

        article = article_result.article
        if article_result.status == StageStatus.DEGRADED:
            warnings.extend(article_result.warnings)

        if is_blocked(article, stage=stage):
            discarded += 1
            succeeded += 1
            terminal = {**article, "discarded_status": "filtered"}
            try:
                append_json_items(history_path, [terminal], key=_url_key)
                record_queue_event(
                    stage=stage,
                    status="completed",
                    reason="blocked_by_editorial_keyword",
                    item=terminal,
                )
            except JsonStateError as exc:
                failed += 1
                succeeded -= 1
                logger.error("%s no pudo registrar descarte: %s", stage, exc)
            continue

        try:
            # Orden deliberado: la cola durable/consumible se guarda antes del
            # histórico. Un corte puede causar re-fetch, nunca pérdida.
            append_json_items(output_path, [article], key=_url_key)
            append_json_items(history_path, [article], key=_url_key)
            succeeded += 1
            known_urls.add(_url_key(article))
        except JsonStateError as exc:
            failed += 1
            logger.error("%s no pudo persistir %s: %s", stage, url, exc)
            record_queue_event(
                stage=stage,
                status="failed",
                reason="state_write_error",
                item=article,
                metadata={"message": str(exc)},
            )

    result = result_from_counts(
        stage,
        received=len(links_result.links),
        selected=len(candidates),
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        duration_seconds=time.monotonic() - started,
        details={
            "known": len(links_result.links) - len(candidates),
            "discarded": discarded,
            "warnings": sorted(set(warnings)),
            "output": os.path.basename(output_path),
        },
    )
    if warnings and result.status == StageStatus.SUCCESS:
        result.status = StageStatus.DEGRADED
        result.error_type = "media_degraded"
    return result
