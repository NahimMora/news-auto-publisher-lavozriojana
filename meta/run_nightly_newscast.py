"""Etapa del Noticiero de la Noche (Reel locutado de las 21).

La lanza la tarea programada ``LaVozRiojana-Noticiero`` a las 20:30
(``scripts/run_nightly_newscast.ps1``): arma el guion, la locución y el
render, deja el video en ``output/noticiero/<fecha>/`` y, sólo con
``NIGHTLY_NEWSCAST_PUBLISH=true``, espera a las 21 y publica en Instagram y
Facebook. Una edición por día; un resultado ambiguo no se reintenta.

Uso:
    python meta/run_nightly_newscast.py              # según flags
    python meta/run_nightly_newscast.py --dry-run    # genera sin publicar
    python meta/run_nightly_newscast.py --force      # regenera aunque ya exista
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from utils import newscast_v3 as v3
from utils import newscast_v5 as v5
from utils import nightly_newscast as nn
from utils.deployment import deployment_plan
from utils.file_manager import JsonStateError
from utils.logging_setup import setup_logger
from utils.stage_result import StageResult, StageStatus, emit_stage_result

logger = setup_logger("run_nightly_newscast", "nightly_newscast.log")

STAGE = "nightly_newscast"


def main(argv: list[str] | None = None) -> StageResult:
    args = argparse.ArgumentParser(description="Noticiero de la Noche")
    args.add_argument("--dry-run", action="store_true", help="genera el video sin publicar")
    args.add_argument("--force", action="store_true", help="regenera aunque la edición del día exista")
    opts = args.parse_args(argv)
    started = time.monotonic()

    if not nn.flag("NIGHTLY_NEWSCAST_ENABLED"):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"disabled": True})
    plan = deployment_plan()
    publish_enabled = nn.flag("NIGHTLY_NEWSCAST_PUBLISH") and not opts.dry_run
    instagram = publish_enabled and plan.channel_enabled("instagram")
    facebook = publish_enabled and plan.channel_enabled("facebook") and nn.flag("NIGHTLY_NEWSCAST_FACEBOOK", "true")
    day = nn.today()
    key = day.isoformat()
    try:
        record = nn.load_state().get(key) or {}
    except JsonStateError as exc:
        logger.error("Estado del noticiero ilegible: %s", exc)
        return StageResult(STAGE, StageStatus.FAILED, error_type="state_read_error")
    if not opts.force and not nn.due(key, publish_enabled=publish_enabled):
        return StageResult(STAGE, StageStatus.NO_WORK, details={"day": key, "record": record})

    nn.note_attempt(key)
    edition = None
    if record.get("video") and os.path.isfile(record["video"]) and not opts.force:
        logger.info("Edición %s ya generada: se reutiliza %s", key, record["video"])
    else:
        # V3/V4 (noticiero policial de 24 h desde la biblioteca de notas
        # propias) detrás de NIGHTLY_NEWSCAST_VISUAL=v3; V5 (apertura en frío,
        # edición por frases, portada) con "v5" y la misma selección. V2 sigue
        # como rollback.
        version = v3.visual_version()
        use_v5 = version == "v5"
        use_v3 = version == "v3" or use_v5
        selection: dict = {}
        if use_v3:
            candidates, selection = v3.collect_candidates_v3()
            # Sólo notas con imagen propia elegible: ningún hecho sale sin imagen.
            candidates, selection["media"] = v3.prescreen_media(candidates)
        else:
            candidates = nn.collect_candidates()
        logger.info("Noticiero %s: %d notas candidatas (visual %s)", key, len(candidates), version if use_v3 else "v2")
        minimum = nn._env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS_V3", 3) if use_v3 else nn._env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS", 4)
        if len(candidates) < minimum:
            nn.mark_day(key, status="no_work", reason="pocas_notas", candidates=len(candidates))
            return StageResult(STAGE, StageStatus.NO_WORK, received=len(candidates), details={"reason": "pocas_notas"})
        script, warnings = (v5.write_script_v5 if use_v5 else v3.write_script_v3 if use_v3 else nn.write_script)(candidates)
        if script is None:
            nn.mark_day(key, status="failed", reason="guion_sin_validar", warnings=warnings[:12])
            logger.warning("Guion del noticiero descartado: %s", warnings[:12])
            return StageResult(STAGE, StageStatus.FAILED, received=len(candidates), error_type="script_rejected",
                               duration_seconds=time.monotonic() - started, details={"warnings": warnings[:12]})
        try:
            if use_v5:
                edition = v5.build_edition_v5(day, candidates, script, providers={"selection": selection})
            elif use_v3:
                edition = v3.build_edition_v3(day, candidates, script, providers={"selection": selection})
            else:
                edition = nn.build_edition(day, candidates, script)
        except v3.NotEnoughMaterial as exc:
            nn.mark_day(key, status="no_work", reason="pocos_hechos_con_imagen", error=str(exc)[:200])
            logger.info("Noticiero %s sin material suficiente: %s", key, exc)
            return StageResult(STAGE, StageStatus.NO_WORK, received=len(candidates), details={"reason": "pocos_hechos_con_imagen"})
        except nn.TTSQuotaError as exc:
            nn.mark_day(key, status="degraded", reason="tts_quota", error=str(exc)[:200])
            logger.warning("Noticiero %s sin locución: %s", key, exc)
            return StageResult(STAGE, StageStatus.DEGRADED, received=len(candidates), error_type="rate_limit",
                               duration_seconds=time.monotonic() - started, details={"reason": "tts_quota"})
        except Exception as exc:  # noqa: BLE001 — render, TTS o ffmpeg: se informa y no se publica nada
            nn.mark_day(key, status="failed", reason=type(exc).__name__, error=str(exc)[:400])
            logger.error("No se pudo armar el noticiero: %s", exc)
            return StageResult(STAGE, StageStatus.FAILED, received=len(candidates), error_type="render_failed",
                               duration_seconds=time.monotonic() - started, details={"error": str(exc)[:400]})
        nn.mark_day(key, status="generated", video=edition.video_path, folder=edition.folder, blocks=len(script.blocks))
        logger.info("Noticiero %s listo: %s (%d bloques)", key, edition.video_path, len(script.blocks))
        record = nn.load_state().get(key) or {}

    if not (instagram or facebook):
        return StageResult(STAGE, StageStatus.SUCCESS, received=1, selected=1, processed=1, succeeded=1,
                           duration_seconds=time.monotonic() - started,
                           details={"day": key, "video": record.get("video"), "published": False})

    if edition is None:
        import json

        with open(os.path.join(record["folder"], "texto.txt"), encoding="utf-8") as fh:
            caption = fh.read()
        with open(os.path.join(record["folder"], "guion.json"), encoding="utf-8") as fh:
            guion = json.load(fh)
        cover = os.path.join(record["folder"], "portada.jpg")
        edition = nn.Edition(day=day, video_path=record["video"], caption=caption, script=None, blocks=guion.get("bloques", []), folder=record["folder"],
                             cover_path=cover if os.path.isfile(cover) else "", caption_complete=guion.get("version") == "v5")
    nn.wait_until_hour(nn._env_int("NIGHTLY_NEWSCAST_HOUR", 21))
    outcome = nn.publish(edition, instagram=instagram, facebook=facebook)
    ok = [v for v in outcome.values() if v == "success"]
    tried = [v for v in outcome.values() if v != "skipped"]
    if "ambiguous" in outcome.values():
        status = StageStatus.DEGRADED
    elif tried and len(ok) == len(tried):
        status = StageStatus.SUCCESS
    elif ok:
        status = StageStatus.DEGRADED
    else:
        status = StageStatus.FAILED
    return StageResult(STAGE, status, received=1, selected=1, processed=len(tried), succeeded=len(ok), failed=len(tried) - len(ok),
                       duration_seconds=time.monotonic() - started, details={"day": key, **outcome})


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
