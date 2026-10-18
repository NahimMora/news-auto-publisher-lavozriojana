"""Guardia de ubicación: captions y hashtags no ubican en La Rioja hechos
cuya fuente no la menciona (videos virales, nacionales, internacionales)."""
import json
import os
import unittest
from unittest import mock

from openIA.caption_generator import generate_caption, invented_riojan_reference
from utils.social_caption import _hashtags


def _response(title: str, body: str) -> str:
    return json.dumps({"titulo_instagram": title, "texto_instagram": body, "cta": "¿Qué opinás?"})


class InventedRiojanReferenceTests(unittest.TestCase):
    def test_flags_riojan_terms_missing_from_source(self):
        self.assertEqual(
            invented_riojan_reference("Newborn so relaxed it went viral", "El bebé riojano que se hizo viral"),
            {"riojano"},
        )

    def test_source_with_riojan_link_is_never_flagged(self):
        self.assertEqual(invented_riojan_reference("Robo en Chilecito", "Robo en Chilecito, La Rioja"), set())

    def test_brand_name_is_not_a_location(self):
        self.assertEqual(invented_riojan_reference("Video viral", "Seguí a La Voz Riojana"), set())


class CaptionLocationGuardTests(unittest.TestCase):
    NOTICIA = {"titulo": "Un recién nacido se volvió viral por su calma", "parrafos": ["Video viral de un parto."], "seccion": "sociedad"}

    def _generate(self, responses):
        env = {"GEMINI_API_KEY": "test", "GEMINI_RETRY_COUNT": "3", "GEMINI_RETRY_SLEEP": "0"}
        with mock.patch.dict(os.environ, env), mock.patch(
            "utils.ai_client.chat_completion", side_effect=list(responses)
        ) as chat:
            return generate_caption(dict(self.NOTICIA)), chat

    def test_retries_with_correction_when_model_localizes(self):
        result, chat = self._generate(
            [
                _response("El bebé riojano que se hizo viral", "📢🗞️ EL BEBÉ RIOJANO 👇"),
                _response("Un bebé que se toma la vida con calma", "📢🗞️ UN BEBÉ TRANQUILO 👇"),
            ]
        )
        self.assertEqual(result["titulo_instagram"], "Un bebé que se toma la vida con calma")
        self.assertFalse(result["caption_fallback_used"])
        self.assertEqual(chat.call_count, 2)
        second_user = chat.call_args_list[1].kwargs["messages"][1]["content"]
        self.assertIn("CORRECCIÓN", second_user)

    def test_falls_back_to_source_when_model_insists(self):
        result, chat = self._generate([_response("Bebé riojano", "📌 Impacto para los riojanos")] * 3)
        self.assertTrue(result["caption_fallback_used"])
        self.assertEqual(result["caption_fallback_reason"], "riojan_reference_invented")
        self.assertNotIn("riojan", result["titulo_instagram"].lower())
        self.assertEqual(chat.call_count, 3)

    def test_local_source_keeps_riojan_reference(self):
        noticia = {"titulo": "Robo en Chilecito", "parrafos": ["Ocurrió en Chilecito."], "seccion": "policiales"}
        env = {"GEMINI_API_KEY": "test", "GEMINI_RETRY_SLEEP": "0"}
        with mock.patch.dict(os.environ, env), mock.patch(
            "utils.ai_client.chat_completion", return_value=_response("Robo en Chilecito, La Rioja", "🚨 ROBO 👇")
        ) as chat:
            result = generate_caption(noticia)
        self.assertEqual(result["titulo_instagram"], "Robo en Chilecito, La Rioja")
        self.assertEqual(chat.call_count, 1)


class HashtagLocationTests(unittest.TestCase):
    def test_item_without_riojan_link_gets_neutral_tags(self):
        tags = _hashtags({"titulo": "Un bebé que se toma la vida con calma", "seccion": "sociedad"})
        self.assertNotIn("Rioja", tags.replace("#LaVozRiojana", ""))
        self.assertIn("#LaVozRiojana", tags)

    def test_riojan_text_keeps_local_tags(self):
        self.assertIn("#LaRioja", _hashtags({"titulo": "Robo en Chilecito", "seccion": "policiales"}))

    def test_local_outlet_keeps_local_tags_without_locality_in_text(self):
        tags = _hashtags({"titulo": "Corte de luz programado", "seccion": "sociedad", "source": "nuevarioja_sociedad"})
        self.assertIn("#LaRioja", tags)

    def test_local_outlet_international_section_is_neutral(self):
        tags = _hashtags({"titulo": "Protestas en París", "seccion": "sociedad", "source": "nuevarioja_internacionales"})
        self.assertNotIn("#LaRioja ", f"{tags} ")


if __name__ == "__main__":
    unittest.main()
