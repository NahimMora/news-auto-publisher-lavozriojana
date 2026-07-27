"""Etapa estructurada de publicación en Facebook."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from meta.fb_client import PAGE_ID, post_to_facebook_detailed
from utils.file_manager import JsonStateError, load_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_queue import (
    claim,
    compact_queue,
    enqueue,
    get_pending,
    mark_dead_letter,
    mark_done,
    mark_pending,
    recover_ambiguous_processing,
    sync_done_from_posted_state,
)
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_fb", "run_fb.log")

META_INPUT = str(data_dir() / "noticias_meta.json")
FB_STATE_PATH = str(data_dir() / "fb_posted.json")


def _bootstrap_queue() -> int:
    noticias = load_json(META_INPUT, [], expected_type=list)
    included = 0
    for noticia in noticias:
        if not str(noticia.get("web_url") or noticia.get("noticia_url") or "").strip():
            continue
        enqueue(noticia, platform="facebook")
        included += 1
    return included


def _sync_posted_state() -> int:
    state = load_json(FB_STATE_PATH, {"posted": {}}, expected_type=dict)
    posted = state.get("posted")
    return sync_done_from_posted_state(
        "facebook",
        set(posted.keys()) if isinstance(posted, dict) else set(),
    )


def main() -> StageResult:
    started = time.monotonic()
    if str(os.getenv("FB_PUBLISH_ENABLED", "false")).strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
        "si",
        "sí",
    }:
        return StageResult(
            "facebook",
            StageStatus.NO_WORK,
            details={"disabled": True},
        )
    if not PAGE_ID or PAGE_ID == "PENDIENTE" or not os.getenv("FB_PAGE_ACCESS_TOKEN"):
        return StageResult(
            "facebook",
            StageStatus.FAILED,
            failed=1,
            error_type="missing_configuration",
            duration_seconds=time.monotonic() - started,
        )
    try:
        ambiguous = recover_ambiguous_processing("facebook")
        bootstrapped = _bootstrap_queue()
        synced = _sync_posted_state()
        all_pending = get_pending("facebook")
        limit = int(os.getenv("PUBLISH_MAX_PER_RUN", "10"))
        selected = get_pending("facebook", max_items=limit)
    except JsonStateError as exc:
        logger.error("Estado social de Facebook ilegible: %s", exc)
        return StageResult(
            "facebook",
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            duration_seconds=time.monotonic() - started,
        )

    if not selected:
        return StageResult(
            "facebook",
            StageStatus.NO_WORK,
            received=len(all_pending),
            duration_seconds=time.monotonic() - started,
            details={
                "bootstrapped": bootstrapped,
                "synced": synced,
                "ambiguous_to_dead_letter": ambiguous,
            },
        )

    succeeded = failed = deferred = processed = 0
    error_type = None
    next_retry_at = None
    for index, noticia in enumerate(selected):
        if not claim(noticia, "facebook"):
            deferred += 1
            continue
        operation = post_to_facebook_detailed(noticia)
        processed += 1
        if operation.ok:
            mark_done(
                noticia,
                "facebook",
                evidence={
                    "external_id": operation.external_id,
                    "deduplicated": operation.deduplicated,
                },
            )
            succeeded += 1
            continue

        error_type = operation.error_type
        next_retry_at = operation.next_retry_at
        outcome = operation.details.get("publication_outcome")
        if operation.retryable and outcome != "unknown":
            mark_pending(noticia, "facebook", operation.error_type or "retryable")
        elif operation.error_type in {"invalid_credential", "missing_configuration"}:
            mark_pending(noticia, "facebook", operation.error_type)
        else:
            mark_dead_letter(
                noticia,
                "facebook",
                operation.error_type or "external_failure",
            )
        failed += 1
        if operation.error_type in {"rate_limit", "invalid_credential"}:
            deferred += len(selected) - index - 1
            break

    compact_queue()
    result = result_from_counts(
        "facebook",
        received=len(all_pending),
        selected=len(selected),
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred + max(0, len(all_pending) - len(selected)),
        duration_seconds=time.monotonic() - started,
        error_type=error_type,
        next_retry_at=next_retry_at,
        details={"ambiguous_to_dead_letter": ambiguous},
    )
    if error_type == "invalid_credential":
        result.status = StageStatus.FAILED
    elif error_type == "rate_limit":
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
