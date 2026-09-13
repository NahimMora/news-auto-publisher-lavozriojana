"""Cliente HTTP eficiente y respetuoso para fuentes oficiales (Parte 23/58).

Envuelve ``utils/safe_http.py`` (SSRF ya bloqueado ahí) agregando lo que ese
módulo no hace: sesión reutilizable, allowlist de hosts por fuente,
User-Agent identificable, ETag/If-Modified-Since.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from sources.registry import SourceDefinition
from utils.safe_http import UnsafeURLError, safe_get
from utils.logging_setup import setup_logger

logger = setup_logger("sources.http_client", "official_sources.log")

USER_AGENT = "LaVozRiojanaBot/1.0 (+https://lavozriojana.com.ar; contexto-editorial)"
DEFAULT_TIMEOUT = 15.0

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})


class SourceFetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    status_code: int
    text: str
    headers: dict
    latency_ms: float
    not_modified: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 or self.not_modified


def _host_checked_get(allowed_hosts: tuple[str, ...]):
    def _get(url: str, **kwargs):
        host = (urlsplit(url).hostname or "").lower()
        if allowed_hosts and host not in {h.lower() for h in allowed_hosts}:
            raise UnsafeURLError(f"Host no permitido para esta fuente: {host}")
        return _SESSION.get(url, **kwargs)

    return _get


def fetch(
    source: SourceDefinition,
    *,
    url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    resolver=None,
) -> FetchResult:
    """GET respetuoso: allowlist de host, condicional (304) si hay etag/last_modified.

    Nunca vuelve a descargar un artículo inmutable si el caller pasa el
    ``etag``/``last_modified`` guardado (Parte 23). ``resolver`` es sólo para
    tests (mismo patrón que ``utils/safe_http.py``, nunca requiere red real).
    """
    target_url = url or source.url
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    started = time.perf_counter()
    try:
        response = safe_get(
            target_url,
            requester=_host_checked_get(source.allowed_hosts),
            headers=headers,
            timeout=timeout,
            resolver=resolver,
        )
    except UnsafeURLError as exc:
        raise SourceFetchError(str(exc)) from exc
    except requests.RequestException as exc:
        raise SourceFetchError(f"error de red: {exc}") from exc
    latency_ms = (time.perf_counter() - started) * 1000.0

    if response.status_code == 304:
        return FetchResult(
            url=target_url,
            status_code=304,
            text="",
            headers=dict(response.headers),
            latency_ms=latency_ms,
            not_modified=True,
        )

    return FetchResult(
        url=target_url,
        status_code=response.status_code,
        text=response.text if response.status_code < 400 else "",
        headers=dict(response.headers),
        latency_ms=latency_ms,
    )
