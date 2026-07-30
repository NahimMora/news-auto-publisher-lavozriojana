"""Resultados tipados de acceso/parsing para distinguir vacío sano de fuente caída."""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from utils.stage_result import StageStatus


@dataclass
class LinkScrapeResult:
    status: StageStatus
    links: list[str] = field(default_factory=list)
    error_type: str | None = None
    http_status: int | None = None
    message: str | None = None


@dataclass
class ArticleScrapeResult:
    status: StageStatus
    article: dict | None = None
    error_type: str | None = None
    http_status: int | None = None
    message: str | None = None
    warnings: list[str] = field(default_factory=list)


def request_error_details(exc: Exception) -> tuple[str, int | None]:
    if isinstance(exc, requests.Timeout):
        return "timeout", None
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return "http_error", getattr(response, "status_code", None)
    if isinstance(exc, requests.RequestException):
        return "network_error", None
    return "unexpected_error", None
