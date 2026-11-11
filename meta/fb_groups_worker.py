"""Publicador de grupos de Facebook (proceso aparte, de a una publicación).

Lo lanza ``meta/run_fb_groups.py`` cuando hay publicaciones pendientes y no
hay otro corriendo. Publica como la página con una pausa al azar entre una y
otra (``FB_GROUPS_GAP_MINUTES``, 12-25) para no bloquear el ciclo, y termina
cuando no queda nada, fuera de horario o al pasar
``FB_GROUPS_WORKER_MAX_MINUTES``.

Ante cualquier aviso de Facebook (captcha, verificación, "actividad inusual",
publicación rechazada por spam) frena todo ``FB_GROUPS_BLOCK_HOURS`` (48). Si
falla después de tocar "Publicar", queda ``unverified`` y no se reintenta.
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

from utils import fb_groups as fg
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir

logger = setup_logger("fb_groups_worker", "fb_groups.log")

PID_PATH = str(data_dir() / "fb_groups_worker.pid")
BLOCK_SIGNS = ("no soy un robot", "actividad inusual", "bloqueado temporalmente", "temporalmente bloquead",
               "publicando muy rápido", "marcado como spam", "se marcó como spam", "confirma tu identidad",
               "revisión de seguridad", "tu cuenta está restringida", "no puedes publicar")
# Aviso que muestra Facebook al enviar en un grupo con aprobación (no el cartel fijo del grupo).
APPROVAL_SIGNS = ("publicación está pendiente", "se publicará cuando", "cuando un administrador la apruebe",
                  "enviada para aprobación", "enviaste tu publicación")


class Blocked(Exception):
    pass


def worker_running() -> bool:
    try:
        with open(PID_PATH, encoding="utf-8") as handle:
            pid = int(handle.read().strip() or 0)
        return pid > 0 and psutil.pid_exists(pid) and "fb_groups_worker" in " ".join(psutil.Process(pid).cmdline())
    except (OSError, ValueError, psutil.Error):
        return False


def _pause(low: float, high: float) -> None:
    time.sleep(random.uniform(low, high))


def _check_block(page) -> None:
    url = page.url
    if "checkpoint" in url or "/login" in url:
        raise Blocked(f"url:{url.split('?')[0]}")
    try:
        text = page.inner_text("body", timeout=5000).lower()
    except Exception:  # noqa: BLE001
        return
    for sign in BLOCK_SIGNS:
        if sign in text:
            raise Blocked(f"aviso:{sign}")


def _close_dialogs(page) -> None:
    for _ in range(3):
        dialog = page.get_by_role("dialog")
        if not dialog.count():
            return
        close = dialog.last.get_by_role("button", name="Cerrar")
        if not close.count():
            return
        close.first.click(timeout=5000)
        _pause(1, 2)


def _composer_dialog(page):
    """El cuadro visible de "Crear publicación" (hay otros ocultos en la página)."""
    for dialog in page.get_by_role("dialog").all():
        try:
            if dialog.is_visible() and "Crear publicación" in dialog.inner_text(timeout=3000):
                return dialog
        except Exception:  # noqa: BLE001 — un cuadro que se cierra mientras se lee
            continue
    return None


def _type_human(page, text: str) -> None:
    for i, line in enumerate(text.split("\n")):
        if i:
            page.keyboard.press("Shift+Enter")
            _pause(0.1, 0.3)
        if line:
            page.keyboard.type(line, delay=random.randint(18, 55))
        _pause(0.2, 0.7)


def _shot(page, key: str, suffix: str) -> str:
    folder = output_dir() / "fb_groups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{key.split(':', 1)[0]}_{suffix}.png"
    page.screenshot(path=str(path))
    return str(path)


def post_one(context, key: str, post: dict, *, dry: bool) -> dict:
    """Publica una nota en un grupo. Devuelve los campos a guardar."""
    page_name = os.getenv("FB_GROUPS_PAGE_NAME", "La Voz Riojana")
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(f"https://www.facebook.com/groups/{post['group_id']}/", wait_until="domcontentloaded")
    _pause(4, 8)
    _check_block(page)
    _close_dialogs(page)
    composer = page.get_by_role("button", name="Escribe algo...")
    if not composer.count():
        composer = page.get_by_text("Escribe algo", exact=False)
    if not composer.count():
        return {"status": fg.FAILED, "error": "composer_not_found", "evidence": _shot(page, key, "sin_editor")}
    composer.first.click(timeout=8000)
    _pause(2, 4)
    dialog = _composer_dialog(page)
    if dialog is None:
        return {"status": fg.FAILED, "error": "dialog_not_found", "evidence": _shot(page, key, "sin_dialogo")}
    if page_name.lower() not in dialog.inner_text().lower():
        # No es la página: nunca publicar como el perfil personal.
        evidence = _shot(page, key, "identidad")
        raise Blocked(f"identidad:no_es_{page_name}:{evidence}")
    box = dialog.get_by_role("textbox").first
    box.click(timeout=8000)
    _pause(0.5, 1.5)
    _type_human(page, post["text"])
    _pause(9, 14)  # la tarjeta del link (con imagen)
    if dry:
        evidence = _shot(page, key, "dryrun")
        page.keyboard.press("Escape")
        _pause(1, 2)
        discard = page.get_by_role("button", name="Descartar")
        if discard.count():
            discard.first.click(timeout=5000)
        return {"status": fg.PENDING, "dry_run_evidence": evidence}
    publish = dialog.get_by_role("button", name="Publicar")
    if not publish.count():
        return {"status": fg.FAILED, "error": "publish_button_not_found", "evidence": _shot(page, key, "sin_boton")}
    publish.first.click(timeout=8000)
    # Desde acá el resultado es externo: ante la duda, unverified.
    for _ in range(30):
        time.sleep(1)
        if _composer_dialog(page) is None:
            break
    else:
        return {"status": fg.UNVERIFIED, "error": "dialog_still_open", "posted_at": int(time.time()),
                "evidence": _shot(page, key, "dudoso")}
    _pause(2, 4)
    text = page.inner_text("body", timeout=8000).lower()
    _check_block(page)
    status = fg.APPROVAL if any(sign in text for sign in APPROVAL_SIGNS) else fg.POSTED
    return {"status": status, "posted_at": int(time.time()), "evidence": _shot(page, key, status)}


def main() -> int:
    from meta.fb_groups_browser import browser

    if worker_running():
        return 0
    with open(PID_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    started = time.time()
    max_minutes = fg._num("FB_GROUPS_WORKER_MAX_MINUTES", 150)
    low, high = (float(x) for x in os.getenv("FB_GROUPS_GAP_MINUTES", "12-25").split("-", 1))
    dry = fg.dry_run()
    done = 0
    try:
        with browser() as context:
            while time.time() - started < max_minutes * 60:
                state = fg.load_state()
                if fg.blocked(state) or not fg.in_active_hours():
                    break
                nxt = fg.next_post(state)
                if not nxt:
                    # Puede quedar pendiente un grupo que publicó hace poco: el
                    # ciclo siguiente vuelve a lanzar el publicador.
                    break
                key, post = nxt
                attempts = int(post.get("attempts") or 0) + 1
                fg.mark(key, attempts=attempts, last_try_at=int(time.time()))
                try:
                    result = post_one(context, key, post, dry=dry)
                except Blocked as exc:
                    fg.mark(key, status=fg.FAILED, error=str(exc)[:200])
                    fg.set_blocked(str(exc))
                    break
                except Exception as exc:  # noqa: BLE001 — un error de página no corta el resto
                    result = {"status": fg.FAILED, "error": f"{type(exc).__name__}"}
                fg.mark(key, **result)
                logger.info("Grupo %s (%s): %s — %s", post["group_name"][:40], post["locality"], result["status"],
                            post["title"][:70])
                if dry:
                    # En prueba se hace una sola y se marca como hecha para no repetir.
                    fg.mark(key, status=fg.EXPIRED, dry_run=True)
                done += 1
                _pause(low * 60, high * 60)
    finally:
        try:
            os.remove(PID_PATH)
        except OSError:
            pass
    logger.info("Publicador de grupos terminó: %s intentos en %.0f min", done, (time.time() - started) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
