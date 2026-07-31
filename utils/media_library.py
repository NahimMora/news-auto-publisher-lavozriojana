"""Biblioteca multimedia de diez días: assets optimizados + búsqueda unificada.

Combina, para uso del Estudio Premium (Fase 3):

- assets de imagen propios (``data/media_library.json`` +
  ``output/media_library/{masters,thumbs}/``): copia maestra optimizada,
  miniatura, hash, dimensiones y metadata de origen;
- noticias candidatas del router editorial (``utils.editorial_router``);
- noticias con evidencia real de publicación automática (Web/Facebook/
  Instagram);
- publicaciones manuales premium existentes (``utils.manual_post_queue``).

No requiere base de datos ni servicios externos. Toda escritura usa
``utils.file_manager`` (atómica, con lock).
"""
from __future__ import annotations

import copy
import hashlib
import io
import os
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir
from utils.upload_validation import InvalidUploadError, validate_upload_content

logger = setup_logger("media_library", "media_library.log")

LIBRARY_WINDOW_DAYS = 10
MASTER_MAX_DIMENSION = 2048
MASTER_MIN_DIMENSION_HINT = 1600  # no se sobre-escala nunca por debajo del original
THUMB_MAX_DIMENSION = 320
MASTER_JPEG_QUALITY = 85
THUMB_JPEG_QUALITY = 78


def _library_path() -> str:
    return str(data_dir() / "media_library.json")


def _masters_dir() -> Path:
    directory = output_dir() / "media_library" / "masters"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _thumbs_dir() -> Path:
    directory = output_dir() / "media_library" / "thumbs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _ascii_lower(text: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


# ── Ingesta de imágenes ──────────────────────────────────────────────────

def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resize_longer_side(image: Image.Image, target: int) -> Image.Image:
    width, height = image.size
    longer = max(width, height)
    if longer <= target:
        return image
    scale = target / float(longer)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.LANCZOS)


def ingest_image_bytes(
    data: bytes,
    *,
    filename: str = "asset.jpg",
    origin: str = "scraped",
    source_url: str | None = None,
    article_id: str | None = None,
    topic_key: str | None = None,
    titulo: str | None = None,
    seccion: str | None = None,
    source: str | None = None,
    validate: bool = True,
) -> dict:
    """Crea (o reutiliza) un asset optimizado + miniatura, deduplicado por hash.

    ``validate=True`` exige que el contenido sea una imagen real con firma
    válida (obligatorio para contenido subido por un operador; para
    contenido ya validado río arriba por el scraper/safe_http se puede
    pasar ``False`` para evitar doble trabajo, pero por defecto se valida
    siempre — más seguro y barato).
    """
    if validate:
        try:
            validate_upload_content(data, filename, "image")
        except InvalidUploadError as exc:
            raise ValueError(f"Imagen inválida: {exc}") from exc

    digest = _hash_bytes(data)
    existing = _find_by_hash(digest)
    if existing:
        _touch_asset(existing["asset_id"])
        updated = _find_by_hash(digest)
        return updated or existing

    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image = opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo decodificar la imagen: {exc}") from exc

    original_width, original_height = image.size
    master = _resize_longer_side(image, MASTER_MAX_DIMENSION)
    thumb = _resize_longer_side(image, THUMB_MAX_DIMENSION)

    master_path = _masters_dir() / f"{digest}.jpg"
    thumb_path = _thumbs_dir() / f"{digest}.jpg"
    if not master_path.exists():
        master.save(master_path, format="JPEG", quality=MASTER_JPEG_QUALITY)
    if not thumb_path.exists():
        thumb.save(thumb_path, format="JPEG", quality=THUMB_JPEG_QUALITY)

    now = int(time.time())
    record = {
        "asset_id": uuid.uuid4().hex,
        "hash": digest,
        "origin": origin,
        "master_path": str(master_path),
        "thumb_path": str(thumb_path),
        "width": original_width,
        "height": original_height,
        "master_width": master.size[0],
        "master_height": master.size[1],
        "source_url": source_url,
        "article_id": article_id,
        "topic_key": topic_key,
        "titulo": titulo,
        "seccion": seccion,
        "source": source,
        "created_at_ts": now,
        "last_used_at_ts": now,
        "used_count": 1,
        "referenced_by": [],
        "files_purged": False,
    }

    def append(assets):
        if not isinstance(assets, list):
            raise ValueError("media_library.json debe contener una lista")
        assets.append(record)
        return assets

    update_json(_library_path(), append, [], expected_type=list)
    logger.info("Asset ingresado hash=%s origin=%s titulo=%s", digest[:12], origin, str(titulo or "")[:60])
    return record


def _find_by_hash(digest: str) -> dict | None:
    assets = load_json(_library_path(), [], expected_type=list)
    for asset in assets:
        if isinstance(asset, dict) and asset.get("hash") == digest:
            return asset
    return None


def get_asset(asset_id: str) -> dict | None:
    """Devuelve una copia del asset por ID, sin exponer el estado mutable."""
    assets = load_json(_library_path(), [], expected_type=list)
    for asset in assets:
        if isinstance(asset, dict) and asset.get("asset_id") == asset_id:
            return copy.deepcopy(asset)
    return None


def get_asset_thumbnail_path(asset_id: str) -> str | None:
    """Resuelve una miniatura vigente dentro del directorio controlado."""
    asset = get_asset(asset_id)
    if not asset or asset.get("files_purged"):
        return None
    raw_path = str(asset.get("thumb_path") or "").strip()
    if not raw_path:
        return None
    root = os.path.realpath(_thumbs_dir())
    candidate = os.path.realpath(raw_path)
    try:
        inside_root = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside_root = False
    if not inside_root or not os.path.isfile(candidate):
        return None
    return candidate


def _touch_asset(asset_id: str) -> None:
    def mutate(assets):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("asset_id") == asset_id:
                asset["used_count"] = int(asset.get("used_count") or 0) + 1
                asset["last_used_at_ts"] = int(time.time())
                break
        return assets

    update_json(_library_path(), mutate, [], expected_type=list)


def mark_asset_used(asset_id: str, draft_id: str) -> None:
    """Un borrador empieza a referenciar un asset: protege de la limpieza."""

    def mutate(assets):
        for asset in assets:
            if not (isinstance(asset, dict) and asset.get("asset_id") == asset_id):
                continue
            referenced = asset.setdefault("referenced_by", [])
            if draft_id not in referenced:
                referenced.append(draft_id)
            asset["used_count"] = int(asset.get("used_count") or 0) + 1
            asset["last_used_at_ts"] = int(time.time())
            break
        return assets

    update_json(_library_path(), mutate, [], expected_type=list)


def unmark_asset_used(asset_id: str, draft_id: str) -> None:
    """Un borrador deja de referenciar un asset (se borró o cambió de imagen)."""

    def mutate(assets):
        for asset in assets:
            if not (isinstance(asset, dict) and asset.get("asset_id") == asset_id):
                continue
            referenced = asset.get("referenced_by") or []
            asset["referenced_by"] = [item for item in referenced if item != draft_id]
            break
        return assets

    update_json(_library_path(), mutate, [], expected_type=list)


# ── Limpieza segura ───────────────────────────────────────────────────────

def cleanup_expired_assets(
    *,
    now_ts: int | None = None,
    retention_days: int = LIBRARY_WINDOW_DAYS,
    dry_run: bool = True,
    active_publication: bool = False,
) -> dict:
    """Limpia sólo assets vencidos, no referenciados y con copia verificada.

    Nunca borra la entrada de metadata completa (rule: no perder historial):
    sólo elimina los archivos físicos y marca ``files_purged``. Se niega a
    ejecutarse si el llamador indica una publicación activa.
    """
    if active_publication:
        return {
            "status": "blocked",
            "reason": "active_publication",
            "purged": [],
            "kept_referenced": 0,
            "kept_not_expired": 0,
            "errors": [],
        }

    now_ts = int(now_ts if now_ts is not None else time.time())
    cutoff = now_ts - retention_days * 86400
    report = {"purged": [], "kept_referenced": 0, "kept_not_expired": 0, "errors": []}

    def mutate(assets):
        if not isinstance(assets, list):
            raise ValueError("media_library.json debe contener una lista")
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("files_purged"):
                continue
            created = int(asset.get("created_at_ts") or 0)
            if created > cutoff:
                report["kept_not_expired"] += 1
                continue
            if asset.get("referenced_by"):
                report["kept_referenced"] += 1
                continue
            master_path = asset.get("master_path")
            if not master_path or not os.path.exists(master_path):
                report["errors"].append(
                    {"asset_id": asset.get("asset_id"), "error": "master_missing_cannot_verify"}
                )
                continue
            report["purged"].append(asset.get("asset_id"))
            if not dry_run:
                for path in (asset.get("master_path"), asset.get("thumb_path")):
                    if path and os.path.exists(path):
                        try:
                            os.unlink(path)
                        except OSError as exc:
                            report["errors"].append({"asset_id": asset.get("asset_id"), "error": str(exc)})
                asset["files_purged"] = True
                asset["purged_at_ts"] = now_ts
                asset["master_path"] = None
                asset["thumb_path"] = None
        return assets

    update_json(_library_path(), mutate, [], expected_type=list)
    report["status"] = "success" if not report["errors"] else "degraded"
    report["dry_run"] = dry_run
    logger.info(
        "Cleanup dry_run=%s purgados=%s referenciados=%s vigentes=%s errores=%s",
        dry_run,
        len(report["purged"]),
        report["kept_referenced"],
        report["kept_not_expired"],
        len(report["errors"]),
    )
    return report


# ── Búsqueda unificada ────────────────────────────────────────────────────

def _published_identity_keys() -> set[str]:
    keys: set[str] = set()
    try:
        ig_state = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict)
        keys.update((ig_state.get("posted") or {}).keys())
    except JsonStateError:
        pass
    try:
        fb_state = load_json(
            str(data_dir() / "fb_posted.json"), {"posted": {}, "page_backoff": {}}, expected_type=dict
        )
        keys.update((fb_state.get("posted") or {}).keys())
    except JsonStateError:
        pass
    try:
        web_published = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
        for item in web_published:
            if not isinstance(item, dict):
                continue
            for field in ("web_queue_key", "dedup_key", "canonical_url", "url"):
                value = item.get(field)
                if value:
                    keys.add(str(value))
    except JsonStateError:
        pass
    return keys


def _news_is_published(noticia: dict, published_keys: set[str]) -> bool:
    for field in ("dedup_key", "meta_queue_key", "web_queue_key", "canonical_url", "url"):
        value = noticia.get(field)
        if value and str(value) in published_keys:
            return True
    return False


def _news_row(noticia: dict, *, published_keys: set[str]) -> dict:
    route_by_channel = noticia.get("route_by_channel") or {}
    is_candidate = route_by_channel.get("instagram") == "candidate"
    is_published = _news_is_published(noticia, published_keys)
    is_automatic = not is_candidate and (route_by_channel.get("instagram") == "automatic" or not route_by_channel)
    estado = "publicada" if is_published else ("candidata" if is_candidate else "automatica")
    return {
        "resource_id": f"news:{noticia.get('meta_queue_key') or noticia.get('dedup_key') or noticia.get('canonical_url') or ''}",
        "resource_type": "news",
        "titulo": noticia.get("titulo_original") or noticia.get("titulo"),
        "seccion": noticia.get("seccion"),
        "fuente": noticia.get("source"),
        "fecha": noticia.get("fecha") or noticia.get("queued_at"),
        "estado": estado,
        "topic_key": noticia.get("topic_key"),
        "thumbnail": noticia.get("imagen_url") or noticia.get("imagen"),
        "is_published": is_published,
        "is_candidate": is_candidate,
        "is_premium": False,
        "is_automatic": is_automatic,
        "used_count": 0,
        "created_at_ts": noticia.get("routed_at_ts") or noticia.get("queued_at") or 0,
    }


def _candidate_row(candidate: dict) -> dict:
    noticia = candidate.get("noticia") or {}
    return {
        "resource_id": f"candidate:{candidate.get('candidate_id')}",
        "resource_type": "news",
        "titulo": candidate.get("titulo"),
        "seccion": candidate.get("seccion"),
        "fuente": candidate.get("source"),
        "fecha": noticia.get("fecha") or candidate.get("created_at_ts"),
        "estado": candidate.get("status"),
        "topic_key": candidate.get("topic_key"),
        "thumbnail": noticia.get("imagen_url") or noticia.get("imagen"),
        "is_published": False,
        "is_candidate": candidate.get("status") == "candidate",
        "is_premium": False,
        "is_automatic": False,
        "used_count": 0,
        "created_at_ts": candidate.get("created_at_ts") or 0,
    }


def _premium_row(item: dict, *, status: str) -> dict:
    return {
        "resource_id": f"premium:{item.get('dedup_key') or item.get('titulo')}",
        "resource_type": "draft" if status == "draft" else "news",
        "titulo": item.get("titulo_original") or item.get("titulo"),
        "seccion": item.get("categoria") or item.get("seccion"),
        "fuente": item.get("source") or "manual_custom_post",
        "fecha": item.get("web_queued_at") or item.get("queued_at"),
        "estado": status,
        "topic_key": item.get("topic_key"),
        "thumbnail": item.get("imagen_url") or item.get("imagen"),
        "is_published": status == "published",
        "is_candidate": False,
        "is_premium": True,
        "is_automatic": False,
        "used_count": 0,
        "created_at_ts": item.get("web_queued_at") or item.get("queued_at") or 0,
    }


def _asset_row(asset: dict) -> dict:
    asset_id = str(asset.get("asset_id") or "")
    thumbnail = None
    if asset_id and not asset.get("files_purged") and asset.get("thumb_path"):
        thumbnail = f"/api/media-library/thumb/{asset_id}"
    return {
        "resource_id": f"asset:{asset_id}",
        "resource_type": "image",
        "titulo": asset.get("titulo"),
        "seccion": asset.get("seccion"),
        "fuente": asset.get("source"),
        "fecha": asset.get("created_at_ts"),
        "estado": "purgado" if asset.get("files_purged") else asset.get("origin"),
        "topic_key": asset.get("topic_key"),
        "thumbnail": thumbnail,
        "is_published": False,
        "is_candidate": False,
        "is_premium": asset.get("origin") == "draft",
        "is_automatic": False,
        "used_count": int(asset.get("used_count") or 0),
        "created_at_ts": asset.get("created_at_ts") or 0,
        "asset_id": asset_id,
        "referenced_by": list(asset.get("referenced_by") or []),
    }


def _all_rows() -> list[dict]:
    rows: list[dict] = []

    try:
        from utils.editorial_router import list_candidates

        for candidate in list_candidates():
            rows.append(_candidate_row(candidate))
    except JsonStateError:
        pass

    try:
        published_keys = _published_identity_keys()
        noticias = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
        for noticia in noticias:
            if isinstance(noticia, dict):
                rows.append(_news_row(noticia, published_keys=published_keys))
    except JsonStateError:
        pass

    try:
        from utils.manual_post_queue import load_post_state

        state = load_post_state()
        for item in state.get("drafts") or []:
            rows.append(_premium_row(item, status="draft"))
        for item in state.get("published") or []:
            rows.append(_premium_row(item, status="published"))
    except JsonStateError:
        pass

    try:
        assets = load_json(_library_path(), [], expected_type=list)
        for asset in assets:
            if isinstance(asset, dict):
                rows.append(_asset_row(asset))
    except JsonStateError:
        pass

    return rows


def _matches_query(row: dict, needle: str) -> bool:
    haystacks = (row.get("titulo"), row.get("topic_key"), row.get("seccion"), row.get("fuente"))
    return any(needle in _ascii_lower(value) for value in haystacks if value)


def search_library(
    *,
    query: str | None = None,
    seccion: str | None = None,
    fuente: str | None = None,
    topic_key: str | None = None,
    estado: str | None = None,
    only_candidatas: bool = False,
    only_publicadas: bool = False,
    only_premium: bool = False,
    only_automaticas: bool = False,
    window_days: int | None = LIBRARY_WINDOW_DAYS,
    now_ts: int | None = None,
) -> list[dict]:
    """Búsqueda local, case/accent-insensitive, sin servicios externos."""
    now_ts = int(now_ts if now_ts is not None else time.time())
    rows = _all_rows()

    if window_days:
        cutoff = now_ts - window_days * 86400
        rows = [row for row in rows if int(row.get("created_at_ts") or 0) >= cutoff]

    if query:
        needle = _ascii_lower(query.strip())
        if needle:
            rows = [row for row in rows if _matches_query(row, needle)]

    if seccion:
        needle = _ascii_lower(seccion)
        rows = [row for row in rows if _ascii_lower(row.get("seccion")) == needle]
    if fuente:
        needle = _ascii_lower(fuente)
        rows = [row for row in rows if _ascii_lower(row.get("fuente")) == needle]
    if topic_key:
        rows = [row for row in rows if row.get("topic_key") == topic_key]
    if estado:
        needle = _ascii_lower(estado)
        rows = [row for row in rows if _ascii_lower(row.get("estado")) == needle]

    if only_candidatas:
        rows = [row for row in rows if row.get("is_candidate")]
    if only_publicadas:
        rows = [row for row in rows if row.get("is_published")]
    if only_premium:
        rows = [row for row in rows if row.get("is_premium")]
    if only_automaticas:
        rows = [row for row in rows if row.get("is_automatic")]

    rows.sort(key=lambda row: int(row.get("created_at_ts") or 0), reverse=True)
    return rows
