"""Etapa estructurada: Reels de formato propio (Último momento y Datos útiles).

Ver ``utils/format_reels.py`` para los criterios. Cada nota se evalúa una sola
vez por formato (queda en ``data/format_reels.json`` con su motivo); como
máximo un Reel de cada formato por ciclo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import format_reels as fr
from utils import nightly_newscast as nn
from utils.deployment import deployment_plan
from utils.editorial_priority import is_breaking
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.social_time import now_ar
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_format_reels", "format_reels.log")

STAGE = "format_reels"
SKIP_CATEGORIES = {"deportes", "espectaculos"}


def _hours(name: str, default: str) -> tuple[int, int]:
    try:
        start, end = (int(x) for x in os.getenv(name, default).split("-"))
        return start, end
    except ValueError:
        a, b = default.split("-")
        return int(a), int(b)


def _in_window(name: str, default: str) -> bool:
    start, end = _hours(name, default)
    return start <= now_ar().hour < end


def _candidate(note: fr.Note) -> nn.Candidate | None:
    article = fr.fetch_note(note.url)
    if not article or not article.get("title") or not article.get("body"):
        return None
    return nn.Candidate(id="n1", title=article["title"], section=note.category or nn._fold(article.get("section") or ""),
                        source=note.source, web_url=note.url, published_at=note.published_at, body=article["body"],
                        photo_url=article.get("photo_url") or "", video_url=note.video_url, localities=note.localities)


def _photo(cand: nn.Candidate, work: str, *, policial: bool) -> tuple[dict | None, str]:
    if not cand.photo_url:
        return None, "sin foto"
    dest = os.path.join(work, "foto.jpg")
    size = nn.prepare_photo(cand.photo_url, dest)
    if not size:
        return None, "no se pudo bajar la foto"
    ok, why = fr.strong_photo(dest, size, policial=policial)
    if not ok:
        return None, why
    return {"type": "photo", "file": dest, "width": size[0], "height": size[1]}, ""


def _video(cand: nn.Candidate, work: str) -> tuple[dict | None, str]:
    raw = os.path.join(work, "video.mp4")
    if not nn.prepare_video(cand.video_url, raw, max_seconds=90, max_width=1080):
        return None, "no se pudo bajar el video"
    clip, why = fr.scene_clip(raw, work)
    if not clip:
        return None, why
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", clip],
                         capture_output=True, text=True, timeout=60)
    try:
        w, h = (int(x) for x in out.stdout.strip().split(","))
    except ValueError:
        return None, "video ilegible"
    credit = f"VIDEO: {cand.source_name.upper()}" if cand.source_name else ""
    return {"type": "video", "file": clip, "width": w, "height": h, "credit": credit}, ""


def _produce(kind: str, note: fr.Note, cand: nn.Candidate, media: dict, plan: fr.Plan, work: str) -> dict:
    rendered = fr.render(plan, cand, media, work)
    caption = fr.caption_for(plan, cand)
    locality = plan.place or (cand.localities[0] if cand.localities else "")
    return fr.publish(kind, note.url, rendered, caption, title=cand.title, section=cand.section, locality=locality)


def run_um(state: dict, records: list[dict]) -> tuple[str, dict]:
    day = now_ar().date().isoformat()
    if fr.published_today("um", state, day) >= fr._int("FORMAT_REELS_UM_MAX_PER_DAY", 2):
        return "no_work", {"um": "tope diario"}
    items = state.get("items") or {}
    for note in fr.recent_notes(fr._int("FORMAT_REELS_UM_MAX_AGE_MINUTES", 180)):
        if f"um:{note.url}" in items or note.category in SKIP_CATEGORIES:
            continue
        if not note.video_url or not is_breaking(note.title, note.category):
            continue  # filtros baratos: no se registra
        if not fr.is_scoop(note, records=records):
            fr.mark("um", note.url, status="rejected", reason="no es primicia", title=note.title[:90])
            continue
        work = fr.new_workdir("um")
        try:
            cand = _candidate(note)
            if not cand:
                fr.mark("um", note.url, status="rejected", reason="nota ilegible", title=note.title[:90])
                continue
            if not fr.is_riojan(cand):
                fr.mark("um", note.url, status="rejected", reason="no es un hecho riojano", title=cand.title[:90])
                continue
            photo, why = _photo(cand, work, policial=cand.section == "policiales")
            if not photo:
                fr.mark("um", note.url, status="rejected", reason=f"foto: {why}", title=cand.title[:90])
                continue
            media, why = _video(cand, work)
            if not media:
                fr.mark("um", note.url, status="rejected", reason=f"video: {why}", title=cand.title[:90])
                continue
            plan, warnings, _ok = fr.write_plan("um", cand)
            if not plan:
                fr.mark("um", note.url, status="rejected", reason="guion sin datos verificables", warnings=warnings[:5], title=cand.title[:90])
                continue
            return "done", {"um": _produce("um", note, cand, media, plan, work)}
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("Último momento falló para %s: %s", note.url, exc)
            fr.mark("um", note.url, status="failed", reason=str(exc)[:200], title=note.title[:90])
            return "error", {"um": "render_failed"}
        finally:
            fr.cleanup(work)
    return "no_work", {"um": "sin candidatas"}


def run_du(state: dict) -> tuple[str, dict]:
    items = state.get("items") or {}
    budget = fr._int("FORMAT_REELS_DU_MAX_EVAL", 4)
    for note in fr.recent_notes(fr._int("FORMAT_REELS_DU_MAX_AGE_MINUTES", 720)):
        if budget <= 0:
            break
        if f"du:{note.url}" in items or note.category in SKIP_CATEGORIES | {"policiales"}:
            continue
        budget -= 1
        cand = _candidate(note)
        if not cand:
            fr.mark("du", note.url, status="rejected", reason="nota ilegible", title=note.title[:90])
            continue
        if not fr.is_riojan(cand):
            fr.mark("du", note.url, status="rejected", reason="no es de La Rioja", title=cand.title[:90])
            continue
        plan, warnings, qualifies = fr.write_plan("du", cand)
        if not qualifies or not plan:
            fr.mark("du", note.url, status="rejected", reason=(warnings[0] if warnings else "sin guion")[:200], title=cand.title[:90])
            continue
        work = fr.new_workdir("du")
        try:
            media, why = _photo(cand, work, policial=False)
            if not media:
                fr.mark("du", note.url, status="rejected", reason=f"foto: {why}", title=cand.title[:90])
                continue
            return "done", {"du": _produce("du", note, cand, media, plan, work)}
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("Datos útiles falló para %s: %s", note.url, exc)
            fr.mark("du", note.url, status="failed", reason=str(exc)[:200], title=note.title[:90])
            return "error", {"du": "render_failed"}
        finally:
            fr.cleanup(work)
    return "no_work", {"du": "sin candidatas"}


def main() -> StageResult:
    started = time.monotonic()
    kinds = [k for k in ("um", "du") if fr.enabled(k)]
    if not kinds:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    if not deployment_plan().channel_enabled("instagram"):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"instagram_disabled": True})
    if not shutil.which("ffmpeg"):
        return StageResult(STAGE, StageStatus.FAILED, error_type="missing_dependency")
    try:
        state = fr.load_state()
    except JsonStateError as exc:
        logger.error("Estado de los Reels de formato ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    details: dict = {}
    statuses = []
    if "um" in kinds and _in_window("FORMAT_REELS_UM_HOURS", "7-24"):
        status, info = run_um(state, fr._web_records())
        statuses.append(status)
        details.update(info)
        state = fr.load_state()
    if "du" in kinds and _in_window("FORMAT_REELS_DU_HOURS", "8-22"):
        status, info = run_du(state)
        statuses.append(status)
        details.update(info)
    published = sum(1 for v in details.values() if isinstance(v, dict) and v.get("ig") == "success")
    failed = sum(1 for v in details.values() if (isinstance(v, dict) and v.get("ig") not in {"success"}) or v == "render_failed")
    if not published and not failed:
        return StageResult(STAGE, StageStatus.NO_WORK, details=details, duration_seconds=time.monotonic() - started)
    status = StageStatus.SUCCESS if not failed else StageStatus.DEGRADED
    return StageResult(STAGE, status, received=published + failed, processed=published + failed, succeeded=published, failed=failed,
                       details=details, duration_seconds=time.monotonic() - started)


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
