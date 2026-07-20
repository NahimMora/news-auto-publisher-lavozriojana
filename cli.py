"""
CLI de control para el AutoPublicador La Voz Riojana.

Comandos:
  python cli.py start          Inicia el supervisor 24x7 en segundo plano
  python cli.py stop           Detiene el supervisor
  python cli.py status         Estado rápido del pipeline (último ciclo)
  python cli.py logs [modulo]  Muestra logs en tiempo real (Ctrl+C para salir)
  python cli.py run-once       Ejecuta un ciclo completo ahora (sin loop)
"""
import os
import sys
import time
import signal
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR  = os.path.join(BASE_DIR, "logs")
PID_FILE  = os.path.join(BASE_DIR, "data", ".supervisor.pid")
PYTHON    = sys.executable

# Logs por módulo: nombre visible → archivo
LOG_FILES = {
    "supervisor":  "run_24x7.log",
    "scraper":     "run_all.log",
    "rewrite":     "rewrite_news.log",
    "classifier":  "classifier.log",
    "facebook":    "run_fb.log",
    "instagram":   "run_ig.log",
    "fb_client":   "fb_client.log",
    "ig_client":   "ig_client.log",
}

CYCLE_SCRIPTS = [
    "run_all.py",
    "pipeline/publish_web.py",
    "meta/run_fb.py",
    "meta/run_ig.py",
]


# ── Utilidades ────────────────────────────────────────────────

def _read_pid() -> int | None:
    try:
        return int(open(PID_FILE).read().strip())
    except Exception:
        return None


def _write_pid(pid: int):
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    open(PID_FILE, "w").write(str(pid))


def _clear_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def _is_running(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and any(
            "run_24x7" in " ".join(p.cmdline())
            for p in [psutil.Process(pid)]
        )
    except Exception:
        # Fallback sin psutil: envía señal 0
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _tail(path: str, n: int = 30) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except FileNotFoundError:
        return []


def _color(text, code):
    return f"\033[{code}m{text}\033[0m"

def green(t):  return _color(t, "32")
def red(t):    return _color(t, "31")
def yellow(t): return _color(t, "33")
def cyan(t):   return _color(t, "36")
def bold(t):   return _color(t, "1")


# ── Comandos ──────────────────────────────────────────────────

def cmd_start(args):
    pid = _read_pid()
    if pid and _is_running(pid):
        print(yellow(f"El supervisor ya está corriendo (PID {pid})."))
        return

    script = os.path.join(BASE_DIR, "run_24x7.py")
    proc = subprocess.Popen(
        [PYTHON, script],
        cwd=BASE_DIR,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _write_pid(proc.pid)
    print(green(f"Supervisor iniciado (PID {proc.pid})."))
    print(f"  Ver progreso: {cyan('python cli.py logs supervisor')}")
    print(f"  Ver estado:   {cyan('python cli.py status')}")
    print(f"  Detener:      {cyan('python cli.py stop')}")


def cmd_stop(args):
    pid = _read_pid()
    if not pid:
        print(yellow("No hay supervisor registrado (sin PID)."))
        return

    if not _is_running(pid):
        print(yellow(f"PID {pid} ya no está corriendo."))
        _clear_pid()
        return

    try:
        import psutil
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for c in children:
            c.terminate()
        proc.terminate()
        gone, alive = psutil.wait_procs([proc] + children, timeout=8)
        for p in alive:
            p.kill()
    except ImportError:
        os.kill(pid, signal.SIGTERM)
        time.sleep(3)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    except Exception as e:
        print(red(f"Error al detener: {e}"))
        return

    _clear_pid()
    print(green(f"Supervisor detenido (PID {pid})."))


def cmd_status(args):
    pid = _read_pid()
    running = pid and _is_running(pid)

    print(bold("\n=== AutoPublicador La Voz Riojana ==="))
    if running:
        print(f"  Supervisor: {green('CORRIENDO')} (PID {pid})")
    elif pid:
        print(f"  Supervisor: {red('CAIDO')} (PID {pid} no responde)")
        _clear_pid()
    else:
        print(f"  Supervisor: {yellow('DETENIDO')}")

    # Último ciclo desde run_24x7.log
    sup_log = os.path.join(LOGS_DIR, "run_24x7.log")
    sup_lines = _tail(sup_log, 60)
    ultimo_ciclo = None
    for line in reversed(sup_lines):
        if "CICLO #" in line:
            ultimo_ciclo = line.strip()
            break
    if ultimo_ciclo:
        print(f"  Último ciclo: {cyan(ultimo_ciclo)}")

    # Estado de cada paso (última línea OK/FALLO por script)
    print()
    print(bold("  Pasos del ciclo:"))
    for modulo, logfile in [
        ("Scraping",    "run_all.log"),
        ("Reescritura", "rewrite_news.log"),
        ("Facebook",    "run_fb.log"),
        ("Instagram",   "run_ig.log"),
    ]:
        lines = _tail(os.path.join(LOGS_DIR, logfile), 5)
        if not lines:
            print(f"    {modulo:12} {yellow('sin datos')}")
            continue
        last = lines[-1]
        if "ERROR" in last or "FALLO" in last:
            print(f"    {modulo:12} {red('ERROR')}  — {last[-70:]}")
        elif "completado" in last or "publicadas" in last or "guardadas" in last:
            print(f"    {modulo:12} {green('OK')}     — {last[-70:]}")
        else:
            print(f"    {modulo:12} {yellow('...')}    — {last[-70:]}")

    # Contadores de cola
    print()
    print(bold("  Cola social:"))
    queue_path = os.path.join(BASE_DIR, "data", "noticias_sociales_pendientes.json")
    meta_path  = os.path.join(BASE_DIR, "data", "noticias_meta.json")
    web_path   = os.path.join(BASE_DIR, "data", "noticias_web_pending.json")
    try:
        import json
        queue = json.load(open(queue_path, encoding="utf-8"))
        pend_fb = sum(1 for n in queue if not n.get("facebook_done"))
        pend_ig = sum(1 for n in queue if not n.get("instagram_done"))
        print(f"    Pendientes FB: {pend_fb}   IG: {pend_ig}   Total en cola: {len(queue)}")
    except Exception:
        print(f"    {yellow('Cola no encontrada o vacía')}")
    try:
        import json
        meta = json.load(open(meta_path, encoding="utf-8"))
        print(f"    noticias_meta.json (Meta): {len(meta)} entradas")
    except Exception:
        pass
    try:
        import json
        web = json.load(open(web_path, encoding="utf-8"))
        print(f"    noticias_web_pending.json: {len(web)} entradas")
    except Exception:
        pass
    print()


def cmd_logs(args):
    modulo = args.modulo or "supervisor"
    logfile = LOG_FILES.get(modulo)
    if not logfile:
        opciones = ", ".join(LOG_FILES.keys())
        print(red(f"Modulo desconocido: '{modulo}'. Opciones: {opciones}"))
        sys.exit(1)

    path = os.path.join(LOGS_DIR, logfile)

    if not os.path.exists(path):
        print(yellow(f"Log aun no existe: {path}"))
        print("Esperando a que se cree...")

    print(bold(f"=== {modulo} → {logfile} === (Ctrl+C para salir)\n"))

    # Mostrar últimas N líneas previas
    for line in _tail(path, 40):
        _print_log_line(line)

    # Seguir en tiempo real
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # ir al final
            while True:
                line = f.readline()
                if line:
                    _print_log_line(line.rstrip())
                else:
                    time.sleep(0.3)
    except FileNotFoundError:
        while not os.path.exists(path):
            time.sleep(1)
        cmd_logs(args)
    except KeyboardInterrupt:
        print()


def _print_log_line(line: str):
    if "ERROR" in line:
        print(red(line))
    elif "WARNING" in line or "WARN" in line:
        print(yellow(line))
    elif "OK" in line or "Publicado" in line or "guardadas" in line:
        print(green(line))
    else:
        print(line)


def cmd_run_once(args):
    print(bold("Ejecutando ciclo completo (sin loop)...\n"))
    from dotenv import load_dotenv
    load_dotenv()

    resultados = {}
    for script in CYCLE_SCRIPTS:
        path = os.path.join(BASE_DIR, script)
        print(cyan(f"  → {script}"))
        try:
            r = subprocess.run([PYTHON, path], cwd=BASE_DIR, timeout=600)
            ok = r.returncode == 0
            resultados[script] = ok
            print(green(f"    OK") if ok else red(f"    FALLO (codigo {r.returncode})"))
        except subprocess.TimeoutExpired:
            resultados[script] = False
            print(red("    TIMEOUT"))
        except Exception as e:
            resultados[script] = False
            print(red(f"    ERROR: {e}"))

    ok = sum(1 for v in resultados.values() if v)
    print(bold(f"\n{ok}/{len(resultados)} pasos completados exitosamente."))


# ── Entry point ───────────────────────────────────────────────

def cmd_videos(args):
    script = os.path.join(BASE_DIR, "video_reel_manager.py")
    subprocess.run(
        [PYTHON, script, "--host", args.host, "--port", str(args.port)],
        cwd=BASE_DIR,
    )


def main():
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="Control del AutoPublicador La Voz Riojana",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="comando")

    sub.add_parser("start",    help="Inicia el supervisor 24x7 en segundo plano")
    sub.add_parser("stop",     help="Detiene el supervisor")
    sub.add_parser("status",   help="Muestra el estado actual del pipeline")
    sub.add_parser("run-once", help="Ejecuta un ciclo completo ahora (sin loop)")

    videos_p = sub.add_parser("videos", help="Abre la mini UI para cargar videos/Reels")
    videos_p.add_argument("--host", default="127.0.0.1")
    videos_p.add_argument("--port", type=int, default=8765)

    logs_p = sub.add_parser("logs", help="Sigue los logs en tiempo real")
    logs_p.add_argument(
        "modulo", nargs="?", default="supervisor",
        help=f"Modulo a seguir: {', '.join(LOG_FILES.keys())} (default: supervisor)",
    )

    args = parser.parse_args()

    if args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "stop":
        cmd_stop(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "logs":
        cmd_logs(args)
    elif args.cmd == "run-once":
        cmd_run_once(args)
    elif args.cmd == "videos":
        cmd_videos(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
