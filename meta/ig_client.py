"""
Cliente de Instagram Graph API para La Voz Riojana.
Publica noticias como posts de imagen en la cuenta de Instagram.

Requiere:
  - Cuenta Instagram Business conectada a la página de Facebook
  - IG_ACCOUNT_ID: ID de la cuenta de Instagram Business
  - IG_ACCESS_TOKEN: Token de acceso con permisos instagram_basic + instagram_content_publish
"""
import os
import time
from urllib.parse import urlparse
import requests
from utils.logging_setup import setup_logger
from utils.file_manager import load_json, save_json
from utils.news_dedup import duplicate_reason
from utils.url_normalization import url_hash
from layout.image_generator import generate_instagram as _gen_ig_img
from utils import r2_storage

logger = setup_logger("ig_client")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
IG_STATE_PATH = os.path.join(DATA_DIR, "ig_posted.json")
IG_RATE_LIMIT_PATH = os.path.join(DATA_DIR, "ig_rate_limit.json")
GRAPH_API = "https://graph.facebook.com/v19.0"

IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
IG_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("IG_RATE_LIMIT_BACKOFF_SECONDS", "10800"))  # 3 horas
IG_VIDEO_PROCESSING_TIMEOUT_SECONDS = int(os.getenv("IG_VIDEO_PROCESSING_TIMEOUT_SECONDS", "300"))
IG_VIDEO_PROCESSING_POLL_SECONDS = int(os.getenv("IG_VIDEO_PROCESSING_POLL_SECONDS", "10"))
IG_POSTED_DEDUP_THRESHOLD = float(os.getenv("IG_POSTED_DEDUP_THRESHOLD", os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5")))


class IGRateLimitError(Exception):
    pass


def is_rate_limited() -> bool:
    """Devuelve True si todavía estamos en el período de backoff por rate limit."""
    state = load_json(IG_RATE_LIMIT_PATH, {})
    blocked_until = state.get("blocked_until", 0)
    if time.time() < blocked_until:
        remaining = int(blocked_until - time.time())
        logger.warning(f"IG rate limit activo: quedan {remaining // 60}m {remaining % 60}s de espera")
        return True
    return False


def _set_rate_limit_backoff() -> None:
    blocked_until = int(time.time()) + IG_RATE_LIMIT_BACKOFF_SECONDS
    save_json(IG_RATE_LIMIT_PATH, {"blocked_until": blocked_until, "set_at": int(time.time())})
    minutes = IG_RATE_LIMIT_BACKOFF_SECONDS // 60
    logger.error(f"IG rate limit detectado (code 4). Backoff de {minutes} min activado hasta {time.strftime('%H:%M:%S', time.localtime(blocked_until))}")


def _is_rate_limit_error(data: dict) -> bool:
    error = data.get("error", {})
    return error.get("code") == 4


def _load_state() -> dict:
    return load_json(IG_STATE_PATH, {"posted": {}})


def _save_state(state: dict) -> None:
    save_json(IG_STATE_PATH, state)


def _is_posted(state: dict, dedup_key: str) -> bool:
    return dedup_key in state.get("posted", {})


def _posted_record(noticia: dict | None, dedup_key: str) -> dict:
    record = {
        "posted_at": int(time.time()),
        "dedup_key": dedup_key,
    }
    if not noticia:
        return record
    for field in (
        "titulo",
        "titulo_instagram",
        "texto_instagram",
        "url",
        "canonical_url",
        "meta_queue_key",
        "web_queue_key",
        "seccion",
        "source",
        "media_type",
    ):
        value = noticia.get(field)
        if value:
            record[field] = value
    return record


def _mark_posted(state: dict, dedup_key: str, noticia: dict | None = None) -> None:
    state.setdefault("posted", {})[dedup_key] = _posted_record(noticia, dedup_key)


def _posted_records(state: dict) -> list[dict]:
    posted = state.get("posted", {})
    if not isinstance(posted, dict):
        return []
    records: list[dict] = []
    for key, value in posted.items():
        if isinstance(value, dict):
            record = dict(value)
            record.setdefault("dedup_key", key)
            records.append(record)
    return records


def _posted_duplicate_reason(state: dict, noticia: dict) -> str | None:
    records = _posted_records(state)
    if not records:
        return None
    return duplicate_reason(
        noticia,
        records,
        key_fields=("dedup_key", "meta_queue_key", "web_queue_key", "canonical_url", "url"),
        threshold=IG_POSTED_DEDUP_THRESHOLD,
    )


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_video_item(noticia: dict) -> bool:
    return str(noticia.get("media_type") or "").lower() == "video" or bool(noticia.get("video_url"))


def _video_url(noticia: dict) -> str:
    for field in ("video_url", "direct_video_url", "mp4_url"):
        value = str(noticia.get(field) or "").strip()
        if value:
            return value
    return ""


def _build_caption(noticia: dict) -> str:
    # Usar caption estructurado si fue generado por OpenAI
    cuerpo = noticia.get("texto_instagram", "").strip()
    if not cuerpo:
        titulo = noticia.get("titulo", "")
        parrafos = noticia.get("parrafos", [])
        primer_parrafo = noticia.get("excerpt", "") or (parrafos[0] if parrafos else "")
        cuerpo = f"{titulo}\n\n{primer_parrafo}"

    hashtag_localidad = noticia.get("hashtag_localidad", "")
    seccion = noticia.get("seccion", "").lower()

    _SECTION_TAGS = {
        "policiales":   "#PoliciaLaRioja #Seguridad",
        "deportes":     "#DeportesRioja #Deportes",
        "cultura":      "#CulturaRioja #Cultura",
        "espectaculos": "#EspectaculosRioja #Cultura",
        "politica":     "#PoliticaRioja #LaRiojaGobierna",
        "economia":     "#EconomiaRioja #Economia",
        "salud":        "#SaludRioja #Salud",
        "educacion":    "#EducacionRioja #Educacion",
        "interior":     "#InteriorRioja #LaRioja",
        "sociedad":     "#LaRiojaHoy #Sociedad",
    }
    tags_extra = _SECTION_TAGS.get(seccion, "#RiojaHoy")
    tags_base  = "#LaVozRiojana #LaRioja #Noticias"
    tags = f"{tags_extra} {tags_base}"
    if hashtag_localidad:
        tags = f"{hashtag_localidad} {tags}"

    return f"{cuerpo}\n\n{tags}"[:2200]


def _wait_video_container(container_id: str) -> bool:
    deadline = time.time() + IG_VIDEO_PROCESSING_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{GRAPH_API}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": IG_ACCESS_TOKEN,
                },
                timeout=30,
            )
            data = r.json()
        except Exception as e:
            logger.warning(f"Excepcion consultando estado de video IG: {e}")
            time.sleep(IG_VIDEO_PROCESSING_POLL_SECONDS)
            continue

        status_code = str(data.get("status_code") or "").upper()
        if status_code in {"FINISHED", "PUBLISHED"}:
            return True
        if status_code == "ERROR":
            logger.error(f"IG no pudo procesar el video: {data}")
            return False
        logger.info(f"Video IG procesando: {status_code or data}")
        time.sleep(IG_VIDEO_PROCESSING_POLL_SECONDS)

    logger.error("Timeout esperando procesamiento de video IG")
    return False


def _post_video_to_instagram(noticia: dict, state: dict, dedup_key: str) -> bool:
    video_url = _video_url(noticia)
    if not _is_http_url(video_url):
        logger.warning("Video IG sin URL publica directa: %s", noticia.get("titulo", "")[:70])
        return False

    caption = _build_caption(noticia)
    payload = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN,
    }
    if str(noticia.get("share_to_feed", True)).lower() not in {"0", "false", "no", "off"}:
        payload["share_to_feed"] = "true"
    cover_url = str(noticia.get("cover_url") or noticia.get("imagen_url") or "").strip()
    if _is_http_url(cover_url):
        payload["cover_url"] = cover_url

    try:
        r = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
            data=payload,
            timeout=60,
        )
        data = r.json()
        if "id" not in data:
            if _is_rate_limit_error(data):
                _set_rate_limit_backoff()
                raise IGRateLimitError("IG rate limit al crear contenedor de Reel")
            logger.error(f"Error creando Reel IG: {data}")
            return False
        container_id = data["id"]
    except IGRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Excepcion creando Reel IG: {e}")
        return False

    if not _wait_video_container(container_id):
        return False

    try:
        r = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": IG_ACCESS_TOKEN,
            },
            timeout=60,
        )
        data = r.json()
        if "id" in data:
            _mark_posted(state, dedup_key, noticia)
            _save_state(state)
            logger.info(f"Reel publicado en Instagram: {noticia.get('titulo', '')[:70]}")
            return True
        if _is_rate_limit_error(data):
            _set_rate_limit_backoff()
            raise IGRateLimitError("IG rate limit al publicar Reel")
        logger.error(f"Error publicando Reel IG: {data}")
        return False
    except IGRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Excepcion publicando Reel IG: {e}")
        return False


def post_to_instagram(noticia: dict) -> bool:
    """
    Publica una noticia en Instagram via Graph API.
    Requiere imagen accesible públicamente (imagen_url).
    Lanza IGRateLimitError si Meta devuelve code 4 (Application request limit reached).
    """
    if not IG_ACCOUNT_ID or IG_ACCOUNT_ID == "PENDIENTE":
        logger.warning("IG_ACCOUNT_ID no configurado, saltando publicación Instagram")
        return False

    if not IG_ACCESS_TOKEN or IG_ACCESS_TOKEN == "PENDIENTE":
        logger.warning("IG_ACCESS_TOKEN no configurado, saltando publicación Instagram")
        return False

    if is_rate_limited():
        raise IGRateLimitError("IG en período de backoff por rate limit")

    state = _load_state()
    dedup_key = noticia.get("dedup_key") or f"link:{url_hash(noticia.get('url', ''))}"
    if _is_posted(state, dedup_key):
        logger.debug(f"Ya publicado en IG: {noticia.get('titulo', '')[:50]}")
        return True
    duplicate = _posted_duplicate_reason(state, noticia)
    if duplicate:
        logger.warning(
            "Ya publicado/similar en IG (%s), se omite: %s",
            duplicate,
            noticia.get("titulo", "")[:70],
        )
        _mark_posted(state, dedup_key, noticia)
        _save_state(state)
        return True

    if _is_video_item(noticia):
        return _post_video_to_instagram(noticia, state, dedup_key)

    imagen_url = noticia.get("imagen_url", "")
    r2_key = None  # clave R2 para eliminar después de publicar

    # ── Generar imagen estilizada y subir a R2 ────────────────
    if r2_storage.is_configured():
        try:
            import tempfile
            ig_img = _gen_ig_img(noticia)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
                ig_img.save(tmp_path, "JPEG", quality=90)

            imagen_url, r2_key = r2_storage.upload_temp(tmp_path, ttl_hint="ig")
            os.unlink(tmp_path)
            logger.info(f"Imagen IG subida a R2: {imagen_url}")
        except Exception as e:
            logger.warning(f"R2 upload falló, usando URL original: {e}")
            r2_key = None
            imagen_url = noticia.get("imagen_url", "")
    else:
        logger.info("R2 no configurado — usando URL original scrapeada para IG")

    if not imagen_url:
        logger.warning(f"Sin imagen para Instagram: {noticia.get('titulo', '')[:50]}")
        return False

    caption = _build_caption(noticia)

    # ── Paso 1: Crear contenedor de media ─────────────────────
    try:
        r = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
            data={
                "image_url": imagen_url,
                "caption": caption,
                "access_token": IG_ACCESS_TOKEN,
            },
            timeout=30,
        )
        data = r.json()
        if "id" not in data:
            if _is_rate_limit_error(data):
                if r2_key:
                    r2_storage.delete(r2_key)
                _set_rate_limit_backoff()
                raise IGRateLimitError("IG rate limit al crear media container")
            logger.error(f"Error creando media IG: {data}")
            if r2_key:
                r2_storage.delete(r2_key)
            return False
        container_id = data["id"]
    except IGRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Excepción creando media IG: {e}")
        if r2_key:
            r2_storage.delete(r2_key)
        return False

    # IG ya descargó la imagen al crear el contenedor — la podemos eliminar de R2
    if r2_key:
        r2_storage.delete(r2_key)
        r2_key = None

    time.sleep(5)

    # ── Paso 2: Publicar el contenedor ────────────────────────
    try:
        r = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": IG_ACCESS_TOKEN,
            },
            timeout=30,
        )
        data = r.json()
        if "id" in data:
            _mark_posted(state, dedup_key, noticia)
            _save_state(state)
            logger.info(f"Publicado en Instagram: {noticia.get('titulo', '')[:70]}")
            return True
        else:
            if _is_rate_limit_error(data):
                _set_rate_limit_backoff()
                raise IGRateLimitError("IG rate limit al publicar media container")
            logger.error(f"Error publicando media IG: {data}")
            return False
    except IGRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Excepción publicando en Instagram: {e}")
        return False
