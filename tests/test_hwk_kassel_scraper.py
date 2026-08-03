import unittest

from scrapers.hwk_kassel import extract_bbz_trade, normalize_bbz_trade


class BbzMarburgTradeParsingTests(unittest.TestCase):
    def test_extract_bbz_trade_strips_spaced_format_suffix(self):
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + Lackierer Vollzeit"),
            "Maler + Lackierer",
        )

    def test_extract_bbz_trade_strips_glued_format_suffix_typo(self):
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + LackiererTeilzeit"),
            "Maler + Lackierer",
        )
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + LackiererVollzeit"),
            "Maler + Lackierer",
        )

    def test_normalize_bbz_trade_maps_maler_lackierer_variants(self):
        self.assertEqual(normalize_bbz_trade("Maler + Lackierer"), "Maler und Lackierer")
        self.assertEqual(normalize_bbz_trade("Maler + LackiererTeilzeit"), "Maler und Lackierer")
        self.assertEqual(normalize_bbz_trade("Maler + LackiererVollzeit"), "Maler und Lackierer")

    def test_normalize_bbz_trade_keeps_other_trades(self):
        self.assertEqual(normalize_bbz_trade("Friseur"), "Friseur")
        self.assertEqual(normalize_bbz_trade("Kfz-Techniker"), "Kfz.-Techniker")


if __name__ == "__main__":
    unittest.main()
