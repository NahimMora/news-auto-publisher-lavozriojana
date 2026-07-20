"""
Orquestador de scraping: ejecuta los 3 scrapers + reescritura con OpenAI.
Pasos:
  1. Locales (si habilitado)
  2. Policiales (si habilitado)
  3. Interior (si habilitado)
  4. Reescritura con OpenAI
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from utils.logging_setup import setup_logger

logger = setup_logger("run_all", "run_all.log")

BASE_DIR = os.path.dirname(__file__)
PYTHON = sys.executable


TIMEOUTS = {
    "openIA/rewrite_news.py": 1800,  # 30 min: 3 llamadas OpenAI por artículo
}
DEFAULT_TIMEOUT = 300


def run_script(script: str) -> bool:
    path = os.path.join(BASE_DIR, script)
    timeout = TIMEOUTS.get(script, DEFAULT_TIMEOUT)
    logger.info(f"Ejecutando: {script} (timeout: {timeout}s)")
    try:
        result = subprocess.run(
            [PYTHON, path],
            cwd=BASE_DIR,
            timeout=timeout,
            capture_output=False,
        )
        if result.returncode == 0:
            logger.info(f"OK: {script}")
            return True
        else:
            logger.error(f"FALLO (código {result.returncode}): {script}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"TIMEOUT: {script}")
        return False
    except Exception as e:
        logger.error(f"Excepción en {script}: {e}")
        return False


def main():
    logger.info("=== Iniciando ciclo de scraping ===")

    steps = [
        ("main_locales.py", os.getenv("SCRAPER_LOCALES_ENABLED", "1") == "1"),
        ("main_policiales.py", os.getenv("SCRAPER_POLICIALES_ENABLED", "1") == "1"),
        ("main_interior.py", os.getenv("SCRAPER_INTERIOR_ENABLED", "1") == "1"),
        ("main_deportes.py", os.getenv("SCRAPER_DEPORTES_ENABLED", "1") == "1"),
        ("main_nuevarioja.py", os.getenv("SCRAPER_NUEVARIOJA_ENABLED", "1") == "1"),
        ("openIA/rewrite_news.py", True),
    ]

    resultados = {}
    for script, enabled in steps:
        if not enabled:
            logger.info(f"Saltando (deshabilitado): {script}")
            continue
        resultados[script] = run_script(script)

    exitosos = sum(1 for v in resultados.values() if v)
    logger.info(f"=== Scraping completado: {exitosos}/{len(resultados)} pasos exitosos ===")


if __name__ == "__main__":
    main()
