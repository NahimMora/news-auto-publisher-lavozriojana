"""Noticiero V3/V4: noticiero policial de 24 h con plan audiovisual por hechos.

    biblioteca de notas propias (policiales de 24 h, fotos ya procesadas)
    → guion por tramos (un tramo = un hecho) + gancho hablado por hechos
    → inventario de fotos/videos con procedencia y control visual (caché)
    → elegibilidad (puertas) y puntaje (sólo entre elegibles)
    → locución por bloque (Orus, dirección enérgica, ritmo medido, caché)
    → alineamiento real → plan audiovisual versionado: intro, familias,
      tomas, datos que aparecen cuando la voz los dice, transiciones,
      efectos y música; milisegundos → frames en un solo lugar
    → validación del plan → Remotion ``NightlyNewscastV3`` → inspección.

Remotion ejecuta el plan: no clasifica recursos ni llama a modelos. El
plan, los subtítulos y la inspección quedan junto al MP4 para auditoría.
Se activa con ``NIGHTLY_NEWSCAST_VISUAL=v3``; V2 sigue intacta.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from utils import nightly_newscast as nn
from utils.logging_setup import setup_logger

logger = setup_logger("nightly_newscast", "nightly_newscast.log")

PLAN_VERSION = "lvr-newscast-plan-4.0"
FPS = 30
FAMILIES = ("video", "photo", "timeline", "related", "data", "limited", "service", "judicial", "brief")
TIPOS = ("hecho", "hechos_relacionados", "cronologia", "servicio", "dato", "judicial", "breve")
DESCRIPTOR_DEFAULT = "Policiales · últimas 24 h"
HOOK_TAIL = ""  # la marca cierra la apertura sin locución propia
OUTRO_TEXT_V3 = "Lo que pasa en La Rioja, lo sabés acá. Seguinos."
CTA_DEFAULT = "@lavozriojana.ok"
MEDIA_CHECK_VERSION = "media-check-3"

# Tiempos (ms). Entre noticias ~340 ms de aire, cubiertos por la transición.
LEAD_FIRST_MS = 150
LEAD_MS = 200
GAP_MS = 140
INTRO_LEAD_MS = 220
INTRO_TAIL_MS = 1150
OUTRO_LEAD_MS = 150
OUTRO_TAIL_MS = 500
OUTRO_MIN_MS = 2000
OUTRO_MAX_MS = 4500
SHOT_MIN_MS = 2200
TITLE_FULL_MIN_MS = 1900
TITLE_FULL_MAX_MS = 3400
MAX_TOTAL_MS = 119_000

# Cartera editorial (pesos orientativos, configurables por entorno).
PORTFOLIO_WEIGHTS = {"interes": 0.30, "novedad": 0.20, "impacto_local": 0.20, "utilidad": 0.15, "seguimiento": 0.10, "material": 0.05}
# Puntaje de recursos elegibles (procedencia y derechos son puertas, no puntos).
ASSET_WEIGHTS = {"relevance": 0.50, "clarity": 0.20, "utility": 0.15, "framing": 0.10, "novelty": 0.05}

# Voz V4 (2026-10-31): la V3 midió ~121 palabras/min (V2 ~130). La dirección
# anterior pedía "entonación cantada y tranquila" y alargar sílabas; ésta pide
# ritmo de noticiero sin perder la tonada, y el ritmo se mide y ajusta.
VOICE_DIRECTION_V4 = (
    "Sos el locutor del noticiero policial de un medio de La Rioja, Argentina. Hablá en español argentino "
    "con una tonada riojana suave y natural, sin exagerarla: seseo y voseo, la 'll' y la 'y' como una 'ye' "
    "suave, nunca la 'sh' porteña. Voz grave, cercana, firme y con energía de noticiero: ritmo ágil, frases "
    "que avanzan sin arrastrar vocales, pausas breves sólo en los puntos. Remarcá con intención el dato "
    "fuerte de cada noticia (el lugar, la cifra, lo que pasó). Nada de tono solemne, lento, cantado ni de "
    "asistente virtual. Leé exactamente este texto, sin agregar, quitar ni cambiar palabras:\n\n"
)

SCRIPT_PROMPT_V3 = """Sos el editor del noticiero policial de la noche de La Voz Riojana, un medio de La Rioja, Argentina.
Recibís las notas que publicamos en las últimas 24 horas (policiales, judiciales, siniestros, incendios y sucesos de La Rioja; id, sección, título, texto y si el tema es sensible) y armás el guion de un Reel vertical locutado de menos de dos minutos.

Devolvé SOLO este JSON:
{"bloques": [{"ids": ["..."], "seccion": "policiales", "tipo": "hecho", "titulo": "...", "titulo_corto": "...", "palabra_clave": "...",
  "relevancia": {"interes": 3, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3},
  "tramos": [{"ids": ["..."], "lugar": "...", "texto": "...", "momento": "", "dato": ""}],
  "servicio": {"accion": "", "zona": "", "vigencia": ""}}]}

Reglas editoriales (obligatorias):
- Usá SOLO datos que estén en los textos recibidos. No inventes datos, cifras, edades, horarios, armas, personas, causas, citas ni hechos ajenos al original.
- Sólo hechos ocurridos en La Rioja (no estadísticas nacionales ni hechos de otras provincias).
- Cubrí TODOS los hechos policiales, judiciales, incendios y siniestros locales de la lista, salvo duplicados: entre 8 y 12 bloques cuando haya material. Si hay más de 12, dejá afuera los menores. No rellenes con notas sin interés.
- Las notas del MISMO hecho van juntas en un bloque con todos sus ids (aunque vengan de medios distintos). Hechos distintos van en bloques distintos; "hechos_relacionados" sólo para 2 o 3 hechos distintos y breves del mismo fenómeno, con un tramo por hecho.
- Nunca juntes en un bloque un accidente, una causa judicial y un delito. Si una nota es una denuncia, no digas que hubo detenidos.
- No sumes ni cuentes personas, heridos o hechos entre notas distintas: cada hecho con las cifras de su nota.
- "tipo": "hecho" (lo normal); "hechos_relacionados"; "cronologia" sólo si el texto da al menos dos momentos del mismo hecho en orden; "dato" si la historia se explica por una cifra de la nota; "judicial" para decisiones de la Justicia (procesamiento, juicio, condena, prisión preventiva, liberación); "breve" para un hecho secundario contado en una sola oración.
- "tramos": cada tramo tiene 1 o 2 oraciones sobre UN solo hecho y los ids de las notas que lo respaldan. La primera oración dice el hecho principal.
- Orden natural del castellano: sujeto + verbo + complemento ("Un incendio destruyó un comercio en Sanagasta", "Dos jóvenes resultaron heridas al caer de una moto"). Nunca empieces una oración con el verbo ("Destruyó un incendio…", "Resultaron heridas…").
- Ritmo de noticiero: cada bloque entre 18 y 30 palabras ("hechos_relacionados" hasta 40, "breve" entre 12 y 18). Entre todos los tramos, entre 230 y 280 palabras. Oraciones cortas y en voz activa, para el oído: sin paréntesis, comillas ni siglas sin desarrollar, sin adjetivos de opinión (escándalo, brutal, polémico, terrible).
- Presunción de inocencia: "acusado", "investigado", "detenido"; nunca des por probado lo que la nota no da por probado.
- Temas sensibles (violencia de género, abusos, suicidio, menores): se informan con cuidado, sin nombres ni datos que identifiquen a víctimas o menores, sin detalles morbosos y sin describir métodos.
- No digas días de la semana ni fechas salvo que el texto los diga. Sin saludos ni despedidas.
- "seccion": policiales para los hechos policiales, judiciales, siniestros e incendios; si no, una de interior, sociedad, economia, salud, educacion, cultura, politica.
- "titulo": titular de pantalla fiel al hecho, con un verbo fuerte, sin punto final, máximo 46 caracteres. "titulo_corto": la misma idea en máximo 30 caracteres y de 3 a 6 palabras. "palabra_clave": 1 o 2 palabras del título, tal cual aparecen en él, que concentran el hecho.
- "lugar" de cada tramo: barrio o localidad DONDE OCURRIÓ ese hecho tal como figura en el texto (máximo 22 caracteres); no el origen de las personas, ni la sede del juzgado o la fiscalía, ni una calle suelta; si no figura, "".
- "momento": la hora o el momento del hecho sólo si el texto lo dice ("anoche", "21:30"); si no, "".
- "dato": la cifra clave del tramo tal como figura en la nota y en tu texto (máximo 28 caracteres): cantidades de detenidos, heridos, hectáreas, secuestros o montos. Nunca una edad. Si no hay, "".
- "titulo_corto" abre el Reel cuando el hecho está entre los principales: escribilo como una frase de radio contundente y fiel (por ejemplo "Fuego destruyó un comercio en Sanagasta"), gramatical y completa: no omitas preposiciones ni artículos ("Juicio por tentativa de femicidio", nunca "Juicio por tentativa femicidio"). Respetá la situación procesal exacta de la nota: si dice "demorado", nunca "detenido"; si dice "aprehendido", nunca "imputado" ni "condenado".
- "relevancia": de 1 a 5 cada criterio, según el texto (no según si hay fotos).
"""


def visual_version() -> str:
    return (os.getenv("NIGHTLY_NEWSCAST_VISUAL") or "v2").strip().lower()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def ms_to_frame(ms: float, fps: int = FPS) -> int:
    """Única conversión ms → frame del plan: fronteras, no duraciones."""
    return int(round(ms * fps / 1000))


# ── Guion ────────────────────────────────────────────────────────────────
@dataclass
class ScriptV3:
    blocks: list[dict]
    diagnostics: list[str] = field(default_factory=list)
    hook_frases: list[dict] = field(default_factory=list)

    @property
    def hook(self) -> str:
        frases = " ".join(f["texto"] for f in self.hook_frases)
        return f"{frases} {HOOK_TAIL}".strip() if frases else (self.blocks[0]["tramos"][0]["texto"] if self.blocks else "")


FUNCTION_WORDS = {"de", "del", "la", "el", "los", "las", "en", "a", "al", "por", "con", "un", "una", "y"}
HOOK_MAX_WORDS = 10
INTRO_MAX_MS = 7000


def repair_short_title(short: str, title: str) -> str:
    """Repone las preposiciones y artículos que el título corto se comió
    ("tentativa femicidio" → "tentativa de femicidio") tomándolos del título
    completo o de la locución. Sólo inserta palabras funcionales que ya están
    en ese texto, entre las mismas dos palabras."""
    words = short.split()
    full = title.split()
    folded = [nn._fold(w).strip(".,;:") for w in full]
    out: list[str] = []
    for k, word in enumerate(words):
        out.append(word)
        if k + 1 >= len(words):
            break
        a, b = nn._fold(word).strip(".,;:"), nn._fold(words[k + 1]).strip(".,;:")
        for i, w in enumerate(folded):
            if w != a:
                continue
            j = next((j for j in range(i + 2, min(i + 4, len(folded))) if folded[j] == b), None)
            if j is not None and all(x in FUNCTION_WORDS for x in folded[i + 1:j]):
                out.extend(full[i + 1:j])
                break
    return " ".join(out)


# Situación procesal o desenlace: un título no puede pasar de una a otra
# ("demorado" → "detenido"); cada familia tiene que estar en las notas.
STATUS_FAMILIES = {
    "demorado": ("demor",),
    "detenido": ("deten", "detien", "detuv", "arrest", "apreh", "captur"),
    "imputado": ("imput",),
    "procesado": ("procesad", "procesam", "procesan", "proceso a"),
    "condenado": ("conden",),
    "muerto": ("muer", "murio", "fallec", "asesin", "homicid", "femicid", "mataron", "mato a"),
}


def status_drift(text: str, sources: list[nn.Candidate]) -> list[str]:
    """Familias de situación procesal o desenlace que el texto afirma y las
    notas no mencionan."""
    said, original = nn._fold(text), nn._fold(_source_text(sources))
    return [family for family, stems in STATUS_FAMILIES.items()
            if any(re.search(r"\b" + s, said) for s in stems) and not any(re.search(r"\b" + s, original) for s in stems)]


def derive_hook(blocks: list[dict], assets: dict, limit: int = 3) -> list[dict]:
    """Gancho de la apertura: el título corto (ya validado contra las notas)
    de los hechos más importantes que tienen imagen propia elegible. Abre
    siempre un hecho con video si lo hay (el primer cuadro decide si se
    sigue mirando) y no pasa de ``HOOK_MAX_WORDS`` palabras (apertura ≤ 7 s)."""
    scored = []
    for b in blocks:
        eligible = [a for n in b["ids"] for a in assets.get(n, []) if a.eligible]
        if not eligible:
            continue
        text = b.get("titulo_corto") or (b["titulo"] if len(b["titulo"].split()) <= 6 else "")
        if not text:
            continue
        text = repair_short_title(text.rstrip("."), f"{b['titulo']} {b.get('locucion', '')}")
        has_video = any(a.type == "video" for a in eligible)
        scored.append((-(story_score(b, 0.0) + (0.15 if has_video else 0.0)), b["titulo"], b, text, has_video))
    chosen = []
    words = 0
    for item in sorted(scored, key=lambda x: (x[0], x[1])):
        n = len(item[3].split())
        if len(chosen) >= limit or (chosen and words + n > HOOK_MAX_WORDS):
            continue
        chosen.append(item)
        words += n
    chosen.sort(key=lambda x: not x[4])  # estable: video primero, después por puntaje
    return [{"ids": [b["ids"][0]], "texto": text + ".", "video": has_video} for _s, _t, b, text, has_video in chosen]

    @property
    def teasers(self) -> list[str]:
        return [f["texto"] for f in self.hook_frases]


def _payload(candidates: list[nn.Candidate]) -> str:
    return json.dumps(
        [{"id": c.id, "seccion": c.section, "titulo": c.title, "lugares": c.localities, "sensible": bool(getattr(c, "sensitive", False)),
          "texto": c.body[:1400]} for c in candidates],
        ensure_ascii=False,
    )


def _clean_text(value) -> str:
    return " ".join(str(value or "").split())


def _source_text(sources: list[nn.Candidate]) -> str:
    return "\n".join(f"{c.title}\n{c.body}\n{' '.join(c.localities)}" for c in sources)


def _relevance(raw) -> dict:
    out = {}
    for key in ("interes", "novedad", "impacto_local", "utilidad", "seguimiento"):
        try:
            out[key] = max(1, min(5, int((raw or {}).get(key, 3))))
        except (TypeError, ValueError):
            out[key] = 3
    return out


def _numbers(text: str) -> set[str]:
    from pipeline.node_webapp.editorial import _extract_numbers

    return set(_extract_numbers(text, include_uno=False))


_GENERIC = {"hombre", "mujer", "personas", "tras", "sobre", "durante", "provincia", "rioja", "riojano", "riojana", "para", "desde",
            "barrio", "ciudad", "capital", "policia", "policial", "justicia", "causa", "anoche", "ayer", "denuncian", "detienen", "como",
            "este", "esta", "cerca", "entre", "luego", "hasta", "donde", "zona", "centro", "calle"}


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-zñ]{4,}", nn._fold(text)) if w not in _GENERIC}


_COURT = r"(tribunal(es)?|camara|juzgado|fiscalia|circunscripcion|juez|jueza|sede|multifuero\w*)"


def _court_seat_only(place: str, sources: list[nn.Candidate]) -> bool:
    """El lugar sólo aparece como sede judicial ("tribunales de Chamical"):
    no es donde ocurrió el hecho."""
    folded = nn._fold(place)
    text = nn._fold(_source_text(sources))
    hits = [m.start() for m in re.finditer(re.escape(folded), text)]
    return bool(hits) and all(re.search(_COURT + r"[^.]{0,45}$", text[max(0, h - 60): h]) for h in hits)


def same_event_ok(notes: list[nn.Candidate]) -> bool:
    """Notas agrupadas como un mismo hecho: comparten una localidad del
    archivo o al menos dos palabras significativas del título."""
    if len(notes) < 2:
        return True
    base = notes[0]
    for other in notes[1:]:
        shared_place = {nn._fold(x) for x in base.localities} & {nn._fold(x) for x in other.localities}
        shared_words = _stems(base.title) & _stems(other.title)
        if not shared_place and len(shared_words) < 2:
            return False
    return True


def validate_script_v3(raw: dict, candidates: list[nn.Candidate], *, words: tuple[int, int, int] | None = None,
                       block_words: int = 45) -> tuple[ScriptV3 | None, list[str]]:
    """Mismas barreras factuales que V2, aplicadas por tramo contra SUS notas
    (no contra todo el bloque): un tramo no puede tomar datos de otro hecho.
    El gancho se valida frase por frase contra las notas de su hecho.

    ``words`` = (mínimo, ideal_máximo, tope) de palabras de toda la edición
    (V4: 215/280/290 por entorno); ``block_words``: tope por bloque."""
    by_id = {c.id: c for c in candidates}
    warnings: list[str] = []
    diagnostics: list[str] = []
    blocks: list[dict] = []
    used: set[str] = set()
    for i, b in enumerate(raw.get("bloques") or []):
        if not isinstance(b, dict):
            continue
        label = f"bloque {i + 1}"
        ids = [x for x in (b.get("ids") or []) if x in by_id and x not in used]
        titulo = _clean_text(b.get("titulo")).rstrip(".")
        corto = _clean_text(b.get("titulo_corto")).rstrip(".")
        corto = repair_short_title(corto, f"{titulo} {_clean_text(b.get('locucion'))}") if corto else corto
        clave = _clean_text(b.get("palabra_clave")).strip(".,;:")
        seccion = nn._fold(_clean_text(b.get("seccion")))
        tipo = _clean_text(b.get("tipo")).lower() or "hecho"
        if not ids or not titulo:
            warnings.append(f"{label}: incompleto o con notas repetidas")
            continue
        if seccion not in nn.CATEGORIES:
            seccion = by_id[ids[0]].section if by_id[ids[0]].section in nn.CATEGORIES else "policiales"
        if tipo not in TIPOS:
            tipo = "hecho"
        block_warnings: list[str] = []
        tramos = []
        for k, t in enumerate(b.get("tramos") or []):
            if not isinstance(t, dict):
                continue
            texto = _clean_text(t.get("texto"))
            tids = [x for x in (t.get("ids") or []) if x in ids] or list(ids)
            if not texto:
                continue
            sources = [by_id[x] for x in tids]
            tlabel = f"{label} tramo {k + 1}"
            raw_place = _clean_text(t.get("lugar"))
            if raw_place and _court_seat_only(raw_place, sources):
                diagnostics.append(f"{tlabel}: '{raw_place}' es la sede del tribunal, no el lugar del hecho; se omite")
                t = {**t, "lugar": ""}
            if not same_event_ok(sources):
                block_warnings.append(f"{tlabel}: las notas {tids} no parecen el mismo hecho ({' / '.join(c.title for c in sources)}); separalas en bloques distintos")
            block_warnings += nn.factual_warnings(texto, sources, tlabel)
            lugar = nn.place_label(_clean_text(t.get("lugar")), sources)
            original = nn._fold(_source_text(sources))
            momento = _clean_text(t.get("momento"))[:24]
            if momento and nn._fold(momento) not in original:
                diagnostics.append(f"{tlabel}: momento '{momento}' no figura tal cual en la nota; se omite")
                momento = ""
            dato = _clean_text(t.get("dato"))[:28]
            if dato:
                dnums = _numbers(dato)
                if not dnums or not dnums <= _numbers(_source_text(sources)) or not dnums <= _numbers(texto):
                    diagnostics.append(f"{tlabel}: dato '{dato}' sin respaldo exacto en la nota y en la locución; se omite")
                    dato = ""
                elif nn.factual_warnings(dato, sources, tlabel):
                    diagnostics.append(f"{tlabel}: dato '{dato}' con nombres sin respaldo; se omite")
                    dato = ""
            tramos.append({"ids": tids, "lugar": lugar, "texto": texto, "momento": momento, "dato": dato})
        if not tramos:
            warnings.append(f"{label}: sin tramos válidos")
            continue
        all_sources = [by_id[x] for x in ids]
        block_warnings += nn.factual_warnings(titulo, all_sources, f"{label} título")
        block_warnings += [f"{label} título: dice '{f}' y las notas no" for f in status_drift(titulo, all_sources)]
        if corto:
            corto_w = nn.factual_warnings(corto, all_sources, f"{label} título corto")
            corto_w += [f"dice '{f}' y las notas no" for f in status_drift(corto, all_sources)]
            if corto_w or len(corto) > 34:
                diagnostics.append(f"{label}: título corto descartado ({'; '.join(corto_w) or 'largo'})")
                corto = ""
        if clave and nn._fold(clave) not in nn._fold(titulo):
            diagnostics.append(f"{label}: palabra clave '{clave}' no está en el título; se omite")
            clave = ""
        block_total = sum(len(t["texto"].split()) for t in tramos)
        limit = block_words + 15 if tipo == "hechos_relacionados" else block_words
        if block_total > limit:
            block_warnings.append(f"{label}: la locución tiene {block_total} palabras (máximo {limit})")
        if len(titulo) > 70:
            block_warnings.append(f"{label}: el título supera 70 caracteres")
        # El tipo pedido se verifica contra la estructura real.
        events = [frozenset(t["ids"]) for t in tramos]
        if tipo == "hechos_relacionados" and (len(set(events)) < 2 or any(a & b for a in set(events) for b in set(events) if a != b)):
            diagnostics.append(f"{label}: 'hechos_relacionados' sin hechos distintos por tramo; se trata como hecho")
            tipo = "hecho"
        if tipo == "cronologia" and sum(1 for t in tramos if t["momento"]) < 2:
            diagnostics.append(f"{label}: cronología sin dos momentos comprobados; se trata como hecho")
            tipo = "hecho"
        servicio = {}
        if tipo == "servicio":
            raw_service = b.get("servicio") or {}
            servicio = {k: _clean_text(raw_service.get(k))[:60] for k in ("accion", "zona", "vigencia")}
            original = nn._fold(_source_text(all_sources))
            if not servicio["zona"] or not servicio["vigencia"] or nn._fold(servicio["zona"]) not in original or nn._fold(servicio["vigencia"]) not in original:
                diagnostics.append(f"{label}: servicio sin zona y vigencia textuales; se trata como hecho")
                tipo, servicio = "hecho", {}
            elif service_expired(servicio["vigencia"]):
                diagnostics.append(f"{label}: servicio vencido ({servicio['vigencia']}); no se presenta como aviso vigente")
                tipo, servicio = "hecho", {}
        if tipo == "dato" and not any(t["dato"] for t in tramos):
            tipo = "hecho"
        lugares = {t["lugar"] for t in tramos if t["lugar"]}
        used.update(ids)
        blocks.append({
            "ids": ids, "seccion": seccion, "tipo": tipo, "titulo": titulo, "titulo_corto": corto, "palabra_clave": clave,
            "lugar": next(iter(lugares)) if len(lugares) == 1 and tipo != "hechos_relacionados" else "",
            "tramos": tramos, "servicio": servicio, "relevancia": _relevance(b.get("relevancia")),
            "locucion": " ".join(t["texto"] for t in tramos),
            "sensible": any(getattr(by_id[x], "sensitive", False) for x in ids),
            "_warnings": block_warnings,
        })
        warnings += block_warnings
    hook_frases = []
    block_of = {x: k for k, b in enumerate(blocks) for x in b["ids"]}
    for k, f in enumerate(((raw.get("gancho") or {}).get("frases") or [])[:3]):
        if not isinstance(f, dict):
            continue
        texto = _clean_text(f.get("texto"))
        ids = [x for x in (f.get("ids") or []) if x in block_of]
        if not texto or not ids or len(texto.split()) > 11:
            diagnostics.append(f"gancho frase {k + 1}: sin hecho del guion o demasiado larga; se omite")
            continue
        hook_warnings = nn.factual_warnings(texto, [by_id[x] for x in ids], f"gancho frase {k + 1}")
        hook_warnings += [f"gancho frase {k + 1}: dice '{f}' y las notas no" for f in status_drift(texto, [by_id[x] for x in ids])]
        if hook_warnings:
            warnings += hook_warnings
            continue
        if not re.search(r"[.!?]$", texto):
            texto += "."
        if any(block_of[ids[0]] == block_of[h["ids"][0]] for h in hook_frases):
            continue
        hook_frases.append({"ids": ids, "texto": texto})
    minimum = nn._env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS_V3", 3)
    if len(blocks) < minimum:
        warnings.append(f"hay {len(blocks)} bloques válidos; se necesitan al menos {minimum}")
    if not blocks:
        return None, warnings
    total = sum(len(b["locucion"].split()) for b in blocks)
    unused = [c for c in candidates if c.id not in used]
    low, ideal, cap = words or (nn._env_int("NIGHTLY_NEWSCAST_MIN_WORDS", 215), 280, nn._env_int("NIGHTLY_NEWSCAST_MAX_WORDS", 290))
    target = f"{low + 15}–{ideal}"
    if total > cap:
        warnings.append(f"duración: el guion tiene {total} palabras; recortá a {target} acortando cada bloque sin perder hechos importantes")
    elif total < low and unused and len(blocks) < 12:
        titles = "; ".join(f"{c.id}: {c.title}" for c in unused[:8])
        warnings.append(f"cobertura: el guion tiene {total} palabras y {len(blocks)} bloques; sumá los hechos locales que quedaron afuera ({titles}) hasta {target} palabras")
    return ScriptV3(blocks=blocks[: nn._env_int("NIGHTLY_NEWSCAST_MAX_BLOCKS_V3", 12)], diagnostics=diagnostics, hook_frases=hook_frases), warnings


def service_expired(vigencia: str, today: date | None = None) -> bool:
    """Sólo fechas explícitas ("31 de octubre", "30/10"): si ya pasaron, el
    aviso está vencido. Sin fecha explícita no se presume vigencia ni
    vencimiento: lo resuelve el texto del guion."""
    today = today or nn.today()
    text = nn._fold(vigencia)
    found = []
    for day_s, month_name in re.findall(r"\b(\d{1,2}) de (" + "|".join(nn._fold(m) for m in nn.MESES) + r")\b", text):
        found.append((int(day_s), [nn._fold(m) for m in nn.MESES].index(month_name) + 1))
    for day_s, month_s in re.findall(r"\b(\d{1,2})/(\d{1,2})\b", text):
        found.append((int(day_s), int(month_s)))
    dates = []
    for d, m in found:
        try:
            dates.append(date(today.year, m, d))
        except ValueError:
            continue
    return bool(dates) and max(dates) < today


def write_script_v3(candidates: list[nn.Candidate], *, completion=None, attempts: int = 4, prompt: str = SCRIPT_PROMPT_V3,
                    words: tuple[int, int, int] | None = None, block_words: int = 45) -> tuple[ScriptV3 | None, list[str]]:
    """Pide el guion por tramos y lo revisa; mismo esquema de reintentos con
    devolución y la misma regla final que V2 (salen los bloques con
    observaciones, nunca un dato sin verificar). V5 pasa su propio prompt y
    sus límites de palabras."""
    from utils.ai_client import chat_completion

    completion = completion or chat_completion
    model = os.getenv("NIGHTLY_NEWSCAST_SCRIPT_MODEL") or os.getenv("GEMINI_MODEL") or None
    feedback = ""
    warnings: list[str] = []
    last: ScriptV3 | None = None
    last_warnings: list[str] = []
    for attempt in range(1, attempts + 1):
        user = _payload(candidates)
        if feedback:
            user += "\n\nCorregí estos problemas del intento anterior (sin agregar datos nuevos):\n" + feedback
        try:
            content = completion(
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                model=model,
                temperature=0.4 if attempt == 1 else 0.55,
                max_tokens=6000,
                timeout=float(os.getenv("GEMINI_TIMEOUT", "90")),
                json_mode=True,
                stage="nightly_newscast",
            )
            raw = json.loads(content or "{}")
        except Exception as exc:  # noqa: BLE001 — red, cuota o JSON inválido: se reintenta
            logger.warning("Guion V3, intento %s/%s falló: %s", attempt, attempts, type(exc).__name__)
            warnings = [f"intento {attempt}: {type(exc).__name__}"]
            time.sleep(min(30, 4 * attempt))
            continue
        script, warnings = validate_script_v3(raw if isinstance(raw, dict) else {}, candidates, words=words, block_words=block_words)
        if script and not warnings:
            return _strip(script), []
        logger.info("Guion V3, intento %s/%s con observaciones: %s", attempt, attempts, warnings[:6])
        feedback = "\n".join(f"- {w}" for w in warnings[:12])
        # Se conserva el intento con más palabras en bloques limpios (no el último).
        if script is not None and _clean_words(script) >= _clean_words(last):
            last, last_warnings = script, warnings
    warnings = last_warnings if last is not None else warnings
    if last is not None and not any(w.startswith("hay ") for w in warnings):
        # La cobertura es un pedido, no una barrera factual: no descarta bloques.
        clean = [b for b in last.blocks if not b["_warnings"]]
        if len(clean) >= nn._env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS_V3", 3):
            logger.info("Guion V3: salen %d bloques con observaciones", len(last.blocks) - len(clean))
            kept = {x for b in clean for x in b["ids"]}
            last.blocks = clean
            last.hook_frases = [f for f in last.hook_frases if set(f["ids"]) <= kept]
            return _strip(last), []
    return None, warnings


def _clean_words(script: ScriptV3 | None) -> int:
    if script is None:
        return -1
    return sum(len(b["locucion"].split()) for b in script.blocks if not b["_warnings"])


def _strip(script: ScriptV3) -> ScriptV3:
    script.blocks = [{k: v for k, v in b.items() if k != "_warnings"} for b in script.blocks]
    return script


# ── Selección: policiales de las últimas 24 h ────────────────────────────
def collect_candidates_v3(*, now: float | None = None, hours: int | None = None, refresh=None) -> tuple[list[nn.Candidate], dict]:
    """Candidatas desde la biblioteca de notas propias (se actualiza antes):
    todas las policiales/judiciales/sucesos locales de la ventana, sin cuota
    por sección. Devuelve también el reporte de consideradas y excluidas."""
    from utils import newscast_library as lib

    now = now or time.time()
    hours = hours or nn._env_int("NIGHTLY_NEWSCAST_WINDOW_HOURS_V3", 24)
    report = (refresh or lib.refresh)(now=now)
    limit = nn._env_int("NIGHTLY_NEWSCAST_MAX_CANDIDATES", 30)
    out: list[nn.Candidate] = []
    stale: list[dict] = []
    for entry in lib.entries("policiales", now=now, hours=hours)[:limit]:
        old = stale_weekday(f"{entry['title']}. {entry['body']}", now)
        if old:
            # Publicada dentro de la ventana pero el hecho es de otro día.
            stale.append({"titulo": entry["title"], "motivo": f"el texto dice '{old}'"})
            continue
        out.append(nn.Candidate(
            id=f"n{len(out) + 1}", title=entry["title"], section=entry.get("section") or "policiales", source=entry.get("source", ""),
            web_url=entry["web_url"], published_at=float(entry.get("published_at") or 0), body=entry["body"],
            photo_url=(entry.get("photo") or {}).get("url", ""), video_url=entry.get("video_url", ""),
            localities=list(entry.get("localities") or []), sensitive=nn.is_sensitive(f"{entry['title']} {entry['body'][:600]}"),
            photo_path=(entry.get("photo") or {}).get("path", ""), library_key=entry.get("key", ""),
        ))
    if stale:
        logger.info("Noticiero: %d notas fuera por hecho de otro día: %s", len(stale), [s["titulo"][:60] for s in stale])
    report = {**(report or {}), "window_hours": hours, "candidates": len(out), "stale": stale}
    return out, report


_WEEKDAYS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_WEEKDAY_RE = re.compile(r"\b(este|el pasado|pasado|(?:madrugada|manana|tarde|noche) del)\s+(" + "|".join(_WEEKDAYS) + r")\b")


def stale_weekday(text: str, now: float) -> str:
    """Devuelve la mención ("este miércoles") si el comienzo de la nota ubica
    el hecho dos o más días antes de la edición; "" si es de hoy o de ayer o
    no lo dice. Una nota vieja republicada entra por la fecha de publicación
    y el noticiero la contaría como de las últimas 24 h."""
    m = _WEEKDAY_RE.search(nn._fold(text[:500]))
    if not m:
        return ""
    today = datetime.fromtimestamp(now).weekday()
    return m.group(0) if (today - _WEEKDAYS.index(m.group(2))) % 7 >= 2 else ""


# ── Cartera editorial ────────────────────────────────────────────────────
def story_score(block: dict, material: float) -> float:
    rel = block.get("relevancia") or {}
    weights = {**PORTFOLIO_WEIGHTS}
    score = sum(weights[k] * (float(rel.get(k, 3)) - 1) / 4 for k in ("interes", "novedad", "impacto_local", "utilidad", "seguimiento"))
    return round(score + weights["material"] * max(0.0, min(1.0, material)), 4)


def order_portfolio(blocks: list[dict], material: dict[int, float]) -> tuple[list[int], list[str]]:
    """Orden por importancia (no por casillero de sección). Más de 65 % de
    palabras policiales o tres policiales seguidos abre una revisión: se
    adelanta una alternativa no policial sólo si su puntaje es comparable
    (≤ 0,08 menos). Nunca veta ni agrega relleno."""
    scored = sorted(range(len(blocks)), key=lambda i: (-story_score(blocks[i], material.get(i, 0.0)), i))
    notes = []
    words = {i: len(blocks[i]["locucion"].split()) for i in scored}
    total = sum(words.values()) or 1
    policial = sum(words[i] for i in scored if blocks[i]["seccion"] == "policiales")
    share = policial / total
    notes.append(f"policiales: {share:.0%} de las palabras ({sum(1 for i in scored if blocks[i]['seccion'] == 'policiales')}/{len(scored)} historias)")
    if share > _env_float("NIGHTLY_NEWSCAST_POLICIAL_REVIEW_SHARE", 0.65):
        notes.append("revisión: más de 65 % del tiempo es policial; se mantienen por puntaje (no hay cuota)")
    order = list(scored)
    for pos in range(2, len(order)):
        trio = [blocks[order[k]]["seccion"] == "policiales" for k in (pos - 2, pos - 1, pos)]
        if not all(trio):
            continue
        current = story_score(blocks[order[pos]], material.get(order[pos], 0.0))
        for later in range(pos + 1, len(order)):
            alt = order[later]
            if blocks[alt]["seccion"] != "policiales" and story_score(blocks[alt], material.get(alt, 0.0)) >= current - 0.08:
                order.insert(pos, order.pop(later))
                notes.append(f"revisión: tres policiales seguidos; se adelanta '{blocks[alt]['titulo']}' (puntaje comparable)")
                break
        else:
            notes.append("revisión: tres policiales seguidos sin alternativa comparable; se mantiene el orden")
    return order, notes


def order_police(blocks: list[dict], hook_frases: list[dict], material: dict[int, float]) -> tuple[list[int], list[str]]:
    """Formato policial: abren los hechos del gancho, en su orden (lo que se
    promete al principio se cumple primero); después, por importancia."""
    first: list[int] = []
    for f in hook_frases:
        for i, b in enumerate(blocks):
            if f["ids"][0] in b["ids"] and i not in first:
                first.append(i)
    rest = sorted((i for i in range(len(blocks)) if i not in first), key=lambda i: (-story_score(blocks[i], material.get(i, 0.0)), i))
    order = first + rest
    return order, [f"orden: {len(first)} hechos del gancho primero, el resto por importancia"]


# ── Recursos ─────────────────────────────────────────────────────────────
MEDIA_CHECK_PROMPT = """Sos editor gráfico de un medio de La Rioja. Te paso {what} que acompaña esta nota:
TÍTULO: {title}
EXTRACTO: {excerpt}

Respondé SOLO este JSON (un único objeto para todo el material, no uno por cuadro):
{{"corresponde": "si", "tipo": "registro_del_hecho", "texto_incrustado": "", "zona_texto": "ninguna",
  "persona_primer_plano": false, "menor_identificable": false, "foco_x": 0.5, "foco_y": 0.5,
  "sujetos_en_bordes": false, "nitidez": 4, "cuadros_utiles": [], "describe": ""}}

- corresponde: "si" si muestra el hecho, el lugar o los protagonistas de ESTA nota, o si es una placa/afiche oficial sobre el MISMO tema; "no" si muestra otro hecho u otro lugar, o si un texto incrustado (zócalo, placa) habla de otra cosa; "dudoso" si es genérica y no se puede saber.
- tipo: "registro_del_hecho", "lugar_o_protagonistas", "ilustrativa_generica", "placa_o_flyer", "estudio_o_entrevista" (gente hablando en un estudio o set de TV/radio), "captura_de_redes" o "retrato".
- texto_incrustado: el texto principal legible dentro de la imagen (zócalos, carteles), tal cual, o "".
- zona_texto: dónde está ese texto: "ninguna", "arriba", "abajo", "centro" o "toda".
- persona_primer_plano: una cara ocupa una parte importante (fichaje, retrato, primer plano).
- menor_identificable: se ve la cara de un niño o adolescente.
- foco_x, foco_y: centro de lo más importante de la imagen (0 a 1, desde arriba a la izquierda).
- sujetos_en_bordes: hay sujetos importantes cerca de los dos bordes laterales (un recorte vertical los cortaría).
- nitidez: 1 (ilegible) a 5 (nítida).
- cuadros_utiles: {frames_rule}
- describe: qué se ve, en 12 palabras como máximo, sin suponer nada que no se vea."""


@dataclass
class Asset:
    note_id: str
    type: str                 # image | video
    file: str                 # ruta local
    url: str
    width: int
    height: int
    duration_ms: int = 0
    sha: str = ""
    check: dict = field(default_factory=dict)
    eligible: bool = True
    role: str = "actual"      # actual | context
    label: str = ""           # rótulo exigido ("Imagen ilustrativa")
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0
    layout: str = "window"    # full | window (escenario grande con panel)
    usable_ms: tuple[int, int] = (0, 0)

    @property
    def id(self) -> str:
        return self.sha[:12]

    def public(self) -> dict:
        return {
            "id": self.id, "note": self.note_id, "type": self.type, "url": self.url, "width": self.width, "height": self.height,
            "durationMs": self.duration_ms, "eligible": self.eligible, "role": self.role, "label": self.label,
            "reasons": self.reasons, "score": self.score, "layout": self.layout, "check": self.check,
            "usableMs": list(self.usable_ms),
        }


def file_sha(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_frames(path: str, duration_ms: int, dest_dir: str, count: int = 5) -> list[tuple[str, int]]:
    """Cuadros de muestra (proxy chico) repartidos por el video."""
    out = []
    for k in range(count):
        at = int(duration_ms * (0.06 + 0.88 * k / max(1, count - 1)))
        dest = os.path.join(dest_dir, f"{os.path.basename(path)}_{k}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at / 1000:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=640:-2", dest],
                       capture_output=True, timeout=60)
        if os.path.isfile(dest):
            out.append((dest, at))
    return out


def usable_range(check: dict, duration_ms: int, count: int = 5) -> tuple[int, int]:
    """Tramo del video que el control visual verificó: desde el primer
    cuadro que muestra el hecho (no antes) hasta medio paso después del
    último. Los tiempos de muestra son los de ``video_frames``."""
    useful = [int(k) for k in (check or {}).get("cuadros_utiles") or [] if str(k).isdigit() and int(k) < count]
    if not useful:
        return (0, 0)
    times = [int(duration_ms * (0.06 + 0.88 * k / max(1, count - 1))) for k in range(count)]
    step = duration_ms * 0.88 / max(1, count - 1)
    return (times[min(useful)], min(duration_ms, int(times[max(useful)] + step / 2)))


def check_media(images: list[str], *, title: str, excerpt: str, video: bool, cache_dir: str | None = None) -> dict:
    """Control visual (Gemini, una llamada por recurso, como el de V2) con el
    título de la nota: pertinencia, tipo, texto incrustado, caras, foco y
    nitidez. Cacheado por hash de imágenes + nota + versión del prompt."""
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "PENDIENTE":
        return {}
    digest = hashlib.sha256()
    for path in images:
        with open(path, "rb") as fh:
            digest.update(hashlib.sha256(fh.read()).digest())
    digest.update(f"{MEDIA_CHECK_VERSION}|{title}|{excerpt[:400]}".encode("utf-8"))
    cached = os.path.join(cache_dir, f"check_{digest.hexdigest()[:20]}.json") if cache_dir else ""
    if cached and os.path.isfile(cached):
        with open(cached, encoding="utf-8") as fh:
            return {**json.load(fh), "_cached": True}
    prompt = MEDIA_CHECK_PROMPT.format(
        what=f"{len(images)} cuadros (en orden, índices 0 a {len(images) - 1}) de un video" if video else "una foto",
        title=title, excerpt=excerpt[:400],
        frames_rule="índices de los cuadros que muestran el hecho de esta nota" if video else "[]",
    )
    try:
        parts = []
        for path in images:
            with open(path, "rb") as fh:
                parts.append(types.Part.from_bytes(data=fh.read(), mime_type="image/jpeg"))
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=os.getenv("NIGHTLY_NEWSCAST_VISION_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
            contents=[*parts, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        out = json.loads(response.text or "{}")
    except Exception as exc:  # noqa: BLE001 — sin control visual: las puertas lo tratan como no verificado
        logger.warning("Control visual falló: %s", type(exc).__name__)
        return {}
    if isinstance(out, list):
        out = merge_frame_checks(out)
    if not isinstance(out, dict) or not out:
        logger.warning("Control visual: respuesta sin objeto (%s)", type(out).__name__)
        return {}
    if cached:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cached, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
    return out


def merge_frame_checks(items: list) -> dict:
    """Respuesta por cuadro → un control para todo el video: corresponde si
    algún cuadro corresponde; los cuadros útiles son los que corresponden."""
    frames = [x for x in items if isinstance(x, dict)]
    if not frames:
        return {}
    verdicts = [str(x.get("corresponde") or "").lower() for x in frames]
    useful = [k for k, v in enumerate(verdicts) if v == "si"]
    good = [frames[k] for k in useful] or frames
    corresponde = "si" if useful else ("no" if "no" in verdicts else "dudoso")
    tipos = [str(x.get("tipo") or "") for x in good]
    zones = [str(x.get("zona_texto") or "ninguna") for x in frames if str(x.get("zona_texto") or "ninguna") != "ninguna"]
    sharp = sorted(int(x.get("nitidez") or 3) for x in good if str(x.get("nitidez") or "3").isdigit())
    return {
        "corresponde": corresponde, "tipo": max(set(tipos), key=tipos.count) if tipos else "",
        "texto_incrustado": next((str(x.get("texto_incrustado")) for x in frames if x.get("texto_incrustado")), ""),
        "zona_texto": zones[0] if zones else "ninguna",
        "persona_primer_plano": any(bool(x.get("persona_primer_plano")) for x in good),
        "menor_identificable": any(bool(x.get("menor_identificable")) for x in frames),
        "foco_x": sum(_f(x.get("foco_x"), 0.5) for x in good) / len(good), "foco_y": sum(_f(x.get("foco_y"), 0.5) for x in good) / len(good),
        "sujetos_en_bordes": any(bool(x.get("sujetos_en_bordes")) for x in good),
        "nitidez": sharp[len(sharp) // 2] if sharp else 3, "cuadros_utiles": useful,
        "describe": str(good[0].get("describe") or ""), "_merged": len(frames),
    }


def _f(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def assess(asset: Asset, *, policial: bool, sensitive: bool, judicial: bool = False) -> Asset:
    """Puertas de elegibilidad (no compensables) y puntaje entre elegibles.

    Rostros (decisión del 2026-10-31): no se excluyen primeros planos de
    adultos por ser policiales; sí cualquier menor identificable y cualquier
    rostro en temas sensibles (posibles víctimas)."""
    c = asset.check or {}
    reasons = asset.reasons
    corresponde = str(c.get("corresponde") or "").lower()
    tipo = str(c.get("tipo") or "").lower()
    if not c:
        if asset.type == "video":
            reasons.append("video sin control visual: no se puede verificar que muestre este hecho")
            asset.eligible = False
        else:
            reasons.append("foto de la nota sin control visual: se usa como contexto")
            corresponde, tipo = "dudoso", "ilustrativa_generica"
    if corresponde == "no":
        asset.eligible = False
        reasons.append(f"no corresponde al hecho ({c.get('texto_incrustado') or c.get('describe') or 'otro hecho'})")
    if c.get("menor_identificable"):
        asset.eligible = False
        reasons.append("menor identificable")
    if sensitive and (c.get("persona_primer_plano") or tipo == "retrato"):
        asset.eligible = False
        reasons.append("rostro en tema sensible (posible víctima)")
    if judicial and (c.get("persona_primer_plano") or tipo == "retrato"):
        # En una causa judicial no se sabe si el retrato es del acusado, de la
        # víctima o del juez: junto al titular sugeriría culpa a quien no es.
        asset.eligible = False
        reasons.append("retrato en historia judicial (no se sabe si es acusado, víctima o funcionario)")
    if tipo == "estudio_o_entrevista":
        asset.eligible = False
        reasons.append("estudio/entrevista: no muestra el hecho")
    nitidez = int(c.get("nitidez") or 3) if str(c.get("nitidez") or "3").isdigit() else 3
    if nitidez <= 1:
        asset.eligible = False
        reasons.append("ilegible")
    if asset.type == "video":
        frames_ok = [int(x) for x in (c.get("cuadros_utiles") or []) if str(x).isdigit()]
        asset.check["cuadros_utiles"] = frames_ok
        if c and not frames_ok and corresponde != "si":
            asset.eligible = False
            reasons.append("ningún cuadro muestra el hecho")
    if tipo in ("ilustrativa_generica",) or corresponde == "dudoso":
        asset.role, asset.label = "context", "Imagen ilustrativa"
    elif tipo in ("placa_o_flyer", "captura_de_redes"):
        asset.role = "context"
    else:
        asset.role = "actual"
    relevance = {"si": 1.0, "dudoso": 0.5}.get(corresponde, 0.0)
    clarity = max(0.0, min(1.0, (nitidez - 1) / 4))
    utility = {"registro_del_hecho": 1.0, "lugar_o_protagonistas": 0.7, "retrato": 0.6, "ilustrativa_generica": 0.4, "placa_o_flyer": 0.3,
               "captura_de_redes": 0.25}.get(tipo, 0.4)
    if asset.type == "video" and tipo == "registro_del_hecho":
        utility = 1.0
    elif asset.type == "image" and tipo == "registro_del_hecho":
        utility = 0.85
    asset.layout = choose_layout(asset)
    framing = 1.0 if asset.layout == "full" else 0.65
    asset.score = round(ASSET_WEIGHTS["relevance"] * relevance + ASSET_WEIGHTS["clarity"] * clarity + ASSET_WEIGHTS["utility"] * utility
                        + ASSET_WEIGHTS["framing"] * framing + ASSET_WEIGHTS["novelty"] * 1.0, 4)
    return asset


def choose_layout(asset: Asset, *, out_w: int = 1080, out_h: int = 1920) -> str:
    """Pantalla completa si el recorte 9:16 no corta sujetos ni texto y no
    amplía más de 2,4× (2,0× en video); si no, escenario grande (1080 × ~1180)
    con panel informativo debajo. En video se tolera el zócalo abajo: cae en
    la zona de interfaz de Reels, debajo de los subtítulos."""
    c = asset.check or {}
    if not c or not asset.width or not asset.height:
        return "window"
    zone = str(c.get("zona_texto") or "ninguna")
    if zone not in ("", "ninguna") and not (asset.type == "video" and zone == "abajo"):
        return "window"
    if str(c.get("tipo") or "") in ("placa_o_flyer", "captura_de_redes") or c.get("sujetos_en_bordes"):
        return "window"
    aspect = asset.width / asset.height
    crop_h = asset.height if aspect >= out_w / out_h else asset.width * out_h / out_w
    upscale = out_h / crop_h
    limit = _env_float("NIGHTLY_NEWSCAST_MAX_UPSCALE", 2.4) if asset.type == "image" else _env_float("NIGHTLY_NEWSCAST_MAX_UPSCALE_VIDEO", 2.0)
    return "full" if upscale <= limit else "window"


# ── Plan ─────────────────────────────────────────────────────────────────
@dataclass
class StoryInput:
    block: dict
    voice_file: str
    voice_ms: int
    tokens: list            # newscast_align.Token o dicts con text/start_ms/end_ms/method
    assets: list[Asset]
    credit: str
    align_ok: bool
    note_sources: dict = field(default_factory=dict)


def _tok(t) -> dict:
    return t if isinstance(t, dict) else {"text": t.text, "start_ms": t.start_ms, "end_ms": t.end_ms, "method": t.method}


def tramo_spans(block: dict, tokens: list, voice_ms: int) -> list[tuple[int, int]] | None:
    """Inicio/fin (ms, relativos al clip) de cada tramo según el
    alineamiento. La frontera entre tramos es el medio del silencio entre la
    última palabra de uno y la primera del siguiente."""
    return phrase_spans([t["texto"] for t in block["tramos"]], tokens, voice_ms)


def phrase_spans(texts: list[str], tokens: list, voice_ms: int) -> list[tuple[int, int]] | None:
    toks = [_tok(t) for t in tokens]
    counts = [len(t.split()) for t in texts]
    if not toks or sum(counts) != len(toks):
        return None
    spans = []
    cursor = 0
    for n in counts:
        first, last = toks[cursor], toks[cursor + n - 1]
        spans.append([first["start_ms"], last["end_ms"]])
        cursor += n
    bounds = [0]
    for a, b in zip(spans, spans[1:]):
        bounds.append(int((a[1] + b[0]) / 2))
    bounds.append(voice_ms)
    return [(bounds[i], bounds[i + 1]) for i in range(len(spans))]


def sentence_breaks(tokens: list, lo: int, hi: int) -> list[int]:
    """Pausas reales entre oraciones/cláusulas dentro de [lo, hi] (ms)."""
    toks = [_tok(t) for t in tokens]
    out = []
    for a, b in zip(toks, toks[1:]):
        if lo < a["end_ms"] < hi and re.search(r"[.;:,]$", a["text"]):
            out.append(int((a["end_ms"] + b["start_ms"]) / 2))
    return out


def _pick(assets: list[Asset], note_ids: list[str], ledger: dict, *, exclude: set[str] = frozenset()) -> list[Asset]:
    """Elegibles del hecho, por puntaje con novedad (lo no usado primero)."""
    pool = [a for a in assets if a.eligible and a.note_id in note_ids and a.id not in exclude]
    return sorted(pool, key=lambda a: (-(a.score - (0.05 if a.id in ledger else 0.0) + (0.06 if a.type == "video" else 0.0)), a.id))


def _movement(index: int, ms: int, asset: Asset) -> dict:
    """Cámara: 6–12 % de escala en la toma con desplazamiento hacia el foco
    (fotos); el video real conserva su propio movimiento (sin zoom)."""
    if asset.type == "video":
        return {"scaleFrom": 1.0, "scaleTo": 1.0, "dx": 0.0, "dy": 0.0}
    seconds = ms / 1000
    total = max(0.06, min(0.12, 0.05 + 0.012 * seconds))
    focus_x = _f((asset.check or {}).get("foco_x"), 0.5)
    direction = 1 if focus_x >= 0.5 else -1
    zoom_in = index % 2 == 0
    return {
        "scaleFrom": 1.0 if zoom_in else round(1 + total, 4),
        "scaleTo": round(1 + total, 4) if zoom_in else 1.0,
        "dx": round(direction * min(0.03, 0.005 * seconds), 4),
        "dy": round(-0.006 * min(seconds, 6) / 6, 4),
    }


def _shot(asset: Asset | None, start: int, end: int, *, event: int, reason: str, index: int, source_in_ms: int = 0, framing: str = "general") -> dict:
    if asset is None:
        return {"startMs": start, "endMs": end, "event": event, "media": None, "layout": "type", "reason": reason, "framing": framing,
                "move": {"scaleFrom": 1.0, "scaleTo": 1.0, "dx": 0.0, "dy": 0.0}}
    check = asset.check or {}
    return {
        "startMs": start, "endMs": end, "event": event, "reason": reason, "framing": framing,
        "layout": asset.layout,
        "media": {
            "id": asset.id, "note": asset.note_id, "type": asset.type, "file": asset.file, "width": asset.width, "height": asset.height,
            "role": asset.role, "label": asset.label, "sourceInMs": source_in_ms, "durationMs": asset.duration_ms,
            "focusX": _f(check.get("foco_x"), 0.5), "focusY": _f(check.get("foco_y"), 0.45),
            "textZone": str(check.get("zona_texto") or "ninguna"),
            "edgeSubjects": bool(check.get("sujetos_en_bordes")),
            "people": bool(check.get("persona_primer_plano")) or str(check.get("tipo") or "") == "retrato",
        },
        "move": _movement(index, end - start, asset),
    }


def _split(start: int, end: int, breaks: list[int], pieces: int) -> list[int]:
    """Cortes en pausas reales cercanas a partes iguales; si no hay pausas
    adecuadas, no se corta (nunca se divide por cantidad de fotos)."""
    if pieces <= 1:
        return [start, end]
    cuts = [start]
    for k in range(1, pieces):
        ideal = start + (end - start) * k / pieces
        options = [b for b in breaks if cuts[-1] + SHOT_MIN_MS <= b <= end - SHOT_MIN_MS]
        if not options:
            break
        best = min(options, key=lambda b: abs(b - ideal))
        if abs(best - ideal) > (end - start) / pieces * 0.6:
            continue
        cuts.append(best)
    cuts.append(end)
    return cuts


def plan_story_shots(story: StoryInput, story_ms: int, voice_at: int, ledger: dict) -> tuple[str, list[dict], list[dict], list[str]]:
    """Familia y tomas de una historia (ms relativos al inicio de la historia)."""
    block = story.block
    notes: list[str] = []
    note_ids = block["ids"]
    eligible = [a for a in story.assets if a.eligible]
    best_video = next(iter(_pick([a for a in eligible if a.type == "video"], note_ids, ledger)), None)
    best_photo = next(iter(_pick([a for a in eligible if a.type == "image"], note_ids, ledger)), None)
    spans = tramo_spans(block, story.tokens, story.voice_ms) if story.align_ok else None
    events = []
    if spans:
        for k, (tramo, (a, b)) in enumerate(zip(block["tramos"], spans)):
            lo = 0 if k == 0 else voice_at + a
            hi = story_ms if k == len(spans) - 1 else voice_at + b
            events.append({"index": k, "ids": tramo["ids"], "lugar": tramo["lugar"], "startMs": lo, "endMs": hi,
                           "momento": tramo["momento"], "dato": tramo["dato"]})
    else:
        events.append({"index": 0, "ids": note_ids, "lugar": block.get("lugar", ""), "startMs": 0, "endMs": story_ms, "momento": "", "dato": ""})
    distinct_events = len({frozenset(e["ids"]) for e in events})
    tipo = block["tipo"]
    has_media = bool(best_video or best_photo)
    # Elección de familia: material + función narrativa, no sección.
    if tipo == "servicio" and block.get("servicio"):
        family = "service"
    elif tipo == "cronologia" and spans and sum(1 for e in events if e["momento"]) >= 2:
        family = "timeline"
    elif tipo == "hechos_relacionados" and spans and distinct_events >= 2:
        family = "related"
    elif tipo == "hechos_relacionados" and not spans:
        family = "limited"
        notes.append("hechos relacionados sin alineamiento: sin tomas por hecho para no cruzar imágenes")
    elif tipo == "judicial":
        family = "judicial"
    elif has_media and (tipo == "breve" or story.voice_ms < 6500):
        family = "brief"
    elif best_video and (not best_photo or best_video.score >= best_photo.score - 0.05):
        family = "video"
    elif best_photo and best_photo.role == "actual" and best_photo.score >= 0.55:
        family = "photo"
    elif any(e["dato"] for e in events) or tipo == "dato":
        # Una cifra verificada explica mejor que una foto ilustrativa.
        family = "data"
    elif best_photo:
        family = "photo"
    else:
        family = "limited"
    breaks = sentence_breaks(story.tokens, 0, story.voice_ms) if story.align_ok else []
    breaks = [voice_at + b for b in breaks]
    shots: list[dict] = []
    if family in ("related", "timeline"):
        for e in events:
            need = e["endMs"] - e["startMs"]
            pool = [a for a in _pick(eligible, e["ids"], ledger) if a.type != "video" or _video_in(a, need, ledger) >= 0]
            asset = pool[0] if pool else None
            if asset is None:
                notes.append(f"hecho {e['index'] + 1}: sin material propio; composición tipográfica (nunca foto de otro hecho)")
            shots.append(_shot(asset, e["startMs"], e["endMs"], event=e["index"], reason="material del hecho" if asset else "sin material del hecho", index=len(shots),
                               source_in_ms=_video_in(asset, need, ledger) if asset else 0))
            if asset:
                _book(ledger, asset, shots[-1])
    elif not has_media or family in ("service", "limited") or (family == "data" and not best_photo):
        shots.append(_shot(None, 0, story_ms, event=0, reason=f"familia {family}: composición tipográfica", index=0))
    else:
        # Video o foto: tramos distintos del mismo hecho, cortes en pausas reales.
        pool = _pick(eligible, note_ids, ledger)
        if family == "data":
            pool = pool[:1]
        extra = 1 if pool and (pool[0].type == "video" or _detail_ok(pool[0])) else 0
        pieces = max(1, min(len(pool) + extra + (1 if pool and pool[0].type == "video" else 0), round(story_ms / 3600)))
        cuts = _split(0, story_ms, breaks, pieces)
        used_here: set[str] = set()
        for k in range(len(cuts) - 1):
            lo, hi = cuts[k], cuts[k + 1]
            candidates = [a for a in pool if a.id not in used_here or a.type == "video"]
            asset = candidates[0] if candidates else (pool[0] if pool else None)
            framing = "general"
            source_in = 0
            if asset and asset.type == "video":
                source_in = _video_in(asset, hi - lo, ledger)
                if source_in < 0:
                    # El video no alcanza para otro tramo sin repetir: foto del mismo hecho.
                    photos = [a for a in pool if a.type == "image" and a.id not in used_here]
                    asset = photos[0] if photos else None
                    source_in = 0
                    if asset is None:
                        if shots:
                            shots[-1]["endMs"] = hi
                            notes.append("el video no alcanza y no hay otra foto: se sostiene la toma anterior (sin loop)")
                            continue
            elif asset and asset.id in used_here:
                framing = "detail" if _detail_ok(asset) else "general"
                if framing == "general":
                    shots[-1]["endMs"] = hi
                    continue
            shots.append(_shot(asset, lo, hi, event=0, reason="mejor recurso elegible del hecho" if asset else "sin material", index=len(shots),
                               source_in_ms=max(0, source_in), framing=framing))
            if asset:
                used_here.add(asset.id)
                _book(ledger, asset, shots[-1])
    # La misma foto en tomas seguidas (nodos de una cronología) es una sola
    # toma continua: sin reiniciar el movimiento de cámara en cada nodo.
    merged: list[dict] = []
    for shot in shots:
        prev = merged[-1] if merged else None
        same = prev and shot["media"] and prev["media"] and shot["media"]["id"] == prev["media"]["id"] \
            and shot["media"]["type"] == "image" and shot["framing"] == prev["framing"]
        if same:
            prev["endMs"] = shot["endMs"]
            prev["move"] = _movement(0, prev["endMs"] - prev["startMs"], next(a for a in story.assets if a.id == shot["media"]["id"]))
            continue
        merged.append(shot)
    shots = merged
    if not shots:
        shots.append(_shot(None, 0, story_ms, event=0, reason="sin tomas", index=0))
    shots[0]["startMs"] = 0
    shots[-1]["endMs"] = story_ms
    return family, shots, events, notes


def _detail_ok(asset: Asset) -> bool:
    """Un segundo encuadre (detalle real) sólo con resolución suficiente."""
    return asset.type == "image" and min(asset.width, asset.height) >= 1000 and bool(asset.check)


def _video_in(asset: Asset | None, need_ms: int, ledger: dict) -> int:
    """Primer tramo no usado del video que alcanza para la toma; -1 si no hay
    (no se repite ni se hace loop)."""
    if asset is None or asset.type != "video":
        return 0
    lo, hi = asset.usable_ms if asset.usable_ms != (0, 0) else (0, asset.duration_ms)
    used = sorted(ledger.get(asset.id, []))
    cursor = lo
    for a, b in used:
        if a - cursor >= need_ms:
            return cursor
        cursor = max(cursor, b)
    return cursor if hi - cursor >= need_ms else -1


def _book(ledger: dict, asset: Asset, shot: dict) -> None:
    if asset.type == "video":
        start = shot["media"]["sourceInMs"]
        ledger.setdefault(asset.id, []).append((start, start + shot["endMs"] - shot["startMs"]))
    else:
        ledger.setdefault(asset.id, []).append((0, 0))


def compact_at(block: dict, tokens: list, voice_at: int, align_ok: bool) -> int:
    """Momento (ms de la historia) en que el titular grande se contrae en
    regleta: la primera pausa real entre 1,9 y 3,4 s."""
    if align_ok:
        for b in sentence_breaks(tokens, 0, 10_000):
            at = voice_at + b
            if TITLE_FULL_MIN_MS <= at <= TITLE_FULL_MAX_MS:
                return at
    return 2600


def _credit(names: list[str]) -> str:
    names = sorted({n for n in names if n})
    return ("Fuente: " + " y ".join(names)) if names else ""


def dato_frame(dato: str, tokens: list, offset_ms: int, fps: int) -> int | None:
    """Frame (global) en que la locución dice la cifra del dato: la cifra
    aparece cuando se escucha, con su valor final."""
    first = re.search(r"\d+(?:[.,]\d+)?", dato or "")
    if not first:
        return None
    for t in (_tok(x) for x in tokens):
        if first.group(0) in t["text"]:
            return ms_to_frame(offset_ms + t["start_ms"], fps)
    return None


# ── Datos que aparecen con la voz ────────────────────────────────────────
_NUMBER_WORDS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
                 "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100}
COUNT_NOUNS = ("detenid", "aprehendid", "herid", "lesionad", "personas", "jovenes", "hombres", "mujeres", "vehiculos", "autos", "motos",
               "viviendas", "casas", "animales", "caballos", "hectareas", "allanamientos", "procedimientos", "victimas", "familias",
               "gramos", "kilos", "dosis", "plantas", "dolares", "pesos", "focos", "dotaciones", "bomberos", "efectivos")
KEY_TERMS = {"allanamiento": "ALLANAMIENTO", "allanamientos": "ALLANAMIENTOS", "operativo": "OPERATIVO", "incendio": "INCENDIO",
             "choque": "CHOQUE", "vuelco": "VUELCO", "juicio": "JUICIO", "estafa": "ESTAFA", "estafas": "ESTAFAS", "robo": "ROBO",
             "rescate": "RESCATE", "accidente": "ACCIDENTE", "drogas": "DROGAS", "estupefacientes": "ESTUPEFACIENTES", "denuncia": "DENUNCIA",
             "procesado": "PROCESADO", "procesaron": "PROCESAMIENTO", "imputado": "IMPUTADO", "detenida": "DETENIDA", "detenido": "DETENIDO",
             "detenidos": "DETENIDOS", "investigacion": "INVESTIGACIÓN", "fuego": "FUEGO", "evacuados": "EVACUADOS"}


def _word(text: str) -> str:
    return nn._fold(re.sub(r"[^\wÁÉÍÓÚÑáéíóúñü]", "", text))


def detect_emphasis(block: dict, tokens: list, voice_at: int, story_ms: int, *, allow_tag: bool = True, used_tags: set | None = None) -> list[dict]:
    """Lugar, cantidades, cifra del dato y término clave, con el ms (de la
    historia) en que la voz los dice. Sólo texto del guion validado: nada que
    la locución no diga. Máximo 3 por historia, separados ≥ 1,4 s."""
    toks = [_tok(t) for t in tokens]
    if not toks:
        return []
    words = [_word(t["text"]) for t in toks]
    found: list[tuple[int, int, dict]] = []  # (prioridad, ms, item)
    for tramo in block["tramos"]:
        if tramo.get("dato"):
            first = re.search(r"\d+(?:[.,]\d+)?", tramo["dato"])
            for k, t in enumerate(toks):
                if first and first.group(0) in t["text"]:
                    found.append((0, voice_at + t["start_ms"], {"kind": "data", "text": tramo["dato"]}))
                    break
    for k, w in enumerate(words[:-1]):
        value = _NUMBER_WORDS.get(w) or (int(w) if w.isdigit() and 1 < int(w) < 10000 else None)
        noun = words[k + 1]
        if value and any(noun.startswith(n) for n in COUNT_NOUNS):
            label = re.sub(r"[^\wÁÉÍÓÚÑáéíóúñü]", "", toks[k + 1]["text"]).upper()
            found.append((1, voice_at + toks[k]["start_ms"], {"kind": "count", "value": str(value), "text": label}))
    places = [t.get("lugar") for t in block["tramos"] if t.get("lugar")] or ([block["lugar"]] if block.get("lugar") else [])
    for place in places:
        target = [_word(p) for p in place.split() if _word(p) not in ("barrio", "el", "la", "de", "del", "en")]
        if not target:
            continue
        for k, w in enumerate(words):
            if w == target[0]:
                found.append((2, voice_at + toks[k]["start_ms"], {"kind": "place", "text": place}))
                break
    # Término clave: nunca sobre retratos ni en historias judiciales (una
    # palabra como ROBO junto a una persona sugiere culpa); no se repite.
    for k, w in enumerate(words):
        if allow_tag and w in KEY_TERMS and KEY_TERMS[w] not in (used_tags or set()):
            found.append((3, voice_at + toks[k]["start_ms"], {"kind": "tag", "text": KEY_TERMS[w]}))
            break
    chosen: list[tuple[int, dict]] = []
    for prio, at, item in sorted(found, key=lambda x: (x[0], x[1])):
        if at > story_ms - 1500 or any(abs(at - c[0]) < 1400 for c in chosen) or any(c[1]["kind"] == item["kind"] for c in chosen):
            continue
        chosen.append((at, item))
        if len(chosen) >= 3:
            break
    return [{**item, "atMs": at} for at, item in sorted(chosen, key=lambda x: x[0])]


def _cues(tokens: list, offset_ms: int, story_index: int, f_end: int, fps: int) -> list[dict]:
    from utils.newscast_align import Token, build_cues

    toks = [t if isinstance(t, Token) else Token(t["text"], t["start_ms"], t["end_ms"], t.get("method", "asr")) for t in tokens]
    out = []
    for cue in build_cues(toks, offset_ms=offset_ms):
        a = ms_to_frame(cue["startMs"], fps)
        b = min(ms_to_frame(cue["endMs"], fps), f_end)
        if b > a:
            out.append({"text": cue["text"], "from": a, "to": b, "story": story_index,
                        "words": [{"text": w["text"], "from": ms_to_frame(w["startMs"], fps), "method": w["method"]} for w in cue["words"]]})
    return out


TRANSITIONS = ("slash", "cover", "locality", "iris")


def _transition(index: int, story: dict) -> str:
    """Transición determinista por posición: varía sin azar. "locality"
    sólo si la historia tiene un lugar que mostrar."""
    if index == 0:
        return "slash"
    kind = TRANSITIONS[index % len(TRANSITIONS)]
    if kind == "locality" and not (story.get("lugar") or any(e.get("lugar") for e in story.get("events", []))):
        kind = "slash"
    return kind


@dataclass
class IntroInput:
    voice_file: str
    voice_ms: int
    tokens: list
    frases: list[dict]       # {"ids", "texto"} + "assets" (elegibles del hecho)
    align_ok: bool


def plan_intro(intro: IntroInput, ledger: dict, fps: int) -> tuple[dict, int]:
    """Apertura (4–7 s): cada frase del gancho con la imagen de SU hecho,
    cortada cuando la voz empieza a decirla; cierre con la marca."""
    total_ms = INTRO_LEAD_MS + intro.voice_ms + INTRO_TAIL_MS
    texts = [f["texto"] for f in intro.frases] + ([HOOK_TAIL] if HOOK_TAIL else [])
    spans = phrase_spans(texts, intro.tokens, intro.voice_ms) if intro.align_ok else None
    if not spans:
        # Sin alineamiento: sin frases en pantalla (no se adivina cuándo se
        # dicen); montaje de los hechos del gancho y marca al final.
        share = intro.voice_ms / max(1, len(texts))
        spans = [(int(k * share), int((k + 1) * share)) for k in range(len(texts))]
    if not HOOK_TAIL:
        spans.append((intro.voice_ms + 80, intro.voice_ms + 80))
    beats = []
    for k, frase in enumerate(intro.frases):
        lo = 0 if k == 0 else INTRO_LEAD_MS + spans[k][0]
        hi = INTRO_LEAD_MS + spans[k + 1][0] if k + 1 < len(spans) else total_ms
        pool = _pick(frase.get("assets") or [], frase["ids"], ledger)
        asset = pool[0] if pool else None
        need = hi - lo
        source_in = 0
        if asset and asset.type == "video":
            source_in = _video_in(asset, need, ledger)
            if source_in < 0:
                photos = [a for a in pool if a.type == "image"]
                asset = photos[0] if photos else None
                source_in = 0
        shot = _shot(asset, lo, hi, event=0, reason="gancho: imagen del hecho mencionado", index=k, source_in_ms=source_in)
        if asset:
            _book(ledger, asset, shot)
        beats.append({"from": ms_to_frame(lo, fps), "to": ms_to_frame(hi, fps), "ids": frase["ids"],
                      "text": frase["texto"] if intro.align_ok else "", "shot": shot})
    tail_from = ms_to_frame(INTRO_LEAD_MS + spans[-1][0], fps)
    if beats:
        beats[-1]["to"] = tail_from
    for b in beats:
        media = b["shot"]["media"]
        if media:
            media["sourceInFrames"] = ms_to_frame(media["sourceInMs"], fps)
        b["shot"]["from"] = 0
        b["shot"]["durationInFrames"] = b["to"] - b["from"]
    duration = ms_to_frame(total_ms, fps)
    plan = {
        "from": 0, "durationInFrames": duration, "beats": beats, "tailFrom": tail_from, "tailText": HOOK_TAIL,
        "voice": {"file": intro.voice_file, "from": ms_to_frame(INTRO_LEAD_MS, fps),
                  "durationInFrames": ms_to_frame(INTRO_LEAD_MS + intro.voice_ms, fps) - ms_to_frame(INTRO_LEAD_MS, fps)},
    }
    return plan, total_ms


def outro_lines(text: str, tokens: list, offset_ms: int, fps: int) -> list[dict]:
    """El cierre muestra en grande lo que dice la voz (sin subtítulos): cada
    línea aparece cuando se pronuncia."""
    parts = [p.strip() for p in re.split(r"(?<=[,.])\s+", text) if p.strip()]
    toks = [_tok(t) for t in tokens]
    out = []
    cursor = 0
    for part in parts:
        n = len(part.split())
        at = toks[cursor]["start_ms"] if toks and cursor < len(toks) else 0
        out.append({"text": part.rstrip(",."), "at": ms_to_frame(offset_ms + at, fps) if toks else None})
        cursor += n
    return out


def build_plan(stories: list[StoryInput], *, outro_voice: str, outro_ms: int, date_label: str, fps: int = FPS,
               descriptor: str = DESCRIPTOR_DEFAULT, cta: str = CTA_DEFAULT, music: dict | None = None,
               diagnostics: list[str] | None = None, outro_tokens: list | None = None, test_banner: str = "",
               intro: IntroInput | None = None) -> dict:
    """Plan audiovisual completo. Función pura (mismo input → mismo plan)."""
    ledger: dict = {}
    intro_plan, cursor = (plan_intro(intro, ledger, fps) if intro else (None, 0))
    plan_stories = []
    voices = []
    captions = []
    sfx: list[dict] = []
    used_tags: set[str] = set()
    if intro_plan:
        sfx.append({"file": "newscast/impact.mp3", "from": 0, "volume": 0.55})
        for b in intro_plan["beats"][1:]:
            sfx.append({"file": "newscast/whoosh.mp3", "from": max(0, b["from"] - 5), "volume": 0.4})
        sfx.append({"file": "newscast/impact.mp3", "from": intro_plan["tailFrom"], "volume": 0.7})
    for i, story in enumerate(stories):
        lead = LEAD_FIRST_MS if i == 0 else LEAD_MS
        start = cursor
        voice_at = lead
        story_ms = lead + story.voice_ms + GAP_MS
        family, shots, events, notes = plan_story_shots(story, story_ms, voice_at, ledger)
        block = story.block
        f0 = ms_to_frame(start, fps)
        f1 = ms_to_frame(start + story_ms, fps)
        frame_shots = []
        for s in shots:
            a = ms_to_frame(start + s["startMs"], fps) - f0
            b = ms_to_frame(start + s["endMs"], fps) - f0
            if b <= a:
                continue
            media = s["media"]
            if media:
                media = {**media, "sourceInFrames": ms_to_frame(media["sourceInMs"], fps)}
            frame_shots.append({**s, "media": media, "from": a, "durationInFrames": b - a})
        # Sin huecos: cada toma termina donde empieza la siguiente.
        for x, y in zip(frame_shots, frame_shots[1:]):
            x["durationInFrames"] = y["from"] - x["from"]
        if frame_shots:
            frame_shots[-1]["durationInFrames"] = (f1 - f0) - frame_shots[-1]["from"]
        frame_events = []
        for e in events:
            dato_at = dato_frame(e["dato"], story.tokens, start + voice_at, fps) if story.align_ok and e["dato"] else None
            frame_events.append({**e, "from": ms_to_frame(start + e["startMs"], fps) - f0, "to": ms_to_frame(start + e["endMs"], fps) - f0,
                                 "credit": _credit([story.note_sources.get(x, "") for x in e["ids"]]) or story.credit,
                                 "datoAt": (dato_at - f0) if dato_at is not None else None})
        emphasis = []
        portraits = any(s["media"] and s["media"].get("people") for s in shots)
        if story.align_ok:
            allow_tag = family != "judicial" and not portraits
            for item in detect_emphasis(block, story.tokens, voice_at, story_ms, allow_tag=allow_tag, used_tags=used_tags):
                if item["kind"] == "tag":
                    used_tags.add(item["text"])
                at = ms_to_frame(start + item.pop("atMs"), fps) - f0
                emphasis.append({**item, "at": at})
                sfx.append({"file": "newscast/tick.mp3", "from": f0 + at, "volume": 0.3})
        voices.append({"file": story.voice_file, "from": ms_to_frame(start + voice_at, fps), "durationInFrames": ms_to_frame(start + voice_at + story.voice_ms, fps) - ms_to_frame(start + voice_at, fps)})
        cues = _cues(story.tokens, start + voice_at, i, f1, fps) if story.align_ok and story.tokens else []
        captions += cues
        entry = {
            "index": i, "ids": block["ids"], "seccion": block["seccion"], "tipo": block["tipo"], "family": family,
            "principal": i == 0, "titulo": block["titulo"], "tituloCorto": block.get("titulo_corto") or "", "keyword": block.get("palabra_clave") or "",
            "lugar": block.get("lugar") or "", "credit": story.credit, "sensible": bool(block.get("sensible")),
            "servicio": block.get("servicio") or {}, "tramos": [{"texto": t["texto"], "lugar": t["lugar"], "momento": t["momento"], "dato": t["dato"], "ids": t["ids"]} for t in block["tramos"]],
            "from": f0, "durationInFrames": f1 - f0, "compactAt": ms_to_frame(start + compact_at(block, story.tokens, voice_at, story.align_ok), fps) - f0,
            "shots": frame_shots, "events": frame_events, "emphasis": emphasis, "captionsOk": bool(cues), "notes": notes,
            "rejected": [a.public() for a in story.assets if not a.eligible],
        }
        entry["wipe"] = _transition(i, entry)
        if i > 0 or intro_plan:
            sfx.append({"file": "newscast/whoosh.mp3", "from": max(0, f0 - 7), "volume": 0.5 if i % 2 else 0.42})
        plan_stories.append(entry)
        cursor = start + story_ms
    outro_start = cursor
    outro_len = max(OUTRO_MIN_MS, min(OUTRO_MAX_MS, OUTRO_LEAD_MS + outro_ms + OUTRO_TAIL_MS))
    of0 = ms_to_frame(outro_start, fps)
    of1 = ms_to_frame(outro_start + outro_len, fps)
    sfx.append({"file": "newscast/whoosh.mp3", "from": max(0, of0 - 7), "volume": 0.45})
    sfx.append({"file": "newscast/sting.mp3", "from": of0, "volume": 0.5})
    outro = {"from": of0, "durationInFrames": of1 - of0, "cta": cta,
             "lines": outro_lines(OUTRO_TEXT_V3, outro_tokens or [], outro_start + OUTRO_LEAD_MS, fps),
             "voice": {"file": outro_voice, "from": ms_to_frame(outro_start + OUTRO_LEAD_MS, fps),
                       "durationInFrames": ms_to_frame(outro_start + OUTRO_LEAD_MS + outro_ms, fps) - ms_to_frame(outro_start + OUTRO_LEAD_MS, fps)} if outro_voice else None}
    return {
        "version": PLAN_VERSION, "fps": fps, "width": 1080, "height": 1920, "totalFrames": of1,
        "edition": {"brand": "La Voz Riojana", "descriptor": descriptor, "dateLabel": date_label, "testBanner": test_banner, "count": len(plan_stories)},
        "intro": intro_plan, "stories": plan_stories, "voices": voices, "captions": captions, "outro": outro,
        "music": music, "sfx": sorted(sfx, key=lambda x: x["from"]), "ledger": {k: v for k, v in ledger.items()}, "diagnostics": diagnostics or [],
    }


def validate_plan(plan: dict, assets_by_id: dict[str, Asset] | None = None) -> list[str]:
    """Invariantes del plan: continuidad sin huecos, tomas dentro de su
    historia, recursos del hecho activo, video leído dentro de su duración,
    subtítulos dentro de su historia y sin solaparse (ninguno sobre el
    cierre), voz completa."""
    errors = []
    fps = plan["fps"]
    intro = plan.get("intro")
    cursor = intro["durationInFrames"] if intro else 0
    if intro:
        for k, beat in enumerate(intro["beats"]):
            media = beat["shot"].get("media")
            if media and media["note"] not in beat["ids"]:
                errors.append(f"gancho frase {k + 1}: imagen de {media['note']} sobre el hecho {beat['ids']}")
            if beat["to"] <= beat["from"]:
                errors.append(f"gancho frase {k + 1}: duración inválida")
    for s in plan["stories"]:
        if s["from"] != cursor:
            errors.append(f"historia {s['index'] + 1}: empieza en {s['from']} y debía en {cursor}")
        if s["durationInFrames"] <= 0:
            errors.append(f"historia {s['index'] + 1}: duración no positiva")
        shot_cursor = 0
        for k, shot in enumerate(s["shots"]):
            if shot["from"] != shot_cursor or shot["durationInFrames"] <= 0:
                errors.append(f"historia {s['index'] + 1} toma {k + 1}: hueco o duración inválida")
            shot_cursor = shot["from"] + shot["durationInFrames"]
            media = shot.get("media")
            if media:
                event = next((e for e in s["events"] if e["index"] == shot["event"]), None)
                allowed = event["ids"] if event else s["ids"]
                if media["note"] not in allowed:
                    errors.append(f"historia {s['index'] + 1} toma {k + 1}: recurso de {media['note']} sobre el hecho {allowed}")
                if media["type"] == "video":
                    end = media["sourceInFrames"] + shot["durationInFrames"]
                    if end > ms_to_frame(media["durationMs"], fps) + 1:
                        errors.append(f"historia {s['index'] + 1} toma {k + 1}: lee el video después de su final")
                if assets_by_id is not None:
                    asset = assets_by_id.get(media["id"])
                    if asset is None or not asset.eligible:
                        errors.append(f"historia {s['index'] + 1} toma {k + 1}: recurso no elegible")
        if shot_cursor != s["durationInFrames"]:
            errors.append(f"historia {s['index'] + 1}: las tomas cubren {shot_cursor} de {s['durationInFrames']} frames")
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
    for asset_id, ranges in (plan.get("ledger") or {}).items():
        spans = sorted(r for r in ranges if r[1] > r[0])
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            overlap = max(0, min(a1, b1) - max(a0, b0))
            if overlap > 0.2 * min(a1 - a0, b1 - b0):
                errors.append(f"recurso {asset_id}: tramo de video repetido más de 20 %")
    return errors


# ── Voz ──────────────────────────────────────────────────────────────────
def synth_energetic(text: str, dest: str) -> float:
    """Orus con la dirección V4 y ritmo medido: si la toma sale por debajo
    de ``NIGHTLY_NEWSCAST_TARGET_PPM`` (158 palabras/min, pausas incluidas),
    se ajusta con atempo hasta 1,12× (sin pasar a voz robótica)."""
    nn.synthesize(text, dest, direction=VOICE_DIRECTION_V4, tempo=os.getenv("NIGHTLY_NEWSCAST_TEMPO_V3", "1.0"))
    seconds = nn.media_duration(dest)
    words = len(text.split())
    ppm = words / max(0.1, seconds) * 60
    target = _env_float("NIGHTLY_NEWSCAST_TARGET_PPM", 158)
    factor = min(_env_float("NIGHTLY_NEWSCAST_MAX_TEMPO_FIX", 1.12), target / ppm) if ppm > 0 else 1.0
    if factor > 1.01:
        tmp = dest + ".tempo.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dest, "-af", f"atempo={factor:.3f}", tmp], check=True, capture_output=True, timeout=120)
        os.replace(tmp, dest)
        seconds = nn.media_duration(dest)
    logger.info("Locución: %d palabras, %.0f ppm → %.0f ppm (×%.2f)", words, ppm, words / max(0.1, seconds) * 60, max(1.0, factor))
    return seconds


def cached_tts(text: str, dest_wav: str, cache_dir: str, synth=None, calls: dict | None = None) -> float:
    """Locución por texto cacheada por voz/modelo/ritmo/dirección/texto:
    regenerar la edición no vuelve a facturar ni a gastar cupo; un texto
    nuevo sí genera audio nuevo."""
    key = hashlib.sha1("|".join([
        os.getenv("NIGHTLY_NEWSCAST_TTS_MODEL", "gemini-2.5-pro-preview-tts"), os.getenv("NIGHTLY_NEWSCAST_VOICE", "Orus"),
        os.getenv("NIGHTLY_NEWSCAST_TEMPO_V3", "1.0"), os.getenv("NIGHTLY_NEWSCAST_TARGET_PPM", "158"), VOICE_DIRECTION_V4, text,
    ]).encode("utf-8")).hexdigest()[:16]
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, f"voz4_{key}.wav")
    if not os.path.isfile(cached):
        (synth or synth_energetic)(text, cached)
        if calls is not None:
            calls["tts"] = calls.get("tts", 0) + 1
    shutil.copyfile(cached, dest_wav)
    return nn.media_duration(dest_wav)


def _lufs(path: str) -> float | None:
    out = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=120)
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", out.stderr)
    return float(found[-1]) if found else None


def music_gain_db(voice_files: list[str], bed: str, under_db: float | None = None) -> float | None:
    """Ganancia de la música para quedar ``under_db`` debajo de la voz
    (medido con ebur128 sobre la voz real y la música)."""
    voice = [x for x in (_lufs(v) for v in voice_files[:3]) if x is not None]
    music = _lufs(bed)
    if not voice or music is None:
        return None
    under = under_db if under_db is not None else _env_float("NIGHTLY_NEWSCAST_MUSIC_UNDER_DB", 13.0)
    return round(sum(voice) / len(voice) - under - music, 2)


def ensure_tick(remotion_dir: str) -> None:
    """Acento sonoro breve para los datos (sintetizado con ffmpeg, propio)."""
    path = os.path.join(remotion_dir, "public", "newscast", "tick.mp3")
    if os.path.isfile(path):
        return
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.6*sin(2*PI*(900+1400*t)*t)*exp(-38*t)':s=48000:d=0.18",
                    "-af", "lowpass=f=5000,afade=t=out:st=0.12:d=0.06", "-c:a", "libmp3lame", "-b:a", "128k", path],
                   check=True, capture_output=True, timeout=60)


# ── Armado ───────────────────────────────────────────────────────────────
class NotEnoughMaterial(Exception):
    """No alcanzan los hechos con imagen propia para una edición digna."""


JUDICIAL_HINT_RE = re.compile(r"\b(juicio|juzga|tribunal|camara|condena|imputa|procesa|fiscal|sentencia|audiencia|preventiva|absuel|querella)")


def require_media() -> bool:
    return os.getenv("NIGHTLY_NEWSCAST_REQUIRE_MEDIA", "true").strip().lower() not in ("0", "false", "no")


def _load_library() -> dict:
    from utils import newscast_library as lib

    try:
        return nn.load_json(lib.library_path(), {}, expected_type=dict)
    except nn.JsonStateError:
        return {}


def gather_assets(c: nn.Candidate, work: str, library: dict, providers: dict, *, video_budget: list[int], photo: bool = True, video: bool = True) -> list[Asset]:
    """Foto procesada y video de una nota, con procedencia. ``video_budget``
    es un contador compartido ([n]) de videos que todavía se pueden sumar."""
    from utils import newscast_library as lib

    prepare_photo = providers.get("photo") or nn.prepare_photo
    prepare_video = providers.get("video") or (lambda url, dest, max_seconds=90: nn.prepare_video(url, dest, max_seconds=max_seconds, max_width=1920))
    entry = library.get(c.library_key) or {}
    items: list[Asset] = []
    if photo:
        dest = os.path.join(work, f"{c.id}.jpg")
        size = None
        if c.photo_path and os.path.isfile(c.photo_path):
            shutil.copyfile(c.photo_path, dest)
            from PIL import Image

            with Image.open(dest) as im:
                size = im.size
        elif c.photo_url:
            size = prepare_photo(c.photo_url, dest)
        if size:
            items.append(Asset(c.id, "image", dest, c.photo_url, size[0], size[1], sha=file_sha(dest)))
    if video and c.video_url and video_budget[0] > 0:
        dest = os.path.join(work, f"{c.id}.mp4")
        stored = entry.get("video") or {}
        if stored.get("path") and os.path.isfile(stored["path"]):
            shutil.copyfile(stored["path"], dest)
            vsize = (stored.get("width"), stored.get("height"))
        else:
            vsize = prepare_video(c.video_url, dest, max_seconds=nn._env_int("NIGHTLY_NEWSCAST_VIDEO_SECONDS", 90))
            if vsize and c.library_key and not providers.get("no_library"):
                keep = os.path.join(lib.media_root(), c.library_key, "video.mp4")
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copyfile(dest, keep)
                lib.remember(c.library_key, video={"path": keep, "width": vsize[0], "height": vsize[1], "url": c.video_url})
        if vsize and vsize[0]:
            items.append(Asset(c.id, "video", dest, c.video_url, vsize[0], vsize[1], duration_ms=int(nn.media_duration(dest) * 1000), sha=file_sha(dest)))
            video_budget[0] -= 1
    return items


def check_assets(c: nn.Candidate, items: list[Asset], library: dict, providers: dict, calls: dict, *, policial: bool, sensitive: bool,
                 judicial: bool, cache_dir: str, frames_dir: str) -> None:
    """Control visual (caché por hash, también en la biblioteca) y puertas."""
    from utils import newscast_library as lib

    vision = providers.get("vision") or check_media
    stored_checks = (library.get(c.library_key) or {}).get("checks") or {}
    for asset in items:
        if asset.sha in stored_checks:
            asset.check = dict(stored_checks[asset.sha])
        elif asset.type == "video":
            samples = video_frames(asset.file, asset.duration_ms, frames_dir)
            asset.check = vision([p for p, _ in samples], title=c.title, excerpt=c.body, video=True, cache_dir=cache_dir) or {}
            calls["vision"] = calls.get("vision", 0) + int(not asset.check.pop("_cached", False))
        else:
            asset.check = vision([asset.file], title=c.title, excerpt=c.body, video=False, cache_dir=cache_dir) or {}
            calls["vision"] = calls.get("vision", 0) + int(not asset.check.pop("_cached", False))
        if asset.check and c.library_key and asset.sha not in stored_checks and not providers.get("no_library"):
            lib.remember(c.library_key, check=(asset.sha, dict(asset.check)))
            library.setdefault(c.library_key, {}).setdefault("checks", {})[asset.sha] = dict(asset.check)
        if asset.type == "video":
            asset.usable_ms = usable_range(asset.check, asset.duration_ms)
        assess(asset, policial=policial, sensitive=sensitive, judicial=judicial)


def looks_judicial(c: nn.Candidate) -> bool:
    from utils import newscast_library as lib

    return str(c.source or "").startswith("judicial_") or bool(JUDICIAL_HINT_RE.search(lib._fold(c.title)))


def prescreen_media(candidates: list[nn.Candidate], *, providers: dict | None = None) -> tuple[list[nn.Candidate], dict]:
    """Antes del guion: sólo pasan las notas con foto o video propio elegible,
    así el guion nunca elige un hecho que después saldría sin imagen.

    Se revisa primero la foto; el video sólo si la foto no sirve (ahorra
    descargas). Los controles quedan en la biblioteca y en la caché por hash:
    el armado de la edición los reutiliza sin volver a llamar al modelo.
    Las notas judiciales se evalúan con la regla estricta (sin retratos)."""
    from utils.remotion_renderer import REMOTION_DIR

    providers = providers or {}
    report = {"checked": 0, "kept": 0, "excluded": [], "vision_calls": 0}
    if not require_media():
        return list(candidates), {**report, "skipped": "NIGHTLY_NEWSCAST_REQUIRE_MEDIA=false"}
    library = _load_library()
    cache_dir = os.path.join(REMOTION_DIR, "public", "tmp", "newscast_cache")
    os.makedirs(cache_dir, exist_ok=True)
    video_budget = [nn._env_int("NIGHTLY_NEWSCAST_PRESCREEN_VIDEOS", 8)]
    calls: dict = {"vision": 0}
    kept: list[nn.Candidate] = []
    work = tempfile.mkdtemp(prefix="lvr_prescreen_")
    try:
        frames_dir = os.path.join(work, "proxies")
        os.makedirs(frames_dir, exist_ok=True)
        for c in candidates:
            report["checked"] += 1
            gates = {"policial": True, "sensitive": bool(c.sensitive), "judicial": looks_judicial(c)}
            reasons: list[str] = []
            ok = False
            for kind in ("photo", "video"):
                items = gather_assets(c, work, library, providers, video_budget=video_budget, photo=kind == "photo", video=kind == "video")
                check_assets(c, items, library, providers, calls, cache_dir=cache_dir, frames_dir=frames_dir, **gates)
                ok = any(a.eligible for a in items)
                reasons += [r for a in items for r in a.reasons if not a.eligible]
                if ok:
                    break
            if ok:
                kept.append(c)
            else:
                report["excluded"].append({"id": c.id, "titulo": c.title, "motivo": "; ".join(reasons) or "sin foto ni video"})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report["kept"] = len(kept)
    report["vision_calls"] = calls["vision"]
    logger.info("Prefiltro de imágenes: %d de %d notas con imagen propia elegible", len(kept), len(candidates))
    return kept, report


def build_edition_v3(day: date, candidates: list[nn.Candidate], script: ScriptV3, *, providers: dict | None = None) -> nn.Edition:
    """Arma la edición. ``providers`` permite inyectar descarga, control
    visual, locución, alineamiento y render (fixtures sin red)."""
    from utils import newscast_library as lib
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
    stamp = f"newscast3_{day.isoformat()}_{int(time.time())}"
    work = os.path.join(REMOTION_DIR, "public", "tmp", stamp)
    rel = f"tmp/{stamp}"
    cache_dir = os.path.join(REMOTION_DIR, "public", "tmp", "newscast_cache")
    os.makedirs(work, exist_ok=True)
    folder = str(nn.output_dir() / "noticiero" / day.isoformat())
    os.makedirs(folder, exist_ok=True)
    calls = {"tts": 0, "vision": 0}
    diagnostics = list(script.diagnostics)
    try:
        # 1. Inventario con procedencia (la biblioteca evita re-descargar).
        library = _load_library()
        video_budget = [nn._env_int("NIGHTLY_NEWSCAST_MAX_VIDEOS", 6)]
        assets: dict[str, list[Asset]] = {}
        for note in [x for b in script.blocks for x in b["ids"]]:
            assets[note] = gather_assets(by_id[note], work, library, providers, video_budget=video_budget)
        lap("descarga")
        # 2. Control visual (caché por hash, también en la biblioteca) y puertas.
        frames_dir = os.path.join(work, "proxies")
        os.makedirs(frames_dir, exist_ok=True)
        for block in script.blocks:
            for note in block["ids"]:
                check_assets(by_id[note], assets[note], library, providers, calls, policial=block["seccion"] == "policiales",
                             sensitive=bool(block.get("sensible")), judicial=block["tipo"] == "judicial", cache_dir=cache_dir, frames_dir=frames_dir)
        lap("control_visual")
        # 3. Hechos sin ninguna imagen propia elegible: salen siempre (decisión
        # del 2026-10-31: el Reel no muestra noticias sólo con texto). Con
        # NIGHTLY_NEWSCAST_REQUIRE_MEDIA=false vuelve la regla anterior.
        blocks = list(script.blocks)
        kept = []
        remaining = len(blocks)
        minimum = nn._env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS_V3", 3)
        for b in blocks:
            has = any(a.eligible for n in b["ids"] for a in assets[n])
            essential = (b.get("relevancia") or {}).get("interes", 3) >= 5 or b["tipo"] == "judicial"
            if not has and (require_media() or (not essential and remaining > minimum)):
                diagnostics.append(f"sale '{b['titulo']}': sin imagen propia elegible")
                remaining -= 1
                continue
            kept.append(b)
        blocks = kept
        if len(blocks) < minimum:
            raise NotEnoughMaterial(f"quedan {len(blocks)} hechos con imagen propia (mínimo {minimum})")
        hook_frases = derive_hook(blocks, assets)
        # 4. Orden: lo que promete el gancho, primero.
        material = {i: max([a.score for n in b["ids"] for a in assets[n] if a.eligible] or [0.0]) for i, b in enumerate(blocks)}
        order, order_notes = order_police(blocks, hook_frases, material)
        blocks = [blocks[i] for i in order]
        diagnostics += order_notes
        # 5. Presupuesto de duración (< 2 min): estimado antes de la locución.
        def estimate(bs):
            return 6500 + 3200 + sum(len(b["locucion"].split()) / 2.6 * 1000 + LEAD_MS + GAP_MS for b in bs)

        hook_block_ids = {f["ids"][0] for f in hook_frases}
        while estimate(blocks) > MAX_TOTAL_MS and len(blocks) > 3:
            removable = [b for b in blocks if not set(b["ids"]) & hook_block_ids]
            victim = min(removable or blocks, key=lambda b: story_score(b, 0.0))
            diagnostics.append(f"sale '{victim['titulo']}' por duración (estimada {estimate(blocks) / 1000:.0f} s)")
            blocks.remove(victim)
        # 6. Locución y alineamiento.
        synth = providers.get("tts")
        align = providers.get("align") or align_clip
        align_report = []
        intro_in = None
        if hook_frases:
            while True:
                hook_text = (" ".join(f["texto"] for f in hook_frases) + " " + HOOK_TAIL).strip()
                hook_wav = os.path.join(work, "hook.wav")
                hook_s = cached_tts(hook_text, hook_wav, cache_dir, synth, calls)
                lap("locucion")
                # Apertura de 7 s como máximo: si la toma se pasa, sale la
                # última frase (nunca la que abre con video) y se rehace.
                if INTRO_LEAD_MS + int(hook_s * 1000) + INTRO_TAIL_MS <= INTRO_MAX_MS or len(hook_frases) <= 2:
                    break
                diagnostics.append(f"gancho de {hook_s:.1f} s: sale '{hook_frases[-1]['texto']}'")
                hook_frases = hook_frases[:-1]
            hook_al = align(hook_wav, hook_text, int(hook_s * 1000), cache_dir=cache_dir)
            lap("alineamiento")
            align_report.append({"story": "gancho", "ok": hook_al.ok, "coverage": hook_al.coverage, "critical_ok": hook_al.critical_ok,
                                 "errors": hook_al.errors, "elapsed_s": hook_al.elapsed_s, "method": hook_al.method})
            intro_in = IntroInput(voice_file=f"{rel}/hook.wav", voice_ms=int(hook_s * 1000), tokens=hook_al.tokens if hook_al.ok else [],
                                  frases=[{**f, "assets": [a for n in f["ids"] for a in assets.get(n, [])]} for f in hook_frases],
                                  align_ok=hook_al.ok and hook_al.critical_ok)
        stories: list[StoryInput] = []
        for i, b in enumerate(blocks):
            wav = os.path.join(work, f"b{i}.wav")
            seconds = cached_tts(b["locucion"], wav, cache_dir, synth, calls)
            lap("locucion")
            result = align(wav, b["locucion"], int(seconds * 1000), cache_dir=cache_dir)
            lap("alineamiento")
            align_report.append({"story": i, "ok": result.ok, "coverage": result.coverage, "critical_ok": result.critical_ok,
                                 "errors": result.errors, "elapsed_s": result.elapsed_s, "method": result.method})
            names = sorted({by_id[x].source_name for x in b["ids"] if by_id[x].source_name})
            stories.append(StoryInput(
                block=b, voice_file=f"{rel}/b{i}.wav", voice_ms=int(seconds * 1000), tokens=result.tokens if result.ok else [],
                assets=[a for n in b["ids"] for a in assets[n]], credit=_credit(names),
                align_ok=result.ok and result.critical_ok, note_sources={x: by_id[x].source_name for x in b["ids"]},
            ))
        outro_wav = os.path.join(work, "outro.wav")
        outro_s = cached_tts(OUTRO_TEXT_V3, outro_wav, cache_dir, synth, calls)
        lap("locucion")
        outro_align = align(outro_wav, OUTRO_TEXT_V3, int(outro_s * 1000), cache_dir=cache_dir)
        align_report.append({"story": "cierre", "ok": outro_align.ok, "coverage": outro_align.coverage, "critical_ok": outro_align.critical_ok,
                             "errors": outro_align.errors, "elapsed_s": outro_align.elapsed_s, "method": outro_align.method})
        lap("alineamiento")
        # Duración real: si se pasa de 1:59, salen las de menor puntaje.
        def real_ms():
            intro_ms = (INTRO_LEAD_MS + intro_in.voice_ms + INTRO_TAIL_MS) if intro_in else 0
            return intro_ms + sum(LEAD_MS + s.voice_ms + GAP_MS for s in stories) + min(OUTRO_MAX_MS, OUTRO_LEAD_MS + int(outro_s * 1000) + OUTRO_TAIL_MS)

        while real_ms() > MAX_TOTAL_MS and len(stories) > 3:
            removable = [s for s in stories if not set(s.block["ids"]) & hook_block_ids]
            victim = min(removable or stories, key=lambda s: story_score(s.block, 0.0))
            diagnostics.append(f"sale '{victim.block['titulo']}' por duración real ({real_ms() / 1000:.1f} s)")
            stories.remove(victim)
        # 7. Plan.
        for a in [a for items in assets.values() for a in items]:
            a.file = f"{rel}/{os.path.basename(a.file)}"
        music = None
        bed = os.path.join(REMOTION_DIR, "public", "newscast", "bed.mp3")
        if nn.flag("NIGHTLY_NEWSCAST_MUSIC", "true") and os.path.isfile(bed):
            voice_files = [os.path.join(work, f"b{i}.wav") for i in range(len(blocks))]
            gain = music_gain_db(voice_files, bed)
            if gain is not None:
                music = {"file": "newscast/bed.mp3", "gainDb": gain, "openGainDb": gain + 5, "introGainDb": gain + 8}
        ensure_tick(REMOTION_DIR)
        plan = build_plan(stories, outro_voice=f"{rel}/outro.wav", outro_ms=int(outro_s * 1000), date_label=nn.date_label(day),
                          descriptor=os.getenv("NIGHTLY_NEWSCAST_DESCRIPTOR", DESCRIPTOR_DEFAULT), cta=os.getenv("NIGHTLY_NEWSCAST_CTA", CTA_DEFAULT),
                          music=music, diagnostics=diagnostics,
                          outro_tokens=outro_align.tokens if outro_align.ok else None,
                          test_banner=providers.get("test_banner", ""), intro=intro_in)
        all_assets = {a.id: a for items in assets.values() for a in items}
        errors = validate_plan(plan, all_assets)
        lap("plan")
        selection = providers.get("selection") or {}
        with open(os.path.join(folder, "visual_plan.json"), "w", encoding="utf-8") as fh:
            json.dump({**plan, "selection": selection, "alignment": align_report, "timings": timings, "calls": calls, "validation": errors,
                       "assets": [a.public() for a in all_assets.values()]}, fh, ensure_ascii=False, indent=1)
        if errors:
            raise RuntimeError(f"Plan del noticiero inválido: {errors[:5]}")
        # 8. Render.
        props_path = os.path.join(work, "props.json")
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False)
        raw_video = os.path.join(tempfile.gettempdir(), f"lvr_{stamp}.mp4")
        (providers.get("render") or render_v3)(props_path, raw_video)
        lap("render")
        final = os.path.join(folder, f"noticiero-{day.isoformat()}.mp4")
        target = os.getenv("NIGHTLY_NEWSCAST_LUFS", "-14")
        subprocess.run(
            # loudnorm de una pasada deja picos de −1,1 dBTP: limitador a −2 dBFS.
            ["ffmpeg", "-v", "error", "-y", "-i", raw_video, "-c:v", "copy", "-af", f"loudnorm=I={target}:TP=-1.5:LRA=9,alimiter=limit=0.79:level=false",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", final],
            check=True, capture_output=True, timeout=600,
        )
        os.unlink(raw_video)
        lap("normalizacion")
        # 9. Entregables (mismos nombres y claves que V2, más campos nuevos).
        final_blocks = [s.block for s in stories]
        caption = caption_v3(day, final_blocks, by_id)
        with open(os.path.join(folder, "texto.txt"), "w", encoding="utf-8") as fh:
            fh.write(caption)
        with open(os.path.join(folder, "guion.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "version": "v3", "gancho": (" ".join(f["texto"] for f in hook_frases) + " " + HOOK_TAIL).strip(),
                "titulares": [f["texto"] for f in hook_frases],
                "bloques": [{**b, "notas": [by_id[x].web_url for x in b["ids"]]} for b in final_blocks],
                "cierre": OUTRO_TEXT_V3,
            }, fh, ensure_ascii=False, indent=2)
        write_srt(plan, os.path.join(folder, "subtitulos.srt"))
        report = inspect_video(final) if providers.get("inspect", True) else {}
        lap("inspeccion")
        with open(os.path.join(folder, "visual_plan.json"), "r+", encoding="utf-8") as fh:
            data = json.load(fh)
            data.update({"timings": timings, "calls": calls, "inspection": report})
            fh.seek(0)
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.truncate()
        script.blocks = final_blocks
        logger.info("Noticiero V3 %s: %d historias, tiempos %s, llamadas %s", day, len(final_blocks), timings, calls)
        return nn.Edition(day=day, video_path=final, caption=caption, script=script, blocks=final_blocks, folder=folder)
    finally:
        if not providers.get("keep_work"):
            shutil.rmtree(work, ignore_errors=True)


def caption_v3(day: date, blocks: list[dict], candidates: dict[str, nn.Candidate]) -> str:
    """Texto del Reel: hechos, invitación a seguir y créditos de imágenes
    (la atribución va acá, no en pantalla)."""
    base = nn.caption_for(day, blocks, candidates)
    names = sorted({candidates[x].source_name for b in blocks for x in b["ids"] if x in candidates and candidates[x].source_name})
    base = base.replace("🎙️ Noticiero de la Noche", "🚨 Policiales de La Rioja · últimas 24 h")
    if names:
        base += "\n\nInformación e imágenes: " + ", ".join(names) + "."
    return base


def render_v3(props_path: str, out_path: str, *, attempts: int = 2, composition: str = "NightlyNewscastV3") -> None:
    """Render con Remotion CLI. Un timeout al levantar el navegador headless
    (contención con otros renders del host) se reintenta una vez; cualquier
    otro error falla de inmediato. V5 pasa su propia composición."""
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    for attempt in range(1, attempts + 1):
        result = _render_once(props_path, out_path, REMOTION_DIR, _npx_args, composition)
        if result.returncode == 0 and os.path.isfile(out_path):
            return
        output = (result.stderr or result.stdout or "")
        if attempt < attempts and "setting up the headless browser" in output:
            logger.warning("Render V3: timeout del navegador headless, reintento %s/%s", attempt + 1, attempts)
            time.sleep(10)
            continue
        raise RuntimeError(f"Render del noticiero ({composition}) falló: {output[-600:]}")


def _render_once(props_path: str, out_path: str, remotion_dir: str, npx_args, composition: str = "NightlyNewscastV3"):
    return subprocess.run(
        npx_args(["remotion", "render", os.getenv("NIGHTLY_NEWSCAST_ENTRY", "src/index.ts"), composition, out_path, "--codec=h264", "--crf=18",
                  "--timeout=120000", f"--concurrency={os.getenv('NIGHTLY_NEWSCAST_RENDER_CONCURRENCY', '4')}", f"--props={props_path}"]),
        cwd=remotion_dir, capture_output=True, text=True, timeout=int(os.getenv("NIGHTLY_NEWSCAST_RENDER_TIMEOUT", "2400")),
    )


def write_srt(plan: dict, path: str) -> None:
    def stamp(frame: int) -> str:
        ms = int(frame * 1000 / plan["fps"])
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    with open(path, "w", encoding="utf-8") as fh:
        for k, c in enumerate(plan["captions"], 1):
            fh.write(f"{k}\n{stamp(c['from'])} --> {stamp(c['to'])}\n{c['text']}\n\n")


# ── Inspección del MP4 ───────────────────────────────────────────────────
def inspect_video(path: str) -> dict:
    """Chequeo técnico del MP4 final: formato, decodificación completa,
    negro, congelamiento y sonoridad. Umbrales documentados; una placa quieta
    deliberada no es un error por sí sola, y la ausencia de alertas no
    certifica calidad editorial."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels",
                            "-of", "json", path], capture_output=True, text=True, timeout=120)
    info = json.loads(probe.stdout or "{}")
    run = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", path,
         "-vf", "blackdetect=d=0.4:pix_th=0.08,freezedetect=n=0.003:d=2.5", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=900,
    )
    log = run.stderr
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    freezes = re.findall(r"freeze_start: ([\d.]+)", log)
    freeze_ends = re.findall(r"freeze_end: ([\d.]+)", log)
    integrated = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", log)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)
    return {
        "streams": info.get("streams", []), "duration": float((info.get("format") or {}).get("duration") or 0),
        "decode_ok": run.returncode == 0, "black": black,
        "freezes": [[float(a), float(b) if k < len(freeze_ends) else None] for k, (a, b) in enumerate(zip(freezes, freeze_ends + [None] * len(freezes)))],
        "lufs": float(integrated[-1]) if integrated else None, "lra": float(lra[-1]) if lra else None,
        "true_peak_dbfs": float(peak[-1]) if peak else None,
    }
