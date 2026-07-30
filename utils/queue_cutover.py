"""Cortes operativos de colas con archivo durable y trazabilidad."""
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


def _window_identity(item: dict, index: int, queue_name: str) -> str:
    dedup_key = str(item.get("dedup_key") or "").strip()
    if dedup_key:
        return dedup_key
    url = str(item.get("canonical_url") or item.get("url") or "").strip()
    if url:
        return f"link:{url_hash(url)}"
    for field in ("web_queue_key", "meta_queue_key"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return f"{queue_name}:index:{index}"


def _queue_timestamp(item: dict, queue_name: str) -> int | None:
    fields = {
        "web": ("web_queued_at", "queued_at"),
        "meta": ("queued_at", "web_queued_at"),
        "social": ("social_queued_at", "queued_at", "web_queued_at"),
    }[queue_name]
    for field in fields:
        value = item.get(field)
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp > 0:
            return timestamp
    return None


def _latest_window_state(
    keep_latest: int,
    env: Mapping[str, str],
) -> tuple[
    dict[str, str],
    dict[str, list],
    list[str],
    dict[str, tuple[int, int]],
    int,
]:
    if keep_latest <= 0:
        raise ValueError("--keep-latest debe ser mayor que cero")
    paths = _paths(env)
    queues = {
        name: load_json(paths[name], [], expected_type=list)
        for name in ("web", "meta", "social")
    }
    scores: dict[str, tuple[int, int]] = {}
    unknown_order = 0
    for queue_name in ("web", "meta"):
        for index, raw in enumerate(queues[queue_name]):
            if not isinstance(raw, dict):
                unknown_order += 1
                continue
            item_id = _window_identity(raw, index, queue_name)
            timestamp = _queue_timestamp(raw, queue_name)
            if timestamp is None:
                unknown_order += 1
                continue
            score = (timestamp, index)
            scores[item_id] = max(scores.get(item_id, (0, -1)), score)
    ranked = [
        item_id
        for item_id, _ in sorted(
            scores.items(),
            key=lambda entry: (entry[1], entry[0]),
            reverse=True,
        )
    ]
    keep_ids = set(ranked[:keep_latest])
    return paths, queues, ranked, scores, unknown_order


def build_latest_window_report(
    keep_latest: int,
    values: Mapping[str, str] | None = None,
) -> dict:
    """Reporta un corte por orden durable de encolado, independiente de ``fecha``."""
    env = os.environ if values is None else values
    paths, queues, ranked, scores, unknown_order = _latest_window_state(
        keep_latest,
        env,
    )
    keep_ids = set(ranked[:keep_latest])
    summaries: dict[str, dict] = {}
    stable: dict[str, list[dict]] = {}
    for queue_name, items in queues.items():
        identities = [
            _window_identity(raw, index, queue_name)
            if isinstance(raw, dict)
            else f"{queue_name}:invalid:{index}"
            for index, raw in enumerate(items)
        ]
        retained = sum(item_id in keep_ids for item_id in identities)
        summaries[queue_name] = {
            "total": len(items),
            "retained": retained,
            "older_than_window": len(items) - retained,
        }
        stable[queue_name] = [
            {
                "item_id": item_id,
                "queued_at": scores[item_id][0] if item_id in scores else None,
                "queue_order": scores[item_id][1] if item_id in scores else None,
            }
            for item_id in identities
        ]
    report_id = hashlib.sha256(
        json.dumps(
            {
                "keep_latest": keep_latest,
                "queues": stable,
                "ranked": ranked,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "version": 2,
        "report_id": report_id,
        "strategy": "latest_durable_queue_order",
        "keep_latest": keep_latest,
        "unique_items": len(ranked),
        "unknown_order": unknown_order,
        "report_only": True,
        "modified_queues": False,
        "queues": summaries,
        "archive_path": paths["archive"],
    }


def apply_latest_window(
    keep_latest: int,
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> dict:
    """Conserva las últimas N noticias y archiva el resto sin fingir publicación."""
    env = os.environ if values is None else values
    report = build_latest_window_report(keep_latest, env)
    if report["unknown_order"]:
        raise ValueError(
            f"Hay {report['unknown_order']} entradas sin timestamp durable; "
            "el corte no modificó ninguna cola"
        )

    paths, _, ranked, _, _ = _latest_window_state(keep_latest, env)
    keep_ids = set(ranked[:keep_latest])
    timestamp = int(time.time() if now is None else now)
    archived_events: list[dict] = []
    social_events: list[dict] = []
    counters = {
        "web_archived": 0,
        "meta_archived": 0,
        "social_states_excluded": 0,
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
                if not isinstance(raw, dict):
                    retained.append(raw)
                    continue
                item_id = _window_identity(raw, index, queue_name)
                if item_id in keep_ids:
                    retained.append(raw)
                    continue
                item = copy.deepcopy(raw)
                archive_id = hashlib.sha256(
                    f"latest|{keep_latest}|{queue_name}|{item_id}".encode("utf-8")
                ).hexdigest()
                if archive_id not in known_archive_ids:
                    archive.append(
                        {
                            "archive_id": archive_id,
                            "queue": queue_name,
                            "item_id": item_id,
                            "keep_latest": keep_latest,
                            "archived_at": timestamp,
                            "reason": "operator_baseline_older_than_latest_window",
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
            if not isinstance(raw, dict):
                continue
            item_id = _window_identity(raw, index, "social")
            if item_id in keep_ids:
                continue
            for platform in ("facebook", "instagram"):
                state = _social_state(raw, platform)
                if state in _TERMINAL_SOCIAL_STATES:
                    continue
                if state == "processing":
                    destination = "dead_letter"
                    reason = "operator_baseline_processing_ambiguous"
                    counters["social_processing_dead_letter"] += 1
                else:
                    destination = "excluded"
                    reason = "operator_baseline_older_than_latest_window"
                    counters["social_states_excluded"] += 1
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
            status="excluded",
            reason="operator_baseline_older_than_latest_window",
            item=event["item"],
            metadata={
                "item_id": event["item_id"],
                "keep_latest": keep_latest,
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
                "keep_latest": keep_latest,
            },
        )

    logger.info(
        "Corte últimas %s aplicado: web=%s meta=%s estados_sociales=%s",
        keep_latest,
        counters["web_archived"],
        counters["meta_archived"],
        counters["social_states_excluded"],
    )
    return {
        "status": "success",
        "report_id": report["report_id"],
        "strategy": "latest_durable_queue_order",
        "keep_latest": keep_latest,
        "archive_path": paths["archive"],
        **counters,
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
