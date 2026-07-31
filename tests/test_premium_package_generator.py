from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openIA.premium_package_generator import (
    PremiumGenerationError,
    generate_premium_package_json,
)


def _client_with_content(content: str):
    create = Mock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    return client, create


class PremiumPackageGeneratorTests(unittest.TestCase):
    def test_success_returns_parseable_json_with_expected_openai_contract(self):
        generated = {
            "title": "Actualización confirmada",
            "caption": "Resumen para redes",
            "section": "sociedad",
            "suggested_template": "lvr_cronica",
            "slides": [
                {"type": "cover", "text": "Actualización confirmada"},
                {"type": "closing", "text": "La Voz Riojana"},
            ],
            "sources": [],
            "unknowns": [],
        }
        client, create = _client_with_content(json.dumps(generated))

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-only",
                "OPENAI_MODEL": "test-model",
                "OPENAI_RETRY_COUNT": "1",
                "OPENAI_TIMEOUT": "7",
            },
            clear=False,
        ), patch("openai.OpenAI", return_value=client) as openai_class:
            result = generate_premium_package_json(
                "El operador confirma esta actualización y no aporta otros datos."
            )

        self.assertEqual(generated, json.loads(result))
        openai_class.assert_called_once_with(api_key="test-only", timeout=7.0)
        self.assertEqual("test-model", create.call_args.kwargs["model"])
        self.assertEqual(
            {"type": "json_object"},
            create.call_args.kwargs["response_format"],
        )
        system_prompt = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("NO inventes datos", system_prompt)
        self.assertIn("armas, personas", system_prompt)
        self.assertIn("NO investigues", system_prompt)

    def test_final_failure_after_retries_is_visible(self):
        create = Mock(side_effect=RuntimeError("provider unavailable"))
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create),
            )
        )

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-only",
                "OPENAI_RETRY_COUNT": "3",
                "OPENAI_RETRY_SLEEP": "0",
            },
            clear=False,
        ), patch("openai.OpenAI", return_value=client):
            with self.assertRaises(PremiumGenerationError) as raised:
                generate_premium_package_json("Texto confirmado por el operador.")

        self.assertEqual(3, create.call_count)
        self.assertIn("tras 3 intentos", str(raised.exception))

    def test_empty_text_is_rejected_before_calling_openai(self):
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-only"},
            clear=False,
        ), patch("openai.OpenAI") as openai_class:
            with self.assertRaisesRegex(PremiumGenerationError, "vacío"):
                generate_premium_package_json("   ")

        openai_class.assert_not_called()

    def test_missing_api_key_is_reported_without_fallback(self):
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": ""},
            clear=False,
        ), patch("openai.OpenAI") as openai_class:
            with self.assertRaisesRegex(
                PremiumGenerationError,
                "OPENAI_API_KEY no está configurada",
            ):
                generate_premium_package_json("Texto confirmado por el operador.")

        openai_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
