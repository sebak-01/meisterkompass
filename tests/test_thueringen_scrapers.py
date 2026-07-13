import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_bayern import parse_parts
from scrapers.hwk_erfurt import HwkErfurtScraper
from scrapers.hwk_ostthueringen_gera import HwkOstthueringenGeraScraper
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


if __name__ == "__main__":
    unittest.main()
