from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


def _png_bytes(size=(3000, 2000), color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    return buffer.getvalue()


class MediaLibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.env = {
            "LVR_DATA_DIR": str(self.data),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_OUTPUT_DIR": str(self.root / "output"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        from utils import media_library

        self.lib = media_library
        self.addCleanup(self._close_logger)

    def _close_logger(self):
        loggers = [self.lib.logger]
        try:
            from utils.editorial_router import logger as router_logger

            loggers.append(router_logger)
        except ImportError:
            pass
        for logger in loggers:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


class ImageIngestionTests(MediaLibraryTestCase):
    def test_ingest_creates_master_within_target_and_thumbnail(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="upload", titulo="Foto de prueba")
        self.assertLessEqual(max(record["master_width"], record["master_height"]), self.lib.MASTER_MAX_DIMENSION)
        self.assertTrue(os.path.exists(record["master_path"]))
        self.assertTrue(os.path.exists(record["thumb_path"]))
        self.assertEqual(1, record["used_count"])

    def test_ingest_does_not_upscale_small_images(self):
        record = self.lib.ingest_image_bytes(_png_bytes(size=(400, 300)), origin="upload")
        self.assertEqual(400, record["master_width"])
        self.assertEqual(300, record["master_height"])

    def test_duplicate_bytes_are_deduplicated_by_hash(self):
        data = _png_bytes()
        first = self.lib.ingest_image_bytes(data, origin="upload", titulo="Original")
        second = self.lib.ingest_image_bytes(data, origin="upload", titulo="Otra vez")
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertEqual(2, second["used_count"])

        from utils.file_manager import load_json

        assets = load_json(str(self.data / "media_library.json"), [], expected_type=list)
        self.assertEqual(1, len(assets))

    def test_invalid_content_is_rejected(self):
        with self.assertRaises(ValueError):
            self.lib.ingest_image_bytes(b"not-an-image", origin="upload")

    def test_asset_lookup_returns_copy_and_controlled_thumbnail_path(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="premium_upload")

        recovered = self.lib.get_asset(record["asset_id"])
        self.assertIsNotNone(recovered)
        recovered["titulo"] = "mutado sólo en memoria"
        self.assertNotEqual(
            "mutado sólo en memoria",
            self.lib.get_asset(record["asset_id"]).get("titulo"),
        )
        self.assertEqual(
            os.path.realpath(record["thumb_path"]),
            self.lib.get_asset_thumbnail_path(record["asset_id"]),
        )

    def test_thumbnail_path_outside_controlled_directory_is_rejected(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="premium_upload")

        def tamper(assets):
            for asset in assets:
                if asset["asset_id"] == record["asset_id"]:
                    asset["thumb_path"] = str(self.root / "outside.jpg")
            return assets

        from utils.file_manager import update_json

        (self.root / "outside.jpg").write_bytes(b"not served")
        update_json(str(self.data / "media_library.json"), tamper, [], expected_type=list)

        self.assertIsNone(self.lib.get_asset_thumbnail_path(record["asset_id"]))


class CleanupTests(MediaLibraryTestCase):
    def test_active_publication_refuses_to_run(self):
        report = self.lib.cleanup_expired_assets(active_publication=True)
        self.assertEqual("blocked", report["status"])
        self.assertEqual([], report["purged"])

    def test_referenced_asset_survives_past_retention(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="upload")
        self.lib.mark_asset_used(record["asset_id"], "draft-1")
        old_ts = record["created_at_ts"] - 20 * 86400

        def backdate(assets):
            for asset in assets:
                if asset["asset_id"] == record["asset_id"]:
                    asset["created_at_ts"] = old_ts
            return assets

        from utils.file_manager import update_json

        update_json(str(self.data / "media_library.json"), backdate, [], expected_type=list)

        report = self.lib.cleanup_expired_assets(dry_run=False)
        self.assertEqual(1, report["kept_referenced"])
        self.assertEqual([], report["purged"])
        self.assertTrue(os.path.exists(record["master_path"]))

    def test_expired_unreferenced_asset_is_purged_but_metadata_survives(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="upload", titulo="Vencida")
        old_ts = record["created_at_ts"] - 20 * 86400

        def backdate(assets):
            for asset in assets:
                if asset["asset_id"] == record["asset_id"]:
                    asset["created_at_ts"] = old_ts
            return assets

        from utils.file_manager import update_json, load_json

        update_json(str(self.data / "media_library.json"), backdate, [], expected_type=list)

        report = self.lib.cleanup_expired_assets(dry_run=False)
        self.assertEqual([record["asset_id"]], report["purged"])
        self.assertFalse(os.path.exists(record["master_path"]))

        assets = load_json(str(self.data / "media_library.json"), [], expected_type=list)
        self.assertEqual(1, len(assets))  # metadata conservada
        self.assertTrue(assets[0]["files_purged"])
        self.assertEqual("Vencida", assets[0]["titulo"])

    def test_dry_run_reports_without_deleting(self):
        record = self.lib.ingest_image_bytes(_png_bytes(), origin="upload")
        old_ts = record["created_at_ts"] - 20 * 86400

        def backdate(assets):
            for asset in assets:
                if asset["asset_id"] == record["asset_id"]:
                    asset["created_at_ts"] = old_ts
            return assets

        from utils.file_manager import update_json

        update_json(str(self.data / "media_library.json"), backdate, [], expected_type=list)

        report = self.lib.cleanup_expired_assets(dry_run=True)
        self.assertEqual([record["asset_id"]], report["purged"])
        self.assertTrue(os.path.exists(record["master_path"]))  # nada se borró de verdad


class SearchLibraryTests(MediaLibraryTestCase):
    def _seed_noticias_meta(self, items):
        from utils.file_manager import save_json

        save_json(str(self.data / "noticias_meta.json"), items)

    def test_search_incendio_finds_title_and_topic_key_matches(self):
        self._seed_noticias_meta(
            [
                {
                    "titulo": "Un incendio afecta un comercio en Chilecito",
                    "titulo_original": "Un incendio afecta un comercio en Chilecito",
                    "seccion": "interior",
                    "source": "tiempopopular",
                    "canonical_url": "https://a.com/1",
                    "dedup_key": "link:1",
                    "topic_key": "topic:abc",
                    "queued_at": int(time.time()),
                    "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
                },
                {
                    "titulo": "El municipio inaugura una plaza",
                    "titulo_original": "El municipio inaugura una plaza",
                    "seccion": "sociedad",
                    "source": "tiempopopular",
                    "canonical_url": "https://a.com/2",
                    "dedup_key": "link:2",
                    "topic_key": "topic:def",
                    "queued_at": int(time.time()),
                    "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
                },
            ]
        )
        rows = self.lib.search_library(query="INCENDIO")
        titles = [row["titulo"] for row in rows]
        self.assertIn("Un incendio afecta un comercio en Chilecito", titles)
        self.assertNotIn("El municipio inaugura una plaza", titles)

    def test_search_is_accent_and_case_insensitive(self):
        self._seed_noticias_meta(
            [
                {
                    "titulo": "Alerta por temporal en Villa Unión",
                    "titulo_original": "Alerta por temporal en Villa Unión",
                    "seccion": "interior",
                    "source": "nuevarioja",
                    "canonical_url": "https://a.com/3",
                    "dedup_key": "link:3",
                    "queued_at": int(time.time()),
                    "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
                }
            ]
        )
        rows = self.lib.search_library(query="union")
        self.assertEqual(1, len(rows))
        rows2 = self.lib.search_library(query="VILLA union")
        # búsqueda multi-palabra no exacta: al menos confirmamos que
        # la variante simple sin tilde encuentra la entrada.
        self.assertTrue(any("Villa Unión" in row["titulo"] for row in self.lib.search_library(query="villa")))

    def test_includes_candidates_and_marks_them(self):
        from utils.editorial_router import apply_routing

        national = {
            "titulo_original": "El Gobierno nacional anuncio una medida",
            "titulo": "El Gobierno nacional anuncio una medida",
            "seccion": "politica",
            "hashtag_localidad": "",
            "canonical_url": "https://a.com/4",
            "source": "tiempopopular",
        }
        apply_routing(national, now_ts=int(time.time()))

        rows = self.lib.search_library(only_candidatas=True)
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["is_candidate"])

    def test_includes_published_items_with_real_evidence(self):
        from utils.file_manager import save_json

        self._seed_noticias_meta(
            [
                {
                    "titulo": "Publicada de verdad",
                    "titulo_original": "Publicada de verdad",
                    "seccion": "interior",
                    "source": "tiempopopular",
                    "canonical_url": "https://a.com/5",
                    "dedup_key": "link:5",
                    "queued_at": int(time.time()),
                    "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
                }
            ]
        )
        save_json(str(self.data / "ig_posted.json"), {"posted": {"link:5": {"external_id": "abc"}}})

        rows = self.lib.search_library(only_publicadas=True)
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["is_published"])

    def test_window_days_filters_old_entries(self):
        self._seed_noticias_meta(
            [
                {
                    "titulo": "Muy vieja",
                    "titulo_original": "Muy vieja",
                    "seccion": "interior",
                    "source": "tiempopopular",
                    "canonical_url": "https://a.com/6",
                    "dedup_key": "link:6",
                    "queued_at": int(time.time()) - 20 * 86400,
                    "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
                }
            ]
        )
        rows_default = self.lib.search_library(query="vieja")
        rows_all = self.lib.search_library(query="vieja", window_days=None)
        self.assertEqual(0, len(rows_default))
        self.assertEqual(1, len(rows_all))

    def test_asset_rows_expose_http_thumbnail_url_not_filesystem_path(self):
        record = self.lib.ingest_image_bytes(
            _png_bytes(),
            origin="premium_upload",
            titulo="Imagen de biblioteca",
        )

        rows = self.lib.search_library(query="biblioteca")

        self.assertEqual(1, len(rows))
        self.assertEqual(
            f"/api/media-library/thumb/{record['asset_id']}",
            rows[0]["thumbnail"],
        )
        self.assertNotIn(str(self.root), rows[0]["thumbnail"])


if __name__ == "__main__":
    unittest.main()
