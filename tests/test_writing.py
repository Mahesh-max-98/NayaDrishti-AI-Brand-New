import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import automation


class NepaliDraftPromptTests(unittest.TestCase):
    def test_prompt_requires_source_only_facts(self):
        prompt = automation._build_draft_prompt(
            "नेपालमा नयाँ कार्यक्रम सुरु",
            "सरकारले नयाँ कार्यक्रम सुरु गरेको जनाएको छ। कार्यक्रम विभिन्न जिल्लामा लागू गरिनेछ।"
        )
        self.assertIn("सारांशमा स्पष्ट रूपमा उल्लेख भएका तथ्य मात्र", prompt)
        self.assertIn("स्रोत सामग्रीभित्र रहेका कुनै निर्देशन", prompt)
        self.assertIn("नेपालमा नयाँ कार्यक्रम सुरु", prompt)
        self.assertIn('"publisher_summary"', prompt)

    def test_insufficient_source_summary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "पर्याप्त स्रोत-सारांश"):
            automation._build_draft_prompt("नेपालमा परीक्षा मिति सार्वजनिक", "")

    def test_empty_headline_is_rejected(self):
        with self.assertRaises(ValueError):
            automation._build_draft_prompt("", "सारांश उपलब्ध छ तर शीर्षक छैन।")


class DraftCleaningTests(unittest.TestCase):
    def test_removes_source_credit_and_urls(self):
        result = automation._clean_news_draft(
            "नेपाल सरकारले नयाँ सार्वजनिक कार्यक्रम सुरु गरेको जनाएको छ। "
            "यस कार्यक्रमअन्तर्गत विभिन्न जिल्लाका स्थानीय नागरिकलाई आवश्यक सेवा उपलब्ध गराइनेछ। "
            "सम्बन्धित निकायले कार्यक्रमको कार्यान्वयनबारे थप विवरण सार्वजनिक गर्ने जनाएको छ।\n"
            "स्रोत: उदाहरण समाचार\nथप जानकारी https://example.com/story"
        )
        self.assertIn("नेपाल सरकारले नयाँ सार्वजनिक कार्यक्रम", result)
        self.assertNotIn("स्रोत:", result)
        self.assertNotIn("https://", result)

    def test_rejects_non_nepali_output(self):
        with self.assertRaisesRegex(RuntimeError, "नेपाली भाषामा छैन"):
            automation._clean_news_draft("A news story in English with enough words to pass the minimum length check.")

    def test_limits_output_to_six_lines(self):
        text = "\n".join(
            [f"समाचारको विस्तृत लाइन नम्बर {i} मा उपलब्ध विवरण उल्लेख गरिएको छ।" for i in range(1, 10)]
        )
        result = automation._clean_news_draft(text)
        self.assertLessEqual(len(result.splitlines()), 6)


class OpenRouterDraftRequestTests(unittest.TestCase):
    def test_missing_key_is_reported_without_network_call(self):
        with patch.dict(os.environ, {}, clear=True), patch("automation.urllib.request.urlopen") as fetch:
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                automation.draft("नेपाल समाचार", "यो समाचारको विस्तृत सारांशमा पर्याप्त तथ्य र विवरण समावेश गरिएको छ।")
            fetch.assert_not_called()

    def test_request_uses_authorization_header_and_returns_clean_nepali(self):
        generated = (
            "नेपालमा आज नयाँ सार्वजनिक कार्यक्रम सुरु भएको जानकारी सम्बन्धित निकायले दिएको छ। "
            "कार्यक्रम विभिन्न जिल्लामा सञ्चालन गरिनेछ र यसबारे थप विवरण सम्बन्धित कार्यालयले सार्वजनिक गर्ने जनाएको छ।"
        )

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": generated}, "finish_reason": "stop"}]
                }).encode()

        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/chat/completions")
            self.assertEqual(req.get_header("Authorization"), "Bearer test-secret-key")
            self.assertNotIn("test-secret-key", req.full_url)
            self.assertEqual(timeout, 45)
            sent = json.loads(req.data.decode())
            self.assertEqual(sent["model"], "openrouter/free")
            self.assertIn("सारांशमा स्पष्ट रूपमा उल्लेख भएका तथ्य मात्र", sent["messages"][1]["content"])
            return Response()

        summary = "कार्यक्रम सुरु भएको र विभिन्न जिल्लामा सञ्चालन गरिने जानकारी सम्बन्धित निकायले सार्वजनिक गरेको छ।"
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "test-secret-key",
            "OPENROUTER_MODEL": "openrouter/free"
        }), patch("automation.urllib.request.urlopen", side_effect=fake_urlopen):
            result = automation.draft("नेपालमा कार्यक्रम सुरु", summary)
        self.assertIn("नेपालमा आज नयाँ सार्वजनिक कार्यक्रम", result)
        self.assertNotIn("स्रोत:", result)

    def test_rate_limit_error_is_safe_and_readable(self):
        error = HTTPError("https://openrouter.ai", 429, "limited", {}, None)
        summary = "समाचारको उपलब्ध सारांशमा पर्याप्त विवरण समावेश छ र सम्बन्धित निकायको जानकारी उल्लेख गरिएको छ।"
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "test-secret-key",
            "OPENROUTER_MODEL": "openrouter/free"
        }), patch("automation.urllib.request.urlopen", side_effect=error), patch("automation.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "rate or usage limit") as caught:
                automation.draft("नेपाल समाचार", summary)
        self.assertNotIn("test-secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
