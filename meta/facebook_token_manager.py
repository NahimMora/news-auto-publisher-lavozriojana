"""
Gestiona el token de acceso a la página de Facebook.
El .env guarda un USER token (long-lived) o directamente el PAGE token de
FB_PAGE_ID. Un user token se intercambia por el page token via /me/accounts;
un page token se usa tal cual. El resultado se cachea en disco junto con la
huella del token de origen, así rotar el .env invalida la cache sola.
"""
import hashlib
import os
import time
import requests
from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("fb_token_manager", "facebook_token_manager.log")

TOKEN_CACHE = str(data_dir() / "fb_token_cache.json")
GRAPH_API = os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0").rstrip("/")

APP_ID     = os.getenv("FB_APP_ID", "")
APP_SECRET = os.getenv("FB_APP_SECRET", "")
PAGE_ID    = os.getenv("FB_PAGE_ID", "")
USER_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")  # puede ser user o page token


def get_page_token() -> str:
    """
    Retorna el Page Access Token para PAGE_ID.
    1. Busca en cache (fb_token_cache.json)
    2. Si no hay, llama /me/accounts para obtenerlo del user token
    3. Cachea el resultado
    """
    if not USER_TOKEN or USER_TOKEN == "PENDIENTE":
        raise ValueError("FB_PAGE_ACCESS_TOKEN no configurado en .env")
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        raise ValueError("FB_PAGE_ID no configurado en .env")

    source_fingerprint = _fingerprint(USER_TOKEN)

    # 1. Intentar cache (sólo si se derivó del token configurado hoy en .env)
    cache = load_json(TOKEN_CACHE, {})
    cached_token = cache.get("page_token")
    cached_page  = cache.get("page_id")
    if (
        cached_token
        and cached_page == PAGE_ID
        and cache.get("source_fingerprint") == source_fingerprint
    ):
        logger.debug("Usando page token cacheado")
        return cached_token

    try:
        # 2. Si el token del .env ya es el page token de PAGE_ID, usarlo directo
        me = requests.get(
            f"{GRAPH_API}/me",
            params={"access_token": USER_TOKEN, "fields": "id,name"},
            timeout=15,
        ).json()
        if "error" in me:
            err = me["error"]
            raise ValueError(f"Error Meta API [{err.get('code')}]: {err.get('message')}")
        if str(me.get("id")) == str(PAGE_ID):
            logger.info(f"El token configurado es el page token de: {me.get('name')} ({PAGE_ID})")
            _save_cache(USER_TOKEN, me.get("name", ""), source_fingerprint)
            return USER_TOKEN

        # 3. Obtener page token via /me/accounts
        logger.info("Obteniendo page token via /me/accounts...")
        r = requests.get(
            f"{GRAPH_API}/me/accounts",
            params={"access_token": USER_TOKEN, "fields": "id,name,access_token"},
            timeout=15,
        )
        data = r.json()

        if "error" in data:
            err = data["error"]
            raise ValueError(f"Error Meta API [{err.get('code')}]: {err.get('message')}")

        pages = data.get("data", [])
        for page in pages:
            if str(page.get("id")) == str(PAGE_ID):
                page_token = page.get("access_token")
                if not page_token:
                    raise ValueError(f"Página {PAGE_ID} encontrada pero sin access_token")
                logger.info(f"Page token obtenido para: {page.get('name')} ({PAGE_ID})")
                _save_cache(page_token, page.get("name", ""), source_fingerprint)
                return page_token

        raise ValueError(
            f"Página {PAGE_ID} no encontrada en /me/accounts. "
            f"Páginas disponibles: {[p.get('id') for p in pages]}"
        )

    except ValueError:
        raise
    except Exception as e:
        if str(os.getenv("FB_ALLOW_DIRECT_TOKEN_FALLBACK", "false")).lower() in {
            "1", "true", "yes", "si", "sí",
        }:
            logger.warning(
                "No se pudo obtener page token (%s); fallback directo habilitado explícitamente",
                type(e).__name__,
            )
            return USER_TOKEN
        raise ValueError(
            f"No se pudo obtener page token: {type(e).__name__}. "
            "El fallback directo está deshabilitado."
        ) from e


def _fingerprint(token: str) -> str:
    """Huella SHA-256 del token de origen, para detectar una rotación del .env."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _save_cache(page_token: str, page_name: str, source_fingerprint: str) -> None:
    def update_cache(current):
        current.update(
            {
                "page_token": page_token,
                "page_id": PAGE_ID,
                "page_name": page_name,
                "source_fingerprint": source_fingerprint,
                "updated_at": int(time.time()),
            }
        )
        return current

    update_json(TOKEN_CACHE, update_cache, {}, expected_type=dict)


def invalidate_cache():
    """Fuerza re-fetch del page token en la próxima llamada."""
    try:
        os.remove(TOKEN_CACHE)
        logger.info("Cache de token FB invalidada")
    except FileNotFoundError:
        pass


def verify_token(token: str) -> bool:
    """Verifica que el token sea válido contra la Graph API."""
    try:
        r = requests.get(
            f"{GRAPH_API}/me",
            params={"access_token": token, "fields": "id,name"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Error verificando token FB: {e}")
        return False
