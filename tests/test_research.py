import unittest
from datetime import datetime, timedelta, timezone

import automation


class ResearchCategoryTests(unittest.TestCase):
    def test_nepali_sports_headline(self):
        self.assertEqual(automation._research_category("नेपालमा क्रिकेट प्रतियोगिता सुरु"), "Sports")

    def test_education_headline(self):
        self.assertEqual(automation._research_category("SEE परीक्षा सम्बन्धी सूचना"), "Education")

    def test_unmatched_headline_is_other(self):
        self.assertEqual(automation._research_category("स्थानीय कार्यक्रम सम्पन्न"), "Other")


class HeadlineMatchingTests(unittest.TestCase):
    def test_normalization_removes_punctuation_and_spacing(self):
        self.assertEqual(automation._normalized_title("  नेपाल—क्रिकेट!   आज "), "नेपाल क्रिकेट आज")

    def test_same_headline_has_full_similarity(self):
        self.assertEqual(automation._title_similarity("नेपालमा क्रिकेट सुरु", "नेपालमा क्रिकेट सुरु"), 1.0)

    def test_unrelated_headlines_do_not_match(self):
        self.assertLess(automation._title_similarity("नेपालमा क्रिकेट सुरु", "बैंकको ब्याजदर परिवर्तन"), 0.84)

    def test_empty_titles_never_match(self):
        self.assertEqual(automation._title_similarity("", "नेपाल समाचार"), 0.0)

    def test_matcher_accepts_rephrased_headline_with_three_shared_terms(self):
        self.assertTrue(automation._headline_match_candidate(
            "नेपाल क्रिकेट टोलीले आज प्रतियोगिता जित्यो",
            "आज नेपाल क्रिकेट टोलीले फाइनल खेल जित्यो",
            "Sports", "Sports"
        ))

    def test_matcher_rejects_generic_two_word_overlap(self):
        self.assertFalse(automation._headline_match_candidate(
            "नेपाल सरकारले नयाँ निर्णय गर्‍यो",
            "नेपाल सरकारले अर्को योजना सार्वजनिक गर्‍यो",
            "Politics", "Politics"
        ))

    def test_matcher_rejects_different_categories(self):
        self.assertFalse(automation._headline_match_candidate(
            "नेपाल क्रिकेट टोलीले प्रतियोगिता जित्यो",
            "नेपाल क्रिकेट टोलीले प्रतियोगिता जित्यो",
            "Sports", "Politics"
        ))

    def test_matcher_rejects_reports_more_than_one_day_apart(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        self.assertFalse(automation._headline_match_candidate(
            "नेपाल क्रिकेट टोलीले प्रतियोगिता जित्यो",
            "नेपाल क्रिकेट टोली प्रतियोगितामा विजयी भयो",
            "Sports", "Sports", now, now - timedelta(hours=30)
        ))


class PublicationDateTests(unittest.TestCase):
    def test_rss_published_date_is_parsed(self):
        parsed = automation._published_datetime({"published": "Wed, 25 Nov 2026 10:00:00 GMT"})
        self.assertEqual(parsed, datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc))

    def test_missing_date_returns_none(self):
        self.assertIsNone(automation._published_datetime({"title": "No date"}))


class ResearchSignalTests(unittest.TestCase):
    def test_unknown_date_is_flagged_and_not_breaking(self):
        flags, evidence, breaking = automation._research_metadata(["Source A"], None, summary="")
        self.assertIn("publication_time_unknown", flags)
        self.assertIn("headline_only_no_article_summary", flags)
        self.assertEqual(evidence, "headline_only_single_source")
        self.assertFalse(breaking)

    def test_old_story_is_flagged(self):
        old = datetime.now(timezone.utc) - timedelta(days=3)
        flags, _, breaking = automation._research_metadata(["Source A"], old, summary="Summary")
        self.assertIn("possibly_old_news", flags)
        self.assertFalse(breaking)

    def test_two_sources_are_only_a_headline_match(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=20)
        flags, evidence, breaking = automation._research_metadata(["Source A", "Source B"], recent, summary="Summary")
        self.assertIn("similar_headline_seen_in_multiple_sources", flags)
        self.assertEqual(evidence, "multiple_source_headline_match_only")
        self.assertFalse(breaking)

    def test_three_sources_can_only_be_a_breaking_candidate(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=20)
        flags, _, breaking = automation._research_metadata(["Source A", "Source B", "Source C"], recent, summary="Summary")
        self.assertTrue(breaking)
        self.assertIn("breaking_candidate_requires_editorial_verification", flags)

    def test_future_timestamp_is_not_breaking(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        flags, _, breaking = automation._research_metadata(["Source A", "Source B", "Source C"], future, summary="Summary")
        self.assertFalse(breaking)
        self.assertNotIn("breaking_candidate_requires_editorial_verification", flags)


if __name__ == "__main__":
    unittest.main()
