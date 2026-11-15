"""Etapa del ciclo: borra copias de trabajo viejas (ver ``utils/disk_cleanup.py``)."""
from __future__ import annotations

import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from utils import disk_cleanup
from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_disk_cleanup", "disk_cleanup.log")
STAGE = "disk_cleanup"


def main() -> StageResult:
    started = time.monotonic()
    if os.getenv("DISK_CLEANUP_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on", "si", "sí"}:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    report = disk_cleanup.cleanup()
    free_gb = round(shutil.disk_usage(disk_cleanup.REPO_DIR).free / 1024 ** 3, 2)
    details = {"deleted": report.deleted, "freed_gb": round(report.freed_bytes / 1024 ** 3, 2), "in_use": report.in_use, "free_gb": free_gb}
    if free_gb < float(os.getenv("DISK_CLEANUP_WARN_FREE_GB", "5")):
        logger.warning("Quedan %.2f GB libres en el disco del proyecto", free_gb)
    if not report.total:
        return StageResult(STAGE, StageStatus.NO_WORK, details=details, duration_seconds=time.monotonic() - started)
    return StageResult(STAGE, StageStatus.SUCCESS, received=report.total, processed=report.total, succeeded=report.total,
                       details=details, duration_seconds=time.monotonic() - started)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
