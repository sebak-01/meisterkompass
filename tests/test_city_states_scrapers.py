import json
import unittest
from pathlib import Path

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_berlin import parse_format_and_mode, parse_title
from scrapers.hwk_bremen import (
    HwkBremenScraper,
    parse_parts,
    parse_price,
    parse_trade,
    resolve_trade_name,
    _merge_offers,
)
from scrapers.base import RawCourseOffer, normalize_trade
from scrapers.hwk_hamburg import iso_date, parse_trade as parse_hamburg_trade
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
            parse_hamburg_trade("Meistervorbereitung im Tischlerhandwerk"),
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
        self.assertEqual(
            parse_parts(
                "Meistervorbereitung Elektrotechnik Fachrichtung Gebäudetechnik Teil I und II - Teilzeit",
                "Meisterprüfung Teil I + II vor der HWK Bremen",
            ),
            [1, 2],
        )
        self.assertEqual(parse_price("8.100 €"), 8100.0)
        self.assertEqual(parse_price("850,00 €"), 850.0)

    def test_bremen_trade_aliases(self):
        self.assertEqual(parse_trade("22426 - Meistervorbereitung im Bauhandwerk Teil I+II  Teilzeit"), "Maurer und Betonbauer")
        self.assertEqual(parse_trade("22472 - Meistervorbereitung im Malerhandwerk Teil I + II"), "Maler und Lackierer")
        self.assertEqual(resolve_trade_name("Elektrotechnik"), "Elektrotechniker")
        self.assertEqual(normalize_trade(parse_trade("22472 - Meistervorbereitung im Malerhandwerk Teil I + II"))[0], "maler-und-lackierer")
        self.assertEqual(normalize_trade(parse_trade("22426 - Meistervorbereitung im Bauhandwerk Teil I+II  Teilzeit"))[0], "maurer-und-betonbauer")

    def test_bremen_merge_prefers_kdb_runs(self):
        kdb = [
            RawCourseOffer(
                title="Tischler (Teile I + II)",
                trade_name="Tischler",
                parts=[1, 2],
                format_key="part_time",
                teaching_mode="presence",
                start_date="2026-09-01",
                end_date=None,
                duration_hours=800,
                course_fee=8100.0,
                city="Bremen",
                street="Schongauerstr. 2",
                zip_code="28219",
                availability="available",
                source_url="https://example.test/kdb",
            )
        ]
        web = [
            RawCourseOffer(
                title="Tischler (Teile I + II)",
                trade_name="Tischler",
                parts=[1, 2],
                format_key="part_time",
                teaching_mode="presence",
                start_date=None,
                end_date=None,
                duration_hours=850,
                course_fee=None,
                city="Bremen",
                street="Schongauerstr. 2",
                zip_code="28219",
                availability="unknown",
                source_url="https://example.test/web",
            ),
            RawCourseOffer(
                title="Elektrotechniker (Teile I + II)",
                trade_name="Elektrotechniker",
                parts=[1, 2],
                format_key="part_time",
                teaching_mode="presence",
                start_date=None,
                end_date=None,
                duration_hours=850,
                course_fee=None,
                city="Bremen",
                street="Schongauerstr. 2",
                zip_code="28219",
                availability="unknown",
                source_url="https://example.test/elektro",
            ),
        ]
        merged = _merge_offers(kdb, web)
        self.assertEqual(len(merged), 2)
        self.assertEqual({o.source_url for o in merged}, {"https://example.test/kdb", "https://example.test/elektro"})

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


class CityStateExamFeeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fee_path = Path(__file__).resolve().parents[1] / "data" / "manual" / "exam_fees_manual.json"
        cls.lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))

    def test_berlin_full_master_exam_bundle(self):
        resolved = resolve_exam_fee("hwk-berlin", "elektrotechniker", [1, 2, 3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 462.0)
        self.assertEqual(resolved["display"], "462 €")

    def test_hamburg_full_master_exam_bundle(self):
        resolved = resolve_exam_fee("hwk-hamburg", "tischler", [1, 2, 3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 1300.0)
        self.assertEqual(resolved["display"], "1.300 €")

    def test_bremen_trade_specific_parts_sum(self):
        resolved = resolve_exam_fee("hwk-bremen", "tischler", [1, 2, 3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 1170.0)
        self.assertEqual(resolved["display"], "1.170 €")

    def test_bremen_maler_exam_fees(self):
        resolved = resolve_exam_fee("hwk-bremen", "maler-und-lackierer", [1, 2, 3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 1880.0)
        self.assertEqual(resolved["display"], "1.880 €")

    def test_bremen_maurer_exam_fees(self):
        resolved = resolve_exam_fee("hwk-bremen", "maurer-und-betonbauer", [1, 2, 3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 1290.0)

    def test_bremen_generic_parts_three_and_four(self):
        resolved = resolve_exam_fee("hwk-bremen", "allgemein-teil-iii-iv", [3, 4], None, self.lookup)
        self.assertEqual(resolved["fee"], 510.0)


if __name__ == "__main__":
    unittest.main()
