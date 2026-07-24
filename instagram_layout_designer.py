"""
Genera output/instagram_layout.html — diseñador visual de layout Instagram.
Uso: python instagram_layout_designer.py
"""
import json, os, sys, webbrowser, base64

sys.path.insert(0, os.path.dirname(__file__))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
OUT_FILE = os.path.join(OUT_DIR, "instagram_layout.html")

SECTIONS = [
    ("locales",    "Locales",    "#2563eb"),
    ("policiales", "Policiales", "#dc2626"),
    ("interior",   "Interior",   "#16a34a"),
    ("deportes",   "Deportes",   "#d97706"),
]

def load_articles():
    arts = []
    for key, label, color in SECTIONS:
        path = os.path.join(DATA_DIR, f"noticias_ejecutadas_{key}.json")
        if not os.path.exists(path): continue
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        for it in items:
            arts.append({
                "titulo":     it.get("titulo", ""),
                "parrafo":    (it.get("parrafos") or [""])[0],
                "imagen_url": it.get("imagen_url", ""),
                "url":        it.get("url", ""),
                "fecha":      it.get("fecha", ""),
                "seccion":    label,
                "color":      color,
            })
    return arts

LOGO_PATH = os.path.join(os.path.dirname(__file__), "data", "media", "logo.png")

def _logo_b64():
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    return ""

def build_html(articles):
    data_json = json.dumps(articles, ensure_ascii=False)
    logo_src  = _logo_b64()
    logo_img  = f'<img src="{logo_src}" style="width:100%;height:auto;display:block">' if logo_src else "LOGO"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Diseñador Instagram · La Voz Riojana</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0c0e18;--panel:#13162a;--panel2:#1a1d2e;--border:#252840;
  --text:#e2e8f0;--muted:#5a6480;--accent:#6366f1;
}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;overflow:hidden}}

.hdr{{background:var(--panel);border-bottom:1px solid var(--border);
      padding:11px 22px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}}
.hdr-title{{font-size:.92rem;font-weight:700}}.hdr-title span{{color:var(--accent)}}
.hdr-sub{{font-size:.7rem;color:var(--muted)}}
.workspace{{display:flex;flex:1;overflow:hidden}}
.sidebar{{width:268px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);
          overflow-y:auto;padding:14px 13px;display:flex;flex-direction:column;gap:15px}}
.sidebar::-webkit-scrollbar{{width:3px}}
.sidebar::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
.sb-lbl{{font-size:.63rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
          color:var(--muted);margin-bottom:3px}}
.field{{display:flex;flex-direction:column;gap:4px}}
.field label{{font-size:.74rem;color:#8892a4;display:flex;justify-content:space-between}}
.field label b{{color:var(--text);font-weight:600}}
input[type=range]{{accent-color:var(--accent);width:100%;cursor:pointer}}
input[type=color]{{width:100%;height:28px;border:1px solid var(--border);border-radius:6px;
                   background:none;cursor:pointer;padding:2px}}
.filters{{display:flex;flex-wrap:wrap;gap:5px}}
.fbtn{{font-size:.7rem;font-weight:600;padding:3px 9px;border-radius:99px;
       border:1.5px solid var(--border);background:none;color:var(--muted);cursor:pointer;transition:.12s}}
.fbtn.on{{color:#fff;background:#1e2140;border-color:var(--accent)}}
.nav-row{{display:flex;align-items:center;gap:8px}}
.nb{{background:var(--panel2);border:1px solid var(--border);border-radius:7px;color:var(--text);
     width:32px;height:32px;font-size:.95rem;cursor:pointer;display:flex;align-items:center;
     justify-content:center;flex-shrink:0;transition:.12s}}
.nb:hover{{background:var(--border)}}
.nc{{flex:1;text-align:center;font-size:.78rem;color:var(--muted)}}
.trow{{display:flex;align-items:center;justify-content:space-between}}
.trow .tlbl{{font-size:.74rem;color:#8892a4}}
.tog{{position:relative;width:34px;height:18px;flex-shrink:0}}
.tog input{{opacity:0;width:0;height:0}}
.tog-sl{{position:absolute;inset:0;background:#252840;border-radius:99px;cursor:pointer;transition:.2s}}
.tog-sl::before{{content:'';position:absolute;width:12px;height:12px;left:3px;bottom:3px;
                 background:#fff;border-radius:50%;transition:.2s}}
.tog input:checked+.tog-sl{{background:var(--accent)}}
.tog input:checked+.tog-sl::before{{transform:translateX(16px)}}
.sz-row{{display:flex;gap:6px}}
.sz-btn{{flex:1;background:var(--panel2);border:1.5px solid var(--border);border-radius:7px;
         padding:6px 4px;font-size:.72rem;color:var(--muted);cursor:pointer;text-align:center;
         line-height:1.4;transition:.12s}}
.sz-btn.on{{border-color:var(--accent);color:#fff;background:#1e2140}}
.divider{{border:none;border-top:1px solid var(--border)}}
.canvas{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
         gap:16px;overflow:auto;padding:20px}}
.post-wrap{{display:flex;align-items:center;gap:12px}}
.pnav{{background:var(--panel);border:1px solid var(--border);border-radius:7px;color:#94a3b8;
       font-size:1rem;width:32px;height:32px;cursor:pointer;display:flex;align-items:center;
       justify-content:center;flex-shrink:0;transition:.12s}}
.pnav:hover{{background:var(--border);color:#fff}}

/* ── POST LAYERS (z-index stack) ── */
#post{{position:relative;overflow:hidden;border-radius:3px;
       box-shadow:0 20px 70px rgba(0,0,0,.75);flex-shrink:0}}
/* z0 blurred bg */
#bg-blur{{position:absolute;inset:-30px;background-size:cover;
           transform:scale(1.08);z-index:0}}
/* z1 main image (cover: rellena y recorta bordes) */
#bg-main{{position:absolute;top:0;left:0;right:0;
           object-fit:cover;object-position:center 50%;z-index:1}}
/* z2 fade overlays (positioned by JS at real image edges) */
#fade-top,#fade-bot{{position:absolute;left:0;right:0;z-index:2;pointer-events:none;height:0}}
/* z3 main gradient */
#grad{{position:absolute;inset:0;z-index:3}}
/* z4 watermark */
#wm{{position:absolute;z-index:4;display:flex;align-items:center;justify-content:center;
     mix-blend-mode:screen}}
/* z5 logo top-left — sin fondo, sombra para legibilidad */
#logo-tl{{position:absolute;z-index:6;display:flex;align-items:center;
           justify-content:center;background:none;
           filter:drop-shadow(0 1px 6px rgba(0,0,0,0.9)) drop-shadow(0 0 3px rgba(0,0,0,0.7))}}
/* z5 content */
#content{{position:absolute;z-index:5;left:0;right:0;bottom:0;
           display:flex;flex-direction:column;align-items:flex-start}}
#badge-el{{display:inline-block;font-weight:800;text-transform:uppercase;
            letter-spacing:.07em;color:#fff;border-radius:99px;line-height:1;flex-shrink:0}}
#title-el{{color:#fff;font-weight:900;line-height:1.2;text-shadow:0 2px 18px rgba(0,0,0,.55)}}
#date-el{{color:rgba(255,255,255,.55);font-weight:500}}
/* z6 left accent bar */
#left-bar{{position:absolute;left:0;z-index:6;width:4px}}
/* z6 footer strip */
#footer-strip{{position:absolute;bottom:0;left:0;right:0;z-index:7;
               display:flex;align-items:center;justify-content:space-between}}
#footer-url{{color:rgba(255,255,255,.9);font-weight:700;letter-spacing:.04em}}
#footer-social{{display:flex;align-items:center;gap:6px}}
.soc-icon{{fill:currentColor;flex-shrink:0}}

.art-info{{max-width:500px;text-align:center}}
.art-info h2{{font-size:.85rem;font-weight:700;color:var(--text);margin-bottom:4px;line-height:1.35}}
.art-info p{{font-size:.72rem;color:var(--muted);line-height:1.5;margin-bottom:4px}}
.art-info a{{color:var(--accent);font-size:.68rem;word-break:break-all;text-decoration:none}}
.art-info a:hover{{text-decoration:underline}}
</style>
</head>
<body>

<header class="hdr">
  <div class="hdr-title">La Voz Riojana <span>— Diseñador Instagram</span></div>
  <div class="hdr-sub" id="hdr-c"></div>
  <div class="hdr-sub">← → navegar</div>
</header>

<div class="workspace">

<!-- ══ SIDEBAR ══ -->
<aside class="sidebar">

  <div>
    <div class="sb-lbl">Formato</div>
    <div class="sz-row">
      <button class="sz-btn on" onclick="setSize(414,518,this)">4:5<br><small>Instagram</small></button>
      <button class="sz-btn" onclick="setSize(460,460,this)">1:1<br><small>Facebook</small></button>
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Sección</div>
    <div class="filters" id="sec-filters">
      <button class="fbtn on" onclick="filterSec('all',this)">Todas</button>
      <button class="fbtn" onclick="filterSec('Locales',this)">Locales</button>
      <button class="fbtn" onclick="filterSec('Policiales',this)">Policiales</button>
      <button class="fbtn" onclick="filterSec('Interior',this)">Interior</button>
      <button class="fbtn" onclick="filterSec('Deportes',this)">Deportes</button>
    </div>
  </div>

  <div>
    <div class="sb-lbl">Navegación</div>
    <div class="nav-row">
      <button class="nb" onclick="prev()">&#8592;</button>
      <div class="nc" id="nav-c"></div>
      <button class="nb" onclick="next()">&#8594;</button>
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Gradiente</div>
    <div class="field">
      <label>Opacidad <b id="lgo">100</b>%</label>
      <input type="range" id="grad-op" min="60" max="100" value="100" oninput="sl('lgo',this);draw()">
    </div>
    <div class="field">
      <label>Punto de inicio <b id="lgs">43</b>%</label>
      <input type="range" id="grad-soft" min="2" max="45" value="43" oninput="sl('lgs',this);draw()">
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Logo (arriba izq)</div>
    <div class="trow" style="margin-bottom:8px">
      <span class="tlbl">Visible</span>
      <label class="tog"><input type="checkbox" id="show-logo-tl" checked onchange="draw()"><span class="tog-sl"></span></label>
    </div>
    <div class="field">
      <label>Ancho <b id="ltlw">16</b>%</label>
      <input type="range" id="logo-tl-w" min="8" max="65" value="16" oninput="sl('ltlw',this);draw()">
    </div>
  </div>

  <div>
    <div class="sb-lbl">Marca de agua (centro)</div>
    <div class="trow" style="margin-bottom:8px">
      <span class="tlbl">Visible</span>
      <label class="tog"><input type="checkbox" id="show-wm" checked onchange="draw()"><span class="tog-sl"></span></label>
    </div>
    <div class="field">
      <label>Opacidad <b id="lwmo">19</b>%</label>
      <input type="range" id="wm-op" min="3" max="50" value="19" oninput="sl('lwmo',this);draw()">
    </div>
    <div class="field">
      <label>Tamaño <b id="lwms">38</b>%</label>
      <input type="range" id="wm-size" min="12" max="65" value="38" oninput="sl('lwms',this);draw()">
    </div>
    <div class="field">
      <label>Posición vertical <b id="lwmv">27</b>%</label>
      <input type="range" id="wm-vpos" min="15" max="70" value="27" oninput="sl('lwmv',this);draw()">
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Imagen</div>
    <div class="field">
      <label>Encuadre vertical <b id="livp">50</b>%</label>
      <input type="range" id="img-vpos" min="0" max="100" value="50" oninput="sl('livp',this);draw()">
      <small style="color:var(--muted);font-size:.66rem">0%=arriba · 50%=centro · 100%=abajo</small>
    </div>
    <div class="field">
      <label>Fade bordes imagen <b id="libl">9</b>%</label>
      <input type="range" id="img-blend" min="0" max="48" value="9" oninput="sl('libl',this);draw()">
      <small style="color:var(--muted);font-size:.66rem">Desvanece arriba y abajo de la foto</small>
    </div>
    <div class="field">
      <label>Oscuridad fondo <b id="libr">10</b>%</label>
      <input type="range" id="bg-dark" min="0" max="95" value="10" oninput="sl('libr',this);draw()">
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Contenido</div>
    <div class="field">
      <label>Altura donde empieza <b id="lca">55</b>%</label>
      <input type="range" id="content-top" min="35" max="72" value="55" oninput="sl('lca',this);draw()">
    </div>
    <div class="field">
      <label>Color badge / barra</label>
      <input type="color" id="brand-col" value="#c0392b" oninput="draw()">
    </div>
    <div class="field">
      <label>Ancho título <b id="ltw">95</b>%</label>
      <input type="range" id="title-w" min="40" max="95" value="95" oninput="sl('ltw',this);draw()">
    </div>
  </div>

  <hr class="divider">

  <div>
    <div class="sb-lbl">Pie de imagen</div>
    <div class="trow" style="margin-bottom:8px">
      <span class="tlbl">Mostrar</span>
      <label class="tog"><input type="checkbox" id="show-footer" checked onchange="draw()"><span class="tog-sl"></span></label>
    </div>
    <div class="field">
      <label>Color iconos redes</label>
      <input type="color" id="social-color" value="#e30000" oninput="draw()">
    </div>
    <div class="field">
      <label>Tamaño pie <b id="lfth">7</b>%</label>
      <input type="range" id="footer-h" min="4" max="14" value="7" oninput="sl('lfth',this);draw()">
    </div>
  </div>

  <div>
    <div class="sb-lbl">Extras</div>
    <div class="trow" style="margin-bottom:8px">
      <span class="tlbl">Badge de sección</span>
      <label class="tog"><input type="checkbox" id="show-badge" checked onchange="draw()"><span class="tog-sl"></span></label>
    </div>
    <div class="trow" style="margin-bottom:8px">
      <span class="tlbl">Barra lateral color</span>
      <label class="tog"><input type="checkbox" id="show-leftbar" checked onchange="draw()"><span class="tog-sl"></span></label>
    </div>
    <div class="trow">
      <span class="tlbl">Fecha</span>
      <label class="tog"><input type="checkbox" id="show-date" onchange="draw()"><span class="tog-sl"></span></label>
    </div>
  </div>

</aside>

<!-- ══ CANVAS ══ -->
<main class="canvas">

  <div class="post-wrap">
    <button class="pnav" onclick="prev()">&#8592;</button>

    <div id="post" style="width:414px;height:518px">
      <div id="bg-blur"></div>
      <img id="bg-main" src="" alt="">
      <div id="fade-top"></div>
      <div id="fade-bot"></div>
      <div id="grad"></div>
      <div id="wm">{logo_img}</div>
      <div id="left-bar"></div>
      <div id="logo-tl">{logo_img}</div>
      <div id="content">
        <div id="badge-el"></div>
        <div id="title-el"></div>
        <div id="date-el"></div>
      </div>
      <div id="footer-strip">
        <div id="footer-social">
          <svg class="soc-icon" id="fb-icon" viewBox="0 0 24 24">
            <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/>
          </svg>
          <svg class="soc-icon" id="ig-icon" viewBox="0 0 24 24">
            <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.98 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
          </svg>
        </div>
        <div id="footer-url">www.lavozriojana.com</div>
      </div>
    </div>

    <button class="pnav" onclick="next()">&#8594;</button>
  </div>

  <div class="art-info" id="art-info"></div>

</main>
</div>

<script>
const ALL = {data_json};
let filtered=[...ALL], idx=0, postW=414, postH=518, _imgContH=518;

document.getElementById('hdr-c').textContent = ALL.length+' noticias';

/* ── TITLE FIT ── */
function fitTitle(text, wPx, maxHpx, minFs, maxFs) {{
  const p = document.createElement('div');
  p.style.cssText = `position:absolute;visibility:hidden;left:-9999px;top:0;
    font-weight:900;line-height:1.2;word-break:break-word;width:${{wPx}}px`;
  document.body.appendChild(p);
  let lo=minFs, hi=maxFs;
  for (let i=0;i<18;i++) {{
    const mid=(lo+hi)/2;
    p.style.fontSize=mid+'px'; p.textContent=text;
    p.offsetHeight<=maxHpx ? (lo=mid) : (hi=mid);
  }}
  document.body.removeChild(p);
  return Math.floor(lo);
}}

/* ── FADES: cover rellena toda el área, fades en top/bottom del zone de imagen ── */
function applyFades() {{
  const imgBlend = +document.getElementById('img-blend').value;
  const bgDark   = +document.getElementById('bg-dark').value;
  const ftop     = document.getElementById('fade-top');
  const fbot     = document.getElementById('fade-bot');

  if (imgBlend === 0) {{
    ftop.style.height = '0'; fbot.style.height = '0'; return;
  }}

  const fadeH     = Math.min(Math.round(_imgContH * imgBlend / 100), Math.floor(_imgContH * 0.45));
  const fadeColor = `rgba(0,0,0,${{Math.min(bgDark/100 + 0.4, 0.95).toFixed(2)}})`;

  ftop.style.top        = '0px';
  ftop.style.bottom     = 'auto';
  ftop.style.height     = fadeH + 'px';
  ftop.style.background = `linear-gradient(to bottom, ${{fadeColor}} 0%, transparent 100%)`;

  fbot.style.top        = (_imgContH - fadeH) + 'px';
  fbot.style.bottom     = 'auto';
  fbot.style.height     = fadeH + 'px';
  fbot.style.background = `linear-gradient(to top, ${{fadeColor}} 0%, transparent 100%)`;
}}

/* ── DRAW ── */
function draw() {{
  const art       = filtered[idx]; if(!art) return;
  const gradOp    = +document.getElementById('grad-op').value/100;
  const gradSoft  = +document.getElementById('grad-soft').value;
  const brandCol  = document.getElementById('brand-col').value;
  const titleWpct = +document.getElementById('title-w').value;
  const contTop   = +document.getElementById('content-top').value;
  const showBadge = document.getElementById('show-badge').checked;
  const showDate  = document.getElementById('show-date').checked;
  const showLogoTl= document.getElementById('show-logo-tl').checked;
  const showWm    = document.getElementById('show-wm').checked;
  const showFooter= document.getElementById('show-footer').checked;
  const showLBar  = document.getElementById('show-leftbar').checked;
  const wmOp      = +document.getElementById('wm-op').value/100;
  const wmSize    = +document.getElementById('wm-size').value;
  const wmVpos    = +document.getElementById('wm-vpos').value;
  const logoTlW   = +document.getElementById('logo-tl-w').value;
  const imgVpos   = +document.getElementById('img-vpos').value;
  const bgDark    = +document.getElementById('bg-dark').value;
  const socialCol = document.getElementById('social-color').value;
  const footerHpct= +document.getElementById('footer-h').value;

  /* ── background blur ── */
  const url = art.imagen_url||'';
  const bgBlur = document.getElementById('bg-blur');
  bgBlur.style.backgroundImage    = url ? `url('${{url}}')` : 'none';
  bgBlur.style.backgroundPosition = `center ${{imgVpos}}%`;
  const bright = Math.max(0.05, 1 - bgDark/100).toFixed(2);
  bgBlur.style.filter = `blur(28px) brightness(${{bright}})`;

  /* ── main image: limitada al área superior (no invade el contenido) ── */
  const pad = postW * 0.052;
  const contentTopPxEarly = postH * contTop / 100;
  _imgContH = contentTopPxEarly;
  const bgMain = document.getElementById('bg-main');
  bgMain.style.height = contentTopPxEarly + 'px';
  bgMain.style.bottom = 'auto';
  bgMain.onload = applyFades;
  bgMain.src = url;
  bgMain.style.objectPosition = `center ${{imgVpos}}%`;
  if (bgMain.naturalWidth) applyFades(); // ya cargada (cache)

  /* ── gradient principal (bottom half) ── */
  const g = document.getElementById('grad');
  g.style.background = `linear-gradient(to top,
    rgba(0,0,0,${{gradOp}}) 0%,
    rgba(0,0,0,${{(gradOp*0.7).toFixed(2)}}) ${{gradSoft}}%,
    rgba(0,0,0,0.01) 50%,
    rgba(0,0,0,0) 50.1%)`;

  /* ── logo top-left ── */
  const logoTl = document.getElementById('logo-tl');
  if (showLogoTl) {{
    const lw    = postW * logoTlW / 100;
    const inset = Math.round(postW * 0.022); // pequeño margen arriba-izq
    logoTl.style.display      = 'block';
    logoTl.style.width        = lw + 'px';
    logoTl.style.height       = 'auto';
    logoTl.style.top          = inset + 'px';
    logoTl.style.left         = inset + 'px';
    logoTl.style.background   = 'none';
    logoTl.style.borderRadius = '0';
    logoTl.style.padding      = '0';
    logoTl.style.border       = 'none';
  }} else {{ logoTl.style.display='none'; }}

  /* ── watermark center ── */
  const wm = document.getElementById('wm');
  if (showWm) {{
    const ww = postW * wmSize / 100;
    wm.style.display   = 'flex';
    wm.style.width     = ww+'px';
    wm.style.height    = (ww*0.42)+'px';
    wm.style.left      = ((postW-ww)/2)+'px';
    wm.style.top       = (postH*wmVpos/100 - ww*0.21)+'px';
    wm.style.opacity   = wmOp;
    wm.style.background= 'none';
    wm.style.border    = 'none';
  }} else {{ wm.style.display='none'; }}

  /* ── footer strip ── */
  const footer = document.getElementById('footer-strip');
  if (showFooter) {{
    const fh = Math.round(postH * footerHpct / 100);
    const fpad = Math.round(postW * 0.038);
    const iconSz = Math.round(fh * 0.52);
    footer.style.display  = 'flex';
    footer.style.height   = fh + 'px';
    footer.style.padding  = `0 ${{fpad}}px`;
    document.getElementById('footer-url').style.fontSize = Math.round(fh*0.33)+'px';
    ['fb-icon','ig-icon'].forEach(id=>{{
      const el = document.getElementById(id);
      el.setAttribute('width', iconSz);
      el.setAttribute('height', iconSz);
      el.style.color = socialCol;
    }});
  }} else {{ footer.style.display='none'; }}

  /* ── left accent bar ── */
  const lbar = document.getElementById('left-bar');
  if (showLBar) {{
    const barW = Math.round(postW * 0.011);
    const barTop = Math.round(postH * contTop / 100);
    lbar.style.display = 'block';
    lbar.style.width   = barW + 'px';
    lbar.style.top     = barTop + 'px';
    lbar.style.bottom  = '0';
    lbar.style.background = brandCol;
  }} else {{ lbar.style.display='none'; }}

  /* ── content block ── */
  const contentEl    = document.getElementById('content');
  const contentTopPx = contentTopPxEarly;
  const lbarOff      = showLBar ? Math.round(postW*0.011)+Math.round(pad*0.5) : 0;
  const contentGap   = Math.round(postH * 0.018); // espacio entre borde imagen y badge
  contentEl.style.top     = contentTopPx + 'px';
  contentEl.style.padding = `${{contentGap}}px ${{pad}}px ${{pad*0.85}}px ${{pad + lbarOff}}px`;
  contentEl.style.gap     = (postH*0.010)+'px';

  const badgeEl = document.getElementById('badge-el');
  if (showBadge) {{
    badgeEl.style.display    = 'inline-block';
    badgeEl.textContent      = art.seccion;
    badgeEl.style.background = brandCol;
    badgeEl.style.fontSize   = (postW*0.030)+'px';
    badgeEl.style.padding    = `${{postH*0.011}}px ${{postW*0.034}}px`;
  }} else {{ badgeEl.style.display='none'; }}

  const titleEl  = document.getElementById('title-el');
  // ancho disponible = postW menos padding izq (pad+lbarOff) menos padding der (pad)
  const availW   = postW - 2*pad - lbarOff;
  const trgW     = availW * titleWpct / 100;
  const footerPx = showFooter ? Math.round(postH * footerHpct / 100) : 0;
  const maxH     = postH - contentTopPx - contentGap - pad
                   - (showBadge ? postH*0.06 : 0)
                   - (showDate  ? postH*0.04 : 0)
                   - footerPx;
  const fs = fitTitle(art.titulo, trgW, maxH, postW*0.022, postW*0.075);
  titleEl.style.fontSize = fs+'px';
  titleEl.style.width    = trgW+'px';
  titleEl.textContent    = art.titulo;

  const dateEl = document.getElementById('date-el');
  if (showDate && art.fecha) {{
    dateEl.style.display  = 'block';
    dateEl.textContent    = art.fecha;
    dateEl.style.fontSize = (postW*0.026)+'px';
  }} else {{ dateEl.style.display='none'; }}

  document.getElementById('nav-c').textContent = `${{idx+1}} / ${{filtered.length}}`;
  const info = document.getElementById('art-info');
  const infoTitle = document.createElement('h2');
  infoTitle.textContent = String(art.titulo || '');
  const infoBody = document.createElement('p');
  infoBody.textContent = String(art.parrafo || '').slice(0,160) + '...';
  const infoLink = document.createElement('a');
  const safeUrl = /^https?:\/\//i.test(String(art.url || '')) ? String(art.url) : '';
  infoLink.href = safeUrl || '#';
  infoLink.target = '_blank';
  infoLink.rel = 'noopener noreferrer';
  infoLink.textContent = safeUrl;
  info.replaceChildren(infoTitle, infoBody, infoLink);
}}

function next(){{idx=(idx+1)%filtered.length;draw();}}
function prev(){{idx=(idx-1+filtered.length)%filtered.length;draw();}}

function filterSec(sec,btn){{
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  filtered=sec==='all'?[...ALL]:ALL.filter(a=>a.seccion===sec);
  idx=0;draw();
}}

function setSize(w,h,btn){{
  postW=w;postH=h;
  document.querySelectorAll('.sz-btn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  const p=document.getElementById('post');
  p.style.width=w+'px';p.style.height=h+'px';
  draw();
}}

function sl(id,inp){{document.getElementById(id).textContent=inp.value;}}
document.addEventListener('keydown',e=>{{
  if(e.key==='ArrowRight')next();
  if(e.key==='ArrowLeft')prev();
}});

draw();
</script>
</body>
</html>"""

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    arts = load_articles()
    if not arts:
        print("No hay noticias. Ejecuta primero los scrapers.")
        sys.exit(1)
    print(f"Cargadas {len(arts)} noticias")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(build_html(arts))
    print(f"Generado: {OUT_FILE}")
    try:
        webbrowser.open(f"file:///{OUT_FILE.replace(os.sep,'/')}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
