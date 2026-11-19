"""Compuerta de valor de los Reels locales, Último momento y Datos útiles (REEL_VALUE_GATE_ENABLED)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import reel_editorial_score as rs


def _reply(score: int, motivo: str = "ok"):
    return lambda **_kw: json.dumps({"score": score, "motivo": motivo})


class ScoreValueTests(unittest.TestCase):
    def test_disabled_approves_without_calling_ai(self):
        ai = mock.Mock()
        with mock.patch.dict(os.environ, {"REEL_VALUE_GATE_ENABLED": "false"}):
            decision = rs.score_value("um", title="t", section="policiales", text="x", completion=ai)
        self.assertEqual(("disabled", True), (decision.status, decision.allowed))
        ai.assert_not_called()

    def test_threshold_per_kind(self):
        with mock.patch.dict(os.environ, {"REEL_VALUE_GATE_ENABLED": "true"}):
            self.assertTrue(rs.score_value("um", title="t", section="s", text="x", completion=_reply(65)).allowed)
            # Locales: 70 (calibrado con los Reels reales del 18-19/11).
            self.assertFalse(rs.score_value("local_video", title="t", section="s", text="x", completion=_reply(65)).allowed)
            self.assertTrue(rs.score_value("local_video", title="t", section="s", text="x", completion=_reply(75)).allowed)
        with mock.patch.dict(os.environ, {"REEL_VALUE_GATE_ENABLED": "true", "REEL_VALUE_MIN_SCORE_DU": "90"}):
            self.assertFalse(rs.score_value("du", title="t", section="s", text="x", completion=_reply(85)).allowed)

    def test_ai_failure_is_unavailable_and_not_approved(self):
        def broken(**_kw):
            raise RuntimeError("caída")

        with mock.patch.dict(os.environ, {"REEL_VALUE_GATE_ENABLED": "true"}):
            decision = rs.score_value("du", title="t", section="s", text="x", completion=broken)
        self.assertEqual(("unavailable", False), (decision.status, decision.allowed))

    def test_prompt_carries_kind_criteria_and_video_channel(self):
        seen = {}

        def spy(**kw):
            seen.update(kw)
            return json.dumps({"score": 80, "motivo": "ok"})

        with mock.patch.dict(os.environ, {"REEL_VALUE_GATE_ENABLED": "true"}):
            rs.score_value("local_video", title="Acto", section="politica", text="x", video_source="Medios Provincia", completion=spy)
        system, user = seen["messages"][0]["content"], seen["messages"][1]["content"]
        self.assertIn("institucional", system)
        self.assertIn("Canal del video: Medios Provincia", user)


class LocalReelGateTests(unittest.TestCase):
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
        noticia = {"titulo": "Quintela recordó un discurso", "seccion": "Politica", "source": "tiempopopular_locales",
                   "video_url": "https://www.youtube.com/watch?v=abc", "video_credit": "Ricardo Quintela",
                   "reel_channels": ["instagram", "facebook"]}
        self.job = {"noticia": noticia, "status": "pending", "attempts": 0, "queued_at": 1}
        self.jobs_path.write_text(json.dumps({"jobs": {"reel:1": self.job}}), encoding="utf-8")

    def _state(self):
        return json.loads(self.jobs_path.read_text(encoding="utf-8"))["jobs"]["reel:1"]

    def test_low_value_local_reel_expires_and_goes_as_image(self):
        low = rs.ReelScoreDecision(False, "rejected", 35, "institucional")
        with mock.patch.object(self.stage, "score_value", return_value=low), mock.patch.object(self.stage, "render_reel_item") as render:
            self.assertEqual("dropped", self.stage._process("reel:1", self.job, instagram=True, facebook=True))
        render.assert_not_called()
        self.assertEqual(("expired", "low_value", 35), (self._state()["status"], self._state()["reason"], self._state()["value_score"]))

    def test_ai_down_keeps_job_pending(self):
        down = rs.ReelScoreDecision(False, "unavailable", reason="ai_failed")
        with mock.patch.object(self.stage, "score_value", return_value=down), mock.patch.object(self.stage, "render_reel_item") as render:
            self.assertEqual("skipped", self.stage._process("reel:1", self.job, instagram=True, facebook=True))
        render.assert_not_called()
        self.assertEqual("pending", self._state()["status"])


class FormatReelGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rejected_um_is_marked_and_not_scripted(self):
        from meta import run_format_reels as stage
        from utils import format_reels as fr
        from utils import nightly_newscast as nn

        note = fr.Note(url="https://lavozriojana.com/noticias/a", title="Policía advierte", category="policiales", localities=[],
                       published_at=0, source="nuevarioja_policiales")
        cand = nn.Candidate(id="n1", title="Policía advierte por agresiones", section="policiales", source="x", web_url=note.url,
                            published_at=0, body="La Policía advirtió.")
        low = rs.ReelScoreDecision(False, "rejected", 35, "comunicado")
        with mock.patch.object(stage, "score_value", return_value=low):
            self.assertFalse(stage._worth_it("um", note, cand))
        item = fr.load_state()["items"][f"um:{note.url}"]
        self.assertEqual("rejected", item["status"])
        self.assertIn("poco valor (35)", item["reason"])

    def test_ai_down_is_not_marked(self):
        from meta import run_format_reels as stage
        from utils import format_reels as fr
        from utils import nightly_newscast as nn

        note = fr.Note(url="https://lavozriojana.com/noticias/b", title="t", category="sociedad", localities=[], published_at=0, source="x")
        cand = nn.Candidate(id="n1", title="t", section="sociedad", source="x", web_url=note.url, published_at=0, body="b")
        with mock.patch.object(stage, "score_value", return_value=rs.ReelScoreDecision(False, "unavailable")):
            self.assertFalse(stage._worth_it("du", note, cand))
        self.assertNotIn(f"du:{note.url}", fr.load_state().get("items", {}))


if __name__ == "__main__":
    unittest.main()
