"""
Cliente de Facebook Graph API para La Voz Riojana.
Publica noticias en la pagina de Facebook configurada usando el link web para cargar preview OG.
"""
import os
import time
from urllib.parse import urlparse

import requests

from meta.facebook_token_manager import get_page_token
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger
from utils.url_normalization import url_hash

logger = setup_logger("fb_client")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
FB_STATE_PATH = os.path.join(DATA_DIR, "fb_posted.json")
GRAPH_API = "https://graph.facebook.com/v19.0"

PAGE_ID = os.getenv("FB_PAGE_ID", "")
DISABLED_PAGE_IDS = set(
    x.strip() for x in os.getenv("FB_DISABLED_PAGE_IDS", "").split(",") if x.strip()
)
TEMP_BLOCK_BACKOFF = int(os.getenv("FB_TEMP_BLOCK_BACKOFF_SECONDS", "1800"))


def _load_state() -> dict:
    return load_json(FB_STATE_PATH, {"posted": {}, "page_backoff": {}})


def _save_state(state: dict) -> None:
    save_json(FB_STATE_PATH, state)


def _is_posted(state: dict, dedup_key: str) -> bool:
    return dedup_key in state.get("posted", {})


def _mark_posted(state: dict, dedup_key: str) -> None:
    state.setdefault("posted", {})[dedup_key] = int(time.time())


def _is_in_backoff(state: dict) -> bool:
    until = state.get("page_backoff", {}).get(PAGE_ID, 0)
    return time.time() < until


def _set_backoff(state: dict) -> None:
    state.setdefault("page_backoff", {})[PAGE_ID] = int(time.time()) + TEMP_BLOCK_BACKOFF
    logger.warning(f"Backoff activado para pagina {PAGE_ID} por {TEMP_BLOCK_BACKOFF}s")


def _build_message(noticia: dict) -> str:
    cuerpo = str(noticia.get("texto_instagram") or "").strip()
    if not cuerpo:
        titulo = noticia.get("titulo", "")
        parrafos = noticia.get("parrafos", [])
        primer_parrafo = noticia.get("excerpt", "") or (parrafos[0] if parrafos else "")
        cuerpo = f"{titulo}\n\n{primer_parrafo}"

    hashtag_localidad = noticia.get("hashtag_localidad", "")
    seccion = str(noticia.get("seccion", "")).lower()

    section_tags = {
        "policiales": "#PoliciaLaRioja #Seguridad",
        "deportes": "#DeportesRioja #Deportes",
        "cultura": "#CulturaRioja #Cultura",
        "espectaculos": "#EspectaculosRioja #Cultura",
        "politica": "#PoliticaRioja #LaRiojaGobierna",
        "economia": "#EconomiaRioja #Economia",
        "salud": "#SaludRioja #Salud",
        "educacion": "#EducacionRioja #Educacion",
        "interior": "#InteriorRioja #LaRioja",
        "sociedad": "#LaRiojaHoy #Sociedad",
    }
    tags_extra = section_tags.get(seccion, "#RiojaHoy")
    tags_base = "#LaVozRiojana #LaRioja #Noticias"
    tags = f"{tags_extra} {tags_base}"
    if hashtag_localidad:
        tags = f"{hashtag_localidad} {tags}"

    return f"{cuerpo}\n\n{tags}"


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_video_item(noticia: dict) -> bool:
    return str(noticia.get("media_type") or "").lower() == "video" or bool(noticia.get("video_url"))


def _video_url(noticia: dict) -> str:
    for key in ("video_url", "direct_video_url", "mp4_url"):
        value = str(noticia.get(key) or "").strip()
        if _is_http_url(value):
            return value
    return ""


def _web_link(noticia: dict) -> str:
    for key in ("web_url", "noticia_url", "public_url", "publicUrl", "permalink", "link"):
        value = str(noticia.get(key) or "").strip()
        if _is_http_url(value):
            return value
    return ""


def _dedup_key(noticia: dict) -> str:
    basis = noticia.get("canonical_url") or noticia.get("url") or _web_link(noticia) or noticia.get("titulo", "")
    return f"link:{url_hash(str(basis))}"


def _post_video_to_facebook(noticia: dict, token: str, state: dict, dedup_key: str) -> bool:
    video_url = _video_url(noticia)
    if not video_url:
        return False

    payload = {
        "description": _build_message(noticia),
        "file_url": video_url,
        "access_token": token,
    }

    try:
        r = requests.post(f"{GRAPH_API}/{PAGE_ID}/videos", data=payload, timeout=120)
        data = r.json()

        if r.status_code == 200 and ("id" in data or "video_id" in data):
            _mark_posted(state, dedup_key)
            _save_state(state)
            logger.info(f"Video publicado en Facebook: {noticia.get('titulo', '')[:70]}")
            return True

        if "error" in data:
            error = data["error"]
            code = error.get("code", 0)
            msg = error.get("message", "")
            if code in (32, 613) or "temporarily blocked" in msg.lower():
                _set_backoff(state)
                _save_state(state)
            logger.error(f"Error Graph API FB video [{code}]: {msg}")
        return False
    except Exception as e:
        logger.error(f"Excepcion publicando video en Facebook: {e}")
        return False


def post_to_facebook(noticia: dict) -> bool:
    """Publica una noticia en la pagina de Facebook. Retorna True si exitoso."""
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        logger.warning("FB_PAGE_ID no configurado, saltando publicacion Facebook")
        return False

    if PAGE_ID in DISABLED_PAGE_IDS:
        logger.info(f"Pagina {PAGE_ID} deshabilitada")
        return False

    state = _load_state()

    if _is_in_backoff(state):
        logger.warning(f"Pagina {PAGE_ID} en backoff, saltando")
        return False

    dedup_key = noticia.get("dedup_key") or _dedup_key(noticia)
    if _is_posted(state, dedup_key):
        logger.debug(f"Ya publicado en FB: {noticia.get('titulo', '')[:50]}")
        return True

    if _is_video_item(noticia):
        try:
            token = get_page_token()
        except ValueError as e:
            logger.error(str(e))
            return False

        if _post_video_to_facebook(noticia, token, state, dedup_key):
            return True

        source_link = str(noticia.get("source_video_url") or noticia.get("url") or "").strip()
        if _is_http_url(source_link):
            payload = {
                "message": _build_message(noticia),
                "link": source_link,
                "access_token": token,
            }
            try:
                r = requests.post(f"{GRAPH_API}/{PAGE_ID}/feed", data=payload, timeout=60)
                data = r.json()
                if r.status_code == 200 and ("id" in data or "post_id" in data):
                    _mark_posted(state, dedup_key)
                    _save_state(state)
                    logger.info(f"Link de video publicado en Facebook: {noticia.get('titulo', '')[:70]}")
                    return True
            except Exception as e:
                logger.error(f"Excepcion publicando link de video en Facebook: {e}")
        return False

    link = _web_link(noticia)
    if not link:
        logger.warning("Facebook requiere web_url/noticia_url para cargar preview OG: %s", noticia.get("titulo", "")[:70])
        return False

    try:
        token = get_page_token()
    except ValueError as e:
        logger.error(str(e))
        return False

    payload = {
        "message": _build_message(noticia),
        "link": link,
        "access_token": token,
    }

    try:
        r = requests.post(f"{GRAPH_API}/{PAGE_ID}/feed", data=payload, timeout=60)
        data = r.json()

        if r.status_code == 200 and ("id" in data or "post_id" in data):
            _mark_posted(state, dedup_key)
            _save_state(state)
            logger.info(f"Publicado en Facebook: {noticia.get('titulo', '')[:70]}")
            return True

        if "error" in data:
            error = data["error"]
            code = error.get("code", 0)
            msg = error.get("message", "")
            if code in (32, 613) or "temporarily blocked" in msg.lower():
                _set_backoff(state)
                _save_state(state)
            logger.error(f"Error Graph API FB [{code}]: {msg}")
        return False

    except Exception as e:
        logger.error(f"Excepcion publicando en Facebook: {e}")
        return False
