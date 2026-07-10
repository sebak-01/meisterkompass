import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_freiburg import COURSES as FREIBURG_COURSES, HwkFreiburgScraper
from scrapers.hwk_heilbronn import COURSES as HEILBRONN_COURSES, HwkHeilbronnScraper
from scrapers.hwk_karlsruhe import (
    COURSE_SECTIONS,
    HwkKarlsruheScraper,
    parse_availability as parse_karlsruhe_availability,
)
from scrapers.hwk_konstanz import COURSES as KONSTANZ_COURSES, HwkKonstanzScraper
from scrapers.hwk_reutlingen import COURSES as REUTLINGEN_COURSES, HwkReutlingenScraper
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


class FreiburgParserTests(unittest.TestCase):
    def test_numeric_appointment_parses_current_values(self):
        soup = BeautifulSoup(
            """
            <main>
              Termine: 17.11.2026 - 28.05.2027, Freiburg (3 freie Plätze)
              Freie Plätze: 3
              Zeiten: Mo-Do 8:00-16:15 Uhr
              Dauer: 850 Unterrichtsstunden
              Preis: € 9200,00
              Preisinfo: Zzgl. € 750,00 Prüfungsgebühr (Stand Okt. 2024)
            </main>
            """,
            "html.parser",
        )
        offer = HwkFreiburgScraper._parse_appointment(
            soup,
            "https://www.gewerbeakademie.de/weiterbildung/kursangebot/seminar/mvkfeinwerk/32/",
            FREIBURG_COURSES["mvkfeinwerk"],
        )
        self.assertEqual(offer.start_date, "2026-11-17")
        self.assertEqual(offer.course_fee, 9200.0)
        self.assertEqual(offer.exam_fee_scraped, 750.0)
        self.assertEqual(offer.duration_hours, 850)
        self.assertEqual(offer.format_key, "full_time")
        self.assertEqual(offer.teaching_mode, "presence")
        self.assertEqual(offer.availability, "available")


class KonstanzParserTests(unittest.TestCase):
    def test_vernr_cards_are_independent_runs(self):
        soup = BeautifulSoup(
            """
            <a class="termin_details" vernr="1001">08.03.2027 – 08.10.2027: Teilzeit Rottweil</a>
            <div id="uni-kurs-1001">
              ausreichend freie Plätze Kosten 4.090,00 €
              Unterricht 08.03.2027 – 08.10.2027
              Lehrgangsdauer 300 UE
              Lehrgangsort Steinhauserstraße 18 78628 Rottweil
              Kurs buchen
            </div>
            <a class="termin_details" vernr="1002">06.03.2028 – 13.10.2028: Teilzeit Rottweil</a>
            <div id="uni-kurs-1002">
              ausgebucht Kosten 4.190,00 €
              Unterricht 06.03.2028 – 13.10.2028
              Lehrgangsdauer 300 UE
              Lehrgangsort Steinhauserstraße 18 78628 Rottweil
              Warteliste
            </div>
            """,
            "html.parser",
        )
        offers = HwkKonstanzScraper()._parse_course(
            soup,
            "https://www.bildungsakademie.de/seminar/mv_baecker/",
            KONSTANZ_COURSES["mv_baecker"],
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual([offer.course_fee for offer in offers], [4090.0, 4190.0])
        self.assertEqual([offer.availability for offer in offers], ["available", "full"])


class ReutlingenParserTests(unittest.TestCase):
    def test_plain_date_heading_parses_run_not_next_summary(self):
        spec = next(item for item in REUTLINGEN_COURSES if item.slug == "t-mv-i-ii_metall-tz")
        soup = BeautifulSoup(
            """
            <main>
              <h4>Nächster Kurs: 10.11.2026 — 30.10.2027</h4>
              <div><h4>10.11.2026 — 30.10.2027</h4>
                Es gibt noch freie Plätze Bildungsakademie Tübingen
                Seminardauer 700 Unterrichtseinheiten Kosten 8.250,00 €
                Kursnummer 8 Kurstyp Teilzeit
              </div>
            </main>
            """,
            "html.parser",
        )
        offers = HwkReutlingenScraper()._parse_course(soup, spec)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].start_date, "2026-11-10")
        self.assertEqual(offers[0].course_fee, 8250.0)
        self.assertEqual(offers[0].city, "Tübingen")

    def test_combined_module_fee_is_used(self):
        spec = next(item for item in REUTLINGEN_COURSES if item.slug == "r-mv-iii-iv-vz")
        soup = BeautifulSoup(
            """
            <main><div><h4>28.09.2027 — 07.12.2027</h4>
              Es gibt noch freie Plätze Seminardauer 355 Unterrichtseinheiten
              Kursnummer 19 Kurstyp Vollzeit
              Teil III und Teil IV 28.09.2027 - 07.12.2027 2.950,00 €
              Teil III 1.995,00 € Teil IV 950,00 €
            </div></main>
            """,
            "html.parser",
        )
        offers = HwkReutlingenScraper()._parse_course(soup, spec)
        self.assertEqual(offers[0].course_fee, 2950.0)


class HeilbronnParserTests(unittest.TestCase):
    def test_run_and_hybrid_location_override(self):
        spec = next(item for item in HEILBRONN_COURSES if item.slug == "mv-iiiiv-e-learning")
        soup = BeautifulSoup(
            """
            <main><div><h4>07.10.2028 — 14.07.2029</h4>
              Es gibt noch freie Plätze Handwerkskammer Heilbronn Allee 76 74072 Heilbronn
              Online und Präsenz Seminardauer 320 Stunden Gebühr 2.090 EURO
              Kursnummer 3 Kurstyp Teilzeit
            </div></main>
            """,
            "html.parser",
        )
        offers = HwkHeilbronnScraper()._parse_course(soup, spec)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].teaching_mode, "hybrid")
        self.assertEqual(offers[0].street, "Allee 76")
        self.assertEqual(offers[0].course_fee, 2090.0)


if __name__ == "__main__":
    unittest.main()
