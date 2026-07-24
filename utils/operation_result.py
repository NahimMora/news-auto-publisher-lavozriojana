"""Resultado tipado para una operación individual contra una integración externa."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.stage_result import StageStatus


@dataclass
class OperationResult:
    status: StageStatus
    error_type: str | None = None
    error_code: str | int | None = None
    retryable: bool = False
    next_retry_at: float | int | str | None = None
    external_id: str = ""
    public_url: str = ""
    response: dict[str, Any] | None = None
    deduplicated: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, StageStatus):
            self.status = StageStatus(str(self.status))

    @property
    def ok(self) -> bool:
        return self.status == StageStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "ok": self.ok,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "next_retry_at": self.next_retry_at,
            "external_id": self.external_id,
            "public_url": self.public_url,
            "deduplicated": self.deduplicated,
            "details": self.details,
        }
