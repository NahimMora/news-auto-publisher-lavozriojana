"""Heartbeat persistente y métricas de cola para supervisor/CLI."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from utils.file_manager import JsonCorruptionError, JsonStateError, load_json, save_json
from utils.paths import data_dir
from utils.stage_result import StageResult


def _iso_from_timestamp(value: float | int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z")


def heartbeat_path() -> str:
    return str(data_dir() / "supervisor_heartbeat.json")


def write_heartbeat(
    *,
    cycle_number: int,
    supervisor_status: str,
    heartbeat_at: float | int | None = None,
    cycle_started_at: float | int | None = None,
    cycle_finished_at: float | int | None = None,
    stage_results: Iterable[StageResult | dict] = (),
    pid: int | None = None,
) -> dict:
    now = float(time.time() if heartbeat_at is None else heartbeat_at)
    stages = [
        result.to_dict() if isinstance(result, StageResult) else dict(result)
        for result in stage_results
    ]
    payload = {
        "version": 1,
        "pid": int(pid or os.getpid()),
        "supervisor_status": str(supervisor_status),
        "cycle_number": int(cycle_number),
        "heartbeat_at_ts": now,
        "heartbeat_at": _iso_from_timestamp(now),
        "cycle_started_at_ts": float(cycle_started_at) if cycle_started_at is not None else None,
        "cycle_started_at": _iso_from_timestamp(cycle_started_at),
        "cycle_finished_at_ts": float(cycle_finished_at) if cycle_finished_at is not None else None,
        "cycle_finished_at": _iso_from_timestamp(cycle_finished_at),
        "stages": stages,
        "queues": collect_queue_metrics(),
    }
    save_json(heartbeat_path(), payload)
    return payload


def heartbeat_snapshot(*, now: float | int | None = None) -> dict:
    path = heartbeat_path()
    if not os.path.exists(path):
        return {
            "present": False,
            "stale": True,
            "age_seconds": None,
            "status": "missing",
            "data": None,
        }
    try:
        payload = load_json(path, {}, expected_type=dict)
    except JsonCorruptionError as exc:
        return {
            "present": True,
            "stale": True,
            "age_seconds": None,
            "status": "corrupt",
            "error": str(exc),
            "data": None,
        }
    except JsonStateError as exc:
        return {
            "present": True,
            "stale": True,
            "age_seconds": None,
            "status": "error",
            "error": str(exc),
            "data": None,
        }
    current = float(time.time() if now is None else now)
    try:
        timestamp = float(payload.get("heartbeat_at_ts"))
    except (TypeError, ValueError):
        return {
            "present": True,
            "stale": True,
            "age_seconds": None,
            "status": "invalid",
            "data": payload,
        }
    age = max(0, int(current - timestamp))
    try:
        stale_seconds = max(1, int(os.getenv("PIPELINE_24X7_STALE_SECONDS", "900")))
    except ValueError:
        stale_seconds = 900
    return {
        "present": True,
        "stale": age > stale_seconds,
        "age_seconds": age,
        "stale_after_seconds": stale_seconds,
        "status": "stale" if age > stale_seconds else "fresh",
        "data": payload,
    }


def _read_queue(path: Path, default, expected_type) -> tuple[object | None, dict]:
    if not path.exists():
        return default, {"status": "missing"}
    try:
        return load_json(str(path), default, expected_type=expected_type), {"status": "ok"}
    except JsonCorruptionError as exc:
        return None, {"status": "corrupt", "error": str(exc)}
    except JsonStateError as exc:
        return None, {"status": "error", "error": str(exc)}


def _platform_pending(item: dict, platform: str) -> bool:
    status = str(
        item.get(f"{platform}_state")
        or item.get(f"{platform}_status")
        or ""
    ).lower()
    if status in {"completed", "expired", "dead_letter", "excluded"}:
        return False
    if status in {"pending", "processing"}:
        return True
    return not bool(item.get(f"{platform}_done"))


def collect_queue_metrics() -> dict:
    root = data_dir()
    social, social_status = _read_queue(
        root / "noticias_sociales_pendientes.json",
        [],
        list,
    )
    meta, meta_status = _read_queue(root / "noticias_meta.json", [], list)
    web, web_status = _read_queue(root / "noticias_web_pending.json", [], list)
    rewrite, rewrite_status = _read_queue(root / "rewrite_queue_state.json", {}, dict)

    if isinstance(social, list):
        social_status.update(
            size=len(social),
            facebook_pending=sum(
                1 for item in social if isinstance(item, dict) and _platform_pending(item, "facebook")
            ),
            instagram_pending=sum(
                1 for item in social if isinstance(item, dict) and _platform_pending(item, "instagram")
            ),
        )
    if isinstance(meta, list):
        meta_status["size"] = len(meta)
    if isinstance(web, list):
        web_status["size"] = len(web)
    if isinstance(rewrite, dict):
        rewrite_status.update(
            {
                bucket: len(rewrite.get(bucket, []))
                for bucket in (
                    "pending",
                    "processing",
                    "completed",
                    "failed",
                    "expired",
                    "dead_letter",
                )
            }
        )

    return {
        "social": social_status,
        "meta": meta_status,
        "web": web_status,
        "rewrite": rewrite_status,
    }
