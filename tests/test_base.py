import unittest

from scrapers.base import harmonize_course_record, normalize_trade, singularize_trade_name


class TradeNormalizationTests(unittest.TestCase):
    def test_plural_trade_names_map_to_singular(self):
        self.assertEqual(singularize_trade_name("Konditoren"), "Konditor")
        self.assertEqual(singularize_trade_name("Stuckateure"), "Stuckateur")
        self.assertEqual(singularize_trade_name("Friseure"), "Friseur")

    def test_normalize_trade_uses_singular_slug(self):
        self.assertEqual(normalize_trade("Konditoren"), ("konditor", "Konditor"))
        self.assertEqual(normalize_trade("Stuckateure"), ("stuckateur", "Stuckateur"))

    def test_harmonize_course_record_rebuilds_title(self):
        rec = {
            "trade_name": "Konditoren",
            "trade_slug": "konditoren",
            "title": "Konditoren (Teile I + II)",
            "parts": [1, 2],
        }
        harmonize_course_record(rec)
        self.assertEqual(rec["trade_name"], "Konditor")
        self.assertEqual(rec["trade_slug"], "konditor")
        self.assertEqual(rec["title"], "Konditor (Teile I + II)")


if __name__ == "__main__":
    unittest.main()
