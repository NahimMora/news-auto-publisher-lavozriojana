"""Validación de URLs públicas para evitar SSRF en entradas controladas por usuarios."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


class UnsafeURLError(ValueError):
    pass


def validate_public_http_url(
    value: object,
    *,
    resolver=None,
    resolve: bool = True,
) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise UnsafeURLError("URL vacía")

    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError(f"URL inválida: {exc}") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURLError("Sólo se permiten URLs http/https")
    if not parsed.hostname:
        raise UnsafeURLError("La URL no tiene host")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("No se permiten credenciales embebidas en URLs")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeURLError("No se permiten hosts locales")

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        addresses.add(ipaddress.ip_address(host))
    except ValueError:
        if resolve:
            try:
                resolver = resolver or socket.getaddrinfo
                for result in resolver(host, port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM):
                    addresses.add(ipaddress.ip_address(result[4][0]))
            except (OSError, ValueError) as exc:
                raise UnsafeURLError(f"No se pudo resolver el host público: {host}") from exc

    if not addresses and resolve:
        raise UnsafeURLError(f"El host no resolvió direcciones: {host}")
    for address in addresses:
        if not address.is_global:
            raise UnsafeURLError(f"Dirección no pública rechazada: {address}")

    normalized_netloc = host
    if ":" in host and not host.startswith("["):
        normalized_netloc = f"[{host}]"
    if port:
        normalized_netloc = f"{normalized_netloc}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            normalized_netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def safe_request(
    method: str,
    url: str,
    *,
    requester=None,
    max_redirects: int = 4,
    resolver=None,
    **kwargs,
):
    """Hace una solicitud y revalida cada redirect para bloquear pivotes SSRF."""
    verb = str(method or "GET").upper()
    current = validate_public_http_url(url, resolver=resolver)
    kwargs.pop("allow_redirects", None)
    if requester is None:
        requester = requests.request

    for redirect_count in range(max_redirects + 1):
        if requester is requests.request:
            response = requester(verb, current, allow_redirects=False, **kwargs)
        else:
            response = requester(current, allow_redirects=False, **kwargs)
        status = int(getattr(response, "status_code", 0) or 0)
        if status not in {301, 302, 303, 307, 308}:
            return response
        location = str(getattr(response, "headers", {}).get("Location") or "").strip()
        try:
            response.close()
        except (AttributeError, TypeError):
            pass
        if not location:
            raise UnsafeURLError("Redirect sin encabezado Location")
        if redirect_count >= max_redirects:
            raise UnsafeURLError("Demasiados redirects")
        current = validate_public_http_url(urljoin(current, location), resolver=resolver)
    raise UnsafeURLError("Demasiados redirects")


def safe_get(url: str, **kwargs):
    requester = kwargs.pop("requester", requests.get)
    return safe_request("GET", url, requester=requester, **kwargs)


def safe_head(url: str, **kwargs):
    requester = kwargs.pop("requester", requests.head)
    return safe_request("HEAD", url, requester=requester, **kwargs)
