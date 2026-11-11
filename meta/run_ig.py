"""Etapa estructurada de publicación en Instagram."""
from __future__ import annotations

import math
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
from utils.editorial_priority import item_category, item_is_breaking, item_source
from utils.editorial_router import detect_riojan_link, manual_automatic_candidates
from utils.file_manager import JsonStateError, load_json
from utils.logging_setup import setup_logger
from utils.paparazzi_video_jobs import local_reel_expected
from utils.paths import data_dir
from utils.same_event import drop_already_posted, drop_superseded
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
    mark_policy_excluded,
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


def _quiet_hours_window() -> tuple[int, int] | None:
    """Lee ``IG_STATIC_QUIET_HOURS`` ("0-7": desde las 0 hasta antes de las 7).

    Vacío o inválido = apagado (comportamiento previo). Las imágenes estáticas
    publicadas de madrugada tienen un alcance mediano de ~20 cuentas contra
    ~200 a la tarde (``cli.py kpis``) y consumen el tope diario de la cuenta.
    """
    raw = os.getenv("IG_STATIC_QUIET_HOURS", "").strip()
    if not raw:
        return None
    try:
        start_raw, end_raw = raw.split("-", 1)
        start, end = int(start_raw), int(end_raw)
    except ValueError:
        logger.warning("IG_STATIC_QUIET_HOURS inválido (%r); horario silencioso apagado", raw)
        return None
    if not (0 <= start <= 23 and 0 <= end <= 24) or start == end:
        logger.warning("IG_STATIC_QUIET_HOURS fuera de rango (%r); horario silencioso apagado", raw)
        return None
    return start, end


def _in_quiet_hours(hour: int, window: tuple[int, int]) -> bool:
    start, end = window
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _is_static_post(noticia: dict) -> bool:
    return not (
        str(noticia.get("media_type") or "").lower() == "video"
        or noticia.get("video_url")
    )


def _split_quiet_hours(selected: list[dict]) -> tuple[list[dict], int]:
    """Difiere imágenes estáticas en horario silencioso sin tomarlas de la cola.

    No hace ``claim``: quedan pendientes y entran en el primer ciclo fuera del
    horario. Reels y videos no se difieren.
    """
    window = _quiet_hours_window()
    if window is None or not _in_quiet_hours(time.localtime().tm_hour, window):
        return selected, 0
    kept = [noticia for noticia in selected if not _is_static_post(noticia)]
    deferred = len(selected) - len(kept)
    if deferred:
        logger.info(
            "Horario silencioso IG (%s-%s h): %s imágenes estáticas quedan para más tarde",
            window[0],
            window[1],
            deferred,
        )
    return kept, deferred


_LOCAL_EXCLUDED_SOURCE_MARKERS = ("paparazzi", "infobae", "internacional")


def _is_local_news(noticia: dict) -> bool:
    """Nota local (Nueva Rioja, Tiempo Popular): ni farándula, ni Infobae, ni internacional."""
    source = item_source(noticia)
    return not any(marker in source for marker in _LOCAL_EXCLUDED_SOURCE_MARKERS)


def _local_categories() -> set[str]:
    """``IG_LOCAL_CATEGORIES``: categorías locales que van a Instagram (vacío = todas).

    Las imágenes locales tienen un alcance mediano de 40-120 cuentas contra
    ~1.240 de espectáculos (ver docs/DECISIONS.md 2026-10-16). Último momento
    siempre pasa. Facebook no aplica este filtro: lleva tráfico a la web.
    """
    raw = os.getenv("IG_LOCAL_CATEGORIES", "")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _local_fill_categories() -> set[str]:
    """``IG_LOCAL_FILL_CATEGORIES``: categorías locales de relleno (vacío = ninguna).

    Entran a Instagram sólo con el cupo del ciclo que no usaron las
    categorías principales (``IG_LOCAL_CATEGORIES``) ni el resto del lote.
    Cuentan para ``IG_LOCAL_DAILY_MAX`` como cualquier nota local.
    """
    raw = os.getenv("IG_LOCAL_FILL_CATEGORIES", "")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _fill_riojan_enabled() -> bool:
    """``IG_LOCAL_FILL_RIOJAN``: las notas locales con vínculo riojano de
    cualquier categoría también entran como relleno."""
    return os.getenv("IG_LOCAL_FILL_RIOJAN", "false").strip().lower() in {"1", "true", "yes", "on"}


def _is_local_fill(noticia: dict) -> bool:
    """Nota local que sólo entra como relleno (no es principal ni último momento)."""
    fill = _local_fill_categories()
    riojan = _fill_riojan_enabled()
    if not (fill or riojan) or not _is_local_news(noticia) or item_is_breaking(noticia):
        return False
    category = item_category(noticia)
    if category in _local_categories():
        return False
    return category in fill or (riojan and detect_riojan_link(noticia)[0])


def _local_allowed_by_category(noticia: dict) -> bool:
    allowed = _local_categories()
    if not allowed or not _is_local_news(noticia):
        return True
    return item_is_breaking(noticia) or item_category(noticia) in allowed or _is_local_fill(noticia)


def _select_with_local_fill(limit: int) -> list[dict]:
    """Lote del ciclo: primero lo principal y, si sobra cupo, el relleno local."""
    if not _local_fill_categories():
        return get_pending("instagram", max_items=limit)
    selected = get_pending(
        "instagram",
        max_items=limit,
        item_filter=lambda noticia: not _is_local_fill(noticia),
    )
    room = limit - len(selected)
    if room > 0:
        fill = get_pending("instagram", max_items=room, item_filter=_is_local_fill)
        if fill:
            logger.info("Relleno local en IG: %s notas con el cupo libre del ciclo", len(fill))
        selected.extend(fill)
    return selected


def _local_daily_max() -> int:
    try:
        return max(0, int(os.getenv("IG_LOCAL_DAILY_MAX", "0")))
    except ValueError:
        return 0


def _local_posted_today(now: float | None = None) -> int:
    """Notas locales ya publicadas hoy (día local) según ``ig_posted.json``."""
    current = time.localtime(now if now is not None else time.time())
    midnight = time.mktime((current.tm_year, current.tm_mon, current.tm_mday, 0, 0, 0, 0, 0, -1))
    state = load_json(IG_STATE_PATH, {"posted": {}}, expected_type=dict)
    posted = state.get("posted")
    if not isinstance(posted, dict):
        return 0
    return sum(
        1
        for record in posted.values()
        if isinstance(record, dict)
        and int(record.get("posted_at") or 0) >= midnight
        and str(record.get("media_type") or "").lower() not in {"reel", "video"}
        and _is_local_news(record)
    )


def _active_day_fraction(now: float | None = None) -> float:
    """Fracción transcurrida del día activo de Instagram (fuera del horario
    silencioso de imágenes): 0 al terminar el silencio, 1 a la medianoche."""
    current = time.localtime(now if now is not None else time.time())
    hour = current.tm_hour + current.tm_min / 60
    window = _quiet_hours_window()
    if window is None:
        return hour / 24
    start, end = window
    quiet = (end - start) % 24
    active = 24 - quiet
    elapsed = (hour - end) % 24
    return min(1.0, elapsed / active) if elapsed < active else 1.0


def _local_pacing_allowance(cap: int, now: float | None = None) -> int:
    """Notas locales que pueden llevar publicadas hoy a esta hora.

    ``IG_LOCAL_PACING_SLACK`` (0 = sin reparto) suma un margen sobre la parte
    proporcional del tope: sin reparto, el tope de 30 se llenaba a media tarde
    y de noche sólo salían Reels.
    """
    try:
        slack = int(os.getenv("IG_LOCAL_PACING_SLACK", "0"))
    except ValueError:
        slack = 0
    if slack <= 0:
        return cap
    return min(cap, math.ceil(cap * _active_day_fraction(now)) + slack)


def _local_pacing_max_age() -> float:
    try:
        return float(os.getenv("IG_LOCAL_PACING_MAX_AGE_HOURS", "6")) * 3600
    except ValueError:
        return 6 * 3600


def _queued_age(noticia: dict, now: float) -> float:
    for field in ("social_queued_at", "queued_at"):
        try:
            value = float(noticia.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value:
            return now - value
    return 0.0


def _apply_local_daily_cap(selected: list[dict]) -> tuple[list[dict], int, int]:
    """Tope diario de notas locales (``IG_LOCAL_DAILY_MAX``, 0 = sin tope),
    repartido a lo largo del día (``IG_LOCAL_PACING_SLACK``).

    ``selected`` ya viene en orden de prioridad (último momento y policiales
    primero). Lo que excede el tope se descarta para Instagram (sigue en Web y
    Facebook): pasarlo al día siguiente publicaría noticias viejas. Lo que
    sólo excede el reparto de esta hora queda pendiente sin tomarlo de la cola
    (sale en un ciclo siguiente) mientras tenga menos de
    ``IG_LOCAL_PACING_MAX_AGE_HOURS``; más vieja, se descarta.
    """
    cap = _local_daily_max()
    if not cap:
        return selected, 0, 0
    now = time.time()
    posted = _local_posted_today(now)
    budget = max(0, cap - posted)
    paced_budget = max(0, min(budget, _local_pacing_allowance(cap, now) - posted))
    kept: list[dict] = []
    excluded = paced = 0
    for noticia in selected:
        # Sin ``selected_for_publish`` sólo entra por promoción manual: no se topea.
        if not noticia.get("selected_for_publish") or not _is_local_news(noticia):
            kept.append(noticia)
        elif paced_budget > 0:
            kept.append(noticia)
            paced_budget -= 1
            budget -= 1
        elif budget > 0 and _queued_age(noticia, now) < _local_pacing_max_age():
            paced += 1
        else:
            mark_policy_excluded(noticia, "instagram", "policy_ig_local_daily_cap")
            excluded += 1
    if excluded:
        logger.info("Tope diario de notas locales en IG (%s): %s descartadas para Instagram", cap, excluded)
    if paced:
        logger.info("Reparto diario de notas locales en IG: %s quedan para un ciclo siguiente", paced)
    return kept, excluded, paced


def _static_quota_ceiling() -> int:
    try:
        return max(0, int(os.getenv("IG_STATIC_QUOTA_CEILING", "0")))
    except ValueError:
        return 0


def _publishing_quota_usage() -> int | None:
    """Publicaciones por API de las últimas 24 h según Meta (lectura: no
    consume el tope). ``None`` si no se pudo leer."""
    from meta.ig_client import graph_get

    data = graph_get(f"{IG_ACCOUNT_ID}/content_publishing_limit", {"fields": "quota_usage"})
    try:
        return int(((data or {}).get("data") or [{}])[0]["quota_usage"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _apply_static_quota_guard(selected: list[dict]) -> tuple[list[dict], int]:
    """Con el tope de Meta (100 cada 24 h) cerca, las imágenes estáticas esperan
    para dejar lugar a los Reels (``IG_STATIC_QUOTA_CEILING``, 0 = apagado).

    Quedan pendientes sin tomarlas de la cola. Si el uso no se puede leer, no
    se frena nada (comportamiento previo).
    """
    ceiling = _static_quota_ceiling()
    if not ceiling or not any(_is_static_post(n) for n in selected):
        return selected, 0
    usage = _publishing_quota_usage()
    if usage is None:
        return selected, 0
    room = max(0, ceiling - usage)
    kept: list[dict] = []
    deferred = 0
    for noticia in selected:
        if not _is_static_post(noticia):
            kept.append(noticia)
        elif room > 0:
            kept.append(noticia)
            room -= 1
        else:
            deferred += 1
    if deferred:
        logger.info(
            "Tope de Meta cerca (%s/24 h, techo para imágenes %s): %s imágenes quedan para más tarde",
            usage,
            ceiling,
            deferred,
        )
    return kept, deferred


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
    # Local con YouTube incrustado: sale como Reel desde run_paparazzi_videos.
    reel_expected = local_reel_expected()
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
        # Seleccionada sólo para la Web (p. ej. paparazzi con video: sale como Reel).
        if not manual_override and noticia.get("social_skip_reason"):
            omitted_by_policy += 1
            continue
        if not manual_override and _is_suppressed(noticia):
            omitted_by_policy += 1
            continue
        if not manual_override and reel_expected(noticia):
            omitted_by_policy += 1
            continue
        if not manual_override and not _local_allowed_by_category(noticia):
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
        selected = _select_with_local_fill(limit)
        selected, superseded = drop_superseded(selected, "instagram")
        selected, same_event_skipped = drop_already_posted(selected, "instagram")
        selected, quiet_deferred = _split_quiet_hours(selected)
        selected, local_cap_excluded, local_paced = _apply_local_daily_cap(selected)
        selected, quota_deferred = _apply_static_quota_guard(selected)
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
                "quiet_hours_deferred": quiet_deferred,
                "local_daily_cap_excluded": local_cap_excluded,
                "local_paced_deferred": local_paced,
                "quota_deferred": quota_deferred,
                "same_event_already_posted": same_event_skipped,
                "included_by_manual_override": manual_overrides,
                "manual_override_without_web_url": manual_without_web_url,
                "restored_from_candidate_store": restored_from_candidates,
                "omitted_by_policy": omitted,
                "blocked_missing_web_url": missing_web_url,
                "synced": synced,
                "ambiguous_to_dead_letter": ambiguous,
                "superseded_by_update": superseded,
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
            "quiet_hours_deferred": quiet_deferred,
            "local_daily_cap_excluded": local_cap_excluded,
            "local_paced_deferred": local_paced,
            "quota_deferred": quota_deferred,
            "same_event_already_posted": same_event_skipped,
            "included_by_manual_override": manual_overrides,
            "manual_override_without_web_url": manual_without_web_url,
            "restored_from_candidate_store": restored_from_candidates,
            "omitted_by_policy": omitted,
            "blocked_missing_web_url": missing_web_url,
            "ambiguous_to_dead_letter": ambiguous,
            "superseded_by_update": superseded,
        },
    )
    if error_type == "invalid_credential":
        result.status = StageStatus.FAILED
    elif error_type == "rate_limit":
        result.status = StageStatus.DEGRADED
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
