import os
import re
import time
from typing import Literal
from utils.editorial_priority import priority_interleave, split_priority_batch
from utils.file_manager import load_json, save_json
from utils.news_dedup import duplicate_reason
from utils.url_normalization import url_hash
from utils.logging_setup import setup_logger

logger = setup_logger("social_queue")

DATA_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
QUEUE_PATH = os.path.join(DATA_DIR, "noticias_sociales_pendientes.json")

Platform = Literal["facebook", "instagram"]

# Noticias más viejas que esto no se publican (son irrelevantes)
SOCIAL_TTL_HOURS = int(os.getenv("SOCIAL_TTL_HOURS", "48"))

# Umbral de similitud Jaccard para considerar dos títulos como duplicados
DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5"))

def _load_queue() -> list[dict]:
    return load_json(QUEUE_PATH, [])


def _save_queue(queue: list[dict]) -> None:
    save_json(QUEUE_PATH, queue)


def _normalize(text: str) -> set[str]:
    """
    Tokeniza un título en stems de 5 chars para comparar similitud.
    El truncado a 5 letras aproxima stemming en español:
    heridos/heridas → herid, provincial/provincia → provi, etc.
    """
    stopwords = {"para", "con", "por", "del", "los", "las", "una", "que", "son",
                 "fue", "dos", "tres", "sus", "este", "esta", "desde", "hacia"}
    words = re.findall(r"[a-záéíóúüñ]+", text.lower())
    return {w[:5] for w in words if len(w) >= 4 and w not in stopwords}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _priority_interleave(items: list[dict]) -> list[dict]:
    return priority_interleave(items)


def _item_keys(item: dict) -> set[str]:
    keys = {
        str(item.get(field) or "").strip()
        for field in ("dedup_key", "meta_queue_key", "web_queue_key")
        if item.get(field)
    }
    for field in ("canonical_url", "url"):
        value = str(item.get(field) or "").strip()
        if value:
            keys.add(f"link:{url_hash(value)}")
    return {key for key in keys if key}


def _social_category_caps() -> dict[str, int]:
    max_deportes = _env_int(
        "SOCIAL_MAX_DEPORTES_PER_RUN",
        _env_int("MAX_DEPORTES_PER_RUN", 1),
    )
    return {"deportes": max_deportes}


def _is_similar_to_existing(titulo: str, queue: list[dict]) -> bool:
    """Devuelve True si ya hay un artículo con título muy similar en la cola."""
    return duplicate_reason(
        {"titulo": titulo},
        queue,
        threshold=DEDUP_SIMILARITY_THRESHOLD,
    ) is not None


def enqueue(noticia: dict, platform: Platform | None = None) -> None:
    """Agrega una noticia a la cola si no está ya (por URL ni por título similar)."""
    queue = _load_queue()

    # Dedup por URL
    key = f"link:{url_hash(noticia.get('url', ''))}"
    noticia["dedup_key"] = noticia.get("dedup_key") or key
    new_keys = _item_keys(noticia)
    for item in queue:
        if not isinstance(item, dict) or not (_item_keys(item) & new_keys):
            continue
        if platform:
            field = f"{platform}_done"
            done_at_field = f"{platform}_done_at"
            if item.get(field):
                if item.get(done_at_field):
                    logger.debug(f"Ya completado en {platform}: {noticia.get('titulo', '')[:50]}")
                    return
                item[field] = False
                _save_queue(queue)
                logger.info(f"Reactivado en cola {platform}: {noticia.get('titulo', '')[:50]}")
        logger.debug(f"Ya en cola (URL): {noticia.get('titulo', '')[:50]}")
        return

    # Dedup por similitud de título
    titulo = noticia.get("titulo", "")
    if _is_similar_to_existing(titulo, queue):
        logger.info(f"Descartado por similitud: {titulo[:60]}")
        return

    noticia["social_queued_at"] = int(time.time())
    if platform == "facebook":
        noticia.setdefault("facebook_done", False)
        noticia.setdefault("instagram_done", True)
    elif platform == "instagram":
        noticia.setdefault("facebook_done", True)
        noticia.setdefault("instagram_done", False)
    else:
        noticia.setdefault("facebook_done",  False)
        noticia.setdefault("instagram_done", False)
    queue.append(noticia)
    _save_queue(queue)
    logger.info(f"Encolado: {titulo[:60]}")


def get_pending(platform: Platform, *, max_items: int | None = None) -> list[dict]:
    """Retorna artículos pendientes para la plataforma, excluyendo los vencidos por TTL."""
    queue    = _load_queue()
    field    = f"{platform}_done"
    cutoff   = int(time.time()) - SOCIAL_TTL_HOURS * 3600

    vencidos = 0
    pending  = []
    for item in queue:
        if item.get("manual_status") == "draft" or item.get("needs_direct_video_url"):
            continue
        if item.get(field, False):
            continue
        queued_at = item.get("social_queued_at", item.get("queued_at", cutoff))
        if queued_at < cutoff:
            # Marcar como hecho en esta plataforma para que compact_queue la limpie
            item[field] = True
            item[f"{platform}_done_at"] = int(time.time())
            vencidos += 1
            continue
        pending.append(item)

    if vencidos:
        _save_queue(queue)
        logger.info(f"TTL: {vencidos} artículos vencidos (+{SOCIAL_TTL_HOURS}h) descartados de cola {platform}")

    if max_items is None:
        return _priority_interleave(pending)

    selected, deferred = split_priority_batch(
        pending,
        max_items=max_items,
        category_caps=_social_category_caps(),
    )
    if deferred:
        logger.info(
            "Prioridad editorial %s: %s en lote, %s diferidas (cupo Deportes=%s)",
            platform,
            len(selected),
            len(deferred),
            _social_category_caps().get("deportes"),
        )
    return selected


def mark_done(noticia: dict, platform: Platform) -> None:
    queue = _load_queue()
    keys  = _item_keys(noticia)
    field = f"{platform}_done"
    done_at_field = f"{platform}_done_at"
    for item in queue:
        if isinstance(item, dict) and (_item_keys(item) & keys):
            item[field] = True
            item[done_at_field] = int(time.time())
            break
    _save_queue(queue)


def sync_done_from_posted_state(platform: Platform, posted_keys: set[str]) -> int:
    """Marca como hechas las entradas que ya figuran en el estado local publicado."""
    if not posted_keys:
        return 0

    queue = _load_queue()
    field = f"{platform}_done"
    done_at_field = f"{platform}_done_at"
    changed = 0
    for item in queue:
        if not isinstance(item, dict):
            continue
        if _item_keys(item) & posted_keys:
            updated = False
            if not item.get(field):
                item[field] = True
                updated = True
            if not item.get(done_at_field):
                item[done_at_field] = int(time.time())
                updated = True
            if updated:
                changed += 1

    if changed:
        _save_queue(queue)
        logger.info("%s: %s entradas ya publicadas fueron sincronizadas en la cola", platform, changed)
    return changed


def compact_queue() -> None:
    """Elimina entradas completadas en todas las plataformas."""
    queue  = _load_queue()
    active = [
        item for item in queue
        if not (item.get("facebook_done") and item.get("instagram_done"))
    ]
    removed = len(queue) - len(active)
    if removed:
        logger.info(f"Cola compactada: {removed} entradas eliminadas")
    _save_queue(active)
