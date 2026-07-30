"""Etapa estructurada de publicación en Instagram."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from meta.ig_client import (
    IG_ACCESS_TOKEN,
    IG_ACCOUNT_ID,
    post_to_instagram_detailed,
    rate_limit_until,
)
from utils.editorial_priority import item_category, item_is_breaking
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

logger = setup_logger("run_ig", "run_ig.log")

META_INPUT = str(data_dir() / "noticias_meta.json")
IG_STATE_PATH = str(data_dir() / "ig_posted.json")
IG_ALLOWED_CATEGORIES = {
    value.strip()
    for value in os.getenv("IG_ALLOWED_CATEGORIES", "interior,sociedad,politica").lower().split(",")
    if value.strip()
}


def _allowed_for_instagram(noticia: dict) -> bool:
    return item_category(noticia) in IG_ALLOWED_CATEGORIES or item_is_breaking(noticia)


def _bootstrap_queue() -> tuple[int, int, int]:
    noticias = load_json(META_INPUT, [], expected_type=list)
    included = 0
    omitted_by_policy = 0
    missing_web_url = 0
    for noticia in noticias:
        if not str(noticia.get("web_url") or noticia.get("noticia_url") or "").strip():
            missing_web_url += 1
            continue
        if _allowed_for_instagram(noticia):
            enqueue(noticia, platform="instagram")
            included += 1
        else:
            omitted_by_policy += 1
    return included, omitted_by_policy, missing_web_url


def _sync_posted_state() -> int:
    state = load_json(IG_STATE_PATH, {"posted": {}}, expected_type=dict)
    posted = state.get("posted")
    return sync_done_from_posted_state(
        "instagram",
        set(posted.keys()) if isinstance(posted, dict) else set(),
    )


def main() -> StageResult:
    started = time.monotonic()
    if str(os.getenv("IG_PUBLISH_ENABLED", "false")).strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
        "si",
        "sí",
    }:
        return StageResult("instagram", StageStatus.NO_WORK, details={"disabled": True})
    if (
        not IG_ACCOUNT_ID
        or IG_ACCOUNT_ID == "PENDIENTE"
        or not IG_ACCESS_TOKEN
        or IG_ACCESS_TOKEN == "PENDIENTE"
    ):
        return StageResult(
            "instagram",
            StageStatus.FAILED,
            failed=1,
            error_type="missing_configuration",
            duration_seconds=time.monotonic() - started,
        )
    try:
        until = rate_limit_until()
        if time.time() < until:
            return StageResult(
                "instagram",
                StageStatus.DEGRADED,
                deferred=1,
                error_type="rate_limit",
                next_retry_at=until,
                duration_seconds=time.monotonic() - started,
            )
        ambiguous = recover_ambiguous_processing("instagram")
        included, omitted, missing_web_url = _bootstrap_queue()
        synced = _sync_posted_state()
        all_pending = get_pending("instagram")
        limit = int(os.getenv("IG_MAX_PER_RUN", "1"))
        selected = get_pending("instagram", max_items=limit)
    except JsonStateError as exc:
        logger.error("Estado social de Instagram ilegible: %s", exc)
        return StageResult(
            "instagram",
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            duration_seconds=time.monotonic() - started,
        )

    if not selected:
        return StageResult(
            "instagram",
            StageStatus.NO_WORK,
            received=len(all_pending),
            duration_seconds=time.monotonic() - started,
            details={
                "included": included,
                "omitted_by_policy": omitted,
                "blocked_missing_web_url": missing_web_url,
                "synced": synced,
                "ambiguous_to_dead_letter": ambiguous,
            },
        )

    succeeded = failed = deferred = processed = 0
    error_type = None
    next_retry_at = None
    for index, noticia in enumerate(selected):
        if not claim(noticia, "instagram"):
            deferred += 1
            continue
        operation = post_to_instagram_detailed(noticia)
        processed += 1
        if operation.ok:
            mark_done(
                noticia,
                "instagram",
                evidence={
                    "external_id": operation.external_id,
                    "deduplicated": operation.deduplicated,
                    "fallback_used": operation.details.get("fallback_used", False),
                },
            )
            succeeded += 1
            continue

        error_type = operation.error_type
        next_retry_at = operation.next_retry_at
        outcome = operation.details.get("publication_outcome")
        failure_metadata = operation.failure_metadata()
        logger.error(
            "Fallo externo de Instagram para %s: %s",
            str(noticia.get("dedup_key") or noticia.get("titulo") or "")[:120],
            failure_metadata,
        )
        if operation.retryable and outcome != "unknown":
            mark_pending(noticia, "instagram", operation.error_type or "retryable")
        elif operation.error_type in {"invalid_credential", "missing_configuration"}:
            mark_pending(noticia, "instagram", operation.error_type)
        else:
            mark_dead_letter(
                noticia,
                "instagram",
                operation.error_type or "external_failure",
                metadata=failure_metadata,
            )
        failed += 1
        if operation.error_type in {"rate_limit", "invalid_credential"}:
            deferred += len(selected) - index - 1
            break

    compact_queue()
    result = result_from_counts(
        "instagram",
        received=len(all_pending),
        selected=len(selected),
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred + max(0, len(all_pending) - len(selected)) + missing_web_url,
        duration_seconds=time.monotonic() - started,
        error_type=error_type,
        next_retry_at=next_retry_at,
        details={
            "omitted_by_policy": omitted,
            "blocked_missing_web_url": missing_web_url,
            "ambiguous_to_dead_letter": ambiguous,
        },
    )
    if error_type == "invalid_credential":
        result.status = StageStatus.FAILED
    elif error_type == "rate_limit":
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
