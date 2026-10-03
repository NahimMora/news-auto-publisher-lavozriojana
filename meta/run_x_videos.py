"""Etapa estructurada: videos de X (backend HolaSalta) publicados como Reel."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from meta.ig_client import post_reel_video_to_instagram, rate_limit_until
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.paparazzi_reels import delete_reel_upload, publish_facebook_reel, render_reel_item
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts
from utils import x_video_reels as xv

logger = setup_logger("run_x_videos", "run_x_videos.log")

MAX_ATTEMPTS = 3


def _enabled() -> bool:
    return str(os.getenv("X_VIDEO_REELS_ENABLED", "false")).strip().lower() in {
        "1", "true", "yes", "on", "si", "sí",
    }


def _retry_or_dead(job_id: str, job: dict, reason: str) -> None:
    attempts = int(job.get("attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        xv._transition(job_id, status="dead_letter", reason=reason, attempts=attempts)
    else:
        xv._transition(job_id, status="pending", reason=reason, attempts=attempts)


def _process(job_id: str, job: dict, *, instagram: bool, facebook: bool) -> str:
    """Devuelve ``completed``, ``failed`` o ``deferred`` (rate limit)."""
    xv._transition(job_id, status="processing", attempts=int(job.get("attempts") or 0))

    noticia = xv.build_news_item(job, xv.fetch_x_metadata(job["url"]))
    if noticia is None:
        _retry_or_dead(job_id, job, "x_metadata_unavailable")
        return "failed"
    rendered = render_reel_item(noticia)
    if rendered is None:
        _retry_or_dead(job_id, job, "reel_render_unavailable")
        return "failed"
    reel_item, r2_key = rendered

    ig_id = fb_id = ""
    ig_result = None
    if instagram:
        ig_result = post_reel_video_to_instagram(reel_item)
        ig_id = ig_result.external_id if ig_result.ok else ""
    if facebook and (ig_result is None or ig_result.ok):
        _fb_ok, fb_id = publish_facebook_reel(reel_item)

    if ig_id or fb_id:
        xv._transition(
            job_id,
            status="completed",
            reason="",
            instagram_id=ig_id,
            facebook_id=fb_id,
            titulo=str(noticia.get("titulo_instagram") or "")[:120],
            completed_at=int(time.time()),
        )
        logger.info("Reel de X publicado (%s): ig=%s fb=%s", job["url"], bool(ig_id), bool(fb_id))
        return "completed"

    delete_reel_upload(r2_key)
    if ig_result is not None:
        outcome = ig_result.details.get("publication_outcome")
        if ig_result.error_type == "rate_limit":
            xv._transition(job_id, status="pending", reason="rate_limit")
            return "deferred"
        if outcome == "unknown":
            xv._transition(job_id, status="dead_letter", reason="ambiguous_publication_outcome")
            return "failed"
        if ig_result.retryable:
            _retry_or_dead(job_id, job, ig_result.error_type or "retryable")
            return "failed"
        xv._transition(job_id, status="dead_letter", reason=ig_result.error_type or "external_failure")
        return "failed"
    _retry_or_dead(job_id, job, "facebook_reel_failed")
    return "failed"


def main() -> StageResult:
    started = time.monotonic()
    if not _enabled():
        return StageResult("x_videos", StageStatus.NO_WORK, details={"disabled": True})
    plan = deployment_plan()
    instagram = plan.channel_enabled("instagram")
    facebook = plan.channel_enabled("facebook")
    if not instagram and not facebook:
        return StageResult("x_videos", StageStatus.NO_WORK, details={"channels_disabled": True})

    try:
        ambiguous = xv.recover_interrupted()
        feed, feed_issue = xv.read_feed()
        ingested = xv.ingest(feed) if feed else {"new": 0, "skipped_old": 0, "skipped_duplicate_url": 0}
        selected = xv.pending_jobs(int(os.getenv("X_VIDEO_MAX_PER_CYCLE", "2")))
    except JsonStateError as exc:
        logger.error("Estado de videos de X ilegible: %s", exc)
        return StageResult(
            "x_videos",
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            duration_seconds=time.monotonic() - started,
        )

    details = {"feed_issue": feed_issue, **ingested, "ambiguous_to_dead_letter": ambiguous}
    if not selected:
        return StageResult(
            "x_videos",
            StageStatus.NO_WORK,
            received=len(feed),
            details=details,
            duration_seconds=time.monotonic() - started,
        )

    succeeded = failed = deferred = processed = 0
    next_retry_at = None
    for index, (job_id, job) in enumerate(selected):
        until = rate_limit_until() if instagram else 0
        if time.time() < until:
            deferred += len(selected) - index
            next_retry_at = until
            break
        outcome = _process(job_id, job, instagram=instagram, facebook=facebook)
        processed += 1
        if outcome == "completed":
            succeeded += 1
        elif outcome == "deferred":
            deferred += len(selected) - index
            break
        else:
            failed += 1

    result = result_from_counts(
        "x_videos",
        received=len(feed),
        selected=len(selected),
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred,
        next_retry_at=next_retry_at,
        duration_seconds=time.monotonic() - started,
        details=details,
    )
    if deferred and result.status == StageStatus.SUCCESS:
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
