import re
import unittest
from unittest.mock import patch

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_aachen import HwkAachenScraper, parse_aachen_title
from scrapers.hwk_bayern import parse_exam_fee
from scrapers.hwk_dortmund import HwkDortmundScraper, parse_dortmund_title
from scrapers.hwk_duesseldorf import HwkDuesseldorfScraper, parse_duesseldorf_title
from scrapers.hwk_koeln import HwkKoelnScraper, parse_koeln_title
from scrapers.hwk_muenster import HwkMuensterScraper, parse_muenster_title
from scrapers.hwk_ostwestfalen_lippe_zu_bielefeld import (
    HwkOstwestfalenLippeZuBielefeldScraper,
    parse_owl_title,
)
from scrapers.hwk_suedwestfalen import HwkSuedwestfalenScraper, parse_suedwestfalen_title
from scrapers.pipeline import SCRAPERS


class NrwParserTests(unittest.TestCase):
    def test_koeln_title_parsing(self):
        self.assertEqual(
            parse_koeln_title(
                "Vorbereitung auf die Meisterprüfung im Elektrotechniker-Handwerk Teil I und II"
            ),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_koeln_title("Kombikurs Geprüfte/r Fachfrau/-mann für kfm. Betriebsführung (HwO) und AdA Teil III"),
            ([3], None),
        )

    def test_duesseldorf_title_parsing(self):
        self.assertEqual(parse_duesseldorf_title("Friseur/in (I+II)"), ([1, 2], "Friseur"))
        self.assertEqual(parse_duesseldorf_title("Kfz-Techniker/in (I+II)"), ([1, 2], "Kfz.-Techniker"))
        self.assertEqual(parse_duesseldorf_title("Kombinationslehrgang Teil III"), ([3], None))

    def test_aachen_title_parsing(self):
        self.assertEqual(
            parse_aachen_title("Feinwerkmechaniker/in Teil I + II - Meisterschule"),
            ([1, 2], "Feinwerkmechaniker"),
        )
        self.assertEqual(
            parse_aachen_title("Betriebswirtschaft und Recht | Teil III der Meisterprüfung"),
            ([3], None),
        )

    def test_owl_title_parsing(self):
        self.assertEqual(
            parse_owl_title(
                "Meistervorbereitung im Elektrotechniker-Handwerk Teile I-II Schwerpunkt Energie- und Gebäudetechnik",
                "elektrotechnik",
            ),
            ([1, 2], "Elektrotechniker"),
        )

    def test_muenster_title_parsing(self):
        self.assertEqual(
            parse_muenster_title("Elektrotechniker-Meisterschule Teile I und II Teilzeit"),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_muenster_title("AdA und Gepr. Fachmann und Fachfrau - Meisterschule Teile IV + III"),
            ([3, 4], None),
        )

    def test_suedwestfalen_title_parsing(self):
        self.assertEqual(
            parse_suedwestfalen_title("Meisterkurs Elektrotechnik Vollzeit"),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_suedwestfalen_title("Ausbildung der Ausbilder (AEVO) (Teil IV)"),
            ([4], None),
        )

    def test_dortmund_title_parsing(self):
        self.assertEqual(
            parse_dortmund_title(
                "Metallbauer/in Teilzeitlehrgang (Meistervorbereitung Teile I und II)"
            ),
            ([1, 2], "Metallbauer"),
        )
        self.assertEqual(
            parse_dortmund_title("Ausbildung der Ausbilder nach der AEVO Teilzeit"),
            ([4], None),
        )

    def test_leipzig_exam_fee_without_ca_from_zzgl_mehraufwendungen(self):
        sample = (
            "Prüfungsgebühr für Teil I:\n395 Euro\n"
            "Prüfungsgebühr für Teil II:\n320 Euro\n"
            "zzgl. berufsbezogener Mehraufwendungen"
        )
        fee, qualifier = parse_exam_fee(sample, [1, 2])
        self.assertEqual(fee, 715.0)
        self.assertEqual(qualifier, "")

    def test_muenster_short_date_parsing(self):
        from bs4 import BeautifulSoup

        html = """
        <div class="course-detail__dates-list">
          <li class="course-detail__dates-list-item">
            <label class="course-detail__date-choice-label">
              <span class="date">22.10.27 - 19.01.30</span>
            </label>
          </li>
        </div>
        """
        runs = HwkMuensterScraper._parse_runs(BeautifulSoup(html, "html.parser"))
        self.assertEqual(runs, [("2027-10-22", "2030-01-19")])

    def test_dortmund_display_price_parsing(self):
        html = '<script>"display_price":10260,"display_regular_price":10260</script>'
        match = re.search(r'"display_price":(\d+)', html)
        self.assertEqual(float(match.group(1)), 10260.0)


class NrwRegistrationTests(unittest.TestCase):
    def test_all_chambers_registered(self):
        expected = {
            "hwk-koeln": HwkKoelnScraper,
            "hwk-duesseldorf": HwkDuesseldorfScraper,
            "hwk-aachen": HwkAachenScraper,
            "hwk-ostwestfalen-lippe-zu-bielefeld": HwkOstwestfalenLippeZuBielefeldScraper,
            "hwk-muenster": HwkMuensterScraper,
            "hwk-suedwestfalen": HwkSuedwestfalenScraper,
            "hwk-dortmund": HwkDortmundScraper,
        }
        for slug, cls in expected.items():
            self.assertIs(SCRAPERS[slug], cls)

    def test_chamber_metadata(self):
        scrapers = (
            HwkKoelnScraper(),
            HwkDuesseldorfScraper(),
            HwkAachenScraper(),
            HwkOstwestfalenLippeZuBielefeldScraper(),
            HwkMuensterScraper(),
            HwkSuedwestfalenScraper(),
            HwkDortmundScraper(),
        )
        for scraper in scrapers:
            self.assertEqual(scraper.chamber_region, "Nordrhein-Westfalen")
            self.assertTrue(scraper.chamber_slug)
            self.assertTrue(scraper.chamber_name)
            self.assertTrue(scraper.chamber_website)


class NrwExamFeeTests(unittest.TestCase):
    def test_duesseldorf_pdf_fee_parsing(self):
        sample = """
        Meisterprüfung Teil I
        Elektrotechniker/in 500,00 €
        Friseur/in 420,00 €
        Teil II der Meisterprüfung:
        Alle 380,00 €
        Teil III der Meisterprüfung:
        Alle 280,00 €
        """
        part_i = HwkDuesseldorfScraper.parse_part_i_exam_fees(sample)
        generic = HwkDuesseldorfScraper.parse_generic_exam_fees(sample)
        self.assertEqual(part_i["Elektrotechniker"], 500.0)
        self.assertEqual(generic[2], 380.0)

    @patch.object(HwkDuesseldorfScraper, "_fetch_exam_fees_from_pdf")
    def test_duesseldorf_exam_fee_resolution(self, mock_fetch):
        mock_fetch.return_value = (
            {"Elektrotechniker": 500.0, "Friseur": 420.0},
            {2: 380.0, 3: 280.0, 4: 220.0},
        )
        rows = HwkDuesseldorfScraper().published_exam_fee_rows()
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee("hwk-duesseldorf", "elektrotechniker", [1, 2], None, lookup)["fee"],
            880.0,
        )
        self.assertEqual(
            resolve_exam_fee("hwk-duesseldorf", "tischler", [3], None, lookup)["fee"],
            280.0,
        )

    def test_suedwestfalen_card_fee_parsing(self):
        card = {
            "title": "Meisterkurs Elektrotechnik Vollzeit",
            "text": "1250 Unterrichtsstunden 10.880,00 €",
            "url": "https://www.bbz-arnsberg.de/meisterkurse/elektrotechnik",
        }
        offers = HwkSuedwestfalenScraper()._parse_card(card)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].course_fee, 10880.0)
        self.assertEqual(offers[0].trade_name, "Elektrotechniker")


if __name__ == "__main__":
    unittest.main()
