"""Galería local de comparación V1 / V2 (Visual System V2).

QA read-only: no publica, no toca colas ni ``data/``. Lee fotos y videos ya
descargados (``--fotos-dir`` / ``--videos-dir``), arma los props de V1 con la
MISMA lógica que producción (``layout/image_generator.py`` y
``utils/video_renderer.py``) y los de V2 con ``utils/visual_v2_props.py``,
renderiza ambas versiones con los mismos datos y genera ``index.html``.

Uso:
    python scripts/visual_v2_gallery.py --fotos-dir C:\\LVR\\FotosLVR \\
        --videos-dir C:\\LVR\\output\\renders --out output\\visual_v2_gallery
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

CASES_PATH = ROOT / "tests" / "fixtures" / "visual_v2" / "cases.json"
REMOTION_DIR = ROOT / "remotion"
IMAGE_REEL_SECONDS = 10
NO_ASSET_REEL_SECONDS = 8


def _npx(args: list[str]) -> list[str]:
    return ["cmd", "/c", *args] if os.name == "nt" else args


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(data["format"]["duration"])


def _trim(src: Path, dest: Path, seconds: int) -> None:
    if dest.exists():
        return
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", str(seconds), "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-r", "30", "-c:a", "aac", "-b:a", "160k", str(dest)],
        check=True,
    )


def _v1_reel_props(item: dict, frames: int, asset_type: str) -> dict:
    """Espejo de utils/video_renderer.py::_render_remotion_main (cinematic_style=True)."""
    from openIA.caption_generator import select_highlight_phrase

    titulo = str(item.get("titulo_reel") or item.get("titulo") or "").upper()
    terms = item.get("highlight_terms") or []
    terms = [str(t).strip() for t in terms if str(t).strip()][:2]
    if not terms:
        selected = select_highlight_phrase(titulo)
        terms = [selected] if selected else []
    return {
        "titulo": titulo,
        "seccion": str(item.get("seccion") or "sociedad").upper(),
        "assetType": asset_type,
        "assetFile": "",
        "kenBurnsVariant": 0,
        "durationInFrames": frames,
        "highlightTerms": terms,
    }


def _v1_instagram_props(item: dict, orientation: str | None) -> dict:
    """Espejo de layout/image_generator.py::_generate_instagram_remotion con
    el paquete visual compartido activo (estado productivo actual)."""
    from layout.image_generator import _deck_for_render, _visual_highlight_terms

    props = {
        "titulo": item.get("titulo", ""),
        "seccion": item.get("seccion", ""),
        "assetFile": "",
        "highlightTerms": _visual_highlight_terms(item, publication_visual_style=True),
        "locality": str(item.get("locality") or ""),
        "deck": _deck_for_render(item),
        "imageTreatment": "auto",
        "publicationStyle": "manual_publication",
    }
    if orientation:
        props["assetOrientation"] = orientation
    return props


def _v1_og_props(item: dict) -> dict:
    """Espejo de pipeline/node_webapp/media.py + _generate_facebook_remotion."""
    from layout.image_generator import _visual_highlight_terms

    article = dict(item)
    article["titulo"] = item.get("titulo_instagram") or item.get("titulo") or ""
    return {
        "titulo": article["titulo"],
        "seccion": item.get("seccion", ""),
        "assetFile": "",
        "highlightTerms": _visual_highlight_terms(article, publication_visual_style=True),
        "publicationStyle": "manual_publication",
    }


def build_jobs(cases: list[dict], fotos_dir: Path, videos_dir: Path, out: Path, work: Path) -> tuple[list[dict], dict]:
    from PIL import Image

    from utils.visual_v2_props import instagram_props_v2, og_props_v2, reel_props_v2

    jobs: list[dict] = []
    meta: dict = {}
    for case in cases:
        cid = case["id"]
        item = case["item"]
        photo = fotos_dir / case["photo"] if case.get("photo") else None
        size = None
        orientation = None
        if photo and photo.is_file():
            with Image.open(photo) as im:
                size = im.size
            orientation = "landscape" if size[0] > size[1] else "portrait" if size[1] > size[0] else "square"
        else:
            photo = None
        info = {"label": case["label"], "notes": case.get("notes", ""), "item": item, "photo_size": size, "outputs": {}}

        if not case.get("video"):
            assets = {"assetFile": str(photo)} if photo else {}
            v2_ig = instagram_props_v2(item, asset_file="", asset_size=size)
            v2_og = og_props_v2(item, asset_file="")
            for version, comp, props, scale in (
                ("v1", "AutomaticInstagramCard", _v1_instagram_props(item, orientation), 2),
                ("v2", "AutomaticInstagramCardV2", v2_ig, 2),
            ):
                jobs.append({"id": f"{cid}__ig_{version}", "kind": "still", "compositionId": comp, "props": props, "assetPaths": assets, "out": str(work / f"{cid}__ig_{version}.png"), "scale": scale})
            for version, comp, props in (("v1", "FacebookOgCard", _v1_og_props(item)), ("v2", "FacebookOgCardV2", v2_og)):
                jobs.append({"id": f"{cid}__og_{version}", "kind": "still", "compositionId": comp, "props": props, "assetPaths": assets, "out": str(work / f"{cid}__og_{version}.png"), "scale": 1})
            info["v2_ig_props"] = v2_ig
            info["v2_og_props"] = v2_og

        if case.get("reel"):
            if case.get("video"):
                clip = work / f"{cid}_clip.mp4"
                _trim(videos_dir / case["video"], clip, int(case.get("clip_seconds") or 12))
                w, h, dur = _probe(clip)
                seconds = max(3, min(90, int(dur)))
                asset_type, asset_path, asset_size = "video", clip, (w, h)
            elif photo:
                seconds, asset_type, asset_path, asset_size = IMAGE_REEL_SECONDS, "image", photo, size
            else:
                seconds, asset_type, asset_path, asset_size = NO_ASSET_REEL_SECONDS, "none", None, None
            frames = seconds * 30
            assets = {"assetFile": str(asset_path)} if asset_path else {}
            v2 = reel_props_v2(item, duration_frames=frames, asset_type=asset_type, asset_file="x" if asset_path else "", asset_size=asset_size)
            for version, comp, props in (
                ("v1", "EditorialReel", _v1_reel_props(item, frames, asset_type if asset_path else "none")),
                ("v2", "EditorialReelV2", v2),
            ):
                jobs.append({"id": f"{cid}__reel_{version}", "kind": "video", "compositionId": comp, "props": props, "assetPaths": assets, "out": str(out / "reels" / f"{cid}__reel_{version}.mp4")})
            info["reel"] = {"seconds": seconds, "asset_type": asset_type, "asset_size": asset_size, "v2_props": v2}
        meta[cid] = info
    return jobs, meta


def postprocess(jobs: list[dict], results: dict, out: Path) -> None:
    from PIL import Image

    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for job in jobs:
        res = results.get(job["id"]) or {}
        if not res.get("ok"):
            continue
        if job["kind"] == "still":
            src = Path(job["out"])
            if not src.exists():
                continue
            dest = out / "images" / f"{job['id']}.jpg"
            with Image.open(src) as im:
                # Mismas opciones JPEG que producción (calidad 95, 4:4:4).
                im.convert("RGB").save(dest, "JPEG", quality=95, subsampling=0, optimize=True)
            res["file"] = f"images/{dest.name}"
            res["size"] = list(Image.open(dest).size)
        else:
            mp4 = Path(job["out"])
            res["file"] = f"reels/{mp4.name}"
            w, h, dur = _probe(mp4)
            res["size"] = [w, h]
            res["duration"] = dur
            body = job["props"]["durationInFrames"] / 30
            times = [0.15, 0.6, 1.2, 1.9, 2.6, 4.0, min(body * 0.6, body - 1), max(0.5, body - 0.4), body + 0.5, body + 1.4]
            frames = []
            for t in sorted({round(x, 2) for x in times if 0 <= x < dur}):
                dest = out / "frames" / f"{job['id']}_{int(t * 1000):06d}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-i", str(mp4), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "3", str(dest)], check=True)
                frames.append({"t": t, "file": f"frames/{dest.name}"})
            res["frames"] = frames


def write_html(cases: list[dict], meta: dict, results: dict, out: Path) -> None:
    def media(job_id: str, kind: str) -> str:
        res = results.get(job_id)
        if not res:
            return '<div class="missing">no aplica</div>'
        if not res.get("ok"):
            return f'<div class="missing">render falló: {html.escape(res.get("error", ""))}</div>'
        cap = f'{res["ms"] / 1000:.1f} s de render · {res["size"][0]}×{res["size"][1]}'
        if kind == "video":
            strip = "".join(f'<figure><img loading="lazy" src="{f["file"]}"><figcaption>{f["t"]:.1f}s</figcaption></figure>' for f in res.get("frames", []))
            return f'<video controls preload="metadata" src="{res["file"]}"></video><p class="cap">{cap}</p><div class="strip">{strip}</div>'
        return f'<a href="{res["file"]}" target="_blank"><img loading="lazy" src="{res["file"]}"></a><p class="cap">{cap}</p>'

    rows = []
    for case in cases:
        cid = case["id"]
        m = meta[cid]
        it = m["item"]
        facts = " · ".join(html.escape(str(x)) for x in [it.get("seccion"), it.get("locality"), f'foto {m["photo_size"][0]}×{m["photo_size"][1]}' if m.get("photo_size") else "sin foto"] if x)
        block = [f'<section id="{cid}"><h2>{html.escape(m["label"])}</h2><p class="facts">{facts}</p>']
        block.append(f'<p class="title">“{html.escape(str(it.get("titulo", "")))}”</p>')
        if it.get("deck"):
            block.append(f'<p class="deck">Bajada: {html.escape(str(it["deck"]))}</p>')
        if m.get("notes"):
            block.append(f'<p class="note">{html.escape(m["notes"])}</p>')
        for kind, label, cls in (("ig", "Post Instagram 1080×1350 (render 2×)", "ig"), ("og", "Open Graph 1200×630", "og"), ("reel", "Reel 1080×1920", "reel")):
            if f"{cid}__{kind}_v1" not in results and f"{cid}__{kind}_v2" not in results:
                continue
            k = "video" if kind == "reel" else "still"
            block.append(f'<h3>{label}</h3><div class="pair {cls}"><div><h4>V1 · actual</h4>{media(f"{cid}__{kind}_v1", k)}</div><div><h4>V2 · propuesta</h4>{media(f"{cid}__{kind}_v2", k)}</div></div>')
        block.append("</section>")
        rows.append("".join(block))

    perf = {}
    for job_id, res in results.items():
        if not res.get("ok"):
            continue
        _, kv = job_id.split("__")
        kind, version = kv.rsplit("_", 1)
        perf.setdefault(kind, {}).setdefault(version, []).append(res["ms"])
    perf_rows = "".join(
        f"<tr><td>{k}</td>" + "".join(f"<td>{sum(v.get(ver, [0])) / max(1, len(v.get(ver, []))) / 1000:.1f} s</td>" for ver in ("v1", "v2")) + "</tr>"
        for k, v in sorted(perf.items())
    )
    nav = "".join(f'<a href="#{c["id"]}">{html.escape(meta[c["id"]]["label"])}</a>' for c in cases)
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galería V1 / V2</title><style>
:root{{--bg:#0e1116;--fg:#e9e6df;--mute:#9aa1ab;--line:#262c36;--red:#B30000}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
header{{padding:28px 24px 8px;border-bottom:1px solid var(--line)}} h1{{margin:0 0 6px;font-size:24px}}
nav{{display:flex;flex-wrap:wrap;gap:8px;padding:12px 24px;position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);z-index:2}}
nav a{{color:var(--fg);text-decoration:none;font-size:13px;padding:4px 8px;border:1px solid var(--line)}}
section{{padding:24px;border-bottom:1px solid var(--line)}} h2{{margin:0;font-size:20px}} h3{{margin:22px 0 8px;font-size:15px;color:var(--mute);font-weight:600}}
h4{{margin:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase}} .pair>div:last-child h4{{color:#ff6b5e}}
.facts,.cap,.deck{{color:var(--mute);margin:4px 0}} .title{{font-size:17px;margin:8px 0}} .note{{color:#f2c46b;margin:4px 0}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}} .pair img,.pair video{{width:100%;height:auto;display:block;background:#000}}
.ig img{{max-width:460px}} .reel video{{max-width:360px}} .og img{{max-width:600px}}
.strip{{display:flex;gap:6px;overflow-x:auto;margin-top:8px}} .strip figure{{margin:0;flex:0 0 96px}} .strip img{{width:96px}} .strip figcaption{{font-size:11px;color:var(--mute);text-align:center}}
.missing{{color:var(--mute);padding:20px;border:1px dashed var(--line)}} table{{border-collapse:collapse;margin:8px 0 16px}} td,th{{border:1px solid var(--line);padding:6px 12px;text-align:left}}
@media (max-width:760px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>La Voz Riojana — Visual System V1 vs V2</h1>
<p class="facts">Galería local de QA. Mismos datos y mismos archivos multimedia en cada par. Nada de esto se publicó.</p>
<table><tr><th>Pieza</th><th>V1 promedio</th><th>V2 promedio</th></tr>{perf_rows}</table></header>
<nav>{nav}</nav>{''.join(rows)}</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Galería local V1/V2 (no publica nada)")
    parser.add_argument("--fotos-dir", required=True, type=Path)
    parser.add_argument("--videos-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "visual_v2_gallery")
    parser.add_argument("--only", default="", help="regex sobre el id de trabajo")
    parser.add_argument("--html-only", action="store_true")
    args = parser.parse_args()

    out = args.out.resolve()
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    jobs, meta = build_jobs(cases, args.fotos_dir, args.videos_dir, out, work)
    jobs_path = work / "jobs.json"
    results_path = out / "results.json"
    jobs_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "cases_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    if not args.html_only:
        env = dict(os.environ)
        if args.only:
            env["ONLY"] = args.only
        subprocess.run(_npx(["node", "scripts/render_compare.mjs", str(jobs_path), str(results_path)]), cwd=REMOTION_DIR, env=env, check=True)

    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    postprocess(jobs, results, out)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(cases, meta, results, out)
    failed = [k for k, v in results.items() if not v.get("ok")]
    print(f"Galería: {out / 'index.html'} — {len(results)} renders, {len(failed)} fallidos")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
