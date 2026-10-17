"""Bajada con mayúsculas, tope diario de IG y horario silencioso de imágenes."""
from __future__ import annotations

import os
import time
import unittest
from unittest import mock

from openIA.caption_generator import restore_deck_casing


class DeckCasingTests(unittest.TestCase):
    def test_restores_proper_nouns_from_source(self):
        reference = (
            "Barbie Simons recordó su mudanza. La periodista fue invitada al "
            "programa de Juana Viale y habló con Luis Novaresio."
        )
        self.assertEqual(
            "La periodista fue invitada al programa de Juana Viale",
            restore_deck_casing("la periodista fue invitada al programa de juana viale", reference),
        )

    def test_does_not_capitalize_common_words_at_sentence_start(self):
        reference = "El equipo de Vichigasta ganó. El global fue 3 a 1."
        self.assertEqual(
            "El equipo de Vichigasta se impuso en el global",
            restore_deck_casing("el equipo de vichigasta se impuso en el global", reference),
        )

    def test_ignores_uppercase_titles_and_articles_of_proper_nouns(self):
        # Caso real: el caption viejo trae "📢🗞️ TITULO EN MAYÚSCULAS" y la
        # fuente dice "en La Rioja"; ni "DE" ni "La" deben contagiar la bajada.
        reference = (
            "📢🗞️ EDELAR EJECUTÓ OBRAS DE MANTENIMIENTO EN LA PROVINCIA\n"
            "Los trabajos se hicieron en La Rioja. La empresa optimiza la red."
        )
        self.assertEqual(
            "La empresa busca optimizar la calidad del servicio en la provincia",
            restore_deck_casing(
                "la empresa busca optimizar la calidad del servicio en la provincia", reference
            ),
        )

    def test_render_reference_uses_web_version_when_queue_has_no_paragraphs(self):
        from layout.image_generator import _deck_for_render

        article = {
            "titulo": "Barbie Simons recordó su mudanza",
            "deck": "la periodista fue invitada al programa de juana viale",
            "web_editorial": {"lead": "La periodista estuvo en el programa de Juana Viale."},
        }
        self.assertEqual(
            "La periodista fue invitada al programa de Juana Viale",
            _deck_for_render(article),
        )

    def test_keeps_deck_that_already_has_casing(self):
        self.assertEqual("Desde Chilecito", restore_deck_casing("Desde Chilecito", "chilecito"))

    def test_empty_deck(self):
        self.assertEqual("", restore_deck_casing("", "Texto"))

    def test_render_props_use_restored_deck(self):
        from layout.image_generator import _deck_for_render

        article = {
            "titulo": "Volcó en la avenida Ortiz de Ocampo",
            "parrafos": ["El conductor circulaba por la avenida Ortiz de Ocampo."],
            "deck": "el conductor perdió el control en ortiz de ocampo",
        }
        self.assertEqual(
            "El conductor perdió el control en Ortiz de Ocampo",
            _deck_for_render(article),
        )


class InstagramDailyLimitTests(unittest.TestCase):
    def test_daily_publishing_limit_is_rate_limit(self):
        from meta import ig_client

        data = {"error": {"code": 9, "error_subcode": 2207042, "type": "OAuthException"}}
        self.assertTrue(ig_client._is_rate_limit_error(data, 400))

    def test_other_rejections_are_not_rate_limit(self):
        from meta import ig_client

        data = {"error": {"code": 100, "error_subcode": 2207026}}
        self.assertFalse(ig_client._is_rate_limit_error(data, 400))

    def test_publish_rejection_by_daily_limit_returns_to_pending(self):
        from meta import ig_client

        response = mock.Mock(status_code=400)
        response.json.return_value = {"error": {"code": 9, "error_subcode": 2207042}}
        with mock.patch.object(ig_client, "_set_rate_limit_backoff", return_value=123):
            result = ig_client._error_result(response, outcome="unknown")
        self.assertEqual("rate_limit", result.error_type)
        self.assertTrue(result.retryable)
        self.assertEqual(123, result.next_retry_at)


class QuietHoursTests(unittest.TestCase):
    def _split(self, items, value, hour):
        from meta import run_ig

        fake = time.struct_time((2026, 10, 4, hour, 0, 0, 6, 277, -1))
        with mock.patch.dict(os.environ, {"IG_STATIC_QUIET_HOURS": value}), mock.patch.object(
            run_ig.time, "localtime", return_value=fake
        ):
            return run_ig._split_quiet_hours(items)

    def setUp(self):
        self.static = {"titulo": "imagen"}
        self.video = {"titulo": "reel", "video_url": "https://x/v.mp4"}

    def test_off_by_default(self):
        self.assertEqual(([self.static, self.video], 0), self._split([self.static, self.video], "", 3))

    def test_defers_static_only_inside_window(self):
        self.assertEqual(([self.video], 1), self._split([self.static, self.video], "0-7", 3))

    def test_outside_window_keeps_everything(self):
        self.assertEqual(([self.static], 0), self._split([self.static], "0-7", 7))

    def test_window_crossing_midnight(self):
        self.assertEqual(1, self._split([self.static], "23-6", 23)[1])
        self.assertEqual(1, self._split([self.static], "23-6", 2)[1])
        self.assertEqual(0, self._split([self.static], "23-6", 12)[1])

    def test_invalid_value_is_off(self):
        self.assertEqual(0, self._split([self.static], "madrugada", 3)[1])
        self.assertEqual(0, self._split([self.static], "5-5", 5)[1])

    def test_all_deferred_is_no_work_not_degraded(self):
        from meta import run_ig
        from utils.stage_result import StageStatus

        env = {"IG_PUBLISH_ENABLED": "true", "IG_STATIC_QUIET_HOURS": "0-7"}
        fake = time.struct_time((2026, 10, 4, 3, 0, 0, 6, 277, -1))
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(run_ig, "IG_ACCOUNT_ID", "1"), \
                mock.patch.object(run_ig, "IG_ACCESS_TOKEN", "t"), \
                mock.patch.object(run_ig, "rate_limit_until", return_value=0), \
                mock.patch.object(run_ig, "recover_ambiguous_processing", return_value=0), \
                mock.patch.object(run_ig, "_bootstrap_queue", return_value=(0, 0, 0, 0, 0, 0)), \
                mock.patch.object(run_ig, "_sync_posted_state", return_value=0), \
                mock.patch.object(run_ig, "get_pending", return_value=[dict(self.static)]), \
                mock.patch.object(run_ig, "claim") as claim, \
                mock.patch.object(run_ig.time, "localtime", return_value=fake):
            result = run_ig.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(1, result.details["quiet_hours_deferred"])
        claim.assert_not_called()


if __name__ == "__main__":
    unittest.main()
