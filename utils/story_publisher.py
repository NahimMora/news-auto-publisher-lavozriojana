"""Historias de Instagram y Facebook (la misma imagen en las dos redes).

Dos orígenes:

* publicaciones de Instagram ya hechas (posts, carruseles y Reels de la
  cuenta): la historia muestra la publicación tal cual salió;
* piezas de servicio y seguimiento (clima, alertas, dólar, cortes,
  feriados, actualizaciones) que arman ``utils/social_formats.py`` y
  ``utils/story_updates.py``.

Estado propio en ``data/stories_state.json`` (no comparte cupos ni dedup con
el feed). Un resultado ambiguo (red caída después de enviar) no se reintenta:
queda marcado y se informa en el reporte.
"""
from __future__ import annotations

import io
import os
import tempfile
import time

from PIL import Image

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.safe_http import UnsafeURLError, safe_get
from utils.social_time import now_ar, quiet_hours, today_ar

logger = setup_logger("story_publisher", "stories.log")

STATE_PATH = str(data_dir() / "stories_state.json")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}

# Mismos defaults que StoryV2Schema: Remotion no completa props faltantes.
STORY_DEFAULTS: dict = {
    "kind": "post", "assetFile": "", "assetWidth": 0, "assetHeight": 0, "seccion": "", "titulo": "",
    "body": "", "dateLabel": "", "timeLabel": "", "sourceLabel": "", "before": "", "after": "",
    "place": "La Rioja", "temp": 0, "sky": "", "detail": "", "days": [], "alertSummary": "",
    "level": "amarilla", "zones": [], "rows": [], "service": "aviso", "holidays": [], "countdown": "",
    "headline": "", "subhead": "", "groups": [], "magnitude": "", "epicenter": "", "depth": "", "felt": [],
}


def _flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def instagram_enabled() -> bool:
    return _flag("IG_STORIES_ENABLED")


def facebook_enabled() -> bool:
    return _flag("FB_STORIES_ENABLED")


def max_per_day() -> int:
    return _int("STORY_MAX_PER_DAY", 20)


def in_quiet_hours() -> bool:
    return quiet_hours(window=os.getenv("STORY_QUIET_HOURS", "0-7"))


# ── Estado ───────────────────────────────────────────────────────────────
def load_state() -> dict:
    return load_json(STATE_PATH, {"posted": {}}, expected_type=dict)


def _record(key: str, **fields) -> None:
    def mutate(state):
        posted = state.setdefault("posted", {})
        entry = posted.setdefault(key, {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated_at"] = int(time.time())
        cutoff = time.time() - 30 * 86400
        state["posted"] = {k: v for k, v in posted.items() if int(v.get("updated_at") or 0) >= cutoff}
        return state

    update_json(STATE_PATH, mutate, {"posted": {}}, expected_type=dict)


def stories_today(state: dict | None = None) -> int:
    state = state if state is not None else load_state()
    today = today_ar().isoformat()
    return sum(1 for v in (state.get("posted") or {}).values() if v.get("day") == today and (v.get("ig_id") or v.get("fb_id")))


def already_done(key: str, state: dict | None = None) -> bool:
    state = state if state is not None else load_state()
    entry = (state.get("posted") or {}).get(key) or {}
    return bool(entry.get("ig_id") or entry.get("fb_id") or entry.get("ambiguous"))


# ── Render ───────────────────────────────────────────────────────────────
def story_props(**props) -> dict:
    merged = dict(STORY_DEFAULTS)
    merged.update({k: v for k, v in props.items() if v is not None})
    return merged


def render_story(props: dict, asset_path: str | None = None) -> bytes:
    """JPEG 1080×1920 de ``StoryV2``. Lanza ``RemotionRenderError`` si falla."""
    from utils.remotion_renderer import render_still

    full = story_props(**props)
    assets: dict[str, str] = {}
    if asset_path:
        with Image.open(asset_path) as image:
            full["assetWidth"], full["assetHeight"] = image.size
        assets["assetFile"] = asset_path
    png, _meta = render_still("StoryV2", full, asset_paths=assets, timeout=240)
    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=92, optimize=True, subsampling=0)
        return out.getvalue()


def download_image(url: str, max_bytes: int = 15 * 1024 * 1024) -> str | None:
    """Baja una imagen pública a un archivo temporal JPEG (o ``None``)."""
    try:
        response = safe_get(url, timeout=40, headers={"User-Agent": "LaVozRiojanaBot/1.0"})
    except (UnsafeURLError, Exception) as exc:  # noqa: BLE001 — cualquier fallo de red deja la pieza sin imagen
        logger.warning("No se pudo bajar la imagen: %s", type(exc).__name__)
        return None
    content = getattr(response, "content", b"") or b""
    if getattr(response, "status_code", 0) != 200 or not content or len(content) > max_bytes:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            rgb = image.convert("RGB")
            handle, path = tempfile.mkstemp(suffix=".jpg", prefix="lvr_story_")
            os.close(handle)
            rgb.save(path, "JPEG", quality=92)
            return path
    except Exception as exc:  # noqa: BLE001 — imagen corrupta o formato no soportado
        logger.warning("Imagen inválida para la historia: %s", type(exc).__name__)
        return None


# ── Publicación ──────────────────────────────────────────────────────────
def publish_story(key: str, jpeg: bytes, *, instagram: bool, facebook: bool, meta: dict | None = None) -> dict:
    """Publica la misma imagen como historia en Instagram y/o Facebook.

    Devuelve ``{"ig": status, "fb": status}`` (``success``/``failed``/
    ``skipped``/``ambiguous``/``rate_limit``). Registra evidencia por canal.
    """
    from meta import fb_client, ig_client
    from utils import r2_storage

    state = load_state()
    entry = (state.get("posted") or {}).get(key) or {}
    outcome = {"ig": "skipped", "fb": "skipped"}
    day = today_ar().isoformat()
    base = {"day": day, "kind": (meta or {}).get("kind"), "label": (meta or {}).get("label")}

    if instagram and not entry.get("ig_id"):
        if not r2_storage.is_configured():
            outcome["ig"] = "failed"
        else:
            handle, tmp = tempfile.mkstemp(suffix=".jpg", prefix="lvr_story_up_")
            os.close(handle)
            r2_key = ""
            try:
                with open(tmp, "wb") as fh:
                    fh.write(jpeg)
                public_url, r2_key = r2_storage.upload_temp(tmp, ttl_hint="story")
                result = ig_client.post_story_image(public_url)
            except RuntimeError as exc:
                logger.warning("No se pudo subir la historia a R2: %s", exc)
                result = None
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            if result is None:
                outcome["ig"] = "failed"
            elif result.ok:
                outcome["ig"] = "success"
                _record(key, ig_id=result.external_id, ig_at=int(time.time()), **base)
            else:
                outcome["ig"] = _classify(result)
                if outcome["ig"] == "ambiguous":
                    _record(key, ambiguous="instagram", **base)
            if r2_key and outcome["ig"] != "ambiguous":
                try:
                    r2_storage.delete(r2_key)
                except Exception:  # noqa: BLE001 — el objeto temporal expira solo
                    logger.warning("No se pudo borrar la historia temporal de R2")

    if facebook and not entry.get("fb_id") and outcome["ig"] != "ambiguous":
        result = fb_client.post_photo_story(jpeg)
        if result.ok:
            outcome["fb"] = "success"
            _record(key, fb_id=result.external_id, fb_at=int(time.time()), **base)
        else:
            outcome["fb"] = _classify(result)
            if outcome["fb"] == "ambiguous":
                _record(key, ambiguous="facebook", **base)
    logger.info("Historia %s → instagram=%s facebook=%s", key, outcome["ig"], outcome["fb"])
    return outcome


def _classify(result) -> str:
    if result.error_type == "rate_limit":
        return "rate_limit"
    if (result.details or {}).get("publication_outcome") == "unknown":
        return "ambiguous"
    return "failed"


# ── Historias de publicaciones de Instagram ──────────────────────────────
_LOCAL_SOURCES = ("nuevarioja", "tiempopopular", "fenix", "judicial_")


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def recent_instagram_media(limit: int = 25) -> list[dict]:
    from meta import ig_client

    data = ig_client.graph_get(
        f"{ig_client.IG_ACCOUNT_ID}/media",
        {"fields": "id,media_type,media_product_type,media_url,thumbnail_url,timestamp,caption,children{media_type,media_url}", "limit": limit},
    )
    return list((data or {}).get("data") or [])


def _posted_index() -> dict[str, dict]:
    """external_id → registro de ig_posted (sección, fuente, título)."""
    try:
        state = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict)
    except JsonStateError:
        return {}
    out = {}
    for record in (state.get("posted") or {}).values():
        if isinstance(record, dict) and record.get("external_id"):
            out[str(record["external_id"])] = record
    return out


def _media_image_url(media: dict) -> str:
    kind = str(media.get("media_type") or "")
    if kind == "VIDEO":
        return str(media.get("thumbnail_url") or "")
    if kind == "CAROUSEL_ALBUM":
        for child in ((media.get("children") or {}).get("data") or []):
            if child.get("media_type") == "IMAGE" and child.get("media_url"):
                return str(child["media_url"])
        return ""
    return str(media.get("media_url") or "")


def _timestamp(media: dict) -> float:
    from datetime import datetime

    try:
        return datetime.strptime(str(media.get("timestamp")), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return 0.0


def post_story_candidates(media: list[dict], *, lookback_hours: float, state: dict, now: float | None = None) -> list[dict]:
    """Publicaciones recientes sin historia, ordenadas: último momento,
    locales y el resto; dentro de cada grupo, la más nueva primero."""
    from utils.editorial_priority import is_breaking

    now = now or time.time()
    index = _posted_index()
    out = []
    for m in media:
        media_id = str(m.get("id") or "")
        if not media_id or already_done(f"post:{media_id}", state):
            continue
        ts = _timestamp(m)
        if not ts or now - ts > lookback_hours * 3600:
            continue
        image_url = _media_image_url(m)
        if not image_url:
            continue
        record = index.get(media_id) or {}
        reel = m.get("media_product_type") == "REELS"
        title = str(record.get("titulo") or "")
        section = str(record.get("seccion") or "")
        # El orden usa la misma regla de urgencia que el feed (amplia); el
        # rótulo "Último momento" en la historia, sólo con la palabra explícita.
        breaking = bool(title) and is_breaking(title, section)
        explicit = any(word in _fold(title) for word in ("ultimo momento", "urgente"))
        local = str(record.get("source") or "").startswith(_LOCAL_SOURCES)
        rank = 0 if breaking else 1 if local else 2
        out.append({
            "key": f"post:{media_id}", "media_id": media_id, "image_url": image_url, "reel": reel,
            "breaking": breaking, "explicit_breaking": explicit, "seccion": section, "title": title, "rank": rank, "ts": ts,
        })
    out.sort(key=lambda c: (c["rank"], -c["ts"]))
    return out


def story_for_candidate(candidate: dict) -> tuple[dict, str | None]:
    """Props + imagen local para una publicación de Instagram."""
    path = download_image(candidate["image_url"])
    kind = "reel" if candidate["reel"] else "breaking" if candidate.get("explicit_breaking") else "post"
    return story_props(kind=kind, seccion=candidate["seccion"]), path


def describe_now() -> str:
    return now_ar().strftime("%Y-%m-%d %H:%M")
