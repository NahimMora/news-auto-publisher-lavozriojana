from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from meta import run_ig
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class BootstrapQueueSelectionTests(unittest.TestCase):
    """select_publish_batch.py decide qué se publica (``selected_for_publish``,
    ver docs/DECISIONS.md) — ya no hay gate de categoría ni cupo reservado por
    fuente acá; ``_bootstrap_queue`` sólo respeta esa marca y "suppressed"
    (duplicado técnico real, la única protección del router que sigue
    aplicando)."""

    def _run_bootstrap(self, noticias):
        with patch.object(run_ig, "load_json", return_value=noticias), patch.object(
            run_ig, "manual_automatic_candidates", return_value=[]
        ), patch.object(run_ig, "enqueue") as enqueue_mock:
            result = run_ig._bootstrap_queue()
        return result, enqueue_mock

    def test_selected_for_publish_is_enqueued(self):
        noticia = {"titulo": "x", "web_url": "https://x", "selected_for_publish": True}
        (included, omitted, missing, *_rest), enqueue_mock = self._run_bootstrap([noticia])
        self.assertEqual(1, included)
        self.assertEqual(0, omitted)
        enqueue_mock.assert_called_once()

    def test_not_selected_is_omitted(self):
        noticia = {"titulo": "x", "web_url": "https://x"}
        (included, omitted, missing, *_rest), enqueue_mock = self._run_bootstrap([noticia])
        self.assertEqual(0, included)
        self.assertEqual(1, omitted)
        enqueue_mock.assert_not_called()

    def test_suppressed_technical_duplicate_is_omitted_even_if_selected(self):
        noticia = {
            "titulo": "x",
            "web_url": "https://x",
            "selected_for_publish": True,
            "route_by_channel": {"instagram": "suppressed"},
        }
        (included, omitted, missing, *_rest), enqueue_mock = self._run_bootstrap([noticia])
        self.assertEqual(0, included)
        self.assertEqual(1, omitted)
        enqueue_mock.assert_not_called()

    def test_missing_web_url_is_omitted_without_manual_override(self):
        noticia = {"titulo": "x", "selected_for_publish": True}
        (included, omitted, missing, *_rest), enqueue_mock = self._run_bootstrap([noticia])
        self.assertEqual(0, included)
        self.assertEqual(1, missing)
        enqueue_mock.assert_not_called()

    def test_local_and_national_sources_both_need_selected_for_publish(self):
        """El balde ya no distingue paparazzi/infobae vs local acá — ambos
        pasan por la misma marca, la distinción de baldes vive en
        utils/publish_selection.py."""
        paparazzi = {
            "titulo": "p", "web_url": "https://p", "source": "paparazzi",
            "selected_for_publish": True,
        }
        local = {
            "titulo": "l", "web_url": "https://l", "source": "tiempopopular_policiales",
            "selected_for_publish": True,
        }
        (included, *_rest), enqueue_mock = self._run_bootstrap([paparazzi, local])
        self.assertEqual(2, included)
        self.assertEqual(2, enqueue_mock.call_count)


class ManualOverrideBudgetTests(unittest.TestCase):
    """Un backlog grande de promociones manuales (operador aprobó candidatas
    mientras estaban bloqueadas por el gate viejo) no debe entrar todo de una
    sola corrida — se paceó a IG_MANUAL_OVERRIDE_MAX_PER_RUN por vez."""

    def test_restored_from_candidate_store_respects_budget(self):
        from meta import run_ig

        candidates = [
            {
                "identity": f"link:c{i}",
                "noticia": {"dedup_key": f"link:c{i}", "titulo": f"c{i}", "web_url": f"https://x/{i}"},
            }
            for i in range(10)
        ]
        with patch.dict(
            os.environ, {"IG_MANUAL_OVERRIDE_MAX_PER_RUN": "3"}, clear=False
        ), patch.object(run_ig, "load_json", return_value=[]), patch.object(
            run_ig, "manual_automatic_candidates", return_value=candidates
        ), patch.object(run_ig, "enqueue") as enqueue:
            (
                included,
                omitted,
                missing,
                manual,
                manual_without_web,
                restored,
            ) = run_ig._bootstrap_queue()

        self.assertEqual(3, included)
        self.assertEqual(3, manual)
        self.assertEqual(3, restored)
        self.assertEqual(3, enqueue.call_count)

    def test_zero_budget_disables_manual_override_restoration(self):
        from meta import run_ig

        candidates = [
            {"identity": "link:c0", "noticia": {"dedup_key": "link:c0", "titulo": "c0"}}
        ]
        with patch.dict(
            os.environ, {"IG_MANUAL_OVERRIDE_MAX_PER_RUN": "0"}, clear=False
        ), patch.object(run_ig, "load_json", return_value=[]), patch.object(
            run_ig, "manual_automatic_candidates", return_value=candidates
        ), patch.object(run_ig, "enqueue") as enqueue:
            result = run_ig._bootstrap_queue()

        self.assertEqual((0, 0, 0, 0, 0, 0), result)
        enqueue.assert_not_called()


class DispatchBySourceTests(unittest.TestCase):
    """El único trato distinto que sobrevive para paparazzi en run_ig.py es
    CÓMO se publica (carrusel imagen+video) — no CUÁNTO ni SI se publica."""

    def test_paparazzi_uses_carousel_others_use_standard_post(self):
        general = {"dedup_key": "link:g0", "titulo": "g", "source": "nuevarioja"}
        paparazzi = {"dedup_key": "link:p0", "titulo": "p", "source": "paparazzi"}
        operations = {
            "link:g0": OperationResult(StageStatus.SUCCESS, external_id="g0"),
            "link:p0": OperationResult(StageStatus.SUCCESS, external_id="p0"),
        }

        with patch.object(run_ig, "IG_ACCOUNT_ID", "ig"), patch.object(
            run_ig, "IG_ACCESS_TOKEN", "token"
        ), patch.dict(
            os.environ,
            {"IG_PUBLISH_ENABLED": "true", "IG_MAX_PER_RUN": "10"},
            clear=False,
        ), patch.object(
            run_ig, "rate_limit_until", return_value=0
        ), patch.object(
            run_ig, "recover_ambiguous_processing", return_value=0
        ), patch.object(
            run_ig, "_bootstrap_queue", return_value=(2, 0, 0, 0, 0, 0)
        ), patch.object(
            run_ig, "_sync_posted_state", return_value=0
        ), patch.object(
            run_ig, "get_pending", return_value=[general, paparazzi]
        ), patch.object(
            run_ig, "claim", return_value=True
        ), patch.object(
            run_ig,
            "post_to_instagram_detailed",
            side_effect=lambda noticia: operations[noticia["dedup_key"]],
        ) as standard_publish, patch.object(
            run_ig,
            "post_paparazzi_carousel_to_instagram",
            side_effect=lambda noticia: operations[noticia["dedup_key"]],
        ) as paparazzi_publish, patch.object(
            run_ig, "mark_done"
        ), patch.object(
            run_ig, "compact_queue"
        ):
            result = run_ig.main()

        self.assertEqual(2, result.succeeded)
        standard_publish.assert_called_once_with(general)
        paparazzi_publish.assert_called_once_with(paparazzi)


if __name__ == "__main__":
    unittest.main()
