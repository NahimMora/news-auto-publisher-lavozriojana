"""
Preview pipeline: genera imágenes de las últimas noticias de cada sección
y abre una galería HTML en el navegador para revisión visual.

Uso: python preview_pipeline.py [--n 3]
  --n  cuántas noticias por sección mostrar (default: 2)
"""
import os, sys, json, glob, argparse, webbrowser, base64
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import layout.image_generator as ig_mod
from layout.image_generator import section_color
from PIL import Image

BASE     = os.path.dirname(__file__)
OUT_DIR  = os.path.join(BASE, "output", "preview")
GALLERY  = os.path.join(OUT_DIR, "gallery.html")

SECCIONES = {
    "locales":    {"file": "data/noticias_ejecutadas_locales.json"},
    "deportes":   {"file": "data/noticias_ejecutadas_deportes.json"},
    "policiales": {"file": "data/noticias_ejecutadas_policiales.json"},
    "interior":   {"file": "data/noticias_ejecutadas_interior.json"},
}

# ── Carga artículos ───────────────────────────────────────────
def cargar_articulos(sec, cfg, n):
    path = os.path.join(BASE, cfg["file"])
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    return data[:n]

# ── Loader de imagen: local primero, luego URL ────────────────
def make_loader(article):
    local = article.get("imagen_optimizada") or article.get("imagen") or ""
    url   = article.get("imagen_url", "")

    def _loader(_url):
        if local and os.path.exists(local):
            return Image.open(local).convert("RGBA")
        import requests, io as _io
        try:
            r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return Image.open(_io.BytesIO(r.content)).convert("RGBA")
        except Exception as e:
            print(f"  ⚠ No se pudo descargar imagen: {e}")
            return None
    return _loader

# ── Convierte imagen a data-URI para embeber en HTML ──────────
def img_to_datauri(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/jpeg;base64,{b64}"

# ── Genera HTML de galería ────────────────────────────────────
def build_gallery(items):
    cards = ""
    for item in items:
        ig_uri = img_to_datauri(item["ig_path"])
        fb_uri = img_to_datauri(item["fb_path"])
        sec    = item["seccion"].upper()
        titulo = item["titulo"][:80]
        color  = item["color"]
        cards += f"""
        <div class="card">
          <div class="label" style="background:{color}">{sec}</div>
          <p class="titulo">{titulo}</p>
          <div class="imgs">
            <div><span>Instagram 4:5</span><img src="{ig_uri}"></div>
            <div><span>Facebook 1:1</span><img src="{fb_uri}"></div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Preview — La Voz Riojana</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #111; color: #eee; font-family: Arial, sans-serif; padding: 24px; }}
  h1 {{ text-align: center; margin-bottom: 24px; font-size: 22px; color: #fff; }}
  .card {{ background: #1e1e1e; border-radius: 12px; padding: 18px;
            margin-bottom: 32px; box-shadow: 0 4px 16px rgba(0,0,0,.5); }}
  .label {{ display: inline-block; padding: 4px 14px; border-radius: 99px;
             font-size: 12px; font-weight: bold; color: #fff; margin-bottom: 10px; }}
  .titulo {{ font-size: 15px; color: #ccc; margin-bottom: 14px; line-height: 1.4; }}
  .imgs {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .imgs > div {{ display: flex; flex-direction: column; align-items: center; gap: 6px; }}
  .imgs span {{ font-size: 11px; color: #888; }}
  .imgs img {{ border-radius: 8px; max-height: 420px; width: auto;
               box-shadow: 0 2px 10px rgba(0,0,0,.6); }}
</style>
</head>
<body>
<h1>Preview de publicaciones — La Voz Riojana</h1>
{cards}
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2, help="Noticias por sección")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    items = []

    for sec, cfg in SECCIONES.items():
        articulos = cargar_articulos(sec, cfg, args.n)
        if not articulos:
            print(f"[{sec}] Sin articulos")
            continue

        color = section_color(sec)

        for idx, art in enumerate(articulos):
            titulo = art.get("titulo", "")
            print(f"[{sec}] Generando: {titulo[:60]}")

            ig_mod._download = make_loader(art)
            article = {
                "titulo":    titulo,
                "seccion":   sec.upper(),
                "color":     color,
                "imagen_url": art.get("imagen_url", ""),
                "parrafos":  art.get("parrafos", []),
                "url":       art.get("url", ""),
            }

            slug    = f"{sec}_{idx}"
            ig_path = os.path.join(OUT_DIR, f"{slug}_ig.jpg")
            fb_path = os.path.join(OUT_DIR, f"{slug}_fb.jpg")

            try:
                # IG usa el motor real (Remotion "Editorial Cinemática Riojana" con
                # fallback Pillow) vía generate_instagram_with_engine, igual que el
                # pipeline en vivo — ver docs/DECISIONS.md. FB/OG sigue en Pillow
                # puro (workflow "og", fuera de alcance de este rediseño).
                ig_bytes, ig_engine = ig_mod.generate_instagram_with_engine(article)
                with open(ig_path, "wb") as handle:
                    handle.write(ig_bytes)
                ig_mod.generate_facebook(article).save(fb_path,  "JPEG", quality=92)
                items.append({
                    "seccion": sec, "color": color,
                    "titulo": titulo, "ig_path": ig_path, "fb_path": fb_path,
                })
                print(f"  OK {slug}_ig.jpg (motor={ig_engine})  {slug}_fb.jpg")
            except Exception as e:
                print(f"  ERROR: {e}")

    if not items:
        print("No se generó ninguna imagen.")
        return

    html = build_gallery(items)
    with open(GALLERY, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nGaleria: {GALLERY}")
    webbrowser.open(f"file:///{GALLERY.replace(chr(92), '/')}")

if __name__ == "__main__":
    main()
