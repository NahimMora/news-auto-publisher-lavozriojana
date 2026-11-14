"""Inicio de sesión asistido en Facebook para los grupos (una sola vez).

Uso: ``python scripts/fb_groups_login.py --dir <carpeta> [--minutes 15]``

Abre Chrome sin ventana con el perfil de ``meta/fb_groups_browser.py``,
completa usuario y contraseña desde ``FB_LOGIN_EMAIL`` / ``FB_LOGIN_PASSWORD``
(del ``.env``; nunca se imprimen) y deja en ``<carpeta>``:

* ``screen.png``: lo que muestra Facebook (se actualiza cada pocos segundos);
* ``status.json``: paso detectado (``needs_code``, ``approve_on_phone``,
  ``logged_in``…), URL sin parámetros y botones visibles.

Para responder, el operador (o el asistente) escribe ``<carpeta>/input.json``:
``{"code": "123456"}``, ``{"click": "Texto del botón"}`` o ``{"goto": "url"}``.
Termina al quedar la sesión iniciada o al vencer el tiempo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from meta.fb_groups_browser import browser, logged_in

CODE_SELECTORS = ('input[name="approvals_code"]', 'input[autocomplete="one-time-code"]', 'input[type="tel"]',
                  'input[aria-label*="código" i]', 'input[aria-label*="code" i]')


def write(folder: str, name: str, value) -> None:
    tmp = os.path.join(folder, f".{name}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(folder, name))


def buttons(page) -> list[str]:
    try:
        names = page.eval_on_selector_all(
            'button, [role="button"], a[role="link"], input[type="submit"]',
            "els => els.filter(e => e.offsetParent).map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())"
            ".filter(t => t && t.length < 60)",
        )
    except Exception:  # noqa: BLE001 — la página puede estar navegando
        return []
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen[:25]


def step_of(page, context) -> str:
    if logged_in(context):
        return "logged_in"
    url = page.url
    for selector in CODE_SELECTORS:
        if page.locator(selector).count():
            return "needs_code"
    if page.locator('input[name="email"]').count() and page.locator('input[name="pass"]').count():
        return "login_form"
    text = (page.inner_text("body") or "").lower() if page.locator("body").count() else ""
    if "notificac" in text or "otro dispositivo" in text or "notification" in text:
        return "approve_on_phone"
    if "checkpoint" in url or "two_step" in url:
        return "checkpoint"
    return "other"


def handle_input(folder: str, page) -> str:
    path = os.path.join(folder, "input.json")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            command = json.load(handle)
    finally:
        os.remove(path)
    if command.get("code"):
        for selector in CODE_SELECTORS:
            field = page.locator(selector).first
            if field.count():
                field.fill(str(command["code"]).strip())
                page.keyboard.press("Enter")
                return "code_sent"
        return "code_field_not_found"
    if command.get("click"):
        target = page.get_by_role("button", name=command["click"]).first
        if not target.count():
            target = page.get_by_text(command["click"], exact=False).first
        target.click(timeout=8000)
        return f"clicked:{command['click']}"
    if command.get("goto"):
        page.goto(command["goto"], wait_until="domcontentloaded")
        return "navigated"
    return "unknown_command"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--minutes", type=float, default=15)
    args = parser.parse_args()
    os.makedirs(args.dir, exist_ok=True)
    deadline = time.time() + args.minutes * 60
    email = os.getenv("FB_LOGIN_EMAIL", "").strip()
    password = os.getenv("FB_LOGIN_PASSWORD", "")
    last_action = ""
    with browser() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        submitted = False
        while time.time() < deadline:
            time.sleep(3)
            try:
                step = step_of(page, context)
                if step == "login_form" and not submitted:
                    if not email or not password:
                        step = "missing_credentials"
                    else:
                        page.fill('input[name="email"]', email)
                        page.fill('input[name="pass"]', password)
                        page.keyboard.press("Enter")
                        submitted = True
                        last_action = "credentials_sent"
                action = handle_input(args.dir, page)
                last_action = action or last_action
                page.screenshot(path=os.path.join(args.dir, "screen.png"))
                write(args.dir, "status.json", {
                    "step": step, "url": page.url.split("?")[0], "buttons": buttons(page),
                    "last_action": last_action, "at": time.strftime("%H:%M:%S"),
                })
                if step == "logged_in":
                    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
                    time.sleep(4)
                    page.screenshot(path=os.path.join(args.dir, "screen.png"))
                    return 0
            except Exception as exc:  # noqa: BLE001 — se informa y se sigue mirando
                write(args.dir, "status.json", {"step": "error", "error": type(exc).__name__, "at": time.strftime("%H:%M:%S")})
    write(args.dir, "status.json", {"step": "timeout", "at": time.strftime("%H:%M:%S")})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
