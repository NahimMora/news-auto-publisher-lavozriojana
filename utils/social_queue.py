"""Cola social compatible con el JSON histórico y segura ante concurrencia."""
from __future__ import annotations

import os
import time
from typing import Literal

from utils.editorial_priority import priority_interleave, split_priority_batch
from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.news_dedup import duplicate_reason
from utils.paths import data_dir
from utils.queue_events import record_queue_event
from utils.url_normalization import url_hash

logger = setup_logger("social_queue", "social_queue.log")

QUEUE_PATH = str(data_dir() / "noticias_sociales_pendientes.json")
Platform = Literal["facebook", "instagram"]

SOCIAL_TTL_HOURS = int(os.getenv("SOCIAL_TTL_HOURS", "48"))
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5"))
_TERMINAL_STATES = {"completed", "expired", "dead_letter", "excluded"}


def _load_queue() -> list[dict]:
    return load_json(QUEUE_PATH, [], expected_type=list)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


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


def _social_category_caps() -> dict[str, int]:
    max_deportes = _env_int(
        "SOCIAL_MAX_DEPORTES_PER_RUN",
        _env_int("MAX_DEPORTES_PER_RUN", 1),
    )
    return {"deportes": max_deportes}


def _is_similar_to_existing(titulo: str, queue: list[dict]) -> bool:
    return duplicate_reason(
        {"titulo": titulo},
        queue,
        threshold=DEDUP_SIMILARITY_THRESHOLD,
    ) is not None


def enqueue(noticia: dict, platform: Platform | None = None) -> None:
    """Agrega o activa atómicamente una noticia para las plataformas pedidas."""
    incoming = dict(noticia)
    url = incoming.get("canonical_url") or incoming.get("url") or ""
    incoming["dedup_key"] = incoming.get("dedup_key") or f"link:{url_hash(url)}"
    incoming_keys = _item_keys(incoming)
    outcome = {"action": "unchanged"}

    def mutate(queue):
        if not isinstance(queue, list):
            raise ValueError("La cola social debe ser una lista")
        for item in queue:
            if not isinstance(item, dict) or not (_item_keys(item) & incoming_keys):
                continue
            if platform:
                state = platform_state(item, platform)
                if state == "completed" and item.get(f"{platform}_done_at"):
                    outcome["action"] = "already_completed"
                    return queue
                if state not in {"processing", "dead_letter"}:
                    _set_platform_state(item, platform, "pending")
                    outcome["action"] = "reactivated"
            return queue

        if _is_similar_to_existing(str(incoming.get("titulo") or ""), queue):
            outcome["action"] = "duplicate"
            return queue

        item = dict(incoming)
        item["social_queued_at"] = int(time.time())
        platforms = ("facebook", "instagram")
        for current in platforms:
            enabled = platform is None or platform == current
            _set_platform_state(item, current, "pending" if enabled else "excluded")
        queue.append(item)
        outcome["action"] = "enqueued"
        return queue

    update_json(QUEUE_PATH, mutate, [], expected_type=list)
    action = outcome["action"]
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
    for item in expired_items:
        record_queue_event(
            stage=platform,
            status="expired",
            reason="social_ttl_exceeded",
            item=item,
            metadata={"ttl_hours": SOCIAL_TTL_HOURS},
        )
    return _load_queue(), len(expired_items)


def get_pending(platform: Platform, *, max_items: int | None = None) -> list[dict]:
    """Retorna pendientes; processing nunca se reintenta automáticamente."""
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
    if max_items is None:
        return _priority_interleave(pending)
    selected, deferred = split_priority_batch(
        pending,
        max_items=max_items,
        category_caps=_social_category_caps(),
    )
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


def mark_dead_letter(noticia: dict, platform: Platform, reason: str) -> None:
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
    for item in recovered:
        record_queue_event(
            stage=platform,
            status="dead_letter",
            reason="ambiguous_after_restart_requires_reconciliation",
            item=item,
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
