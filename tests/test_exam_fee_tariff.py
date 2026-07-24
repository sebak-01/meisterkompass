"""Unit tests for shared Gebührenverzeichnis helpers and course/fee scrape split."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scrapers.exam_fee_tariff import (
    merge_tariff_rows_last_good,
    parse_berlin_meister_fees,
    parse_bremen_meister_fees,
    parse_bavaria_b_iv_meister_fees,
    parse_bw_322_meister_fees,
    parse_bw_meister_fees_from_html,
    parse_ulm_infoblatt_fees,
    parse_hamburg_meister_fees,
    parse_hesse_schedule_fees,
    parse_koblenz_meister_fees,
    parse_rheinhessen_meister_fees,
    parse_thuringia_meister_fees,
)
from scrapers import pipeline


KOBLENZ_SNIPPET = """
B.II.1 Abnahme von Prüfungsteilen der Meisterprüfung bzw. deren Wiederholung
B.II.1.a Prüfungsteil I: Praktische Prüfung bis 1.200,00
B.II.1.b Prüfungsteil II: Prüfung der fachtheoretischen Kenntnisse bis 600,00
B.II.1.c Prüfungsteil III: Prüfung der wirtschaftlichen und rechtlichen Kenntnisse  bis 400,00
B.II.1.d Prüfungsteil IV: Prüfung der berufs- und arbeitspädagogischen Kenntnisse bis 400,00
"""

RHEINHESSEN_SNIPPET = """
Gebühren für Meisterprüfung
Lfd. Nr. Beschreibung Gebühren in EURO
30 Antrag auf Zulassung zur Meisterprüfung 50
31 Abnahme einer Prüfung
• praktische Prüfung (Teil I)
• Prüfung der fachtheoretischen Kenntnisse (Teil II)
• Prüfung der wirtschaftlichen und rechtlichen Kenntnisse (Teil III)
• Prüfung der berufs- und arbeitspädagogischen Kenntnisse (Teil IV)
600 - 2000
300 - 700
220 - 300
220 - 500
32 Wiederholungsprüfungen
Gebühren für Fortbildung
"""

HESSE_SNIPPET = """
27 Meisterprüfung
a) Teil I 420,00
Teil II 420,00
Teil III 340,00
Teil IV 235,00
b) Gleichzeitige Ablegung von Prüfungsteilen
- Prüfungsabschnitt: Teil I und II 730,00
- Prüfungsabschnitt: Teil III und IV 490,00
c) Ablegung der einzelnen Teile der Meisterprüfung als Gesamtprüfung
Höchstbetrag 820,00
30 Fortbildungsprüfung
"""

BERLIN_SNIPPET = """
Meisterprüfung zu einem Prüfungstermin 462,00
b. Abnahme von Teilprüfungen
 Teil 1 315,00
 Teil 2 272,50
 Teil 3 168,75
 Teil 4 168,75
"""

HAMBURG_SNIPPET = """
Meisterprüfungen
aa) Prüfungsteil I 430,--
bb) Prüfungsteil II 430,--
cc) Prüfungsteil III 350,--
dd) Prüfungsteil IV 350,--
ee) Anmeldung zur Ablegung der gesamten Meisterprüfung (Teile I-IV im Zusammenhang) 1.300,--
"""

BW_322_SNIPPET = """
3.2.2 Meisterprüfung, Teile 1 - 4 zusammen 1.150,00
3.2.2.1 Teilgebühr für Prüfungsteil I 400,00
3.2.2.2 Teilgebühr für Prüfungsteil II 350,00
3.2.2.3 Teilgebühr für Prüfungsteil III 200,00
3.2.2.4 Teilgebühr für Prüfungsteil IV 200,00
"""

REUTLINGEN_SNIPPET = """
3.2.2 Meisterprüfung Teil I-IV zusammen
Teilgebühr Prüfungsteil I
Teilgebühr Prüfungsteil II
Teilgebühr Prüfungsteil III
Teilgebühr Prüfungsteil IV
1.100,00
300,00
350,00
200,00
250,00
3.2.3 Wiederholung
"""

ULM_SNIPPET = """
Meisterprüfungsgebühr sowie Nebenkosten
Die Meisterprüfungsgebühr von 1590 Euro (Teil I = 580 Euro, Teil II = 470 Euro, Teil III = 260 Euro, Teil IV =
280 Euro).
Handwerksberuf Nebenkosten in Euro
Bäcker 315
Elektrotechniker 850
Maler und Lackierer 210/270
Tischler 450
Der Aufstellung liegen die Erfahrungswerte
"""

HTML_BW_SNIPPET = """
Prüfungsgebühren
Teil I (praktischer Teil): 380 Euro
Teil II (fachtheoretischer Teil): 200 Euro
Teil III (Betriebswirtschaftlicher Teil): 250 Euro
Teil IV (AdA-Prüfung): 150 Euro
"""

BAVARIA_B_IV_SNIPPET = """
B. IV Meisterprüfung
Teil I 340,00
Teil II 290,00
Teil III 165,00
Teil IV 165,00
"""

BREMEN_SNIPPET = """
3. Abnahme und Wiederholung der Meisterprüfung
a) Teil I (Fachpraxis)
Tischler 400,00 €
b) Teil II (Fachtheorie)
Tischler 260,00 €
c) Teil III (gewerkeübergreifend) 220,00 €
D. Fortbildungsprüfungen
a) AEVO (Anerkennung als Teil 4 der Meisterprüfung möglich) 290,00 €
"""

THURINGIA_SNIPPET = """
5.1 Teil I 380,00 €
5.2 Teil II 380,00 €
5.3 Teil III 340,00 €
5.4 Teil IV 340,00 €
"""


class ExamFeeTariffParsersTest(unittest.TestCase):
    def test_parse_koblenz_ceiling_fees(self):
        fees, qualifier = parse_koblenz_meister_fees(KOBLENZ_SNIPPET)
        self.assertEqual(qualifier, "bis zu")
        self.assertEqual(fees, {1: 1200.0, 2: 600.0, 3: 400.0, 4: 400.0})

    def test_parse_rheinhessen_ranges(self):
        fees, fee_max = parse_rheinhessen_meister_fees(RHEINHESSEN_SNIPPET)
        self.assertEqual(fees, {1: 600.0, 2: 300.0, 3: 220.0, 4: 220.0})
        self.assertEqual(fee_max, {1: 2000.0, 2: 700.0, 3: 300.0, 4: 500.0})

    def test_parse_hesse_schedule_with_combos(self):
        fees, combos = parse_hesse_schedule_fees(HESSE_SNIPPET)
        self.assertEqual(fees, {1: 420.0, 2: 420.0, 3: 340.0, 4: 235.0})
        self.assertEqual(combos[(1, 2)], 730.0)
        self.assertEqual(combos[(3, 4)], 490.0)
        self.assertEqual(combos[(1, 2, 3, 4)], 820.0)

    def test_parse_berlin_meister_fees(self):
        fees, combos = parse_berlin_meister_fees(BERLIN_SNIPPET)
        self.assertEqual(fees, {1: 315.0, 2: 272.5, 3: 168.75, 4: 168.75})
        self.assertEqual(combos[(1, 2, 3, 4)], 462.0)

    def test_parse_hamburg_meister_fees(self):
        fees, combos = parse_hamburg_meister_fees(HAMBURG_SNIPPET)
        self.assertEqual(fees, {1: 430.0, 2: 430.0, 3: 350.0, 4: 350.0})
        self.assertEqual(combos[(1, 2, 3, 4)], 1300.0)

    def test_parse_bw_322_meister_fees(self):
        fees, combos = parse_bw_322_meister_fees(BW_322_SNIPPET)
        self.assertEqual(fees, {1: 400.0, 2: 350.0, 3: 200.0, 4: 200.0})
        self.assertEqual(combos[(1, 2, 3, 4)], 1150.0)

    def test_parse_bw_322_reutlingen_column_layout(self):
        fees, combos = parse_bw_322_meister_fees(REUTLINGEN_SNIPPET)
        self.assertEqual(fees, {1: 300.0, 2: 350.0, 3: 200.0, 4: 250.0})
        self.assertEqual(combos[(1, 2, 3, 4)], 1100.0)

    def test_parse_ulm_infoblatt_fees(self):
        generic, combos, trade_part1, trade_part1_max = parse_ulm_infoblatt_fees(ULM_SNIPPET)
        self.assertEqual(generic, {1: 580.0, 2: 470.0, 3: 260.0, 4: 280.0})
        self.assertEqual(combos[(1, 2, 3, 4)], 1590.0)
        self.assertEqual(trade_part1["Bäcker"], {1: 895.0})
        self.assertEqual(trade_part1["Elektrotechniker"], {1: 1430.0})
        self.assertEqual(trade_part1["Tischler"], {1: 1030.0})
        self.assertEqual(trade_part1["Maler und Lackierer"], {1: 790.0})
        self.assertEqual(trade_part1_max["Maler und Lackierer"], {1: 850.0})

    def test_parse_bw_meister_fees_from_html(self):
        fees, combos = parse_bw_meister_fees_from_html(HTML_BW_SNIPPET)
        self.assertEqual(fees, {1: 380.0, 2: 200.0, 3: 250.0, 4: 150.0})
        self.assertEqual(combos, {})

    def test_parse_bavaria_b_iv_meister_fees(self):
        fees = parse_bavaria_b_iv_meister_fees(BAVARIA_B_IV_SNIPPET)
        self.assertEqual(fees, {1: 340.0, 2: 290.0, 3: 165.0, 4: 165.0})

    def test_parse_bremen_trade_and_generic_fees(self):
        trade_fees, generic = parse_bremen_meister_fees(BREMEN_SNIPPET)
        self.assertEqual(trade_fees["Tischler"], {1: 400.0, 2: 260.0})
        self.assertEqual(generic, {3: 220.0, 4: 290.0})

    def test_parse_thuringia_meister_fees(self):
        fees = parse_thuringia_meister_fees(THURINGIA_SNIPPET)
        self.assertEqual(fees, {1: 380.0, 2: 380.0, 3: 340.0, 4: 340.0})

    def test_merge_tariff_rows_keeps_last_good_on_empty(self):
        previous = [
            {"chamber_slug": "hwk-a", "part": 1, "fee": 100.0},
            {"chamber_slug": "hwk-b", "part": 1, "fee": 200.0},
        ]
        fresh = {
            "hwk-a": [{"chamber_slug": "hwk-a", "part": 1, "fee": 111.0}],
            "hwk-b": [],  # failed scrape
        }
        merged = merge_tariff_rows_last_good(previous, fresh)
        by_chamber = {row["chamber_slug"]: row["fee"] for row in merged}
        self.assertEqual(by_chamber["hwk-a"], 111.0)
        self.assertEqual(by_chamber["hwk-b"], 200.0)


class CourseFeeSplitTest(unittest.TestCase):
    def test_daily_finalize_reuses_stored_tariffs(self):
        tariff = [{
            "chamber_slug": "hwk-demo",
            "trade_slug": None,
            "part": 3,
            "fee": 340.0,
            "qualifier": "",
            "source_url": "https://example.test/fees",
        }]
        course_row = {
            "chamber_slug": "hwk-demo",
            "chamber_name": "HWK Demo",
            "chamber_region": "Hessen",
            "trade_slug": "sonstige",
            "trade_name": "Sonstige",
            "title": "Meistervorbereitung Teil III",
            "parts": [3],
            "format": "part_time",
            "format_display": "Teilzeit",
            "teaching_mode": "presence",
            "start_date": "2099-01-15",
            "end_date": "2099-06-01",
            "start_date_note": "",
            "duration_hours": None,
            "course_fee": 1000.0,
            "course_fee_display": "1.000 €",
            "exam_fee_scraped": None,
            "exam_fee_qualifier": "",
            "exam_fee": None,
            "city": "Demo",
            "street": "",
            "zip_code": "",
            "latitude": None,
            "longitude": None,
            "availability": "available",
            "source_url": "https://example.test/course",
        }

        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "manual").mkdir()
            (data_dir / "cache").mkdir()
            courses_path = data_dir / "courses.json"
            archive_path = data_dir / "courses_archive.json"
            fees_path = data_dir / "scraped_exam_fees.json"
            courses_path.write_text("[]\n", encoding="utf-8")
            archive_path.write_text("[]\n", encoding="utf-8")
            fees_path.write_text(json.dumps({"rows": tariff}), encoding="utf-8")
            (data_dir / "manual" / "exam_fees_manual.json").write_text("[]\n", encoding="utf-8")
            (data_dir / "exam_fees.json").write_text(json.dumps({"nested": {}}), encoding="utf-8")
            (data_dir / "chambers.json").write_text("[]\n", encoding="utf-8")

            batch = pipeline.ScrapeBatch(
                fresh_by_chamber={"hwk-demo": [course_row]},
                scraped_exam_rows=[],  # daily: no published tariffs in batch
                results={},
                per_chamber={"hwk-demo": 1},
            )
            # Pretend the chamber scraped successfully so nested fees update.
            from scrapers.base import ScrapeResult
            batch.results["hwk-demo"] = ScrapeResult(
                chamber_slug="hwk-demo",
                chamber_name="HWK Demo",
                chamber_region="Hessen",
                chamber_website="https://example.test",
            )

            with patch.object(pipeline, "DATA_DIR", data_dir), \
                 patch.object(pipeline, "COURSES_JSON", courses_path), \
                 patch.object(pipeline, "ARCHIVE_JSON", archive_path), \
                 patch.object(pipeline, "SCRAPED_EXAM_FEES_JSON", fees_path), \
                 patch.object(pipeline, "MANUAL_FEES_JSON", data_dir / "manual" / "exam_fees_manual.json"), \
                 patch.object(pipeline, "GEOCODE_CACHE", data_dir / "cache" / "geocode_cache.json"), \
                 patch.object(pipeline, "apply_coordinates", lambda records, geocoder: None), \
                 patch.object(pipeline, "Geocoder") as geo_cls:
                geo_cls.return_value.save = lambda: None
                pipeline._finalize_batch(batch, "2099-01-01", update_courses=True)

            written = json.loads(courses_path.read_text(encoding="utf-8"))
            self.assertEqual(len(written), 1)
            # Part 3 tariff present; part 4 missing → sum may be incomplete, but
            # from_tariff path should still engage for available parts.
            exam = written[0]["exam_fee"]
            self.assertTrue(exam.get("from_tariff") or exam.get("fee") is not None)


if __name__ == "__main__":
    unittest.main()
