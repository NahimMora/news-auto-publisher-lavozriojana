"""Notas con video (paparazzi, Infobae, locales) publicadas en redes como Reel.

Con ``PAPARAZZI_VIDEO_ONLY_ENABLED`` / ``INFOBAE_VIDEO_ONLY_ENABLED`` la nota
que trae video no sale en Facebook ni Instagram como imagen ni con link (ver
``utils/publish_selection.py``; la de paparazzi sí va a la Web con
``PUBLISH_PAPARAZZI_WEB_ALL``). Este módulo la toma de ``noticias_meta.json``
(sólo lectura) y la registra como job propio en
``data/paparazzi_video_jobs.json``; ``meta/run_paparazzi_videos.py`` la
publica como Reel EditorialReel en Instagram y Facebook, sin puntaje editorial
y fuera de todo cupo del lote.

Las locales de policiales/interior con YouTube incrustado
(``is_local_video_reel_item``) van como Reel sólo a Instagram: Facebook sigue
con su post con link. ``run_ig`` no las publica como imagen mientras se espere
el Reel (``local_reel_expected``) y las retoma si el Reel falla o vence.

Flujo propio y separado (mismo patrón que ``utils/x_video_reels.py``): sólo
comparte con el resto el backoff de rate limit de Meta y el dedup de reels
(``data/paparazzi_reels_posted.json``), para no publicar dos veces la misma nota.
"""
from __future__ import annotations

import os
import time

from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.paparazzi_reels import reel_dedup_key
from utils.paths import data_dir
from utils.publish_selection import is_local_video_reel_item, is_reel_only_item, local_video_reel_enabled
from utils.social_queue import bootstrap_not_before

logger = setup_logger("paparazzi_video_jobs", "paparazzi_video_jobs.log")

STATE_PATH = str(data_dir() / "paparazzi_video_jobs.json")
META_INPUT = str(data_dir() / "noticias_meta.json")
REELS_POSTED_PATH = str(data_dir() / "paparazzi_reels_posted.json")

# Campos de la nota que necesita el render/publicación del Reel.
_SNAPSHOT_FIELDS = (
    "titulo",
    "titulo_instagram",
    "texto_instagram",
    "caption",
    "seccion",
    "source",
    "url",
    "canonical_url",
    "dedup_key",
    "imagen_url",
    "video_url",
    "video_duration_seconds",
    "paparazzi_relevance_score",
    "reel_channels",
    "video_credit",
)

_GIVEN_UP = {"dead_letter", "expired"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _queued_at(noticia: dict) -> int | None:
    value = noticia.get("queued_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _cutoff(current: int) -> int:
    return max(bootstrap_not_before(), current - _env_int("PAPARAZZI_VIDEO_MAX_AGE_HOURS", 24) * 3600)


def _local_reel_fields(noticia: dict) -> dict:
    """Reel local: el YouTube incrustado como fuente, sólo Instagram y con crédito."""
    fields: dict = {"video_url": str(noticia["video_embed_url"]).strip(), "reel_channels": ["instagram"]}
    author = str(noticia.get("video_embed_author") or "").strip()
    if author:
        fields["video_credit"] = author
        caption = str(noticia.get("texto_instagram") or "").rstrip()
        if caption:
            fields["texto_instagram"] = f"{caption}\n\n🎥 Video: {author}"
    return fields


def local_reel_expected(*, now: float | None = None):
    """Devuelve ``expected(noticia)``: True si esa nota local va a salir como Reel.

    Lo usa ``run_ig`` (que corre antes que esta etapa) para no publicar la misma
    nota también como imagen. False si el Reel ya falló o venció, o si la nota es
    demasiado vieja para entrar como job: en ese caso sale como imagen.
    """
    if not local_video_reel_enabled():
        return lambda _noticia: False
    current = int(time.time() if now is None else now)
    cutoff = _cutoff(current)
    jobs = load_json(STATE_PATH, {"jobs": {}}, expected_type=dict).get("jobs") or {}

    def expected(noticia: dict) -> bool:
        if not is_local_video_reel_item(noticia):
            return False
        job = jobs.get(reel_dedup_key(noticia))
        if job is not None:
            return job.get("status") not in _GIVEN_UP
        queued = _queued_at(noticia)
        return queued is not None and queued >= cutoff

    return expected


def ingest(*, now: float | None = None) -> dict[str, int]:
    """Registra como ``pending`` las notas con video recientes (sólo Reel).

    Sólo entran notas encoladas después del corte operativo
    (``SOCIAL_BOOTSTRAP_NOT_BEFORE_TS``) y dentro de
    ``PAPARAZZI_VIDEO_MAX_AGE_HOURS`` (default 24): nunca se publica un video viejo.
    """
    current = int(time.time() if now is None else now)
    cutoff = _cutoff(current)
    noticias = load_json(META_INPUT, [], expected_type=list)
    posted = load_json(REELS_POSTED_PATH, {"posted": {}}, expected_type=dict).get("posted") or {}

    candidates: list[tuple[str, dict]] = []
    for noticia in noticias:
        if not isinstance(noticia, dict):
            continue
        local = is_local_video_reel_item(noticia)
        if not local and not is_reel_only_item(noticia):
            continue
        queued = _queued_at(noticia)
        if queued is None or queued < cutoff:
            continue
        key = reel_dedup_key(noticia)
        if key in posted:
            continue
        snapshot = {field: noticia[field] for field in _SNAPSHOT_FIELDS if noticia.get(field) not in (None, "")}
        if local:
            snapshot.update(_local_reel_fields(noticia))
        candidates.append((key, {"noticia": snapshot, "queued_at": queued}))

    counts = {"new": 0}
    if not candidates:
        return counts

    def mutate(state):
        jobs = state.setdefault("jobs", {})
        for key, payload in candidates:
            if key in jobs:
                continue
            jobs[key] = {
                **payload,
                "status": "pending",
                "attempts": 0,
                "seen_at": current,
                "updated_at": current,
            }
            counts["new"] += 1
        return state

    update_json(STATE_PATH, mutate, {"jobs": {}}, expected_type=dict)
    if counts["new"]:
        logger.info("Notas con video registradas para Reel: %s", counts["new"])
    return counts


def transition(job_id: str, **fields) -> None:
    def mutate(state):
        job = state.setdefault("jobs", {}).get(job_id)
        if job is not None:
            job.update(fields)
            job["updated_at"] = int(time.time())
        return state

    update_json(STATE_PATH, mutate, {"jobs": {}}, expected_type=dict)


def recover_interrupted() -> int:
    """Un ``processing`` heredado pudo haberse publicado: no se reintenta a ciegas."""
    recovered = {"count": 0}

    def mutate(state):
        for job in state.setdefault("jobs", {}).values():
            if job.get("status") == "processing":
                job.update(status="dead_letter", reason="ambiguous_after_restart_requires_review")
                job["updated_at"] = int(time.time())
                recovered["count"] += 1
        return state

    update_json(STATE_PATH, mutate, {"jobs": {}}, expected_type=dict)
    return recovered["count"]


def expire_stale(*, now: float | None = None) -> int:
    """Un pendiente que superó la antigüedad máxima no se publica más tarde."""
    current = int(time.time() if now is None else now)
    cutoff = current - _env_int("PAPARAZZI_VIDEO_MAX_AGE_HOURS", 24) * 3600
    expired = {"count": 0}

    def mutate(state):
        for job in state.setdefault("jobs", {}).values():
            if job.get("status") == "pending" and int(job.get("queued_at") or 0) < cutoff:
                job.update(status="expired", reason="older_than_max_age", updated_at=current)
                expired["count"] += 1
        return state

    update_json(STATE_PATH, mutate, {"jobs": {}}, expected_type=dict)
    return expired["count"]


def pending_jobs(limit: int) -> list[tuple[str, dict]]:
    """Pendientes del más viejo al más nuevo (``limit`` <= 0: todos)."""
    state = load_json(STATE_PATH, {"jobs": {}}, expected_type=dict)
    pending = [(job_id, job) for job_id, job in state.get("jobs", {}).items() if job.get("status") == "pending"]
    pending.sort(key=lambda pair: (int(pair[1].get("queued_at") or 0), pair[0]))
    return pending[:limit] if limit > 0 else pending
