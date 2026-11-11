"""Reglas visuales de crecimiento (T02 del plan maestro, sección 9).

Ajustes chicos y determinísticos sobre el Visual System V2, sin otro motor ni
otra llamada a IA:

* destacado del titular acotado (máximo tres palabras y un tercio del título)
  y sin partir un nombre propio ("Tini | Stoessel");
* sección visual editorial cuando llega el nombre de la fuente
  ("Paparazzi" → "Espectáculos");
* fotos compuestas (dos paneles o grilla 2×2, típicas de los portales) en un
  hueco angosto: en vez de recortar al centro —donde está la costura y se
  cortan las caras— se recompone con paneles enteros (díptico o primera
  columna de la grilla). Nunca se inventa contenido: sólo se reubican partes
  de la misma foto;
* medición del titular con la fuente real (Pillow + Archivo variable) para
  QA de overflow sin Node.

Todo queda detrás de ``GROWTH_IMAGE_RULES_ENABLED`` (default ``false``) y de
la lista de workflows ``GROWTH_IMAGE_RULES_WORKFLOWS`` (default
``instagram,og``). Con el flag apagado el render es idéntico al anterior.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping
from functools import lru_cache

from PIL import Image, ImageChops, ImageFilter, ImageFont, ImageStat

RULES_VERSION = "growth-1"
ENABLED_ENV = "GROWTH_IMAGE_RULES_ENABLED"
WORKFLOWS_ENV = "GROWTH_IMAGE_RULES_WORKFLOWS"
DEFAULT_WORKFLOWS = ("instagram", "og")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}

# Hueco de la foto en FacebookOgCardV2 (columna de texto de 600 px).
OG_PHOTO_SLOT = (600, 630)

MAX_HIGHLIGHT_WORDS = 3
MAX_HIGHLIGHT_SHARE = 0.34

# Secciones que llegan con el nombre de la fuente y no de la categoría.
VISUAL_SECTION_ALIASES = {
    "paparazzi": "espectaculos",
    "farandula": "espectaculos",
    "tv": "espectaculos",
    "teve": "espectaculos",
    "famosos": "espectaculos",
}

# Conectores que pueden ir dentro de un nombre propio ("Universidad Nacional
# de Chilecito", "Ángel Vicente Peñaloza").
_NAME_CONNECTORS = {"de", "del", "la", "las", "los", "y", "e"}

FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "remotion", "public", "fonts", "Archivo[wdth,wght].ttf")


def growth_image_rules_enabled(workflow: str, values: Mapping[str, str] | None = None) -> bool:
    env = os.environ if values is None else values
    if str(env.get(ENABLED_ENV, "false")).strip().lower() not in _TRUE:
        return False
    raw = str(env.get(WORKFLOWS_ENV) or "").strip()
    workflows = {w.strip().lower() for w in raw.split(",") if w.strip()} if raw else set(DEFAULT_WORKFLOWS)
    return workflow in workflows


def _fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def visual_section(seccion: str) -> str:
    """Categoría editorial para la etiqueta visual; el resto queda igual."""
    return VISUAL_SECTION_ALIASES.get(_fold(seccion), seccion)


# ── Destacados ───────────────────────────────────────────────────────────
def _norm_word(word: str) -> str:
    return re.sub(r"^[^\w%$]+|[^\w%$]+$", "", unicodedata.normalize("NFC", word).casefold())


def _name_mask(words: list[str]) -> list[bool]:
    """Palabras que forman parte de un nombre propio (por mayúscula inicial).

    En un título todo en MAYÚSCULAS no se puede distinguir: no marca nada.
    La primera palabra sólo cuenta si la siguiente también es nombre propio
    ("Lali Espósito"), porque la mayúscula inicial es de la oración.
    """
    letters = "".join(ch for ch in " ".join(words) if ch.isalpha())
    if not letters or letters == letters.upper():
        return [False] * len(words)

    def capital(word: str) -> bool:
        core = re.sub(r"^[^\w]+", "", word)
        return bool(core) and core[0].isupper()

    mask = [capital(w) for w in words]
    if mask and len(words) > 1 and not mask[1]:
        mask[0] = False
    for i in range(1, len(words) - 1):
        if not mask[i] and _norm_word(words[i]) in _NAME_CONNECTORS and mask[i - 1] and mask[i + 1]:
            # "y" sólo une nombres cuando no termina uno y empieza otro: se
            # deja fuera para que "Lali Espósito y Tini" sean dos nombres.
            mask[i] = _norm_word(words[i]) not in {"y", "e"}
    return mask


def _name_runs(words: list[str]) -> list[tuple[int, int]]:
    mask = _name_mask(words)
    runs, start = [], None
    for i, flag in enumerate([*mask, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i))
            start = None
    return runs


def _max_words(total: int) -> int:
    return max(2, min(MAX_HIGHLIGHT_WORDS, int(total * MAX_HIGHLIGHT_SHARE)))


def _window_ok(start: int, length: int, total: int, runs: list[tuple[int, int]]) -> bool:
    if length > _max_words(total):
        return False
    end = start + length
    for a, b in runs:
        overlaps = start < b and a < end
        if overlaps and not (start <= a and b <= end):
            return False
    return True


def _find(words_norm: list[str], phrase: str) -> int | None:
    target = [_norm_word(w) for w in phrase.split() if _norm_word(w)]
    if not target:
        return None
    for i in range(len(words_norm) - len(target) + 1):
        if words_norm[i : i + len(target)] == target:
            return i
    return None


def refine_highlight_terms(title: str, terms: list[str]) -> list[str]:
    """Un único destacado corto, sin partir nombres; ``[]`` antes que uno malo.

    Usa las mismas reglas estructurales del selector local
    (``openIA.caption_generator._highlight_candidate_score``), restringidas
    a ventanas válidas. Sólo devuelve texto que está literalmente en el título.
    """
    from openIA.caption_generator import _crosses_punctuation, _highlight_candidate_score, _normalized_title_word

    words = str(title or "").split()
    if len(words) < 3:
        return []
    norm = [_norm_word(w) for w in words]
    runs = _name_runs(words)
    preferred: set[int] = set()
    for term in terms or []:
        start = _find(norm, str(term))
        if start is None:
            continue
        length = len([w for w in str(term).split() if _norm_word(w)])
        if _window_ok(start, length, len(words), runs):
            return [" ".join(words[start : start + length])]
        preferred.update(range(start, start + length))

    scoring = [_normalized_title_word(w) for w in words]
    best: tuple[float, int, int] | None = None
    for length in range(2, _max_words(len(words)) + 1):
        for start in range(len(words) - length + 1):
            if not _window_ok(start, length, len(words), runs) or _crosses_punctuation(words[start : start + length]):
                continue
            score = _highlight_candidate_score(scoring, start, length)
            if score is None:
                continue
            # Se prefiere quedarse cerca del destacado editorial original.
            score += 8 * len(preferred.intersection(range(start, start + length)))
            candidate = (score, -start, length)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return []
    _score, neg_start, length = best
    return [" ".join(words[-neg_start : -neg_start + length])]


# ── Fotos compuestas ─────────────────────────────────────────────────────
_ANALYSIS_MAX_W = 800
SEAM_MIN_ROWS = 0.6
_STEP_MIN = 14


def _seam_profile(gray: Image.Image) -> list[float]:
    """Fracción de filas con un escalón NÍTIDO de 1 px entre columnas x y x+1.

    Una costura de montaje es un salto de un píxel; un borde natural de la
    foto (poste, pared, perfil) viene suavizado por la óptica y la
    compresión. Se exige que el salto sea grande y al menos el doble que los
    saltos vecinos. Todo en C vía ``ImageChops`` (sin numpy).
    """
    w, h = gray.size
    diff = ImageChops.difference(gray.crop((0, 0, w - 1, h)), gray.crop((1, 0, w, h)))
    dw = diff.width
    center = diff.crop((1, 0, dw - 1, h))
    neighbors = ImageChops.lighter(diff.crop((0, 0, dw - 2, h)), diff.crop((2, 0, dw, h)))
    sharp = ImageChops.subtract(center, neighbors.point(lambda v: min(255, v * 2))).point(lambda v: 255 if v > 6 else 0)
    big = center.point(lambda v: 255 if v > _STEP_MIN else 0)
    both = ImageChops.multiply(sharp, big)
    y0, y1 = int(h * 0.03), max(int(h * 0.03) + 1, int(h * 0.97))
    profile = both.crop((0, y0, both.width, y1)).resize((both.width, 1), Image.Resampling.BOX)
    # índice i → costura entre las columnas i+1 e i+2
    return [profile.getpixel((i, 0)) / 255 for i in range(profile.width)]


def _gutter_profile(gray: Image.Image) -> list[float]:
    """1.0 en columnas casi uniformes de punta a punta (canaleta blanca/negra)."""
    w, h = gray.size
    out = []
    for x in range(w):
        lo, hi = gray.crop((x, int(h * 0.03), x + 1, int(h * 0.97))).getextrema()
        out.append(1.0 if hi - lo <= 24 else 0.0)
    return out


def _seams(gray: Image.Image, *, gutters: bool) -> list[tuple[float, float]]:
    """Costuras (fracción del largo) entre el 20 % y el 80 %.

    Las canaletas uniformes sólo se aceptan cuando se pide (filas de una
    grilla que ya tiene costura vertical): en fondos lisos de estudio una
    columna uniforme no es un montaje.
    """
    w = gray.width
    hits = [i + 1.5 for i, v in enumerate(_seam_profile(gray)) if v >= SEAM_MIN_ROWS]
    if gutters:
        hits += [float(x) for x, v in enumerate(_gutter_profile(gray)) if v and 0 < x < w - 1]
    hits = sorted(x for x in hits if 0.2 * w <= x <= 0.8 * w)
    spans: list[list[float]] = []
    for x in hits:
        if spans and x - spans[-1][1] <= max(4, w * 0.02):
            spans[-1][1] = x
        else:
            spans.append([x, x])
    # Una canaleta demasiado ancha es parte de la imagen, no un montaje.
    return [(a / w, (b + 1) / w) for a, b in spans if (b - a) <= w * 0.04]


def _detail(img: Image.Image) -> float:
    return ImageStat.Stat(img.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]


def detect_panels(img: Image.Image) -> list[list[tuple[int, int, int, int]]]:
    """Grilla de paneles (filas de cajas en coordenadas originales).

    Una foto simple devuelve una sola caja. Admite hasta 3 columnas y 2 filas.
    """
    w, h = img.size
    gray = img.convert("L")
    if gray.width > _ANALYSIS_MAX_W:
        gray = gray.resize((_ANALYSIS_MAX_W, max(8, round(h * _ANALYSIS_MAX_W / w))), Image.Resampling.NEAREST)
    vertical = _seams(gray, gutters=False)[:2]
    horizontal = []
    if vertical:
        horizontal = [
            s for s in _seams(gray.transpose(Image.Transpose.TRANSPOSE), gutters=True)
            if 0.3 <= (s[0] + s[1]) / 2 <= 0.7
        ][:1]

    def cuts(spans, length):
        edges, cursor = [], 0
        for a, b in spans:
            edges.append((cursor, max(cursor + 1, int(a * length) - 2)))
            cursor = min(length - 1, int(b * length) + 2)
        edges.append((cursor, length))
        return edges

    cols, rows = cuts(vertical, w), cuts(horizontal, h)
    grid = [[(x0, y0, x1, y1) for (x0, x1) in cols] for (y0, y1) in rows]
    if len(rows) == 1 and len(cols) > 1:
        # Barras laterales lisas o difuminadas (foto vertical "pillarbox"):
        # no son paneles. Queda sólo lo que tiene detalle.
        details = [_detail(img.crop(box)) for box in grid[0]]
        keep = [box for box, d in zip(grid[0], details) if d >= 0.35 * max(details)]
        grid = [keep]
    return grid


def _cover(img: Image.Image, w: int, h: int, focus_y: float = 0.42) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    resized = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.Resampling.LANCZOS)
    left = (resized.width - w) // 2
    top = int((resized.height - h) * focus_y)
    return resized.crop((left, top, left + w, top + h))


def recompose_for_slot(img: Image.Image, slot: tuple[int, int], *, gap_color=(10, 13, 18)) -> tuple[Image.Image | None, dict]:
    """Recompone una foto compuesta para un hueco angosto, o ``None``.

    * Foto simple, o compuesta que entra casi entera en el hueco: no se toca.
    * Dos paneles lado a lado: díptico con ambos paneles enteros y centrados.
    * Grilla 2×2: la primera columna (dos fotos apiladas), máximo dos imágenes.
    """
    slot_w, slot_h = slot
    grid = detect_panels(img)
    rows, cols = len(grid), len(grid[0])
    info = {"panels": rows * cols, "grid": f"{rows}x{cols}", "applied": False}
    if rows * cols == 1:
        x0, y0, x1, y1 = grid[0][0]
        if (x1 - x0) >= img.width * 0.97:
            return None, info
        # Pillarbox: se usa la foto real sin las barras.
        info.update({"applied": True, "layout": "single_panel"})
        return _cover(img.crop(grid[0][0]), slot_w * 2, slot_h * 2), info
    src_aspect = img.width / img.height
    slot_aspect = slot_w / slot_h
    if src_aspect <= slot_aspect * 1.33:
        return None, info
    out_w, out_h = slot_w * 2, slot_h * 2
    gap = 12
    canvas = Image.new("RGB", (out_w, out_h), gap_color)
    if rows >= 2:
        boxes = [grid[0][0], grid[1][0]]
        cell_h = (out_h - gap) // 2
        for i, box in enumerate(boxes):
            canvas.paste(_cover(img.crop(box), out_w, cell_h), (0, i * (cell_h + gap)))
        info["layout"] = "first_column"
    else:
        boxes = grid[0][:2]
        cell_w = (out_w - gap) // 2
        for i, box in enumerate(boxes):
            canvas.paste(_cover(img.crop(box), cell_w, out_h), (i * (cell_w + gap), 0))
        info["layout"] = "diptych"
    info["applied"] = True
    return canvas, info


# ── Medición con la fuente real (QA) ─────────────────────────────────────
@lru_cache(maxsize=64)
def _font(size: int, weight: int, width: float) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONT_PATH, size)
    font.set_variation_by_axes([weight, width])
    return font


def wrap_headline(text: str, max_width: int, size: int, *, weight: int = 800, width: float = 87.5) -> list[str]:
    """Mismo wrap por palabra que ``remotion/src/v2/fit.ts`` (semi-condensed = 87,5 %)."""
    font = _font(size, weight, width)
    lines: list[str] = []
    current = ""
    for word in str(text or "").split():
        candidate = f"{current} {word}" if current else word
        if not current or font.getlength(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_headline(text: str, max_width: int, max_height: int, min_size: int, max_size: int, max_lines: int, lh: float = 1.0) -> dict:
    """Búsqueda binaria equivalente a ``fit.ts``: tamaño, líneas y overflow."""
    best = None
    lo, hi = min_size, max_size
    while lo <= hi:
        mid = (lo + hi) // 2
        lines = wrap_headline(text, max_width, mid)
        widest = max((_font(mid, 800, 87.5).getlength(line) for line in lines), default=0)
        if len(lines) <= max_lines and len(lines) * mid * lh <= max_height and widest <= max_width + 0.5:
            best = (mid, lines, widest)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        lines = wrap_headline(text, max_width, min_size)
        return {"size": min_size, "lines": lines, "overflow": True}
    return {"size": best[0], "lines": best[1], "overflow": False, "widest": round(best[2], 1)}
