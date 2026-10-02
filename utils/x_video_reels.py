"""Videos de X enviados desde el backend de HolaSalta, publicados como Reel.

El backend anota cada link de X que manda a procesar en un JSON de intercambio
(``C:\\sources\\x_video_sources.json``, más nuevo primero, máximo 100). Este
módulo lo lee en sólo lectura, toma los ``job_id`` nuevos (deduplicando también
por URL) y los publica con el mismo motor de reels que el resto de los videos
(``utils.paparazzi_reels.render_reel_item``: descarga con yt-dlp, EditorialReel,
R2 temporal, Reel en Instagram y Facebook).

Flujo propio y separado: estado en ``data/x_video_reels.json``, sin tocar las
colas web/meta/social. Comparte con el resto sólo el backoff de rate limit de
Meta (misma cuenta). Nunca escribe ni borra el archivo del backend.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.url_normalization import url_hash

logger = setup_logger("x_video_reels", "x_video_reels.log")

STATE_PATH = str(data_dir() / "x_video_reels.json")
_TERMINAL = {"completed", "skipped", "dead_letter"}
_X_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"}


def feed_path() -> Path:
    explicit = str(os.getenv("X_VIDEO_FEED_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    exchange = str(os.getenv("HOLASALTA_EXCHANGE_DIR") or r"C:\sources").strip()
    return Path(exchange) / "x_video_sources.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def read_feed() -> tuple[list[dict], str | None]:
    """Lee el archivo del backend de una vez y lo suelta. Nunca lo modifica.

    Ausente o ilegible no es un error: el backend lo crea con el primer video y
    lo reemplaza de forma atómica, así que se reintenta en el próximo ciclo.
    """
    path = feed_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], "feed_missing"
    except OSError as exc:
        return [], f"feed_unreadable:{type(exc).__name__}"
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "feed_invalid_json"
    if not isinstance(data, list):
        return [], "feed_not_a_list"
    items = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        job_id = str(entry.get("job_id") or "").strip()
        url = str(entry.get("url") or "").strip()
        if job_id and _is_x_status_url(url):
            items.append({"job_id": job_id, "url": url, "created_at": str(entry.get("created_at") or "")})
    return items, None


def _is_x_status_url(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.lower() in _X_HOSTS and "/status/" in parsed.path


def _url_key(url: str) -> str:
    match = re.search(r"/status/(\d+)", url)
    return f"x:{match.group(1)}" if match else f"link:{url_hash(url)}"


def _created_ts(created_at: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def ingest(feed_items: list[dict], *, now: float | None = None) -> dict[str, int]:
    """Registra los job_id nuevos. Viejos o URL repetida quedan ``skipped``."""
    current = int(time.time() if now is None else now)
    max_age = _env_int("X_VIDEO_MAX_AGE_HOURS", 24) * 3600
    counts = {"new": 0, "skipped_old": 0, "skipped_duplicate_url": 0}

    def mutate(state):
        jobs = state.setdefault("jobs", {})
        known_urls = {job.get("url_key") for job in jobs.values() if job.get("status") != "skipped"}
        # Del más viejo al más nuevo, como recomienda el manual del backend.
        for entry in reversed(feed_items):
            if entry["job_id"] in jobs:
                continue
            url_key = _url_key(entry["url"])
            created = _created_ts(entry["created_at"])
            record = {
                "url": entry["url"],
                "url_key": url_key,
                "created_at": entry["created_at"],
                "seen_at": current,
                "updated_at": current,
                "attempts": 0,
            }
            if url_key in known_urls:
                record.update(status="skipped", reason="duplicate_url")
                counts["skipped_duplicate_url"] += 1
            elif created is not None and created < current - max_age:
                record.update(status="skipped", reason="older_than_max_age")
                counts["skipped_old"] += 1
            else:
                record.update(status="pending")
                known_urls.add(url_key)
                counts["new"] += 1
            jobs[entry["job_id"]] = record
        return state

    update_json(STATE_PATH, mutate, {"jobs": {}}, expected_type=dict)
    return counts


def _transition(job_id: str, **fields) -> None:
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


def pending_jobs(limit: int) -> list[tuple[str, dict]]:
    state = load_json(STATE_PATH, {"jobs": {}}, expected_type=dict)
    pending = [(job_id, job) for job_id, job in state.get("jobs", {}).items() if job.get("status") == "pending"]
    pending.sort(key=lambda pair: (pair[1].get("created_at") or "", pair[1].get("seen_at") or 0))
    return pending[: max(0, limit)]


def _clean_tweet_text(text: str) -> str:
    text = re.sub(r"https?://t\.co/\S+", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_x_metadata(url: str) -> dict:
    """Texto del post vía yt-dlp (sin descargar el video). Vacío si falla."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings", "--ignore-config", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_env_int("YTDLP_TIMEOUT_SECONDS", 180),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("No se pudo leer el texto del post de X: %s", type(exc).__name__)
        return {}
    if result.returncode != 0:
        logger.warning("yt-dlp no devolvió metadatos del post de X (code %s)", result.returncode)
        return {}
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return {}
    return {
        "text": _clean_tweet_text(str(data.get("description") or data.get("title") or "")),
        "uploader": str(data.get("uploader") or data.get("uploader_id") or ""),
    }


def build_news_item(job: dict, metadata: dict) -> dict | None:
    """Noticia mínima para el motor de reels, con caption del mismo generador.

    Una sola llamada a IA (la del caption, igual que cualquier otra noticia);
    la sección es fija por configuración para no sumar la del clasificador.
    """
    text = str(metadata.get("text") or "").strip()
    if not text:
        return None
    from openIA.caption_generator import generate_caption

    seccion = str(os.getenv("X_VIDEO_DEFAULT_SECTION") or "sociedad").strip().lower()
    titulo = text if len(text) <= 120 else text[:117].rsplit(" ", 1)[0] + "..."
    noticia = {"titulo": titulo, "parrafos": [text], "seccion": seccion}
    noticia.update(generate_caption(noticia))
    noticia.update({"source_url": job["url"], "canonical_url": job["url"], "source": "x_video"})
    return noticia
