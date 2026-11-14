"""Importa la sesión de Facebook del navegador del operador al perfil de grupos.

Uso: ``python scripts/fb_groups_cookies.py --paste`` (pegar el contenido en la
terminal y terminar con una línea que diga FIN) o ``--file <ruta>``.

Acepta el ``cookies.txt`` de "Get cookies.txt LOCALLY" (formato Netscape) o el
JSON de "Cookie-Editor". Sólo toma cookies de facebook.com. Verifica que la
sesión sirva y borra el archivo (es un secreto). Nunca imprime valores.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from meta.fb_groups_browser import browser, logged_in

_SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict", "unspecified": "Lax"}
_EOL = "\r\n"


def parse(text: str) -> list[dict]:
    cookies: list[dict] = []
    stripped = text.strip()
    if stripped.startswith("["):
        for c in json.loads(stripped):
            cookies.append({
                "name": c["name"], "value": c["value"], "domain": c.get("domain", ".facebook.com"),
                "path": c.get("path", "/"), "secure": bool(c.get("secure", True)), "httpOnly": bool(c.get("httpOnly", False)),
                "sameSite": _SAMESITE.get(str(c.get("sameSite") or "lax").lower(), "Lax"),
                **({"expires": float(c["expirationDate"])} if c.get("expirationDate") else {}),
            })
    else:
        for line in stripped.splitlines():
            http_only = line.startswith("#HttpOnly_")
            if line.startswith("#") and not http_only:
                continue
            parts = line.replace("#HttpOnly_", "", 1).split("\t")
            if len(parts) != 7:
                continue
            domain, _flag, path, secure, expires, name, value = parts
            cookies.append({
                "name": name, "value": value, "domain": domain, "path": path, "secure": secure.upper() == "TRUE",
                "httpOnly": http_only, "sameSite": "None" if secure.upper() == "TRUE" else "Lax",
                **({"expires": float(expires)} if expires not in ("0", "") else {}),
            })
    return [c for c in cookies if c["domain"].lstrip(".").endswith("facebook.com")]


def _read_pasted() -> str:
    print("Pegá el contenido exportado y, en una línea aparte, escribí FIN y Enter:")
    lines = []
    for line in sys.stdin:
        if line.strip() == "FIN":
            break
        lines.append(line.rstrip(_EOL))
    return chr(10).join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--paste", action="store_true")
    parser.add_argument("--keep", action="store_true", help="no borrar el archivo (sólo para pruebas)")
    args = parser.parse_args()
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if args.paste:
        raw = _read_pasted()
    elif args.file:
        with open(args.file, encoding="utf-8-sig") as handle:
            raw = handle.read()
    else:
        parser.error("usar --paste o --file")
    cookies = parse(raw)
    names = {c["name"] for c in cookies}
    if not {"c_user", "xs"} <= names:
        print("No encuentro una sesión de Facebook (faltan c_user/xs). ¿Estabas logueado al exportar?")
        return 2
    shot_dir = os.path.join(base, "fb_groups")
    os.makedirs(shot_dir, exist_ok=True)
    with browser() as context:
        context.clear_cookies()
        context.add_cookies(cookies)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        ok = logged_in(context) and "login" not in page.url and "checkpoint" not in page.url
        page.screenshot(path=os.path.join(shot_dir, "after_import.png"))
    if args.file and not args.keep:
        os.remove(args.file)
    print("Sesión importada y verificada." if ok else "Facebook no aceptó la sesión importada.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
