"""Exploración puntual (sin publicar): abre una URL con la sesión de grupos,
guarda captura y botones visibles. Uso: ``--url <url> --out <png> [--click <texto>]``."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from meta.fb_groups_browser import browser
from scripts.fb_groups_login import buttons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--click", action="append", default=[])
    args = parser.parse_args()
    url = args.url.replace("{PAGE_ID}", os.getenv("FB_PAGE_ID", ""))
    with browser() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        for text in args.click:
            scope = page
            if text.startswith("dialog:"):
                scope, text = page.get_by_role("dialog").last, text[len("dialog:"):]
            target = scope.get_by_role("button", name=text).first
            if not target.count():
                target = scope.get_by_text(text, exact=False).first
            target.click(timeout=8000)
            page.wait_for_timeout(5000)
        page.screenshot(path=args.out)
        print(json.dumps({"url": page.url.split("?")[0], "buttons": buttons(page)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
