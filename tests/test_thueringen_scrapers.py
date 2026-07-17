import json
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_bayern import parse_parts
from scrapers.hwk_erfurt import HwkErfurtScraper
from scrapers.hwk_ostthueringen_gera import (
    HwkOstthueringenGeraScraper,
    LEHESTEN_COURSES,
    TENTATIVE_DATE_NOTE,
    _parse_ostthueringen_schedule,
)
from scrapers.hwk_suedthueringen_suhl import (
    HwkSuedthueringenSuhlScraper,
    parse_suhl_title,
)
from scrapers.pipeline import SCRAPERS


class ThueringenParserTests(unittest.TestCase):
    def test_explicit_combined_parts_win_over_generic_keyword(self):
        self.assertEqual(
            parse_parts(
                "Meisterkurs Teile III und IV – kaufmännische Betriebsführung und AEVO"
            ),
            [3, 4],
        )
        self.assertEqual(parse_parts("Teil I / Teil II"), [1, 2])

    def test_erfurt_accepts_friseur_title_without_meister_word(self):
        soup = BeautifulSoup(
            """
            <div class="row">
              <h3>02.11.2026 - 19.03.2027: Vollzeit
                <a href="/kurse/x-4,0,coursedetail.html?id=42">Friseur-Handwerk Teil I/II</a>
              </h3>
              <p>Erfurt</p>
            </div>
            """,
            "html.parser",
        )
        card = HwkErfurtScraper()._parse_card(soup.select_one("a"))
        self.assertEqual(card["parts"], [1, 2])
        self.assertEqual(card["trade_name"], "Friseur")
        self.assertEqual(card["detail_url"], "https://www.hwk-erfurt.de/4,0,coursedetail.html?id=42")

    def test_suhl_title_parsing(self):
        self.assertEqual(
            parse_suhl_title("Meister im Elektrotechniker-Handwerk Teil I und II"),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_suhl_title("Geprüfter Fachmann für kaufmännische Betriebsführung"),
            ([3], None),
        )
        self.assertEqual(
            parse_suhl_title("Ausbildereignungsprüfung nach AEVO"),
            ([4], None),
        )

    def test_suhl_discovery_deduplicates_and_excludes_unrelated_courses(self):
        soup = BeautifulSoup(
            """
            <a href="/seminar/elektro_vz/">Meister im Elektrotechniker-Handwerk Teil I und II</a>
            <a href="/seminar/elektro_vz/?ref=home">Meister im Elektrotechniker-Handwerk Teil I und II</a>
            <a href="/seminar/mathe/">Mathematik für Meisterschüler</a>
            <a href="/seminar/ihk/">Industriemeister Metall</a>
            """,
            "html.parser",
        )
        courses = HwkSuedthueringenSuhlScraper._discover(soup)
        self.assertEqual(
            courses,
            [(
                "Meister im Elektrotechniker-Handwerk Teil I und II",
                "https://www.hwk-suedthueringen.de/seminar/elektro_vz/",
            )],
        )

    def test_suhl_multi_run_detail_preserves_run_specific_fields(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Meister im Elektrotechniker-Handwerk</h1>
              <h4>Seminardauer</h4><p>1.224 Unterrichtseinheiten à 45 Minuten</p>
              <section>
                <h4>01.09.2026 — 11.06.2027</h4>
                <p>Keine Plätze mehr frei</p>
                <p>Werkstattgebäude W6<br>98530 Rohr</p>
                <h4>Kosten</h4><p>10.975,00 €</p>
                <h4>Kursnummer</h4><p>207748</p>
                <h4>Kurstyp</h4><p>Vollzeit</p>
              </section>
              <section>
                <h4>30.08.2027 — 16.06.2028</h4>
                <p>Es gibt noch freie Plätze</p>
                <p>Kloster 1<br>98530 Rohr</p>
                <h4>Kosten</h4><p>11.890,00 €</p>
                <h4>Kursnummer</h4><p>208401</p>
                <h4>Kurstyp</h4><p>Vollzeit</p>
              </section>
            </main>
            """,
            "html.parser",
        )
        offers = HwkSuedthueringenSuhlScraper()._parse_course(
            soup,
            "Meister im Elektrotechniker-Handwerk Teil I und II",
            "https://www.hwk-suedthueringen.de/seminar/elektro_vz/",
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual([offer.course_fee for offer in offers], [10975.0, 11890.0])
        self.assertEqual([offer.availability for offer in offers], ["full", "available"])
        self.assertTrue(all(offer.duration_hours == 1224 for offer in offers))
        self.assertTrue(all(offer.street == "Kloster 1" for offer in offers))
        self.assertTrue(all(offer.city == "Rohr" for offer in offers))

    def test_suhl_parses_page_level_kosten_without_dated_runs(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Meister im Holzbildhauerhandwerk Teile I/II - Vollzeit</h1>
              <h4>Seminardauer</h4><p>1.200 Unterrichtseinheiten à 45 Minuten</p>
              <h4>Kosten</h4><p>MVL Teil I/II Holzbildhauer: 8560,00 €</p>
              <h4>Termine auf Anfrage.</h4>
            </main>
            """,
            "html.parser",
        )
        offers = HwkSuedthueringenSuhlScraper()._parse_course(
            soup,
            "Meister im Holzbildhauerhandwerk Teile I/II",
            "https://www.hwk-suedthueringen.de/seminar/hobi-teil-i-ii/",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].course_fee, 8560.0)
        self.assertIsNone(offers[0].start_date)
        self.assertEqual(offers[0].trade_name, "Holzbildhauer")

    def test_suhl_collect_publishes_exam_fee_rows(self):
        scraper = HwkSuedthueringenSuhlScraper()
        rows = scraper.published_exam_fee_rows()
        self.assertEqual(len(rows), 4)
        lookup = build_exam_fee_lookup(rows, [])
        resolved = resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)
        self.assertEqual(resolved["fee"], 555.0)

    def test_ostthueringen_ignores_format_suffixes_in_trade_names(self):
        offers = HwkOstthueringenGeraScraper().fetch_raw_courses()
        weird = {o.trade_name for o in offers if o.trade_name and "(" in o.trade_name}
        self.assertEqual(weird, set())

    def test_ostthueringen_parses_unterricht_schedule_without_alle_termine_bleed(self):
        soup = BeautifulSoup(
            """
            <main>
              <h3>Unterricht</h3>
              <p>03.2027 - 04.2027</p>
              <p>Mo. - Fr. 07:30- 14:30 Uhr</p>
              <span class="trafficlight-orange">genauer Termin steht noch nicht fest</span>
              <h3>Lehrgangsort</h3><p>Gera</p>
              <h2>Alle Termine</h2>
              <h3>18.08.2026 - 15.07.2027: Abend</h3>
              <h3>März 2027 - April 2027: Vollzeit</h3>
            </main>
            """,
            "html.parser",
        )
        card = {"card_text": "März 2027 - April 2027: Vollzeit\nMeister Teil III"}
        start, end, note = _parse_ostthueringen_schedule(soup, card)
        self.assertEqual(start, "2027-03-01")
        self.assertEqual(end, "2027-04-01")
        self.assertEqual(note, TENTATIVE_DATE_NOTE)

    def test_ostthueringen_keeps_exact_unterricht_dates_without_note(self):
        soup = BeautifulSoup(
            """
            <main>
              <h3>Unterricht</h3>
              <p>18.08.2026 - 15.07.2027</p>
              <p>Di. und Do. 16:30-20:45 Uhr</p>
              <h3>Lehrgangsort</h3><p>Gera</p>
              <h2>Alle Termine</h2>
              <h3>März 2027 - April 2027: Vollzeit</h3>
            </main>
            """,
            "html.parser",
        )
        card = {"card_text": "18.08.2026 - 15.07.2027: Abend\nMeister Teil III"}
        start, end, note = _parse_ostthueringen_schedule(soup, card)
        self.assertEqual(start, "2026-08-18")
        self.assertEqual(end, "2027-07-15")
        self.assertEqual(note, "")

    def test_ostthueringen_parses_meister_exam_fees_from_pdf_text(self):
        text = """
        5. Abnahme von Teilen der Meisterprüfung für alle Handwerke
        5.1 Teil I 335,00 €
        5.2 Teil II 220,00 €
        5.3 Teil III / Geprüfte/r Fachmann/-frau für kaufmännische
        Betriebsführung (HWO)
        190,00 €
        5.4 Teil IV / Ausbildereignungsprüfung 190,00 €
        """
        self.assertEqual(
            HwkOstthueringenGeraScraper.parse_meister_exam_fees(text),
            {1: 335.0, 2: 220.0, 3: 190.0, 4: 190.0},
        )

    def test_ostthueringen_collect_uses_scraped_exam_fees(self):
        scraper = HwkOstthueringenGeraScraper()
        scraped = {1: 335.0, 2: 220.0, 3: 190.0, 4: 190.0}
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(scraper, "_fetch_exam_fees_from_pdf", return_value=scraped):
                rows = scraper.collect().exam_fee_rows
        self.assertEqual(
            {(row["part"], row["fee"]) for row in rows},
            {(1, 335.0), (2, 220.0), (3, 190.0), (4, 190.0)},
        )
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            555.0,
        )
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [3, 4], None, lookup)["fee"],
            380.0,
        )

    def test_lehesten_provider_parses_partner_course(self):
        scraper = HwkOstthueringenGeraScraper()
        spec = next(item for item in LEHESTEN_COURSES if item["trade_name"] == "Dachdecker")
        overview = BeautifulSoup(
            """
            <main>
              <p>Lehrgangskosten 8.710,00€ (Stand für Kurs 2026/27)</p>
              <p>Der Lehrgang umfasst ca. 1.140 Stunden.</p>
            </main>
            """,
            "html.parser",
        )
        run_page = BeautifulSoup(
            """
            <main>
              <h1>Meistervorbereitungslehrgang Dachdecker Teil 1 und Teil 2</h1>
              <p>07.09.2026</p>
              <p>25.03.2027</p>
              <p>Dachdeckermeisterkurs in Vollzeit</p>
            </main>
            """,
            "html.parser",
        )
        scraper.parse_html = lambda url: overview if "dachdeckermeister-teil-1-2" in url else run_page
        offer = scraper._parse_lehesten_course(spec)

        self.assertEqual(offer.trade_name, "Dachdecker")
        self.assertEqual(offer.parts, [1, 2])
        self.assertEqual(offer.start_date, "2026-09-07")
        self.assertEqual(offer.end_date, "2027-03-25")
        self.assertEqual(offer.course_fee, 8710.0)
        self.assertEqual(offer.duration_hours, 1140)
        self.assertEqual(offer.street, "Friedrichsbruch 3")
        self.assertEqual(offer.city, "Lehesten")


class ThueringenIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered_with_issue_slugs(self):
        expected = {
            "hwk-erfurt": HwkErfurtScraper,
            "hwk-ostthueringen-gera": HwkOstthueringenGeraScraper,
            "hwk-suedthueringen-suhl": HwkSuedthueringenSuhlScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Thüringen")

    def test_published_chamber_exam_fees_are_injected(self):
        cases = (
            (HwkOstthueringenGeraScraper, [1, 2], 555.0),
            (HwkOstthueringenGeraScraper, [3, 4], 380.0),
            (HwkSuedthueringenSuhlScraper, [1, 2], 555.0),
            (HwkSuedthueringenSuhlScraper, [3, 4], 370.0),
        )
        for scraper_class, parts, expected in cases:
            scraper = scraper_class()
            with patch.object(scraper, "fetch_raw_courses", return_value=[]):
                rows = scraper.collect().exam_fee_rows
            lookup = build_exam_fee_lookup(rows, [])
            resolved = resolve_exam_fee(
                scraper.chamber_slug, "any-trade", parts, None, lookup
            )
            self.assertEqual(resolved["fee"], expected)
            self.assertEqual(resolved["qualifier"], "")

    def test_erfurt_manual_exam_fee_schedule(self):
        fee_path = Path(__file__).resolve().parents[1] / "data/manual/exam_fees_manual.json"
        lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))
        cases = (
            ([1, 2], 760.0),
            ([3], 340.0),
            ([4], 340.0),
        )
        for parts, expected in cases:
            resolved = resolve_exam_fee("hwk-erfurt", "any-trade", parts, None, lookup)
            self.assertEqual(resolved["fee"], expected)
            self.assertEqual(resolved["qualifier"], "")


if __name__ == "__main__":
    unittest.main()
