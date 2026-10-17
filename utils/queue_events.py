"""Journal durable de eventos terminales y degradaciones de colas."""
from __future__ import annotations

import copy
import os
import time
import uuid

from utils.file_manager import update_json
from utils.paths import data_dir

# Texto completo de la nota: no aporta al diagnóstico de un evento y hacía que
# cada evento reescribiera un journal de ~40 MB (KNOWN_ISSUES 96). El evento
# conserva identidad (título, URLs, fuente, sección), estado y motivos.
HEAVY_ITEM_FIELDS = frozenset(
    {
        "parrafos",
        "texto_instagram",
        "caption",
        "cta",
        "deck",
        "excerpt",
        "highlight_terms",
        "titulo_original",
        "titulo_original_scrapeado",
        "imagen",
        "imagen_optimizada",
        "web_editorial",
        "contenido",
        "html",
    }
)


def compact_item(item: dict | None) -> dict:
    """Copia de ``item`` sin los campos de texto pesado (idempotente)."""
    return {key: copy.deepcopy(value) for key, value in (item or {}).items() if key not in HEAVY_ITEM_FIELDS}


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
        "item": compact_item(item),
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
        # Eventos previos a la compactación: se achican al pasar (idempotente).
        for event in events:
            item = event.get("item") if isinstance(event, dict) else None
            if isinstance(item, dict) and not HEAVY_ITEM_FIELDS.isdisjoint(item):
                event["item"] = compact_item(item)
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
