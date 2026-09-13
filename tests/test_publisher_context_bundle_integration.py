from __future__ import annotations

import logging
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


class PublisherContextBundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": self.temp.name,
                "LVR_LOGS_DIR": os.path.join(self.temp.name, "logs"),
                "JSON_BACKUP_ENABLED": "false",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(logging.shutdown)

    def test_successful_publish_ingests_article_into_archive_index_without_authorname(self):
        from pipeline.node_webapp import publisher
        from pipeline.node_webapp import editorial_flags
        from editorial_context import archive_index as ec_archive_index
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        editorial = SimpleNamespace(title="Nota", quality_score=0.95, fallback_used=False, tags=[])
        media = SimpleNamespace(ok=True, warnings=[])
        public_url = "https://lavozriojana.example/nota-integracion"
        noticia = {
            "titulo": "Comenzo la obra de repavimentacion en Chilecito",
            "titulo_original": "Comenzo la obra de repavimentacion en Chilecito",
            "seccion": "interior",
            "parrafos": ["Vialidad provincial confirmo el inicio de los trabajos en la ruta."],
            "canonical_url": "https://fuente.example/nota-original",
        }

        captured_payload = {}

        def fake_build_post_payload(noticia_arg, editorial_arg, media_arg, **kwargs):
            payload = {
                "title": "NOTA PUBLICADA",
                "excerpt": "Excerpt de la nota",
                "categorySlug": "interior",
                "tags": ["Interior"],
                "publishedAt": "2026-08-10T10:00:00Z",
            }
            if kwargs.get("story_key"):
                payload["storyKey"] = kwargs["story_key"]
            captured_payload.update(payload)
            return payload

        with mock.patch.object(publisher, "prepare_editorial", return_value=editorial), mock.patch.object(
            publisher, "prepare_media", return_value=media
        ), mock.patch.object(
            publisher, "build_post_payload", side_effect=fake_build_post_payload
        ), mock.patch.object(
            publisher,
            "post_payload_detailed",
            return_value=OperationResult(
                StageStatus.SUCCESS,
                public_url=public_url,
                external_id="post-123",
                response={"ok": True, "url": public_url},
            ),
        ), mock.patch.object(editorial_flags, "detect_breaking", return_value=False), mock.patch.object(
            editorial_flags, "detect_featured", return_value=False
        ), mock.patch.object(publisher, "sync_meta_web_link", return_value=public_url), mock.patch.object(
            publisher, "_record_published_history"
        ), mock.patch.object(publisher, "record_queue_event"):
            result = publisher.publish_one_detailed(noticia)

        self.assertTrue(result["published"])
        self.assertNotIn("authorName", captured_payload)

        article_id = publisher.external_id(noticia)
        archived = ec_archive_index.get_by_article_id(article_id)
        self.assertIsNotNone(archived)
        self.assertEqual(archived.canonical_url, public_url)
        self.assertEqual(archived.category, "interior")


if __name__ == "__main__":
    unittest.main()
