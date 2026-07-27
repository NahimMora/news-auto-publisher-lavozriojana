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

    def failure_metadata(self) -> dict[str, Any]:
        """Devuelve diagnóstico persistible sin copiar cuerpos externos arbitrarios."""
        metadata: dict[str, Any] = {
            "error_type": self.error_type,
            "http_status": self.error_code,
            "retryable": self.retryable,
        }
        outcome = self.details.get("publication_outcome")
        if outcome:
            metadata["publication_outcome"] = str(outcome)[:80]
        if self.next_retry_at is not None:
            metadata["next_retry_at"] = self.next_retry_at

        response = self.response if isinstance(self.response, dict) else {}
        provider_error = response.get("error")
        if not isinstance(provider_error, dict):
            provider_error = {}
        for source, target in (
            ("code", "provider_code"),
            ("error_subcode", "provider_subcode"),
            ("type", "provider_type"),
        ):
            value = provider_error.get(source)
            if value is not None and str(value).strip():
                metadata[target] = str(value)[:120] if isinstance(value, str) else value
        return {key: value for key, value in metadata.items() if value is not None}
