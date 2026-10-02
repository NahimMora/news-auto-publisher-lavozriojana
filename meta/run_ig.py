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
    post_paparazzi_carousel_to_instagram,
    post_to_instagram_detailed,
    rate_limit_until,
)
from utils.editorial_priority import item_source
from utils.editorial_router import manual_automatic_candidates
from utils.file_manager import JsonStateError, load_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_queue import (
    claim,
    bootstrap_not_before,
    compact_queue,
    enqueue_many,
    get_pending,
    is_too_old_for_bootstrap,
    item_identity,
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
# Fuente con carrusel imagen+video propio (ver docs/DECISIONS.md).
IG_PAPARAZZI_SOURCE_PREFIX = "paparazzi"


def _is_suppressed(noticia: dict) -> bool:
    """Único remanente del router que sigue gateando Instagram: duplicado
    técnico real detectado por utils/editorial_router.py (protección que no
    depende de la curación por lote — ver docs/DECISIONS.md). Qué se publica
    ya lo decide select_publish_batch.py (``selected_for_publish``); esto
    sólo evita republicar una nota que el router marcó como el mismo hecho
    que otra ya en curso."""
    return (noticia.get("route_by_channel") or {}).get("instagram") == "suppressed"


def _item_identities(noticia: dict) -> set[str]:
    identities = {
        str(noticia.get(field) or "").strip()
        for field in ("meta_queue_key", "dedup_key", "web_queue_key", "canonical_url", "url")
        if noticia.get(field)
    }
    identities.add(item_identity(noticia))
    return {identity for identity in identities if identity}


def _matches_manual_automatic(noticia: dict, identities: set[str]) -> bool:
    """True sólo para una promoción manual durable de esta misma noticia."""
    return bool(
        identities
        and not _is_suppressed(noticia)
        and (_item_identities(noticia) & identities)
    )


def _promoted_at(candidate: dict) -> int:
    """Última promoción manual candidate -> automatic (epoch, 0 si no hay)."""
    latest = 0
    for change in candidate.get("manual_override_history") or []:
        if not isinstance(change, dict) or change.get("to") != "automatic":
            continue
        try:
            latest = max(latest, int(change.get("ts") or 0))
        except (TypeError, ValueError):
            continue
    return latest


def _publish_paparazzi(noticia: dict):
    """Nota con video: un único Reel. Sin video utilizable: imagen sola.

    Ya no se publica carrusel portada+video más un reel aparte (dos
    publicaciones de la misma nota en Instagram).
    """
    from utils.paparazzi_reels import publish_paparazzi_reel_as_instagram_post

    if noticia.get("video_url"):
        operation = publish_paparazzi_reel_as_instagram_post(noticia)
        if operation is not None:
            return operation
        logger.info("Sin reel utilizable para la nota de paparazzi; se publica la imagen sola")
    image_only = {
        key: value
        for key, value in noticia.items()
        if key not in ("video_url", "video_duration_seconds", "media_type")
    }
    return post_paparazzi_carousel_to_instagram(image_only)


def _bootstrap_queue() -> tuple[int, int, int, int, int, int]:
    noticias = load_json(META_INPUT, [], expected_type=list)
    included = 0
    omitted_by_policy = 0
    missing_web_url = 0
    included_by_manual_override = 0
    manual_override_without_web_url = 0
    restored_from_candidate_store = 0
    too_old = 0
    batch: list[dict] = []
    not_before = bootstrap_not_before()
    manual_candidates = [
        candidate
        for candidate in manual_automatic_candidates(channel="instagram")
        # Una promoción anterior al corte operativo de colas no se drena sola.
        if not not_before or _promoted_at(candidate) >= not_before
    ]
    manual_by_identity = {
        str(candidate.get("identity") or "").strip(): candidate
        for candidate in manual_candidates
        if str(candidate.get("identity") or "").strip()
    }
    manual_identities = set(manual_by_identity)
    # Pacea el drenaje de un backlog de promociones manuales acumuladas (p.ej.
    # candidatas aprobadas por un operador mientras el gate de ruteo las
    # tenía bloqueadas): sin este tope, todas entran de una sola corrida y
    # pueden superar el timeout de la etapa (varias con video de paparazzi
    # procesan varios minutos cada una). El resto queda para la próxima
    # corrida, no se pierde.
    manual_override_budget = int(os.getenv("IG_MANUAL_OVERRIDE_MAX_PER_RUN", "3"))
    seen_meta_identities: set[str] = set()
    for noticia in noticias:
        seen_meta_identities.update(_item_identities(noticia) & manual_identities)
        manual_override = manual_override_budget > 0 and _matches_manual_automatic(
            noticia, manual_identities
        )
        has_web_url = bool(
            str(noticia.get("web_url") or noticia.get("noticia_url") or "").strip()
        )
        if not has_web_url and not manual_override:
            missing_web_url += 1
            continue
        if not manual_override and not noticia.get("selected_for_publish"):
            omitted_by_policy += 1
            continue
        if not manual_override and _is_suppressed(noticia):
            omitted_by_policy += 1
            continue
        if not manual_override and is_too_old_for_bootstrap(noticia):
            omitted_by_policy += 1
            too_old += 1
            continue
        batch.append(noticia)
        included += 1
        if manual_override:
            manual_override_budget -= 1
            included_by_manual_override += 1
            if not has_web_url:
                manual_override_without_web_url += 1
            logger.info(
                "Override manual habilitado para Instagram (url_web=%s): %s",
                "presente" if has_web_url else "ausente",
                str(noticia.get("dedup_key") or noticia.get("titulo") or "")[:120],
            )

    for identity, candidate in manual_by_identity.items():
        if manual_override_budget <= 0:
            break
        if identity in seen_meta_identities:
            continue
        noticia = candidate.get("noticia")
        if not isinstance(noticia, dict):
            logger.warning(
                "Promoción manual sin payload recuperable en candidatas: %s",
                identity[:120],
            )
            continue
        restored = dict(noticia)
        restored.setdefault("dedup_key", identity)
        route_by_channel = dict(restored.get("route_by_channel") or {})
        route_by_channel["instagram"] = "automatic"
        restored["route_by_channel"] = route_by_channel
        has_web_url = bool(
            str(restored.get("web_url") or restored.get("noticia_url") or "").strip()
        )
        batch.append(restored)
        included += 1
        manual_override_budget -= 1
        included_by_manual_override += 1
        restored_from_candidate_store += 1
        if not has_web_url:
            manual_override_without_web_url += 1
        logger.info(
            "Override manual recuperado desde candidatas (url_web=%s): %s",
            "presente" if has_web_url else "ausente",
            str(restored.get("dedup_key") or restored.get("titulo") or "")[:120],
        )
    if batch:
        enqueue_many(batch, platform="instagram")
    if too_old:
        logger.info("Bootstrap Instagram: %s noticias omitidas por antigüedad", too_old)
    return (
        included,
        omitted_by_policy,
        missing_web_url,
        included_by_manual_override,
        manual_override_without_web_url,
        restored_from_candidate_store,
    )


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
        (
            included,
            omitted,
            missing_web_url,
            manual_overrides,
            manual_without_web_url,
            restored_from_candidates,
        ) = _bootstrap_queue()
        synced = _sync_posted_state()
        all_pending = get_pending("instagram")
        # Qué se publica ya lo decidió select_publish_batch.py (mismo lote
        # que Web y Facebook); acá sólo se pacea cuánto de ese lote se
        # intenta subir en esta corrida puntual.
        limit = int(os.getenv("IG_MAX_PER_RUN", "10"))
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
                "included_by_manual_override": manual_overrides,
                "manual_override_without_web_url": manual_without_web_url,
                "restored_from_candidate_store": restored_from_candidates,
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
        is_paparazzi = item_source(noticia).startswith(IG_PAPARAZZI_SOURCE_PREFIX)
        if is_paparazzi:
            operation = _publish_paparazzi(noticia)
        else:
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
            "included_by_manual_override": manual_overrides,
            "manual_override_without_web_url": manual_without_web_url,
            "restored_from_candidate_store": restored_from_candidates,
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
