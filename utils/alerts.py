"""Detección, deduplicación, outbox y entrega mínima de alertas operativas."""
from __future__ import annotations

import copy
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping

import requests

from utils.file_manager import JsonStateError, load_json, update_json
from utils.heartbeat import heartbeat_snapshot
from utils.paths import data_dir
from utils.queue_events import events_path
from utils.safe_http import UnsafeURLError, safe_request
from utils.stage_result import StageResult, StageStatus


_TRUE = {"1", "true", "yes", "on", "si", "sí"}
_SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)
_TOKEN_TEXT = re.compile(
    r"(?i)\b(access_token|token|secret|api[_-]?key|authorization)\s*[=:]\s*[^\s,;]+"
)


def alert_outbox_path() -> str:
    configured = str(os.getenv("LVR_ALERT_OUTBOX_PATH") or "").strip()
    return configured or str(data_dir() / "alert_outbox.json")


def alert_state_path() -> str:
    configured = str(os.getenv("LVR_ALERT_STATE_PATH") or "").strip()
    return configured or str(data_dir() / "alert_state.json")


def _enabled(values: Mapping[str, str], name: str, default: str) -> bool:
    return str(values.get(name, default) or "").strip().lower() in _TRUE


def sanitize_alert_value(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTADO]" if _SECRET_KEY.search(str(key)) else sanitize_alert_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_alert_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_alert_value(item) for item in value]
    if isinstance(value, str):
        return _TOKEN_TEXT.sub(lambda match: f"{match.group(1)}=[REDACTADO]", value)
    return value


def _empty_state() -> dict:
    return {
        "version": 1,
        "active": {},
        "degraded_counts": {},
        "backlog_history": [],
        "seen_dead_letter_events": [],
        "seen_quarantine_files": [],
    }


def _empty_outbox() -> dict:
    return {"version": 1, "events": []}


def _queue_backlog(snapshot: dict) -> int:
    queues = snapshot.get("queues") or {}
    social = queues.get("social") or {}
    web = queues.get("web") or {}
    rewrite = queues.get("rewrite") or {}
    return sum(
        int(value or 0)
        for value in (
            social.get("facebook_pending"),
            social.get("instagram_pending"),
            web.get("size"),
            rewrite.get("pending"),
            rewrite.get("processing"),
        )
    )


def _dead_letter_event_ids() -> list[str]:
    try:
        events = load_json(events_path(), [], expected_type=list)
    except JsonStateError:
        return []
    return [
        str(event.get("event_id"))
        for event in events
        if isinstance(event, dict)
        and event.get("status") == "dead_letter"
        and event.get("event_id")
    ]


def _quarantine_files() -> list[str]:
    configured = str(os.getenv("LVR_QUARANTINE_DIR") or "").strip()
    root = Path(configured) if configured else data_dir() / "quarantine"
    if not root.is_dir():
        return []
    return sorted(str(path.name) for path in root.iterdir() if path.is_file())


def _detect(snapshot: dict, state: dict, now: int, env: Mapping[str, str]) -> dict[str, dict]:
    conditions: dict[str, dict] = {}
    heartbeat = snapshot.get("heartbeat") or {}
    if heartbeat.get("stale"):
        conditions["heartbeat_stale"] = {
            "type": "heartbeat_stale",
            "severity": "critical",
            "details": {"age_seconds": heartbeat.get("age_seconds")},
        }

    stages = snapshot.get("stages") or []
    degraded_counts = state.setdefault("degraded_counts", {})
    seen_stages: set[str] = set()
    for item in stages:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "unknown")
        seen_stages.add(stage)
        status = str(item.get("status") or "")
        error_type = str(item.get("error_type") or "")
        if status == "failed":
            conditions[f"stage_failed:{stage}"] = {
                "type": "stage_failed",
                "severity": "high",
                "stage": stage,
                "details": {"error_type": error_type, "error_code": item.get("error_code")},
            }
        if status == "degraded":
            degraded_counts[stage] = int(degraded_counts.get(stage, 0)) + 1
        else:
            degraded_counts[stage] = 0
        if degraded_counts[stage] >= 3:
            conditions[f"stage_degraded_repeated:{stage}"] = {
                "type": "stage_degraded_repeated",
                "severity": "medium",
                "stage": stage,
                "details": {"consecutive_cycles": degraded_counts[stage]},
            }
        if error_type == "invalid_credential":
            conditions[f"invalid_credential:{stage}"] = {
                "type": "invalid_credential",
                "severity": "high",
                "stage": stage,
                "details": {},
            }
        if error_type == "selector_mismatch":
            conditions[f"selector_mismatch:{stage}"] = {
                "type": "selector_mismatch",
                "severity": "high",
                "stage": stage,
                "details": {},
            }
        if error_type == "rate_limit":
            retry_at = item.get("next_retry_at")
            try:
                expired_retry = retry_at is not None and float(retry_at) <= now
            except (TypeError, ValueError):
                expired_retry = False
            if expired_retry:
                conditions[f"rate_limit_overdue:{stage}"] = {
                    "type": "rate_limit_overdue",
                    "severity": "medium",
                    "stage": stage,
                    "details": {"next_retry_at": retry_at},
                }
    for stage in list(degraded_counts):
        if stage not in seen_stages:
            degraded_counts[stage] = 0

    history = state.setdefault("backlog_history", [])
    history.append({"timestamp": now, "size": _queue_backlog(snapshot)})
    del history[:-3]
    if len(history) == 3 and history[0]["size"] < history[1]["size"] < history[2]["size"]:
        conditions["backlog_growing"] = {
            "type": "backlog_growing",
            "severity": "medium",
            "details": {"samples": copy.deepcopy(history)},
        }

    seen_dead = set(state.setdefault("seen_dead_letter_events", []))
    current_dead = _dead_letter_event_ids()
    for event_id in current_dead:
        if event_id not in seen_dead:
            conditions[f"dead_letter_new:{event_id}"] = {
                "type": "dead_letter_new",
                "severity": "high",
                "details": {"event_id": event_id},
            }
    state["seen_dead_letter_events"] = current_dead[-5000:]

    seen_quarantine = set(state.setdefault("seen_quarantine_files", []))
    current_quarantine = _quarantine_files()
    for filename in current_quarantine:
        if filename not in seen_quarantine:
            conditions[f"json_quarantined:{filename}"] = {
                "type": "json_quarantined",
                "severity": "high",
                "details": {"filename": filename},
            }
    state["seen_quarantine_files"] = current_quarantine[-5000:]

    minimum = int(env.get("DISK_FREE_MIN_MB", "1024"))
    try:
        free_mb = int(shutil.disk_usage(data_dir()).free / (1024 * 1024))
    except OSError:
        free_mb = -1
    if free_mb < minimum:
        conditions["disk_space_low"] = {
            "type": "disk_space_low",
            "severity": "critical",
            "details": {"free_mb": free_mb, "minimum_mb": minimum},
        }
    return conditions


def _append_events(events: list[dict]) -> None:
    if not events:
        return

    def append(outbox):
        bucket = outbox.setdefault("events", [])
        bucket.extend(copy.deepcopy(events))
        return outbox

    update_json(alert_outbox_path(), append, _empty_outbox(), expected_type=dict)


def process_snapshot(
    snapshot: dict,
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> StageResult:
    env = os.environ if values is None else values
    if not _enabled(env, "ALERTS_ENABLED", "false"):
        return StageResult(
            "alerts",
            StageStatus.NO_WORK,
            details={"disabled": True, "events_created": 0},
        )
    timestamp = int(time.time() if now is None else now)
    dedup_seconds = max(1, int(env.get("ALERT_DEDUP_SECONDS", "3600")))
    recovery_enabled = _enabled(env, "ALERT_RECOVERY_ENABLED", "true")
    state = load_json(alert_state_path(), _empty_state(), expected_type=dict)
    conditions = _detect(snapshot, state, timestamp, env)
    active = state.setdefault("active", {})
    created: list[dict] = []

    for key, condition in conditions.items():
        previous = active.get(key)
        last_emitted = int((previous or {}).get("last_emitted_at") or 0)
        if previous is None or timestamp - last_emitted >= dedup_seconds:
            created.append(
                {
                    "alert_id": uuid.uuid4().hex,
                    "dedup_key": key,
                    "event": "alert",
                    "created_at": timestamp,
                    "delivery_status": (
                        "pending"
                        if str(env.get("ALERT_WEBHOOK_URL") or "").strip()
                        else "local_only"
                    ),
                    "delivery_attempts": 0,
                    **sanitize_alert_value(condition),
                }
            )
            last_emitted = timestamp
        if condition["type"] in {"dead_letter_new", "json_quarantined"}:
            # Son eventos irreversibles, no condiciones recuperables. Su dedupe se
            # conserva en los listados ``seen_*`` y no debe emitir falsa recuperación.
            continue
        active[key] = {
            "type": condition["type"],
            "stage": condition.get("stage"),
            "first_seen_at": int((previous or {}).get("first_seen_at") or timestamp),
            "last_seen_at": timestamp,
            "last_emitted_at": last_emitted,
        }

    for key in list(active):
        if key in conditions:
            continue
        previous = active.pop(key)
        if recovery_enabled:
            created.append(
                {
                    "alert_id": uuid.uuid4().hex,
                    "dedup_key": key,
                    "event": "recovery",
                    "type": previous.get("type"),
                    "stage": previous.get("stage"),
                    "severity": "info",
                    "created_at": timestamp,
                    "delivery_status": (
                        "pending"
                        if str(env.get("ALERT_WEBHOOK_URL") or "").strip()
                        else "local_only"
                    ),
                    "delivery_attempts": 0,
                    "details": {"first_seen_at": previous.get("first_seen_at")},
                }
            )
    update_json(
        alert_state_path(),
        lambda _current: state,
        _empty_state(),
        expected_type=dict,
    )
    _append_events(created)
    return StageResult(
        "alerts",
        StageStatus.SUCCESS if created else StageStatus.NO_WORK,
        received=len(conditions),
        selected=len(conditions),
        processed=len(conditions),
        succeeded=len(created),
        details={"events_created": len(created), "active_conditions": len(conditions)},
    )


def deliver_pending(
    values: Mapping[str, str] | None = None,
    *,
    http_post: Callable = requests.post,
    resolver=None,
    now: float | None = None,
) -> StageResult:
    env = os.environ if values is None else values
    if not _enabled(env, "ALERTS_ENABLED", "false"):
        return StageResult("alert_delivery", StageStatus.NO_WORK, details={"disabled": True})
    webhook = str(env.get("ALERT_WEBHOOK_URL") or "").strip()
    if not webhook:
        return StageResult(
            "alert_delivery",
            StageStatus.NO_WORK,
            details={"local_outbox_only": True},
        )
    timestamp = int(time.time() if now is None else now)
    max_attempts = max(1, int(env.get("ALERT_MAX_DELIVERY_ATTEMPTS", "3")))
    selected: list[dict] = []

    def claim(outbox):
        for event in outbox.get("events", []):
            if event.get("delivery_status") != "pending":
                continue
            retry_at = int(event.get("next_retry_at") or 0)
            if retry_at > timestamp or int(event.get("delivery_attempts") or 0) >= max_attempts:
                continue
            event["delivery_status"] = "delivering"
            event["delivery_attempts"] = int(event.get("delivery_attempts") or 0) + 1
            selected.append(copy.deepcopy(event))
            break
        return outbox

    update_json(alert_outbox_path(), claim, _empty_outbox(), expected_type=dict)
    if not selected:
        return StageResult("alert_delivery", StageStatus.NO_WORK)
    event = selected[0]
    status = StageStatus.SUCCESS
    error_type = None
    next_retry_at = None
    try:
        response = safe_request(
            "POST",
            webhook,
            requester=http_post,
            resolver=resolver,
            json=sanitize_alert_value(event),
            timeout=15,
        )
        http_status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= http_status < 300:
            delivery_status = "delivered"
        elif http_status == 429:
            delivery_status = "pending"
            status = StageStatus.DEGRADED
            error_type = "rate_limit"
            try:
                delay = max(1, int((getattr(response, "headers", {}) or {}).get("Retry-After", "60")))
            except ValueError:
                delay = 60
            next_retry_at = timestamp + delay
        else:
            delivery_status = (
                "failed"
                if int(event.get("delivery_attempts") or 0) >= max_attempts
                else "pending"
            )
            status = StageStatus.DEGRADED
            error_type = "webhook_rejected"
    except requests.Timeout:
        delivery_status = "pending"
        status = StageStatus.DEGRADED
        error_type = "timeout"
        next_retry_at = timestamp + 60
    except (requests.RequestException, UnsafeURLError) as exc:
        delivery_status = "pending"
        status = StageStatus.DEGRADED
        error_type = type(exc).__name__
        next_retry_at = timestamp + 60

    def finish(outbox):
        for current in outbox.get("events", []):
            if current.get("alert_id") != event["alert_id"]:
                continue
            current["delivery_status"] = delivery_status
            current["last_delivery_at"] = timestamp
            current["delivery_error"] = error_type
            current["next_retry_at"] = next_retry_at
            break
        return outbox

    update_json(alert_outbox_path(), finish, _empty_outbox(), expected_type=dict)
    return StageResult(
        "alert_delivery",
        status,
        received=1,
        selected=1,
        processed=1,
        succeeded=1 if status == StageStatus.SUCCESS else 0,
        failed=0 if status == StageStatus.SUCCESS else 1,
        error_type=error_type,
        next_retry_at=next_retry_at,
        details={"notifier_failed": status != StageStatus.SUCCESS},
    )


def monitor_operational_state(
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> StageResult:
    snapshot = heartbeat_snapshot(now=now)
    data = snapshot.get("data") or {}
    normalized = {
        "heartbeat": {key: value for key, value in snapshot.items() if key != "data"},
        "stages": data.get("stages") or [],
        "queues": data.get("queues") or {},
    }
    detection = process_snapshot(normalized, values, now=now)
    if detection.status == StageStatus.NO_WORK and detection.details.get("disabled"):
        return detection
    delivery = deliver_pending(values, now=now)
    if delivery.status == StageStatus.DEGRADED:
        detection.details["notifier"] = delivery.to_dict()
        detection.status = StageStatus.DEGRADED
        detection.error_type = "notifier_failure"
        detection.failed = max(1, detection.failed)
    return detection


def alert_test(
    values: Mapping[str, str] | None = None,
    *,
    http_post: Callable = requests.post,
    resolver=None,
    now: float | None = None,
) -> StageResult:
    env = os.environ if values is None else values
    if not _enabled(env, "ALERTS_ENABLED", "false"):
        return StageResult(
            "alert_test",
            StageStatus.NO_WORK,
            details={"disabled": True, "event_created": False},
        )
    timestamp = int(time.time() if now is None else now)
    event = {
        "alert_id": uuid.uuid4().hex,
        "dedup_key": "manual_alert_test",
        "event": "alert",
        "type": "manual_alert_test",
        "severity": "info",
        "created_at": timestamp,
        "delivery_status": (
            "pending" if str(env.get("ALERT_WEBHOOK_URL") or "").strip() else "local_only"
        ),
        "delivery_attempts": 0,
        "details": {"message": "Prueba operativa La Voz Riojana"},
    }
    _append_events([event])
    delivery = deliver_pending(
        env,
        http_post=http_post,
        resolver=resolver,
        now=timestamp,
    )
    status = StageStatus.DEGRADED if delivery.status == StageStatus.DEGRADED else StageStatus.SUCCESS
    return StageResult(
        "alert_test",
        status,
        received=1,
        selected=1,
        processed=1,
        succeeded=1,
        error_type=delivery.error_type if status == StageStatus.DEGRADED else None,
        details={
            "event_created": True,
            "delivery": delivery.to_dict(),
            "contains_secrets": False,
        },
    )
