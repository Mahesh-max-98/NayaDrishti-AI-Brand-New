import os
import unittest
from unittest.mock import patch

import app as web_app


class HealthAndReadinessTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config.update(TESTING=True, SECRET_KEY="phase-14-test-session-secret")
        web_app.app.secret_key = "phase-14-test-session-secret"
        self.client = web_app.app.test_client()

    def test_health_endpoint_reports_liveness_without_stale_phase_label(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertEqual(response.get_json()["service"], "NayaDrishti AI")
        self.assertNotIn("phase", response.get_json())

    def test_readiness_reports_missing_configuration_without_database_call(self):
        with patch.dict(os.environ, {}, clear=True), patch("automation.database_status") as database_status:
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["status"], "configuration_required")
        self.assertEqual(set(payload["missing"]), {"SECRET_KEY", "ADMIN_PASSWORD", "DATABASE_URL"})
        database_status.assert_not_called()

    def test_readiness_reports_database_failure(self):
        config = {
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD": "test-password",
            "DATABASE_URL": "postgresql://test.invalid/test_db",
        }
        with patch.dict(os.environ, config, clear=True), patch(
            "automation.database_status", return_value={"ok": False, "database": None}
        ):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "database_not_ready")
        self.assertNotIn("phase", response.get_json())

    def test_readiness_reports_ready_database_and_source_count(self):
        config = {
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD": "test-password",
            "DATABASE_URL": "postgresql://test.invalid/test_db",
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "test-model",
        }
        database_result = {"ok": True, "database": "test_db", "sources": 25}
        with patch.dict(os.environ, config, clear=True), patch(
            "automation.database_status", return_value=database_result
        ):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["database"], "connected")
        self.assertEqual(payload["sources"], 25)
        self.assertTrue(payload["ai"]["configured"])
        self.assertNotIn("phase", payload)


if __name__ == "__main__":
    unittest.main()
