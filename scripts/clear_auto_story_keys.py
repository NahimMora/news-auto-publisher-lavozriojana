"""Quita las historias del agrupamiento automático (``storyKey`` que no empieza
con ``event:``) de los posts del CMS y del archivo editorial local.

El agrupamiento automático juntaba hechos distintos y la web los mostraba
como cronología (docs/KNOWN_ISSUES.md, 2026-10-23). Por defecto sólo informa;
con ``--apply`` guarda primero un respaldo (id → storyKey) en
``output/story_keys_backup_<fecha>.json`` y después hace ``PATCH storyKey=null``
post por post. ``--restore <respaldo>`` vuelve a poner las claves.

    python scripts/clear_auto_story_keys.py            # informe
    python scripts/clear_auto_story_keys.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

import requests

from editorial_context.bundle import VERIFIED_STORY_PREFIX
from pipeline.node_webapp.editorial_flags import _patch_post
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir

logger = setup_logger("clear_auto_story_keys", "publish_web.log")


def cms_posts_with_story_key() -> list[dict]:
    base = os.getenv("WEBAPP_BASE_URL", "").rstrip("/")
    out = []
    for page in range(1, 1000):
        response = requests.get(f"{base}/api/public/posts", params={"page": page, "perPage": 50}, timeout=30)
        response.raise_for_status()
        items = (response.json().get("data") or {}).get("items") or []
        if not items:
            break
        out += [{"id": p["id"], "storyKey": p["storyKey"], "title": p.get("title", "")} for p in items if p.get("storyKey")]
    return out


def clear_local(db_path: str) -> int:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.execute(
            "UPDATE archive_articles SET story_key = '', updated_at_ts = ? WHERE story_key != '' AND story_key NOT LIKE ?",
            (time.time(), f"{VERIFIED_STORY_PREFIX}%"),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", default="")
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    if args.restore:
        with open(args.restore, encoding="utf-8") as handle:
            rows = json.load(handle)
        ok = sum(_patch_post(str(r["id"]), {"storyKey": r["storyKey"]}) for r in rows)
        print(f"Restaurados {ok}/{len(rows)}")
        return 0 if ok == len(rows) else 1

    rows = [r for r in cms_posts_with_story_key() if not str(r["storyKey"]).startswith(VERIFIED_STORY_PREFIX)]
    stories = {r["storyKey"] for r in rows}
    print(f"Posts con historia automática: {len(rows)} en {len(stories)} historias")
    if not args.apply:
        print("Sólo informe. Con --apply se respaldan y se quitan.")
        return 0

    backup = os.path.join(str(output_dir()), f"story_keys_backup_{datetime.now():%Y%m%d_%H%M%S}.json")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    with open(backup, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    print(f"Respaldo: {backup}")

    failed = []
    for i, r in enumerate(rows, 1):
        if not _patch_post(str(r["id"]), {"storyKey": None}):
            failed.append(r["id"])
        if args.sleep:
            time.sleep(args.sleep)
        if i % 100 == 0:
            print(f"  {i}/{len(rows)}")
    local = clear_local(str(data_dir() / "derived" / "editorial_context.sqlite3"))
    print(f"CMS: {len(rows) - len(failed)} quitadas, {len(failed)} fallidas {failed[:20]}")
    print(f"Archivo local: {local} notas sin historia automática")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
