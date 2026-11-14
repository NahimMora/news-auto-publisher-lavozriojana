"""Controles de costo de IA: medición, paparazzi heurístico, nacionales, caption
bajo demanda y llamada única. Sin red ni IA reales."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from utils import cost_controls as cc


class _Data(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class PaparazziTests(_Data):
    def test_score_rewards_top_figures_and_strong_events(self):
        strong = {"titulo": "Wanda Nara confirmó su separación de L-Gante", "parrafos": ["La mediática habló en televisión."]}
        filler = {"titulo": "Horóscopo: qué le depara a cada signo", "parrafos": ["Las predicciones de la semana."]}
        minor = {"titulo": "Una participante de un reality mostró su nuevo corte", "parrafos": ["Sin más datos."]}
        self.assertGreaterEqual(cc.paparazzi_score(strong), 8)
        self.assertLessEqual(cc.paparazzi_score(filler), 2)
        self.assertLess(cc.paparazzi_score(minor), 5)

    def test_gate_threshold_and_daily_cap(self):
        good = {"titulo": "Murió un reconocido actor: lo despidió Susana Giménez", "parrafos": []}
        with mock.patch.dict(os.environ, {"PAPARAZZI_HEURISTIC_MIN": "5", "PAPARAZZI_DAILY_MAX": "2"}):
            self.assertFalse(cc.paparazzi_gate({"titulo": "Horóscopo semanal", "parrafos": []})[0])
            self.assertTrue(cc.paparazzi_gate(dict(good))[0])
            self.assertTrue(cc.paparazzi_gate(dict(good))[0])
            passed, reason, _ = cc.paparazzi_gate(dict(good))
        self.assertFalse(passed)
        self.assertEqual(reason, "paparazzi_daily_cap")


class NationalTests(unittest.TestCase):
    def test_local_sources_and_riojan_text_are_never_national(self):
        self.assertFalse(cc.is_national({"source": "fenix_locales", "titulo": "Explosión en Lanús"}))
        self.assertFalse(cc.is_national({"source": "paparazzi", "titulo": "Wanda Nara"}))
        self.assertFalse(cc.is_national({"source": "nuevarioja_sociedad", "titulo": "Corte de luz en La Rioja", "parrafos": []}))
        self.assertFalse(cc.is_national({"source": "nuevarioja_sociedad", "titulo": "Granizo", "parrafos": ["Cayó granizo en Chilecito."]}))

    def test_national_without_riojan_signal(self):
        self.assertTrue(cc.is_national({"source": "nuevarioja_sociedad", "titulo": "Explosión de gas en Lanús deja 20 heridos",
                                        "parrafos": ["Ocurrió en el conurbano bonaerense."], "seccion": "sociedad"}))
        self.assertTrue(cc.is_national({"source": "infobae_policiales", "titulo": "Detuvieron a un hombre en Rosario", "parrafos": []}))


class LazyCaptionTests(_Data):
    def test_generated_once_and_cached(self):
        calls = []

        def gen(noticia):
            calls.append(noticia["titulo"])
            return {"titulo_instagram": "T", "texto_instagram": "Texto del caption", "cta": "Seguinos", "caption_fallback_used": False}

        a = {"titulo": "Nota", "canonical_url": "https://src/1", "caption_deferred": True}
        b = {"titulo": "Nota", "canonical_url": "https://src/1", "caption_deferred": True}
        cc.ensure_caption(a, generator=gen)
        cc.ensure_caption(b, generator=gen)
        self.assertEqual(len(calls), 1)
        self.assertEqual(b["texto_instagram"], "Texto del caption")

    def test_not_deferred_or_already_has_caption_is_untouched(self):
        gen = mock.Mock()
        cc.ensure_caption({"titulo": "x", "texto_instagram": "ya"}, generator=gen)
        cc.ensure_caption({"titulo": "x", "caption_deferred": True, "texto_instagram": "ya"}, generator=gen)
        gen.assert_not_called()

    def test_social_caption_uses_web_text_without_ai(self):
        from utils import social_caption

        noticia = {"titulo": "Nota", "caption_deferred": True}
        with mock.patch.object(social_caption, "_caption_from_web", return_value="Texto de la web"), \
                mock.patch.dict(os.environ, {"IG_CAPTION_FROM_WEB_ENABLED": "true"}), \
                mock.patch.object(cc, "ensure_caption") as ensure:
            text = social_caption.build_instagram_caption(noticia)
        ensure.assert_not_called()
        self.assertIn("Texto de la web", text)

    def test_social_caption_generates_when_web_text_missing(self):
        from utils import social_caption

        noticia = {"titulo": "Nota", "caption_deferred": True, "canonical_url": "https://src/2"}
        gen = {"titulo_instagram": "T", "texto_instagram": "Generado bajo demanda", "cta": ""}
        with mock.patch.object(social_caption, "_caption_from_web", return_value=""), \
                mock.patch("openIA.caption_generator.generate_caption", return_value=gen):
            text = social_caption.build_instagram_caption(noticia)
        self.assertIn("Generado bajo demanda", text)


class RewriteTests(_Data):
    def _note(self, **kw):
        base = {"titulo": "Detuvieron a un hombre por robar una moto en Chilecito", "parrafos": ["La Policía detuvo a un hombre en Chilecito."],
                "source": "nuevarioja_policiales", "canonical_url": "https://src/9"}
        base.update(kw)
        return base

    def test_single_call_replaces_title_class_and_score(self):
        from openIA import rewrite_news as rn

        answer = json.dumps({"titulo": "Cayó un ladrón de motos en Chilecito", "hashtag": rn.LOCALITY_HASHTAGS[0], "categoria": "policiales"})
        env = {"REWRITE_SINGLE_CALL_ENABLED": "true", "CAPTION_LAZY_ENABLED": "true", "LOCALITY_DECK_LAZY_ENABLED": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(rn, "chat_completion", return_value=answer) as chat, \
                mock.patch.object(rn, "clasificar_con_resultado") as classify, mock.patch.object(rn, "generate_caption") as caption:
            out = rn.rewrite_noticia(self._note())
        self.assertEqual(chat.call_count, 1)
        classify.assert_not_called()
        caption.assert_not_called()
        self.assertEqual(out["titulo"], "Cayó un ladrón de motos en Chilecito")
        self.assertEqual(out["seccion"], "Policiales")
        self.assertTrue(out["caption_deferred"])
        self.assertFalse(out["rewrite_fallback_used"])

    def test_single_call_invalid_answer_falls_back_to_separate_calls(self):
        from openIA import rewrite_news as rn
        from utils.classifier import ClassificationResult

        responses = ["{\"titulo\": \"\"}", "TITULO: Título de respaldo\nHASHTAG: NINGUNO"]
        env = {"REWRITE_SINGLE_CALL_ENABLED": "true", "CAPTION_LAZY_ENABLED": "true", "LOCALITY_DECK_LAZY_ENABLED": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(rn, "chat_completion", side_effect=responses), \
                mock.patch.object(rn, "clasificar_con_resultado", return_value=ClassificationResult("Policiales")) as classify:
            out = rn.rewrite_noticia(self._note())
        classify.assert_called_once()
        self.assertEqual(out["titulo"], "Título de respaldo")

    def test_video_notes_still_get_caption_eagerly(self):
        from openIA import rewrite_news as rn
        from utils.classifier import ClassificationResult

        env = {"REWRITE_SINGLE_CALL_ENABLED": "false", "CAPTION_LAZY_ENABLED": "true", "LOCALITY_DECK_LAZY_ENABLED": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(rn, "chat_completion", return_value="TITULO: T\nHASHTAG: NINGUNO"), \
                mock.patch.object(rn, "clasificar_con_resultado", return_value=ClassificationResult("Policiales")), \
                mock.patch.object(rn, "generate_caption", return_value={"texto_instagram": "c"}) as caption:
            out = rn.rewrite_noticia(self._note(video_url="https://cdn/v.mp4"))
        caption.assert_called_once()
        self.assertNotIn("caption_deferred", out)

    def test_paparazzi_combined_score(self):
        from openIA import rewrite_news as rn

        answer = json.dumps({"titulo": "Wanda habló de todo", "hashtag": "", "categoria": "Espectaculos", "relevancia": 8})
        env = {"REWRITE_SINGLE_CALL_ENABLED": "true", "CAPTION_LAZY_ENABLED": "true", "LOCALITY_DECK_LAZY_ENABLED": "true"}
        with mock.patch.dict(os.environ, env), mock.patch.object(rn, "chat_completion", return_value=answer), \
                mock.patch.object(rn, "score_relevance") as relevance:
            out = rn.rewrite_noticia(self._note(source="paparazzi", titulo="Wanda Nara habló"))
        relevance.assert_not_called()
        self.assertEqual(out["paparazzi_relevance_score"], 8)


class UsageTests(_Data):
    def test_caller_stage_is_inferred(self):
        from utils import ai_client

        def fake_caller():
            return ai_client._caller_stage()

        self.assertTrue(fake_caller().startswith("auto:"))

    def test_summary_prices_by_model(self):
        from editorial_context import instrumentation
        from utils import ai_usage

        path = os.path.join(self.tmp.name, "ctx.sqlite3")
        instrumentation.record_ai_call(stage="caption", model="gemini-3.1-flash-lite", tokens_in=1_000_000, tokens_out=100_000, path=path)
        instrumentation.record_ai_call(stage="tts", model="gemini-3.8-flash-tts", tokens_in=1000, tokens_out=2000, path=path)
        instrumentation.record_ai_call(stage="x", model="modelo-raro", tokens_in=10, tokens_out=10, path=path)
        report = ai_usage.summary(days=1, path=path)
        caption = next(e for e in report["by_stage"] if e["stage"] == "caption")
        self.assertAlmostEqual(caption["usd"], 0.25 + 0.15, places=4)
        self.assertIn("modelo-raro", report["unpriced_models"])
        self.assertIn("USD", ai_usage.render_text(report))


if __name__ == "__main__":
    unittest.main()
