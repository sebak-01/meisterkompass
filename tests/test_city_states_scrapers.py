import unittest

from scrapers.hwk_berlin import parse_format_and_mode, parse_title
from scrapers.hwk_bremen import HwkBremenScraper, parse_parts, parse_price
from scrapers.hwk_hamburg import iso_date, parse_trade
from scrapers.hwk_universal_kdb import build_kdb_detail_url, parse_kdb_availability
from scrapers.pipeline import SCRAPERS


class CityStateScraperParserTests(unittest.TestCase):
    def test_berlin_title_parsing(self):
        self.assertEqual(
            parse_title("Meistervorbereitungslehrgang Elektrotechnik Teil I und Teil II Vollzeit 1-26"),
            ("Elektrotechnik", [1, 2]),
        )
        self.assertEqual(
            parse_title("MVL Wirtschaft und Recht, Pädagogik Teil III und Teil IV Digital/ Live 2-27"),
            (None, [3, 4]),
        )

    def test_berlin_trade_alias_applied_in_scraper(self):
        from scrapers.hwk_berlin import TRADE_ALIASES

        self.assertEqual(TRADE_ALIASES["Elektrotechnik"], "Elektrotechniker")

    def test_berlin_format_and_mode(self):
        self.assertEqual(
            parse_format_and_mode("Meistervorbereitungslehrgang Digital/ Live"),
            ("part_time", "online"),
        )

    def test_hamburg_trade_parsing(self):
        self.assertEqual(
            parse_trade("Meistervorbereitung im Tischlerhandwerk"),
            "Tischler",
        )

    def test_hamburg_iso_date(self):
        self.assertEqual(iso_date("2026-10-12T00:00:00+00:00"), "2026-10-12")

    def test_bremen_parts_and_price(self):
        self.assertEqual(
            parse_parts(
                "22462 - Meistervorbereitung im Tischlerhandwerk Teil I + II",
                "Handwerksmeister Teil I + II",
            ),
            [1, 2],
        )
        self.assertEqual(parse_price("8.100 €"), 8100.0)
        self.assertEqual(parse_price("850,00 €"), 850.0)

    def test_bremen_availability_and_urls(self):
        self.assertEqual(parse_kdb_availability("18", "18"), "full")
        self.assertEqual(
            build_kdb_detail_url(
                "https://www.handwerkbremen.de/service-center/kurse-und-seminare#/",
                "MVK",
                "365",
                "44360",
            ),
            "https://www.handwerkbremen.de/service-center/kurse-und-seminare#/vorlage/MVK/365?kurs=44360",
        )


class CityStateScraperIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered(self):
        expected = {
            "hwk-berlin": "Berlin",
            "hwk-hamburg": "Hamburg",
            "hwk-bremen": "Bremen",
        }
        for slug, region in expected.items():
            self.assertIn(slug, SCRAPERS)
            self.assertEqual(SCRAPERS[slug].chamber_region, region)


if __name__ == "__main__":
    unittest.main()
