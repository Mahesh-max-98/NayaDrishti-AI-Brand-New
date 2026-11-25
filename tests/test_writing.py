import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import automation


class NepaliDraftPromptTests(unittest.TestCase):
    def test_prompt_requires_source_only_facts(self):
        prompt = automation._build_draft_prompt("नेपालमा नयाँ कार्यक्रम सुरु", "सरकारले कार्यक्रम सुरु गरेको जनाएको छ।")
        self.assertIn("तथ्य मात्र प्रयोग", prompt)
        self.assertIn("स्रोत क्रेडिट", prompt)
        self.assertIn("अविश्वसनीय", prompt)
        self.assertIn("नेपालमा नयाँ कार्यक्रम सुरु", prompt)

    def test_headline_only_prompt_forbids_extra_details(self):
        prompt = automation._build_draft_prompt("नेपालमा परीक्षा मिति सार्वजनिक", "")
        self.assertIn("शीर्षक मात्र उपलब्ध छ", prompt)
        self.assertIn('"publisher_summary": ""', prompt)

    def test_empty_headline_is_rejected(self):
        with self.assertRaises(ValueError):
            automation._build_draft_prompt("", "सारांश")


class DraftCleaningTests(unittest.TestCase):
    def test_removes_source_credit_and_urls(self):
        result = automation._clean_news_draft(
            "नेपालमा नयाँ कार्यक्रम सुरु भयो।\nस्रोत: उदाहरण समाचार\nथप जानकारी https://example.com/story"
        )
        self.assertIn("नेपालमा नयाँ कार्यक्रम सुरु भयो", result)
        self.assertNotIn("स्रोत:", result)
        self.assertNotIn("https://", result)

    def test_rejects_non_nepali_output(self):
        with self.assertRaisesRegex(RuntimeError, "not in Nepali"):
            automation._clean_news_draft("A news story in English")

    def test_limits_output_to_ten_lines(self):
        text = "\n".join([f"समाचार लाइन {i}" for i in range(15)])
        result = automation._clean_news_draft(text)
        self.assertEqual(len(result.splitlines()), 10)


class GeminiDraftRequestTests(unittest.TestCase):
    def test_missing_key_is_reported_without_network_call(self):
        with patch.dict(os.environ, {}, clear=True), patch("automation.urllib.request.urlopen") as fetch:
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                automation.draft("नेपाल समाचार", "")
            fetch.assert_not_called()

    def test_request_uses_header_key_and_returns_clean_nepali(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": "नेपालमा आज नयाँ कार्यक्रम सुरु भयो।\nस्रोत: Example"}]}}]}).encode()
        def fake_urlopen(req, timeout):
            self.assertEqual(req.get_header("X-goog-api-key"), "test-secret-key")
            self.assertNotIn("test-secret-key", req.full_url)
            self.assertEqual(timeout, 35)
            sent = json.loads(req.data.decode())
            self.assertIn("तथ्य मात्र प्रयोग", sent["contents"][0]["parts"][0]["text"])
            return Response()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret-key", "GEMINI_MODEL": "gemini-test"}), patch("automation.urllib.request.urlopen", side_effect=fake_urlopen):
            result = automation.draft("नेपालमा कार्यक्रम सुरु", "कार्यक्रम सुरु भएको जानकारी।")
        self.assertIn("नेपालमा आज नयाँ कार्यक्रम सुरु भयो", result)
        self.assertNotIn("स्रोत:", result)

    def test_rate_limit_error_is_safe_and_readable(self):
        error = HTTPError("https://example.invalid", 429, "limited", {}, None)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret-key"}), patch("automation.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "usage limit") as caught:
                automation.draft("नेपाल समाचार", "")
        self.assertNotIn("test-secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()