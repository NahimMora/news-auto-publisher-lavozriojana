"""Selección unificada de qué se publica cada ciclo — mismo lote replicado en
Web, Facebook e Instagram (ver docs/DECISIONS.md).

Reemplaza la selección independiente que hacía cada canal (gate de categoría
+ router sólo para Instagram, sin ningún filtro para Web/Facebook) por un
único cálculo acá, marcado (``selected_for_publish``) en las dos colas de
salida de la reescritura (``noticias_meta.json`` y ``noticias_web_pending.json``,
correlacionadas por ``canonical_url``/``url``). Cada canal sigue publicando a
su propio ritmo — reintentos, rate limits, recuperación ante cortes no
cambian — pero los tres miran el mismo universo de ítems elegibles.

Tres baldes por corrida:
- Local (cualquier fuente que no sea paparazzi/infobae): hasta
  ``PUBLISH_LOCAL_MAX_PER_RUN``, en el orden de prioridad editorial que ya
  existe (policiales/interior por delante de política/sociedad), mientras
  haya candidatas de esas categorías. ``PUBLISH_LOCAL_EXCLUDED_CATEGORIES``
  (default ``deportes,espectaculos``) saca categorías de relleno del balde
  local por completo — no completan aunque no haya nada más disponible.
- Paparazzi: hasta ``PUBLISH_PAPARAZZI_MAX_PER_RUN``, con video primero y
  después por el score de relevancia que ya se calcula en la reescritura
  (sin llamadas de IA nuevas).
- Infobae: hasta ``PUBLISH_INFOBAE_MAX_PER_RUN``, con video primero y
  después por intensidad de palabras de urgencia ya existentes en
  ``BREAKING_KEYWORDS`` (proxy gratuito de "fuerte/polémica", sin IA).

Si el balde local no llega a su cupo (no hay suficientes candidatas de
categorías elegibles esa corrida), la capacidad libre se reparte entre
paparazzi e infobae en vez de quedar sin usar — ver docs/DECISIONS.md.

Lo no seleccionado no se descarta: queda pendiente y vuelve a competir en el
próximo cálculo de lote (con el TTL de las colas como límite natural).
"""
from __future__ import annotations

import os
import time
import unicodedata
import uuid

from utils.editorial_priority import (
    BREAKING_KEYWORDS,
    item_category,
    item_source,
    priority_interleave,
)
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("publish_selection", "publish_selection.log")

META_PATH = str(data_dir() / "noticias_meta.json")
WEB_PATH = str(data_dir() / "noticias_web_pending.json")

PAPARAZZI_SOURCE_PREFIX = "paparazzi"
INFOBAE_SOURCE_PREFIX = "infobae"


def _local_max_per_run() -> int:
    return int(os.getenv("PUBLISH_LOCAL_MAX_PER_RUN", "6"))


def _local_excluded_categories() -> set[str]:
    raw = os.getenv("PUBLISH_LOCAL_EXCLUDED_CATEGORIES", "deportes,espectaculos")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _paparazzi_max_per_run() -> int:
    return int(os.getenv("PUBLISH_PAPARAZZI_MAX_PER_RUN", "2"))


def _infobae_max_per_run() -> int:
    return int(os.getenv("PUBLISH_INFOBAE_MAX_PER_RUN", "2"))


def _identity(item: dict) -> str:
    for field in ("canonical_url", "url"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return str(item.get("titulo") or "")


def _has_video(item: dict) -> bool:
    return bool(item.get("video_url"))


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _strength_score(item: dict) -> int:
    """Proxy gratuito (sin IA) de intensidad para ordenar el balde de
    Infobae: cuántas ``BREAKING_KEYWORDS`` aparecen en el título."""
    title = _ascii_lower(item.get("titulo") or "")
    return sum(1 for keyword in BREAKING_KEYWORDS if keyword in title)


def _is_paparazzi(item: dict) -> bool:
    return item_source(item).startswith(PAPARAZZI_SOURCE_PREFIX)


def _is_infobae(item: dict) -> bool:
    return item_source(item).startswith(INFOBAE_SOURCE_PREFIX)


def _is_local(item: dict) -> bool:
    return not _is_paparazzi(item) and not _is_infobae(item)


def _paparazzi_sort_key(item: dict):
    return (not _has_video(item), -int(item.get("paparazzi_relevance_score") or 0))


def _infobae_sort_key(item: dict):
    return (not _has_video(item), -_strength_score(item))


def select_batch(pending: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pura: separa ``pending`` en (seleccionados, resto) según los 3 baldes.

    Si el balde local no llena su cupo (no hay suficientes candidatas de
    categorías elegibles), la capacidad libre se reparte entre paparazzi e
    infobae en vez de quedar sin usar — nunca se completa el local con
    categorías de relleno (``PUBLISH_LOCAL_EXCLUDED_CATEGORIES``).
    """
    excluded = _local_excluded_categories()
    local_pool = [
        item
        for item in pending
        if isinstance(item, dict) and _is_local(item) and item_category(item) not in excluded
    ]
    paparazzi_pool = [item for item in pending if isinstance(item, dict) and _is_paparazzi(item)]
    infobae_pool = [item for item in pending if isinstance(item, dict) and _is_infobae(item)]

    local_cap = _local_max_per_run()
    local_selected = priority_interleave(local_pool)[:local_cap]
    shortfall = max(0, local_cap - len(local_selected))

    paparazzi_cap = _paparazzi_max_per_run() + (shortfall + 1) // 2
    infobae_cap = _infobae_max_per_run() + shortfall // 2

    paparazzi_selected = sorted(paparazzi_pool, key=_paparazzi_sort_key)[:paparazzi_cap]
    # Lo que paparazzi no pudo usar de su extra (poca disponibilidad) pasa a infobae.
    unused_paparazzi_extra = paparazzi_cap - len(paparazzi_selected)
    if unused_paparazzi_extra > 0:
        infobae_cap += unused_paparazzi_extra
    infobae_selected = sorted(infobae_pool, key=_infobae_sort_key)[:infobae_cap]

    selected = local_selected + paparazzi_selected + infobae_selected
    selected_identities = {_identity(item) for item in selected}
    rest = [item for item in pending if _identity(item) not in selected_identities]
    return selected, rest


def _bucket_name(item: dict) -> str:
    if _is_paparazzi(item):
        return "paparazzi"
    if _is_infobae(item):
        return "infobae"
    return "local"


def compute_next_batch() -> dict:
    """I/O: calcula el próximo lote y lo marca (``selected_for_publish``) en
    ambas colas de salida de la reescritura, por identidad compartida
    (``canonical_url``/``url``) — Web, Facebook e Instagram terminan
    publicando exactamente el mismo lote.

    El pool de candidatas sale de ``noticias_meta.json`` (tiene los campos
    ricos que necesitan los baldes: video, score, categoría) pero filtrado a
    ítems que todavía pueden llegar a tener ``web_url`` real: ya lo tienen
    (publicados a Web antes), o siguen vivos en ``noticias_web_pending.json``
    (van a publicarse ahí este ciclo o uno próximo). ``noticias_meta.json``
    es un histórico que crece y se poda por su propio TTL, independiente del
    de la cola web — sin este filtro, se seleccionaban notas cuya entrada en
    la cola web ya había expirado, que nunca iban a conseguir `web_url` y
    por lo tanto nunca se publicaban en ningún canal (ver docs/DECISIONS.md).
    """
    meta_items = load_json(META_PATH, [], expected_type=list)
    web_items = load_json(WEB_PATH, [], expected_type=list)
    web_identities = {_identity(item) for item in web_items if isinstance(item, dict)}

    pending = [
        item
        for item in meta_items
        if isinstance(item, dict)
        and not item.get("selected_for_publish")
        and (bool(item.get("web_url")) or _identity(item) in web_identities)
    ]
    selected, _rest = select_batch(pending)

    counts = {"local": 0, "paparazzi": 0, "infobae": 0}
    for item in selected:
        counts[_bucket_name(item)] += 1

    if not selected:
        return {"batch_id": None, "selected": 0, **counts}

    batch_id = uuid.uuid4().hex
    now = int(time.time())
    selected_identities = {_identity(item) for item in selected}

    def stamp(path: str):
        def mutate(queue):
            for item in queue:
                if isinstance(item, dict) and _identity(item) in selected_identities:
                    item["selected_for_publish"] = True
                    item["publish_batch_id"] = batch_id
                    item["publish_batch_at"] = now
                    item["publish_bucket"] = _bucket_name(item)
            return queue

        update_json(path, mutate, [], expected_type=list)

    stamp(META_PATH)
    stamp(WEB_PATH)

    logger.info(
        "Lote de publicación %s: local=%s paparazzi=%s infobae=%s",
        batch_id,
        counts["local"],
        counts["paparazzi"],
        counts["infobae"],
    )
    return {"batch_id": batch_id, "selected": len(selected), **counts}
