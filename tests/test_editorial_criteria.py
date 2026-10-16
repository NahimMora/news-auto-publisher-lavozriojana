"""Criterio editorial del lote (docs/DECISIONS.md 2026-10-16).

Paparazzi con video = sólo Reel; paparazzi sin video con relevancia mínima;
internacionales en balde propio sólo de alto impacto; Instagram selectivo con
las notas locales; una falla de IA no manda la nota primera en la fila.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_publish_selection import _local, _paparazzi

_SELECTION_ENV = {
    "PUBLISH_LOCAL_MAX_PER_RUN": "6",
    "PUBLISH_PAPARAZZI_MAX_PER_RUN": "2",
    "PUBLISH_INFOBAE_MAX_PER_RUN": "2",
    "PUBLISH_LOCAL_EXCLUDED_CATEGORIES": "deportes,espectaculos",
}


def _international(key, *, score=None, seccion="sociedad"):
    item = {
        "titulo": f"internacional-{key}",
        "canonical_url": f"https://nuevarioja.com.ar/mundo/{key}",
        "seccion": seccion,
        "source": "nuevarioja_internacionales",
    }
    if score is not None:
        item["international_impact_score"] = score
    return item


_TITLES = [
    "Cortes de agua programados en el barrio Vargas",
    "El Concejo aprobó la nueva tarifa del transporte urbano",
    "Chilecito inaugura un centro de salud en el norte",
    "Detuvieron a dos jóvenes por robos en Famatina",
    "Abren las inscripciones para becas universitarias provinciales",
    "La Legislatura debatió el presupuesto de obras viales",
    "Productores de olivo reclaman ayuda por la helada tardía",
    "Se viene la feria del libro en la plaza 25 de Mayo",
    "Paparazzi: escándalo en un programa de televisión",
    "El municipio repavimentará la avenida Ortiz de Ocampo",
    "Vacunación antigripal casa por casa en Chamical",
]


def _ids(items):
    return {item["titulo"] for item in items}


class SelectionCriteriaTests(unittest.TestCase):
    def setUp(self):
        from utils import publish_selection

        self.module = publish_selection

    def _select(self, pending, **env):
        with mock.patch.dict(os.environ, {**_SELECTION_ENV, **env}):
            return self.module.select_batch(pending)

    def test_defaults_keep_previous_behavior(self):
        pending = [_paparazzi("v", video=True, score=2), _international("a"), _local("l")]
        with mock.patch.dict(os.environ, _SELECTION_ENV):
            for name in (
                "PAPARAZZI_VIDEO_ONLY_ENABLED",
                "PUBLISH_PAPARAZZI_MIN_SCORE",
                "PUBLISH_INTERNATIONAL_BUCKET_ENABLED",
            ):
                os.environ.pop(name, None)
            selected, _rest = self.module.select_batch(pending)
        self.assertEqual({"paparazzi-v", "internacional-a", "local-l"}, _ids(selected))

    def test_paparazzi_with_video_leaves_the_batch_when_video_only(self):
        pending = [_paparazzi("v", video=True, score=9), _paparazzi("i", score=9)]
        selected, rest = self._select(pending, PAPARAZZI_VIDEO_ONLY_ENABLED="true")
        self.assertEqual({"paparazzi-i"}, _ids(selected))
        self.assertEqual({"paparazzi-v"}, _ids(rest))

    def test_paparazzi_without_video_needs_min_score(self):
        pending = [_paparazzi("bajo", score=4), _paparazzi("alto", score=6)]
        selected, _rest = self._select(pending, PUBLISH_PAPARAZZI_MIN_SCORE="6")
        self.assertEqual({"paparazzi-alto"}, _ids(selected))

    def test_paparazzi_without_score_passes_but_goes_last(self):
        sin_puntaje = _paparazzi("sin")
        sin_puntaje.pop("paparazzi_relevance_score")
        pending = [sin_puntaje, _paparazzi("a", score=7), _paparazzi("b", score=8)]
        selected, _rest = self._select(
            pending,
            PUBLISH_PAPARAZZI_MIN_SCORE="6",
            PUBLISH_PAPARAZZI_MAX_PER_RUN="2",
            PUBLISH_LOCAL_MAX_PER_RUN="0",
            PUBLISH_INFOBAE_MAX_PER_RUN="0",
        )
        self.assertEqual({"paparazzi-a", "paparazzi-b"}, _ids(selected))

    def test_international_bucket_only_high_impact_with_own_cap(self):
        pending = [
            _international("bajo", score=5),
            _international("sin"),
            _international("alto", score=8),
            _international("maximo", score=10),
            _local("l"),
        ]
        selected, _rest = self._select(
            pending,
            PUBLISH_INTERNATIONAL_BUCKET_ENABLED="true",
            PUBLISH_INTERNATIONAL_MIN_SCORE="8",
            PUBLISH_INTERNATIONAL_MAX_PER_RUN="1",
        )
        self.assertEqual({"internacional-maximo", "local-l"}, _ids(selected))
        with mock.patch.dict(os.environ, {"PUBLISH_INTERNATIONAL_BUCKET_ENABLED": "true"}):
            self.assertEqual("internacional", self.module._bucket_name(pending[3]))

    def test_international_does_not_take_local_slots(self):
        pending = [_international(i, score=9) for i in range(5)]
        selected, _rest = self._select(
            pending,
            PUBLISH_INTERNATIONAL_BUCKET_ENABLED="true",
            PUBLISH_INTERNATIONAL_MAX_PER_RUN="1",
        )
        self.assertEqual(1, len(selected))


class RelevanceFallbackTests(unittest.TestCase):
    def test_ai_failure_leaves_note_without_score(self):
        from utils import paparazzi_relevance

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x", "GEMINI_RETRY_COUNT": "1"}), mock.patch(
            "utils.ai_client.chat_completion", side_effect=RuntimeError("caída")
        ):
            result = paparazzi_relevance.score_relevance("Título", ["Texto"])
        self.assertIsNone(result.score)
        self.assertTrue(result.fallback_used)

    def test_missing_credential_leaves_international_without_score(self):
        from utils import paparazzi_relevance

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            result = paparazzi_relevance.score_international_impact("Título", ["Texto"])
        self.assertIsNone(result.score)

    def test_international_prompt_scores(self):
        from utils import paparazzi_relevance

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), mock.patch(
            "utils.ai_client.chat_completion", return_value="9"
        ) as chat:
            result = paparazzi_relevance.score_international_impact("Papa", ["Visita"])
        self.assertEqual(9, result.score)
        self.assertIn("ALTO IMPACTO", chat.call_args.kwargs["messages"][0]["content"])


class InstagramLocalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from meta import run_ig
        from utils import social_queue

        self.run_ig = run_ig
        self.queue = social_queue
        self.ig_state = Path(self.tmp.name) / "ig_posted.json"
        self.queue_path = Path(self.tmp.name) / "social.json"
        for target, value in (
            (run_ig, ("IG_STATE_PATH", str(self.ig_state))),
            (social_queue, ("QUEUE_PATH", str(self.queue_path))),
        ):
            patcher = mock.patch.object(target, *value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("utils.social_queue.record_queue_event")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _note(self, key, *, seccion="politica", titulo=None, source="nuevarioja_politica"):
        return {
            "titulo": titulo or _TITLES[key % len(_TITLES)],
            "canonical_url": f"https://example.com/{key}",
            "seccion": seccion,
            "source": source,
            "selected_for_publish": True,
        }

    def test_category_filter(self):
        with mock.patch.dict(os.environ, {"IG_LOCAL_CATEGORIES": "policiales,sociedad"}):
            allowed = self.run_ig._local_allowed_by_category
            self.assertTrue(allowed(self._note(1, seccion="policiales")))
            self.assertFalse(allowed(self._note(2, seccion="politica")))
            self.assertTrue(allowed(self._note(3, seccion="interior", titulo="Grave accidente en la ruta 38")))
            self.assertTrue(allowed(self._note(4, seccion="espectaculos", source="paparazzi")))
            self.assertTrue(allowed(self._note(5, seccion="sociedad", source="nuevarioja_internacionales")))
        with mock.patch.dict(os.environ, {"IG_LOCAL_CATEGORIES": ""}):
            self.assertTrue(self.run_ig._local_allowed_by_category(self._note(6)))

    def test_daily_cap_counts_today_and_excludes_the_rest(self):
        now = int(time.time())
        posted = {
            "a": {"posted_at": now, "seccion": "policiales", "source": "nuevarioja_policiales"},
            "b": {"posted_at": now, "seccion": "espectaculos", "source": "paparazzi"},
            "c": {"posted_at": now, "seccion": "policiales", "source": "x", "media_type": "reel"},
            "d": {"posted_at": now - 3 * 86400, "seccion": "policiales", "source": "nuevarioja_policiales"},
        }
        self.ig_state.write_text(json.dumps({"posted": posted}), encoding="utf-8")
        notes = [self._note(i) for i in range(1, 4)]
        paparazzi = self._note(9, seccion="espectaculos", source="paparazzi")
        manual = {**self._note(10), "selected_for_publish": False}
        self.queue.enqueue_many(notes + [paparazzi, manual], platform="instagram")

        with mock.patch.dict(os.environ, {"IG_LOCAL_DAILY_MAX": "2"}):
            kept, excluded = self.run_ig._apply_local_daily_cap(notes + [paparazzi, manual])

        self.assertEqual([notes[0]["titulo"], paparazzi["titulo"], manual["titulo"]], [n["titulo"] for n in kept])
        self.assertEqual(2, excluded)
        queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        states = {item["titulo"]: item["instagram_state"] for item in queue}
        self.assertEqual("excluded", states[notes[1]["titulo"]])

        # El bootstrap del ciclo siguiente no reactiva un descarte por política.
        counts = self.queue.enqueue_many([notes[1]], platform="instagram")
        self.assertEqual(1, counts["unchanged"])
        self.assertEqual([], [n for n in self.queue.get_pending("instagram") if n["titulo"] == notes[1]["titulo"]])

    def test_no_cap_by_default(self):
        notes = [self._note(i) for i in range(1, 4)]
        with mock.patch.dict(os.environ, {"IG_LOCAL_DAILY_MAX": "0"}):
            kept, excluded = self.run_ig._apply_local_daily_cap(notes)
        self.assertEqual((notes, 0), (kept, excluded))


class PaparazziVideoJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import paparazzi_video_jobs

        self.jobs = paparazzi_video_jobs
        root = Path(self.tmp.name)
        self.meta = root / "meta.json"
        self.posted = root / "reels_posted.json"
        for name, value in (
            ("STATE_PATH", str(root / "jobs.json")),
            ("META_INPUT", str(self.meta)),
            ("REELS_POSTED_PATH", str(self.posted)),
        ):
            patcher = mock.patch.object(paparazzi_video_jobs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(
            os.environ,
            {"PAPARAZZI_VIDEO_ONLY_ENABLED": "true", "PAPARAZZI_VIDEO_MAX_AGE_HOURS": "24", "SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": ""},
        )
        env.start()
        self.addCleanup(env.stop)

    def _write_meta(self, items):
        self.meta.write_text(json.dumps(items), encoding="utf-8")

    def test_ingest_only_recent_video_notes_not_yet_posted(self):
        now = int(time.time())
        fresh = {**_paparazzi("v", video=True, score=3), "queued_at": now - 60}
        old = {**_paparazzi("old", video=True), "queued_at": now - 3 * 86400}
        image = {**_paparazzi("img"), "queued_at": now}
        done = {**_paparazzi("done", video=True), "queued_at": now}
        from utils.paparazzi_reels import reel_dedup_key

        self.posted.write_text(json.dumps({"posted": {reel_dedup_key(done): {}}}), encoding="utf-8")
        self._write_meta([fresh, old, image, done])

        self.assertEqual({"new": 1}, self.jobs.ingest(now=now))
        self.assertEqual({"new": 0}, self.jobs.ingest(now=now))
        pending = self.jobs.pending_jobs(5)
        self.assertEqual([reel_dedup_key(fresh)], [job_id for job_id, _ in pending])
        self.assertEqual(fresh["video_url"], pending[0][1]["noticia"]["video_url"])

    def test_respects_operational_cutoff_and_flag(self):
        now = int(time.time())
        self._write_meta([{**_paparazzi("v", video=True), "queued_at": now - 60}])
        with mock.patch.dict(os.environ, {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": str(now)}):
            self.assertEqual({"new": 0}, self.jobs.ingest(now=now))
        with mock.patch.dict(os.environ, {"PAPARAZZI_VIDEO_ONLY_ENABLED": "false"}):
            self.assertEqual({"new": 0}, self.jobs.ingest(now=now))

    def test_stale_pending_expires(self):
        now = int(time.time())
        self._write_meta([{**_paparazzi("v", video=True), "queued_at": now - 60}])
        self.jobs.ingest(now=now)
        self.assertEqual(1, self.jobs.expire_stale(now=now + 2 * 86400))
        self.assertEqual([], self.jobs.pending_jobs(5))


class RunPaparazziVideosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from meta import run_paparazzi_videos
        from utils import paparazzi_video_jobs

        self.stage = run_paparazzi_videos
        self.jobs_path = Path(self.tmp.name) / "jobs.json"
        patcher = mock.patch.object(paparazzi_video_jobs, "STATE_PATH", str(self.jobs_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job = {"noticia": _paparazzi("v", video=True), "status": "pending", "attempts": 0, "queued_at": 1}
        self.jobs_path.write_text(json.dumps({"jobs": {"reel:1": self.job}}), encoding="utf-8")

    def _job(self):
        return json.loads(self.jobs_path.read_text(encoding="utf-8"))["jobs"]["reel:1"]

    def test_publishes_reel_and_records_dedup(self):
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        ok = OperationResult(StageStatus.SUCCESS, external_id="ig-1")
        with mock.patch.object(self.stage, "render_reel_item", return_value=({"video_url": "u"}, "k")), mock.patch.object(
            self.stage, "post_reel_video_to_instagram", return_value=ok
        ), mock.patch.object(self.stage, "publish_facebook_reel", return_value=(True, "fb-1")), mock.patch.object(
            self.stage, "_record_evidence"
        ) as evidence:
            outcome = self.stage._process("reel:1", self.job, instagram=True, facebook=True)
        self.assertEqual("completed", outcome)
        job = self._job()
        self.assertEqual(("completed", "ig-1", "fb-1"), (job["status"], job["instagram_id"], job["facebook_id"]))
        evidence.assert_called_once()

    def test_render_failure_retries_without_publishing_anything_else(self):
        with mock.patch.object(self.stage, "render_reel_item", return_value=None), mock.patch.object(
            self.stage, "post_reel_video_to_instagram"
        ) as post:
            outcome = self.stage._process("reel:1", self.job, instagram=True, facebook=True)
        self.assertEqual("failed", outcome)
        post.assert_not_called()
        job = self._job()
        self.assertEqual(("pending", "reel_render_unavailable", 1), (job["status"], job["reason"], job["attempts"]))

    def test_rate_limit_defers(self):
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        limited = OperationResult(StageStatus.DEGRADED, error_type="rate_limit", retryable=True)
        with mock.patch.object(self.stage, "render_reel_item", return_value=({"video_url": "u"}, "k")), mock.patch.object(
            self.stage, "post_reel_video_to_instagram", return_value=limited
        ), mock.patch.object(self.stage, "delete_reel_upload") as cleanup:
            outcome = self.stage._process("reel:1", self.job, instagram=True, facebook=True)
        self.assertEqual("deferred", outcome)
        cleanup.assert_called_once_with("k")
        self.assertEqual("pending", self._job()["status"])

    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {"PAPARAZZI_VIDEO_ONLY_ENABLED": "false"}):
            result = self.stage.main()
        self.assertEqual({"disabled": True}, result.details)


if __name__ == "__main__":
    unittest.main()
