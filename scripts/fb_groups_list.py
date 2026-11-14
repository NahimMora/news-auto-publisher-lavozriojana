"""Lista los grupos donde está la página (sin publicar). Uso: ``--out <json> [--shot <png>]``.

Se pone como la página (``FB_PAGE_ID``) si la sesión todavía está como el
perfil personal, abre la lista de grupos y la recorre con desplazamiento.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from meta.fb_groups_browser import browser

_GROUP_RE = re.compile(r"^https://www\.facebook\.com/groups/([^/?#]+)/?$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--shot")
    args = parser.parse_args()
    with browser() as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.facebook.com/groups/joins/?nav_source=tab", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        found: dict[str, str] = {}
        idle = 0
        for _ in range(80):
            for link in page.eval_on_selector_all(
                'a[href*="/groups/"]',
                "els => els.map(e => [e.href.split('?')[0], (e.innerText || e.getAttribute('aria-label') || '').trim()])",
            ):
                href, name = link
                match = _GROUP_RE.match(href)
                if not match or match.group(1) in {"feed", "joins", "discover", "create", "notifications"}:
                    continue
                name = name.split("\n")[0].strip()
                if name and len(name) > len(found.get(href, "")):
                    found[href] = name
                found.setdefault(href, "")
            before = len(found)
            page.mouse.wheel(0, 3000)
            page.keyboard.press("End")
            page.wait_for_timeout(2500)
            idle = idle + 1 if len(found) == before else 0
            if idle >= 6:
                break
        if args.shot:
            page.screenshot(path=args.shot)
    groups = [{"url": url, "name": name} for url, name in found.items()]
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(groups, handle, ensure_ascii=False, indent=2)
    print(f"{len(groups)} grupos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
