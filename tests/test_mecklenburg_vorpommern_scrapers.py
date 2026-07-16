import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_ostmecklenburg_vorpommern import (
    EXAM_FEES_PAGE_URL as OMV_EXAM_FEES_PAGE_URL,
    HwkOstmecklenburgVorpommernScraper,
    parse_omv_title,
)
from scrapers.hwk_schwerin import (
    EXAM_FEES_PAGE_URL as SCHWERIN_EXAM_FEES_PAGE_URL,
    HwkSchwerinScraper,
    parse_schwerin_title,
)
from scrapers.pipeline import SCRAPERS


class MecklenburgVorpommernParserTests(unittest.TestCase):
    def test_schwerin_title_parsing(self):
        self.assertEqual(
            parse_schwerin_title("Meisterausbildung Teile 1 und 2 Metallbau"),
            ([1, 2], "Metallbauer"),
        )
        self.assertEqual(
            parse_schwerin_title("Meisterausbildung Teile 1 und 2 Kfz- Techniker (Vollzeit)"),
            ([1, 2], "Kfz.-Techniker"),
        )
        self.assertEqual(
            parse_schwerin_title("Meisterausbildung Teil 1 und 2 Inst./Hzg Vollzeit"),
            ([1, 2], "Installateur- und Heizungsbauer"),
        )
        self.assertEqual(
            parse_schwerin_title(
                "Geprüfter Fachmann für die kaufmännische Betriebsführung nach der Handwerksordnung"
            ),
            ([3], None),
        )

    def test_schwerin_parses_exam_fees_from_pdf_text(self):
        text = """
        8.5. Meisterprüfungsgebühr
        8.5.1. Teil I 400,00 €
        8.5.2. Teil II 400,00 €
        8.5.3. Teil III 200,00 €
        8.5.4. Teil IV 200,00 €
        """
        self.assertEqual(
            HwkSchwerinScraper.parse_meister_exam_fees(text),
            {1: 400.0, 2: 400.0, 3: 200.0, 4: 200.0},
        )

    def test_schwerin_collect_resolves_exam_fees(self):
        scraper = HwkSchwerinScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value={1: 400.0, 2: 400.0, 3: 200.0, 4: 200.0},
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            800.0,
        )

    def test_schwerin_card_allows_trade_resolution_from_detail(self):
        soup = BeautifulSoup(
            """
            <div class="row">
              <h3><a href="/kurse/meister-19,0,coursedetail.html?id=1">
                Meisterausbildung Teil I/II (Teilzeit)
              </a></h3>
              <div>01.09.2026 - 01.03.2028</div>
              <div>Schwerin</div>
            </div>
            """,
            "html.parser",
        )
        link = soup.select_one("a[href*='coursedetail']")
        card = HwkSchwerinScraper()._parse_card(link)
        self.assertEqual(card["parts"], [1, 2])
        self.assertIsNone(card["trade_name"])

    def test_omv_title_parsing(self):
        self.assertEqual(
            parse_omv_title("Meistervorbereitung Kfz Teil I und Teil II"),
            ([1, 2], "Kfz.-Techniker"),
        )
        self.assertEqual(
            parse_omv_title("Meistervorbereitung Maler-/Lackierer Teil I/II"),
            ([1, 2], "Maler und Lackierer"),
        )
        self.assertEqual(
            parse_omv_title("Land- und Baumaschinenmechatroniker/-in Teil I und II"),
            ([1, 2], "Land- und Baumaschinenmechatroniker"),
        )
        self.assertEqual(
            parse_omv_title("Meistervorbereitung Maurer und Betonbauer Teil I + II"),
            ([1, 2], "Maurer und Betonbauer"),
        )

    def test_omv_parses_exam_fees_from_pdf_text(self):
        text = """
        2.5 Meisterprüfung
         - Teil I praktische Prüfung  380,00 €
         - Teil II Prüfung der fachtheoretischen Kenntnisse  330,00 €
         - Teil III Prüfung der betriebswirtschaftlichen,
          kaufmännischen und rechtlichen Kenntnisse
        190,00 €
        2.7 Fortbildungsprüfungen
         - Ausbildereignungsprüfung 190,00 €
        """
        self.assertEqual(
            HwkOstmecklenburgVorpommernScraper.parse_meister_exam_fees(text),
            {1: 380.0, 2: 330.0, 3: 190.0, 4: 190.0},
        )

    def test_omv_collect_resolves_exam_fees(self):
        scraper = HwkOstmecklenburgVorpommernScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value={1: 380.0, 2: 330.0, 3: 190.0, 4: 190.0},
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            710.0,
        )

    def test_exam_fee_rows_use_mv_source_pages(self):
        for scraper, source_url in (
            (HwkSchwerinScraper(), SCHWERIN_EXAM_FEES_PAGE_URL),
            (HwkOstmecklenburgVorpommernScraper(), OMV_EXAM_FEES_PAGE_URL),
        ):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_pdf",
                return_value={1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0},
            ):
                rows = scraper.published_exam_fee_rows()
            self.assertTrue(all(row["source_url"] == source_url for row in rows))


class MecklenburgVorpommernIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered(self):
        expected = {
            "hwk-schwerin": HwkSchwerinScraper,
            "hwk-ostmecklenburg-vorpommern": HwkOstmecklenburgVorpommernScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Mecklenburg-Vorpommern")


if __name__ == "__main__":
    unittest.main()
