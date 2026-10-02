"""Journal durable de eventos terminales y degradaciones de colas."""
from __future__ import annotations

import copy
import os
import time
import uuid

from utils.file_manager import update_json
from utils.paths import data_dir


def events_path() -> str:
    configured = str(os.getenv("LVR_QUEUE_EVENTS_PATH") or "").strip()
    return configured or str(data_dir() / "queue_events.json")


def _build_event(
    *,
    stage: str,
    status: str,
    reason: str,
    item: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "stage": str(stage),
        "status": str(status),
        "reason": str(reason),
        "timestamp": int(time.time()),
        "item": copy.deepcopy(item or {}),
        "metadata": copy.deepcopy(metadata or {}),
    }


def _append_events(new_events: list[dict]) -> None:
    try:
        retention = max(100, int(os.getenv("QUEUE_EVENT_RETENTION_COUNT", "10000")))
    except ValueError:
        retention = 10000

    def append(events):
        if not isinstance(events, list):
            raise ValueError("queue_events.json debe contener una lista")
        events.extend(new_events)
        if len(events) > retention:
            del events[: len(events) - retention]
        return events

    update_json(events_path(), append, [], expected_type=list)


def record_queue_event(
    *,
    stage: str,
    status: str,
    reason: str,
    item: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    event = _build_event(
        stage=stage,
        status=status,
        reason=reason,
        item=item,
        metadata=metadata,
    )
    _append_events([event])
    return event


def record_queue_events(entries: list[dict]) -> list[dict]:
    """Registra varios eventos con una sola escritura del journal.

    Cada entrada acepta las mismas claves que ``record_queue_event``.
    """
    events = [_build_event(**entry) for entry in entries]
    if events:
        _append_events(events)
    return events
