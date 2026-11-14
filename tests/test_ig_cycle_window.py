"""Tope por ciclo de Instagram y arranque único del render server (13/11/2026)."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from meta import run_ig
from utils import deployment, remotion_renderer
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def news(key):
    return {"titulo": key, "dedup_key": f"link:{key}", "web_url": f"https://lavozriojana.com/noticias/{key}"}


class InstagramCycleWindowTests(unittest.TestCase):
    def _run(self, candidates, *, limit, superseded_keys=()):
        def fake_superseded(selected, platform):
            kept = [n for n in selected if n["dedup_key"] not in superseded_keys]
            return kept, len(selected) - len(kept)

        with patch.object(run_ig, "IG_ACCOUNT_ID", "ig"), patch.object(
            run_ig, "IG_ACCESS_TOKEN", "token"
        ), patch.dict(
            os.environ, {"IG_PUBLISH_ENABLED": "true", "IG_MAX_PER_RUN": str(limit)}, clear=False
        ), patch.object(run_ig, "rate_limit_until", return_value=0), patch.object(
            run_ig, "recover_ambiguous_processing", return_value=0
        ), patch.object(
            run_ig, "_bootstrap_queue", return_value=(len(candidates), 0, 0, 0, 0, 0)
        ), patch.object(run_ig, "_sync_posted_state", return_value=0), patch.object(
            run_ig, "get_pending", return_value=candidates
        ), patch.object(
            run_ig, "_select_with_local_fill", return_value=list(candidates)
        ) as select, patch.object(
            run_ig, "drop_superseded", side_effect=fake_superseded
        ), patch.object(
            run_ig, "drop_already_posted", side_effect=lambda s, p: (s, 0)
        ), patch.object(run_ig, "claim", return_value=True), patch.object(
            run_ig,
            "post_to_instagram_detailed",
            side_effect=lambda n: OperationResult(StageStatus.SUCCESS, external_id=f"ig-{n['titulo']}"),
        ) as post, patch.object(run_ig, "mark_done"), patch.object(
            run_ig, "mark_pending"
        ), patch.object(run_ig, "mark_dead_letter"), patch.object(run_ig, "compact_queue"):
            result = run_ig.main()
        return result, select, post

    def test_descartadas_no_ocupan_lugares_del_ciclo(self):
        candidates = [news(k) for k in "abcdef"]
        result, select, post = self._run(candidates, limit=2, superseded_keys={"link:a", "link:b", "link:c"})

        select.assert_called_once_with(2 * run_ig.SELECTION_WINDOW_FACTOR)
        published = [call.args[0]["titulo"] for call in post.call_args_list]
        self.assertEqual(["d", "e"], published)
        self.assertEqual(2, result.succeeded)

    def test_el_tope_se_respeta_aunque_la_ventana_sea_mayor(self):
        candidates = [news(k) for k in "abcdef"]
        _, _, post = self._run(candidates, limit=3)
        self.assertEqual(3, post.call_count)


class InstagramCycleCapTests(unittest.TestCase):
    def test_default_sigue_en_ocho(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIPELINE_IG_MAX_PER_CYCLE", None)
            self.assertEqual(8, deployment.instagram_max_per_cycle())

    def test_tope_configurable_y_acotado(self):
        for raw, expected in (("12", 12), ("0", 1), ("99", 20), ("x", 8)):
            with patch.dict(os.environ, {"PIPELINE_IG_MAX_PER_CYCLE": raw}, clear=False):
                self.assertEqual(expected, deployment.instagram_max_per_cycle())


class RenderServerStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.info = os.path.join(self.tmp.name, ".render-server.json")
        self.marker = os.path.join(self.tmp.name, ".render-server.starting")
        for target, value in (
            ("RENDER_SERVER_INFO_PATH", self.info),
            ("RENDER_SERVER_STARTING_PATH", self.marker),
            ("RENDER_SERVER_STARTUP_TIMEOUT", 0.5),
            ("RENDER_SERVER_DISABLED", False),
        ):
            patcher = patch.object(remotion_renderer, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(remotion_renderer.os.path, "isfile", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_lanza_un_segundo_servidor_si_otro_esta_arrancando(self):
        with open(self.marker, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": __import__("time").time()}, handle)
        with patch.object(remotion_renderer.subprocess, "Popen") as popen:
            self.assertIsNone(remotion_renderer.ensure_render_server())
        popen.assert_not_called()

    def test_marca_vieja_o_proceso_muerto_permite_relanzar(self):
        with open(self.marker, "w", encoding="utf-8") as handle:
            json.dump({"pid": 999999, "started_at": 0}, handle)
        fake = MagicMock(pid=4321)
        with patch.object(remotion_renderer.subprocess, "Popen", return_value=fake) as popen:
            remotion_renderer.ensure_render_server()
        popen.assert_called_once()
        env = popen.call_args.kwargs["env"]
        self.assertIn("RENDER_SERVER_IDLE_MS", env)
        with open(self.marker, encoding="utf-8") as handle:
            self.assertEqual(4321, json.load(handle)["pid"])

    def test_servidor_sano_limpia_la_marca(self):
        with open(self.info, "w", encoding="utf-8") as handle:
            json.dump({"pid": 1, "port": 5555}, handle)
        with open(self.marker, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": 0}, handle)
        with patch.object(remotion_renderer, "_server_health_check", side_effect=[False, True]):
            self.assertEqual(5555, remotion_renderer.ensure_render_server())
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    unittest.main()
