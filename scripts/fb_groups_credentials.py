"""Guarda FB_LOGIN_EMAIL y FB_LOGIN_PASSWORD en el .env sin mostrarlos.

Uso (cmd, PowerShell o bash): ``C:\\LVR\\venv\\Scripts\\python.exe C:\\LVR\\scripts\\fb_groups_credentials.py``
Con ``--borrar`` quita la contraseña (la sesión ya iniciada sigue sirviendo).
"""
from __future__ import annotations

import getpass
import os
import sys

ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
KEYS = ("FB_LOGIN_EMAIL=", "FB_LOGIN_PASSWORD=")


def _lines() -> list[str]:
    with open(ENV, encoding="utf-8") as handle:
        return handle.read().splitlines()


def _write(lines: list[str]) -> None:
    tmp = ENV + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(tmp, ENV)


def main() -> int:
    if "--borrar" in sys.argv:
        _write([line for line in _lines() if not line.startswith("FB_LOGIN_PASSWORD=")])
        print("Contraseña borrada del .env.")
        return 0
    email = input("Email o teléfono de Facebook: ").strip()
    password = getpass.getpass("Contraseña de Facebook (no se ve al escribir): ")
    if not email or not password:
        print("Faltan datos; no se guardó nada.")
        return 1
    lines = [line for line in _lines() if not line.startswith(KEYS)]
    lines += [f"FB_LOGIN_EMAIL={email}", f"FB_LOGIN_PASSWORD={password}"]
    _write(lines)
    print("Listo: datos guardados en C:\\LVR\\.env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
