"""
Supervisor 24x7 de La Voz Riojana.
Ejecuta el ciclo completo cada PIPELINE_24X7_INTERVAL_SECONDS (por defecto 3600 = 1 hora).

Ciclo:
  1. run_all.py        → Scraping de las 3 secciones + reescritura OpenAI
  2. publish_web.py    → Publicación en WebApp Node.js (o 'off')
  3. run_fb.py         → Publicación en Facebook
  4. run_ig.py         → Publicación en Instagram

Características:
  - Aislamiento de fallos: un paso fallido no detiene los siguientes
  - Log de estado por ciclo
  - Reinicio automático tras cada ciclo
"""
import os
import sys
import time
import subprocess
import signal
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from utils.logging_setup import setup_logger

logger = setup_logger("run_24x7", "run_24x7.log")

BASE_DIR = os.path.dirname(__file__)
PYTHON = sys.executable

INTERVAL = int(os.getenv("PIPELINE_24X7_INTERVAL_SECONDS", "3600"))
HEARTBEAT = int(os.getenv("PIPELINE_24X7_HEARTBEAT_SECONDS", "30"))

CYCLE_STEPS = [
    "run_all.py",
    "pipeline/publish_web.py",
    "meta/run_fb.py",
    "meta/run_ig.py",
]

# Timeouts por paso (segundos). run_all y publish_web necesitan mucho más
# porque hacen múltiples llamadas a OpenAI por artículo.
_STEP_TIMEOUTS = {
    "run_all.py":              3600,   # 1h: scrapers + rewrite (3 calls OpenAI/artículo)
    "pipeline/publish_web.py": 3600,   # 1h: editorial enricher (hasta 6 calls OpenAI/artículo)
}
_DEFAULT_STEP_TIMEOUT = 600

_running = True


def _handle_sigterm(sig, frame):
    global _running
    logger.info("SIGTERM recibido, finalizando después del ciclo actual...")
    _running = False


signal.signal(signal.SIGTERM, _handle_sigterm)


def run_step(script: str) -> bool:
    path = os.path.join(BASE_DIR, script)
    timeout = _STEP_TIMEOUTS.get(script, _DEFAULT_STEP_TIMEOUT)
    logger.info(f"  -> {script} (timeout: {timeout}s)")
    try:
        result = subprocess.run(
            [PYTHON, path],
            cwd=BASE_DIR,
            timeout=timeout,
        )
        ok = result.returncode == 0
        logger.info(f"  {'OK' if ok else 'FALLO'}: {script}")
        return ok
    except subprocess.TimeoutExpired:
        logger.error(f"  TIMEOUT: {script}")
        return False
    except Exception as e:
        logger.error(f"  ERROR en {script}: {e}")
        return False


def run_cycle(cycle_num: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"")
    logger.info(f"{'='*60}")
    logger.info(f"CICLO #{cycle_num} - {ts}")
    logger.info(f"{'='*60}")

    resultados = {}
    for step in CYCLE_STEPS:
        resultados[step] = run_step(step)

    ok = sum(1 for v in resultados.values() if v)
    logger.info(f"Ciclo #{cycle_num} completado: {ok}/{len(resultados)} pasos exitosos")
    return resultados


def main():
    logger.info("=== La Voz Riojana - Supervisor 24x7 iniciado ===")
    logger.info(f"Intervalo entre ciclos: {INTERVAL}s ({INTERVAL//60} min)")

    cycle_num = 0
    while _running:
        cycle_num += 1
        run_cycle(cycle_num)

        if not _running:
            break

        logger.info(f"Próximo ciclo en {INTERVAL}s ({INTERVAL//60} min)...")
        elapsed = 0
        while elapsed < INTERVAL and _running:
            time.sleep(min(HEARTBEAT, INTERVAL - elapsed))
            elapsed += HEARTBEAT

    logger.info("=== Supervisor 24x7 detenido ===")


if __name__ == "__main__":
    main()
