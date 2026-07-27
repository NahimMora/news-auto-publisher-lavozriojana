"""Publicación canary aislada, explícita, idempotente y sin consumir colas."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Mapping

import requests

from utils.file_manager import JsonStateError, load_json, update_json
from utils.operation_result import OperationResult
from utils.paths import data_dir
from utils.stage_result import StageResult, StageStatus


CANARY_CHANNELS = ("web", "facebook", "instagram")
_SENSITIVE = {
    "policiales",
    "policial",
    "judiciales",
    "judicial",
    "menores",
    "minoridad",
}
_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def canary_state_path() -> str:
    configured = str(os.getenv("LVR_CANARY_STATE_PATH") or "").strip()
    return configured or str(data_dir() / "canary_runs.json")


def _load_fixture(path: str | os.PathLike[str]) -> dict:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.suffix.lower() != ".json":
        raise ValueError("El fixture canary debe ser un archivo JSON existente")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("El fixture canary no es JSON válido") from exc
    if not isinstance(value, dict):
        raise ValueError("El fixture canary debe contener un objeto")
    return value


def _canary_id(fixture: dict) -> str:
    explicit = str(fixture.get("canary_id") or "").strip()
    if explicit:
        normalized = "".join(character for character in explicit if character.isalnum() or character in "-_")
        if not normalized or len(normalized) > 80:
            raise ValueError("canary_id inválido")
        return normalized
    encoded = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"lvr-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _validate_fixture(fixture: dict) -> None:
    category = str(
        fixture.get("categoria")
        or fixture.get("category")
        or fixture.get("seccion")
        or ""
    ).strip().lower()
    if category in _SENSITIVE:
        raise ValueError("El canary no admite categorías sensibles")
    if bool(fixture.get("breaking") or fixture.get("is_breaking") or fixture.get("isBreaking")):
        raise ValueError("El canary no admite contenido breaking")
    title = str(fixture.get("titulo") or fixture.get("title") or "").strip()
    if not title:
        raise ValueError("El canary requiere título")
    lowered = title.lower()
    if any(word in lowered for word in ("menor de edad", "homicidio", "violación", "detenido")):
        raise ValueError("El título canary contiene temática sensible")


def _decorate_fixture(fixture: dict, canary_id: str) -> dict:
    item = copy.deepcopy(fixture)
    title = str(item.get("titulo") or item.get("title") or "").strip()
    tagged = title if title.upper().startswith("[CANARY LVR]") else f"[CANARY LVR] {title}"
    item["titulo"] = tagged
    item["title"] = tagged
    item["canary_id"] = canary_id
    item["dedup_key"] = f"canary:{canary_id}"
    item["source"] = "lvr_canary"
    return item


def _operation_with_permalink(channel: str, operation: OperationResult) -> OperationResult:
    if not operation.ok or operation.public_url or not operation.external_id:
        return operation
    graph = str(os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0")).rstrip("/")
    token_name = "FB_PAGE_ACCESS_TOKEN" if channel == "facebook" else "IG_ACCESS_TOKEN"
    token = str(os.getenv(token_name) or "").strip()
    if not token:
        operation.status = StageStatus.DEGRADED
        operation.error_type = "missing_permalink_evidence"
        operation.details["publication_outcome"] = "confirmed"
        return operation
    permalink_field = "permalink" if channel == "instagram" else "permalink_url"
    try:
        response = requests.get(
            f"{graph}/{operation.external_id}",
            params={"fields": f"id,{permalink_field}", "access_token": token},
            timeout=30,
        )
        data = response.json() if response.status_code == 200 else {}
        url = str(data.get(permalink_field) or "") if isinstance(data, dict) else ""
    except (requests.RequestException, ValueError):
        url = ""
    if url:
        operation.public_url = url
        return operation
    operation.status = StageStatus.DEGRADED
    operation.error_type = "missing_permalink_evidence"
    operation.details["publication_outcome"] = "confirmed"
    return operation


def _publish_web(item: dict) -> OperationResult:
    from pipeline.node_webapp.publisher import post_payload_detailed, validate_post_payload

    payload = item.get("web_payload")
    if not isinstance(payload, dict):
        return OperationResult(StageStatus.FAILED, error_type="missing_canary_web_payload")
    payload = copy.deepcopy(payload)
    title = str(payload.get("title") or item["titulo"])
    payload["title"] = title if title.upper().startswith("[CANARY LVR]") else f"[CANARY LVR] {title}"
    payload.setdefault("metadata", {})
    payload["metadata"].update(
        {
            "externalId": f"canary:{item['canary_id']}",
            "sourceSystem": "lvr_canary",
            "canary": True,
        }
    )
    warnings = validate_post_payload(payload)
    if warnings:
        return OperationResult(
            StageStatus.FAILED,
            error_type="invalid_canary_payload",
            details={"warnings": warnings},
        )
    return post_payload_detailed(payload)


def _publish_facebook(item: dict) -> OperationResult:
    from meta import fb_client

    fb_client.FB_STATE_PATH = str(data_dir() / "canary_fb_posted.json")
    return _operation_with_permalink("facebook", fb_client.post_to_facebook_detailed(item))


def _publish_instagram(item: dict) -> OperationResult:
    from meta import ig_client

    ig_client.IG_STATE_PATH = str(data_dir() / "canary_ig_posted.json")
    ig_client.IG_RATE_LIMIT_PATH = str(data_dir() / "canary_ig_rate_limit.json")
    return _operation_with_permalink("instagram", ig_client.post_to_instagram_detailed(item))


def default_publishers() -> dict[str, Callable[[dict], OperationResult]]:
    return {
        "web": _publish_web,
        "facebook": _publish_facebook,
        "instagram": _publish_instagram,
    }


def _cleanup_request(channel: str, evidence: dict) -> OperationResult:
    external_id = str(evidence.get("external_id") or "").strip()
    if not external_id:
        return OperationResult(StageStatus.FAILED, error_type="missing_external_id")
    if channel == "web":
        base = str(os.getenv("WEBAPP_BASE_URL") or "").rstrip("/")
        template = str(os.getenv("WEBAPP_CANARY_DELETE_PATH") or "").strip()
        token = str(os.getenv("PRIVATE_API_KEY") or os.getenv("WEBAPP_API_KEY") or "").strip()
        if not base or not template or not token:
            return OperationResult(
                StageStatus.BLOCKED,
                error_type="cleanup_not_supported",
                external_id=external_id,
            )
        endpoint = f"{base}/{template.lstrip('/')}".replace("{id}", external_id)
        headers = {"x-api-key": token}
    else:
        graph = str(os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0")).rstrip("/")
        endpoint = f"{graph}/{external_id}"
        token_name = "FB_PAGE_ACCESS_TOKEN" if channel == "facebook" else "IG_ACCESS_TOKEN"
        token = str(os.getenv(token_name) or "").strip()
        if not token:
            return OperationResult(StageStatus.BLOCKED, error_type="cleanup_missing_credential")
        headers = {}
    try:
        response = requests.delete(
            endpoint,
            headers=headers,
            params={"access_token": token} if channel != "web" else None,
            timeout=30,
        )
        data = response.json()
    except requests.Timeout:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="cleanup_timeout",
            external_id=external_id,
            details={"publication_outcome": "unknown"},
        )
    except (requests.RequestException, ValueError) as exc:
        return OperationResult(
            StageStatus.FAILED,
            error_type=type(exc).__name__,
            external_id=external_id,
        )
    if response.status_code in {200, 204} and (
        response.status_code == 204 or data is True or (isinstance(data, dict) and data.get("success") is True)
    ):
        return OperationResult(StageStatus.SUCCESS, external_id=external_id)
    return OperationResult(
        StageStatus.FAILED,
        error_type="cleanup_rejected",
        error_code=response.status_code,
        external_id=external_id,
    )


def default_cleanupers() -> dict[str, Callable[[dict], OperationResult]]:
    return {
        channel: (lambda evidence, current=channel: _cleanup_request(current, evidence))
        for channel in CANARY_CHANNELS
    }


def _reserve_channel(run_id: str, channel: str, fixture_hash: str) -> tuple[str, dict]:
    outcome = {"action": ""}

    def reserve(state):
        if not isinstance(state, dict):
            raise ValueError("canary_runs.json debe ser un objeto")
        runs = state.setdefault("runs", {})
        run = runs.setdefault(
            run_id,
            {
                "canary_id": run_id,
                "fixture_hash": fixture_hash,
                "created_at": int(time.time()),
                "channels": {},
            },
        )
        if run.get("fixture_hash") != fixture_hash:
            raise ValueError("canary_id reutilizado con contenido diferente")
        current = run["channels"].get(channel) or {}
        status = str(current.get("status") or "")
        if status == "completed":
            outcome.update(action="duplicate", evidence=current.get("evidence") or {})
            return state
        if status in {"processing", "ambiguous"}:
            outcome.update(action="ambiguous", evidence=current.get("evidence") or {})
            return state
        run["channels"][channel] = {
            "status": "processing",
            "started_at": int(time.time()),
        }
        outcome["action"] = "reserved"
        return state

    update_json(canary_state_path(), reserve, {"version": 1, "runs": {}}, expected_type=dict)
    return str(outcome["action"]), dict(outcome.get("evidence") or {})


def _finish_channel(run_id: str, channel: str, status: str, evidence: dict, error_type: str | None) -> None:
    def finish(state):
        run = state["runs"][run_id]
        run["channels"][channel] = {
            "status": status,
            "finished_at": int(time.time()),
            "evidence": copy.deepcopy(evidence),
            "error_type": error_type,
        }
        return state

    update_json(canary_state_path(), finish, {"version": 1, "runs": {}}, expected_type=dict)


def run_canary(
    input_path: str,
    channels: list[str],
    *,
    dry_run: bool,
    confirm_external_publication: bool,
    cleanup: bool = False,
    values: Mapping[str, str] | None = None,
    publishers: Mapping[str, Callable[[dict], OperationResult]] | None = None,
    cleanupers: Mapping[str, Callable[[dict], OperationResult]] | None = None,
) -> StageResult:
    env = os.environ if values is None else values
    requested = list(dict.fromkeys(str(channel).strip().lower() for channel in channels if channel))
    invalid = [channel for channel in requested if channel not in CANARY_CHANNELS]
    if invalid or not requested:
        return StageResult(
            "canary",
            StageStatus.FAILED,
            failed=1,
            error_type="invalid_channels",
            details={"invalid": invalid},
        )
    try:
        fixture = _load_fixture(input_path)
        _validate_fixture(fixture)
        run_id = _canary_id(fixture)
    except ValueError as exc:
        return StageResult(
            "canary",
            StageStatus.FAILED,
            failed=1,
            error_type="invalid_fixture",
            details={"message": str(exc)},
        )
    item = _decorate_fixture(fixture, run_id)
    fixture_hash = hashlib.sha256(
        json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    if dry_run:
        return StageResult(
            "canary",
            StageStatus.SUCCESS,
            received=1,
            selected=1,
            processed=1,
            succeeded=1,
            details={
                "canary_id": run_id,
                "channels": requested,
                "production_calls": False,
                "max_per_channel": 1,
                "fixture_valid": True,
            },
        )
    enabled = str(env.get("CANARY_ENABLED", "false")).lower() in _TRUE
    if not enabled:
        return _blocked_canary("canary_disabled", run_id, requested)
    if not confirm_external_publication:
        return _blocked_canary("external_confirmation_required", run_id, requested)

    handlers = dict(cleanupers or default_cleanupers()) if cleanup else dict(publishers or default_publishers())
    results: dict[str, dict] = {}
    succeeded = failed = ambiguous = blocked = degraded = 0
    for channel in requested:
        if cleanup:
            state = load_json(canary_state_path(), {"version": 1, "runs": {}}, expected_type=dict)
            evidence = (
                ((state.get("runs") or {}).get(run_id) or {}).get("channels", {}).get(channel, {}).get("evidence")
                or {}
            )
            operation = handlers[channel](evidence)
        else:
            try:
                action, evidence = _reserve_channel(run_id, channel, fixture_hash)
            except (JsonStateError, ValueError) as exc:
                operation = OperationResult(StageStatus.FAILED, error_type=type(exc).__name__)
            else:
                if action == "duplicate":
                    operation = OperationResult(
                        StageStatus.SUCCESS,
                        external_id=str(evidence.get("external_id") or ""),
                        public_url=str(evidence.get("public_url") or ""),
                        deduplicated=True,
                        details={"idempotent_replay": True},
                    )
                elif action == "ambiguous":
                    operation = OperationResult(
                        StageStatus.DEGRADED,
                        error_type="ambiguous_external_outcome",
                        details={"publication_outcome": "unknown"},
                    )
                else:
                    try:
                        operation = handlers[channel](item)
                    except Exception as exc:
                        operation = OperationResult(
                            StageStatus.DEGRADED,
                            error_type=type(exc).__name__,
                            retryable=False,
                            details={"publication_outcome": "unknown"},
                        )

        evidence = {
            "external_id": operation.external_id,
            "public_url": operation.public_url,
            "cleanup_supported": not (
                operation.status == StageStatus.BLOCKED
                and operation.error_type in {"cleanup_not_supported", "cleanup_missing_credential"}
            ),
            "deduplicated": operation.deduplicated,
        }
        outcome = str(operation.details.get("publication_outcome") or "")
        is_ambiguous = outcome == "unknown" or operation.error_type == "ambiguous_external_outcome"
        complete_evidence = bool(operation.external_id or operation.public_url)
        if operation.ok and (cleanup or complete_evidence):
            channel_status = "cleanup_completed" if cleanup else "completed"
            succeeded += 1
        elif is_ambiguous:
            channel_status = "ambiguous"
            ambiguous += 1
        elif operation.status == StageStatus.BLOCKED:
            channel_status = "blocked"
            blocked += 1
        elif operation.status == StageStatus.DEGRADED:
            channel_status = "degraded"
            degraded += 1
        else:
            channel_status = "failed"
            failed += 1
        if not cleanup:
            _finish_channel(run_id, channel, channel_status, evidence, operation.error_type)
        results[channel] = {
            **evidence,
            "status": channel_status,
            "error_type": operation.error_type,
            "error_code": operation.error_code,
        }

    if ambiguous or degraded or (succeeded and (failed or blocked)):
        status = StageStatus.DEGRADED
    elif blocked and not succeeded:
        status = StageStatus.BLOCKED
    elif failed and not succeeded:
        status = StageStatus.FAILED
    elif failed:
        status = StageStatus.DEGRADED
    else:
        status = StageStatus.SUCCESS
    return StageResult(
        "canary_cleanup" if cleanup else "canary",
        status,
        received=1,
        selected=1,
        processed=len(requested),
        succeeded=succeeded,
        failed=failed,
        deferred=ambiguous + blocked + degraded,
        error_type=(
            "ambiguous_external_outcome"
            if ambiguous
            else "partial_canary_failure"
            if status == StageStatus.DEGRADED
            else "canary_failed"
            if status == StageStatus.FAILED
            else "canary_blocked"
            if status == StageStatus.BLOCKED
            else None
        ),
        details={
            "canary_id": run_id,
            "channels": results,
            "production_calls": True,
            "cleanup": cleanup,
            "max_per_channel": 1,
            "automatic_retry": False,
        },
    )


def _blocked_canary(error_type: str, run_id: str, channels: list[str]) -> StageResult:
    return StageResult(
        "canary",
        StageStatus.BLOCKED,
        error_type=error_type,
        details={
            "canary_id": run_id,
            "channels": channels,
            "production_calls": False,
        },
    )
