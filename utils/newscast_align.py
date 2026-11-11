"""Subtítulos del Noticiero V3 alineados con la locución realmente producida.

Gemini TTS no entrega tiempos por palabra, así que se alinea localmente el
texto aprobado contra el WAV definitivo (ya recortado y con ``atempo``) de
cada bloque:

1. whisper.cpp (CPU, modelo multilingüe ``small-q5_1``) transcribe el clip con
   tiempos por palabra. Sólo se le sugieren los nombres propios del bloque,
   nunca el texto completo, para no forzarlo a "oír" lo que esperamos.
2. Las palabras reconocidas se mapean de forma monótona (programación
   dinámica) contra las palabras del texto aprobado, comparando formas
   habladas (cifras expandidas a palabras, sin tildes).
3. Las palabras del guion sin par se ubican sólo dentro del hueco entre dos
   anclas reales vecinas, proporcional a su largo, y quedan marcadas como
   ``interpolated`` (nunca énfasis ni reparto uniforme del clip completo).
4. Se valida cobertura, orden, rangos y palabras críticas (negaciones,
   cifras, nombres). Si el audio no coincide con el guion, el bloque falla y
   NO lleva subtítulos inventados.

El resultado (tokens y cues) se cachea por hash del audio final + texto +
motor/modelo/versión; un cambio de diseño reutiliza voz y alineamiento.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field

from utils.logging_setup import setup_logger

logger = setup_logger("newscast_align", "nightly_newscast.log")

ALIGNER_VERSION = "lvr-align-3"
WHISPER_RELEASE = "b5454"
WHISPER_ZIP_URL = f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_RELEASE}/whisper-bin-x64.zip"
WHISPER_ZIP_SHA256 = "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb"
MODEL_FILE = "ggml-small-q5_1.bin"
MODEL_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{MODEL_FILE}"
MODEL_SHA256 = "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb"
MODEL_SIZE = 190085487

# Segmentación de subtítulos (referencias, la medición final la hace Remotion).
CUE_MAX_WORDS = 7
CUE_MIN_WORDS = 3
CUE_MAX_CHARS = 64  # dos líneas de ~32 caracteres
CUE_MIN_MS = 800
CPS_WARN = 20.0

NEGATIONS = {"no", "ni", "nunca", "jamas", "tampoco", "sin"}


def aligner_dir() -> str:
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "whisper")
    return os.getenv("NIGHTLY_NEWSCAST_ALIGNER_DIR") or default


def _binary() -> str:
    for name in ("whisper-cli.exe", "whisper-cli", "main.exe"):
        path = os.path.join(aligner_dir(), name)
        if os.path.isfile(path):
            return path
    return ""


def aligner_status() -> dict:
    model = os.path.join(aligner_dir(), MODEL_FILE)
    return {
        "dir": aligner_dir(),
        "binary": bool(_binary()),
        "model": os.path.isfile(model) and os.path.getsize(model) == MODEL_SIZE,
        "ok": bool(_binary()) and os.path.isfile(model) and os.path.getsize(model) == MODEL_SIZE,
    }


# ── Formas habladas ──────────────────────────────────────────────────────
def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
          "trece", "catorce", "quince", "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
          "veintidos", "veintitres", "veinticuatro", "veinticinco", "veintiseis", "veintisiete", "veintiocho", "veintinueve"]
_TENS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_HUNDREDS = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos", 6: "seiscientos",
             7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def number_words(n: int) -> list[str]:
    """Cifra entera a palabras en español (forma hablada para comparar)."""
    if n < 0:
        return ["menos", *number_words(-n)]
    if n < 30:
        return [_UNITS[n]]
    if n < 100:
        tens, unit = divmod(n, 10)
        return [_TENS[tens]] + (["y", _UNITS[unit]] if unit else [])
    if n == 100:
        return ["cien"]
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_HUNDREDS[hundreds]] + (number_words(rest) if rest else [])
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = ["mil"] if thousands == 1 else [*number_words(thousands), "mil"]
        return head + (number_words(rest) if rest else [])
    millions, rest = divmod(n, 1_000_000)
    head = ["un", "millon"] if millions == 1 else [*number_words(millions), "millones"]
    return head + (number_words(rest) if rest else [])


_SYMBOLS = {"%": ["por", "ciento"], "$": ["pesos"], "us$": ["dolares"], "km": ["kilometros"], "kg": ["kilos"]}


def spoken_forms(word: str) -> list[str]:
    """Palabra de pantalla → palabras habladas plegadas (sin tildes)."""
    raw = word.strip()
    clean = fold(re.sub(r"^[^\w$%]+|[^\w%]+$", "", raw))
    if not clean:
        return []
    hour = re.fullmatch(r"(\d{1,2}):(\d{2})", clean)
    if hour:
        h, mnt = int(hour.group(1)), int(hour.group(2))
        return number_words(h) + (number_words(mnt) if mnt else [])
    m = re.fullmatch(r"(us\$|\$)?(\d{1,3}(?:\.\d{3})+|\d+)(?:[,.](\d{1,2}))?(%)?", clean)
    if m:
        currency, integer, decimals, percent = m.groups()
        out = number_words(int(integer.replace(".", "")))
        if decimals:
            out += ["coma", *number_words(int(decimals))]
        if percent:
            out += _SYMBOLS["%"]
        if currency:
            out += _SYMBOLS[currency]
        return out
    if clean in _SYMBOLS:
        return list(_SYMBOLS[clean])
    return [w for w in re.split(r"[^\w]+", clean) if w]


@dataclass
class Token:
    text: str            # palabra tal como se muestra
    start_ms: int
    end_ms: int
    method: str          # "asr" (ancla real) | "interpolated" (entre anclas)
    score: float = 0.0
    critical: bool = False


@dataclass
class Alignment:
    ok: bool
    tokens: list[Token] = field(default_factory=list)
    coverage: float = 0.0
    critical_ok: bool = True
    errors: list[str] = field(default_factory=list)
    asr_text: str = ""
    method: str = ""
    elapsed_s: float = 0.0

    def to_json(self) -> dict:
        data = asdict(self)
        data["tokens"] = [asdict(t) for t in self.tokens]
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Alignment":
        tokens = [Token(**t) for t in data.get("tokens") or []]
        return cls(**{**data, "tokens": tokens})


def _similar(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()


def _is_critical(word: str, index: int) -> bool:
    clean = fold(re.sub(r"[^\w$%]", "", word))
    if clean in NEGATIONS or re.search(r"\d", word):
        return True
    return index > 0 and word[:1].isupper()


def map_words(script_words: list[str], asr: list[tuple[str, int, int, float]], clip_ms: int) -> Alignment:
    """Alineamiento monótono texto aprobado ↔ palabras reconocidas.

    ``asr``: (palabra, inicio_ms, fin_ms, probabilidad). Cada palabra del
    guion se expande a su forma hablada; la programación dinámica empareja
    unidades habladas con palabras ASR (sustitución por similitud ≥ 0,6)."""
    units: list[tuple[int, str]] = []  # (índice de palabra del guion, unidad hablada)
    for i, word in enumerate(script_words):
        for unit in spoken_forms(word) or [fold(word)]:
            units.append((i, unit))
    # El reconocedor escribe cifras con dígitos ("62%", "28,8"): se expanden
    # a la misma forma hablada; cada unidad conserva su palabra ASR de origen.
    asr_units: list[tuple[int, str]] = []
    for j, (w, *_rest) in enumerate(asr):
        for unit in spoken_forms(w) or [fold(re.sub(r"[^\w%$]", "", w))]:
            asr_units.append((j, unit))
    asr_folded = [u for _, u in asr_units]
    n, m = len(units), len(asr_folded)
    gap = -0.45
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
        back[i][0] = 1
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
        back[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sim = _similar(units[i - 1][1], asr_folded[j - 1])
            match = score[i - 1][j - 1] + (sim if sim >= 0.6 else -0.6)
            up = score[i - 1][j] + gap
            left = score[i][j - 1] + gap
            best = max(match, up, left)
            score[i][j] = best
            back[i][j] = 0 if best == match else (1 if best == up else 2)
    pairs: dict[int, list[int]] = {}
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j] if i > 0 and j > 0 else (1 if i > 0 else 2)
        if move == 0:
            if _similar(units[i - 1][1], asr_folded[j - 1]) >= 0.6:
                pairs.setdefault(units[i - 1][0], []).append(asr_units[j - 1][0])
            i, j = i - 1, j - 1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    tokens: list[Token | None] = []
    for idx, word in enumerate(script_words):
        hits = sorted(set(pairs.get(idx, [])))
        expected = len(spoken_forms(word) or [word])
        matched_units = len(pairs.get(idx, []))
        if hits and matched_units >= max(1, expected // 2):
            start = asr[hits[0]][1]
            end = asr[hits[-1]][2]
            prob = sum(asr[h][3] for h in hits) / len(hits)
            tokens.append(Token(word, start, max(end, start + 40), "asr", round(prob, 3), _is_critical(word, idx)))
        else:
            tokens.append(None)
    anchored = sum(1 for t in tokens if t)
    # Huecos: sólo entre anclas reales, proporcional al largo de la palabra.
    k = 0
    while k < len(tokens):
        if tokens[k] is not None:
            k += 1
            continue
        run_end = k
        while run_end < len(tokens) and tokens[run_end] is None:
            run_end += 1
        left = tokens[k - 1].end_ms if k > 0 and tokens[k - 1] else 0
        right = tokens[run_end].start_ms if run_end < len(tokens) and tokens[run_end] else clip_ms
        span = max(0, right - left)
        weights = [max(2, len(script_words[x])) for x in range(k, run_end)]
        total = sum(weights) or 1
        cursor = left
        for offset, x in enumerate(range(k, run_end)):
            length = int(span * weights[offset] / total)
            tokens[x] = Token(script_words[x], cursor, cursor + max(1, length), "interpolated", 0.0, _is_critical(script_words[x], x))
            cursor += length
        k = run_end
    final = [t for t in tokens if t is not None]
    coverage = anchored / max(1, len(script_words))
    errors = []
    critical_missing = [t.text for t in final if t.critical and t.method != "asr"]
    for a, b in zip(final, final[1:]):
        if b.start_ms < a.start_ms:
            errors.append("orden no monótono")
            break
    if any(t.start_ms < 0 or t.end_ms > clip_ms + 250 for t in final):
        errors.append("tiempos fuera del clip")
    return Alignment(
        ok=not errors,
        tokens=final,
        coverage=round(coverage, 4),
        critical_ok=not critical_missing,
        errors=errors + ([f"palabras críticas sin ancla: {critical_missing[:6]}"] if critical_missing else []),
        asr_text=" ".join(w for w, *_ in asr),
        method=f"whispercpp-{WHISPER_RELEASE}/{MODEL_FILE}/{ALIGNER_VERSION}",
    )


# ── whisper.cpp ──────────────────────────────────────────────────────────
def _asr_words(wav: str, hint: str) -> list[tuple[str, int, int, float]]:
    """Palabras con tiempos de whisper.cpp (una palabra por segmento)."""
    binary = _binary()
    model = os.path.join(aligner_dir(), MODEL_FILE)
    with tempfile.TemporaryDirectory() as tmp:
        pcm = os.path.join(tmp, "clip.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", pcm],
                       check=True, capture_output=True, timeout=120)
        base = os.path.join(tmp, "out")
        args = [binary, "-m", model, "-f", pcm, "-l", "es", "-ml", "1", "-sow", "-ojf", "-of", base, "-np",
                "-t", str(max(1, min(8, (os.cpu_count() or 4) - 2))), "--dtw", "small"]
        if hint:
            args += ["--prompt", hint[:200]]
        subprocess.run(args, check=True, capture_output=True, timeout=600)
        with open(base + ".json", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    words = []
    for seg in data.get("transcription") or []:
        text = str(seg.get("text") or "").strip()
        offsets = seg.get("offsets") or {}
        if not text or not re.search(r"\w", text):
            continue
        tokens = [t for t in seg.get("tokens") or [] if not str(t.get("text", "")).startswith("[_")]
        prob = sum(float(t.get("p") or 0) for t in tokens) / len(tokens) if tokens else 0.0
        start, end = int(offsets.get("from") or 0), int(offsets.get("to") or 0)
        # Con DTW el inicio por token es más preciso que el del segmento.
        dtw = [int(t["t_dtw"]) * 10 for t in tokens if int(t.get("t_dtw") or -1) >= 0]
        if dtw:
            start = max(0, min(dtw[0], end - 40))
        words.append((text, start, end, prob))
    return words


def _hint(text: str) -> str:
    """Sólo nombres propios del bloque como pista para el reconocedor."""
    names = re.findall(r"(?<![.!?]\s)(?<!^)\b[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+)*", text)
    seen: list[str] = ["La Voz Riojana"]
    for name in names:
        if name not in seen:
            seen.append(name)
    return ", ".join(seen[:12])


def cache_key(wav: str, text: str) -> str:
    digest = hashlib.sha256()
    with open(wav, "rb") as fh:
        digest.update(hashlib.sha256(fh.read()).digest())
    digest.update("|".join([text, "es", WHISPER_RELEASE, MODEL_FILE, ALIGNER_VERSION]).encode("utf-8"))
    return digest.hexdigest()[:20]


def align_clip(wav: str, text: str, clip_ms: int, *, cache_dir: str | None = None, runner=None) -> Alignment:
    """Alinea el texto aprobado contra el WAV final. Cachea por hash."""
    import time

    key = cache_key(wav, text)
    cached = os.path.join(cache_dir, f"align_{key}.json") if cache_dir else ""
    if cached and os.path.isfile(cached):
        with open(cached, encoding="utf-8") as fh:
            return Alignment.from_json(json.load(fh))
    started = time.monotonic()
    if runner is None and not aligner_status()["ok"]:
        return Alignment(ok=False, errors=["alineador no instalado (scripts/install_newscast_aligner.py)"])
    try:
        asr = (runner or _asr_words)(wav, _hint(text))
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        logger.warning("Alineamiento falló: %s", type(exc).__name__)
        return Alignment(ok=False, errors=[f"whisper.cpp: {type(exc).__name__}"])
    result = map_words(text.split(), asr, clip_ms)
    result = _verdict(result)
    result.elapsed_s = round(time.monotonic() - started, 2)
    if cached and result.tokens:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cached, "w", encoding="utf-8") as fh:
            json.dump(result.to_json(), fh, ensure_ascii=False)
    return result


def _verdict(result: Alignment) -> Alignment:
    """Umbrales de aceptación: con menos de 85 % de anclas el audio no
    coincide con el guion (o el reconocedor falló): no hay subtítulos."""
    if result.coverage < 0.85:
        result.ok = False
        result.errors.append(f"cobertura {result.coverage:.0%} < 85 %: el audio no coincide con el guion")
    return result


# ── Cues ─────────────────────────────────────────────────────────────────
_NO_BREAK_AFTER = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "en", "y", "e", "o",
                   "u", "que", "por", "para", "con", "sin", "su", "sus", "no", "ni", "se", "lo", "le", "les", "mas",
                   "muy", "tras", "entre", "sobre", "hasta", "desde", "como", "cuando", "donde",
                   # Cifra dicha en palabras + unidad ("cuatro | hectáreas").
                   "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "cien", "mil", "millones"}


def _can_break_after(prev: str, nxt: str) -> bool:
    p = fold(re.sub(r"[^\w]", "", prev))
    if p in _NO_BREAK_AFTER:
        return False
    # Cifra + unidad, nombre + apellido.
    if re.search(r"\d", prev) and not re.search(r"[.,;:]$", prev):
        return False
    if prev[:1].isupper() and nxt[:1].isupper() and not re.search(r"[.,;:]$", prev):
        return False
    return True


def build_cues(tokens: list[Token], *, offset_ms: int = 0, max_words: int = CUE_MAX_WORDS, max_chars: int = CUE_MAX_CHARS,
               min_ms: int = CUE_MIN_MS, hold_gap_ms: int = 400) -> list[dict]:
    """Agrupa tokens en cues de 3–7 palabras, cortando en puntuación o en
    fronteras que no separan artículo/sustantivo, cifra/unidad, nombre/
    apellido ni negación/verbo. V5 pide grupos más cortos (subtítulos
    cinéticos) con ``max_words``/``max_chars``/``min_ms``."""
    cues: list[dict] = []
    current: list[Token] = []

    def flush():
        if not current:
            return
        text = " ".join(t.text for t in current)
        cues.append({
            "text": text,
            "startMs": offset_ms + current[0].start_ms,
            "endMs": offset_ms + current[-1].end_ms,
            "words": [{"text": t.text, "startMs": offset_ms + t.start_ms, "endMs": offset_ms + t.end_ms, "method": t.method} for t in current],
        })
        current.clear()

    for i, token in enumerate(tokens):
        current.append(token)
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is None:
            break
        text = " ".join(t.text for t in current)
        sentence_end = bool(re.search(r"[.!?]$", token.text))
        clause_end = bool(re.search(r"[,;:]$", token.text))
        too_long = len(text) + 1 + len(nxt.text) > max_chars or len(current) >= max_words
        breakable = _can_break_after(token.text, nxt.text)
        if sentence_end or (clause_end and len(current) >= 2) or (too_long and breakable) or len(current) >= max_words + 2:
            flush()
    flush()
    # Cues muy breves: se unen al siguiente si caben (sin cruzar oración).
    merged: list[dict] = []
    for cue in cues:
        if merged:
            prev = merged[-1]
            short = prev["endMs"] - prev["startMs"] < min_ms
            fits = len(prev["text"]) + 1 + len(cue["text"]) <= max_chars + 8
            if short and fits and not re.search(r"[.!?]$", prev["text"]):
                prev["text"] += " " + cue["text"]
                prev["endMs"] = cue["endMs"]
                prev["words"] += cue["words"]
                continue
        merged.append(cue)
    # Cola breve de una oración ("local."): vuelve al cue anterior si entra.
    tidy: list[dict] = []
    for cue in merged:
        short = cue["endMs"] - cue["startMs"] < min_ms or len(cue["words"]) < 2
        if tidy and short and len(tidy[-1]["text"]) + 1 + len(cue["text"]) <= max_chars + 8 and not re.search(r"[.!?]$", tidy[-1]["text"]):
            tidy[-1]["text"] += " " + cue["text"]
            tidy[-1]["endMs"] = cue["endMs"]
            tidy[-1]["words"] += cue["words"]
            continue
        tidy.append(cue)
    merged = tidy
    # Cada cue dura hasta el próximo (sin parpadeo en pausas cortas).
    for a, b in zip(merged, merged[1:]):
        if 0 < b["startMs"] - a["endMs"] < hold_gap_ms:
            a["endMs"] = b["startMs"]
    return merged


def cue_metrics(cues: list[dict]) -> dict:
    """Velocidad de lectura y cues breves (para el reporte de inspección)."""
    cps = []
    short = 0
    for cue in cues:
        seconds = max(0.001, (cue["endMs"] - cue["startMs"]) / 1000)
        cps.append(len(cue["text"]) / seconds)
        short += int(seconds < CUE_MIN_MS / 1000)
    cps_sorted = sorted(cps)
    return {
        "cues": len(cues),
        "cps_median": round(cps_sorted[len(cps_sorted) // 2], 1) if cps else 0.0,
        "cps_max": round(max(cps), 1) if cps else 0.0,
        "over_20cps": sum(1 for x in cps if x > CPS_WARN),
        "short_cues": short,
    }
