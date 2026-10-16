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

Filtros editoriales (apagados por defecto, ver docs/DECISIONS.md 2026-10-16):
- ``PAPARAZZI_VIDEO_ONLY_ENABLED`` / ``INFOBAE_VIDEO_ONLY_ENABLED``: la nota con
  video de esa fuente no sale en redes como imagen ni con link; se publica sólo
  el Reel desde ``meta/run_paparazzi_videos.py`` (fuera de todo cupo). La de
  Infobae tampoco genera artículo Web.
- ``PUBLISH_PAPARAZZI_MIN_SCORE``: paparazzi sin video sale en redes sólo con
  ``paparazzi_relevance_score`` >= umbral (sin puntaje por falla de IA: pasa,
  pero al final de la fila).
- ``PUBLISH_PAPARAZZI_WEB_ALL``: todas las notas de paparazzi van a la Web, sin
  cupo (con video o con relevancia baja incluidas). Las que no corresponden a
  redes quedan marcadas con ``social_skip_reason`` (``policy_*``) y Facebook e
  Instagram no las encolan; el cupo de paparazzi pasa a ser sólo el de redes.
- ``PUBLISH_INTERNATIONAL_BUCKET_ENABLED``: las internacionales dejan de
  competir como locales y tienen su balde propio
  (``PUBLISH_INTERNATIONAL_MAX_PER_RUN``), sólo con
  ``international_impact_score`` >= ``PUBLISH_INTERNATIONAL_MIN_SCORE``.

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
INTERNATIONAL_SOURCE_MARKER = "internacional"

_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def _flag(name: str) -> bool:
    return str(os.getenv(name, "false")).strip().lower() in _TRUE


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _local_max_per_run() -> int:
    return int(os.getenv("PUBLISH_LOCAL_MAX_PER_RUN", "6"))


def _local_excluded_categories() -> set[str]:
    raw = os.getenv("PUBLISH_LOCAL_EXCLUDED_CATEGORIES", "deportes,espectaculos")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _paparazzi_max_per_run() -> int:
    return int(os.getenv("PUBLISH_PAPARAZZI_MAX_PER_RUN", "2"))


def _infobae_max_per_run() -> int:
    return int(os.getenv("PUBLISH_INFOBAE_MAX_PER_RUN", "2"))


def paparazzi_video_only_enabled() -> bool:
    return _flag("PAPARAZZI_VIDEO_ONLY_ENABLED")


def infobae_video_only_enabled() -> bool:
    return _flag("INFOBAE_VIDEO_ONLY_ENABLED")


def video_reels_enabled() -> bool:
    """Alguna fuente publica sus notas con video sólo como Reel."""
    return paparazzi_video_only_enabled() or infobae_video_only_enabled()


def _paparazzi_web_all_enabled() -> bool:
    return _flag("PUBLISH_PAPARAZZI_WEB_ALL")


def _paparazzi_min_score() -> int:
    return _env_int("PUBLISH_PAPARAZZI_MIN_SCORE", 0)


def _international_bucket_enabled() -> bool:
    return _flag("PUBLISH_INTERNATIONAL_BUCKET_ENABLED")


def _international_max_per_run() -> int:
    return _env_int("PUBLISH_INTERNATIONAL_MAX_PER_RUN", 1)


def _international_min_score() -> int:
    return _env_int("PUBLISH_INTERNATIONAL_MIN_SCORE", 8)


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


def is_international(item: dict) -> bool:
    return INTERNATIONAL_SOURCE_MARKER in item_source(item)


def is_video_only_paparazzi(item: dict) -> bool:
    """Nota de paparazzi con video que en redes sale sólo como Reel (flag activo)."""
    return paparazzi_video_only_enabled() and _is_paparazzi(item) and _has_video(item)


def is_video_only_infobae(item: dict) -> bool:
    """Nota de Infobae con video que sale sólo como Reel, sin Web (flag activo)."""
    return infobae_video_only_enabled() and _is_infobae(item) and _has_video(item)


def is_reel_only_item(item: dict) -> bool:
    """Nota con video que en redes se publica sólo como Reel EditorialReel."""
    return is_video_only_paparazzi(item) or is_video_only_infobae(item)


def _is_international_bucket(item: dict) -> bool:
    return _international_bucket_enabled() and is_international(item)


def _is_local(item: dict) -> bool:
    return not _is_paparazzi(item) and not _is_infobae(item) and not _is_international_bucket(item)


def _score(item: dict, field: str) -> int | None:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _paparazzi_eligible(item: dict) -> bool:
    if is_video_only_paparazzi(item):
        return False
    score = _score(item, "paparazzi_relevance_score")
    # Sin puntaje (falla de IA) no se pierde la nota: pasa, al final de la fila.
    return score is None or score >= _paparazzi_min_score()


def _international_eligible(item: dict) -> bool:
    # Sólo alto impacto: sin puntaje no hay evidencia de impacto, no entra.
    score = _score(item, "international_impact_score")
    return score is not None and score >= _international_min_score()


def _paparazzi_sort_key(item: dict):
    score = _score(item, "paparazzi_relevance_score")
    return (not _has_video(item), score is None, -(score or 0))


def _international_sort_key(item: dict):
    return -(_score(item, "international_impact_score") or 0)


def _infobae_sort_key(item: dict):
    return (not _has_video(item), -_strength_score(item))


SOCIAL_SKIP_VIDEO = "policy_video_reel_only"
SOCIAL_SKIP_LOW_RELEVANCE = "policy_paparazzi_low_relevance"
SOCIAL_SKIP_SOCIAL_CAP = "policy_paparazzi_social_cap"


def select_batch(pending: list[dict]) -> tuple[list[dict], list[dict]]:
    selected, rest, _web_only = select_batch_detailed(pending)
    return selected, rest


def select_batch_detailed(pending: list[dict]) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Pura: separa ``pending`` en (seleccionados, resto, sólo Web) según los baldes.

    ``sólo Web`` mapea identidad -> motivo ``policy_*`` de las seleccionadas que
    van a la Web pero no a Facebook/Instagram (``PUBLISH_PAPARAZZI_WEB_ALL``).

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
    paparazzi_all = [item for item in pending if isinstance(item, dict) and _is_paparazzi(item)]
    paparazzi_pool = [item for item in paparazzi_all if _paparazzi_eligible(item)]
    # Infobae con video sale sólo como Reel (run_paparazzi_videos), nunca en el lote.
    infobae_pool = [
        item
        for item in pending
        if isinstance(item, dict) and _is_infobae(item) and not is_video_only_infobae(item)
    ]
    international_pool = [
        item
        for item in pending
        if isinstance(item, dict) and _is_international_bucket(item) and _international_eligible(item)
    ]

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
    # Balde propio sin heredar sobrante del local: sólo alto impacto, cupo fijo.
    international_selected = sorted(international_pool, key=_international_sort_key)[
        : max(0, _international_max_per_run())
    ]

    web_only: dict[str, str] = {}
    if _paparazzi_web_all_enabled():
        # Web publica todas las de paparazzi, sin cupo; el cupo queda sólo para redes.
        social_identities = {_identity(item) for item in paparazzi_selected}
        eligible_identities = {_identity(item) for item in paparazzi_pool}
        for item in paparazzi_all:
            identity = _identity(item)
            if identity in social_identities:
                continue
            paparazzi_selected.append(item)
            if is_video_only_paparazzi(item):
                web_only[identity] = SOCIAL_SKIP_VIDEO
            elif identity in eligible_identities:
                web_only[identity] = SOCIAL_SKIP_SOCIAL_CAP
            else:
                web_only[identity] = SOCIAL_SKIP_LOW_RELEVANCE

    selected = local_selected + paparazzi_selected + infobae_selected + international_selected
    selected_identities = {_identity(item) for item in selected}
    rest = [item for item in pending if _identity(item) not in selected_identities]
    return selected, rest, web_only


def _bucket_name(item: dict) -> str:
    if _is_paparazzi(item):
        return "paparazzi"
    if _is_infobae(item):
        return "infobae"
    if _is_international_bucket(item):
        return "internacional"
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
    selected, _rest, web_only = select_batch_detailed(pending)

    counts = {"local": 0, "paparazzi": 0, "infobae": 0, "internacional": 0}
    for item in selected:
        counts[_bucket_name(item)] += 1

    if not selected:
        return {"batch_id": None, "selected": 0, "web_only": 0, **counts}

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
                    reason = web_only.get(_identity(item))
                    if reason:
                        item["social_skip_reason"] = reason
            return queue

        update_json(path, mutate, [], expected_type=list)

    stamp(META_PATH)
    stamp(WEB_PATH)

    logger.info(
        "Lote de publicación %s: local=%s paparazzi=%s infobae=%s internacional=%s (sólo Web: %s)",
        batch_id,
        counts["local"],
        counts["paparazzi"],
        counts["infobae"],
        counts["internacional"],
        len(web_only),
    )
    return {"batch_id": batch_id, "selected": len(selected), "web_only": len(web_only), **counts}
