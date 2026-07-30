"""Cola durable genérica con Pending/Processing/Completed/Failed/Expired/Dead-letter."""
from __future__ import annotations

import copy
import hashlib
import os
import time
from typing import Any, Callable

from utils.file_manager import (
    MultiFileLock,
    _load_json_unlocked,
    _save_json_unlocked,
    load_json,
    update_json,
)
from utils.url_normalization import canonical_url


def durable_item_id(payload: dict) -> str:
    for field in ("web_queue_key", "meta_queue_key", "dedup_key"):
        value = str(payload.get(field) or "").strip()
        if value:
            return value
    url = str(payload.get("canonical_url") or payload.get("url") or "").strip()
    if url:
        basis = canonical_url(url)
    else:
        basis = "|".join(
            str(payload.get(field) or "")
            for field in ("titulo_original", "titulo", "fecha", "source")
        )
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()


class DurableQueue:
    VERSION = 1
    BUCKETS = ("pending", "processing", "completed", "failed", "expired", "dead_letter")

    def __init__(
        self,
        path: str,
        name: str,
        *,
        max_attempts: int = 3,
        clock: Callable[[], float] = time.time,
    ):
        self.path = os.path.abspath(path)
        self.name = name
        self.max_attempts = max(1, int(max_attempts))
        self.clock = clock

    def _empty_state(self) -> dict:
        return {
            "version": self.VERSION,
            "name": self.name,
            **{bucket: [] for bucket in self.BUCKETS},
        }

    def _validate(self, state: Any) -> dict:
        if not isinstance(state, dict):
            raise ValueError(f"Estado durable inválido para {self.name}: se esperaba objeto")
        state.setdefault("version", self.VERSION)
        state.setdefault("name", self.name)
        for bucket in self.BUCKETS:
            value = state.setdefault(bucket, [])
            if not isinstance(value, list):
                raise ValueError(f"Estado durable inválido: {bucket} debe ser lista")
        return state

    def _known_ids(self, state: dict) -> set[str]:
        return {
            str(item.get("id"))
            for bucket in self.BUCKETS
            for item in state[bucket]
            if isinstance(item, dict) and item.get("id")
        }

    def _envelope(self, payload: dict, source: str) -> dict:
        now = int(self.clock())
        return {
            "id": durable_item_id(payload),
            "status": "pending",
            "payload": copy.deepcopy(payload),
            "source": source,
            "attempts": 0,
            "created_at": now,
            "updated_at": now,
        }

    def transfer_from_legacy(self, source_path: str) -> int:
        """Persiste primero en la cola durable y sólo después vacía staging.

        Si el proceso cae entre ambas escrituras, el siguiente intento detecta los IDs
        ya transferidos y puede vaciar staging sin duplicar.
        """
        source_path = os.path.abspath(source_path)
        with MultiFileLock((self.path, source_path)):
            source = _load_json_unlocked(source_path, [], expected_type=list)
            state = self._validate(_load_json_unlocked(self.path, self._empty_state(), expected_type=dict))
            known = self._known_ids(state)
            transferred = 0
            for payload in source:
                if not isinstance(payload, dict):
                    continue
                envelope = self._envelope(payload, os.path.basename(source_path))
                if envelope["id"] in known:
                    continue
                state["pending"].append(envelope)
                known.add(envelope["id"])
                transferred += 1

            # Orden deliberado: durable primero, staging después.
            _save_json_unlocked(self.path, state)
            if source:
                _save_json_unlocked(source_path, [])
            return transferred

    def snapshot(self) -> dict:
        return self._validate(load_json(self.path, self._empty_state(), expected_type=dict))

    def claim_one(self) -> dict | None:
        claimed: dict | None = None

        def claim(state):
            nonlocal claimed
            state = self._validate(state)
            if not state["pending"]:
                return state
            job = state["pending"].pop(0)
            job["status"] = "processing"
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job["claimed_at"] = int(self.clock())
            job["updated_at"] = int(self.clock())
            state["processing"].append(job)
            claimed = copy.deepcopy(job)
            return state

        update_json(self.path, claim, self._empty_state(), expected_type=dict)
        return claimed

    def _pop_processing(self, state: dict, item_id: str) -> dict | None:
        for index, item in enumerate(state["processing"]):
            if str(item.get("id")) == str(item_id):
                return state["processing"].pop(index)
        return None

    def complete(self, item_id: str, metadata: dict | None = None) -> bool:
        changed = False

        def complete_job(state):
            nonlocal changed
            state = self._validate(state)
            if any(str(item.get("id")) == str(item_id) for item in state["completed"]):
                return state
            job = self._pop_processing(state, item_id)
            if not job:
                return state
            job["status"] = "completed"
            job["completed_at"] = int(self.clock())
            job["updated_at"] = int(self.clock())
            if metadata:
                job["result"] = copy.deepcopy(metadata)
            state["completed"].append(job)
            changed = True
            return state

        update_json(self.path, complete_job, self._empty_state(), expected_type=dict)
        return changed

    def fail(self, item_id: str, error: str, *, retryable: bool) -> str:
        destination = "missing"

        def fail_job(state):
            nonlocal destination
            state = self._validate(state)
            job = self._pop_processing(state, item_id)
            if not job:
                return state
            now = int(self.clock())
            job["last_error"] = str(error)
            job["failed_at"] = now
            job["updated_at"] = now
            state["failed"].append(copy.deepcopy({**job, "status": "failed"}))
            if retryable and int(job.get("attempts") or 0) < self.max_attempts:
                job["status"] = "pending"
                state["pending"].append(job)
                destination = "pending"
            else:
                job["status"] = "dead_letter"
                job["dead_letter_at"] = now
                state["dead_letter"].append(job)
                destination = "dead_letter"
            return state

        update_json(self.path, fail_job, self._empty_state(), expected_type=dict)
        return destination

    def expire(self, item_id: str, reason: str) -> bool:
        changed = False

        def expire_job(state):
            nonlocal changed
            state = self._validate(state)
            job = None
            for bucket in ("pending", "processing"):
                for index, candidate in enumerate(state[bucket]):
                    if str(candidate.get("id")) == str(item_id):
                        job = state[bucket].pop(index)
                        break
                if job:
                    break
            if not job:
                return state
            job.update(
                status="expired",
                last_error=str(reason),
                expired_at=int(self.clock()),
                updated_at=int(self.clock()),
            )
            state["expired"].append(job)
            changed = True
            return state

        update_json(self.path, expire_job, self._empty_state(), expected_type=dict)
        return changed

    def dead_letter(self, item_id: str, reason: str) -> bool:
        changed = False

        def move(state):
            nonlocal changed
            state = self._validate(state)
            job = None
            for bucket in ("pending", "processing"):
                for index, candidate in enumerate(state[bucket]):
                    if str(candidate.get("id")) == str(item_id):
                        job = state[bucket].pop(index)
                        break
                if job:
                    break
            if not job:
                return state
            job.update(
                status="dead_letter",
                last_error=str(reason),
                dead_letter_at=int(self.clock()),
                updated_at=int(self.clock()),
            )
            state["dead_letter"].append(job)
            changed = True
            return state

        update_json(self.path, move, self._empty_state(), expected_type=dict)
        return changed

    def recover_processing(self) -> int:
        recovered = 0

        def recover(state):
            nonlocal recovered
            state = self._validate(state)
            jobs = list(state["processing"])
            state["processing"] = []
            now = int(self.clock())
            for job in jobs:
                job["status"] = "pending"
                job["recovered_at"] = now
                job["updated_at"] = now
                state["pending"].append(job)
                recovered += 1
            return state

        update_json(self.path, recover, self._empty_state(), expected_type=dict)
        return recovered
