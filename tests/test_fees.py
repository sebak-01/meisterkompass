import unittest

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee


class ExamFeeSourceTests(unittest.TestCase):
    def test_page_scraped_fee_is_not_from_tariff(self):
        lookup = build_exam_fee_lookup([], [])
        resolved = resolve_exam_fee("hwk-trier", "tischler", [1, 2], 500.0, lookup)
        self.assertEqual(resolved["fee"], 500.0)
        self.assertFalse(resolved["from_tariff"])

    def test_lookup_fee_is_from_tariff(self):
        lookup = build_exam_fee_lookup([], [{
            "chamber_slug": "hwk-berlin",
            "trade_slug": None,
            "parts": [1, 2, 3, 4],
            "fee": 462.0,
            "fee_max": None,
            "qualifier": "",
        }])
        resolved = resolve_exam_fee("hwk-berlin", "elektrotechniker", [1, 2, 3, 4], None, lookup)
        self.assertEqual(resolved["fee"], 462.0)
        self.assertTrue(resolved["from_tariff"])

    def test_per_part_lookup_with_qualifier_is_from_tariff(self):
        lookup = build_exam_fee_lookup([], [{
            "chamber_slug": "hwk-koblenz",
            "trade_slug": None,
            "part": 1,
            "fee": 1200.0,
            "fee_max": None,
            "qualifier": "bis zu",
        }])
        resolved = resolve_exam_fee("hwk-koblenz", "tischler", [1], None, lookup)
        self.assertTrue(resolved["from_tariff"])
        self.assertEqual(resolved["qualifier"], "bis zu")


if __name__ == "__main__":
    unittest.main()
