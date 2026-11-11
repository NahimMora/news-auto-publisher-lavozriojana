"""Etapa estructurada: historia "Sumate a nuestro WhatsApp" (ver
``utils/wa_join_story.py``). Usa la sesión de la app de las historias nativas;
no consume el tope de publicaciones de Graph."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import native_story as ns
from utils import wa_join_story as js
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.social_time import today_ar
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_wa_join_story", "native_stories.log")

STAGE = "wa_join_story"


def publish(image_path: str, url: str) -> dict:
    from instagrapi.types import StoryLink

    from meta import instagrapi_client as igc

    client = igc.NativeStoryClient()
    app = client.connect()
    box = js.LINK_BOX
    try:
        with igc._upload_as_is():
            story = app.photo_upload_to_story(
                Path(image_path),
                links=[StoryLink(webUri=url, x=box["x"], y=box["y"], width=box["width"], height=box["height"])],
                resize_mode="fit",
            )
    except Exception as exc:  # noqa: BLE001 — se clasifica sin propagar datos crudos
        raise igc._classify(exc, published_phase=True) from None
    pk = str(getattr(story, "pk", "") or "")
    if not pk:
        raise igc.NativeStoryError(igc.UNVERIFIED, "story_without_pk")
    return {"story_pk": pk, "story_url": f"https://www.instagram.com/stories/{app.username or client.username}/{pk}/"}


def main() -> StageResult:
    started = time.monotonic()
    if not js.enabled():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if not deployment_plan().channel_enabled("instagram"):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"instagram_disabled": True})
    try:
        if not js.due():
            return StageResult(STAGE, StageStatus.NO_WORK, details={"due": False})
        if float(ns.load_state().get("blocked_until") or 0) > time.time():
            return StageResult(STAGE, StageStatus.DEGRADED, error_type="instagram_blocked")
    except JsonStateError as exc:
        logger.error("Estado ilegible para la historia de WhatsApp: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    try:
        url = js.join_url()
    except ValueError as exc:
        logger.error("Historia de WhatsApp sin enlace válido: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="missing_configuration")

    day = today_ar().isoformat()
    image = js.write_image()
    from meta import instagrapi_client as igc

    try:
        result = publish(image, url)
    except igc.NativeStoryError as exc:
        # Después de enviarla puede haber salido: ese día no se reintenta.
        status = "unverified" if exc.kind == igc.UNVERIFIED else "failed"
        if status == "unverified":
            js.mark(day, status=status, error=exc.code, at=int(time.time()))
        if exc.kind == igc.BLOCKED:
            # Mismo freno que las historias nativas: la cuenta es la misma.
            ns.set_blocked(exc.code)
        logger.error("Historia de WhatsApp %s: %s/%s", status, exc.kind, exc.code)
        return StageResult(STAGE, StageStatus.FAILED if exc.kind == igc.CREDENTIAL else StageStatus.DEGRADED,
                           failed=1, error_type=exc.code, duration_seconds=time.monotonic() - started)
    finally:
        try:
            os.unlink(image)
        except OSError:
            pass
    js.mark(day, status="completed", at=int(time.time()), **result)
    logger.info("Historia de WhatsApp publicada → %s", result["story_url"])
    return StageResult(STAGE, StageStatus.SUCCESS, received=1, processed=1, succeeded=1,
                       details=result, duration_seconds=time.monotonic() - started)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
