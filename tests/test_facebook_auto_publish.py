import unittest

import automation


class UnreviewedFacebookMessageTests(unittest.TestCase):
    def test_message_uses_real_line_breaks_and_warning(self):
        message = automation._unreviewed_facebook_message(
            "नेपालमा नयाँ कार्यक्रम सुरु",
            "सम्बन्धित निकायले कार्यक्रम सुरु भएको जनाएको छ।",
            "https://example.com/news"
        )
        self.assertIn("स्वतन्त्र पुष्टि बाँकी छ।", message)
        self.assertIn("\n\nनेपालमा नयाँ कार्यक्रम सुरु", message)
        self.assertIn("\n\nसम्बन्धित निकायले कार्यक्रम सुरु भएको जनाएको छ।", message)
        self.assertIn("\n\nमूल स्रोत: https://example.com/news", message)
        self.assertNotIn("\\n", message)

    def test_missing_headline_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "headline and a valid original source URL"):
            automation._unreviewed_facebook_message(
                "", "सारांश उपलब्ध छ।", "https://example.com/news"
            )

    def test_invalid_source_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "headline and a valid original source URL"):
            automation._unreviewed_facebook_message(
                "नेपाल समाचार", "सारांश उपलब्ध छ।", "javascript:alert(1)"
            )

    def test_empty_summary_is_allowed_without_empty_section(self):
        message = automation._unreviewed_facebook_message(
            "नेपाल समाचार", "", "https://example.com/news"
        )
        self.assertIn("\n\nमूल स्रोत:", message)
        self.assertNotIn("\n\n\n\n", message)


if __name__ == "__main__":
    unittest.main()
