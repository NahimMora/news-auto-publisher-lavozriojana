"""Noticiero V5: Reel policial con apertura en frío y edición por frases.

Corrección de dirección del 2026-11-01, después de medir el Reel del 31/10
(50 % de abandono en el primer segundo, 6,7 s de visualización promedio
sobre 1:59). V4 (``utils/newscast_v3.py``) queda intacta como rollback; V5
reutiliza su selección, sus barreras factuales, el inventario y control de
imágenes, la caché de locución y el alineamiento local, y cambia:

- **Apertura en frío.** El primer cuadro ya es la noticia principal: foto,
  titular legible y la marca integrada en una barra que se contrae en el HUD
  (~1,4 s). No hay locución de gancho aparte ni placa de marca intermedia:
  la primera frase que se escucha es el hecho más fuerte del día.
- **Guion directo** (``SCRIPT_PROMPT_V5``): primero qué pasó; la segunda
  oración sólo si agrega consecuencia; 140–210 palabras; sin relleno.
- **Voz.** Se acortan las pausas largas medidas en el propio WAV y se ajusta
  el ritmo con Rubber Band (ffmpeg, local): no se vuelve a llamar al TTS.
- **Edición por frases.** Cada historia se reparte en tomas de ~2–3 s
  (general, detalle, contraplano) cortadas en pausas reales; mapa de la
  provincia cuando el tramo tiene una localidad del nomenclador oficial;
  datos que entran cuando la voz los dice.
- **Subtítulos cinéticos** de 1–4 palabras, abajo, con la palabra clave
  marcada; el titular se contrae arriba para no competir con ellos.
- **Entregables:** portada 1080×1920 (``cover_url``), caption informativo
  sin fuentes y con 4 hashtags, ubicación "La Rioja" para Instagram.

Remotion (``NightlyNewscastV5``) sólo ejecuta el plan. Se activa con
``NIGHTLY_NEWSCAST_VISUAL=v5``.
"""
from __future__ import annotations

import array
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from utils import newscast_v3 as v3
from utils import nightly_newscast as nn
from utils.logging_setup import setup_logger

logger = setup_logger("nightly_newscast", "nightly_newscast.log")

PLAN_VERSION = "lvr-newscast-plan-5.0"
COMPOSITION = "NightlyNewscastV5"
COVER_COMPOSITION = "NewscastCoverV5"
FPS = 30
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_PATH = os.path.join(ROOT, "config", "newscast_geo_la_rioja.json")

# Tiempos (ms). Entre historias ~220 ms de aire; la transición los cubre.
LEAD_FIRST_MS = 60
LEAD_MS = 120
GAP_MS = 100
OUTRO_LEAD_MS = 120
OUTRO_TAIL_MS = 700
OUTRO_MIN_MS = 2600
SHOT_TARGET_MS = 2600
SHOT_MIN_MS = 1500
MAP_MS = 1900
LEAD_HEADLINE_MS = 3300   # el titular del gancho se lee entero antes de contraerse
TRANSITION_FRAMES = 9
OPEN_BRAND_FRAMES = 42

# Cortes de pausas (ms que quedan): entre oraciones, en comas y entre palabras.
PAUSE_CAPS = {"sentence": 280, "clause": 160, "word": 90}

# Encuadres: ampliación máxima tolerada por modo (px de salida / px de origen).
FULL_MAX_UPSCALE = 2.0
BAND_H = 1150
BAND_MAX_UPSCALE = 1.75
CARD_W = 940
DETAIL_MAX_UPSCALE = 2.35

TRANSITIONS_V5 = ("slash", "slide", "lift")
OPENING_STYLES = ("headline", "rundown", "map")
HASHTAGS_V5 = "#LaRioja #NoticiasLaRioja #Policiales #LaVozRiojana"
KICKER_DEFAULT = "Resumen policial"

SCRIPT_PROMPT_V5 = """Sos el editor del noticiero policial de la noche de La Voz Riojana, un medio de La Rioja, Argentina.
Recibís las notas que publicamos en las últimas 24 horas (id, sección, título, texto y si el tema es sensible) y armás el guion de un Reel vertical locutado de alrededor de un minuto y medio, para gente que lo mira en el celular y decide en un segundo si se queda.

Devolvé SOLO este JSON:
{"bloques": [{"ids": ["..."], "seccion": "policiales", "tipo": "hecho", "titulo": "...", "titulo_corto": "...", "palabra_clave": "...",
  "relevancia": {"interes": 3, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3},
  "tramos": [{"ids": ["..."], "lugar": "...", "texto": "...", "momento": "", "dato": ""}],
  "servicio": {"accion": "", "zona": "", "vigencia": ""}}]}

Cómo se cuenta (obligatorio):
- Primero qué pasó; después, sólo si suma, cómo pasó, a quién afecta o qué sigue. Nunca empieces con antecedentes ni con fórmulas ("En la jornada de hoy", "Se informó que", "Cabe destacar", "Estas son las noticias").
- Cada bloque: una primera oración de 10 a 18 palabras con el hecho, el lugar y el dato más fuerte; una segunda oración de hasta 14 palabras sólo si agrega una consecuencia, el estado de las personas o lo que hace la Justicia. "breve": una sola oración de hasta 16 palabras.
- Entre 6 y 10 bloques y entre 140 y 210 palabras en total. La duración la decide la noticia: un hecho simple se cuenta en una oración.
- El PRIMER bloque abre el Reel sin introducción: es el hecho más contundente o más útil del día y su primera oración tiene que entenderse sola en tres segundos (qué pasó, dónde, cuánto).
- Dejá afuera lo que no tiene interés público (contravenciones menores, choques sin heridos ni consecuencias, trámites) salvo que no alcance el material.
- Sin relleno burocrático: nada de "el siniestro vial ocurrido en la zona", "del hecho", "en el lugar", "personal policial procedió a" ni "quedó a disposición de la justicia" si no agrega información.
- Oraciones para el oído: sujeto + verbo + complemento, voz activa, sin paréntesis, comillas ni siglas sin desarrollar, sin adjetivos de opinión (escándalo, brutal, polémico, terrible). Nunca empieces una oración con el verbo.

Reglas factuales (obligatorias):
- Usá SOLO datos que estén en los textos recibidos. No inventes datos, cifras, edades, horarios, armas, personas, causas, citas ni hechos ajenos al original.
- Sólo hechos ocurridos en La Rioja. Si el texto ubica el hecho en otro día anterior, no lo cuentes como de hoy.
- Las notas del MISMO hecho van juntas en un bloque con todos sus ids. Hechos distintos van en bloques distintos; "hechos_relacionados" sólo para 2 o 3 hechos distintos y breves del mismo fenómeno, con un tramo por hecho.
- Nunca juntes en un bloque un accidente, una causa judicial y un delito. Si una nota es una denuncia, no digas que hubo detenidos.
- No sumes ni cuentes personas, heridos o hechos entre notas distintas: cada hecho con las cifras de su nota.
- Presunción de inocencia: "acusado", "investigado", "detenido"; nunca des por probado lo que la nota no da por probado. Respetá la situación procesal exacta: si dice "demorado", nunca "detenido"; si dice "aprehendido", nunca "imputado" ni "condenado".
- Temas sensibles (violencia de género, abusos, suicidio, menores): sin nombres ni datos que identifiquen a víctimas o menores, sin detalles morbosos y sin describir métodos.
- No digas días de la semana ni fechas salvo que el texto los diga. Sin saludos ni despedidas.

Campos:
- "tipo": "hecho" (lo normal); "hechos_relacionados"; "cronologia" sólo si el texto da al menos dos momentos del mismo hecho en orden; "dato" si la historia se explica por una cifra de la nota; "judicial" para decisiones de la Justicia; "breve" para un hecho secundario contado en una sola oración.
- "tramos": cada tramo tiene 1 o 2 oraciones sobre UN solo hecho y los ids de las notas que lo respaldan.
- "seccion": policiales para los hechos policiales, judiciales, siniestros e incendios; si no, una de interior, sociedad, economia, salud, educacion, cultura, politica.
- "titulo": titular de pantalla concreto y fiel: qué pasó y, si entra, dónde ("El Zonda reavivó un incendio cerca del aeropuerto"), con verbo, sin punto final, máximo 46 caracteres. Nunca genérico ("Incendios complican la jornada", "Investigan un hecho").
- "titulo_corto": la misma idea en máximo 30 caracteres y de 3 a 6 palabras, gramatical y completa: no omitas preposiciones ni artículos.
- "palabra_clave": 1 o 2 palabras del título, tal cual aparecen en él, que concentran el hecho.
- "lugar" de cada tramo: barrio o localidad DONDE OCURRIÓ ese hecho tal como figura en el texto (máximo 22 caracteres); no el origen de las personas, ni la sede del juzgado o la fiscalía, ni una calle suelta; si no figura, "".
- "momento": la hora o el momento del hecho sólo si el texto lo dice; si no, "".
- "dato": la cifra clave del tramo tal como figura en la nota y en tu texto (máximo 28 caracteres): cantidades de detenidos, heridos, hectáreas, secuestros o montos. Nunca una edad. Si no hay, "".
- "relevancia": de 1 a 5 cada criterio, según el texto (no según si hay fotos).
"""

SCRIPT_WORDS_V5 = (140, 210, 225)
SCRIPT_BLOCK_WORDS_V5 = 36


def _env_int(name: str, default: int) -> int:
    return nn._env_int(name, default)


def opening_style() -> str:
    style = (os.getenv("NIGHTLY_NEWSCAST_OPENING") or "headline").strip().lower()
    return style if style in OPENING_STYLES else "headline"


def write_script_v5(candidates: list[nn.Candidate], *, completion=None) -> tuple[v3.ScriptV3 | None, list[str]]:
    """Mismo circuito de reintentos y barreras que V4, con el prompt directo
    y límites de palabras de V5."""
    return v3.write_script_v3(candidates, completion=completion, prompt=SCRIPT_PROMPT_V5, words=SCRIPT_WORDS_V5,
                              block_words=SCRIPT_BLOCK_WORDS_V5)


# ── Mapa: nomenclador oficial de localidades ─────────────────────────────
@lru_cache(maxsize=1)
def _geo(path: str = GEO_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Nomenclador del mapa ilegible (%s): sin mapas", type(exc).__name__)
        return {"places": {}, "aliases": {}}


_PLACE_PREFIX = re.compile(r"^(la localidad de|localidad de|la ciudad de|ciudad de|el pueblo de|pueblo de)\s+")


def locate(place: str) -> dict | None:
    """Localidad del nomenclador para el lugar de un tramo, sólo con
    coincidencia exacta del nombre (o de un alias inequívoco). "barrio X",
    "Aeropuerto" o una calle no se ubican: nunca se adivina un punto."""
    geo = _geo()
    key = _PLACE_PREFIX.sub("", nn._fold(place).strip(" .,"))
    key = (geo.get("aliases") or {}).get(key, key)
    found = (geo.get("places") or {}).get(key)
    return dict(found) if found else None


# ── Voz: pausas y ritmo, sin volver a sintetizar ─────────────────────────
@dataclass
class Tightened:
    ms: int
    tokens: list[dict]
    factor: float
    removed_ms: int
    ppm_before: float
    ppm_after: float


def _read_pcm(path: str) -> tuple[int, array.array]:
    with wave.open(path, "rb") as w:
        rate, width, channels, frames = w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes()
        if width != 2:
            raise ValueError("sólo PCM de 16 bits")
        data = array.array("h", w.readframes(frames))
    if channels > 1:
        data = data[::channels]
    return rate, data


def _write_pcm(path: str, rate: int, data: array.array) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def detect_silences(data: array.array, rate: int, *, win_ms: int = 10, min_ms: int = 60) -> list[tuple[int, int]]:
    """Silencios (ms) medidos en el audio: ventanas de 10 ms por debajo de un
    umbral relativo al piso de ruido de la toma (entre −48 y −36 dBFS)."""
    n = max(1, rate * win_ms // 1000)
    levels = []
    for i in range(0, len(data) - n + 1, n):
        chunk = data[i:i + n]
        rms = math.sqrt(sum(v * v for v in chunk) / n)
        levels.append(20 * math.log10(max(rms, 1.0) / 32768))
    if not levels:
        return []
    floor = sorted(levels)[len(levels) // 20]
    threshold = max(-48.0, min(-36.0, floor + 10))
    out: list[tuple[int, int]] = []
    start = None
    for k, level in enumerate(levels + [0.0]):
        if level < threshold and start is None:
            start = k
        elif level >= threshold and start is not None:
            if (k - start) * win_ms >= min_ms:
                out.append((start * win_ms, k * win_ms))
            start = None
    return out


def _pause_kind(mid_ms: float, tokens: list[dict]) -> str:
    if len(tokens) < 2:
        return "clause"
    pairs = list(zip(tokens, tokens[1:]))
    a, _b = min(pairs, key=lambda p: abs((p[0]["end_ms"] + p[1]["start_ms"]) / 2 - mid_ms))
    if re.search(r"[.!?]$", a["text"]):
        return "sentence"
    if re.search(r"[,;:]$", a["text"]):
        return "clause"
    return "word"


def tighten_voice(src: str, dst: str, tokens: list[dict], *, target_ppm: float | None = None, max_factor: float | None = None,
                  caps: dict | None = None) -> Tightened:
    """Acorta las pausas largas (deja ``PAUSE_CAPS`` según la puntuación del
    guion alineado) y, si la toma sigue lenta, ajusta el ritmo con Rubber
    Band hasta ``target_ppm`` (tope ``max_factor``). Los tiempos de las
    palabras se trasladan con el mismo mapa: no hace falta re-alinear."""
    caps = caps or PAUSE_CAPS
    target_ppm = target_ppm or v3._env_float("NIGHTLY_NEWSCAST_TARGET_PPM_V5", 168)
    max_factor = max_factor or v3._env_float("NIGHTLY_NEWSCAST_MAX_TEMPO_V5", 1.08)
    rate, data = _read_pcm(src)
    total_ms = int(len(data) * 1000 / rate)
    words = max(1, len(tokens)) if tokens else 1
    ppm_before = words / max(1e-3, total_ms / 60000)
    cuts: list[tuple[int, int]] = []   # (inicio en el original, ms quitados)
    for s, e in detect_silences(data, rate):
        if s <= 0:
            keep = 30
            if e > keep:
                cuts.append((0, e - keep))
            continue
        if e >= total_ms - 10:
            keep = 80
            if e - s > keep:
                cuts.append((s + keep, e - s - keep))
            continue
        cap = caps[_pause_kind((s + e) / 2, tokens)] if tokens else caps["clause"]
        if e - s > cap + 30:
            cuts.append((s + cap // 2, e - s - cap))
    # Se quita el centro de cada pausa larga; 2 ms de fundido a cada lado del
    # empalme (son zonas de silencio: evita cualquier clic).
    out = array.array("h")
    cursor = 0  # muestra
    fade = max(1, rate * 2 // 1000)
    for at, length in cuts:
        a = int(at * rate / 1000)
        b = int((at + length) * rate / 1000)
        piece = data[cursor:a]
        for k in range(min(fade, len(piece))):
            piece[len(piece) - 1 - k] = int(piece[len(piece) - 1 - k] * k / fade)
        out.extend(piece)
        cursor = b
        for k in range(min(fade, max(0, len(data) - cursor))):
            data[cursor + k] = int(data[cursor + k] * k / fade)
    out.extend(data[cursor:])
    removed = sum(length for _a, length in cuts)

    def mapped(t: float) -> float:
        shift = 0.0
        for at, length in cuts:
            if t >= at + length:
                shift += length
            elif t > at:
                shift += t - at
        return t - shift

    compact_ms = int(len(out) * 1000 / rate)
    ppm_mid = words / max(1e-3, compact_ms / 60000)
    factor = min(max_factor, target_ppm / ppm_mid) if tokens else 1.0
    tmp = dst + ".pausas.wav"
    _write_pcm(tmp, rate, out)
    if factor > 1.015:
        _stretch(tmp, dst, factor)
        os.unlink(tmp)
    else:
        factor = 1.0
        os.replace(tmp, dst)
    with wave.open(dst, "rb") as w:
        final_ms = int(w.getnframes() * 1000 / w.getframerate())
    moved = [{**t, "start_ms": int(mapped(t["start_ms"]) / factor), "end_ms": int(mapped(t["end_ms"]) / factor)} for t in tokens]
    for t in moved:
        t["end_ms"] = min(max(t["end_ms"], t["start_ms"] + 1), final_ms)
    result = Tightened(ms=final_ms, tokens=moved, factor=round(factor, 3), removed_ms=removed, ppm_before=round(ppm_before, 1),
                       ppm_after=round(words / max(1e-3, final_ms / 60000), 1))
    logger.info("Voz V5: %d palabras, %.0f → %.0f ppm (pausas −%d ms, ritmo ×%.3f)", words, result.ppm_before, result.ppm_after,
                removed, result.factor)
    return result


def _stretch(src: str, dst: str, factor: float) -> None:
    """Rubber Band conserva formantes (voz natural); si el ffmpeg del host no
    lo trae, atempo (WSOLA) con el mismo factor."""
    for chain in (f"rubberband=tempo={factor:.4f}:formant=preserved", f"atempo={factor:.4f}"):
        done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", chain, "-ar", "48000", "-ac", "1", dst],
                              capture_output=True, timeout=120)
        if done.returncode == 0 and os.path.isfile(dst):
            return
    raise RuntimeError("no se pudo ajustar el ritmo de la locución")


# ── Encuadres ────────────────────────────────────────────────────────────
def base_mode(asset: v3.Asset) -> str:
    """full: pantalla completa sin ampliar más de 2×; band: franja con la
    foto nítida y su extensión desenfocada (fotos apaisadas de ≥ 660 px de
    alto); card: foto enmarcada sobre su propio fondo (fotos chicas)."""
    if not asset.width or not asset.height:
        return "card"
    check = asset.check or {}
    zone = str(check.get("zona_texto") or "ninguna")
    cover_up = max(1080 / asset.width, 1920 / asset.height)
    if asset.type == "video":
        return "full" if cover_up <= FULL_MAX_UPSCALE else "band"
    if cover_up <= FULL_MAX_UPSCALE and zone in ("", "ninguna") and not check.get("sujetos_en_bordes"):
        return "full"
    aspect = asset.width / asset.height
    if BAND_H / asset.height <= BAND_MAX_UPSCALE and aspect * BAND_H >= 1180:
        return "band"
    return "card"


def detail_zoom(asset: v3.Asset, mode: str) -> float:
    """Acercamiento del plano detalle sin pasar ``DETAIL_MAX_UPSCALE``; 0 si
    la foto no lo soporta (se alterna entre planos generales)."""
    if asset.type == "video" or not asset.width or not asset.height:
        return 0.0
    if mode == "full":
        base = max(1080 / asset.width, 1920 / asset.height)
    elif mode == "band":
        base = BAND_H / asset.height
    else:
        base = CARD_W / asset.width
    k = math.floor(min(1.55, DETAIL_MAX_UPSCALE / base) * 1000) / 1000
    return k if k >= 1.22 else 0.0


def _center_x(asset: v3.Asset, focus: float, mode: str) -> float:
    """Posición de paneo (0 = borde izquierdo, 1 = derecho) que centra el
    foco en la franja; 0,5 si la imagen no desborda."""
    if mode != "band":
        return 0.5
    width = BAND_H * asset.width / asset.height
    overflow = width - 1080
    if overflow <= 1:
        return 0.5
    return round(max(0.0, min(1.0, (focus * width - 540) / overflow)), 4)


def shot_move(asset: v3.Asset, mode: str, framing: str, variant: int) -> dict:
    """Movimiento de cámara determinista por modo y variante (sin azar)."""
    check = asset.check or {}
    fx = v3._f(check.get("foco_x"), 0.5)
    k = detail_zoom(asset, mode) if framing == "detail" else 1.0
    if mode == "band":
        center = _center_x(asset, fx, mode)
        swing = 0.16 if variant % 2 == 0 else -0.16
        if framing == "detail":
            return {"s0": k, "s1": round(k * 1.045, 3), "x0": center, "x1": center, "y0": 0.0, "y1": 0.0, "r0": 0.0, "r1": 0.0}
        x0 = round(max(0.0, min(1.0, center - swing)), 4)
        return {"s0": 1.0 if variant % 2 == 0 else 1.05, "s1": 1.05 if variant % 2 == 0 else 1.0, "x0": x0, "x1": center,
                "y0": 0.0, "y1": 0.0, "r0": 0.0, "r1": 0.0}
    if mode == "card":
        tilt = -1.6 if variant % 2 == 0 else 1.4
        if framing == "detail":
            return {"s0": k, "s1": round(k * 1.05, 3), "x0": 0.0, "x1": 0.0, "y0": 0.0, "y1": -0.006, "r0": tilt * 0.3, "r1": tilt * 0.1}
        return {"s0": 1.0, "s1": 1.06, "x0": 0.0, "x1": 0.0, "y0": 0.014, "y1": -0.004, "r0": tilt, "r1": round(tilt * 0.35, 3)}
    direction = 1 if fx >= 0.5 else -1
    if framing == "detail":
        return {"s0": k, "s1": round(k * 1.04, 3), "x0": 0.0, "x1": round(-direction * 0.008, 4), "y0": 0.0, "y1": 0.0, "r0": 0.0, "r1": 0.0}
    if variant % 2 == 0:
        return {"s0": 1.0, "s1": 1.08, "x0": 0.0, "x1": round(-direction * 0.012, 4), "y0": 0.0, "y1": -0.006, "r0": 0.0, "r1": 0.0}
    return {"s0": 1.09, "s1": 1.0, "x0": round(direction * 0.012, 4), "x1": 0.0, "y0": -0.004, "y1": 0.0, "r0": 0.0, "r1": 0.0}


def _media(asset: v3.Asset, source_in_ms: int = 0) -> dict:
    check = asset.check or {}
    return {
        "id": asset.id, "note": asset.note_id, "type": asset.type, "file": asset.file, "width": asset.width, "height": asset.height,
        "focusX": v3._f(check.get("foco_x"), 0.5), "focusY": v3._f(check.get("foco_y"), 0.45), "label": asset.label,
        "sourceInFrames": v3.ms_to_frame(source_in_ms), "durationMs": asset.duration_ms,
    }


# ── Plan ─────────────────────────────────────────────────────────────────
def _boundaries(tokens: list, voice_at: int) -> tuple[list[int], list[int]]:
    """Pausas de oración/cláusula (preferidas) y fronteras entre palabras
    (alternativa), en ms de la historia."""
    toks = [v3._tok(t) for t in tokens]
    strong, weak = [], []
    for a, b in zip(toks, toks[1:]):
        at = voice_at + int((a["end_ms"] + b["start_ms"]) / 2)
        (strong if re.search(r"[.;:,]$", a["text"]) else weak).append(at)
    return strong, weak


def _segments(lo: int, hi: int, strong: list[int], weak: list[int]) -> list[tuple[int, int]]:
    """Reparte [lo, hi) en tomas de ~``SHOT_TARGET_MS`` cortando en pausas
    reales (o, si no hay, entre palabras), nunca por debajo del mínimo."""
    span = hi - lo
    pieces = max(1, int(round(span / SHOT_TARGET_MS)))
    if span < 2 * SHOT_MIN_MS:
        return [(lo, hi)]
    cuts = [lo]
    for k in range(1, pieces):
        ideal = lo + span * k / pieces
        options = [(abs(c - ideal), c) for c in strong if cuts[-1] + SHOT_MIN_MS <= c <= hi - SHOT_MIN_MS]
        options += [(abs(c - ideal) + 450, c) for c in weak if cuts[-1] + SHOT_MIN_MS <= c <= hi - SHOT_MIN_MS]
        if not options:
            continue
        cost, best = min(options)
        if cost > span / pieces * 0.55:
            continue
        cuts.append(best)
    cuts.append(hi)
    return list(zip(cuts, cuts[1:]))


def _word_time(tokens: list, word: str) -> int | None:
    target = nn._fold(word)
    for t in (v3._tok(x) for x in tokens):
        if v3._word(t["text"]) == target:
            return t["start_ms"]
    return None


def _map_slot(story: v3.StoryInput, story_ms: int, voice_at: int, *, lead: bool) -> dict | None:
    """Mapa cuando un tramo tiene una localidad del nomenclador: entra cuando
    la voz la nombra (o en la segunda frase si no la nombra) y deja foto
    antes y después."""
    if story_ms < 5200 or story.block.get("sensible"):
        return None
    for tramo in story.block["tramos"]:
        place = locate(tramo.get("lugar") or "")
        if not place:
            continue
        label = tramo["lugar"]
        first = next((w for w in label.split() if nn._fold(w) not in ("villa", "la", "el", "de", "del")), label)
        said = _word_time(story.tokens, first) if story.align_ok else None
        earliest = LEAD_HEADLINE_MS + 200 if lead else SHOT_MIN_MS
        start = voice_at + said - 300 if said is not None else voice_at + 2200
        start = max(earliest, start)
        if start + MAP_MS > story_ms - SHOT_MIN_MS:
            start = story_ms - SHOT_MIN_MS - MAP_MS
        if start < earliest:
            return None
        return {"startMs": start, "endMs": start + MAP_MS, "place": {**place, "label": label}, "said": said is not None}
    return None


def plan_story_v5(story: v3.StoryInput, story_ms: int, voice_at: int, ledger: dict, *, index: int) -> tuple[list[dict], dict | None, list[str]]:
    """Tomas de una historia (ms relativos a su inicio): general, detalle y
    contraplano del material elegible, mapa si corresponde."""
    notes: list[str] = []
    eligible = [a for a in story.assets if a.eligible]
    pool = v3._pick(eligible, story.block["ids"], ledger)
    strong, weak = _boundaries(story.tokens, voice_at) if story.align_ok else ([], [])
    map_slot = _map_slot(story, story_ms, voice_at, lead=index == 0) if pool else None
    spans: list[tuple[int, int, str]] = []
    if map_slot:
        spans += [(a, b, "photo") for a, b in _segments(0, map_slot["startMs"], strong, weak)]
        spans.append((map_slot["startMs"], map_slot["endMs"], "map"))
        spans += [(a, b, "photo") for a, b in _segments(map_slot["endMs"], story_ms, strong, weak)]
    else:
        spans = [(a, b, "photo") for a, b in _segments(0, story_ms, strong, weak)]
    shots: list[dict] = []
    shown: set[str] = set()
    photo_k = 0
    for a, b, kind in spans:
        if not pool:
            shots.append({"startMs": a, "endMs": b, "kind": "type", "mode": "type", "framing": "wide", "media": None,
                          "move": {"s0": 1, "s1": 1, "x0": 0, "x1": 0, "y0": 0, "y1": 0, "r0": 0, "r1": 0}})
            continue
        asset = pool[photo_k % len(pool)] if len(pool) > 1 and photo_k % 2 == 1 else pool[0]
        mode = base_mode(asset)
        if kind == "map":
            shots.append({"startMs": a, "endMs": b, "kind": "map", "mode": "map", "framing": "wide", "media": _media(asset),
                          "place": map_slot["place"], "move": {"s0": 1.0, "s1": 1.16, "x0": 0, "x1": 0, "y0": 0, "y1": 0, "r0": 0, "r1": 0}})
            continue
        source_in = 0
        if asset.type == "video":
            source_in = v3._video_in(asset, b - a, ledger)
            if source_in < 0:
                asset = next((x for x in pool if x.type == "image"), pool[0])
                mode, source_in = base_mode(asset), 0
        # Patrón: general → detalle → contraplano → detalle… (el detalle sólo
        # si la resolución lo soporta y la foto ya se presentó en general; el
        # video conserva su propio movimiento).
        if asset.type == "video" or asset.id not in shown:
            framing = "wide"
        elif photo_k % 2 == 1 and detail_zoom(asset, mode):
            framing = "detail"
        else:
            framing = "wide"
        shown.add(asset.id)
        variant = photo_k // 2 + index
        shots.append({"startMs": a, "endMs": b, "kind": asset.type, "mode": mode, "framing": framing,
                      "media": _media(asset, max(0, source_in)), "move": shot_move(asset, mode, framing, variant)})
        v3._book(ledger, asset, {"media": {"sourceInMs": max(0, source_in)}, "startMs": a, "endMs": b})
        photo_k += 1
    if not shots:
        notes.append("sin tomas")
    return shots, map_slot, notes


_NUMBER_WORDS = set(v3._NUMBER_WORDS)


def caption_keys(block: dict) -> set[str]:
    """Palabras que se marcan en el subtítulo: lugares de los tramos, cifras
    del dato y términos clave del hecho."""
    keys: set[str] = set()
    for tramo in block["tramos"]:
        for w in (tramo.get("lugar") or "").split():
            f = v3._word(w)
            if f and f not in ("barrio", "villa", "la", "el", "de", "del", "en", "los", "las"):
                keys.add(f)
        for w in (tramo.get("dato") or "").split():
            keys.add(v3._word(w))
    return {k for k in keys if k}


def build_captions(tokens: list, offset_ms: int, story_index: int, f_end: int, block: dict, fps: int = FPS) -> list[dict]:
    """Subtítulos cinéticos: grupos de 1–4 palabras (≤ 24 caracteres), cada
    palabra con su frame y, como mucho, una palabra clave marcada por grupo."""
    from utils.newscast_align import Token, build_cues

    toks = [t if isinstance(t, Token) else Token(t["text"], t["start_ms"], t["end_ms"], t.get("method", "asr")) for t in tokens]
    keys = caption_keys(block)
    # La palabra clave del titular ya va en rojo arriba: no se repite abajo.
    headline_key = {v3._word(w) for w in (block.get("palabra_clave") or "").split()}
    out = []
    for cue in build_cues(toks, offset_ms=offset_ms, max_words=4, max_chars=24, min_ms=420, hold_gap_ms=300):
        a = v3.ms_to_frame(cue["startMs"], fps)
        b = min(v3.ms_to_frame(cue["endMs"], fps), f_end)
        if b <= a:
            continue
        words = []
        marked = False
        for k, w in enumerate(cue["words"]):
            folded = v3._word(w["text"])
            nxt = v3._word(cue["words"][k + 1]["text"]) if k + 1 < len(cue["words"]) else ""
            # Una cifra se marca sólo si es el dato del guion o cuenta algo
            # ("dos mujeres", "4 hectáreas"): no rutas, horas ni edades (una
            # edad no informa y, con menores, expone).
            quantity = (folded in _NUMBER_WORDS or folded.isdigit()) and any(nxt.startswith(n) for n in v3.COUNT_NOUNS)
            age = nxt.startswith("ano")
            is_key = (folded in keys or folded in v3.KEY_TERMS or quantity) and folded not in headline_key and not age
            words.append({"text": w["text"], "from": v3.ms_to_frame(w["startMs"], fps), "key": bool(is_key and not marked)})
            marked = marked or is_key
        out.append({"text": cue["text"], "from": a, "to": b, "story": story_index, "words": words})
    return out


def _inserts(story: v3.StoryInput, voice_at: int, story_ms: int, map_slot: dict | None, f0: int, start_ms: int, *, compact_ms: int,
             fps: int = FPS) -> list[dict]:
    """Datos y lugar que entran cuando la voz los dice. Si la voz los dice
    mientras el titular grande todavía está en pantalla, esperan a que suba
    (como mucho 900 ms después); nunca se superponen con el mapa ni muestran
    una edad como "dato" (no informa y, con menores, expone)."""
    items = []
    if not story.align_ok:
        return items
    map_lo, map_hi = (map_slot["startMs"], map_slot["endMs"]) if map_slot else (None, None)
    for item in v3.detect_emphasis(story.block, story.tokens, voice_at, story_ms, allow_tag=False):
        at = item.pop("atMs")
        if item["kind"] == "place" and map_slot:
            continue
        if re.search(r"\baños?\b", item.get("text", ""), re.IGNORECASE):
            continue
        if at < compact_ms + 100:
            if compact_ms - at > 900:
                continue
            at = compact_ms + 100
        hold = 1500 if item["kind"] == "place" else 1800
        until = min(story_ms - 150, at + hold)
        if map_lo is not None and at < map_hi and until > map_lo:
            if at < map_lo and map_lo - 100 - at >= 900:
                until = map_lo - 100
            else:
                continue
        if until - at < 900:
            continue
        items.append({**item, "at": v3.ms_to_frame(start_ms + at, fps) - f0, "until": v3.ms_to_frame(start_ms + until, fps) - f0})
    return items


def _transition(index: int, count: int) -> str:
    if count >= 5 and index == count // 2:
        return "brand"
    return TRANSITIONS_V5[(index - 1) % len(TRANSITIONS_V5)]


def build_plan_v5(stories: list[v3.StoryInput], *, outro_voice: str, outro_ms: int, outro_tokens: list | None, date_label: str,
                  fps: int = FPS, cta: str = v3.CTA_DEFAULT, music: dict | None = None, diagnostics: list[str] | None = None,
                  style: str = "headline", kicker: str = KICKER_DEFAULT, test_banner: str = "") -> dict:
    """Plan audiovisual completo (función pura: mismo input → mismo plan)."""
    ledger: dict = {}
    cursor = 0
    plan_stories, voices, captions, sfx = [], [], [], []
    sfx.append({"file": "newscast/impact.mp3", "from": 0, "volume": 0.42})
    count = len(stories)
    for i, story in enumerate(stories):
        lead = i == 0
        voice_at = LEAD_FIRST_MS if lead else LEAD_MS
        story_ms = voice_at + story.voice_ms + GAP_MS
        start = cursor
        shots, map_slot, notes = plan_story_v5(story, story_ms, voice_at, ledger, index=i)
        f0 = v3.ms_to_frame(start, fps)
        f1 = v3.ms_to_frame(start + story_ms, fps)
        frame_shots = []
        for s in shots:
            a = v3.ms_to_frame(start + s["startMs"], fps) - f0
            b = v3.ms_to_frame(start + s["endMs"], fps) - f0
            if b > a:
                frame_shots.append({**{k: v for k, v in s.items() if k not in ("startMs", "endMs")}, "from": a, "durationInFrames": b - a})
        for x, y in zip(frame_shots, frame_shots[1:]):
            x["durationInFrames"] = y["from"] - x["from"]
        if frame_shots:
            frame_shots[0]["durationInFrames"] += frame_shots[0]["from"]
            frame_shots[0]["from"] = 0
            frame_shots[-1]["durationInFrames"] = (f1 - f0) - frame_shots[-1]["from"]
        block = story.block
        compact = v3.compact_at(block, story.tokens, voice_at, story.align_ok)
        if lead:
            compact = max(compact, LEAD_HEADLINE_MS)
        if map_slot:
            # El titular grande termina de subir antes de que entre el mapa.
            compact = min(compact, map_slot["startMs"] - 450)
        for s in frame_shots:
            if s["kind"] == "map":
                sfx.append({"file": "newscast/ping.mp3", "from": f0 + s["from"] + 8, "volume": 0.3})
        inserts = _inserts(story, voice_at, story_ms, map_slot, f0, start, compact_ms=compact, fps=fps)
        for item in inserts:
            if item["kind"] in ("data", "count"):
                sfx.append({"file": "newscast/tick.mp3", "from": f0 + item["at"], "volume": 0.28})
        voices.append({"file": story.voice_file, "from": v3.ms_to_frame(start + voice_at, fps),
                       "durationInFrames": v3.ms_to_frame(start + voice_at + story.voice_ms, fps) - v3.ms_to_frame(start + voice_at, fps)})
        if story.align_ok and story.tokens:
            captions += build_captions(story.tokens, start + voice_at, i, f1, block, fps)
        entry = {
            "index": i, "ids": block["ids"], "seccion": block["seccion"], "tipo": block["tipo"], "lead": lead,
            "headline": block["titulo"], "strip": block.get("titulo_corto") or block["titulo"], "keyword": block.get("palabra_clave") or "",
            "tag": "Justicia" if block["tipo"] == "judicial" else ("En breve" if block["tipo"] == "breve" else "Policiales"),
            "lugar": block.get("lugar") or next((t["lugar"] for t in block["tramos"] if t.get("lugar")), ""),
            "sensible": bool(block.get("sensible")), "from": f0, "durationInFrames": f1 - f0,
            "compactAt": v3.ms_to_frame(start + compact, fps) - f0, "shots": frame_shots, "inserts": inserts,
            "wipe": "cut" if lead else _transition(i, count), "captionsOk": bool(story.align_ok and story.tokens), "notes": notes,
            "rejected": [a.public() for a in story.assets if not a.eligible],
        }
        if not lead:
            sfx.append({"file": "newscast/whoosh.mp3", "from": max(0, f0 - TRANSITION_FRAMES), "volume": 0.5 if i % 2 else 0.42})
        plan_stories.append(entry)
        cursor = start + story_ms
    outro_start = cursor
    outro_len = max(OUTRO_MIN_MS, OUTRO_LEAD_MS + outro_ms + OUTRO_TAIL_MS)
    of0 = v3.ms_to_frame(outro_start, fps)
    of1 = v3.ms_to_frame(outro_start + outro_len, fps)
    sfx.append({"file": "newscast/whoosh.mp3", "from": max(0, of0 - TRANSITION_FRAMES), "volume": 0.45})
    sfx.append({"file": "newscast/sting.mp3", "from": of0, "volume": 0.5})
    tiles = []
    for s in plan_stories:
        media = next((sh["media"] for sh in s["shots"] if sh.get("media") and sh["media"]["type"] == "image"), None)
        if media and len(tiles) < 6:
            tiles.append({"file": media["file"], "focusX": media["focusX"], "focusY": media["focusY"]})
    first_media = lambda s: next((sh["media"] for sh in s["shots"] if sh.get("media")), None)  # noqa: E731
    opening = {
        "style": style if style in OPENING_STYLES else "headline", "brandFrames": OPEN_BRAND_FRAMES, "kicker": kicker,
        "region": "La Rioja", "dateLabel": date_label, "count": count,
        "teasers": [{"title": s["strip"], "file": (first_media(s) or {}).get("file", ""), "focusX": (first_media(s) or {}).get("focusX", 0.5),
                     "focusY": (first_media(s) or {}).get("focusY", 0.5)} for s in plan_stories[:3]],
        "places": [sh["place"] for s in plan_stories for sh in s["shots"] if sh["kind"] == "map"][:5],
    }
    return {
        "version": PLAN_VERSION, "fps": fps, "width": 1080, "height": 1920, "totalFrames": of1,
        "edition": {"brand": "La Voz Riojana", "kicker": kicker, "region": "La Rioja", "dateLabel": date_label, "count": count,
                    "handle": cta, "testBanner": test_banner},
        "opening": opening, "stories": plan_stories, "voices": voices, "captions": captions,
        "outro": {"from": of0, "durationInFrames": of1 - of0, "cta": cta, "site": "lavozriojana.com",
                  "lines": v3.outro_lines(v3.OUTRO_TEXT_V3, outro_tokens or [], outro_start + OUTRO_LEAD_MS, fps), "tiles": tiles,
                  "voice": {"file": outro_voice, "from": v3.ms_to_frame(outro_start + OUTRO_LEAD_MS, fps),
                            "durationInFrames": v3.ms_to_frame(outro_start + OUTRO_LEAD_MS + outro_ms, fps) - v3.ms_to_frame(outro_start + OUTRO_LEAD_MS, fps)}
                  if outro_voice else None},
        "music": music, "sfx": sorted(sfx, key=lambda x: x["from"]), "ledger": dict(ledger), "diagnostics": diagnostics or [],
    }


def validate_plan_v5(plan: dict, assets_by_id: dict | None = None) -> list[str]:
    """Invariantes: continuidad sin huecos, tomas que cubren su historia,
    recursos del hecho y elegibles, video leído dentro de su duración,
    voces y subtítulos dentro de su historia y nunca sobre el cierre,
    datos dentro de la historia, mapa sólo con lugar del nomenclador."""
    errors = []
    fps = plan["fps"]
    cursor = 0
    for s in plan["stories"]:
        label = f"historia {s['index'] + 1}"
        if s["from"] != cursor:
            errors.append(f"{label}: empieza en {s['from']} y debía en {cursor}")
        shot_cursor = 0
        for k, shot in enumerate(s["shots"]):
            if shot["from"] != shot_cursor or shot["durationInFrames"] <= 0:
                errors.append(f"{label} toma {k + 1}: hueco o duración inválida")
            shot_cursor = shot["from"] + shot["durationInFrames"]
            media = shot.get("media")
            if media and media["note"] not in s["ids"]:
                errors.append(f"{label} toma {k + 1}: recurso de {media['note']} sobre el hecho {s['ids']}")
            if media and media["type"] == "video" and media["sourceInFrames"] + shot["durationInFrames"] > v3.ms_to_frame(media["durationMs"], fps) + 1:
                errors.append(f"{label} toma {k + 1}: lee el video después de su final")
            if media and assets_by_id is not None and (media["id"] not in assets_by_id or not assets_by_id[media["id"]].eligible):
                errors.append(f"{label} toma {k + 1}: recurso no elegible")
            if shot["kind"] == "map" and not (shot.get("place") or {}).get("name"):
                errors.append(f"{label} toma {k + 1}: mapa sin localidad del nomenclador")
        if shot_cursor != s["durationInFrames"]:
            errors.append(f"{label}: las tomas cubren {shot_cursor} de {s['durationInFrames']} frames")
        for item in s["inserts"]:
            if not 0 <= item["at"] < item["until"] <= s["durationInFrames"]:
                errors.append(f"{label}: dato '{item['text']}' fuera de su historia")
        cursor = s["from"] + s["durationInFrames"]
    if plan["outro"]["from"] != cursor:
        errors.append("el cierre no empieza donde termina la última historia")
    if plan["outro"]["from"] + plan["outro"]["durationInFrames"] != plan["totalFrames"]:
        errors.append("la duración total no coincide con el cierre")
    for k, v in enumerate(plan["voices"]):
        s = plan["stories"][k]
        if v["from"] < s["from"] or v["from"] + v["durationInFrames"] > s["from"] + s["durationInFrames"]:
            errors.append(f"historia {k + 1}: la voz no entra completa en su historia")
    last = -1
    for c in plan["captions"]:
        if c["story"] >= len(plan["stories"]) or c["to"] > plan["outro"]["from"]:
            errors.append(f"subtítulo '{c['text'][:20]}' sobre el cierre")
            continue
        s = plan["stories"][c["story"]]
        if c["from"] < s["from"] or c["to"] > s["from"] + s["durationInFrames"]:
            errors.append(f"subtítulo '{c['text'][:20]}' fuera de su historia")
        if c["from"] < last:
            errors.append(f"subtítulo '{c['text'][:20]}' se superpone con el anterior")
        last = c["to"]
    if plan["totalFrames"] > v3.ms_to_frame(_env_int("NIGHTLY_NEWSCAST_MAX_MS_V5", 119_000), fps):
        errors.append("la edición supera la duración máxima")
    return errors


# ── Caption ──────────────────────────────────────────────────────────────
def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text).strip()


def caption_v5(day: date, blocks: list[dict], *, limit: int = 2200) -> str:
    """Caption informativo y verificado: la primera línea es el hecho que
    abre el Reel (texto ya validado del guion); después, un renglón por
    hecho, un cierre y 4 hashtags. Sin fuentes, sin mayúsculas sostenidas
    ni emojis. Siempre por debajo de ``limit`` caracteres."""
    if not blocks:
        return HASHTAGS_V5
    lead = blocks[0]
    opening = " ".join(t["texto"] for t in lead["tramos"]).strip()
    head = [opening, "", f"El resumen policial de La Rioja, en {len(blocks)} hechos:" if len(blocks) > 1 else "El resumen policial de La Rioja."]
    lines = []
    for b in blocks[1:]:
        sentence = _first_sentence(b["tramos"][0]["texto"])
        place = (b.get("lugar") or b["tramos"][0].get("lugar") or "").strip()
        if place and nn._fold(place) not in nn._fold(sentence):
            sentence = f"{place[0].upper() + place[1:]}: {sentence[0].lower() + sentence[1:]}"
        lines.append(f"• {sentence}")
    tail = ["", "Las notas completas, en lavozriojana.com", "", HASHTAGS_V5]
    while lines and len("\n".join(head + lines + tail)) > limit:
        lines.pop()
    text = "\n".join(head + lines + tail)
    return text[:limit]


# ── Armado ───────────────────────────────────────────────────────────────
def ensure_ping(remotion_dir: str) -> None:
    """Acento del mapa (sintetizado con ffmpeg, propio): campana suave."""
    path = os.path.join(remotion_dir, "public", "newscast", "ping.mp3")
    if os.path.isfile(path):
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.5*sin(2*PI*1320*t)*exp(-9*t)+0.25*sin(2*PI*1980*t)*exp(-14*t)':s=48000:d=0.45",
                    "-af", "afade=t=in:d=0.004,lowpass=f=6000", "-c:a", "libmp3lame", "-b:a", "128k", path],
                   check=True, capture_output=True, timeout=60)


def order_v5(blocks: list[dict], assets: dict[str, list[v3.Asset]]) -> tuple[list[dict], list[str]]:
    """Abre el bloque que el guion puso primero si tiene imagen propia (el
    prompt le pide el hecho más contundente); el resto, por importancia."""
    def material(b):
        return max([a.score for n in b["ids"] for a in assets.get(n, []) if a.eligible] or [0.0])

    if not blocks:
        return [], []
    lead = blocks[0] if material(blocks[0]) > 0 else max(blocks, key=lambda b: v3.story_score(b, material(b)))
    rest = sorted((b for b in blocks if b is not lead), key=lambda b: -v3.story_score(b, material(b)))
    return [lead, *rest], [f"orden: abre '{lead['titulo']}'; el resto por importancia"]


def build_edition_v5(day: date, candidates: list[nn.Candidate], script: v3.ScriptV3, *, providers: dict | None = None) -> nn.Edition:
    """Arma la edición V5. ``providers`` permite inyectar descarga, control
    visual, locución, alineamiento y render (fixtures sin red ni costo)."""
    from utils.newscast_align import align_clip
    from utils.remotion_renderer import REMOTION_DIR

    providers = providers or {}
    timings: dict[str, float] = {}
    clock = time.monotonic()

    def lap(name: str) -> None:
        nonlocal clock
        now = time.monotonic()
        timings[name] = round(timings.get(name, 0.0) + now - clock, 2)
        clock = now

    by_id = {c.id: c for c in candidates}
    stamp = f"newscast5_{day.isoformat()}_{int(time.time())}"
    work = os.path.join(REMOTION_DIR, "public", "tmp", stamp)
    rel = f"tmp/{stamp}"
    cache_dir = providers.get("cache_dir") or os.path.join(REMOTION_DIR, "public", "tmp", "newscast_cache")
    os.makedirs(work, exist_ok=True)
    folder = str(nn.output_dir() / "noticiero" / day.isoformat())
    os.makedirs(folder, exist_ok=True)
    calls = {"tts": 0, "vision": 0}
    diagnostics = list(script.diagnostics)
    try:
        library = v3._load_library()
        video_budget = [_env_int("NIGHTLY_NEWSCAST_MAX_VIDEOS", 6)]
        assets: dict[str, list[v3.Asset]] = {}
        for note in [x for b in script.blocks for x in b["ids"]]:
            assets[note] = v3.gather_assets(by_id[note], work, library, providers, video_budget=video_budget)
        lap("descarga")
        frames_dir = os.path.join(work, "proxies")
        os.makedirs(frames_dir, exist_ok=True)
        for block in script.blocks:
            for note in block["ids"]:
                v3.check_assets(by_id[note], assets[note], library, providers, calls, policial=block["seccion"] == "policiales",
                                sensitive=bool(block.get("sensible")), judicial=block["tipo"] == "judicial", cache_dir=cache_dir,
                                frames_dir=frames_dir)
        lap("control_visual")
        minimum = _env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS_V3", 3)
        blocks = []
        for b in script.blocks:
            if v3.require_media() and not any(a.eligible for n in b["ids"] for a in assets[n]):
                diagnostics.append(f"sale '{b['titulo']}': sin imagen propia elegible")
                continue
            blocks.append(b)
        if len(blocks) < minimum:
            raise v3.NotEnoughMaterial(f"quedan {len(blocks)} hechos con imagen propia (mínimo {minimum})")
        blocks, notes = order_v5(blocks, assets)
        diagnostics += notes
        # Locución (caché por texto), alineamiento local y ajuste de pausas/ritmo.
        synth = providers.get("tts")
        align = providers.get("align") or align_clip
        align_report, voice_report = [], []
        stories: list[v3.StoryInput] = []
        for i, b in enumerate(blocks):
            raw = os.path.join(work, f"b{i}_raw.wav")
            wav = os.path.join(work, f"b{i}.wav")
            seconds = v3.cached_tts(b["locucion"], raw, cache_dir, synth, calls)
            lap("locucion")
            result = align(raw, b["locucion"], int(seconds * 1000), cache_dir=cache_dir)
            lap("alineamiento")
            tokens = [v3._tok(t) for t in result.tokens] if result.ok else []
            try:
                tight = tighten_voice(raw, wav, tokens)
            except (OSError, ValueError, EOFError, RuntimeError, wave.Error) as exc:
                # Sin ajuste se publica la locución tal cual (V4): nunca se cae la edición por esto.
                logger.warning("Voz V5 sin ajustar (historia %d): %s", i, exc)
                diagnostics.append(f"historia {i + 1}: voz sin ajuste de pausas/ritmo ({type(exc).__name__})")
                shutil.copyfile(raw, wav)
                tight = Tightened(ms=int(seconds * 1000), tokens=tokens, factor=1.0, removed_ms=0, ppm_before=0.0, ppm_after=0.0)
            lap("voz")
            align_report.append({"story": i, "ok": result.ok, "coverage": result.coverage, "critical_ok": result.critical_ok,
                                 "errors": result.errors, "method": result.method})
            voice_report.append({"story": i, "ppm_before": tight.ppm_before, "ppm_after": tight.ppm_after, "factor": tight.factor,
                                 "removed_ms": tight.removed_ms})
            stories.append(v3.StoryInput(
                block=b, voice_file=f"{rel}/b{i}.wav", voice_ms=tight.ms, tokens=tight.tokens, assets=[a for n in b["ids"] for a in assets[n]],
                credit="", align_ok=result.ok and result.critical_ok, note_sources={},
            ))
        outro_wav = os.path.join(work, "outro.wav")
        outro_s = v3.cached_tts(v3.OUTRO_TEXT_V3, outro_wav, cache_dir, synth, calls)
        outro_align = align(outro_wav, v3.OUTRO_TEXT_V3, int(outro_s * 1000), cache_dir=cache_dir)
        lap("locucion")
        # Duración: si se pasa del tope, salen las de menor puntaje (nunca la que abre).
        max_ms = _env_int("NIGHTLY_NEWSCAST_MAX_MS_V5", 110_000)

        def real_ms() -> int:
            return sum(LEAD_MS + s.voice_ms + GAP_MS for s in stories) + max(OUTRO_MIN_MS, OUTRO_LEAD_MS + int(outro_s * 1000) + OUTRO_TAIL_MS)

        while real_ms() > max_ms and len(stories) > minimum:
            victim = min(stories[1:], key=lambda s: v3.story_score(s.block, 0.0))
            diagnostics.append(f"sale '{victim.block['titulo']}' por duración ({real_ms() / 1000:.1f} s)")
            stories.remove(victim)
        for a in [a for items in assets.values() for a in items]:
            a.file = f"{rel}/{os.path.basename(a.file)}"
        music = None
        bed = os.path.join(REMOTION_DIR, "public", "newscast", "bed.mp3")
        if nn.flag("NIGHTLY_NEWSCAST_MUSIC", "true") and os.path.isfile(bed):
            gain = v3.music_gain_db([os.path.join(work, f"b{i}.wav") for i in range(min(3, len(stories)))], bed)
            if gain is not None:
                music = {"file": "newscast/bed.mp3", "gainDb": gain, "openGainDb": gain + 5, "introGainDb": gain + 3}
        v3.ensure_tick(REMOTION_DIR)
        ensure_ping(REMOTION_DIR)
        plan = build_plan_v5(stories, outro_voice=f"{rel}/outro.wav", outro_ms=int(outro_s * 1000),
                             outro_tokens=outro_align.tokens if outro_align.ok else None, date_label=nn.date_label(day),
                             cta=os.getenv("NIGHTLY_NEWSCAST_CTA_V5", v3.CTA_DEFAULT), music=music, diagnostics=diagnostics,
                             style=providers.get("opening") or opening_style(), test_banner=providers.get("test_banner", ""))
        all_assets = {a.id: a for items in assets.values() for a in items}
        errors = validate_plan_v5(plan, all_assets)
        lap("plan")
        with open(os.path.join(folder, "visual_plan.json"), "w", encoding="utf-8") as fh:
            json.dump({**plan, "selection": providers.get("selection") or {}, "alignment": align_report, "voice": voice_report,
                       "timings": timings, "calls": calls, "validation": errors, "assets": [a.public() for a in all_assets.values()]},
                      fh, ensure_ascii=False, indent=1)
        if errors:
            raise RuntimeError(f"Plan del noticiero V5 inválido: {errors[:5]}")
        props_path = os.path.join(work, "props.json")
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False)
        raw_video = os.path.join(tempfile.gettempdir(), f"lvr_{stamp}.mp4")
        (providers.get("render") or (lambda p, o: v3.render_v3(p, o, composition=COMPOSITION)))(props_path, raw_video)
        lap("render")
        final = os.path.join(folder, f"noticiero-{day.isoformat()}.mp4")
        target = os.getenv("NIGHTLY_NEWSCAST_LUFS", "-14")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", raw_video, "-c:v", "copy", "-af", f"loudnorm=I={target}:TP=-1.5:LRA=9,alimiter=limit=0.79:level=false",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", final],
            check=True, capture_output=True, timeout=600,
        )
        os.unlink(raw_video)
        lap("normalizacion")
        cover = os.path.join(folder, "portada.jpg")
        try:
            (providers.get("render_cover") or render_cover)(props_path, cover)
        except Exception as exc:  # noqa: BLE001 — sin portada se publica con el cuadro elegido por Meta
            logger.warning("Portada del noticiero no generada: %s", str(exc)[:200])
            cover = ""
        lap("portada")
        final_blocks = [s.block for s in stories]
        caption = caption_v5(day, final_blocks)
        with open(os.path.join(folder, "texto.txt"), "w", encoding="utf-8") as fh:
            fh.write(caption)
        with open(os.path.join(folder, "guion.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "version": "v5", "gancho": final_blocks[0]["tramos"][0]["texto"] if final_blocks else "",
                "titulares": [b["titulo"] for b in final_blocks[:3]],
                "bloques": [{**b, "notas": [by_id[x].web_url for x in b["ids"]]} for b in final_blocks],
                "cierre": v3.OUTRO_TEXT_V3,
            }, fh, ensure_ascii=False, indent=2)
        v3.write_srt(plan, os.path.join(folder, "subtitulos.srt"))
        report = v3.inspect_video(final) if providers.get("inspect", True) else {}
        lap("inspeccion")
        with open(os.path.join(folder, "visual_plan.json"), "r+", encoding="utf-8") as fh:
            data = json.load(fh)
            data.update({"timings": timings, "calls": calls, "inspection": report})
            fh.seek(0)
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.truncate()
        script.blocks = final_blocks
        logger.info("Noticiero V5 %s: %d historias, %.1f s, tiempos %s, llamadas %s", day, len(final_blocks), plan["totalFrames"] / FPS, timings, calls)
        return nn.Edition(day=day, video_path=final, caption=caption, script=script, blocks=final_blocks, folder=folder,
                          cover_path=cover, caption_complete=True)
    finally:
        if not providers.get("keep_work"):
            shutil.rmtree(work, ignore_errors=True)


def render_cover(props_path: str, out_jpg: str) -> None:
    """Portada 1080×1920 con la misma dirección de arte (Remotion still)."""
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    result = subprocess.run(
        _npx_args(["remotion", "still", os.getenv("NIGHTLY_NEWSCAST_ENTRY", "src/index.ts"), COVER_COMPOSITION, out_jpg, "--frame=0",
                   "--image-format=jpeg", "--jpeg-quality=92", "--timeout=120000", f"--props={props_path}"]),
        cwd=REMOTION_DIR, capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0 or not os.path.isfile(out_jpg):
        raise RuntimeError(f"Portada del noticiero falló: {(result.stderr or result.stdout or '')[-400:]}")
