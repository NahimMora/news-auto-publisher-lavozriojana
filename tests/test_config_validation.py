from __future__ import annotations

import unittest


class ConfigValidationTests(unittest.TestCase):
    def _base(self):
        return {
            "PIPELINE_24X7_INTERVAL_SECONDS": "3600",
            "PIPELINE_24X7_HEARTBEAT_SECONDS": "30",
            "PIPELINE_24X7_STALE_SECONDS": "900",
            "SCRAPER_MAX_LINKS": "8",
            "ARTICLE_MAX_AGE_DAYS": "1",
            "WEB_PUBLISH_TARGET": "off",
            "FB_PUBLISH_ENABLED": "false",
            "IG_PUBLISH_ENABLED": "false",
            "OPENAI_FALLBACK_MODE": "allow_non_sensitive",
            "JSON_BACKUP_ENABLED": "true",
            "JSON_BACKUP_RETENTION_COUNT": "20",
        }

    def test_core_config_accepts_safe_values_without_external_credentials(self):
        from utils.config import validate_config

        report = validate_config(self._base(), scope="core")

        self.assertTrue(report.ok, report.to_dict())

    def test_invalid_numbers_booleans_urls_and_stale_window_are_errors(self):
        from utils.config import validate_config

        env = self._base()
        env.update(
            PIPELINE_24X7_HEARTBEAT_SECONDS="0",
            PIPELINE_24X7_STALE_SECONDS="5",
            SCRAPER_MAX_LINKS="many",
            JSON_BACKUP_ENABLED="perhaps",
            WEB_PUBLISH_TARGET="wordpress",
        )
        report = validate_config(env, scope="core")
        codes = {issue.code for issue in report.errors}

        self.assertIn("invalid_positive_int", codes)
        self.assertIn("invalid_boolean", codes)
        self.assertIn("invalid_choice", codes)
        self.assertIn("stale_not_greater_than_heartbeat", codes)

    def test_enabled_external_stages_require_non_placeholder_credentials(self):
        from utils.config import validate_config

        env = self._base()
        env.update(
            WEB_PUBLISH_TARGET="node_webapp",
            WEBAPP_BASE_URL="https://cms.example.com",
            PRIVATE_API_KEY="PENDIENTE",
            FB_PUBLISH_ENABLED="true",
            FB_PAGE_ID="PENDIENTE",
            FB_PAGE_ACCESS_TOKEN="PENDIENTE",
            IG_PUBLISH_ENABLED="true",
            IG_ACCOUNT_ID="PENDIENTE",
            IG_ACCESS_TOKEN="PENDIENTE",
        )
        report = validate_config(env, scope="all")
        fields = {issue.field for issue in report.errors}

        self.assertIn("PRIVATE_API_KEY", fields)
        self.assertIn("FB_PAGE_ID", fields)
        self.assertIn("FB_PAGE_ACCESS_TOKEN", fields)
        self.assertIn("IG_ACCOUNT_ID", fields)
        self.assertIn("IG_ACCESS_TOKEN", fields)
        self.assertIn("R2_ACCOUNT_ID", fields)

    def test_instagram_can_explicitly_use_original_public_image_without_r2(self):
        from utils.config import validate_config

        env = self._base()
        env.update(
            IG_PUBLISH_ENABLED="true",
            IG_ACCOUNT_ID="ig-test",
            IG_ACCESS_TOKEN="test-token",
            IG_ALLOW_ORIGINAL_IMAGE_FALLBACK="true",
        )

        report = validate_config(env, scope="instagram")

        self.assertTrue(report.ok, report.to_dict())

    def test_declared_limits_and_json_path_overrides_are_validated(self):
        from utils.config import validate_config

        env = self._base()
        env.update(
            WEB_PUBLISH_MAX_PER_RUN="-1",
            IG_IMAGE_CONTAINER_WAIT_SECONDS="-1",
            WEB_QUEUE_PATH="not-a-json-file.txt",
        )

        report = validate_config(env, scope="core")
        fields = {issue.field for issue in report.errors}

        self.assertIn("WEB_PUBLISH_MAX_PER_RUN", fields)
        self.assertIn("IG_IMAGE_CONTAINER_WAIT_SECONDS", fields)
        self.assertIn("WEB_QUEUE_PATH", fields)

    def test_article_not_before_date_must_use_iso_format(self):
        from utils.config import validate_config

        valid = self._base()
        valid["ARTICLE_NOT_BEFORE_DATE"] = "2026-07-27"
        invalid = self._base()
        invalid["ARTICLE_NOT_BEFORE_DATE"] = "27/07/2026"

        self.assertTrue(validate_config(valid, scope="core").ok)
        report = validate_config(invalid, scope="core")

        self.assertIn(
            "ARTICLE_NOT_BEFORE_DATE",
            {issue.field for issue in report.errors},
        )

    def test_inventory_classifies_obsolete_and_development_variables(self):
        from utils.config import config_inventory

        inventory = config_inventory()

        self.assertIn("IG_CHROME_PROFILE_DIR", inventory["obsolete"])
        self.assertIn("CUSTOM_POST_DRY_RUN", inventory["development"])
        self.assertIn("PIPELINE_24X7_STALE_SECONDS", inventory["optional"])
        self.assertIn("ARTICLE_NOT_BEFORE_DATE", inventory["optional"])
        self.assertIn("WEB_QUEUE_PATH", inventory["development"])
        self.assertIn("OPENAI_API_KEY", inventory["conditional_required"])

    def test_safe_snapshot_never_exposes_secrets(self):
        from utils.config import safe_config_snapshot

        snapshot = safe_config_snapshot(
            {
                "PRIVATE_API_KEY": "super-secret-api-key",
                "IG_ACCESS_TOKEN": "super-secret-token",
                "WEBAPP_BASE_URL": "https://cms.example.com",
            }
        )

        self.assertEqual("[CONFIGURADO]", snapshot["PRIVATE_API_KEY"])
        self.assertEqual("[CONFIGURADO]", snapshot["IG_ACCESS_TOKEN"])
        self.assertEqual("https://cms.example.com", snapshot["WEBAPP_BASE_URL"])


if __name__ == "__main__":
    unittest.main()
