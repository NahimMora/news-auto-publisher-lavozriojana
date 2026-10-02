"""Cola social compatible con el JSON histórico y segura ante concurrencia."""
from __future__ import annotations

import os
import time
from typing import Literal

from utils.editorial_priority import item_source, priority_interleave, split_priority_batch
from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.news_dedup import duplicate_reason
from utils.paths import data_dir
from utils.queue_events import record_queue_event, record_queue_events
from utils.url_normalization import url_hash

logger = setup_logger("social_queue", "social_queue.log")

QUEUE_PATH = str(data_dir() / "noticias_sociales_pendientes.json")
Platform = Literal["facebook", "instagram"]

SOCIAL_TTL_HOURS = int(os.getenv("SOCIAL_TTL_HOURS", "48"))
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5"))
_TERMINAL_STATES = {"completed", "expired", "dead_letter", "excluded"}


def _load_queue() -> list[dict]:
    return load_json(QUEUE_PATH, [], expected_type=list)


def _priority_interleave(items: list[dict]) -> list[dict]:
    return priority_interleave(items)


def _item_keys(item: dict) -> set[str]:
    keys = {
        str(item.get(field) or "").strip()
        for field in ("dedup_key", "meta_queue_key", "web_queue_key")
        if item.get(field)
    }
    for field in ("canonical_url", "url"):
        value = str(item.get(field) or "").strip()
        if value:
            keys.add(f"link:{url_hash(value)}")
    return {key for key in keys if key}


def item_identity(item: dict) -> str:
    keys = sorted(_item_keys(item))
    if keys:
        return keys[0]
    basis = str(item.get("titulo") or repr(sorted(item.items())))
    return f"item:{url_hash(basis)}"


def _state_field(platform: Platform) -> str:
    return f"{platform}_state"


def platform_state(item: dict, platform: Platform) -> str:
    explicit = str(item.get(_state_field(platform)) or "").strip().lower()
    if explicit:
        return explicit
    return "completed" if item.get(f"{platform}_done", False) else "pending"


def _set_platform_state(
    item: dict,
    platform: Platform,
    state: str,
    *,
    reason: str | None = None,
) -> None:
    now = int(time.time())
    item[_state_field(platform)] = state
    item[f"{platform}_updated_at"] = now
    if state in _TERMINAL_STATES:
        item[f"{platform}_done"] = True
        item[f"{platform}_done_at"] = now
    else:
        item[f"{platform}_done"] = False
    if reason:
        item[f"{platform}_reason"] = reason


def _is_similar_to_existing(titulo: str, queue: list[dict]) -> bool:
    return duplicate_reason(
        {"titulo": titulo},
        queue,
        threshold=DEDUP_SIMILARITY_THRESHOLD,
    ) is not None


def _can_reactivate(item: dict, platform: Platform) -> bool:
    """Sólo una exclusión editorial reversible vuelve a pending.

    ``expired``, ``completed``, ``dead_letter`` y ``processing`` nunca se
    reactivan: reactivar ``expired`` generaba un bucle (el TTL la vencía y el
    bootstrap la reactivaba en cada corrida). Una exclusión hecha por un corte
    de operador (motivo ``operator_*``) tampoco se revierte sola.
    """
    if platform_state(item, platform) != "excluded":
        return False
    reason = str(item.get(f"{platform}_reason") or "")
    return not reason.startswith("operator_")


def bootstrap_not_before() -> int:
    """Corte operativo (epoch) bajo el cual ninguna noticia entra nueva a la cola social."""
    raw = str(os.getenv("SOCIAL_BOOTSTRAP_NOT_BEFORE_TS") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(float(raw)))
    except ValueError:
        logger.warning("SOCIAL_BOOTSTRAP_NOT_BEFORE_TS inválido (%r); se ignora", raw)
        return 0


def is_too_old_for_bootstrap(noticia: dict, *, now: float | None = None) -> bool:
    """True si la noticia es anterior al corte operativo o al TTL social.

    Evita que una noticia vieja de ``noticias_meta.json`` vuelva a entrar como
    nueva (con ``social_queued_at`` fresco) después de compactar la cola. Sin
    timestamp durable no se infiere antigüedad.
    """
    try:
        queued_at = int(noticia.get("queued_at") or 0)
    except (TypeError, ValueError):
        queued_at = 0
    if queued_at <= 0:
        return False
    current = time.time() if now is None else now
    if queued_at < bootstrap_not_before():
        return True
    return queued_at < current - SOCIAL_TTL_HOURS * 3600


def enqueue_many(noticias: list[dict], platform: Platform | None = None) -> dict[str, int]:
    """Agrega o activa un lote de noticias con una sola escritura atómica.

    El bootstrap de Facebook/Instagram recorre cientos de noticias por corrida:
    una escritura completa de la cola por noticia excedía el timeout de la etapa.
    """
    incoming_items: list[dict] = []
    for noticia in noticias:
        incoming = dict(noticia)
        url = incoming.get("canonical_url") or incoming.get("url") or ""
        incoming["dedup_key"] = incoming.get("dedup_key") or f"link:{url_hash(url)}"
        incoming_items.append(incoming)

    counts = {
        "enqueued": 0,
        "reactivated": 0,
        "duplicate": 0,
        "already_completed": 0,
        "unchanged": 0,
    }
    actions: list[tuple[str, dict]] = []
    if not incoming_items:
        return counts

    def mutate(queue):
        if not isinstance(queue, list):
            raise ValueError("La cola social debe ser una lista")
        actions.clear()
        index: dict[str, dict] = {}
        for item in queue:
            if isinstance(item, dict):
                for key in _item_keys(item):
                    index.setdefault(key, item)

        for incoming in incoming_items:
            incoming_keys = _item_keys(incoming)
            existing = next((index[key] for key in sorted(incoming_keys) if key in index), None)
            if existing is not None:
                action = "unchanged"
                if platform:
                    state = platform_state(existing, platform)
                    if state == "completed":
                        action = "already_completed"
                    elif _can_reactivate(existing, platform):
                        _set_platform_state(existing, platform, "pending")
                        action = "reactivated"
                actions.append((action, incoming))
                continue

            if _is_similar_to_existing(str(incoming.get("titulo") or ""), queue):
                actions.append(("duplicate", incoming))
                continue

            item = dict(incoming)
            item["social_queued_at"] = int(time.time())
            for current in ("facebook", "instagram"):
                enabled = platform is None or platform == current
                _set_platform_state(item, current, "pending" if enabled else "excluded")
            queue.append(item)
            for key in _item_keys(item):
                index.setdefault(key, item)
            actions.append(("enqueued", incoming))
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    for action, incoming in actions:
        counts[action] += 1
        if action == "duplicate":
            record_queue_event(
                stage="social",
                status="completed",
                reason="duplicate_pending",
                item=incoming,
            )
            logger.info("Descartado por similitud: %s", str(incoming.get("titulo") or "")[:60])
        elif action in {"enqueued", "reactivated"}:
            logger.info("%s: %s", action, str(incoming.get("titulo") or "")[:60])
    return counts


def enqueue(noticia: dict, platform: Platform | None = None) -> None:
    """Agrega o activa atómicamente una noticia para las plataformas pedidas."""
    enqueue_many([noticia], platform)


def _expire_pending(platform: Platform) -> tuple[list[dict], int]:
    cutoff = int(time.time()) - SOCIAL_TTL_HOURS * 3600
    expired_items: list[dict] = []

    def mutate(queue):
        for item in queue:
            if not isinstance(item, dict) or platform_state(item, platform) != "pending":
                continue
            queued_at = int(item.get("social_queued_at", item.get("queued_at", cutoff)) or cutoff)
            if queued_at < cutoff:
                _set_platform_state(item, platform, "expired", reason="social_ttl_exceeded")
                expired_items.append(dict(item))
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    record_queue_events(
        [
            {
                "stage": platform,
                "status": "expired",
                "reason": "social_ttl_exceeded",
                "item": item,
                "metadata": {"ttl_hours": SOCIAL_TTL_HOURS},
            }
            for item in expired_items
        ]
    )
    return _load_queue(), len(expired_items)


def get_pending(
    platform: Platform,
    *,
    max_items: int | None = None,
    source_prefix: str | None = None,
    exclude_source_prefix: str | None = None,
) -> list[dict]:
    """Retorna pendientes; processing nunca se reintenta automáticamente.

    ``source_prefix``/``exclude_source_prefix`` permiten reservar cupo por
    fuente (ej. paparazzi) sin que compita por el mismo ``max_items`` que el
    resto — ver meta/run_ig.py, que llama esta función dos veces (pool
    general + pool reservado) en vez de mezclar todo en una sola selección.
    """
    queue, expired = _expire_pending(platform)
    if expired:
        logger.info(
            "TTL: %s artículos vencidos (+%sh) registrados para %s",
            expired,
            SOCIAL_TTL_HOURS,
            platform,
        )
    pending = [
        item
        for item in queue
        if isinstance(item, dict)
        and item.get("manual_status") != "draft"
        and not item.get("needs_direct_video_url")
        and platform_state(item, platform) == "pending"
    ]
    if source_prefix is not None:
        pending = [item for item in pending if item_source(item).startswith(source_prefix)]
    if exclude_source_prefix is not None:
        pending = [
            item for item in pending if not item_source(item).startswith(exclude_source_prefix)
        ]
    if max_items is None:
        return _priority_interleave(pending)
    selected, deferred = split_priority_batch(pending, max_items=max_items)
    if deferred:
        logger.info(
            "Prioridad editorial %s: %s en lote, %s diferidas",
            platform,
            len(selected),
            len(deferred),
        )
    return selected


def claim(noticia: dict, platform: Platform) -> bool:
    """Transfiere pending→processing antes de llamar a la API externa."""
    keys = _item_keys(noticia)
    claimed = {"ok": False}

    def mutate(queue):
        for item in queue:
            if not isinstance(item, dict) or not (_item_keys(item) & keys):
                continue
            if platform_state(item, platform) != "pending":
                return queue
            _set_platform_state(item, platform, "processing")
            item[f"{platform}_processing_started_at"] = int(time.time())
            claimed["ok"] = True
            return queue
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    return claimed["ok"]


def mark_pending(noticia: dict, platform: Platform, reason: str) -> None:
    """Devuelve a pending sólo fallos que se sabe que ocurrieron antes de publicar."""
    keys = _item_keys(noticia)

    def mutate(queue):
        for item in queue:
            if isinstance(item, dict) and (_item_keys(item) & keys):
                _set_platform_state(item, platform, "pending", reason=reason)
                break
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)


def mark_dead_letter(
    noticia: dict,
    platform: Platform,
    reason: str,
    *,
    metadata: dict | None = None,
) -> None:
    keys = _item_keys(noticia)
    recorded: dict | None = None

    def mutate(queue):
        nonlocal recorded
        for item in queue:
            if isinstance(item, dict) and (_item_keys(item) & keys):
                _set_platform_state(item, platform, "dead_letter", reason=reason)
                recorded = dict(item)
                break
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    record_queue_event(
        stage=platform,
        status="dead_letter",
        reason=reason,
        item=recorded or noticia,
        metadata=metadata,
    )


def mark_done(noticia: dict, platform: Platform, *, evidence: dict | None = None) -> None:
    keys = _item_keys(noticia)

    def mutate(queue):
        for item in queue:
            if isinstance(item, dict) and (_item_keys(item) & keys):
                _set_platform_state(item, platform, "completed")
                if evidence:
                    item[f"{platform}_evidence"] = dict(evidence)
                break
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)


def recover_ambiguous_processing(platform: Platform) -> int:
    """Aísla trabajos interrumpidos: podrían haberse publicado en la API."""
    recovered: list[dict] = []

    def mutate(queue):
        for item in queue:
            if isinstance(item, dict) and platform_state(item, platform) == "processing":
                _set_platform_state(
                    item,
                    platform,
                    "dead_letter",
                    reason="ambiguous_after_restart_requires_reconciliation",
                )
                recovered.append(dict(item))
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    record_queue_events(
        [
            {
                "stage": platform,
                "status": "dead_letter",
                "reason": "ambiguous_after_restart_requires_reconciliation",
                "item": item,
            }
            for item in recovered
        ]
    )
    return len(recovered)


def sync_done_from_posted_state(platform: Platform, posted_keys: set[str]) -> int:
    if not posted_keys:
        return 0
    changed = {"count": 0}

    def mutate(queue):
        for item in queue:
            if not isinstance(item, dict) or not (_item_keys(item) & posted_keys):
                continue
            if platform_state(item, platform) != "completed":
                _set_platform_state(item, platform, "completed")
                changed["count"] += 1
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    if changed["count"]:
        logger.info(
            "%s: %s entradas ya publicadas sincronizadas",
            platform,
            changed["count"],
        )
    return changed["count"]


def compact_queue() -> None:
    """Compacta sólo entradas terminales; la trazabilidad vive en queue_events."""
    removed = {"count": 0}

    def mutate(queue):
        active = [
            item
            for item in queue
            if not (
                platform_state(item, "facebook") in _TERMINAL_STATES
                and platform_state(item, "instagram") in _TERMINAL_STATES
            )
        ]
        removed["count"] = len(queue) - len(active)
        return active

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    if removed["count"]:
        logger.info("Cola compactada: %s entradas terminales", removed["count"])
