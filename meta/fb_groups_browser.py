"""Navegador para publicar en grupos de Facebook como la página.

La Graph API ya no publica en grupos (2024): esto maneja un Chrome sin ventana
con un perfil propio (``fb_groups/profile``, secreto, ignorado por git) donde
quedó iniciada la sesión del operador. Nunca guarda ni imprime contraseñas: el
inicio lo hace ``scripts/fb_groups_login.py`` una sola vez.
"""
from __future__ import annotations

import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_DIR = Path(os.getenv("FB_GROUPS_PROFILE_DIR") or BASE_DIR / "fb_groups" / "profile")
CHROME_PATH = os.getenv("FB_GROUPS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def chrome_version() -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-Item '{CHROME_PATH}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return out if re.fullmatch(r"[\d.]+", out) else "141.0.0.0"
    except (OSError, subprocess.SubprocessError):
        return "141.0.0.0"


def user_agent() -> str:
    # El de Chrome de escritorio: el modo sin ventana anuncia "HeadlessChrome".
    major = chrome_version().split(".")[0]
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36")


@contextmanager
def browser(headless: bool = True):
    """Contexto persistente (la sesión sobrevive entre corridas)."""
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
            headless=headless,
            locale="es-AR",
            timezone_id="America/Argentina/Catamarca",
            viewport={"width": 1280, "height": 900},
            user_agent=user_agent(),
            args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
        )
        try:
            yield context
        finally:
            context.close()


def logged_in(context) -> bool:
    return any(c.get("name") == "c_user" and c.get("value") for c in context.cookies("https://www.facebook.com"))
