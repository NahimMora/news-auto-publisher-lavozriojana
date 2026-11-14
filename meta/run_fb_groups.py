"""Etapa estructurada: grupos de Facebook por localidad (ver ``utils/fb_groups.py``).

Arma la cola con lo que salió en Facebook y, si hay pendientes en horario y no
hay otro publicador corriendo, lanza ``meta/fb_groups_worker.py`` como proceso
aparte (publica con pausas largas sin frenar el ciclo).

* ``FB_GROUPS_ENABLED=false`` (default): no hace nada.
* ``FB_GROUPS_DRY_RUN=true`` (default): el publicador escribe y no publica.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from meta.fb_groups_worker import worker_running
from utils import fb_groups as fg
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_fb_groups", "fb_groups.log")

STAGE = "fb_groups"
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fb_groups_worker.py")


def spawn_worker() -> int:
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [sys.executable, WORKER], cwd=os.path.dirname(os.path.dirname(WORKER)),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, close_fds=True,
    )
    return proc.pid


def main() -> StageResult:
    started = time.monotonic()
    if not fg.enabled():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    try:
        fg.start_watermark()
        added = fg.plan()
        expired = fg.expire_old()
        state = fg.load_state()
    except (JsonStateError, OSError, ValueError) as exc:
        logger.error("Grupos de Facebook: estado o configuración ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    details = {"added": added, "expired": expired, "posts": fg.summary(state), "dry_run": fg.dry_run()}
    if fg.blocked(state):
        details["blocked_reason"] = state.get("block_reason")
        return StageResult(STAGE, StageStatus.DEGRADED, error_type="facebook_blocked",
                           next_retry_at=state.get("blocked_until"), details=details,
                           duration_seconds=time.monotonic() - started)
    if fg.next_post(state) and fg.in_active_hours():
        if worker_running():
            details["worker"] = "running"
        else:
            details["worker"] = f"started:{spawn_worker()}"
            logger.info("Publicador de grupos lanzado (%s pendientes)", details["posts"].get(fg.PENDING, 0))
    status = StageStatus.SUCCESS if added or details.get("worker") else StageStatus.NO_WORK
    return StageResult(STAGE, status, received=added, processed=added, succeeded=added, details=details,
                       duration_seconds=time.monotonic() - started)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
