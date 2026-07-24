"""Supervisor 24x7 con resultados funcionales y heartbeat persistente."""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from utils.config import validate_config
from utils.heartbeat import heartbeat_snapshot, write_heartbeat
from utils.logging_setup import setup_logger
from utils.process_runner import run_stage_process
from utils.stage_result import (
    StageResult,
    StageStatus,
    aggregate_results,
    emit_stage_result,
)

logger = setup_logger("run_24x7", "run_24x7.log")

BASE_DIR = os.path.dirname(__file__)
CYCLE_STEPS = [
    "run_all.py",
    "pipeline/publish_web.py",
    "meta/run_fb.py",
    "meta/run_ig.py",
]
_STEP_TIMEOUTS = {
    "run_all.py": 3600,
    "pipeline/publish_web.py": 3600,
}
_DEFAULT_STEP_TIMEOUT = 600

_running = True


def _handle_sigterm(sig, frame) -> None:
    global _running
    logger.info("Señal de apagado recibida; se finalizará de forma controlada")
    _running = False


signal.signal(signal.SIGTERM, _handle_sigterm)
if hasattr(signal, "SIGINT"):
    signal.signal(signal.SIGINT, _handle_sigterm)


def run_step(
    script: str,
    *,
    heartbeat_callback=None,
    heartbeat_interval: float = 30.0,
) -> StageResult:
    timeout = _STEP_TIMEOUTS.get(script, _DEFAULT_STEP_TIMEOUT)
    stop_heartbeat = threading.Event()
    worker: threading.Thread | None = None
    if heartbeat_callback:
        def pulse() -> None:
            while not stop_heartbeat.wait(max(1.0, heartbeat_interval)):
                try:
                    heartbeat_callback()
                except Exception:
                    logger.exception("No se pudo actualizar heartbeat durante %s", script)

        worker = threading.Thread(target=pulse, daemon=True)
        worker.start()

    try:
        result = run_stage_process(script, base_dir=BASE_DIR, timeout=timeout)
    finally:
        stop_heartbeat.set()
        if worker:
            worker.join(timeout=2)

    logger.info(
        "Etapa %s status=%s exit=%s %s/%s",
        script,
        result.status.value,
        result.exit_code,
        result.succeeded,
        result.selected,
    )
    return result


def run_cycle(cycle_number: int, *, heartbeat_interval: float = 30.0) -> StageResult:
    started_wall = time.time()
    started_mono = time.monotonic()
    results: list[StageResult] = []

    def pulse() -> None:
        write_heartbeat(
            cycle_number=cycle_number,
            supervisor_status="running",
            cycle_started_at=started_wall,
            cycle_finished_at=None,
            stage_results=results,
        )

    logger.info("")
    logger.info("=" * 60)
    logger.info("CICLO #%s - %s", cycle_number, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)
    pulse()

    for script in CYCLE_STEPS:
        result = run_step(
            script,
            heartbeat_callback=pulse,
            heartbeat_interval=heartbeat_interval,
        )
        results.append(result)
        pulse()

    aggregate = aggregate_results(
        f"cycle_{cycle_number}",
        results,
        duration_seconds=time.monotonic() - started_mono,
    )
    finished = time.time()
    write_heartbeat(
        cycle_number=cycle_number,
        supervisor_status="waiting",
        cycle_started_at=started_wall,
        cycle_finished_at=finished,
        stage_results=results,
    )
    logger.info(
        "Ciclo #%s status=%s etapas aceptables=%s/%s",
        cycle_number,
        aggregate.status.value,
        sum(1 for result in results if result.acceptable),
        len(results),
    )
    return aggregate


def _initial_cycle_number() -> int:
    snapshot = heartbeat_snapshot()
    data = snapshot.get("data") or {}
    try:
        return int(data.get("cycle_number") or 0)
    except (TypeError, ValueError):
        return 0


def main() -> StageResult:
    global _running
    report = validate_config(scope="supervisor")
    if not report.ok:
        result = StageResult(
            stage="supervisor",
            status=StageStatus.FAILED,
            failed=len(report.errors),
            error_type="configuration_error",
            details={"config": report.to_dict()},
        )
        logger.error("Supervisor no iniciado por configuración inválida: %s", report.to_dict())
        return result

    interval = int(os.getenv("PIPELINE_24X7_INTERVAL_SECONDS", "3600"))
    heartbeat_interval = int(os.getenv("PIPELINE_24X7_HEARTBEAT_SECONDS", "30"))
    cycle_number = _initial_cycle_number()
    cycle_results: list[StageResult] = []
    logger.info("=== Supervisor 24x7 iniciado; intervalo=%ss ===", interval)

    while _running:
        cycle_number += 1
        result = run_cycle(cycle_number, heartbeat_interval=heartbeat_interval)
        cycle_results.append(result)
        if not _running:
            break

        elapsed = 0
        while elapsed < interval and _running:
            wait_for = min(heartbeat_interval, interval - elapsed)
            time.sleep(wait_for)
            elapsed += wait_for
            write_heartbeat(
                cycle_number=cycle_number,
                supervisor_status="waiting",
                cycle_started_at=None,
                cycle_finished_at=time.time(),
                stage_results=(result.details.get("children") or []),
            )

    write_heartbeat(
        cycle_number=cycle_number,
        supervisor_status="stopped",
        cycle_started_at=None,
        cycle_finished_at=time.time(),
        stage_results=[],
    )
    logger.info("=== Supervisor 24x7 detenido ===")
    if not cycle_results:
        return StageResult("supervisor", StageStatus.NO_WORK)
    return aggregate_results("supervisor", cycle_results)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
