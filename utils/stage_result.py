"""Contrato uniforme y serializable para el resultado funcional de cada etapa."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


RESULT_PREFIX = "LVR_STAGE_RESULT="


class StageStatus(str, Enum):
    SUCCESS = "success"
    NO_WORK = "no_work"
    DEGRADED = "degraded"
    FAILED = "failed"
    BLOCKED = "blocked"


_EXIT_CODES = {
    StageStatus.SUCCESS: 0,
    StageStatus.NO_WORK: 0,
    StageStatus.DEGRADED: 2,
    StageStatus.FAILED: 1,
    StageStatus.BLOCKED: 3,
}


@dataclass
class StageResult:
    stage: str
    status: StageStatus
    received: int = 0
    selected: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    deferred: int = 0
    expired: int = 0
    duration_seconds: float = 0.0
    error_type: str | None = None
    error_code: str | int | None = None
    next_retry_at: str | int | float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, StageStatus):
            self.status = StageStatus(str(self.status))
        for name in (
            "received",
            "selected",
            "processed",
            "succeeded",
            "failed",
            "deferred",
            "expired",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} no puede ser negativo")
            setattr(self, name, value)
        self.duration_seconds = max(0.0, round(float(self.duration_seconds), 6))

        # Invariante central: 0/N con N > 0 nunca puede ser éxito completo.
        if (
            self.status == StageStatus.SUCCESS
            and self.selected > 0
            and self.succeeded == 0
        ):
            raise ValueError("0/N con N > 0 no puede tener status=success")

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.status]

    @property
    def acceptable(self) -> bool:
        return self.status in {StageStatus.SUCCESS, StageStatus.NO_WORK}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["exit_code"] = self.exit_code
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StageResult":
        values = dict(payload)
        values.pop("exit_code", None)
        values["status"] = StageStatus(values["status"])
        return cls(**values)


def result_from_counts(
    stage: str,
    *,
    received: int = 0,
    selected: int = 0,
    processed: int = 0,
    succeeded: int = 0,
    failed: int = 0,
    deferred: int = 0,
    expired: int = 0,
    duration_seconds: float = 0.0,
    error_type: str | None = None,
    error_code: str | int | None = None,
    next_retry_at: str | int | float | None = None,
    details: dict[str, Any] | None = None,
) -> StageResult:
    received = int(received)
    selected = int(selected)
    processed = int(processed)
    succeeded = int(succeeded)
    failed = int(failed)

    if selected == 0 and processed == 0 and failed == 0:
        status = StageStatus.NO_WORK
    elif failed > 0 and succeeded == 0:
        status = StageStatus.FAILED
    elif error_type and succeeded == 0:
        status = StageStatus.FAILED
    elif failed > 0 or (processed > succeeded) or (selected > 0 and processed == 0):
        status = StageStatus.DEGRADED
    elif selected > 0 and succeeded == 0:
        status = StageStatus.DEGRADED
    else:
        status = StageStatus.SUCCESS

    return StageResult(
        stage=stage,
        status=status,
        received=received,
        selected=selected,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred,
        expired=expired,
        duration_seconds=duration_seconds,
        error_type=error_type,
        error_code=error_code,
        next_retry_at=next_retry_at,
        details=details or {},
    )


def aggregate_results(stage: str, results: Iterable[StageResult], *, duration_seconds: float = 0.0) -> StageResult:
    children = list(results)
    if not children:
        return result_from_counts(stage, duration_seconds=duration_seconds)

    statuses = {child.status for child in children}
    if statuses <= {StageStatus.NO_WORK}:
        status = StageStatus.NO_WORK
    elif StageStatus.FAILED in statuses:
        status = StageStatus.DEGRADED if any(child.acceptable for child in children) else StageStatus.FAILED
    elif StageStatus.DEGRADED in statuses:
        status = StageStatus.DEGRADED
    elif StageStatus.BLOCKED in statuses:
        status = StageStatus.BLOCKED
    elif StageStatus.SUCCESS in statuses:
        status = StageStatus.SUCCESS
    else:
        status = StageStatus.NO_WORK

    return StageResult(
        stage=stage,
        status=status,
        received=sum(item.received for item in children),
        selected=sum(item.selected for item in children),
        processed=sum(item.processed for item in children),
        succeeded=sum(item.succeeded for item in children),
        failed=sum(item.failed for item in children),
        deferred=sum(item.deferred for item in children),
        expired=sum(item.expired for item in children),
        duration_seconds=duration_seconds,
        error_type="child_stage_failed" if StageStatus.FAILED in statuses else None,
        details={"children": [item.to_dict() for item in children]},
    )


def emit_stage_result(result: StageResult, *, stream=None) -> int:
    """Emite JSON por stdout y, si corresponde, al archivo pedido por el padre."""
    payload = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
    target_stream = stream or sys.stdout
    target_stream.write(f"{RESULT_PREFIX}{payload}\n")
    target_stream.flush()

    result_path = str(os.getenv("LVR_STAGE_RESULT_PATH") or "").strip()
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
    return result.exit_code


def read_stage_result(path: str | os.PathLike[str]) -> StageResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return StageResult.from_dict(payload)


def parse_stage_result_output(output: str) -> StageResult | None:
    for line in reversed(str(output or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            return StageResult.from_dict(json.loads(line[len(RESULT_PREFIX) :]))
    return None
