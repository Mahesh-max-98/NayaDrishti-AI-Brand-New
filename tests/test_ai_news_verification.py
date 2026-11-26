import unittest

import automation


class AINewsVerificationGateTests(unittest.TestCase):
    def test_sensitive_news_is_held(self):
        reason = automation._verification_risk_reason(
            "Politics", "सरकारले नयाँ निर्णय गर्‍यो", "मन्त्रिपरिषद्को निर्णय"
        )
        self.assertTrue(reason)

    def test_low_risk_story_is_not_blocked_by_risk_filter(self):
        self.assertEqual(
            automation._verification_risk_reason(
                "Sports", "नेपालले मैत्रीपूर्ण खेल जित्यो", "टोलीले खेल जितेको छ।"
            ),
            ""
        )

    def test_verification_requires_structured_claim_evidence(self):
        with self.assertRaises(ValueError):
            automation._parse_ai_verification(
                '{"verdict":"verified","score":99,"claims":[],"conflicts":[]}'
            )

    def test_verification_parser_accepts_consistent_claims(self):
        result = automation._parse_ai_verification(
            '{"verdict":"verified","score":96,"claims":['
            '{"claim":"दुई टोलीले प्रतियोगिता जितेको बताए","status":"consistent","evidence":"दुवै स्रोतमा उल्लेख"},'
            '{"claim":"कार्यक्रम आज भयो","status":"consistent","evidence":"दुवै स्रोतमा उल्लेख"}],'
            '"conflicts":[],"reason":"दुवै स्रोतका मुख्य तथ्य मिले"}'
        )
        self.assertEqual(result["score"], 96)
        self.assertEqual(len(result["claims"]), 2)

    def test_conflicting_claim_is_not_auto_approval_eligible(self):
        result = automation._parse_ai_verification(
            '{"verdict":"conflict","score":97,"claims":['
            '{"claim":"तथ्य","status":"conflicting","evidence":"स्रोतहरू फरक"},'
            '{"claim":"अर्को तथ्य","status":"consistent","evidence":"मिले"}],'
            '"conflicts":["अंक फरक"],"reason":"विरोधाभास"}'
        )
        self.assertFalse(
            result["verdict"] == "verified"
            and result["score"] >= 92
            and not result["conflicts"]
            and all(x["status"] == "consistent" for x in result["claims"])
        )


if __name__ == "__main__":
    unittest.main()
