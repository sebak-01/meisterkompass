import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_cottbus import (
    EXAM_FEES_PAGE_URL as COTTBUS_EXAM_FEES_PAGE_URL,
    HwkCottbusScraper,
    parse_cottbus_title,
)
from scrapers.hwk_frankfurt_oder_ostbrandenburg import (
    EXAM_FEES_PDF_URL as OB_EXAM_FEES_PDF_URL,
    HwkFrankfurtOderOstbrandenburgScraper,
    _parse_exam_fee_from_page,
    parse_ostbrandenburg_title,
)
from scrapers.hwk_potsdam import (
    EXAM_FEES_PAGE_URL as POTSDAM_EXAM_FEES_PAGE_URL,
    HwkPotsdamScraper,
    _normalize_city,
)
from scrapers.pipeline import SCRAPERS


class BrandenburgParserTests(unittest.TestCase):
    def test_potsdam_title_parsing_via_odav_card(self):
        soup = BeautifulSoup(
            """
            <div class="row">
              <h3><a href="/kurse/meisterausbildung-elektrotechnikerhandwerk-teil-i-9,0,coursedetail.html?id=1">
                Meisterausbildung Elektrotechnikerhandwerk Teil I
              </a></h3>
              <div>7.500,00 €</div>
              <div>248 Std.</div>
              <div>ausreichend freie Plätze</div>
            </div>
            """,
            "html.parser",
        )
        link = soup.select_one("a[href*='coursedetail']")
        card = HwkPotsdamScraper()._parse_card(link)
        self.assertEqual(card["parts"], [1])
        self.assertEqual(card["trade_name"], "Elektrotechniker")

    def test_potsdam_normalizes_city_without_ortsteil(self):
        self.assertEqual(
            _normalize_city("Groß Kreutz (Havel) Ortsteil Götz"),
            "Groß Kreutz (Havel)",
        )
        self.assertEqual(
            _normalize_city("Nuthetal Ortsteil Bergholz-Rehbrücke"),
            "Nuthetal",
        )

    def test_potsdam_resolves_latest_exam_fee_pdf(self):
        scraper = HwkPotsdamScraper()
        pdf_url = scraper._resolve_exam_fees_pdf_url()
        self.assertIn("14516", pdf_url)

    def test_potsdam_availability_from_detail(self):
        scraper = HwkPotsdamScraper()
        offer = scraper.transform_offer(
            scraper.postprocess_offer(
                type("Offer", (), {
                    "availability": "unknown",
                    "exam_fee_scraped": 100.0,
                    "exam_fee_qualifier": "x",
                    "city": "Groß Kreutz (Havel) Ortsteil Götz",
                    "scraped_raw": {},
                })()
            ),
            "Anmelden für die Warteliste\nausreichend freie Plätze",
        )
        self.assertEqual(offer.availability, "waitlist")
        self.assertEqual(offer.city, "Groß Kreutz (Havel)")

    def test_cottbus_title_parsing(self):
        self.assertEqual(
            parse_cottbus_title(
                "Installateur und Heizungsbauer - Meistervorbereitungslehrgang Teil I und II - Vollzeit Gallinchen"
            ),
            ([1, 2], "Installateur- und Heizungsbauer"),
        )
        self.assertEqual(
            parse_cottbus_title("Kosmetiker/in Teil II und I - Vollzeit  Ausbildungsort Frankfurt (Oder)"),
            ([1, 2], "Kosmetiker"),
        )
        self.assertEqual(
            parse_cottbus_title(
                "Straßenbauer - Meistervorbereitungslehrgang Teil I und II - Vollzeit Großräschen"
            ),
            ([1, 2], "Straßenbauer"),
        )

    def test_cottbus_parses_exam_fees_from_pdf_text(self):
        text = """
        B.III.3.1 Prüfungsgebühr Teil I - Grundgebühr 510,00
        B.III.3.2 Prüfungsgebühr Teil II 315,00
        B.III.3.3 Prüfungsgebühr Teil III 200,00
        B.III.3.4 Prüfungsgebühr Teil IV 255,00
        """
        self.assertEqual(
            HwkCottbusScraper.parse_meister_exam_fees(text),
            {1: 510.0, 2: 315.0, 3: 200.0, 4: 255.0},
        )

    def test_ostbrandenburg_title_parsing(self):
        self.assertEqual(
            parse_ostbrandenburg_title(
                "Meisterkurs im Elektrotechniker-Handwerk (Teile I und II)"
            ),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_ostbrandenburg_title(
                "Geprüfte/r Fachfrau/-mann für kaufm. Betriebsführung nach der HWO (Teil III)"
            ),
            ([3], None),
        )

    def test_ostbrandenburg_parses_course_runs(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Meisterkurs im Elektrotechniker-Handwerk (Teile I und II)</h1>
              <p>Lehrgangskosten: 11200,00 EUR</p>
              <p>Prüfungskosten: 680,00 EUR</p>
              <p>ca. 1.200 Unterrichtsstunden</p>
              <div class="hwk-course-app-wrapper">
                06.11.2026 - 12.05.2028
                Berufsbegleitend
                Frankfurt (Oder)
                Fr.: 15:00 - 20:00 Uhr
                Kurs buchen
              </div>
              <div class="hwk-course-app-wrapper">
                14.06.2027 - 06.05.2028
                Vollzeit
                Frankfurt (Oder)
                Mo.-Fr.: 08:00 - 15:00 Uhr
                Kurs buchen
              </div>
            </main>
            """,
            "html.parser",
        )
        offers = HwkFrankfurtOderOstbrandenburgScraper()._parse_course(
            soup,
            "Meisterkurs im Elektrotechniker-Handwerk (Teile I und II)",
            "https://www.weiterbildung-ostbrandenburg.de/lehrgang/meisterkurs-teile-i-und-ii-im-elektrotechniker-handwerk/",
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].trade_name, "Elektrotechniker")
        self.assertEqual(offers[0].course_fee, 11200.0)
        self.assertEqual(offers[0].exam_fee_scraped, 680.0)
        self.assertEqual(offers[0].duration_hours, 1200)
        self.assertEqual(offers[0].availability, "available")
        self.assertEqual(offers[1].format_key, "full_time")

    def test_ostbrandenburg_parses_pruefungskosten_from_course_page(self):
        self.assertEqual(
            _parse_exam_fee_from_page("Lehrgangskosten: 11200,00 EUR Prüfungskosten: 680,00 EUR"),
            680.0,
        )
        self.assertIsNone(_parse_exam_fee_from_page("Lehrgangskosten: 11200,00 EUR"))

    def test_ostbrandenburg_parses_exam_fees_from_pdf_text(self):
        text = """
        3.1 Abnahme von Teilen der Meisterprüfung
        - Prüfung Teil I
        - Prüfung Teil II
        - Prüfung Teil III
        - Prüfung Teil IV
        340 Euro 340 Euro 200 Euro 275 Euro
        """
        self.assertEqual(
            HwkFrankfurtOderOstbrandenburgScraper.parse_meister_exam_fees(text),
            {1: 340.0, 2: 340.0, 3: 200.0, 4: 275.0},
        )

    def test_exam_fee_rows_use_brandenburg_source_pages(self):
        for scraper, source_url in (
            (HwkPotsdamScraper(), POTSDAM_EXAM_FEES_PAGE_URL),
            (HwkCottbusScraper(), COTTBUS_EXAM_FEES_PAGE_URL),
            (HwkFrankfurtOderOstbrandenburgScraper(), OB_EXAM_FEES_PDF_URL),
        ):
            with patch.object(scraper, "_fetch_exam_fees_from_pdf", return_value={1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}) if hasattr(scraper, "_fetch_exam_fees_from_pdf") else patch.object(scraper, "_fetch_exam_fees", return_value={1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}):
                rows = scraper.published_exam_fee_rows()
            self.assertTrue(all(row["source_url"] == source_url for row in rows))

    def test_cottbus_collect_resolves_exam_fees(self):
        scraper = HwkCottbusScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value={1: 510.0, 2: 315.0, 3: 200.0, 4: 255.0},
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            825.0,
        )


class BrandenburgIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered_with_issue_slugs(self):
        expected = {
            "hwk-cottbus": HwkCottbusScraper,
            "hwk-frankfurt-oder-ostbrandenburg": HwkFrankfurtOderOstbrandenburgScraper,
            "hwk-potsdam": HwkPotsdamScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Brandenburg")


if __name__ == "__main__":
    unittest.main()
