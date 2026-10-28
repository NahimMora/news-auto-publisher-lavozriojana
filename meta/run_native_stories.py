"""Etapa estructurada: historias nativas de Instagram con stickers reales.

Por cada publicación reciente del feed (``ig_posted.json``) sin historia,
publica UNA historia sobre fondo #111318 con la publicación compartida, el
enlace a la nota y la ubicación (ver ``utils/native_story.py``). Secuencial,
con cupo propio por ciclo y por día, y estado propio. Un fallo acá nunca
afecta la publicación de la nota.

* ``IG_NATIVE_STORIES_ENABLED=false`` (default): no hace nada.
* ``IG_NATIVE_STORIES_DRY_RUN=true`` (default): genera vista previa + payload
  en ``output/native_stories_preview/`` sin conectarse a Instagram.

Una historia que pudo haber salido (error después de enviarla) queda
``unverified`` y en el ciclo siguiente se busca entre las historias vigentes
de la cuenta antes de reintentar: nunca se publica dos veces a ciegas.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import native_story as ns
from utils.deployment import deployment_plan
from utils.file_manager import FileLock, JsonLockTimeout, JsonStateError
from utils.logging_setup import setup_logger
from utils.social_time import quiet_hours, today_ar
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_native_stories", "native_stories.log")

STAGE = "native_stories"
# Una unverified se busca recién pasado este tiempo (la historia puede tardar
# en aparecer en el listado de la cuenta).
RECONCILE_AFTER_SECONDS = 600


def prepare(candidate: dict) -> tuple[dict | None, str, bytes]:
    """Payload validado para una publicación, o ``(None, motivo, b"")``.

    Lee el permalink de Graph (lectura: no consume el tope de publicaciones)
    y mide la imagen real del post para respetar su proporción.
    """
    from meta import ig_client

    if not candidate.get("in_scope", True):
        return None, f"out_of_scope: {candidate.get('scope_reason')}", b""
    try:
        web_url = ns.validate_web_url(candidate["web_url"])
    except ValueError as exc:
        return None, f"invalid_web_url: {exc}", b""
    info = ig_client.media_info(candidate["media_id"])
    if not info or not info.get("permalink"):
        return None, "media_not_accessible", b""
    try:
        media_pk = ns.media_pk_from_permalink(info["permalink"])
    except ValueError:
        return None, "permalink_without_shortcode", b""
    reel = info.get("media_product_type") == "REELS" or candidate.get("reel", False)
    image_url = str(info.get("thumbnail_url") if info.get("media_type") == "VIDEO" else info.get("media_url") or "")
    aspect, image = ns.measure_aspect(image_url) if image_url else (0.0, b"")
    if not aspect or not image:
        # La imagen del post va dibujada en la historia: sin ella no sale.
        return None, "post_image_unavailable", b""
    location, reason = ns.location_for(candidate["item"])
    if reason:
        logger.info("Historia nativa %s sin ubicación: %s", candidate["media_id"], reason)
    try:
        payload = ns.build_payload(
            media_id=candidate["media_id"], media_pk=media_pk, web_url=web_url, aspect=aspect, location=location, reel=reel,
        )
    except ValueError as exc:
        return None, f"invalid_payload: {exc}", b""
    payload["location_skipped_reason"] = reason or None
    payload["permalink"] = info["permalink"]
    return payload, "", image


def _write_preview(candidate: dict, payload: dict, image: bytes) -> str:
    path = os.path.join(ns.preview_dir(), f"{candidate['media_id']}.png")
    return ns.render_preview(payload, path, image)


def publish_one(client, candidate: dict, payload: dict, attempts: int, image: bytes) -> dict:
    """Publica, verifica y registra. Devuelve ``{"status", ...}``. Propaga
    ``NativeStoryError`` de tipo blocked/credential para frenar la etapa."""
    from meta import instagrapi_client as igc

    media_id = candidate["media_id"]
    ns.mark(media_id, status=ns.STATUS_PROCESSING, attempts=attempts, media_pk=payload["media"]["media_pk"],
            web_url=payload["link"]["url"], started_at=int(time.time()), error="")
    try:
        background = ns.write_story_image(payload, image)
    except (ValueError, OSError) as exc:
        reason = f"story_image_failed: {type(exc).__name__}"
        return {"status": ns.register_failure(media_id, reason, attempts=attempts)["status"], "error": reason}
    try:
        result = client.publish(payload, background)
    except igc.NativeStoryError as err:
        if err.kind == igc.UNVERIFIED:
            ns.mark(media_id, status=ns.STATUS_UNVERIFIED, error=err.code)
            return {"status": ns.STATUS_UNVERIFIED, "error": err.code}
        if err.kind in {igc.BLOCKED, igc.CREDENTIAL, igc.UNAVAILABLE}:
            # No es culpa de la publicación: vuelve a la cola sin gastar intento.
            ns.mark(media_id, status=ns.STATUS_FAILED, attempts=attempts - 1, error=err.code, next_attempt_at=0)
            raise
        return {"status": ns.register_failure(media_id, err.code, attempts=attempts)["status"], "error": err.code}
    finally:
        try:
            os.unlink(background)
        except OSError:
            pass
    return _complete(client, media_id, payload, result)


def _complete(client, media_id: str, payload: dict, result: dict) -> dict:
    from meta import instagrapi_client as igc

    missing: list[str] = []
    try:
        missing = igc.verify(payload, client.inspect(result["story_pk"]))
    except igc.NativeStoryError as err:
        missing = [f"verification_failed:{err.code}"]
    if missing:
        logger.warning("Historia nativa %s publicada sin todos los stickers confirmados: %s", media_id, missing)
    ns.mark(
        media_id, status=ns.STATUS_COMPLETED, day=today_ar().isoformat(), completed_at=int(time.time()),
        story_pk=result["story_pk"], story_id=result.get("story_id"), story_url=result.get("story_url"),
        location_id=(payload.get("location") or {}).get("external_id", ""),
        location_skipped_reason=payload.get("location_skipped_reason"), missing_stickers=missing, error="",
    )
    logger.info("Historia nativa publicada %s → %s (faltan: %s)", media_id, result.get("story_url"), missing or "nada")
    return {"status": ns.STATUS_COMPLETED, "story_pk": result["story_pk"], "missing": missing}


def reconcile(client, media_id: str, entry: dict) -> str:
    """Busca una historia ``unverified`` entre las vigentes de la cuenta."""
    media_pk = int(entry.get("media_pk") or 0)
    if not media_pk:
        ns.mark(media_id, status=ns.STATUS_DEAD, error="unverified_without_media_pk")
        return ns.STATUS_DEAD
    story_pk = client.find_story_for_media(media_pk)
    if story_pk:
        ns.mark(media_id, status=ns.STATUS_COMPLETED, story_pk=story_pk, day=today_ar().isoformat(),
                completed_at=int(time.time()), reconciled=True, error="")
        logger.info("Historia nativa %s reconciliada: ya estaba publicada (%s)", media_id, story_pk)
        return ns.STATUS_COMPLETED
    # No está entre las vigentes: no salió. Cuenta como intento fallido.
    return ns.register_failure(media_id, entry.get("error") or "unverified_not_found", attempts=int(entry.get("attempts") or 1))["status"]


def main(*, force_dry_run: bool = False) -> StageResult:
    started = time.monotonic()
    if not ns.enabled() and not force_dry_run:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    dry = force_dry_run or ns.dry_run()
    if not dry and not deployment_plan().channel_enabled("instagram"):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"instagram_disabled": True})
    if not dry and quiet_hours(window=os.getenv("STORY_QUIET_HOURS", "0-7")):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"quiet_hours": True})

    lock = FileLock(ns.state_path() + ".run", timeout=1, stale_seconds=1800)
    try:
        lock.acquire()
    except JsonLockTimeout:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"locked": True})
    try:
        return _run(dry, started)
    finally:
        lock.release()


def _run(dry: bool, started: float) -> StageResult:
    from meta import instagrapi_client as igc

    try:
        state = ns.load_state()
    except JsonStateError as exc:
        logger.error("Estado de historias nativas ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    now = time.time()
    if not dry and float(state.get("blocked_until") or 0) > now:
        return StageResult(STAGE, StageStatus.DEGRADED, error_type="instagram_blocked",
                           next_retry_at=state["blocked_until"], details={"reason": state.get("block_reason")})

    all_candidates = ns.candidates(state, now=now)
    jobs = state.get("jobs") or {}
    pending = [c for c in all_candidates if c["ready"]]
    to_reconcile = [c for c in pending if (jobs.get(c["media_id"]) or {}).get("status") in {ns.STATUS_UNVERIFIED, ns.STATUS_PROCESSING}]
    fresh = [c for c in pending if c not in to_reconcile]
    budget = min(ns.max_per_cycle(), ns.max_per_day() - ns.stories_today(state))
    selected = fresh[:max(0, budget)]
    outcomes: dict[str, dict] = {}
    succeeded = failed = skipped = 0
    client = None

    try:
        if not dry and (to_reconcile or selected):
            client = igc.NativeStoryClient()
            client.connect()
        for candidate in to_reconcile:
            entry = jobs.get(candidate["media_id"]) or {}
            if dry or now - float(entry.get("updated_at") or 0) < RECONCILE_AFTER_SECONDS:
                continue
            outcomes[candidate["media_id"]] = {"reconciled": reconcile(client, candidate["media_id"], entry)}

        for candidate in selected:
            media_id = candidate["media_id"]
            if candidate["has_graph_story"]:
                # Ya tiene historia por Graph (último momento): no se duplica.
                if not dry:
                    ns.mark(media_id, status=ns.STATUS_SKIPPED, error="graph_story_exists")
                outcomes[media_id] = {"status": ns.STATUS_SKIPPED, "error": "graph_story_exists"}
                skipped += 1
                continue
            payload, reason, image = prepare(candidate)
            if payload is None:
                permanent = reason.startswith(("out_of_scope", "invalid_web_url","permalink_without_shortcode", "invalid_payload"))
                logger.warning("Historia nativa %s no se arma: %s", media_id, reason)
                if not dry:
                    entry = jobs.get(media_id) or {}
                    if permanent:
                        ns.mark(media_id, status=ns.STATUS_SKIPPED, error=reason[:200])
                    else:
                        ns.register_failure(media_id, reason, attempts=int(entry.get("attempts") or 0) + 1)
                outcomes[media_id] = {"status": "not_built", "error": reason[:200]}
                if permanent:
                    skipped += 1
                else:
                    failed += 1
                continue
            if dry:
                outcomes[media_id] = {"status": "dry_run", "preview": _write_preview(candidate, payload, image),
                                      "location_skipped_reason": payload.get("location_skipped_reason")}
                succeeded += 1
                continue
            attempts = int((jobs.get(media_id) or {}).get("attempts") or 0) + 1
            outcome = publish_one(client, candidate, payload, attempts, image)
            outcomes[media_id] = outcome
            if outcome["status"] == ns.STATUS_COMPLETED:
                succeeded += 1
            else:
                failed += 1
    except igc.NativeStoryError as err:
        if err.kind == igc.BLOCKED:
            until = ns.set_blocked(err.code)
            logger.error("Instagram frenó las historias nativas (%s): se pausan hasta %s", err.code, time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
            return _result(all_candidates, selected, succeeded, failed + 1, skipped, outcomes, started, dry,
                           error_type="instagram_blocked", next_retry_at=until)
        if err.kind == igc.CREDENTIAL:
            until = ns.set_blocked(err.code, hours=1)
            return StageResult(STAGE, StageStatus.FAILED, error_type="invalid_credential", error_code=err.code,
                               next_retry_at=until, details={"outcomes": outcomes})
        return StageResult(STAGE, StageStatus.FAILED, error_type="missing_configuration", error_code=err.code,
                           details={"outcomes": outcomes})
    return _result(all_candidates, selected, succeeded, failed, skipped, outcomes, started, dry)


def _result(all_candidates, selected, succeeded, failed, skipped, outcomes, started, dry, **extra) -> StageResult:
    return result_from_counts(
        STAGE,
        received=len(all_candidates),
        selected=len(selected) - skipped,
        processed=succeeded + failed,
        succeeded=succeeded,
        failed=failed,
        deferred=max(0, len(all_candidates) - len(selected)),
        duration_seconds=time.monotonic() - started,
        details={"outcomes": outcomes, "dry_run": dry, "skipped": skipped},
        **extra,
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
