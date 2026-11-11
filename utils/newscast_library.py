"""Biblioteca de notas propias recientes para formatos de video.

Guarda, por nota publicada en lavozriojana.com, lo que ya se procesó una vez
para no volver a pedirlo: título y cuerpo de NUESTRA nota, sección, fuente,
localidades, la foto ya procesada que publicó la web (se reutiliza la copia de
``output/web_media`` si existe; si no, se descarga una vez), el video de la
nota (se prepara una vez, a pedido) y los controles visuales por hash de
imagen. Hoy la usa el Noticiero (policiales); la sección política queda
registrada para una próxima integración.

Estado: ``data/newscast_library.json`` (entradas por clave estable de la
URL, escritas con ``update_json``). Medios: ``output/newscast_library/<clave>/``.
Retención: ``NEWSCAST_LIBRARY_RETENTION_HOURS`` (72 h); se borran entradas y
archivos vencidos.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time

from PIL import Image

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir

logger = setup_logger("newscast_library", "nightly_newscast.log")

LOCAL_SOURCES = ("nuevarioja", "tiempopopular", "fenix", "mediosrioja", "judicial_")
KINDS = ("policiales", "politica")
# Sucesos que el clasificador pone en sociedad/interior (incendios, choques,
# rescates) también son materia del noticiero policial.
POLICE_RE = re.compile(
    r"detenid|detuv|aprehend|robo|robaron|hurto|allana|choque|colisi|accidente|siniestro|vuelco|volc[oó]|incendio|fuego|"
    r"herid|lesion|falleci|muri[oó]|muerte|homicid|femicid|polic[ií]a|bombero|rescat|operativo|secuestr|droga|estupefac|"
    r"estafa|imputad|procesad|juicio|condena|fiscal|prisi[oó]n|denunci|desaparec|b[uú]squeda|violencia|arma|disparo|"
    r"baleado|tiroteo|motociclista|ca[ií]da|derrumbe|evacua",
)
NOT_POLICE_RE = re.compile(r"jubilad|subsecretari|ministr|diputad|senador|gobernador|presupuesto|elecci")


def library_path() -> str:
    return str(data_dir() / "newscast_library.json")


def media_root() -> str:
    return str(output_dir() / "newscast_library")


def key_for(web_url: str) -> str:
    return hashlib.sha1(web_url.encode("utf-8")).hexdigest()[:16]


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def classify(source: str, category: str, title: str) -> tuple[str, str]:
    """(tipo, motivo). tipo: policiales | politica | "" (no se guarda)."""
    if not str(source).startswith(LOCAL_SOURCES):
        return "", "fuente no riojana"
    category = (category or "").lower()
    folded = _fold(title)
    if category == "policiales" or str(source).startswith("judicial_"):
        return "policiales", "sección policiales/judicial"
    if category == "politica":
        return "politica", "sección política"
    if category in ("sociedad", "interior", "salud", "educacion") and POLICE_RE.search(folded) and not NOT_POLICE_RE.search(folded):
        return "policiales", f"suceso en {category} (palabra clave policial en el título)"
    return "", f"sección {category or 'sin clasificar'} sin palabra clave policial"


def _local_processed(photo_url: str) -> str:
    """La web guarda la foto procesada en output/web_media/<hash>.webp."""
    name = os.path.basename(photo_url.split("?")[0])
    path = str(output_dir() / "web_media" / name)
    return path if name and os.path.isfile(path) else ""


def store_photo(photo_url: str, dest: str, *, download=None) -> tuple[int, int] | None:
    """Foto procesada de la nota → JPEG local (máx. 2000 px)."""
    src = _local_processed(photo_url)
    temp = ""
    if not src:
        if download is None:
            from utils.story_publisher import download_image as download
        temp = download(photo_url) or ""
        src = temp
    if not src:
        return None
    try:
        with Image.open(src) as image:
            image = image.convert("RGB")
            image.thumbnail((2000, 2000))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            image.save(dest, "JPEG", quality=92)
            return image.size
    except OSError as exc:
        logger.warning("Foto de la nota ilegible: %s", type(exc).__name__)
        return None
    finally:
        if temp:
            try:
                os.unlink(temp)
            except OSError:
                pass


def refresh(*, now: float | None = None, hours: int | None = None, fetch=None, download=None, archive_info=None, video_index=None) -> dict:
    """Agrega a la biblioteca las notas recientes de policiales y política que
    falten y borra las vencidas. Devuelve un reporte (consideradas, nuevas,
    excluidas con motivo). No falla por una nota: la saltea con su motivo."""
    from utils import nightly_newscast as nn

    now = now or time.time()
    hours = hours or int(os.getenv("NEWSCAST_LIBRARY_WINDOW_HOURS", "36"))
    retention = int(os.getenv("NEWSCAST_LIBRARY_RETENTION_HOURS", "72")) * 3600
    fetch = fetch or nn.fetch_article_full
    try:
        records = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
        library = load_json(library_path(), {}, expected_type=dict)
    except JsonStateError as exc:
        logger.warning("Biblioteca: estado ilegible: %s", exc)
        return {"error": str(exc)}
    fresh = [r for r in records if isinstance(r, dict) and r.get("web_url") and 0 <= now - float(r.get("published_at_ts") or 0) <= hours * 3600]
    info = (archive_info or nn._archive_info)([r["web_url"] for r in fresh])
    videos = (video_index or nn._video_index)()
    report = {"considered": len(fresh), "added": 0, "kept": 0, "excluded": []}
    additions: dict[str, dict] = {}
    for r in fresh:
        url = r["web_url"]
        meta = info.get(url, {})
        kind, reason = classify(str(r.get("source") or ""), meta.get("category", ""), str(r.get("titulo") or ""))
        if not kind:
            report["excluded"].append({"titulo": r.get("titulo"), "source": r.get("source"), "motivo": reason})
            continue
        key = key_for(url)
        if key in library and library[key].get("body"):
            report["kept"] += 1
            continue
        article = fetch(url)
        if not article or not article.get("title") or not article.get("body"):
            report["excluded"].append({"titulo": r.get("titulo"), "source": r.get("source"), "motivo": "no se pudo leer la nota publicada"})
            continue
        video = ""
        for k in (r.get("canonical_url"), r.get("url")):
            if k and k in videos:
                video = videos[k]
                break
        photo = {}
        if article.get("photo_url"):
            dest = os.path.join(media_root(), key, "photo.jpg")
            size = store_photo(article["photo_url"], dest, download=download)
            if size:
                photo = {"path": dest, "url": article["photo_url"], "width": size[0], "height": size[1]}
        additions[key] = {
            "key": key, "kind": kind, "reason": reason, "web_url": url, "title": article["title"], "body": article["body"],
            "section": meta.get("category", ""), "source": str(r.get("source") or ""), "published_at": float(r.get("published_at_ts") or 0),
            "localities": meta.get("localities", []), "photo": photo, "video_url": video, "video": {}, "checks": {}, "stored_at": now,
        }
        report["added"] += 1
    expired: list[str] = []

    def mutate(state):
        for key, entry in additions.items():
            previous = state.get(key) or {}
            state[key] = {**entry, "checks": previous.get("checks") or {}, "video": previous.get("video") or {}}
        for key in [k for k, v in state.items() if now - float(v.get("published_at") or 0) > retention]:
            expired.append(key)
            state.pop(key, None)
        return state

    update_json(library_path(), mutate, {}, expected_type=dict)
    for key in expired:
        shutil.rmtree(os.path.join(media_root(), key), ignore_errors=True)
    report["expired"] = len(expired)
    logger.info("Biblioteca: %d consideradas, %d nuevas, %d ya estaban, %d vencidas", report["considered"], report["added"], report["kept"], len(expired))
    return report


def entries(kind: str, *, now: float | None = None, hours: int = 24) -> list[dict]:
    """Entradas de un tipo dentro de la ventana, más recientes primero."""
    now = now or time.time()
    library = load_json(library_path(), {}, expected_type=dict)
    out = [e for e in library.values() if e.get("kind") == kind and 0 <= now - float(e.get("published_at") or 0) <= hours * 3600]
    return sorted(out, key=lambda e: -float(e.get("published_at") or 0))


def remember(key: str, *, check: tuple[str, dict] | None = None, video: dict | None = None) -> None:
    """Guarda un control visual (por hash de imagen) o el video preparado."""

    def mutate(state):
        entry = state.get(key)
        if entry is None:
            return state
        if check:
            entry.setdefault("checks", {})[check[0]] = check[1]
        if video:
            entry["video"] = video
        return state

    update_json(library_path(), mutate, {}, expected_type=dict)
