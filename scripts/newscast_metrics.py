"""Métricas de las ediciones publicadas del Noticiero (sólo lectura).

Lee ``data/nightly_newscast_state.json`` (``ig_id`` por día) y consulta en la
Graph API de Instagram los insights de cada Reel: reproducciones, cuentas
alcanzadas, tiempo promedio de visualización, me gusta, comentarios,
compartidos y guardados. Calcula el porcentaje medio visto contra la duración
real del MP4 y los compartidos+guardados cada 1000 cuentas, para comparar
ediciones con noticias distintas (ver docs/NIGHTLY_NEWSCAST.md § V5 →
Métricas). La retención por segundo y la tasa de omisión sólo están en la app.

Uso:
    python scripts/newscast_metrics.py            # todas las ediciones con ig_id
    python scripts/newscast_metrics.py --json     # salida en JSON
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import requests  # noqa: E402

from meta.ig_client import GRAPH_API, IG_ACCESS_TOKEN  # noqa: E402
from utils import nightly_newscast as nn  # noqa: E402

METRICS = "views,reach,ig_reels_avg_watch_time,ig_reels_video_view_total_time,likes,comments,shares,saved"


def fetch(media_id: str) -> dict:
    try:
        response = requests.get(f"{GRAPH_API}/{media_id}/insights", params={"metric": METRICS, "access_token": IG_ACCESS_TOKEN}, timeout=30)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": type(exc).__name__}
    if "data" not in data:
        return {"error": (data.get("error") or {}).get("message", "sin datos")[:120]}
    return {item["name"]: item["values"][0]["value"] for item in data["data"]}


def duration(path: str) -> float | None:
    if not path or not os.path.isfile(path):
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Métricas del Noticiero (sólo lectura)")
    parser.add_argument("--json", action="store_true")
    opts = parser.parse_args()
    rows = []
    for day, record in sorted(nn.load_state().items()):
        if not record.get("ig_id"):
            continue
        m = fetch(record["ig_id"])
        seconds = duration(record.get("video", ""))
        avg = (m.get("ig_reels_avg_watch_time") or 0) / 1000
        reach = m.get("reach") or 0
        rows.append({
            "dia": day, "ig_id": record["ig_id"], "duracion_s": round(seconds, 1) if seconds else None, **m,
            "visto_promedio_s": round(avg, 1), "visto_promedio_pct": round(100 * avg / seconds, 1) if seconds else None,
            "compartidos_guardados_x1000": round(1000 * ((m.get("shares") or 0) + (m.get("saved") or 0)) / reach, 1) if reach else None,
        })
    if opts.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    for r in rows:
        if "error" in r:
            print(f"{r['dia']}  error: {r['error']}")
            continue
        print(f"{r['dia']}  {r['duracion_s']} s  alcance {r.get('reach')}  reproducciones {r.get('views')}  "
              f"visto {r['visto_promedio_s']} s ({r['visto_promedio_pct']} %)  me gusta {r.get('likes')}  "
              f"comentarios {r.get('comments')}  compartidos {r.get('shares')}  guardados {r.get('saved')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
