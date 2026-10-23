"""Etapa estructurada: formatos programados y seguimiento.

* "Lo que tenés que saber hoy": carrusel diario desde las 8 (Instagram) y
  álbum de fotos con el mismo texto (Facebook).
* "La semana en cinco": Reel de los domingos desde las 20.
* Seguimiento: si una noticia publicada cambia una cifra en una nota
  posterior, historia de actualización + comentario en Instagram y texto
  editado en Facebook.
* Placas de servicio: cronograma de pagos de Hacienda y sismos con
  epicentro en La Rioja (INPRES), como post y/o historia
  (``utils/service_posts.py``).

Cada formato tiene su interruptor (apagado por defecto) y su estado propio
(``data/social_formats_state.json``); ninguno consume cupos del feed.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from utils import social_formats as sf
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.remotion_renderer import RemotionRenderError
from utils.social_time import hhmm, now_ar, quiet_hours, today_ar
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts

logger = setup_logger("run_social_formats", "social_formats.log")

STAGE = "social_formats"


def _morning_brief(instagram: bool, facebook: bool) -> str:
    if not sf.flag("MORNING_BRIEF_ENABLED") or not sf.brief_due():
        return "not_due"
    day = today_ar().isoformat()
    sf.note_brief_attempt(day)
    try:
        brief = sf.build_morning_brief()
    except RemotionRenderError as exc:
        logger.warning("No se pudo renderizar el carrusel de la mañana: %s", exc)
        return "failed"
    if brief is None:
        return "failed"
    outcome = sf.publish_morning_brief(brief, instagram=instagram, facebook=facebook)
    return "success" if "success" in outcome.values() else "failed"


def _weekly_recap(instagram: bool, facebook: bool) -> str:
    if not sf.flag("WEEKLY_RECAP_ENABLED") or not sf.weekly_due():
        return "not_due"
    end = today_ar()
    sf.note_weekly_attempt(end.isoformat())
    items = sf.select_week_top()
    if len(items) < 3:
        logger.warning("Resumen semanal: sólo %s notas con foto; no se publica", len(items))
        return "failed"
    video = sf.render_weekly_recap(items, end)
    if not video:
        return "failed"
    try:
        outcome = sf.publish_weekly_recap(video, items, end, instagram=instagram, facebook=facebook)
    finally:
        try:
            os.unlink(video)
        except OSError:
            pass
    return "success" if "success" in outcome.values() else "failed"


def _updates(instagram: bool, facebook: bool) -> tuple[int, int]:
    """(publicadas, fallidas)."""
    if not sf.flag("STORY_UPDATES_ENABLED") or quiet_hours():
        return 0, 0
    from meta import fb_client, ig_client
    from utils import story_publisher as sp
    from utils import story_updates as su
    from utils.article_media import fetch_article

    state = sf.load_state()
    done = failed = 0
    for cand in su.update_candidates(state=state)[:2]:
        article = fetch_article(cand["web_url"]) or {}
        new_title = article.get("title") or cand["new_title"].capitalize()
        when = hhmm(now_ar())
        photo = sp.download_image(article["photo_url"]) if article.get("photo_url") else None
        try:
            props = sp.story_props(
                kind="update",
                titulo=(fetch_article_title(cand) or cand["original_title"].capitalize()),
                # Mismo hecho con dato nuevo: antes, lo que ya habíamos publicado.
                before=cand["original_title"] if cand.get("kind") == "event" else su.phrase(cand["noun"], cand["before"]),
                after=new_title,
                timeLabel=when,
                sourceLabel=f"Según la nota publicada a las {when}.",
            )
            jpeg = sp.render_story(props, photo)
        except (RemotionRenderError, OSError) as exc:
            logger.warning("No se pudo renderizar la actualización: %s", exc)
            failed += 1
            continue
        finally:
            if photo:
                try:
                    os.unlink(photo)
                except OSError:
                    pass
        story_key = f"update:{cand['key']}:{cand['web_url']}"
        outcome = sp.publish_story(story_key, jpeg, instagram=instagram, facebook=facebook, meta={"kind": "update", "label": new_title[:80]})
        record = {"story": outcome}
        if instagram:
            comment = ig_client.comment_on_media(cand["ig_media_id"], f"🔄 Actualización {when}: {new_title}. Más información en lavozriojana.com")
            record["ig_comment"] = comment.external_id if comment.ok else comment.error_type
        if facebook and cand["fb_post_id"]:
            original = fb_client.get_post_message(cand["fb_post_id"])
            if original is not None:
                edited = fb_client.edit_post_message(cand["fb_post_id"], su.facebook_message(original, new_title, when, cand["web_url"]))
                record["fb_edit"] = "success" if edited.ok else edited.error_type
        ok = "success" in outcome.values() or str(record.get("ig_comment", "")).isdigit() or record.get("fb_edit") == "success"

        def mutate(st, cand=cand, record=record):
            entry = st.setdefault("updates", {}).setdefault(cand["key"], {"sources": []})
            entry["sources"].append(cand["web_url"])
            entry.setdefault("log", []).append({**record, "at": int(time.time()), "noun": cand["noun"], "before": cand["before"], "after": cand["after"]})
            return st

        sf.update_state(mutate)
        done += 1 if ok else 0
        failed += 0 if ok else 1
    return done, failed


def _service_posts(instagram: bool, facebook: bool) -> tuple[int, int]:
    """(placas con algo publicado, placas fallidas). Va antes que la etapa de
    historias: la historia automática del post queda cubierta por la de
    servicio. Cada placa dice qué lleva (post en Instagram, en Facebook,
    historia) y sólo se publica lo que falta."""
    from utils import service_posts as spost
    from utils import story_publisher as sp

    state = sf.load_state()
    story_state = sp.load_state()
    story_ig = instagram and sp.instagram_enabled()
    story_fb = facebook and sp.facebook_enabled()

    def parts(job: dict) -> dict:
        return spost.pending_parts(job, state, story_state, instagram=instagram, facebook=facebook, stories=story_ig or story_fb)

    done = failed = 0
    for job in spost.due_service_posts(state=state, wanted=lambda job: any(parts(job).values()))[:2]:
        need = parts(job)
        ig_id = ((state.get("service_posts") or {}).get(job["key"]) or {}).get("ig_id") or ""
        published = False
        if need["ig"] or need["fb"]:
            try:
                card = spost.render_card(job["props"])
            except (RemotionRenderError, OSError) as exc:
                logger.warning("No se pudo renderizar la placa %s: %s", job["key"], exc)
                failed += 1
                continue
            outcome = spost.publish_post(job, card, instagram=need["ig"], facebook=need["fb"])
            ig_id = outcome.get("ig_id") or ig_id
            if "success" not in (outcome["ig"], outcome["fb"]):
                # La historia espera al post: se reintentan juntos.
                failed += 1
                if "rate_limit" in (outcome["ig"], outcome["fb"]):
                    break
                continue
            published = True
        if need["story"] or (published and ig_id):
            try:
                story = spost.publish_story(job, ig_id if published else "", instagram=story_ig, facebook=story_fb)
            except (RemotionRenderError, OSError) as exc:
                logger.warning("No se pudo renderizar la historia de la placa %s: %s", job["key"], exc)
                story = {"ig": "failed", "fb": "failed"}
            if "success" in story.values():
                published = True
            elif need["story"] and not published:
                failed += 1
                if "rate_limit" in story.values():
                    break
                continue
        done += int(published)
    return done, failed


def fetch_article_title(cand: dict) -> str:
    """Título con caja original de la noticia de origen (si está en la web)."""
    from utils.article_media import fetch_article
    from utils.file_manager import load_json
    from utils.paths import data_dir

    try:
        web = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError:
        return ""
    for r in web:
        if isinstance(r, dict) and str(r.get("titulo") or "") == cand["original_title"] and r.get("web_url"):
            return str((fetch_article(r["web_url"]) or {}).get("title") or "")
    return ""


def main() -> StageResult:
    started = time.monotonic()
    plan = deployment_plan()
    instagram = plan.channel_enabled("instagram") and sf.flag("SOCIAL_FORMATS_INSTAGRAM_ENABLED")
    facebook = plan.channel_enabled("facebook") and sf.flag("SOCIAL_FORMATS_FACEBOOK_ENABLED")
    if not instagram and not facebook:
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    try:
        sf.load_state()
    except JsonStateError as exc:
        logger.error("Estado de formatos ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")

    results = {
        "morning_brief": _morning_brief(instagram, facebook),
        "weekly_recap": _weekly_recap(instagram, facebook),
    }
    updates_ok, updates_failed = _updates(instagram, facebook)
    results["updates"] = {"published": updates_ok, "failed": updates_failed}
    service_ok, service_failed = _service_posts(instagram, facebook)
    results["service_posts"] = {"published": service_ok, "failed": service_failed}
    attempted = [v for k, v in results.items() if k not in {"updates", "service_posts"} and v != "not_due"]
    succeeded = sum(1 for v in attempted if v == "success") + updates_ok + service_ok
    failed = sum(1 for v in attempted if v != "success") + updates_failed + service_failed
    extra = updates_ok + updates_failed + service_ok + service_failed
    return result_from_counts(
        STAGE,
        received=len(attempted) + extra,
        selected=len(attempted) + extra,
        processed=succeeded + failed,
        succeeded=succeeded,
        failed=failed,
        duration_seconds=time.monotonic() - started,
        details=results,
    )


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
