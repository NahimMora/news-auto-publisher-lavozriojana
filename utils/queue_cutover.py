"""Corte operativo de colas por fecha, con archivo durable y trazabilidad."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Mapping

from utils.file_manager import load_json, update_json_files
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.queue_events import record_queue_event
from utils.url_normalization import url_hash


logger = setup_logger("queue_cutover", "queue_cutover.log")
_TERMINAL_SOCIAL_STATES = {"completed", "expired", "dead_letter", "excluded"}


def _path(env: Mapping[str, str], variable: str, filename: str) -> str:
    configured = str(env.get(variable) or "").strip()
    return configured or str(data_dir() / filename)


def _paths(env: Mapping[str, str]) -> dict[str, str]:
    return {
        "web": _path(env, "WEB_QUEUE_PATH", "noticias_web_pending.json"),
        "meta": _path(env, "META_QUEUE_PATH", "noticias_meta.json"),
        "social": _path(env, "SOCIAL_QUEUE_PATH", "noticias_sociales_pendientes.json"),
        "archive": _path(
            env,
            "LVR_QUEUE_CUTOVER_ARCHIVE_PATH",
            "queue_cutover_archive.json",
        ),
    }


def _parse_cutoff(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("La fecha de corte debe usar YYYY-MM-DD") from exc


def _article_date(item: dict) -> date | None:
    value = str(item.get("fecha") or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _identity(item: dict, index: int) -> str:
    for field in ("web_queue_key", "meta_queue_key", "dedup_key"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    url = str(item.get("canonical_url") or item.get("url") or "").strip()
    if url:
        return f"link:{url_hash(url)}"
    return f"index:{index}"


def _queue_summary(items: list, cutoff: date) -> tuple[dict, list[dict]]:
    before = current = unknown = 0
    identities: list[dict] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            unknown += 1
            identities.append({"item_id": f"invalid:{index}", "fecha": None})
            continue
        item_date = _article_date(raw)
        if item_date is None:
            unknown += 1
        elif item_date < cutoff:
            before += 1
        else:
            current += 1
        identities.append(
            {
                "item_id": _identity(raw, index),
                "fecha": item_date.isoformat() if item_date else None,
            }
        )
    return (
        {
            "total": len(items),
            "before_cutoff": before,
            "on_or_after_cutoff": current,
            "unknown_date": unknown,
        },
        identities,
    )


def build_cutover_report(
    cutoff_date: str,
    values: Mapping[str, str] | None = None,
) -> dict:
    env = os.environ if values is None else values
    cutoff = _parse_cutoff(cutoff_date)
    paths = _paths(env)
    queues: dict[str, dict] = {}
    stable: dict[str, list[dict]] = {}
    for name in ("web", "meta", "social"):
        items = load_json(paths[name], [], expected_type=list)
        queues[name], stable[name] = _queue_summary(items, cutoff)
    report_id = hashlib.sha256(
        json.dumps(
            {"cutoff": cutoff.isoformat(), "queues": stable},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "version": 1,
        "report_id": report_id,
        "cutoff_date": cutoff.isoformat(),
        "report_only": True,
        "modified_queues": False,
        "queues": queues,
    }


def _social_state(item: dict, platform: str) -> str:
    explicit = str(item.get(f"{platform}_state") or "").strip().lower()
    if explicit:
        return explicit
    return "completed" if item.get(f"{platform}_done") else "pending"


def apply_cutover(
    cutoff_date: str,
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> dict:
    env = os.environ if values is None else values
    report = build_cutover_report(cutoff_date, env)
    unknown = sum(
        int(queue["unknown_date"])
        for queue in report["queues"].values()
    )
    if unknown:
        raise ValueError(
            f"Hay {unknown} entradas sin fecha válida; el corte no modificó ninguna cola"
        )

    cutoff = _parse_cutoff(cutoff_date)
    timestamp = int(time.time() if now is None else now)
    paths = _paths(env)
    archived_events: list[dict] = []
    social_events: list[dict] = []
    counters = {
        "web_archived": 0,
        "meta_archived": 0,
        "social_states_expired": 0,
        "social_processing_dead_letter": 0,
    }

    def mutate(files):
        archive = files[paths["archive"]]
        known_archive_ids = {
            str(entry.get("archive_id") or "")
            for entry in archive
            if isinstance(entry, dict)
        }
        for queue_name in ("web", "meta"):
            retained: list = []
            for index, raw in enumerate(files[paths[queue_name]]):
                item = copy.deepcopy(raw)
                if not isinstance(item, dict) or _article_date(item) >= cutoff:
                    retained.append(raw)
                    continue
                item_id = _identity(item, index)
                archive_id = hashlib.sha256(
                    f"{queue_name}|{item_id}|{cutoff.isoformat()}".encode("utf-8")
                ).hexdigest()
                if archive_id not in known_archive_ids:
                    archive.append(
                        {
                            "archive_id": archive_id,
                            "queue": queue_name,
                            "item_id": item_id,
                            "cutoff_date": cutoff.isoformat(),
                            "archived_at": timestamp,
                            "reason": "operator_cutover_before_date",
                            "item": item,
                        }
                    )
                    known_archive_ids.add(archive_id)
                counters[f"{queue_name}_archived"] += 1
                archived_events.append(
                    {"queue": queue_name, "item_id": item_id, "item": item}
                )
            files[paths[queue_name]] = retained

        for index, raw in enumerate(files[paths["social"]]):
            if not isinstance(raw, dict) or _article_date(raw) >= cutoff:
                continue
            item_id = _identity(raw, index)
            for platform in ("facebook", "instagram"):
                state = _social_state(raw, platform)
                if state in _TERMINAL_SOCIAL_STATES:
                    continue
                if state == "processing":
                    destination = "dead_letter"
                    reason = "operator_cutover_processing_ambiguous"
                    counters["social_processing_dead_letter"] += 1
                else:
                    destination = "expired"
                    reason = "operator_cutover_before_date"
                    counters["social_states_expired"] += 1
                raw[f"{platform}_state"] = destination
                raw[f"{platform}_done"] = True
                raw[f"{platform}_done_at"] = timestamp
                raw[f"{platform}_updated_at"] = timestamp
                raw[f"{platform}_reason"] = reason
                social_events.append(
                    {
                        "platform": platform,
                        "status": destination,
                        "reason": reason,
                        "item_id": item_id,
                        "item": copy.deepcopy(raw),
                    }
                )
        return files

    update_json_files(
        {
            paths["archive"]: ([], list),
            paths["web"]: ([], list),
            paths["meta"]: ([], list),
            paths["social"]: ([], list),
        },
        mutate,
        save_order=[
            paths["archive"],
            paths["web"],
            paths["meta"],
            paths["social"],
        ],
    )

    for event in archived_events:
        record_queue_event(
            stage=event["queue"],
            status="expired",
            reason="operator_cutover_before_date",
            item=event["item"],
            metadata={
                "item_id": event["item_id"],
                "cutoff_date": cutoff.isoformat(),
                "archive_path": str(Path(paths["archive"]).name),
            },
        )
    for event in social_events:
        record_queue_event(
            stage=event["platform"],
            status=event["status"],
            reason=event["reason"],
            item=event["item"],
            metadata={
                "item_id": event["item_id"],
                "cutoff_date": cutoff.isoformat(),
            },
        )

    logger.info(
        "Corte %s aplicado: web=%s meta=%s estados_sociales=%s",
        cutoff.isoformat(),
        counters["web_archived"],
        counters["meta_archived"],
        counters["social_states_expired"],
    )
    return {
        "status": "success",
        "report_id": report["report_id"],
        "cutoff_date": cutoff.isoformat(),
        "archive_path": paths["archive"],
        **counters,
    }
