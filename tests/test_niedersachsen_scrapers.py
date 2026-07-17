import re
import unittest
from unittest.mock import patch

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_bayern import DURATION_RE, DURATION_UNIT
from scrapers.hwk_braunschweig_lueneburg_stade import (
    HwkBraunschweigLueneburgStadeScraper,
    parse_bls_title,
)
from scrapers.hwk_hannover import HwkHannoverScraper, parse_hannover_title
from scrapers.hwk_hildesheim_suedniedersachsen import (
    HwkHildesheimSuedniedersachsenScraper,
    parse_hildesheim_title,
)
from scrapers.hwk_oldenburg import HwkOldenburgScraper
from scrapers.hwk_osnabrueck_emsland_grafschaft_bentheim import (
    HwkOsnabrueckEmslandGrafschaftBentheimScraper,
    parse_osn_title,
)
from scrapers.hwk_ostfriesland import HwkOstfrieslandScraper
from scrapers.hwk_universal_kdb import parse_sh_title
from scrapers.pipeline import SCRAPERS


class NiedersachsenParserTests(unittest.TestCase):
    def test_bls_title_parsing(self):
        self.assertEqual(
            parse_bls_title(
                "Meistervorbereitung im Kraftfahrzeugtechnikerhandwerk, Teil I und II"
            ),
            ([1, 2], "Kfz.-Techniker"),
        )
        self.assertEqual(
            parse_bls_title("Meistervorbereitung Teil III und Teil IV"),
            ([3, 4], None),
        )

    def test_hannover_title_parsing(self):
        self.assertEqual(
            parse_hannover_title(
                "Meistervorbereitung Elektrotechniker Teil I und II berufsbegleitend"
            ),
            ([1, 2], "Elektrotechniker"),
        )
        self.assertEqual(
            parse_hannover_title("Meistervorbereitung Teil III und Teil IV"),
            ([3, 4], None),
        )

    def test_hannover_duration_parses_u_std(self):
        text = "Lehrgangsdauer 1150 U-Std. (à 45 Minuten)"
        self.assertEqual(DURATION_RE.search(text).group(1), "1150")
        detail_match = re.search(
            rf"Lehrgangsdauer\s+([\d.]+)\s*{DURATION_UNIT}", text, re.IGNORECASE
        )
        self.assertEqual(detail_match.group(1), "1150")

    def test_hildesheim_title_parsing(self):
        self.assertEqual(
            parse_hildesheim_title("Maurer- und Betonbauermeister, (Teile I und II)"),
            ([1, 2], "Maurer und Betonbauer"),
        )
        self.assertEqual(
            parse_hildesheim_title("Kurs: Meistervorbereitung Teil IV im hybriden Lernformat"),
            ([4], None),
        )

    def test_osn_title_parsing(self):
        self.assertEqual(
            parse_osn_title("Tischler-Meisterschule Teile I und II | Teilzeit"),
            ([1, 2], "Tischler"),
        )
        self.assertEqual(
            parse_osn_title("Meisterkurs Teil III | Vollzeit Gepr. Fachmann für kfm. Betriebsführung HWO"),
            ([3], None),
        )
        self.assertEqual(
            parse_osn_title("Dachdeckermeister*in (Teilzeit)"),
            ([1, 2], "Dachdecker"),
        )

    def test_oldenburg_kdb_title_parsing(self):
        self.assertEqual(
            parse_sh_title(
                "Meistervorbereitung im Tischlerhandwerk (Teil I und II) in Teilzeit"
            ),
            ([1, 2], "Tischler"),
        )

    def test_ostfriesland_kdb_title_parsing(self):
        self.assertEqual(
            parse_sh_title("Meistervorbereitung im Elektrotechnikerhandwerk (Teil I und II)"),
            ([1, 2], "Elektrotechniker"),
        )

    def test_kdb_detail_urls(self):
        ol = HwkOldenburgScraper()
        self.assertTrue(ol._detail_url("MVK", "762", "12345").startswith(
            "https://www.hwk-oldenburg.de/weiterbildung/kurse-und-seminare#/vorlage/MVK/762"
        ))
        aur = HwkOstfrieslandScraper()
        self.assertTrue(aur._detail_url("MVK", "2961", "999").startswith(
            "https://www.hwk-aurich.de/weiterbildung/kurse-and-seminare-finden#/vorlage/MVK/2961"
        ))


class NiedersachsenRegistrationTests(unittest.TestCase):
    def test_all_chambers_registered(self):
        expected = {
            "hwk-braunschweig-lueneburg-stade": HwkBraunschweigLueneburgStadeScraper,
            "hwk-hannover": HwkHannoverScraper,
            "hwk-hildesheim-suedniedersachsen": HwkHildesheimSuedniedersachsenScraper,
            "hwk-oldenburg": HwkOldenburgScraper,
            "hwk-osnabrueck-emsland-grafschaft-bentheim": HwkOsnabrueckEmslandGrafschaftBentheimScraper,
            "hwk-ostfriesland": HwkOstfrieslandScraper,
        }
        for slug, cls in expected.items():
            self.assertIs(SCRAPERS[slug], cls)

    def test_chamber_metadata(self):
        scrapers = (
            HwkBraunschweigLueneburgStadeScraper(),
            HwkHannoverScraper(),
            HwkHildesheimSuedniedersachsenScraper(),
            HwkOldenburgScraper(),
            HwkOsnabrueckEmslandGrafschaftBentheimScraper(),
            HwkOstfrieslandScraper(),
        )
        for scraper in scrapers:
            self.assertEqual(scraper.chamber_region, "Niedersachsen")
            self.assertTrue(scraper.chamber_slug)
            self.assertTrue(scraper.chamber_name)
            self.assertTrue(scraper.chamber_website)


class NiedersachsenExamFeeTests(unittest.TestCase):
    def test_bls_pdf_fee_parsing(self):
        sample = """
        Meisterprüfung Teil 1
        Elektrotechniker 1.750,00 €
        Friseure 1.300,00 €
        Art der Meisterprüfung
        Teil II 590,00 €
        Teil III 690,00 €
        Teil IV 590,00 €
        """
        part_i = HwkBraunschweigLueneburgStadeScraper.parse_part_i_exam_fees(sample)
        generic = HwkBraunschweigLueneburgStadeScraper.parse_generic_exam_fees(sample)
        self.assertEqual(part_i["Elektrotechniker"], 1750.0)
        self.assertEqual(generic[2], 590.0)
        self.assertEqual(generic[4], 590.0)

    def test_hannover_pdf_fee_parsing(self):
        sample = """
        Meisterprüfung Teil I
        Elektrotechniker/in 500,00 €
        Teil II der Meisterprüfung:
        Alle 430,00 €
        Teil III der Meisterprüfung:
        Alle 330,00 €
        Teil IV der Meisterprüfung:
        Alle 350,00 €
        """
        part_i = HwkHannoverScraper.parse_part_i_exam_fees(sample)
        generic = HwkHannoverScraper.parse_generic_exam_fees(sample)
        self.assertEqual(part_i["Elektrotechniker"], 500.0)
        self.assertEqual(generic[3], 330.0)

    def test_ostfriesland_pdf_fee_parsing(self):
        sample = """
        4.1 Abnahme von Teilen der Meisterprüfung
         4.1.1 Teil I  390,00
         4.1.2 Teil II 360,00
         4.1.3 Teil III 250,00
         4.1.4 Teil IV 200,00
        """
        fees = HwkOstfrieslandScraper.parse_meister_exam_fees(sample)
        self.assertEqual(fees, {1: 390.0, 2: 360.0, 3: 250.0, 4: 200.0})

    def test_hildesheim_generic_exam_fees_from_2025_pdf_layout(self):
        sample = """
        3.1 Abnahme der Meisterprüfung
        a) Teil III
        b) Teil IV
           330,00 €
           349,00 €
        3.1.1 im Maurer und Betonbauer-Handwerk
        """
        self.assertEqual(
            HwkHildesheimSuedniedersachsenScraper.parse_generic_exam_fees(sample),
            {3: 330.0, 4: 349.0},
        )

    def test_hildesheim_resolves_current_gebuehrentarif_pdf(self):
        pdf_url = HwkHildesheimSuedniedersachsenScraper()._resolve_exam_fees_pdf_url()
        self.assertIn("gebuehrenordnung-und-gebuehrentarife", pdf_url.lower())
        self.assertIn("2025", pdf_url)
        self.assertNotIn("24,1918", pdf_url)

    @patch.object(HwkOstfrieslandScraper, "_fetch_exam_fees_from_pdf")
    def test_ostfriesland_exam_fee_resolution(self, mock_fetch):
        mock_fetch.return_value = {1: 390.0, 2: 360.0, 3: 250.0, 4: 200.0}
        rows = HwkOstfrieslandScraper().published_exam_fee_rows()
        lookup = build_exam_fee_lookup(rows, [])
        self.assertEqual(
            resolve_exam_fee("hwk-ostfriesland", "tischler", [1, 2], None, lookup)["fee"],
            750.0,
        )
        self.assertEqual(
            resolve_exam_fee("hwk-ostfriesland", "tischler", [3], None, lookup)["fee"],
            250.0,
        )


if __name__ == "__main__":
    unittest.main()
