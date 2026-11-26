import os
import re
import unittest
from unittest.mock import patch

import app as web_app


class AdminSecurityTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config.update(TESTING=True, SECRET_KEY="phase-11-test-session-secret")
        web_app.app.secret_key = "phase-11-test-session-secret"
        web_app._login_failures.clear()
        self.client = web_app.app.test_client()

    def tearDown(self):
        web_app._login_failures.clear()

    def csrf_token(self, client=None):
        response = (client or self.client).get("/admin/login")
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name=csrf_token value="([^"]+)"', response.data)
        self.assertIsNotNone(match, "Login page must include a CSRF token.")
        return match.group(1).decode()

    def test_login_page_sets_security_headers_and_csrf_token(self):
        response = self.client.get("/admin/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn(b'name=csrf_token', response.data)

    def test_admin_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/admin/login", data={"password": "wrong"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(web_app._login_failures, {})

    def test_login_failures_are_limited_per_forwarded_client_ip(self):
        token = self.csrf_token()
        client_ip = "198.51.100.23"
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-correct-password", "SECRET_KEY": "test-secret"}):
            for _ in range(5):
                response = self.client.post(
                    "/admin/login",
                    data={"password": "incorrect", "csrf_token": token},
                    environ_base={"REMOTE_ADDR": "10.0.0.8"},
                    headers={"X-Forwarded-For": client_ip},
                )
                self.assertEqual(response.status_code, 401)
            self.assertEqual(len(web_app._login_failures[client_ip]), 5)
            blocked = self.client.post(
                "/admin/login",
                data={"password": "incorrect", "csrf_token": token},
                environ_base={"REMOTE_ADDR": "10.0.0.8"},
                headers={"X-Forwarded-For": client_ip},
            )
            self.assertEqual(blocked.status_code, 429)

    def test_successful_login_still_works_with_csrf_token(self):
        token = self.csrf_token()
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-correct-password", "SECRET_KEY": "test-secret"}):
            response = self.client.post(
                "/admin/login",
                data={"password": "test-correct-password", "csrf_token": token},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin")
        self.assertEqual(self.client.get("/admin").status_code, 200)


if __name__ == "__main__":
    unittest.main()
