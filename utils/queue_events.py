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


def record_queue_event(
    *,
    stage: str,
    status: str,
    reason: str,
    item: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    now = int(time.time())
    event = {
        "event_id": uuid.uuid4().hex,
        "stage": str(stage),
        "status": str(status),
        "reason": str(reason),
        "timestamp": now,
        "item": copy.deepcopy(item or {}),
        "metadata": copy.deepcopy(metadata or {}),
    }
    try:
        retention = max(100, int(os.getenv("QUEUE_EVENT_RETENTION_COUNT", "10000")))
    except ValueError:
        retention = 10000

    def append(events):
        if not isinstance(events, list):
            raise ValueError("queue_events.json debe contener una lista")
        events.append(event)
        if len(events) > retention:
            del events[: len(events) - retention]
        return events

    update_json(events_path(), append, [], expected_type=list)
    return event
