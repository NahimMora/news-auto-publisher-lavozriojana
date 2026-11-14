"""Actualiza la biblioteca de notas propias para formatos de video.

Guarda policiales y política de las últimas horas con su texto, la foto ya
procesada y los controles visuales (``utils/newscast_library.py``). La corre
el Noticiero antes de armar el guion; también puede programarse cada hora.

Uso:
    python meta/run_newscast_library.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from utils import newscast_library as lib  # noqa: E402
from utils.logging_setup import setup_logger  # noqa: E402
from utils.stage_result import StageResult, StageStatus, emit_stage_result  # noqa: E402

logger = setup_logger("run_newscast_library", "nightly_newscast.log")
STAGE = "newscast_library"


def main() -> StageResult:
    started = time.monotonic()
    report = lib.refresh()
    if report.get("error"):
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error", details={"error": report["error"]})
    status = StageStatus.SUCCESS if report.get("added") else StageStatus.NO_WORK
    return StageResult(STAGE, status, received=report.get("considered", 0), processed=report.get("added", 0),
                       succeeded=report.get("added", 0), duration_seconds=time.monotonic() - started,
                       details={k: v for k, v in report.items() if k != "excluded"})


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
