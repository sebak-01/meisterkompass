import unittest
from unittest.mock import patch

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_flensburg import (
    EXAM_FEES_PAGE_URL as FLENSBURG_EXAM_FEES_PAGE_URL,
    HwkFlensburgScraper,
)
from scrapers.hwk_luebeck import (
    EXAM_FEES_PAGE_URL as LUEBECK_EXAM_FEES_PAGE_URL,
    HwkLuebeckScraper,
)
from scrapers.hwk_universal_kdb import (
    parse_kdb_location,
    parse_kdb_price,
    parse_sh_title,
)
from scrapers.pipeline import SCRAPERS


class SchleswigHolsteinParserTests(unittest.TestCase):
    def test_flensburg_title_parsing(self):
        self.assertEqual(
            parse_sh_title("Metallbauerhandwerk I und II (berufsbegleitend)"),
            ([1, 2], "Metallbauer"),
        )
        self.assertEqual(
            parse_sh_title("Zimmererhandwerk Teil I bis IV (Vollzeit)"),
            ([1, 2, 3, 4], "Zimmerer"),
        )
        self.assertEqual(
            parse_sh_title("Teil III - Geschäfts- und Rechtskunde - Vollzeit -"),
            ([3], None),
        )
        self.assertEqual(
            parse_sh_title(
                "Lehrgang zur Vorbereitung auf die Ausbildereignungsprüfung nach AEVO (AdA) / Teil IV der Meisterprüfung - berufsbegleitend -"
            ),
            ([4], None),
        )
        self.assertEqual(parse_sh_title("Konflikte meistern - Strategien"), ([], None))

    def test_luebeck_title_parsing(self):
        self.assertEqual(
            parse_sh_title(
                "Meistervorbereitungslehrgang im Elektrotechniker-Handwerk Teil I+II berufsbegleitend"
            ),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_sh_title("Meistervorbereitungslehrgang Teil III+IV berufsbegleitend"),
            ([3, 4], None),
        )
        self.assertEqual(
            parse_sh_title(
                "Meistervorbereitungslehrgang im Kraftfahrzeugtechniker-Handwerk Teil I+II (Schwerpunkt Systemtechnik) berufsbegleitend"
            ),
            ([1, 2], "Kfz.-Techniker"),
        )

    def test_detail_urls_point_at_kdb_vorlage_route(self):
        fl = HwkFlensburgScraper()
        self.assertEqual(
            fl._detail_url("MVK", "468", "23824"),
            "https://www.hwk-flensburg.de/weiterbildung/kurse-seminare#/vorlage/MVK/468?kurs=23824",
        )
        hl = HwkLuebeckScraper()
        self.assertEqual(
            hl._detail_url("MVK", "108228", "13225"),
            "https://www.hwk-luebeck.de/weiterbildung/fort-und-weiterbildungskurse#/vorlage/MVK/108228?kurs=13225",
        )

    def test_kdb_price_and_location(self):
        self.assertEqual(parse_kdb_price("9.450,00 €"), 9450.0)
        block = (
            "<lehrgangsort><hausnummer>167</hausnummer><lehrgangsort>BBS Kiel</lehrgangsort>"
            "<ort>Kiel</ort><plz>24109</plz><strasse>Russeer Weg</strasse></lehrgangsort>"
        )
        self.assertEqual(parse_kdb_location(block), ("Russeer Weg 167", "24109", "Kiel"))
        self.assertEqual(parse_kdb_price("9.450,00 €"), 9450.0)
        block = (
            "<lehrgangsort><hausnummer>167</hausnummer><lehrgangsort>BBS Kiel</lehrgangsort>"
            "<ort>Kiel</ort><plz>24109</plz><strasse>Russeer Weg</strasse></lehrgangsort>"
        )
        self.assertEqual(parse_kdb_location(block), ("Russeer Weg 167", "24109", "Kiel"))

    def test_flensburg_parses_exam_fees_from_page_text(self):
        text = """
        Gebühren für das Meisterprüfungsverfahren
        Teil I – Praktische Prüfung
        480,00 Euro
        Teil II – Fachtheoretische Kenntnisse
        480,00 Euro
        Teil III – Wirtschaftliche und rechtliche Kenntnisse
        290,00 Euro
        Teil IV – Berufs- und arbeitspädagogische Kenntnisse
        290,00 Euro
        """
        self.assertEqual(
            HwkFlensburgScraper.parse_meister_exam_fees(text),
            {1: 480.0, 2: 480.0, 3: 290.0, 4: 290.0},
        )

    def test_luebeck_parses_exam_fees_from_page_text(self):
        text = """
        Teil I: 585,00 €
        Teil II: 585,00 €
        Teil III: 380,00 €
        Teil IV: 380,00 €
        """
        self.assertEqual(
            HwkLuebeckScraper.parse_meister_exam_fees(text),
            {1: 585.0, 2: 585.0, 3: 380.0, 4: 380.0},
        )

    def test_exam_fee_rows_use_sh_source_pages(self):
        for scraper, source_url in (
            (HwkFlensburgScraper(), FLENSBURG_EXAM_FEES_PAGE_URL),
            (HwkLuebeckScraper(), LUEBECK_EXAM_FEES_PAGE_URL),
        ):
            with patch.object(scraper, "_fetch_exam_fees_from_page", return_value={1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}):
                rows = scraper.published_exam_fee_rows()
            self.assertTrue(all(row["source_url"] == source_url for row in rows))

    def test_collect_resolves_exam_fees(self):
        scraper = HwkLuebeckScraper()
        with patch.object(scraper, "fetch_raw_courses", return_value=[]):
            with patch.object(
                scraper,
                "_fetch_exam_fees_from_page",
                return_value={1: 585.0, 2: 585.0, 3: 380.0, 4: 380.0},
            ):
                rows = scraper.collect().exam_fee_rows
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee(scraper.chamber_slug, "any-trade", [1, 2], None, lookup)["fee"],
            1170.0,
        )


class SchleswigHolsteinIntegrationTests(unittest.TestCase):
    def test_all_chambers_are_registered(self):
        expected = {
            "hwk-flensburg": HwkFlensburgScraper,
            "hwk-luebeck": HwkLuebeckScraper,
        }
        for slug, scraper in expected.items():
            self.assertIs(SCRAPERS[slug], scraper)
            self.assertEqual(scraper.chamber_region, "Schleswig-Holstein")


if __name__ == "__main__":
    unittest.main()
