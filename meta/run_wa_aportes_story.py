"""Etapa estructurada: historia "Mandanos tu noticia" por WhatsApp (ver
``utils/wa_aportes_story.py``). Sale después de la historia "Sumate"; usa la
sesión de la app de las historias nativas y no consume el tope de Graph."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import native_story as ns
from utils import wa_aportes_story as wa
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.social_time import now_ar
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_wa_aportes_story", "native_stories.log")

STAGE = "wa_aportes_story"


def publish(video_path: str, thumb_path: str, url: str) -> dict:
    from instagrapi.types import StoryLink

    from meta import instagrapi_client as igc

    client = igc.NativeStoryClient()
    app = client.connect()
    box = wa.LINK_BOX
    try:
        story = app.video_upload_to_story(
            Path(video_path),
            thumbnail=Path(thumb_path),
            links=[StoryLink(webUri=url, x=box["x"], y=box["y"], width=box["width"], height=box["height"])],
            resize_mode="fill",
        )
    except Exception as exc:  # noqa: BLE001 — se clasifica sin propagar datos crudos
        raise igc._classify(exc, published_phase=True) from None
    pk = str(getattr(story, "pk", "") or "")
    if not pk:
        raise igc.NativeStoryError(igc.UNVERIFIED, "story_without_pk")
    return {"story_pk": pk, "story_url": f"https://www.instagram.com/stories/{app.username or client.username}/{pk}/"}


def main() -> StageResult:
    started = time.monotonic()
    if not wa.enabled():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if not deployment_plan().channel_enabled("instagram"):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"instagram_disabled": True})
    try:
        if not wa.due():
            return StageResult(STAGE, StageStatus.NO_WORK, details={"due": False})
        if float(ns.load_state().get("blocked_until") or 0) > time.time():
            return StageResult(STAGE, StageStatus.DEGRADED, error_type="instagram_blocked")
    except JsonStateError as exc:
        logger.error("Estado ilegible para la historia de aportes: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    try:
        digits = wa.number()
    except ValueError as exc:
        logger.error("Historia de aportes sin número válido: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="missing_configuration")

    moment = now_ar()
    day = moment.date().isoformat()
    try:
        video, thumb = wa.render(wa.props_for(moment, digits))
    except (RuntimeError, OSError, ValueError) as exc:
        logger.error("No se pudo renderizar la historia de aportes: %s", exc)
        return StageResult(STAGE, StageStatus.DEGRADED, failed=1, error_type="render_failed",
                           duration_seconds=time.monotonic() - started)

    from meta import instagrapi_client as igc

    try:
        result = publish(video, thumb, wa.link(digits))
    except igc.NativeStoryError as exc:
        status = "unverified" if exc.kind == igc.UNVERIFIED else "failed"
        if status == "unverified":
            wa.mark(day, status=status, error=exc.code, at=int(time.time()))
        if exc.kind == igc.BLOCKED:
            ns.set_blocked(exc.code)
        logger.error("Historia de aportes %s: %s/%s", status, exc.kind, exc.code)
        return StageResult(STAGE, StageStatus.FAILED if exc.kind == igc.CREDENTIAL else StageStatus.DEGRADED,
                           failed=1, error_type=exc.code, duration_seconds=time.monotonic() - started)
    finally:
        for path in (video, thumb):
            try:
                os.unlink(path)
            except OSError:
                pass
    wa.mark(day, status="completed", at=int(time.time()), **result)
    logger.info("Historia de aportes publicada → %s", result["story_url"])
    return StageResult(STAGE, StageStatus.SUCCESS, received=1, processed=1, succeeded=1,
                       details=result, duration_seconds=time.monotonic() - started)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
