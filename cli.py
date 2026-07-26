"""CLI segura de operación y diagnóstico del AutoPublicador La Voz Riojana."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

# Las rutas y varios clientes se fijan al importar sus módulos. El entorno debe
# estar cargado antes de cualquier import de ``utils`` para que .env sea efectivo.
load_dotenv()

from utils.config import diagnose_environment, validate_config
from utils.alerts import alert_test, monitor_operational_state
from utils.canary import run_canary
from utils.deployment import deployment_plan, stage_environment
from utils.heartbeat import collect_queue_metrics, heartbeat_snapshot
from utils.file_manager import JsonStateError, backup_json, restore_json
from utils.facebook_reconcile import (
    apply_facebook_decisions,
    build_facebook_report,
)
from utils.paths import ROOT_DIR, data_dir, logs_dir
from utils.preflight import PREFLIGHT_SCOPES, run_preflight
from utils.process_runner import run_stage_process
from utils.stage_result import StageResult, StageStatus, aggregate_results


BASE_DIR = str(ROOT_DIR)
PYTHON = sys.executable

LOG_FILES = {
    "supervisor": "run_24x7.log",
    "scraper": "run_all.log",
    "rewrite": "rewrite_news.log",
    "classifier": "classifier.log",
    "web": "publish_web.log",
    "facebook": "run_fb.log",
    "instagram": "run_ig.log",
    "fb_client": "fb_client.log",
    "ig_client": "ig_client.log",
    "r2": "r2_storage.log",
}

CYCLE_SCRIPTS = [
    ("run_all.py", 3600, None),
    ("pipeline/publish_web.py", 3600, "web"),
    ("meta/run_fb.py", 600, "facebook"),
    ("meta/run_ig.py", 600, "instagram"),
]


def _pid_file() -> Path:
    return data_dir() / ".supervisor.pid"


def _read_pid() -> int | None:
    try:
        with _pid_file().open("r", encoding="ascii") as handle:
            return int(handle.read().strip())
    except (FileNotFoundError, OSError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    path = _pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".supervisor.pid.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(str(int(pid)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _clear_pid() -> None:
    try:
        _pid_file().unlink()
    except FileNotFoundError:
        pass


def _is_running(pid: int) -> bool:
    try:
        import psutil

        process = psutil.Process(pid)
        command = " ".join(process.cmdline()).lower()
        return process.is_running() and "run_24x7.py" in command
    except Exception:
        # No se usa os.kill(pid, 0): podría aceptar un PID reutilizado por otro proceso.
        return False


def _tail(path: Path, count: int = 30) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip() for line in lines[-count:]]
    except FileNotFoundError:
        return []


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _color(text, "32")


def red(text: str) -> str:
    return _color(text, "31")


def yellow(text: str) -> str:
    return _color(text, "33")


def cyan(text: str) -> str:
    return _color(text, "36")


def bold(text: str) -> str:
    return _color(text, "1")


def build_status_snapshot(*, now: float | int | None = None) -> dict:
    pid = _read_pid()
    running = bool(pid and _is_running(pid))
    heartbeat = heartbeat_snapshot(now=now)
    queues = collect_queue_metrics()

    if heartbeat["stale"]:
        supervisor_status = "stale" if heartbeat["present"] or pid else "stopped"
    elif running:
        supervisor_status = "running"
    elif pid:
        supervisor_status = "down"
    else:
        supervisor_status = "stopped"

    queue_errors = [
        name
        for name, value in queues.items()
        if value.get("status") in {"corrupt", "error"}
    ]
    if supervisor_status in {"stale", "down"} or queue_errors:
        overall = StageStatus.FAILED
    elif supervisor_status == "stopped":
        overall = StageStatus.DEGRADED
    else:
        stage_statuses = {
            str(item.get("status"))
            for item in ((heartbeat.get("data") or {}).get("stages") or [])
        }
        overall = (
            StageStatus.DEGRADED
            if stage_statuses & {StageStatus.DEGRADED.value, StageStatus.FAILED.value}
            else StageStatus.SUCCESS
        )

    return {
        "overall_status": overall.value,
        "exit_code": StageResult("status", overall).exit_code,
        "supervisor": {
            "status": supervisor_status,
            "pid": pid,
            "process_matches": running,
        },
        "heartbeat": {
            key: value
            for key, value in heartbeat.items()
            if key != "data"
        },
        "last_cycle": (heartbeat.get("data") or {}).get("cycle_number"),
        "stages": (heartbeat.get("data") or {}).get("stages", []),
        "queues": queues,
        "queue_errors": queue_errors,
        "deployment": (heartbeat.get("data") or {}).get("deployment"),
    }


def cmd_start(args) -> int:
    report = validate_config(scope="supervisor")
    if not report.ok:
        print(red("Configuración inválida; el supervisor no se inició."))
        for issue in report.errors:
            print(f"  - {issue.field}: {issue.message}")
        print("Ejecutá: python cli.py doctor")
        return 1

    pid = _read_pid()
    if pid and _is_running(pid):
        print(yellow(f"El supervisor ya está corriendo (PID {pid})."))
        return 0

    script = os.path.join(BASE_DIR, "run_24x7.py")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [PYTHON, script],
        cwd=BASE_DIR,
        creationflags=creationflags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _write_pid(process.pid)
    print(green(f"Supervisor iniciado (PID {process.pid})."))
    return 0


def cmd_stop(args) -> int:
    pid = _read_pid()
    if not pid:
        print(yellow("No hay supervisor registrado."))
        return 0
    if not _is_running(pid):
        print(red(f"El PID {pid} no corresponde al supervisor; no se envió ninguna señal."))
        return 1

    try:
        import psutil

        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            child.terminate()
        process.terminate()
        _gone, alive = psutil.wait_procs([process, *children], timeout=8)
        for remaining in alive:
            remaining.kill()
    except Exception as exc:
        print(red(f"Error al detener el supervisor: {exc}"))
        return 1
    _clear_pid()
    print(green(f"Supervisor detenido (PID {pid})."))
    return 0


def cmd_status(args) -> int:
    snapshot = build_status_snapshot()
    if getattr(args, "json", False):
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        return int(snapshot["exit_code"])

    supervisor = snapshot["supervisor"]
    print(bold("\n=== AutoPublicador La Voz Riojana ==="))
    color = green if supervisor["status"] == "running" else red
    print(f"  Supervisor: {color(supervisor['status'].upper())} (PID {supervisor['pid'] or '-'})")
    print(
        f"  Heartbeat: {snapshot['heartbeat']['status']} "
        f"(edad={snapshot['heartbeat']['age_seconds']}s)"
    )
    print(f"  Último ciclo: {snapshot['last_cycle'] or 'sin datos'}")
    print(bold("\n  Etapas:"))
    for stage in snapshot["stages"]:
        print(
            f"    {stage.get('stage', '?'):18} {stage.get('status', '?'):10} "
            f"{stage.get('succeeded', 0)}/{stage.get('selected', 0)}"
        )
    print(bold("\n  Colas:"))
    for name, metrics in snapshot["queues"].items():
        print(f"    {name:10} {json.dumps(metrics, ensure_ascii=False, sort_keys=True)}")
    print()
    return int(snapshot["exit_code"])


def cmd_logs(args) -> int:
    module = args.modulo or "supervisor"
    filename = LOG_FILES.get(module)
    if not filename:
        print(red(f"Módulo desconocido: {module}"))
        return 1
    path = logs_dir() / filename
    if not path.exists():
        print(yellow(f"El log todavía no existe: {path}"))
        return 0 if not getattr(args, "follow", False) else 1
    for line in _tail(path, 40):
        print(line)
    if not getattr(args, "follow", False):
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, 2)
            while True:
                line = handle.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(0.3)
    except FileNotFoundError:
        print(yellow(f"El log no existe: {path}"))
        return 1
    except KeyboardInterrupt:
        return 0


def cmd_run_once(args) -> int:
    if getattr(args, "dry_run", False):
        with tempfile.TemporaryDirectory(prefix="lvr-e2e-local-") as temp_root:
            child_env = os.environ.copy()
            child_env.update(
                {
                    "LVR_DATA_DIR": os.path.join(temp_root, "data"),
                    "LVR_LOGS_DIR": os.path.join(temp_root, "logs"),
                    "LVR_OUTPUT_DIR": os.path.join(temp_root, "output"),
                    "LVR_FOTOS_DIR": os.path.join(temp_root, "fotos"),
                    "LVR_BACKUP_DIR": os.path.join(temp_root, "backups"),
                    "LVR_QUARANTINE_DIR": os.path.join(temp_root, "quarantine"),
                    "PIPELINE_DEPLOYMENT_MODE": "observe",
                    "WEB_PUBLISH_TARGET": "off",
                    "FB_PUBLISH_ENABLED": "false",
                    "IG_PUBLISH_ENABLED": "false",
                    "CANARY_ENABLED": "false",
                    "ALERTS_ENABLED": "false",
                    "PRIVATE_API_KEY": "PENDIENTE",
                    "WEBAPP_API_KEY": "PENDIENTE",
                    "OPENAI_API_KEY": "PENDIENTE",
                    "FB_PAGE_ACCESS_TOKEN": "PENDIENTE",
                    "IG_ACCESS_TOKEN": "PENDIENTE",
                    "R2_ACCESS_KEY_ID": "PENDIENTE",
                    "R2_SECRET_ACCESS_KEY": "PENDIENTE",
                    "JSON_BACKUP_ENABLED": "false",
                }
            )
            completed = subprocess.run(
                [PYTHON, "-m", "unittest", "tests.test_e2e_local"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=180,
                env=child_env,
            )
        result = StageResult(
            "local_e2e",
            StageStatus.SUCCESS if completed.returncode == 0 else StageStatus.FAILED,
            received=17,
            selected=17,
            processed=17,
            succeeded=17 if completed.returncode == 0 else 0,
            failed=0 if completed.returncode == 0 else 1,
            error_type=None if completed.returncode == 0 else "local_e2e_failed",
            details={
                "production_calls": False,
                "summary": (completed.stderr or completed.stdout)[-2000:],
            },
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return result.exit_code

    report = validate_config(scope="supervisor")
    if not report.ok:
        result = StageResult(
            "run_once",
            StageStatus.FAILED,
            failed=len(report.errors),
            error_type="configuration_error",
            details={"config": report.to_dict(), "production_calls": False},
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return result.exit_code
    plan = deployment_plan()
    results = []
    for script, timeout, channel in CYCLE_SCRIPTS:
        if channel and not plan.channel_enabled(channel):
            results.append(
                StageResult(
                    channel,
                    StageStatus.NO_WORK,
                    details={
                        "disabled": True,
                        "deployment_mode": plan.mode.value,
                    },
                )
            )
            continue
        results.append(
            run_stage_process(
                script,
                base_dir=BASE_DIR,
                timeout=timeout,
                extra_env=stage_environment(channel, plan) if channel else None,
            )
        )
    aggregate = aggregate_results("run_once", results)
    payload = aggregate.to_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for result in results:
            print(
                f"{result.stage:18} {result.status.value:10} "
                f"{result.succeeded}/{result.selected}"
            )
        print(f"Resultado: {aggregate.status.value}")
    return aggregate.exit_code


def cmd_doctor(args) -> int:
    result = diagnose_environment(scope=getattr(args, "scope", "all"))
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(bold("Diagnóstico seguro de configuración"))
        print(f"Estado: {result.status.value}")
        for issue in result.details["config"]["errors"]:
            print(red(f"  ERROR {issue['field']}: {issue['message']}"))
        for issue in result.details["config"]["warnings"]:
            print(yellow(f"  AVISO {issue['field']}: {issue['message']}"))
        print(f"Dependencias Python: {result.details['python_dependencies']}")
        print(f"Binarios de sistema: {result.details['system_binaries']}")
    return result.exit_code


def cmd_preflight(args) -> int:
    result = run_preflight(getattr(args, "scope", "all"))
    payload = result.to_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Preflight {args.scope}: {result.status.value}")
        print(
            f"Procesados={result.processed} exitosos={result.succeeded} "
            f"fallidos={result.failed} diferidos={result.deferred}"
        )
    return result.exit_code


def cmd_canary(args) -> int:
    channels = [
        value.strip()
        for value in str(getattr(args, "channels", "") or "").split(",")
        if value.strip()
    ]
    result = run_canary(
        args.input,
        channels,
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm_external_publication=bool(
            getattr(args, "confirm_external_publication", False)
        ),
        cleanup=bool(getattr(args, "cleanup", False)),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


def cmd_reconcile_facebook(args) -> int:
    try:
        if getattr(args, "report_only", False):
            report = build_facebook_report(
                verify_meta=not bool(getattr(args, "no_verify_meta", False))
            )
            if getattr(args, "output", None):
                destination = Path(args.output).expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
                temporary.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, destination)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            ambiguous = (
                report["counts"]["ambiguous"]
                + report["counts"]["invalid"]
                + report["counts"]["blocked_missing_web_url"]
            )
            return 2 if ambiguous else 0
        result = apply_facebook_decisions(args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, JsonStateError, json.JSONDecodeError) as exc:
        result = StageResult(
            "reconcile_facebook",
            StageStatus.FAILED,
            failed=1,
            error_type=type(exc).__name__,
            details={"message": str(exc)},
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return result.exit_code


def cmd_alert_test(args) -> int:
    result = alert_test()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


def cmd_alert_check(args) -> int:
    try:
        result = monitor_operational_state()
    except JsonStateError as exc:
        result = StageResult(
            "alerts",
            StageStatus.FAILED,
            failed=1,
            error_type="state_error",
            details={"message": str(exc)},
        )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


def _safe_data_filename(value: str) -> Path:
    name = Path(str(value or "")).name
    if name != value or not name.endswith(".json"):
        raise ValueError("Se requiere un nombre de archivo .json sin ruta")
    return data_dir() / name


def cmd_backup(args) -> int:
    try:
        targets = (
            [_safe_data_filename(args.file)]
            if args.file
            else sorted(data_dir().glob("*.json"))
        )
        created = []
        for target in targets:
            destination = backup_json(str(target))
            if destination:
                created.append(destination)
        print(
            json.dumps(
                {"status": "success", "backups_created": created},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (ValueError, JsonStateError) as exc:
        print(red(f"Backup falló: {exc}"))
        return 1


def cmd_restore(args) -> int:
    try:
        target = _safe_data_filename(args.target)
        backup = Path(args.backup).expanduser().resolve()
        if not backup.is_file() or backup.suffix.lower() != ".json":
            raise ValueError("El backup indicado no existe o no es JSON")
        restore_json(str(backup), str(target))
        print(green(f"Restaurado {target.name}; se respaldó el estado anterior."))
        return 0
    except (ValueError, JsonStateError) as exc:
        print(red(f"Restauración falló: {exc}"))
        return 1


def cmd_videos(args) -> int:
    script = os.path.join(BASE_DIR, "video_reel_manager.py")
    completed = subprocess.run(
        [PYTHON, script, "--host", args.host, "--port", str(args.port)],
        cwd=BASE_DIR,
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="Control del AutoPublicador La Voz Riojana",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="comando")
    sub.add_parser("start", help="Inicia el supervisor 24x7")
    sub.add_parser("stop", help="Detiene el supervisor")

    status_parser = sub.add_parser("status", help="Estado estructurado del pipeline")
    status_parser.add_argument("--json", action="store_true")

    run_parser = sub.add_parser("run-once", help="Ejecuta un ciclo completo")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta los 17 escenarios locales sin integraciones ni datos reales",
    )
    run_parser.add_argument("--json", action="store_true")

    doctor_parser = sub.add_parser("doctor", help="Valida configuración sin publicar")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument(
        "--scope",
        choices=["core", "all", "supervisor", "rewrite", "web", "facebook", "instagram"],
        default="all",
    )

    preflight_parser = sub.add_parser(
        "preflight",
        help="Verifica entorno e integraciones sin publicar contenido",
    )
    preflight_parser.add_argument("--scope", choices=PREFLIGHT_SCOPES, default="all")
    preflight_parser.add_argument("--json", action="store_true")

    canary_parser = sub.add_parser(
        "canary",
        help="Ejecuta una única noticia canary fuera de las colas generales",
    )
    canary_parser.add_argument("--input", required=True, help="Fixture JSON canary")
    canary_parser.add_argument(
        "--channels",
        required=True,
        help="Lista separada por comas: web,facebook,instagram",
    )
    canary_parser.add_argument("--dry-run", action="store_true")
    canary_parser.add_argument("--cleanup", action="store_true")
    canary_parser.add_argument("--confirm-external-publication", action="store_true")
    canary_parser.add_argument("--json", action="store_true")

    reconcile_parser = sub.add_parser(
        "reconcile-facebook",
        help="Clasifica el backlog de Facebook o aplica decisiones aprobadas",
    )
    reconcile_mode = reconcile_parser.add_mutually_exclusive_group(required=True)
    reconcile_mode.add_argument("--report-only", action="store_true")
    reconcile_mode.add_argument("--apply", help="Archivo JSON de decisiones aprobadas")
    reconcile_parser.add_argument("--output", help="Exporta el reporte JSON")
    reconcile_parser.add_argument(
        "--no-verify-meta",
        action="store_true",
        help="No consulta IDs externos; queda indicado en el reporte",
    )
    reconcile_parser.add_argument("--json", action="store_true")

    alert_test_parser = sub.add_parser(
        "alert-test",
        help="Genera una alerta de prueba sin afectar el pipeline",
    )
    alert_test_parser.add_argument("--json", action="store_true")

    alert_check_parser = sub.add_parser(
        "alert-check",
        help="Evalúa heartbeat, colas y eventos y entrega alertas pendientes",
    )
    alert_check_parser.add_argument("--json", action="store_true")

    video_parser = sub.add_parser("videos", help="Abre la UI local de Reels")
    video_parser.add_argument("--host", default="127.0.0.1")
    video_parser.add_argument("--port", type=int, default=8765)

    logs_parser = sub.add_parser("logs", help="Muestra logs")
    logs_parser.add_argument("modulo", nargs="?", default="supervisor")
    logs_parser.add_argument("--follow", action="store_true")

    backup_parser = sub.add_parser("backup", help="Respalda JSON válidos de data")
    backup_parser.add_argument("--file", help="Nombre de un JSON; sin opción respalda todos")

    restore_parser = sub.add_parser(
        "restore",
        help="Restaura un JSON desde backup y respalda antes el estado actual",
    )
    restore_parser.add_argument("--backup", required=True)
    restore_parser.add_argument("--target", required=True, help="Nombre destino dentro de data")

    args = parser.parse_args(argv)
    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "run-once": cmd_run_once,
        "doctor": cmd_doctor,
        "preflight": cmd_preflight,
        "canary": cmd_canary,
        "reconcile-facebook": cmd_reconcile_facebook,
        "alert-test": cmd_alert_test,
        "alert-check": cmd_alert_check,
        "videos": cmd_videos,
        "logs": cmd_logs,
        "backup": cmd_backup,
        "restore": cmd_restore,
    }
    if args.cmd not in commands:
        parser.print_help()
        return 1
    return commands[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
