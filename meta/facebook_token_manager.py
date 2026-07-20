"""
Gestiona el token de acceso a la página de Facebook.
El .env guarda el USER token (long-lived). Este módulo lo intercambia
automáticamente por el PAGE token via /me/accounts y lo cachea en disco.
"""
import os
import time
import requests
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger

logger = setup_logger("fb_token_manager")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TOKEN_CACHE = os.path.join(DATA_DIR, "fb_token_cache.json")
GRAPH_API = "https://graph.facebook.com/v19.0"

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

    # 1. Intentar cache
    cache = load_json(TOKEN_CACHE, {})
    cached_token = cache.get("page_token")
    cached_page  = cache.get("page_id")
    if cached_token and cached_page == PAGE_ID:
        logger.debug("Usando page token cacheado")
        return cached_token

    # 2. Obtener page token via /me/accounts
    logger.info("Obteniendo page token via /me/accounts...")
    try:
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
                # Cachear
                cache["page_token"] = page_token
                cache["page_id"]    = PAGE_ID
                cache["page_name"]  = page.get("name", "")
                cache["updated_at"] = int(time.time())
                save_json(TOKEN_CACHE, cache)
                return page_token

        raise ValueError(
            f"Página {PAGE_ID} no encontrada en /me/accounts. "
            f"Páginas disponibles: {[p.get('id') for p in pages]}"
        )

    except ValueError:
        raise
    except Exception as e:
        # Si /me/accounts falla, usar el token del .env directamente como fallback
        logger.warning(f"No se pudo obtener page token ({e}), usando token del .env")
        return USER_TOKEN


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
