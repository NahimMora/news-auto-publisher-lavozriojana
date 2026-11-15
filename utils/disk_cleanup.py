"""Limpieza automática de copias de trabajo que nada borraba (2026-11-15).

El 15/11 el disco C: llegó a 0,5 GB libres y Remotion falló con ENOSPC. Lo que
crecía sin control eran copias de trabajo, no estado:

* ``output/web_media/*.mp4``: el publicador web baja el video de cada nota y
  nunca lo borraba (19 GB en tres meses). Las fotos de esa carpeta las reusa
  el noticiero (sólo las de las últimas 72 h).
* ``output/renders``: videos de paparazzi y X ya armados y publicados.
* ``remotion/public/tmp``: restos de renders que fallaron; Remotion además
  copia TODA la carpeta ``public`` en cada render, así que también lo hacía
  más lento. Lo mismo en la copia del render server (``.render-cache``) y en
  los bundles que la CLI deja en ``%TEMP%``.

Sólo se borra por antigüedad (días configurables), sin seguir enlaces y sólo
dentro de esas carpetas. Nunca toca ``data/``, ``logs/`` ni ``FotosLVR/``. Un
archivo en uso se saltea (se intenta en el próximo ciclo).

Interruptor: ``DISK_CLEANUP_ENABLED`` (apagado por defecto). Días:
``DISK_CLEANUP_WEB_MEDIA_VIDEO_DAYS`` (7), ``DISK_CLEANUP_WEB_MEDIA_PHOTO_DAYS``
(30), ``DISK_CLEANUP_RENDERS_DAYS`` (14), ``DISK_CLEANUP_REMOTION_TMP_DAYS`` (7),
``DISK_CLEANUP_BUNDLE_DAYS`` (2).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from utils.logging_setup import setup_logger
from utils.paths import output_dir

logger = setup_logger("disk_cleanup", "disk_cleanup.log")

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_NAMES = {"newscast_cache"}  # caché del noticiero: tiene su propia retención


@dataclass
class Rule:
    name: str
    root: str
    days: float
    suffixes: tuple[str, ...] = ()   # vacío = cualquier archivo
    prefix: str = ""                 # sólo entradas que empiezan así (bundles de %TEMP%)
    dirs: bool = False               # también carpetas de primer nivel (por su archivo más nuevo)


@dataclass
class Report:
    deleted: dict[str, int] = field(default_factory=dict)
    freed_bytes: int = 0
    in_use: int = 0

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def _days(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def default_rules() -> list[Rule]:
    out = str(output_dir())
    remotion = os.path.join(REPO_DIR, "remotion")
    tmp = os.path.join(remotion, "public", "tmp")
    return [
        Rule("web_media_videos", os.path.join(out, "web_media"), _days("DISK_CLEANUP_WEB_MEDIA_VIDEO_DAYS", 7), (".mp4", ".part")),
        Rule("web_media_fotos", os.path.join(out, "web_media"), _days("DISK_CLEANUP_WEB_MEDIA_PHOTO_DAYS", 30), (".jpg", ".jpeg", ".webp", ".png")),
        Rule("renders", os.path.join(out, "renders"), _days("DISK_CLEANUP_RENDERS_DAYS", 14)),
        Rule("remotion_tmp", tmp, _days("DISK_CLEANUP_REMOTION_TMP_DAYS", 7), dirs=True),
        Rule("render_cache_tmp", os.path.join(remotion, ".render-cache", "public", "tmp"), _days("DISK_CLEANUP_REMOTION_TMP_DAYS", 7), dirs=True),
        Rule("bundles_temp", tempfile.gettempdir(), _days("DISK_CLEANUP_BUNDLE_DAYS", 2), prefix="remotion-webpack-bundle-", dirs=True),
    ]


def _newest_mtime(path: str) -> float:
    """Fecha del archivo más nuevo adentro (la de la carpeta cambia al crear cosas; vacía = la de la carpeta)."""
    newest = 0.0
    for base, dirnames, files in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(base, d))]
        for name in files:
            try:
                newest = max(newest, os.lstat(os.path.join(base, name)).st_mtime)
            except OSError:
                continue
    return newest or os.lstat(path).st_mtime


def _size(path: str) -> int:
    if not os.path.isdir(path):
        return os.lstat(path).st_size
    total = 0
    for base, dirnames, files in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(base, d))]
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                continue
    return total


def cleanup(rules: list[Rule] | None = None, *, now: float | None = None) -> Report:
    now = now or time.time()
    report = Report()
    for rule in rules if rules is not None else default_rules():
        if not os.path.isdir(rule.root) or os.path.islink(rule.root):
            continue
        cutoff = now - rule.days * 86400
        try:
            entries = list(os.scandir(rule.root))
        except OSError:
            continue
        for entry in entries:
            if entry.name in KEEP_NAMES or (rule.prefix and not entry.name.startswith(rule.prefix)) or entry.is_symlink():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not rule.dirs or _newest_mtime(entry.path) >= cutoff:
                        continue
                    size = _size(entry.path)
                    shutil.rmtree(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if rule.suffixes and not entry.name.lower().endswith(rule.suffixes):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    if stat.st_mtime >= cutoff:
                        continue
                    size = stat.st_size
                    os.remove(entry.path)
                else:
                    continue
            except PermissionError:
                report.in_use += 1  # en uso (Windows): se intenta en el próximo ciclo
                continue
            except OSError as exc:
                logger.warning("No se pudo borrar %s: %s", entry.path, type(exc).__name__)
                report.in_use += 1
                continue
            report.deleted[rule.name] = report.deleted.get(rule.name, 0) + 1
            report.freed_bytes += size
    if report.total:
        logger.info("Limpieza de disco: %s entradas, %.2f GB liberados %s", report.total, report.freed_bytes / 1024 ** 3, report.deleted)
    return report
