import hashlib
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    # Normalizar scheme y host a minúsculas
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Eliminar fragmento, ordenar query params
    params_sorted = urlencode(sorted(parse_qsl(parsed.query)))
    normalized = urlunparse((scheme, netloc, parsed.path, "", params_sorted, ""))
    return normalized.rstrip("/")


def url_hash(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()
