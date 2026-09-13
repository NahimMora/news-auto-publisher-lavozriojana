import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from editorial_context import db as ec_db
from utils import ai_client


class _FakeUsage:
    def __init__(self, prompt_tokens, candidate_tokens):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = candidate_tokens


def _fake_client(text="respuesta generada", usage=None):
    fake_response = MagicMock()
    fake_response.text = text
    fake_response.usage_metadata = usage
    fake_client_instance = MagicMock()
    fake_client_instance.models.generate_content.return_value = fake_response
    return fake_client_instance


class AiClientInstrumentationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "ai_metrics_test.sqlite3"
        self._path_patch = patch("editorial_context.db.db_path", return_value=self.db_path)
        self._path_patch.start()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _call_rows(self):
        with ec_db.connection(self.db_path) as conn:
            return conn.execute("SELECT * FROM ai_call_metrics").fetchall()

    def test_chat_completion_without_stage_does_not_instrument(self):
        with patch("utils.ai_client.genai.Client", return_value=_fake_client()):
            result = ai_client.chat_completion(
                messages=[{"role": "user", "content": "hola"}], api_key="fake-key"
            )
        self.assertEqual(result, "respuesta generada")
        self.assertEqual(self._call_rows(), [])

    def test_chat_completion_with_stage_records_metrics_with_real_usage(self):
        usage = _FakeUsage(prompt_tokens=42, candidate_tokens=7)
        with patch("utils.ai_client.genai.Client", return_value=_fake_client(usage=usage)):
            ai_client.chat_completion(
                messages=[{"role": "user", "content": "hola"}],
                api_key="fake-key",
                stage="editorial_enricher",
                article_id="a1",
            )
        rows = self._call_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "editorial_enricher")
        self.assertEqual(rows[0]["tokens_in"], 42)
        self.assertEqual(rows[0]["tokens_out"], 7)
        self.assertEqual(rows[0]["tokens_estimated"], 0)
        self.assertEqual(rows[0]["success"], 1)

    def test_chat_completion_estimates_tokens_when_sdk_has_no_usage(self):
        with patch("utils.ai_client.genai.Client", return_value=_fake_client(usage=None)):
            ai_client.chat_completion(
                messages=[{"role": "user", "content": "hola"}],
                api_key="fake-key",
                stage="editorial_enricher",
            )
        rows = self._call_rows()
        self.assertEqual(rows[0]["tokens_estimated"], 1)
        self.assertGreaterEqual(rows[0]["tokens_out"], 0)

    def test_chat_completion_records_failure_on_sdk_exception(self):
        fake_client_instance = MagicMock()
        fake_client_instance.models.generate_content.side_effect = RuntimeError("boom")
        with patch("utils.ai_client.genai.Client", return_value=fake_client_instance):
            with self.assertRaises(RuntimeError):
                ai_client.chat_completion(
                    messages=[{"role": "user", "content": "hola"}],
                    api_key="fake-key",
                    stage="editorial_enricher",
                )
        rows = self._call_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["success"], 0)

    def test_chat_completion_records_failure_on_empty_response(self):
        with patch("utils.ai_client.genai.Client", return_value=_fake_client(text="")):
            with self.assertRaises(ai_client.AIClientError):
                ai_client.chat_completion(
                    messages=[{"role": "user", "content": "hola"}],
                    api_key="fake-key",
                    stage="editorial_enricher",
                )
        rows = self._call_rows()
        self.assertEqual(rows[0]["success"], 0)


if __name__ == "__main__":
    unittest.main()
