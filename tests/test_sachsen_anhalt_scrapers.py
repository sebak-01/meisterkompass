import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.base import RawCourseOffer
from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_halle_saale import (
    HwkHalleSaaleScraper,
    parse_halle_title,
    _location,
)
from scrapers.hwk_magdeburg import (
    HwkMagdeburgScraper,
    _clean_card_title,
)
from scrapers.pipeline import SCRAPERS


class SachsenAnhaltParserTests(unittest.TestCase):
    def test_halle_title_parsing(self):
        self.assertEqual(
            parse_halle_title("Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)"),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_halle_title("Meistervorbereitungslehrgang Kraftfahrzeugtechnik Teil 1 und 2"),
            ([1, 2], "Kfz.-Techniker"),
        )
        self.assertEqual(
            parse_halle_title("Meistervorbereitungslehrgang Maler Teil 1 und 2 (Vollzeit)"),
            ([1, 2], "Maler und Lackierer"),
        )
        self.assertEqual(
            parse_halle_title("Meistervorbereitungslehrgang Zimmerer Teil 1 und Teil 2"),
            ([1, 2], "Zimmerer"),
        )

    def test_halle_discovery_deduplicates_seminar_links(self):
        soup = BeautifulSoup(
            """
            <a href="/seminar/mvl-el-teil-1und2-v/">Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)</a>
            <a href="/seminar/mvl-el-teil-1und2-v/?ref=home">Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)</a>
            <a href="/seminar/mathe/">Mathematik für Meisterschüler</a>
            """,
            "html.parser",
        )
        courses = HwkHalleSaaleScraper._discover(soup)
        self.assertEqual(
            courses,
            [(
                "Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)",
                "https://www.hwkhalle.de/seminar/mvl-el-teil-1und2-v/",
            )],
        )

    def test_halle_multi_run_detail_parses_runs(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)</h1>
              <section>
                <h4>28.09.2026 — 15.08.2027, MVL EL - 1/26 VZ</h4>
                <p>Keine Plätze mehr frei</p>
                <h4>Kosten</h4><p>Entgelt Meisterausbildung: 10.660,00 €</p>
                <h4>Kursnummer</h4><p>27702</p>
                <h4>Kurstyp</h4><p>Vollzeit</p>
                <h4>Veranstaltungsort</h4>
                <p>BTZ der Handwerkskammer Halle (Saale), Standort Halle-Osendorf</p>
                <p>HWK 02.G 04</p>
                <p>Straße der Handwerker 2</p>
                <p>06132 Halle (Saale)</p>
              </section>
            </main>
            """,
            "html.parser",
        )
        offers = HwkHalleSaaleScraper()._parse_course(
            soup,
            "Meistervorbereitungslehrgang Elektrotechnik Teil 1 und 2 (Vollzeit)",
            "https://www.hwkhalle.de/seminar/mvl-el-teil-1und2-v/",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].trade_name, "Elektrotechniker")
        self.assertEqual(offers[0].course_fee, 10660.0)
        self.assertEqual(offers[0].availability, "full")
        self.assertEqual(offers[0].street, "Straße der Handwerker 2")
        self.assertEqual(offers[0].zip_code, "06132")
        self.assertEqual(offers[0].city, "Halle (Saale)")

    def test_halle_location_ignores_kursnummer_as_zip_code(self):
        text = """
        Kursnummer
        27703
        Kurstyp
        Vollzeit
        Veranstaltungsort
        BTZ der Handwerkskammer Halle (Saale), Standort Halle-Osendorf
        HWK 02.G 04
        Straße der Handwerker 2
        06132 Halle (Saale)
        """
        self.assertEqual(
            _location(text, "presence"),
            ("Straße der Handwerker 2", "06132", "Halle (Saale)"),
        )

    def test_halle_normalizes_bare_halle_city_name(self):
        text = """
        Veranstaltungsort
        Handwerkskammer Halle (Saale)
        Graefestr. 24
        06110 Halle
        """
        self.assertEqual(
            _location(text, "presence"),
            ("Graefestr. 24", "06110", "Halle (Saale)"),
        )

    def test_halle_parses_trade_specific_part_i_exam_fees(self):
        text = """
        a) Teil I
        Nr.5 Meisterprüfung: Elektrotechnik 430,00 €
        Nr.2 Meisterprüfung: Kraftfahrzeugtechnik 370,00 €
        Nr.12 Meisterprüfung: Maler / Lackierer 489,00 €
        b) Teil II 323,00 €
        c) Teil III 208,00 €
        d) Teil IV 210,00 €
        """
        self.assertEqual(
            HwkHalleSaaleScraper.parse_part_i_exam_fees(text),
            {
                "Elektrotechniker": 430.0,
                "Kfz.-Techniker": 370.0,
                "Maler und Lackierer": 489.0,
            },
        )
        self.assertEqual(
            HwkHalleSaaleScraper.parse_generic_exam_fees(text),
            {2: 323.0, 3: 208.0, 4: 210.0},
        )

    def test_halle_collect_resolves_trade_specific_exam_fees(self):
        scraper = HwkHalleSaaleScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value=({"Elektrotechniker": 430.0}, {2: 323.0}),
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        resolved = resolve_exam_fee(
            scraper.chamber_slug, "elektrotechniker", [1, 2], None, lookup
        )
        self.assertEqual(resolved["fee"], 753.0)

    def test_magdeburg_keeps_course_page_exam_fee(self):
        offer = RawCourseOffer(
            title="Elektrotechniker (Teile I + II)",
            trade_name="Elektrotechniker",
            parts=[1, 2],
            format_key="full_time",
            teaching_mode="presence",
            start_date="2026-08-24",
            end_date="2027-05-15",
            duration_hours=978,
            course_fee=9000.0,
            exam_fee_scraped=855.0,
            city="Magdeburg",
        )
        result = HwkMagdeburgScraper().postprocess_offer(offer)
        self.assertEqual(result.exam_fee_scraped, 855.0)

        lookup = build_exam_fee_lookup(
            [
                {
                    "chamber_slug": "hwk-magdeburg",
                    "trade_slug": "elektrotechniker",
                    "part": 1,
                    "fee": 625.0,
                    "qualifier": "",
                },
                {
                    "chamber_slug": "hwk-magdeburg",
                    "trade_slug": "elektrotechniker",
                    "part": 2,
                    "fee": 230.0,
                    "qualifier": "",
                },
            ],
            [],
        )
        from_page = resolve_exam_fee(
            "hwk-magdeburg", "elektrotechniker", [1, 2], 855.0, lookup
        )
        self.assertEqual(from_page["fee"], 855.0)
        self.assertFalse(from_page["from_tariff"])
        from_tariff = resolve_exam_fee(
            "hwk-magdeburg", "elektrotechniker", [1, 2], None, lookup
        )
        self.assertEqual(from_tariff["fee"], 855.0)
        self.assertTrue(from_tariff["from_tariff"])

    def test_magdeburg_prefers_month_year_course_window_over_anmeldeschluss(self):
        main_text = """
        genauer Termin steht noch nicht fest
        09.2028 - 05.2029
        Lehrgangsdauer 978 Std.
        Anmeldeschluss
        07.08.2028
        Alle Termine
        22.02.2027 - 03.07.2027: Vollzeit
        """
        start, end, note = HwkMagdeburgScraper().resolve_schedule_dates(None, {}, main_text)
        self.assertEqual(start, "2028-09-01")
        self.assertEqual(end, "2029-05-01")
        self.assertEqual(note, "Genauer Termin steht noch nicht fest.")

    def test_magdeburg_strips_stock_image_prefix_from_card_title(self):
        raw = (
            "Gorodenkoff - stock.adobe.com 24.08.2026 - 04.12.2026:\xa0Vollzeit "
            "Meisterausbildung Teile III und IV oder AdA"
        )
        self.assertTrue(_clean_card_title(raw).startswith("24.08.2026"))

    def test_magdeburg_article_card_parsing(self):
        soup = BeautifulSoup(
            """
            <div class="row">
              <a href="/kurse/foo-16,0,coursedetail_BBZ.html?id=12345">
                Anne-Kristin Gotot - HWK Magdeburg 24.08.2026 - 15.05.2027:
                Vollzeit Vorbereitung auf die Elektrotechnikermeisterprüfung
              </a>
            </div>
            """,
            "html.parser",
        )
        link = soup.select_one("a")
        card = HwkMagdeburgScraper()._parse_magdeburg_card(
            link,
            "https://www.hwk-magdeburg.de/16,0,coursedetail.html?id=12345",
            article_title="Meister im Elektrotechnikerhandwerk",
        )
        self.assertEqual(card["parts"], [1, 2])
        self.assertEqual(card["trade_name"], "Elektrotechniker")
        self.assertEqual(card["start_date"], "2026-08-24")

    def test_magdeburg_parses_trade_specific_exam_fees_from_pdf_text(self):
        text = """
        2.1. Elektrotechnik
        2.1.1. Teil I 625,00
        2.1.2. Teil II 230,00
        2.2. Friseur
        2.2.1. Teil I 335,00
        2.2.2. Teil II 195,00
        2.9. Teil III 250,00
        2.10. Teil IV 240,00
        """
        self.assertEqual(
            HwkMagdeburgScraper.parse_trade_exam_fees(text),
            {
                "Elektrotechniker": {1: 625.0, 2: 230.0},
                "Friseur": {1: 335.0, 2: 195.0},
            },
        )
        self.assertEqual(
            HwkMagdeburgScraper.parse_generic_exam_fees(text),
            {3: 250.0, 4: 240.0},
        )

    def test_magdeburg_collect_resolves_trade_specific_exam_fees(self):
        scraper = HwkMagdeburgScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value=({"Elektrotechniker": {1: 625.0, 2: 230.0}}, {3: 250.0, 4: 240.0}),
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "elektrotechniker", [1, 2], None, lookup)["fee"],
            855.0,
        )
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [3, 4], None, lookup)["fee"],
            490.0,
        )


class SachsenAnhaltIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered_with_issue_slugs(self):
        expected = {
            "hwk-halle-saale": HwkHalleSaaleScraper,
            "hwk-magdeburg": HwkMagdeburgScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Sachsen-Anhalt")


if __name__ == "__main__":
    unittest.main()
