import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_karlsruhe import (
    COURSE_SECTIONS,
    HwkKarlsruheScraper,
    parse_availability as parse_karlsruhe_availability,
)
from scrapers.hwk_mannheim import (
    HwkMannheimScraper,
    parse_parts,
    parse_trade,
)
from scrapers.hwk_stuttgart import COURSES as STUTTGART_COURSES, HwkStuttgartScraper
from scrapers.hwk_ulm import HwkUlmScraper, parse_title as parse_ulm_title


def course_card(title: str, details: str, href: str = "/kurse/example,coursedetail.html?id=1") -> BeautifulSoup:
    return BeautifulSoup(
        f"""
        <div class="row">
          <h3>01.09.2026 - 20.11.2026: Vollzeit
            <a href="{href}">{title}</a>
          </h3>
          <div>{details}</div>
        </div>
        """,
        "html.parser",
    )


class MannheimParserTests(unittest.TestCase):
    def test_parts_and_trade_variants(self):
        title = "Meistervorbereitung Maler und Lackierer Teil I + II Maler"
        parts = parse_parts(title)
        self.assertEqual(parts, [1, 2])
        self.assertEqual(parse_trade(title, parts), "Maler und Lackierer")

        aevo = "Ausbilderschein - Vorbereitung auf die AEVO Prüfung (Meister Teil IV)"
        self.assertEqual(parse_parts(aevo), [4])
        self.assertIsNone(parse_trade(aevo, [4]))

    def test_card_parses_fee_duration_dates_and_waitlist(self):
        soup = course_card(
            "Meistervorbereitung Teil III + IV",
            "3.250,00 € 400 UE Mannheim Warteliste",
        )
        offer = HwkMannheimScraper()._parse_card(soup.select_one("a"))

        self.assertEqual(offer.parts, [3, 4])
        self.assertIsNone(offer.trade_name)
        self.assertEqual(offer.start_date, "2026-09-01")
        self.assertEqual(offer.end_date, "2026-11-20")
        self.assertEqual(offer.course_fee, 3250.0)
        self.assertEqual(offer.duration_hours, 400)
        self.assertEqual(offer.availability, "waitlist")
        self.assertEqual(offer.format_key, "full_time")

    def test_card_keeps_unpublished_fee_as_none(self):
        soup = course_card(
            "Meistervorbereitung Konditoren Teil I + II",
            "400 UE Mannheim Gebühren stehen noch nicht fest",
        )
        offer = HwkMannheimScraper()._parse_card(soup.select_one("a"))
        self.assertEqual(offer.trade_name, "Konditor")
        self.assertIsNone(offer.course_fee)


class KarlsruheParserTests(unittest.TestCase):
    def test_manual_exam_fees_include_parts_and_complete_bundle(self):
        fee_path = Path(__file__).resolve().parents[1] / "data" / "manual" / "exam_fees_manual.json"
        lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))

        expected_parts = {1: 400.0, 2: 350.0, 3: 200.0, 4: 200.0}
        for chamber_slug in ("hwk-karlsruhe", "hwk-mannheim"):
            for part, expected_fee in expected_parts.items():
                resolved = resolve_exam_fee(chamber_slug, "any-trade", [part], None, lookup)
                self.assertEqual(resolved["fee"], expected_fee)

            bundle = resolve_exam_fee(chamber_slug, "any-trade", [1, 2, 3, 4], None, lookup)
            self.assertEqual(bundle["fee"], 1150.0)
            self.assertEqual(bundle["display"], "1.150 €")

    def test_section_uses_known_trade_and_parts(self):
        section = COURSE_SECTIONS[3]
        soup = course_card(
            "Meistervorbereitung für Elektrotechnik Teil 1-4",
            "Karlsruhe",
        )
        detail = BeautifulSoup(
            """
            <h1>Meistervorbereitung für Elektrotechnik</h1>
            <p>ausgebucht</p>
            <h3>Gebühren</h3><p>Kurs: 8.500,00 €</p>
            <h3>Unterricht</h3>
            <p>31.08.2026 - 31.01.2029</p>
            <p>montags bis donnerstags, mit Online-Anteilen</p>
            <p>Abend</p><p>Lehrgangsdauer 1290 UE</p>
            <h3>Lehrgangsort</h3><p>Hertzstr. 177<br>76187 Karlsruhe</p>
            <p>Benjamin Sorenson<br>Tel. 0721 1600-430</p>
            """,
            "html.parser",
        )
        scraper = HwkKarlsruheScraper()
        scraper.parse_html = lambda _url: detail
        offers = scraper._parse_section(soup, section)

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].trade_name, "Elektrotechniker")
        self.assertEqual(offers[0].parts, [1, 2, 3, 4])
        self.assertEqual(offers[0].course_fee, 8500.0)
        self.assertEqual(offers[0].availability, "full")
        self.assertEqual(offers[0].format_key, "part_time")
        self.assertEqual(offers[0].teaching_mode, "hybrid")
        self.assertEqual(offers[0].street, "Hertzstr. 177")

    def test_placeholder_preserves_unscheduled_offering(self):
        section = COURSE_SECTIONS[0]
        offer = HwkKarlsruheScraper._placeholder(section)
        self.assertEqual(offer.parts, [1])
        self.assertEqual(offer.format_key, "part_or_full")
        self.assertIsNone(offer.start_date)
        self.assertIsNone(offer.course_fee)
        self.assertEqual(offer.source_url, section.url)

    def test_availability_vocabulary(self):
        self.assertEqual(parse_karlsruhe_availability("wenige Plätze"), "available")
        self.assertEqual(parse_karlsruhe_availability("Warteliste"), "waitlist")
        self.assertEqual(parse_karlsruhe_availability("Termin folgt"), "unknown")


class StuttgartParserTests(unittest.TestCase):
    def test_manual_exam_fees(self):
        fee_path = Path(__file__).resolve().parents[1] / "data" / "manual" / "exam_fees_manual.json"
        lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))
        expected = {1: 360.0, 2: 330.0, 3: 180.0, 4: 180.0}
        for part, fee in expected.items():
            resolved = resolve_exam_fee("hwk-stuttgart", "any-trade", [part], None, lookup)
            self.assertEqual(resolved["fee"], fee)

    def test_appointment_data_attributes_are_authoritative(self):
        spec = next(course for course in STUTTGART_COURSES if course.slug == "meisterkurs-teil-3")
        soup = BeautifulSoup(
            """
            <div class="appointment-listing-container">
              <div class="card"
                   data-appointment-id="158040"
                   data-appointment-price="1790.0"
                   data-appointment-teaching-units="203"
                   data-appointment-learning-method="Blended Learning"
                   data-appointment-start-date="05/03/2027"
                   data-appointment-end-date="31/07/2027">
                05.03.2027 - 31.07.2027 € 1.790,-
              </div>
            </div>
            """,
            "html.parser",
        )
        offers = HwkStuttgartScraper()._parse_course(soup, spec)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].parts, [3])
        self.assertEqual(offers[0].start_date, "2027-03-05")
        self.assertEqual(offers[0].end_date, "2027-07-31")
        self.assertEqual(offers[0].course_fee, 1790.0)
        self.assertEqual(offers[0].duration_hours, 203)
        self.assertEqual(offers[0].teaching_mode, "hybrid")

    def test_stuttgart_placeholder_keeps_published_fee_and_duration(self):
        spec = next(course for course in STUTTGART_COURSES if course.slug == "shk-meister")
        soup = BeautifulSoup("<main>Dauer: 2 Jahre, 1.160 Unterrichtseinheiten Termine auf Anfrage</main>", "html.parser")
        offer = HwkStuttgartScraper._placeholder(soup, spec)
        self.assertIsNone(offer.start_date)
        self.assertEqual(offer.duration_hours, 1160)
        self.assertEqual(offer.course_fee, 6420.0)


class UlmParserTests(unittest.TestCase):
    def test_manual_exam_fees_and_complete_bundle(self):
        fee_path = Path(__file__).resolve().parents[1] / "data" / "manual" / "exam_fees_manual.json"
        lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))
        expected = {1: 580.0, 2: 470.0, 3: 260.0, 4: 280.0}
        for part, fee in expected.items():
            resolved = resolve_exam_fee("hwk-ulm", "any-trade", [part], None, lookup)
            self.assertEqual(resolved["fee"], fee)

        bundle = resolve_exam_fee("hwk-ulm", "any-trade", [1, 2, 3, 4], None, lookup)
        self.assertEqual(bundle["fee"], 1570.0)
        self.assertEqual(bundle["display"], "1.570 €")

    def test_title_mapping(self):
        self.assertEqual(
            parse_ulm_title("Meisterkurs Kraftfahrzeugtechnik Teil I und II in Teilzeit"),
            ("Kfz.-Techniker", [1, 2]),
        )
        self.assertEqual(
            parse_ulm_title("Meisterkurs Teil IV - Ausbilderschein nach AEVO in Vollzeit"),
            (None, [4]),
        )

    def test_multiple_structured_runs_are_parsed_independently(self):
        soup = BeautifulSoup(
            """
            <div class="col-sm-6">
              <strong>Nächster Termin</strong>
              11.09.2026 - 19.06.2027 Es gibt noch freie Plätze
              Kurstyp Teilzeitlehrgang, 884 UE
              Kursort Bildungsakademie Ulm, Ulm
              Kurs-Nr. Kurs 25, 1-MV-METALL-TZ
              Gebühr 7.370 Euro
            </div>
            <div class="col-sm-6">
              <strong>Termin</strong>
              10.09.2027 - 24.06.2028 Kurs ausgebucht
              Kurstyp Teilzeitlehrgang, 884 UE
              Kursort Bildungsakademie Ulm, Ulm
              Kurs-Nr. Kurs 26, 1-MV-METALL-TZ
              Gebühr 7.370 Euro
            </div>
            """,
            "html.parser",
        )
        offers = HwkUlmScraper()._parse_runs(
            soup,
            "https://www.hwk-ulm.de/seminar/1-mv-metall-tz/",
            "Meisterkurs Metallbau Teil I und II in Teilzeit",
            "Metallbauer",
            [1, 2],
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual([offer.start_date for offer in offers], ["2026-09-11", "2027-09-10"])
        self.assertEqual([offer.availability for offer in offers], ["available", "full"])
        self.assertTrue(all(offer.course_fee == 7370.0 for offer in offers))

    def test_planned_run_is_retained_without_dates(self):
        soup = BeautifulSoup(
            """
            <div class="col-sm-6">
              <strong>Nächster Termin</strong><strong>Termine in Planung</strong>
              Kurstyp Teilzeitlehrgang, 610 UE
              Kursort Ulm
              Kurs-Nr. 1-MV-FLIESEN
            </div>
            """,
            "html.parser",
        )
        offers = HwkUlmScraper()._parse_runs(
            soup,
            "https://www.hwk-ulm.de/seminar/1-mv-fliesen-platten/",
            "Meisterkurs Fliesen-, Platten- und Mosaikleger Teil I und II in Teilzeit",
            "Fliesen-, Platten- und Mosaikleger",
            [1, 2],
        )
        self.assertEqual(len(offers), 1)
        self.assertIsNone(offers[0].start_date)
        self.assertEqual(offers[0].duration_hours, 610)


if __name__ == "__main__":
    unittest.main()
