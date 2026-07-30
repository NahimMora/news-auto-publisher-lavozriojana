"""Conciliación explícita y conservadora del backlog histórico de Facebook."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Mapping

import requests

from utils.file_manager import load_json, update_json
from utils.paths import data_dir
from utils.queue_events import record_queue_event
from utils.url_normalization import canonical_url, url_hash


CLASSIFICATIONS = (
    "already_published",
    "pending_valid",
    "expired",
    "duplicate",
    "ambiguous",
    "invalid",
    "blocked_missing_web_url",
)


def _paths(values: Mapping[str, str]) -> tuple[str, str]:
    queue = str(values.get("SOCIAL_QUEUE_PATH") or data_dir() / "noticias_sociales_pendientes.json")
    posted = str(values.get("FB_POSTED_PATH") or data_dir() / "fb_posted.json")
    return queue, posted


def _keys(item: dict) -> set[str]:
    result = {
        str(item.get(name) or "").strip()
        for name in ("dedup_key", "meta_queue_key", "web_queue_key")
        if item.get(name)
    }
    for name in ("canonical_url", "url"):
        value = str(item.get(name) or "").strip()
        if value:
            result.add(f"link:{url_hash(canonical_url(value))}")
    return {value for value in result if value}


def _identity(item: dict, index: int) -> str:
    keys = sorted(_keys(item))
    if keys:
        return keys[0]
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    return f"invalid:{index}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _external_evidence(item: dict, posted: dict, keys: set[str]) -> dict:
    evidence = item.get("facebook_evidence")
    if isinstance(evidence, dict) and evidence.get("external_id"):
        return {
            "external_id": str(evidence.get("external_id")),
            "public_url": str(evidence.get("public_url") or ""),
            "source": "social_queue_evidence",
        }
    for key in keys:
        record = posted.get(key)
        if isinstance(record, dict) and record.get("external_id"):
            return {
                "external_id": str(record.get("external_id")),
                "public_url": str(record.get("public_url") or ""),
                "source": "fb_posted",
            }
    return {}


def _meta_verify(
    external_id: str,
    values: Mapping[str, str],
    *,
    http_get: Callable,
) -> tuple[str, dict]:
    token = str(values.get("FB_PAGE_ACCESS_TOKEN") or "").strip()
    if not token or token == "PENDIENTE":
        return "blocked", {"reason": "missing_token"}
    graph = str(values.get("META_GRAPH_API") or "https://graph.facebook.com/v19.0").rstrip("/")
    try:
        response = http_get(
            f"{graph}/{external_id}",
            params={"fields": "id,permalink_url,created_time", "access_token": token},
            timeout=int(values.get("FB_REQUEST_TIMEOUT_SECONDS", "60")),
        )
    except requests.Timeout:
        return "failed", {"reason": "timeout"}
    except requests.RequestException as exc:
        return "failed", {"reason": type(exc).__name__}
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 200:
        try:
            payload = response.json()
        except ValueError:
            return "failed", {"reason": "non_json_response"}
        if isinstance(payload, dict) and str(payload.get("id") or "") == external_id:
            return "verified", {
                "external_id": external_id,
                "public_url": str(payload.get("permalink_url") or ""),
            }
        return "failed", {"reason": "identity_mismatch"}
    if status in {401, 403, 429}:
        return "blocked", {"reason": f"http_{status}"}
    if status == 404:
        return "not_found", {"reason": "http_404"}
    return "failed", {"reason": f"http_{status}"}


def build_facebook_report(
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
    verify_meta: bool = True,
    http_get: Callable = requests.get,
) -> dict:
    env = os.environ if values is None else values
    queue_path, posted_path = _paths(env)
    queue = load_json(queue_path, [], expected_type=list)
    posted_state = load_json(posted_path, {"posted": {}}, expected_type=dict)
    posted = posted_state.get("posted")
    posted = posted if isinstance(posted, dict) else {}
    current = int(time.time() if now is None else now)
    ttl_hours = max(1, int(env.get("SOCIAL_TTL_HOURS", "48")))
    cutoff = current - ttl_hours * 3600
    seen: set[str] = set()
    items: list[dict] = []
    meta_cache: dict[str, tuple[str, dict]] = {}

    for index, raw in enumerate(queue):
        if not isinstance(raw, dict):
            items.append(
                {
                    "index": index,
                    "item_id": f"invalid:{index}",
                    "classification": "invalid",
                    "reason": "queue_entry_not_object",
                    "evidence": {},
                    "requires_human_decision": True,
                }
            )
            continue
        item = raw
        keys = _keys(item)
        identity = _identity(item, index)
        state = str(item.get("facebook_state") or "").strip().lower()
        reason = str(item.get("facebook_reason") or "").strip()
        evidence = _external_evidence(item, posted, keys)
        web_url = str(item.get("web_url") or item.get("noticia_url") or "").strip()
        queued_at = int(
            item.get("social_queued_at")
            or item.get("queued_at")
            or item.get("facebook_updated_at")
            or 0
        )

        classification = "pending_valid"
        classification_reason = "pending_with_web_url"
        human = False
        if not keys:
            classification = "invalid"
            classification_reason = "missing_stable_identity"
            human = True
        elif identity in seen:
            classification = "duplicate"
            classification_reason = "duplicate_stable_identity_in_queue"
        elif evidence:
            verify_status = "not_requested"
            verify_details = {}
            if verify_meta:
                external_id = evidence["external_id"]
                if external_id not in meta_cache:
                    meta_cache[external_id] = _meta_verify(
                        external_id,
                        env,
                        http_get=http_get,
                    )
                verify_status, verify_details = meta_cache[external_id]
                evidence["meta_verification"] = verify_status
                evidence.update(
                    {
                        key: value
                        for key, value in verify_details.items()
                        if key in {"public_url"} and value
                    }
                )
            if verify_status == "not_found":
                classification = "ambiguous"
                classification_reason = "local_external_id_not_found_in_meta"
                human = True
            elif verify_status == "failed":
                classification = "ambiguous"
                classification_reason = "meta_verification_failed"
                human = True
            else:
                classification = "already_published"
                classification_reason = (
                    "external_id_verified"
                    if verify_status == "verified"
                    else "external_id_local_evidence_meta_blocked"
                    if verify_status == "blocked"
                    else "external_id_local_evidence"
                )
        elif state == "excluded":
            classification = "duplicate"
            classification_reason = reason or "explicit_excluded_state"
        elif state == "expired" or reason in {"social_ttl_exceeded", "expired"}:
            classification = "expired"
            classification_reason = reason or "explicit_expired_state"
        elif state in {"processing", "completed"} or item.get("facebook_done"):
            classification = "ambiguous"
            classification_reason = "terminal_or_processing_without_external_evidence"
            human = True
        elif state == "dead_letter" and (
            "ambiguous" in reason or "restart" in reason or "unknown" in reason
        ):
            classification = "ambiguous"
            classification_reason = "dead_letter_ambiguous_outcome"
            human = True
        elif state == "dead_letter":
            classification = "ambiguous"
            classification_reason = "dead_letter_requires_explicit_decision"
            human = True
        elif queued_at and queued_at < cutoff:
            classification = "expired"
            classification_reason = "social_ttl_exceeded"
        elif not web_url:
            classification = "blocked_missing_web_url"
            classification_reason = "facebook_requires_public_web_url"
        seen.add(identity)
        items.append(
            {
                "index": index,
                "item_id": identity,
                "classification": classification,
                "reason": classification_reason,
                "title": str(item.get("titulo") or "")[:160],
                "canonical_url": str(item.get("canonical_url") or item.get("url") or ""),
                "web_url": web_url,
                "queued_at": queued_at or None,
                "evidence": evidence,
                "requires_human_decision": human or classification in {"ambiguous", "invalid"},
            }
        )

    stable = [
        {
            "index": item["index"],
            "item_id": item["item_id"],
            "classification": item["classification"],
            "reason": item["reason"],
            "evidence": item["evidence"],
        }
        for item in items
    ]
    report_id = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    counts = Counter(item["classification"] for item in items)
    return {
        "version": 1,
        "report_id": report_id,
        "generated_at": current,
        "report_only": True,
        "modified_queue": False,
        "queue_path": queue_path,
        "posted_path": posted_path,
        "total": len(items),
        "counts": {name: counts.get(name, 0) for name in CLASSIFICATIONS},
        "items": items,
        "meta_verification": {
            "attempted": verify_meta,
            "verified": sum(1 for status, _ in meta_cache.values() if status == "verified"),
            "blocked": sum(1 for status, _ in meta_cache.values() if status == "blocked"),
            "failed": sum(1 for status, _ in meta_cache.values() if status in {"failed", "not_found"}),
        },
    }


_ACTIONS = {
    "keep_pending",
    "mark_expired",
    "mark_duplicate",
    "keep_dead_letter",
    "mark_published",
}


def apply_facebook_decisions(
    decision_path: str | os.PathLike[str],
    values: Mapping[str, str] | None = None,
    *,
    now: float | None = None,
) -> dict:
    env = os.environ if values is None else values
    target = Path(decision_path).expanduser().resolve()
    if not target.is_file() or target.suffix.lower() != ".json":
        raise ValueError("El archivo de decisiones no existe o no es JSON")
    decisions_doc = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(decisions_doc, dict) or not isinstance(decisions_doc.get("decisions"), list):
        raise ValueError("El archivo de decisiones debe incluir una lista decisions")
    current_report = build_facebook_report(env, now=now, verify_meta=False)
    if str(decisions_doc.get("report_id") or "") != current_report["report_id"]:
        raise ValueError("El report_id no coincide con el estado actual; regenerá el reporte")

    report_items = {item["item_id"]: item for item in current_report["items"]}
    approved: dict[str, dict] = {}
    for decision in decisions_doc["decisions"]:
        if not isinstance(decision, dict):
            raise ValueError("Cada decisión debe ser un objeto")
        item_id = str(decision.get("item_id") or "")
        action = str(decision.get("action") or "")
        if item_id not in report_items:
            raise ValueError(f"Decisión fuera del reporte aprobado: {item_id}")
        if action not in _ACTIONS:
            raise ValueError(f"Acción no permitida: {action}")
        if action == "mark_published" and not str(decision.get("external_id") or "").strip():
            raise ValueError("mark_published requiere external_id verificable")
        if item_id in approved:
            raise ValueError(f"Decisión duplicada para {item_id}")
        approved[item_id] = copy.deepcopy(decision)

    queue_path, _ = _paths(env)
    applied: list[dict] = []
    timestamp = int(time.time() if now is None else now)

    def mutate(queue):
        for index, item in enumerate(queue):
            if not isinstance(item, dict):
                continue
            item_id = _identity(item, index)
            decision = approved.get(item_id)
            if not decision:
                continue
            action = decision["action"]
            reason = str(decision.get("reason") or f"facebook_reconcile:{action}")
            if action == "keep_pending":
                item["facebook_state"] = "pending"
                item["facebook_done"] = False
            elif action == "mark_expired":
                item["facebook_state"] = "expired"
                item["facebook_done"] = True
            elif action == "mark_duplicate":
                item["facebook_state"] = "excluded"
                item["facebook_done"] = True
            elif action == "keep_dead_letter":
                item["facebook_state"] = "dead_letter"
                item["facebook_done"] = True
            elif action == "mark_published":
                item["facebook_state"] = "completed"
                item["facebook_done"] = True
                item["facebook_evidence"] = {
                    "external_id": str(decision["external_id"]),
                    "public_url": str(decision.get("public_url") or ""),
                    "source": "operator_approved_reconciliation",
                }
            item["facebook_reason"] = reason
            item["facebook_updated_at"] = timestamp
            applied.append(
                {
                    "item_id": item_id,
                    "action": action,
                    "reason": reason,
                    "external_id": str(decision.get("external_id") or ""),
                }
            )
        return queue

    update_json(queue_path, mutate, [], expected_type=list)
    for item in applied:
        record_queue_event(
            stage="facebook_reconciliation",
            status="completed",
            reason=item["action"],
            item={"item_id": item["item_id"]},
            metadata={
                "report_id": current_report["report_id"],
                "operator_reason": item["reason"],
                "external_id": item["external_id"],
            },
        )
    return {
        "status": "success",
        "report_id": current_report["report_id"],
        "approved": len(approved),
        "applied": len(applied),
        "unchanged": current_report["total"] - len(applied),
        "items": applied,
    }
