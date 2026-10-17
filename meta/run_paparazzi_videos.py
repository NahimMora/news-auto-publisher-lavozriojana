"""Etapa estructurada: notas con video (paparazzi, Infobae) publicadas como Reel.

Ver ``utils/paparazzi_video_jobs.py``. El Reel sale siempre con la plantilla
EditorialReel, sin puntaje editorial y fuera de los cupos del lote; si no se
puede renderizar se reintenta y nunca se publica en redes como imagen.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from meta import ig_client
from meta.ig_client import post_reel_video_to_instagram, rate_limit_until
from utils import paparazzi_reels
from utils import paparazzi_video_jobs as pv
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.paparazzi_reels import delete_reel_upload, publish_facebook_reel, render_reel_item
from utils.publish_selection import video_reels_enabled
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_paparazzi_videos", "run_paparazzi_videos.log")

STAGE = "paparazzi_videos"
MAX_ATTEMPTS = 3


def _time_budget_seconds() -> float:
    """Tiempo de la etapa para encadenar Reels; lo que no entra queda pendiente
    para el próximo ciclo (menor que el timeout del supervisor, 1200 s)."""
    try:
        return max(60.0, float(os.getenv("VIDEO_STAGE_TIME_BUDGET_SECONDS", "480")))
    except ValueError:
        return 480.0


def _retry_or_dead(job_id: str, job: dict, reason: str) -> None:
    attempts = int(job.get("attempts") or 0) + 1
    status = "dead_letter" if attempts >= MAX_ATTEMPTS else "pending"
    pv.transition(job_id, status=status, reason=reason, attempts=attempts)


def _record_evidence(job_id: str, noticia: dict, *, ig_id: str, fb_id: str) -> None:
    try:
        paparazzi_reels._mark_posted(job_id, noticia, ig_id=ig_id, fb_id=fb_id)
        if ig_id:
            ig_client._mark_posted(
                paparazzi_reels._instagram_dedup_key(noticia), {**noticia, "media_type": "reel"}, ig_id
            )
    except JsonStateError as exc:
        logger.error("Reel publicado pero no se persistió la evidencia de dedup: %s", exc)


def _process(job_id: str, job: dict, *, instagram: bool, facebook: bool) -> str:
    """Devuelve ``completed``, ``failed`` o ``deferred``."""
    pv.transition(job_id, status="processing", attempts=int(job.get("attempts") or 0))
    noticia = dict(job.get("noticia") or {})

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
        pv.transition(
            job_id,
            status="completed",
            reason="",
            instagram_id=ig_id,
            facebook_id=fb_id,
            completed_at=int(time.time()),
        )
        _record_evidence(job_id, noticia, ig_id=ig_id, fb_id=fb_id)
        logger.info(
            "Reel de nota con video publicado: %s | ig=%s fb=%s",
            str(noticia.get("titulo") or "")[:80],
            ig_id or "-",
            fb_id or "-",
        )
        return "completed"

    delete_reel_upload(r2_key)
    if ig_result is not None:
        outcome = ig_result.details.get("publication_outcome")
        if ig_result.error_type == "rate_limit":
            pv.transition(job_id, status="pending", reason="rate_limit")
            return "deferred"
        if outcome == "unknown":
            pv.transition(job_id, status="dead_letter", reason="ambiguous_publication_outcome")
            return "failed"
        if ig_result.retryable or ig_result.error_type == "invalid_credential":
            _retry_or_dead(job_id, job, ig_result.error_type or "retryable")
            return "failed"
        pv.transition(job_id, status="dead_letter", reason=ig_result.error_type or "external_failure")
        return "failed"
    _retry_or_dead(job_id, job, "facebook_reel_failed")
    return "failed"


def main() -> StageResult:
    started = time.monotonic()
    if not video_reels_enabled():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    plan = deployment_plan()
    instagram = plan.channel_enabled("instagram")
    facebook = plan.channel_enabled("facebook")
    if not instagram and not facebook:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"channels_disabled": True})

    try:
        ambiguous = pv.recover_interrupted()
        ingested = pv.ingest()
        expired = pv.expire_stale()
        # 0 = sin tope: se publican todos, cortando por tiempo (el resto, al próximo ciclo).
        selected = pv.pending_jobs(int(os.getenv("PAPARAZZI_VIDEO_MAX_PER_CYCLE", "2")))
    except JsonStateError as exc:
        logger.error("Estado de reels de paparazzi ilegible: %s", exc)
        return StageResult(
            STAGE,
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            duration_seconds=time.monotonic() - started,
        )

    details = {**ingested, "expired": expired, "ambiguous_to_dead_letter": ambiguous}
    if not selected:
        return StageResult(
            STAGE,
            StageStatus.NO_WORK,
            expired=expired,
            details=details,
            duration_seconds=time.monotonic() - started,
        )

    succeeded = failed = deferred = processed = left_for_next_cycle = 0
    next_retry_at = None
    budget = _time_budget_seconds()
    for index, (job_id, job) in enumerate(selected):
        if processed and time.monotonic() - started >= budget:
            left_for_next_cycle = len(selected) - index
            break
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

    details["left_for_next_cycle"] = left_for_next_cycle
    attempted = len(selected) - left_for_next_cycle
    result = result_from_counts(
        STAGE,
        received=len(selected),
        selected=attempted,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred,
        expired=expired,
        next_retry_at=next_retry_at,
        duration_seconds=time.monotonic() - started,
        details=details,
    )
    if deferred and result.status == StageStatus.SUCCESS:
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
