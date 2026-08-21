from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from openIA.premium_package_generator import (
    PremiumGenerationError,
    generate_premium_package_json,
    normalize_generated_duplicate_context,
    validate_generated_payload,
)


def _gemini_mock(content: str) -> Mock:
    return Mock(return_value=content)


def _source_text() -> str:
    return (
        "El Gobierno de La Rioja anunció para los trabajadores estatales un aumento salarial "
        "del 15% y una acreditación extraordinaria de $50.000 en chachos. La medida alcanzará "
        "a la administración pública provincial y busca reforzar los ingresos. El Ejecutivo "
        "informó que los detalles de la liquidación se comunicarán por los canales oficiales. "
        "Fuente: El Expediente."
    )


def _valid_generated_payload() -> dict:
    title = "la rioja anunció aumento del 15% y $50.000 en chachos para estatales"
    return {
        "title": title,
        "caption": (
            "📍 El Gobierno riojano confirmó una mejora para estatales que combina aumento "
            "salarial y una acreditación extraordinaria en chachos.\n\n"
            "📊 La medida alcanzará a la administración pública provincial y los detalles de "
            "la liquidación se informarán por los canales oficiales.\n\n"
            "Fuente: El Expediente\n\n"
            "#LaRioja #Estatales #Chachos"
        ),
        "section": "economia",
        "suggested_template": "lvr_datos",
        "slides": [
            {
                "type": "cover",
                "title": title,
                "text": (
                    "El Gobierno provincial confirmó la medida para trabajadores estatales y "
                    "explicó que combina una suba salarial con una acreditación extraordinaria "
                    "en la moneda local."
                ),
                "items": [],
                "highlights": ["aumento del 15%", "$50.000 en chachos"],
                "locality": "La Rioja",
                "asset_hint": "estatales La Rioja",
                "source_ids": [],
            },
            {
                "type": "key_points",
                "title": "qué incluye el anuncio",
                "text": "",
                "items": [
                    "El incremento salarial anunciado será del 15% para los trabajadores de la administración pública provincial.",
                    "Cada agente recibirá $50.000 en chachos, según la información difundida por el Gobierno de La Rioja.",
                    "La medida busca reforzar los ingresos de los trabajadores estatales alcanzados dentro de la provincia.",
                ],
                "highlights": [],
                "locality": "",
                "asset_hint": "",
                "source_ids": [],
            },
            {
                "type": "context",
                "title": "qué falta conocer",
                "text": (
                    "El Ejecutivo provincial indicó que la mejora tendrá alcance sobre la "
                    "administración pública. Los detalles de la liquidación y la acreditación "
                    "serán comunicados mediante los canales oficiales, por lo que los agentes "
                    "deberán revisar esa información para conocer cómo se aplicará en cada caso."
                ),
                "items": [],
                "highlights": ["canales oficiales"],
                "locality": "",
                "asset_hint": "",
                "source_ids": [],
            },
        ],
        "sources": [],
        "unknowns": [],
    }


class PremiumPackageGeneratorTests(unittest.TestCase):
    def test_success_returns_parseable_json_with_expected_gemini_contract(self):
        generated = _valid_generated_payload()
        mock_chat = _gemini_mock(json.dumps(generated))

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-only",
                "GEMINI_MODEL": "test-model",
                "GEMINI_RETRY_COUNT": "1",
                "GEMINI_TIMEOUT": "7",
            },
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_premium_package_json(_source_text())

        self.assertEqual(generated, json.loads(result))
        self.assertEqual("test-only", mock_chat.call_args.kwargs["api_key"])
        self.assertEqual(7.0, mock_chat.call_args.kwargs["timeout"])
        self.assertEqual("test-model", mock_chat.call_args.kwargs["model"])
        self.assertEqual(2600, mock_chat.call_args.kwargs["max_tokens"])
        self.assertTrue(mock_chat.call_args.kwargs["json_mode"])
        system_prompt = mock_chat.call_args.kwargs["messages"][0]["content"]
        self.assertIn("NO inventes datos", system_prompt)
        self.assertIn("armas, personas", system_prompt)
        self.assertIn("NO investigues", system_prompt)
        self.assertIn("entre 60 y 80 caracteres", system_prompt)
        self.assertIn("#LaRioja", system_prompt)
        self.assertIn("exactamente 3 o 4 slides", system_prompt)
        self.assertIn("investigan", system_prompt)

    def test_editorial_validator_rejects_short_clickbait_and_thin_carousel(self):
        payload = _valid_generated_payload()
        payload["title"] = "Impactante hecho conmociona"
        payload["slides"] = payload["slides"][:2]
        payload["slides"][0]["title"] = payload["title"]
        payload["caption"] = "Texto sin recursos editoriales\n\nFuente: Medio Inventado"

        errors = validate_generated_payload(payload, _source_text())

        self.assertTrue(any(error.startswith("title_longitud") for error in errors))
        self.assertIn("title_clickbait", errors)
        self.assertTrue(any(error.startswith("slides_cantidad") for error in errors))
        self.assertTrue(any(error.startswith("caption_emojis") for error in errors))
        self.assertIn("caption_sin_hashtag_larioja", errors)
        self.assertIn("caption_fuente_no_presente_en_texto_original", errors)

    def test_editorial_validator_rejects_repeated_slide_types(self):
        payload = _valid_generated_payload()
        payload["slides"][2]["type"] = "key_points"
        payload["slides"][2]["items"] = [
            "El Ejecutivo informará los detalles finales mediante sus canales oficiales durante los próximos días.",
            "Los trabajadores deberán revisar cómo se aplicará la liquidación en cada caso particular informado.",
            "La administración pública provincial es el sector alcanzado por el anuncio difundido oficialmente este jueves.",
        ]

        errors = validate_generated_payload(payload, _source_text())

        self.assertIn("slide_2_tipo_duplicado:key_points", errors)

    def test_duplicate_context_is_normalized_to_text_only_impact(self):
        payload = _valid_generated_payload()
        duplicate = dict(payload["slides"][2])
        duplicate["title"] = "cómo se aplicará la medida"
        duplicate["asset_hint"] = "imagen que no debe conservarse"
        payload["slides"].append(duplicate)
        original_text = duplicate["text"]

        repairs = normalize_generated_duplicate_context(payload)

        self.assertEqual(["slide_3_tipo_normalizado:context->impact"], repairs)
        self.assertEqual("context", payload["slides"][2]["type"])
        self.assertEqual("impact", payload["slides"][3]["type"])
        self.assertEqual(original_text, payload["slides"][3]["text"])
        self.assertEqual("", payload["slides"][3]["asset_hint"])
        self.assertFalse(any("tipo_duplicado" in error for error in validate_generated_payload(payload, _source_text())))

    def test_generator_returns_impact_instead_of_duplicate_context(self):
        generated = _valid_generated_payload()
        generated["slides"].append(dict(generated["slides"][2]))
        mock_chat = _gemini_mock(json.dumps(generated))

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-only",
                "GEMINI_RETRY_COUNT": "1",
                "GEMINI_RETRY_SLEEP": "0",
            },
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = json.loads(generate_premium_package_json(_source_text()))

        self.assertEqual(1, mock_chat.call_count)
        self.assertEqual(["cover", "key_points", "context", "impact"], [slide["type"] for slide in result["slides"]])

    def test_invalid_editorial_json_is_retried_with_actionable_feedback(self):
        invalid = _valid_generated_payload()
        invalid["title"] = "Título corto"
        invalid["slides"][0]["title"] = "Título corto"
        valid = _valid_generated_payload()
        mock_chat = Mock(side_effect=[json.dumps(invalid), json.dumps(valid)])

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-only",
                "GEMINI_RETRY_COUNT": "2",
                "GEMINI_RETRY_SLEEP": "0",
            },
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_premium_package_json(_source_text())

        self.assertEqual(valid, json.loads(result))
        self.assertEqual(2, mock_chat.call_count)
        retry_messages = mock_chat.call_args_list[1].kwargs["messages"]
        self.assertEqual("assistant", retry_messages[2]["role"])
        self.assertEqual(json.dumps(invalid), retry_messages[2]["content"])
        retry_message = retry_messages[3]["content"]
        self.assertIn("title_longitud", retry_message)
        self.assertIn("JSON anterior", retry_message)
        self.assertIn("Devolvé el JSON completo corregido", retry_message)

    def test_last_parseable_json_is_returned_when_editorial_retries_are_exhausted(self):
        first = _valid_generated_payload()
        first["title"] = "Título corto inicial"
        first["slides"][0]["title"] = first["title"]
        last = _valid_generated_payload()
        last["title"] = "Título corto final"
        last["slides"][0]["title"] = last["title"]
        mock_chat = Mock(side_effect=[json.dumps(first), json.dumps(last)])

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-only",
                "GEMINI_RETRY_COUNT": "2",
                "GEMINI_RETRY_SLEEP": "0",
            },
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_premium_package_json(_source_text())

        self.assertEqual(last, json.loads(result))
        self.assertEqual(2, mock_chat.call_count)

    def test_final_failure_after_retries_is_visible(self):
        mock_chat = Mock(side_effect=RuntimeError("provider unavailable"))

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-only",
                "GEMINI_RETRY_COUNT": "3",
                "GEMINI_RETRY_SLEEP": "0",
            },
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            with self.assertRaises(PremiumGenerationError) as raised:
                generate_premium_package_json("Texto confirmado por el operador.")

        self.assertEqual(3, mock_chat.call_count)
        self.assertIn("tras 3 intentos", str(raised.exception))

    def test_empty_text_is_rejected_before_calling_gemini(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only"},
            clear=False,
        ), patch("utils.ai_client.chat_completion") as mock_chat:
            with self.assertRaisesRegex(PremiumGenerationError, "vacío"):
                generate_premium_package_json("   ")

        mock_chat.assert_not_called()

    def test_missing_api_key_is_reported_without_fallback(self):
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": ""},
            clear=False,
        ), patch("utils.ai_client.chat_completion") as mock_chat:
            with self.assertRaisesRegex(
                PremiumGenerationError,
                "GEMINI_API_KEY no está configurada",
            ):
                generate_premium_package_json("Texto confirmado por el operador.")

        mock_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
