"""Envío espaciado a WhatsApp (proceso aparte, de a un mensaje).

Lo lanza ``meta/run_whatsapp.py`` cuando deja mensajes en cola. Envía uno por
vez (último momento primero), con una pausa al azar entre mensajes
(``WHATSAPP_GAP_SECONDS``, 90-240) para que no lleguen en chorro, y termina
cuando la cola queda vacía. Un mensaje que ya pasó ``WHATSAPP_MAX_AGE_HOURS``
mientras esperaba no se envía.
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import psutil

from utils import whatsapp_feed as wf
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("whatsapp_worker", "whatsapp.log")

PID_PATH = str(data_dir() / "whatsapp_worker.pid")


def worker_running() -> bool:
    try:
        with open(PID_PATH, encoding="utf-8") as handle:
            pid = int(handle.read().strip() or 0)
        return pid > 0 and psutil.pid_exists(pid) and "whatsapp_worker" in " ".join(psutil.Process(pid).cmdline())
    except (OSError, ValueError, psutil.Error):
        return False


def run(*, sleep=time.sleep, now=time.time) -> int:
    """Envía la cola. Devuelve cuántos salieron."""
    from meta.run_whatsapp import EXIT_LOGGED_OUT, EXIT_NEEDS_AUTH, send

    wf.recover_in_flight()
    sent = 0
    low, high = wf.gap_seconds()
    first = True
    while True:
        nxt = wf.next_queued(wf.load_state())
        if not nxt:
            break
        key, entry = nxt
        payload = dict(entry["payload"])
        if now() - float(payload.get("posted_at") or entry.get("queued_at") or 0) > wf.max_age_seconds():
            wf.record({key: {"status": wf.STALE}}, {})
            continue
        if not first:
            sleep(random.uniform(low, high))
        first = False
        preview = dict(payload.get("preview") or {})
        thumb = wf.thumbnail_b64(preview.pop("image_url", ""))
        if thumb:
            preview["thumb_b64"] = thumb
        wf.mark_status(key, wf.SENDING)
        code, lines = send([{"key": key, "jid": payload["jid"], "text": payload["text"], "preview": preview}])
        results = wf.parse_results(lines, [key])
        if not results:
            # Ni siquiera llegó a intentarlo (sin conexión): vuelve a la cola.
            wf.mark_status(key, wf.QUEUED)
            if code in (EXIT_NEEDS_AUTH, EXIT_LOGGED_OUT):
                logger.error("WhatsApp sin sesión: hay que volver a vincular (whatsapp/wa.mjs login)")
            break
        wf.record(results, {key: entry.get("title", "")})
        result = results[key]
        if result["status"] == wf.SENT:
            sent += 1
            logger.info("WhatsApp %s → %s", key.split(":", 1)[0], entry.get("title", "")[:80])
        else:
            logger.warning("WhatsApp %s %s: %s", result["status"], entry.get("title", "")[:60], result.get("error", ""))
    return sent


def main() -> int:
    if worker_running():
        return 0
    with open(PID_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        sent = run()
        logger.info("Envío espaciado de WhatsApp terminó: %s mensajes", sent)
    finally:
        try:
            os.remove(PID_PATH)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
