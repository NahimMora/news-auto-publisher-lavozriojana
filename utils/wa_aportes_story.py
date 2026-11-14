"""Historia "Mandanos tu noticia" por WhatsApp (formato WA-D4, 2026-11-14).

Video de 11 s (Remotion ``WaAportesStory``: notificación → chat → llamado)
con un sticker de enlace nativo a ``wa.me`` sobre el botón dibujado. Decisión
del responsable del medio: sólo en historias y justo después de la historia
"Sumate a nuestro WhatsApp" (``utils/wa_join_story.py``), así que sale los
mismos días y sólo si esa historia ya se publicó ese día.

* ``WA_APORTES_STORY_ENABLED=false`` (default): no hace nada.
* ``WA_APORTES_NUMBER`` (default ``5493804922704``): número en formato
  internacional sin signos; el enlace es ``https://wa.me/<número>`` con un
  mensaje inicial.
* La ventana horaria es la de la historia "Sumate" (``WA_JOIN_STORY_HOUR`` a
  ``WA_JOIN_STORY_UNTIL_HOUR``).

Una por día como máximo. Si la subida falla después de enviarse, queda
``unverified`` y ese día no se reintenta (nunca se publica dos veces a ciegas).
Sin IA: los textos son fijos y rotan por día.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from urllib.parse import quote

from utils import native_story as ns
from utils import wa_join_story as js
from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import now_ar

logger = setup_logger("wa_aportes_story", "native_stories.log")

COMPOSITION = "WaAportesStory"
# Caja del sticker de enlace (fracciones del lienzo 1080×1920). Tiene que
# coincidir con BUTTON_TOP/BUTTON_H/BUTTON_SIDE de WaAportesStory.tsx.
_BUTTON_TOP, _BUTTON_H, _BUTTON_SIDE = 1270, 160, 70
LINK_BOX = {
    "x": 0.5,
    "y": round((_BUTTON_TOP + _BUTTON_H / 2) / 1920, 4),
    "width": round((1080 - 2 * _BUTTON_SIDE) / 1080, 4),
    "height": round(_BUTTON_H / 1920, 4),
}
THUMB_SECONDS = 10.0  # cuadro del llamado (número y botón) para la portada
PREFILL = "Hola, La Voz Riojana. "

# Textos aprobados en la mesa (rotan por día).
MESSAGES = (
    {"question": "¿Viste algo que merece ser noticia?", "sub": "Mandanos fotos, videos y qué pasó 📲", "me": "¡Cayó granizo en el centro! 😮"},
    {"question": "¿Qué está pasando en tu barrio?", "sub": "Contanos y mandanos fotos o videos 📲", "me": "¡Cayó granizo en mi barrio! 😮"},
    {"question": "Mandanos tu noticia 📲", "sub": "Fotos, videos y datos de tu localidad.", "me": "Les mando lo del granizo 📷"},
)


def enabled() -> bool:
    return ns._flag("WA_APORTES_STORY_ENABLED")


def number() -> str:
    """Número validado (sólo dígitos, con código de país 54). ``ValueError`` si no."""
    raw = re.sub(r"\D", "", os.getenv("WA_APORTES_NUMBER", "5493804922704"))
    if not raw.startswith("54") or not 11 <= len(raw) <= 13:
        raise ValueError("WA_APORTES_NUMBER no es un número argentino válido")
    return raw


def display_number(digits: str) -> str:
    """``5493804922704`` → ``380 492-2704`` (sin el 54 9)."""
    local = digits[3:] if digits.startswith("549") else digits[2:]
    if len(local) == 10:
        return f"{local[:3]} {local[3:6]}-{local[6:]}"
    return local


def link(digits: str) -> str:
    return f"https://wa.me/{digits}?text={quote(PREFILL)}"


def state_path() -> str:
    return str(data_dir() / "wa_aportes_story.json")


def _join_done_today(day: str) -> bool:
    record = (load_json(js.state_path(), {}, expected_type=dict).get("days") or {}).get(day) or {}
    return record.get("status") == "completed"


def due(now: datetime | None = None, *, state: dict | None = None) -> bool:
    moment = now_ar(now)
    start = ns._int("WA_JOIN_STORY_HOUR", 20)
    until = ns._int("WA_JOIN_STORY_UNTIL_HOUR", 23)
    if moment.weekday() not in js._days() or not start <= moment.hour < until:
        return False
    day = moment.date().isoformat()
    state = state if state is not None else load_json(state_path(), {}, expected_type=dict)
    if day in (state.get("days") or {}):
        return False
    return _join_done_today(day)


def mark(day: str, **fields) -> None:
    def mutate(state):
        state.setdefault("days", {})[day] = fields
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def props_for(moment: datetime, digits: str) -> dict:
    message = MESSAGES[moment.date().toordinal() % len(MESSAGES)]
    return {
        **message,
        "clock": moment.strftime("%H:%M"),
        "number": display_number(digits),
        "backdropFile": "",
        "sfx": True,
    }


def render(props: dict) -> tuple[str, str]:
    """Renderiza el MP4 y su portada. Devuelve ``(video, portada)``.

    ``RuntimeError`` si Remotion o ffmpeg fallan (sin publicar nada).
    """
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    handle, props_path = tempfile.mkstemp(suffix=".json", prefix="lvr_wa_aportes_")
    os.close(handle)
    video = props_path[:-5] + ".mp4"
    thumb = props_path[:-5] + ".jpg"
    try:
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(props, fh, ensure_ascii=False)
        result = subprocess.run(
            _npx_args(["remotion", "render", COMPOSITION, video, "--codec=h264", "--crf=18", f"--props={props_path}"]),
            cwd=REMOTION_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )
        if result.returncode != 0 or not os.path.isfile(video):
            raise RuntimeError(f"remotion: {(result.stderr or result.stdout)[-300:]}")
        shot = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{THUMB_SECONDS}", "-i", video, "-frames:v", "1", "-q:v", "2", thumb],
            capture_output=True, text=True, timeout=60,
        )
        if shot.returncode != 0 or not os.path.isfile(thumb):
            raise RuntimeError(f"ffmpeg: {shot.stderr[-300:]}")
        return video, thumb
    except Exception:
        for path in (video, thumb):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    finally:
        try:
            os.unlink(props_path)
        except OSError:
            pass
