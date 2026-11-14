"""Etapa estructurada: historias de Instagram y Facebook.

Primero las piezas de servicio que corresponden a esta hora (alertas, clima,
dólar, feriados, cortes), después una historia por cada publicación reciente
de Instagram (último momento y locales primero). La misma imagen va a las
dos redes. Cupo propio por ciclo y por día, fuera de los cupos del feed.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import story_publisher as sp
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.remotion_renderer import RemotionRenderError
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_stories", "stories.log")

STAGE = "stories"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> StageResult:
    started = time.monotonic()
    plan = deployment_plan()
    instagram = sp.instagram_enabled() and plan.channel_enabled("instagram")
    facebook = sp.facebook_enabled() and plan.channel_enabled("facebook")
    if not instagram and not facebook:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if sp.in_quiet_hours():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"quiet_hours": True})

    try:
        state = sp.load_state()
    except JsonStateError as exc:
        logger.error("Estado de historias ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    budget = min(_int("STORY_MAX_PER_CYCLE", 6), sp.max_per_day() - sp.stories_today(state))
    if budget <= 0:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"daily_cap_reached": True})

    jobs: list[tuple[str, dict, str | None, dict]] = []
    if os.getenv("SERVICE_STORIES_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on", "si", "sí"}:
        from utils.social_formats import due_service_stories

        try:
            for key, props, asset in due_service_stories(done=lambda k: sp.already_done(k, state)):
                jobs.append((key, props, asset, {"kind": props.get("kind"), "label": key}))
        except Exception:  # noqa: BLE001 — una fuente de servicio rota no frena las historias de posts
            logger.exception("No se pudieron preparar las historias de servicio")

    lookback = float(os.getenv("STORY_POST_LOOKBACK_HOURS", "6"))
    media = sp.recent_instagram_media()
    manual = sp.manual_post_stories()
    for candidate in sp.post_story_candidates(media, lookback_hours=lookback, state=state):
        meta = {"kind": "post", "label": candidate["title"][:80], "candidate": candidate}
        if manual and sp.is_manual_story(candidate):
            # En Instagram la sube el operador; sin Facebook no queda nada que hacer.
            if not facebook:
                continue
            meta["instagram"] = False
        jobs.append((candidate["key"], {}, None, meta))

    selected = jobs[:budget]
    succeeded = failed = 0
    outcomes: dict[str, dict] = {}
    for key, props, asset, meta in selected:
        temp_asset = None
        dollar_values = None
        try:
            if "candidate" in meta:
                props, temp_asset = sp.story_for_candidate(meta["candidate"])
                if not temp_asset:
                    failed += 1
                    outcomes[key] = {"error": "image_download_failed"}
                    continue
                asset = temp_asset
            dollar_values = props.pop("_dollar_values", None)
            jpeg = sp.render_story(props, asset)
        except (RemotionRenderError, OSError, ValueError) as exc:
            logger.warning("No se pudo renderizar la historia %s: %s", key, exc)
            failed += 1
            outcomes[key] = {"error": "render_failed"}
            continue
        finally:
            if temp_asset:
                try:
                    os.unlink(temp_asset)
                except OSError:
                    pass
        outcome = sp.publish_story(
            key,
            jpeg,
            instagram=instagram and meta.get("instagram", True),
            facebook=facebook,
            meta={"kind": meta["kind"], "label": meta["label"]},
        )
        outcomes[key] = outcome
        if "success" in outcome.values():
            succeeded += 1
            if dollar_values:
                from utils.social_formats import remember_dollar

                remember_dollar(dollar_values)
        else:
            failed += 1
        if "rate_limit" in outcome.values():
            break

    return result_from_counts(
        STAGE,
        received=len(jobs),
        selected=len(selected),
        processed=succeeded + failed,
        succeeded=succeeded,
        failed=failed,
        deferred=max(0, len(jobs) - len(selected)),
        duration_seconds=time.monotonic() - started,
        details={"outcomes": outcomes, "instagram": instagram, "facebook": facebook},
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
