import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.logging_setup import setup_logger


class LoggingSecurityTests(unittest.TestCase):
    def test_rotating_file_log_redacts_environment_and_inline_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "LVR_LOGS_DIR": tmp,
                "TEST_ACCESS_TOKEN": "token-super-secreto",
            },
            clear=False,
        ):
            logger = setup_logger("test.redaction.unique", "external.log")
            logger.error(
                "Fallo token=%s access_token=visible-inline",
                "token-super-secreto",
            )
            for handler in logger.handlers:
                handler.flush()
            logging.shutdown()
            content = (Path(tmp) / "external.log").read_text(encoding="utf-8")
        self.assertNotIn("token-super-secreto", content)
        self.assertNotIn("visible-inline", content)
        self.assertIn("[REDACTADO]", content)


if __name__ == "__main__":
    unittest.main()
