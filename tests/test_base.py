import unittest

from scrapers.base import canonicalize_trade_name, harmonize_course_record, normalize_trade


class TradeNormalizationTests(unittest.TestCase):
    def test_plural_trade_names_map_to_singular(self):
        self.assertEqual(canonicalize_trade_name("Konditoren"), "Konditor")
        self.assertEqual(canonicalize_trade_name("Stuckateure"), "Stuckateur")
        self.assertEqual(canonicalize_trade_name("Friseure"), "Friseur")

    def test_handwerk_suffix_and_partial_trade_names(self):
        self.assertEqual(
            canonicalize_trade_name("Schilder- und Lichtreklamehersteller-Handwerk"),
            "Schilder- und Lichtreklamehersteller",
        )
        self.assertEqual(canonicalize_trade_name("Maler"), "Maler und Lackierer")
        self.assertEqual(canonicalize_trade_name("Zahntechnik"), "Zahntechniker")

    def test_normalize_trade_uses_canonical_slug(self):
        self.assertEqual(normalize_trade("Konditoren"), ("konditor", "Konditor"))
        self.assertEqual(
            normalize_trade("Schilder- und Lichtreklamehersteller-Handwerk"),
            ("schilder-und-lichtreklamehersteller", "Schilder- und Lichtreklamehersteller"),
        )
        self.assertEqual(normalize_trade("Maler"), ("maler-und-lackierer", "Maler und Lackierer"))
        self.assertEqual(normalize_trade("Zahntechnik"), ("zahntechniker", "Zahntechniker"))

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
