"""Etapa estructurada: canal y grupo de WhatsApp (ver ``utils/whatsapp_feed.py``).

* ``WHATSAPP_ENABLED=false`` (default): no hace nada.
* ``WHATSAPP_DRY_RUN=true`` (default): escribe los mensajes que saldrían en
  ``output/whatsapp_preview/`` sin conectarse.

El envío lo hace ``whatsapp/wa.mjs`` (Node + Baileys, sin navegador), de a un
mensaje y con pausas, desde ``meta/whatsapp_worker.py`` (proceso aparte que
lanza esta etapa): los mensajes no llegan en chorro y el ciclo no espera. Un fallo acá nunca afecta a la Web ni a
las redes.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import whatsapp_feed as wf
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.paths import output_dir
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_whatsapp", "whatsapp.log")

STAGE = "whatsapp"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WA_SCRIPT = os.path.join(BASE_DIR, "whatsapp", "wa.mjs")
# Códigos de salida de wa.mjs.
EXIT_NEEDS_AUTH, EXIT_LOGGED_OUT, EXIT_TIMEOUT = 2, 3, 4


def _node() -> str:
    return os.getenv("WHATSAPP_NODE") or shutil.which("node") or "node"


def _write_preview(messages: list[dict]) -> str:
    folder = output_dir() / "whatsapp_preview"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def send(messages: list[dict]) -> tuple[int, list[str]]:
    """Corre ``wa.mjs send``. Devuelve (código de salida, líneas JSONL)."""
    with tempfile.TemporaryDirectory(prefix="lvr_wa_") as tmp:
        inbox = os.path.join(tmp, "in.json")
        outbox = os.path.join(tmp, "out.jsonl")
        payload = [{"key": m["key"], "jid": m["jid"], "text": m["text"], "preview": m.get("preview")} for m in messages]
        with open(inbox, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        timeout = int(os.getenv("WHATSAPP_STAGE_TIMEOUT_SECONDS", "420"))
        try:
            proc = subprocess.run(
                [_node(), WA_SCRIPT, "send", "--in", inbox, "--out", outbox],
                cwd=os.path.dirname(WA_SCRIPT), capture_output=True, text=True, timeout=timeout,
            )
            code = proc.returncode
            if code and proc.stderr:
                logger.warning("wa.mjs terminó con %s: %s", code, proc.stderr.strip()[:200])
        except subprocess.TimeoutExpired:
            logger.error("wa.mjs no terminó en %s s", timeout)
            code = EXIT_TIMEOUT
        lines = []
        if os.path.exists(outbox):
            with open(outbox, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        return code, lines


def main() -> StageResult:
    started = time.monotonic()
    if not wf.enabled():
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if not wf.group_jid() and not wf.channel_jid():
        return StageResult(STAGE, StageStatus.FAILED, error_type="missing_configuration")
    try:
        wf.start_watermark()
        state = wf.load_state()
        messages, stale = wf.plan(state)
    except JsonStateError as exc:
        logger.error("Estado de WhatsApp ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    if stale:
        wf.record({key: {"status": wf.STALE} for key in stale}, {})
    if messages and wf.dry_run():
        preview = _write_preview(messages)
        logger.info("WhatsApp (dry-run): %s mensajes en %s", len(messages), preview)
        return StageResult(STAGE, StageStatus.SUCCESS, received=len(messages), processed=len(messages),
                           details={"dry_run": True, "preview": preview})
    queued = wf.enqueue(messages) if messages else 0
    details = {"queued": queued, "stale": len(stale)}
    if wf.next_queued(wf.load_state()):
        from meta.whatsapp_worker import worker_running

        if worker_running():
            details["worker"] = "running"
        else:
            details["worker"] = f"started:{spawn_worker()}"
            logger.info("Envío espaciado de WhatsApp lanzado (%s nuevos en cola)", queued)
    status = StageStatus.SUCCESS if queued or details.get("worker") else StageStatus.NO_WORK
    return StageResult(STAGE, status, received=queued, processed=queued, succeeded=queued, details=details,
                       duration_seconds=time.monotonic() - started)


def spawn_worker() -> int:
    """Lanza ``meta/whatsapp_worker.py`` como proceso aparte (no frena el ciclo)."""
    worker = os.path.join(BASE_DIR, "meta", "whatsapp_worker.py")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen([sys.executable, worker], cwd=BASE_DIR, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    return proc.pid


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
