"""Harness local determinista: no importa .env ni ejecuta integraciones reales."""
from __future__ import annotations

import copy
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from utils.durable_queue import DurableQueue, durable_item_id
from utils.file_manager import JsonStateError, load_json, save_json
from utils.news_dedup import duplicate_reason
from utils.stage_result import StageResult, StageStatus, result_from_counts


@dataclass
class LocalScenario:
    name: str
    news: list[dict] = field(default_factory=list)
    openai: str = "ok"
    allow_fallback: bool = True
    image: str = "ok"
    r2: str = "ok"
    cms: int = 201
    facebook: str = "ok"
    instagram: str = "ok"
    interrupt_after_claim: bool = False
    concurrent_publishers: bool = False
    corrupt_state: bool = False
    expire: bool = False
    breaking: bool = False
    manual_dry_run: bool = False


@dataclass
class LocalEvidence:
    result: StageResult
    state: dict
    events: list[dict]
    social_pending: list[dict]
    external_calls: dict[str, int]
    root: str


def fixture_news(*, suffix: str = "uno", source: str = "fixture") -> dict:
    return {
        "titulo": f"Municipio confirma una obra vial en Aimogasta {suffix}",
        "titulo_original": f"Municipio confirma una obra vial en Aimogasta {suffix}",
        "parrafos": [
            "El municipio confirmó el inicio de trabajos viales en Aimogasta.",
            "La información fue incluida en el parte oficial usado como fixture local.",
        ],
        "url": f"https://fuente.example/{source}/{suffix}",
        "canonical_url": f"https://fuente.example/{source}/{suffix}",
        "source": source,
        "seccion": "interior",
        "imagen_url": f"https://media.example/{suffix}.jpg",
        "fecha": "2026-07-23",
    }


class LocalPipelineHarness:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.staging = self.root / "captured.json"
        self.state_path = self.root / "pipeline_state.json"
        self.events_path = self.root / "events.json"
        self.social_path = self.root / "social_pending.json"
        self.result_path = self.root / "result.json"

    def close(self):
        self._temp.cleanup()

    def _event(self, status: str, reason: str, item: dict | None = None):
        events = load_json(str(self.events_path), [], expected_type=list)
        events.append(
            {
                "status": status,
                "reason": reason,
                "item_id": durable_item_id(item or {}) if item else "",
            }
        )
        save_json(str(self.events_path), events)

    def _seed_unique(self, news: list[dict]) -> tuple[list[dict], int]:
        unique: list[dict] = []
        duplicates = 0
        for item in news:
            if duplicate_reason(
                item,
                unique,
                key_fields=("canonical_url", "url"),
            ):
                duplicates += 1
                self._event("completed", "duplicate_cross_source", item)
            else:
                unique.append(copy.deepcopy(item))
        save_json(str(self.staging), unique)
        return unique, duplicates

    def run(self, scenario: LocalScenario) -> LocalEvidence:
        calls = {"openai": 0, "r2": 0, "cms": 0, "facebook": 0, "instagram": 0}
        social_pending: list[dict] = []
        started = time.monotonic()

        if scenario.manual_dry_run:
            result = StageResult(
                "e2e_local",
                StageStatus.SUCCESS,
                received=1,
                selected=1,
                processed=1,
                succeeded=1,
                duration_seconds=time.monotonic() - started,
                details={"dry_run": True},
            )
            state = {"pending": [], "processing": [], "completed": [{"id": "manual-dry-run"}], "failed": [], "expired": [], "dead_letter": []}
            return self._persist(result, state, [], calls)

        news, duplicates = self._seed_unique(scenario.news)
        queue = DurableQueue(str(self.state_path), "e2e", max_attempts=2)
        if scenario.corrupt_state:
            self.state_path.write_text('{"pending": [', encoding="utf-8")
            try:
                queue.snapshot()
            except JsonStateError as exc:
                self._event("failed", "json_corrupt")
                result = StageResult(
                    "e2e_local",
                    StageStatus.FAILED,
                    received=len(news),
                    failed=1,
                    error_type="state_corrupt",
                    details={"error_class": type(exc).__name__},
                )
                return self._persist(result, {}, [], calls)

        transferred = queue.transfer_from_legacy(str(self.staging))
        if not news:
            result = StageResult(
                "e2e_local",
                StageStatus.NO_WORK,
                details={"duplicates": duplicates},
            )
            return self._persist(result, queue.snapshot(), [], calls)

        if scenario.interrupt_after_claim:
            interrupted = queue.claim_one()
            self._event("degraded", "simulated_interruption", interrupted["payload"])
            queue = DurableQueue(str(self.state_path), "e2e", max_attempts=2)
            queue.recover_processing()

        claimed: list[dict] = []
        if scenario.concurrent_publishers:
            barrier = threading.Barrier(2)
            lock = threading.Lock()

            def worker():
                barrier.wait()
                job = queue.claim_one()
                if job:
                    with lock:
                        claimed.append(job)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        else:
            while True:
                job = queue.claim_one()
                if not job:
                    break
                claimed.append(job)

        succeeded = failed = expired = 0
        degraded_reason = None
        for job in claimed:
            item = job["payload"]
            item_id = job["id"]
            if scenario.expire:
                queue.expire(item_id, "article_ttl_exceeded")
                self._event("expired", "article_ttl_exceeded", item)
                expired += 1
                continue

            calls["openai"] += 1
            fallback_used = scenario.openai != "ok"
            if fallback_used and not scenario.allow_fallback:
                queue.dead_letter(item_id, "openai_fallback_blocked")
                self._event("dead_letter", "openai_fallback_blocked", item)
                failed += 1
                continue
            if fallback_used:
                degraded_reason = "fallback_used"
                self._event("degraded", "openai_fallback_used", item)

            if scenario.image == "missing":
                queue.dead_letter(item_id, "missing_image")
                self._event("dead_letter", "missing_image", item)
                failed += 1
                continue

            calls["r2"] += 1
            if scenario.r2 != "ok":
                queue.fail(item_id, "r2_unavailable", retryable=True)
                self._event("degraded", "r2_unavailable", item)
                degraded_reason = "r2_unavailable"
                failed += 1
                continue

            calls["cms"] += 1
            if scenario.cms == 401:
                queue.fail(item_id, "cms_invalid_credential", retryable=False)
                self._event("failed", "cms_invalid_credential", item)
                failed += 1
                continue
            if scenario.cms == 429:
                queue.fail(item_id, "cms_rate_limit", retryable=True)
                self._event("degraded", "cms_rate_limit", item)
                degraded_reason = "cms_rate_limit"
                failed += 1
                continue
            if scenario.cms not in {200, 201, 409}:
                queue.fail(item_id, f"cms_http_{scenario.cms}", retryable=True)
                self._event("degraded", f"cms_http_{scenario.cms}", item)
                failed += 1
                continue

            web_id = f"web-{item_id[:10]}"
            web_url = f"https://cms.local/noticias/{item_id[:10]}"
            calls["facebook"] += 1
            calls["instagram"] += 1
            channels = {
                "web": {"status": "success", "id": web_id, "url": web_url},
                "facebook": {"status": scenario.facebook},
                "instagram": {"status": scenario.instagram},
            }
            if scenario.breaking:
                channels["editorial"] = {"breaking": True, "strict": True}
            if scenario.facebook != "ok":
                social_pending.append({"id": item_id, "platform": "facebook"})
                self._event("degraded", "facebook_failed", item)
                degraded_reason = "partial_social_publish"
            if scenario.instagram == "rate_limit":
                social_pending.append({"id": item_id, "platform": "instagram"})
                self._event("degraded", "instagram_rate_limit", item)
                degraded_reason = "rate_limit"
            elif scenario.instagram != "ok":
                social_pending.append({"id": item_id, "platform": "instagram"})
                self._event("degraded", "instagram_failed", item)
                degraded_reason = "partial_social_publish"
            queue.complete(
                item_id,
                {
                    "channels": channels,
                    "fallback_used": fallback_used,
                    "exactly_once_key": item_id,
                },
            )
            succeeded += 1

        state = queue.snapshot()
        save_json(str(self.social_path), social_pending)
        result = result_from_counts(
            "e2e_local",
            received=len(scenario.news),
            selected=len(claimed),
            processed=len(claimed),
            succeeded=succeeded,
            failed=failed,
            expired=expired,
            duration_seconds=time.monotonic() - started,
            error_type=degraded_reason,
            details={
                "transferred": transferred,
                "duplicates": duplicates,
                "social_pending": len(social_pending),
            },
        )
        if degraded_reason and result.status == StageStatus.SUCCESS:
            result.status = StageStatus.DEGRADED
            result.error_type = degraded_reason
        if degraded_reason in {"cms_rate_limit", "rate_limit", "r2_unavailable"}:
            result.status = StageStatus.DEGRADED
            result.error_type = degraded_reason
        events = load_json(str(self.events_path), [], expected_type=list)
        return self._persist(result, state, social_pending, calls, events=events)

    def _persist(
        self,
        result: StageResult,
        state: dict,
        social_pending: list[dict],
        calls: dict[str, int],
        *,
        events: list[dict] | None = None,
    ) -> LocalEvidence:
        events = events if events is not None else load_json(str(self.events_path), [], expected_type=list)
        save_json(str(self.result_path), result.to_dict())
        if not self.social_path.exists():
            save_json(str(self.social_path), social_pending)
        return LocalEvidence(
            result=result,
            state=state,
            events=events,
            social_pending=social_pending,
            external_calls=calls,
            root=str(self.root),
        )
