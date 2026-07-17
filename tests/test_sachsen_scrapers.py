import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_chemnitz import HwkChemnitzScraper, parse_chemnitz_title
from scrapers.hwk_dresden import (
    EXAM_FEES_PAGE_URL as DRESDEN_EXAM_FEES_PAGE_URL,
    HwkDresdenScraper,
    _availability,
    parse_dresden_title,
)
from scrapers.hwk_leipzig import EXAM_FEES_PAGE_URL as LEIPZIG_EXAM_FEES_PAGE_URL, HwkLeipzigScraper
from scrapers.pipeline import SCRAPERS


class SachsenParserTests(unittest.TestCase):
    def test_dresden_title_parsing(self):
        self.assertEqual(
            parse_dresden_title("Metallbauerhandwerk Teil II"),
            ([2], "Metallbauer"),
        )
        self.assertEqual(
            parse_dresden_title("Installateur- und Heizungsbauerhandwerk Teil I"),
            ([1], "Installateur- und Heizungsbauer"),
        )

    def test_chemnitz_title_parsing(self):
        self.assertEqual(
            parse_chemnitz_title("Vorbereitungskurs Metallbauermeister Teile I/II"),
            ([1, 2], "Metallbauer"),
        )
        self.assertEqual(
            parse_chemnitz_title("Vorbereitungskurs Informationstechnikermeister Teile I/II"),
            ([1, 2], "Informationstechniker"),
        )

    def test_dresden_discover_excludes_non_meister_courses(self):
        soup = BeautifulSoup(
            """
            <a href="/kurs-finden/kursdetails/kurs/metallbauerhandwerk-teil-ii-1.html">
              Metallbauerhandwerk Teil II
            </a>
            <a href="/kurs-finden/kursdetails/kurs/infoabend-zur-meisterausbildung-1.html">
              Infoabend zur Meisterausbildung
            </a>
            <a href="/kurs-finden/kursdetails/kurs/vorschaltkurs-zum-teil-ii-1.html">
              Vorschaltkurs zum Teil II im Metallbauerhandwerk
            </a>
            """,
            "html.parser",
        )
        courses = HwkDresdenScraper._discover(soup)
        self.assertEqual(
            courses,
            [(
                "Metallbauerhandwerk Teil II",
                "https://www.njumii.de/kurs-finden/kursdetails/kurs/metallbauerhandwerk-teil-ii-1.html",
            )],
        )

    def test_dresden_parses_featured_and_accordion_runs(self):
        soup = BeautifulSoup(
            """
            <div class="sliderheader">Metallbauerhandwerk Teil II</div>
            <div class="row g-5">
              <div class="col"><p class="titel">07.09.2026 - 25.01.2027</p></div>
              <div class="col"><p>Dauer 718 Teilnehmerstunden</p></div>
              <div class="col"><p>7.500,00 €</p></div>
              <div class="col"><p>Kursort Dresden</p></div>
              <div class="col"><button>Jetzt Kurs buchen</button></div>
            </div>
            <div class="accordion-item">
              <button class="accordion-button">12.03.2027 - 25.03.2028 berufsbegleitend Dresden Plätze verfügbar</button>
              <div>Kursort Dresden</div>
              <div>Kosten 7.150,00 €</div>
              <button>Termin wählen</button>
            </div>
            """,
            "html.parser",
        )
        offers = HwkDresdenScraper()._parse_course(
            soup,
            "Metallbauerhandwerk Teil II",
            "https://www.njumii.de/kurs-finden/kursdetails/kurs/metallbauerhandwerk-teil-ii-1.html",
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].course_fee, 7500.0)
        self.assertEqual(offers[0].duration_hours, 718)
        self.assertEqual(offers[0].availability, "available")
        self.assertEqual(offers[1].course_fee, 7150.0)
        self.assertEqual(offers[1].duration_hours, 718)
        self.assertEqual(offers[1].availability, "available")

    def test_dresden_availability_defaults_to_available_with_booking_button(self):
        self.assertEqual(
            _availability("07.09.2026 - 25.01.2027", BeautifulSoup(
                "<button>Jetzt Kurs buchen</button>", "html.parser"
            ).button),
            "available",
        )
        self.assertEqual(
            _availability("12.03.2027 - 25.03.2028 Warteliste", BeautifulSoup(
                "<button>Termin wählen</button>", "html.parser"
            ).button),
            "available",
        )
        self.assertEqual(_availability("Ausgebucht"), "full")
        self.assertEqual(_availability("Warteliste"), "waitlist")

    def test_dresden_exam_fee_rows_use_meisterpruefungen_page(self):
        scraper = HwkDresdenScraper()
        with patch.object(
            scraper,
            "_fetch_exam_fees_from_pdf",
            return_value={1: 440.0, 2: 300.0, 3: 240.0, 4: 240.0},
        ):
            rows = scraper.published_exam_fee_rows()
        self.assertTrue(all(row["source_url"] == DRESDEN_EXAM_FEES_PAGE_URL for row in rows))

    def test_chemnitz_parses_termin_block(self):
        soup = BeautifulSoup(
            """
            <h1>Vorbereitungskurs Metallbauermeister Teile I/II</h1>
            <details id="termin_218">
              <summary>
                <h3>Teilzeit - 21. August 2026 in Chemnitz</h3>
                <span>bis 10. Juli 2027</span>
              </summary>
              <div>
                <h4>Kursnummer</h4><p>10070395</p>
                <h4>Dauer</h4><p>655 Unterrichtseinheiten</p>
                <h4>Termin</h4><p>21. August 2026 -<br/>10. Juli 2027</p>
                <h4>Ort</h4>
                <p>Bildungs- und Technologiezentrum Chemnitz</p>
                <p>Limbacher Straße 195</p>
                <p>09116 Chemnitz</p>
                <h4>Gebühr</h4><p>7.990,00 €</p>
                <p>Es sind nur noch wenige Plätze verfügbar.</p>
              </div>
            </details>
            """,
            "html.parser",
        )
        offers = HwkChemnitzScraper()._parse_course_page(
            soup,
            "https://www.hwk-chemnitz.de/weiterbildung/kurs/vorbereitungskurs-metallbauermeister-teile-i-ii/",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].trade_name, "Metallbauer")
        self.assertEqual(offers[0].start_date, "2026-08-21")
        self.assertEqual(offers[0].end_date, "2027-07-10")
        self.assertEqual(offers[0].course_fee, 7990.0)
        self.assertEqual(offers[0].street, "Limbacher Straße 195")

    def test_leipzig_parses_exam_fees_from_pdf_text(self):
        text = """
        B.III.1. Abnahme der Meisterprüfung für alle Gewerke
         a) Meisterprüfung Teil I 450,00 Euro
         b) Meisterprüfung Teil II 380,00 Euro
         c) Meisterprüfung Teil III 230,00 Euro
         d) Meisterprüfung Teil IV 190,00 Euro
        """
        self.assertEqual(
            HwkLeipzigScraper.parse_meister_exam_fees(text),
            {1: 450.0, 2: 380.0, 3: 230.0, 4: 190.0},
        )

    def test_leipzig_exam_fee_rows_use_gebuehrenordnung_page(self):
        scraper = HwkLeipzigScraper()
        with patch.object(
            scraper,
            "_fetch_exam_fees_from_pdf",
            return_value={1: 450.0, 2: 380.0, 3: 230.0, 4: 190.0},
        ):
            rows = scraper.published_exam_fee_rows()
        self.assertTrue(all(row["source_url"] == LEIPZIG_EXAM_FEES_PAGE_URL for row in rows))

    def test_leipzig_course_page_exam_fees_take_priority(self):
        from scrapers.hwk_bayern import parse_exam_fee

        sample = """
        Prüfungsgebühr für Teil I:
        395 Euro
        Prüfungsgebühr für Teil II:
        320 Euro
        """
        fee, _ = parse_exam_fee(sample, [1, 2])
        self.assertEqual(fee, 715.0)

        scraper = HwkLeipzigScraper()
        soup = scraper.parse_html(
            "https://www.hwk-leipzig.de/3,0,coursedetail.html?id=74457"
        )
        card = {
            "raw_title": "Elektrotechniker-Meister Teile I und II, Vollzeit",
            "parts": [1, 2],
            "trade_name": "Elektrotechniker",
            "format_key": "full_time",
            "teaching_mode": "presence",
            "start_date": None,
            "end_date": None,
            "duration_hours": None,
            "course_fee": None,
            "detail_url": "https://www.hwk-leipzig.de/3,0,coursedetail.html?id=74457",
            "availability": "available",
            "card_text": "",
        }
        offer = scraper._enrich({**card, "detail_url": card["detail_url"]})
        self.assertEqual(offer.exam_fee_scraped, 715.0)

    def test_dresden_collect_resolves_exam_fees(self):
        scraper = HwkDresdenScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value={1: 440.0, 2: 300.0, 3: 240.0, 4: 240.0},
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            740.0,
        )


class SachsenIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered_with_issue_slugs(self):
        expected = {
            "hwk-dresden": HwkDresdenScraper,
            "hwk-chemnitz": HwkChemnitzScraper,
            "hwk-leipzig": HwkLeipzigScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Sachsen")


if __name__ == "__main__":
    unittest.main()
