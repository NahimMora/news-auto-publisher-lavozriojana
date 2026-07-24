"""Ejecución de etapas hijas usando el contrato estructurado, no texto heurístico."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from utils.stage_result import StageResult, StageStatus, parse_stage_result_output, read_stage_result


def run_stage_process(
    script: str,
    *,
    base_dir: str,
    timeout: float,
    extra_env: dict[str, str] | None = None,
) -> StageResult:
    stage_name = Path(script).stem
    started = time.monotonic()
    fd, result_path = tempfile.mkstemp(prefix=f"lvr-{stage_name}-", suffix=".json")
    os.close(fd)
    try:
        os.unlink(result_path)
    except FileNotFoundError:
        pass

    child_env = os.environ.copy()
    child_env["LVR_STAGE_RESULT_PATH"] = result_path
    if extra_env:
        child_env.update({str(key): str(value) for key, value in extra_env.items()})

    path = script if os.path.isabs(script) else os.path.join(base_dir, script)
    try:
        completed = subprocess.run(
            [sys.executable, path],
            cwd=base_dir,
            timeout=timeout,
            capture_output=True,
            text=True,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        return StageResult(
            stage=stage_name,
            status=StageStatus.FAILED,
            duration_seconds=time.monotonic() - started,
            error_type="timeout",
            error_code="step_timeout",
            details={"script": script, "timeout_seconds": timeout},
        )
    except Exception as exc:
        return StageResult(
            stage=stage_name,
            status=StageStatus.FAILED,
            duration_seconds=time.monotonic() - started,
            error_type="process_start_error",
            error_code=type(exc).__name__,
            details={"script": script, "message": str(exc)},
        )

    result: StageResult | None = None
    try:
        if os.path.exists(result_path):
            result = read_stage_result(result_path)
        if result is None:
            result = parse_stage_result_output(completed.stdout)
    except Exception as exc:
        return StageResult(
            stage=stage_name,
            status=StageStatus.FAILED,
            duration_seconds=time.monotonic() - started,
            error_type="invalid_stage_result",
            error_code=type(exc).__name__,
            details={"script": script, "return_code": completed.returncode},
        )
    finally:
        try:
            os.unlink(result_path)
        except FileNotFoundError:
            pass

    if result is None:
        return StageResult(
            stage=stage_name,
            status=StageStatus.FAILED,
            duration_seconds=time.monotonic() - started,
            error_type="missing_stage_result",
            error_code=completed.returncode,
            details={
                "script": script,
                "return_code": completed.returncode,
                "stderr_tail": str(completed.stderr or "")[-500:],
            },
        )

    if completed.returncode != result.exit_code:
        return StageResult(
            stage=stage_name,
            status=StageStatus.FAILED,
            received=result.received,
            selected=result.selected,
            processed=result.processed,
            succeeded=result.succeeded,
            failed=max(1, result.failed),
            deferred=result.deferred,
            expired=result.expired,
            duration_seconds=time.monotonic() - started,
            error_type="exit_code_mismatch",
            error_code=completed.returncode,
            details={
                "script": script,
                "declared_result": result.to_dict(),
                "actual_return_code": completed.returncode,
            },
        )

    result.duration_seconds = round(time.monotonic() - started, 6)
    return result
