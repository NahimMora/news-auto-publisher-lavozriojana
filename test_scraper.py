"""
Ejecuta los 4 scrapers y genera output/scraper_report.html con los resultados.
Uso: python test_scraper.py
"""
import os
import sys
import json
import base64
import datetime
import requests

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from scraping.locales.links_scraper import scrap_links as links_locales
from scraping.locales.noticia_scraper import scrap_noticia as noticia_locales
from scraping.policiales.links_scraper import scrap_links as links_policiales
from scraping.policiales.noticia_scraper import scrap_noticia as noticia_policiales
from scraping.interior.links_scraper import scrap_links as links_interior
from scraping.interior.noticia_scraper import scrap_noticia as noticia_interior
from scraping.deportes.links_scraper import scrap_links as links_deportes
from scraping.deportes.noticia_scraper import scrap_noticia as noticia_deportes

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SECTIONS = [
    {
        "name": "locales",
        "label": "Locales",
        "url": "https://www.tiempopopular.com.ar/locales/",
        "color": "#2563eb",
        "links_fn": links_locales,
        "noticia_fn": noticia_locales,
    },
    {
        "name": "policiales",
        "label": "Policiales",
        "url": "https://www.tiempopopular.com.ar/policiales/",
        "color": "#dc2626",
        "links_fn": links_policiales,
        "noticia_fn": noticia_policiales,
    },
    {
        "name": "interior",
        "label": "Interior",
        "url": "https://www.tiempopopular.com.ar/interior-2/",
        "color": "#16a34a",
        "links_fn": links_interior,
        "noticia_fn": noticia_interior,
    },
    {
        "name": "deportes",
        "label": "Deportes",
        "url": "https://www.tiempopopular.com.ar/deportes/",
        "color": "#d97706",
        "links_fn": links_deportes,
        "noticia_fn": noticia_deportes,
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def image_to_base64(url: str) -> str:
    """Descarga imagen y la convierte a base64 para embeber en HTML."""
    if not url:
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        b64 = base64.b64encode(r.content).decode()
        return f"data:{ct};base64,{b64}"
    except Exception:
        return ""


def run_scraping() -> dict:
    results = {
        "timestamp": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "sections": [],
    }

    for sec in SECTIONS:
        print(f"\n[{sec['label']}] Scrapeando links...")
        links = sec["links_fn"]()
        print(f"  -> {len(links)} links encontrados")

        articles = []
        for i, url in enumerate(links):
            print(f"  [{i+1}/{len(links)}] {url[:80]}")
            noticia = sec["noticia_fn"](url)
            if noticia:
                # Embeber imagen como base64 para el HTML estático
                img_b64 = image_to_base64(noticia.get("imagen_url", ""))
                articles.append({
                    "titulo": noticia.get("titulo", ""),
                    "url": noticia.get("url", ""),
                    "fecha": noticia.get("fecha", ""),
                    "parrafos": noticia.get("parrafos", [])[:2],
                    "imagen_url": noticia.get("imagen_url", ""),
                    "imagen_b64": img_b64,
                    "tiene_imagen": bool(noticia.get("imagen_url")),
                    "parrafos_count": len(noticia.get("parrafos", [])),
                    "ok": True,
                })
            else:
                articles.append({
                    "titulo": "ERROR - No se pudo scrapear",
                    "url": url,
                    "fecha": "",
                    "parrafos": [],
                    "imagen_url": "",
                    "imagen_b64": "",
                    "tiene_imagen": False,
                    "parrafos_count": 0,
                    "ok": False,
                })

        results["sections"].append({
            "name": sec["name"],
            "label": sec["label"],
            "source_url": sec["url"],
            "color": sec["color"],
            "links_found": len(links),
            "articles_ok": sum(1 for a in articles if a["ok"]),
            "articles": articles,
        })
        print(f"  OK: {sum(1 for a in articles if a['ok'])}/{len(articles)}")

    return results


def generate_html(data: dict) -> str:
    total_articles = sum(s["links_found"] for s in data["sections"])
    total_ok = sum(s["articles_ok"] for s in data["sections"])
    total_images = sum(
        1 for s in data["sections"] for a in s["articles"] if a["tiene_imagen"]
    )

    sections_html = ""
    for sec in data["sections"]:
        cards_html = ""
        for art in sec["articles"]:
            img_html = ""
            if art["imagen_b64"]:
                img_html = f'<img src="{art["imagen_b64"]}" alt="" loading="lazy">'
            elif art["imagen_url"]:
                img_html = f'<img src="{art["imagen_url"]}" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
            else:
                img_html = '<div class="no-image">Sin imagen</div>'

            status_class = "ok" if art["ok"] else "error"
            status_label = "OK" if art["ok"] else "ERROR"

            parrafos_html = ""
            for p in art["parrafos"]:
                parrafos_html += f"<p>{p}</p>"

            cards_html += f"""
            <div class="card {status_class}">
              <div class="card-img">{img_html}</div>
              <div class="card-body">
                <div class="card-meta">
                  <span class="badge" style="background:{sec['color']}">{sec['label']}</span>
                  <span class="status-badge {status_class}">{status_label}</span>
                  {f'<span class="date">{art["fecha"]}</span>' if art["fecha"] else ""}
                  <span class="pcount">{art["parrafos_count"]} párrafos</span>
                  {'<span class="img-check">✓ Imagen</span>' if art["tiene_imagen"] else '<span class="img-check miss">✗ Sin imagen</span>'}
                </div>
                <h3 class="card-title"><a href="{art['url']}" target="_blank">{art['titulo']}</a></h3>
                <div class="card-text">{parrafos_html}</div>
                <a class="source-link" href="{art['url']}" target="_blank">{art['url']}</a>
              </div>
            </div>"""

        sections_html += f"""
        <section class="section" id="{sec['name']}">
          <div class="section-header" style="border-color:{sec['color']}">
            <h2 style="color:{sec['color']}">{sec['label']}</h2>
            <div class="section-stats">
              <span>Links encontrados: <strong>{sec['links_found']}</strong></span>
              <span>Scrapeados OK: <strong>{sec['articles_ok']}/{sec['links_found']}</strong></span>
              <a href="{sec['source_url']}" target="_blank" class="src-link">Ver fuente →</a>
            </div>
          </div>
          <div class="cards-grid">{cards_html}</div>
        </section>"""

    nav_links = "".join(
        f'<a href="#{s["name"]}" style="color:{s["color"]}">{s["label"]} ({s["links_found"]})</a>'
        for s in data["sections"]
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test de Scraping — La Voz Riojana</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f1117;
      color: #e2e8f0;
      min-height: 100vh;
    }}

    /* ── HEADER ── */
    .site-header {{
      background: #1a1d2e;
      border-bottom: 1px solid #2d3148;
      padding: 20px 32px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .site-header h1 {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.02em;
    }}
    .site-header h1 span {{ color: #6366f1; }}
    .site-header .timestamp {{
      font-size: 0.8rem;
      color: #64748b;
      margin-top: 2px;
    }}

    /* ── STATS BAR ── */
    .stats-bar {{
      display: flex;
      gap: 16px;
      padding: 18px 32px;
      background: #13151f;
      border-bottom: 1px solid #1e2235;
      flex-wrap: wrap;
      align-items: center;
    }}
    .stat-card {{
      background: #1a1d2e;
      border: 1px solid #2d3148;
      border-radius: 10px;
      padding: 12px 20px;
      text-align: center;
      min-width: 110px;
    }}
    .stat-card .num {{
      font-size: 1.8rem;
      font-weight: 800;
      color: #a5b4fc;
      line-height: 1;
    }}
    .stat-card .lbl {{
      font-size: 0.7rem;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-top: 4px;
    }}

    /* ── NAV ── */
    .section-nav {{
      display: flex;
      gap: 20px;
      padding: 14px 32px;
      background: #13151f;
      border-bottom: 1px solid #1e2235;
      flex-wrap: wrap;
    }}
    .section-nav a {{
      font-size: 0.85rem;
      font-weight: 600;
      text-decoration: none;
      opacity: 0.85;
      transition: opacity .15s;
    }}
    .section-nav a:hover {{ opacity: 1; text-decoration: underline; }}

    /* ── MAIN ── */
    main {{ padding: 32px; max-width: 1400px; margin: 0 auto; }}

    .section {{ margin-bottom: 52px; }}
    .section-header {{
      border-left: 4px solid;
      padding-left: 14px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 24px;
      flex-wrap: wrap;
    }}
    .section-header h2 {{ font-size: 1.25rem; font-weight: 700; }}
    .section-stats {{
      display: flex;
      gap: 16px;
      font-size: 0.82rem;
      color: #94a3b8;
      align-items: center;
      flex-wrap: wrap;
    }}
    .section-stats strong {{ color: #e2e8f0; }}
    .src-link {{
      color: #818cf8;
      text-decoration: none;
      font-size: 0.8rem;
    }}
    .src-link:hover {{ text-decoration: underline; }}

    /* ── CARDS GRID ── */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 18px;
    }}

    .card {{
      background: #1a1d2e;
      border: 1px solid #2d3148;
      border-radius: 12px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: transform .15s, box-shadow .15s;
    }}
    .card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(0,0,0,.4);
    }}
    .card.error {{
      border-color: #7f1d1d;
      background: #1c1010;
    }}

    .card-img {{
      width: 100%;
      aspect-ratio: 16/9;
      overflow: hidden;
      background: #0f1117;
    }}
    .card-img img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .no-image {{
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #334155;
      font-size: 0.8rem;
      background: #0f1117;
    }}

    .card-body {{
      padding: 14px 16px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      flex: 1;
    }}

    .card-meta {{
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .badge {{
      font-size: 0.68rem;
      font-weight: 700;
      color: #fff;
      padding: 2px 8px;
      border-radius: 99px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .status-badge {{
      font-size: 0.68rem;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 99px;
    }}
    .status-badge.ok {{ background: #14532d; color: #86efac; }}
    .status-badge.error {{ background: #7f1d1d; color: #fca5a5; }}
    .date {{ font-size: 0.72rem; color: #64748b; }}
    .pcount {{ font-size: 0.72rem; color: #64748b; margin-left: auto; }}
    .img-check {{ font-size: 0.72rem; color: #22c55e; }}
    .img-check.miss {{ color: #ef4444; }}

    .card-title {{
      font-size: 0.95rem;
      font-weight: 700;
      line-height: 1.35;
      color: #e2e8f0;
    }}
    .card-title a {{
      color: inherit;
      text-decoration: none;
    }}
    .card-title a:hover {{ color: #a5b4fc; }}

    .card-text {{
      font-size: 0.8rem;
      color: #94a3b8;
      line-height: 1.55;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .card-text p + p {{ margin-top: 6px; }}

    .source-link {{
      font-size: 0.7rem;
      color: #475569;
      word-break: break-all;
      text-decoration: none;
      margin-top: auto;
    }}
    .source-link:hover {{ color: #818cf8; }}

    /* ── FOOTER ── */
    footer {{
      text-align: center;
      padding: 24px;
      font-size: 0.75rem;
      color: #334155;
      border-top: 1px solid #1e2235;
    }}
  </style>
</head>
<body>

<header class="site-header">
  <h1>La Voz Riojana <span>— Test de Scraping</span></h1>
  <p class="timestamp">Generado: {data["timestamp"]} · Fuente: tiempopopular.com.ar</p>
</header>

<div class="stats-bar">
  <div class="stat-card">
    <div class="num">{total_articles}</div>
    <div class="lbl">Links totales</div>
  </div>
  <div class="stat-card">
    <div class="num">{total_ok}</div>
    <div class="lbl">Scrapeados OK</div>
  </div>
  <div class="stat-card">
    <div class="num">{total_images}</div>
    <div class="lbl">Con imagen</div>
  </div>
  <div class="stat-card">
    <div class="num">{len(data["sections"])}</div>
    <div class="lbl">Secciones</div>
  </div>
</div>

<nav class="section-nav">
  {nav_links}
</nav>

<main>
  {sections_html}
</main>

<footer>
  AutoPublicador La Voz Riojana · test_scraper.py
</footer>

</body>
</html>"""


def main():
    print("=" * 60)
    print("  La Voz Riojana - Test de Scraping")
    print("=" * 60)

    data = run_scraping()

    total = sum(s["links_found"] for s in data["sections"])
    ok = sum(s["articles_ok"] for s in data["sections"])
    print(f"\nResumen: {ok}/{total} artículos scrapeados correctamente")

    print("\nGenerando HTML...")
    html = generate_html(data)

    report_path = os.path.join(OUTPUT_DIR, "scraper_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Reporte generado: {report_path}")
    print("Abrí ese archivo en tu navegador para ver los resultados.")

    # Intentar abrir en el navegador automáticamente
    try:
        import webbrowser
        webbrowser.open(f"file:///{report_path.replace(chr(92), '/')}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
