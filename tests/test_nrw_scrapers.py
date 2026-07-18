import re
import unittest
from unittest.mock import patch

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_aachen import HwkAachenScraper, parse_aachen_title
from scrapers.hwk_bayern import parse_exam_fee
from scrapers.hwk_dortmund import (
    HwkDortmundScraper,
    parse_availability_from_stock_html,
    parse_availability_from_variations,
    parse_dortmund_title,
)
from scrapers.hwk_duesseldorf import HwkDuesseldorfScraper, parse_duesseldorf_title
from scrapers.hwk_koeln import HwkKoelnScraper, parse_koeln_title
from scrapers.hwk_muenster import HwkMuensterScraper, parse_muenster_title
from scrapers.hwk_ostwestfalen_lippe_zu_bielefeld import (
    HwkOstwestfalenLippeZuBielefeldScraper,
    parse_owl_title,
    _is_meister_card,
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
        self.assertEqual(
            parse_suedwestfalen_title(
                "Geprüfte/r Fachfrau/Fachmann für kaufmännische Betriebsführung (HWO)"
            ),
            ([3], None),
        )

    def test_owl_teil_iii_iv_card_detection(self):
        self.assertTrue(
            _is_meister_card(
                "27.07.2026 - 18.09.2026: Vollzeit Fachmann/-frau kaufmännische Betriebsführung"
            )
        )
        self.assertTrue(
            _is_meister_card("31.08.2026 - 19.09.2026: Vollzeit AdA - Ausbildung der Ausbilder (Teil IV)")
        )

    def test_owl_exam_fee_range_parsing(self):
        sample = """
        5. Meisterprüfung
        a) Teil I (praktischer Teil) und Teil II, III oder IV
         (theoretische Teile)            580,00 bis 3.200,00 Euro
        b) Teil I (praktischer Teil)         380,00 bis 2.450,00 Euro
        c) Teil II, III oder IV (theoretische Teile)          250,00 bis 980,00 Euro
        6. Fortbildungsprüfung
        """
        fees, combo = HwkOstwestfalenLippeZuBielefeldScraper.parse_meister_exam_fees(sample)
        self.assertEqual(fees[1]["fee"], 380.0)
        self.assertEqual(fees[1]["fee_max"], 2450.0)
        self.assertEqual(fees[2]["fee"], 250.0)
        self.assertEqual(fees[2]["fee_max"], 980.0)
        self.assertEqual(combo["fee"], 580.0)
        self.assertEqual(combo["fee_max"], 3200.0)

    def test_owl_teile_i_ii_uses_package_fee_not_sum(self):
        rows = [
            {
                "chamber_slug": "hwk-ostwestfalen-lippe-zu-bielefeld",
                "trade_slug": None,
                "part": 1,
                "fee": 380.0,
                "fee_max": 2450.0,
            },
            {
                "chamber_slug": "hwk-ostwestfalen-lippe-zu-bielefeld",
                "trade_slug": None,
                "part": 2,
                "fee": 250.0,
                "fee_max": 980.0,
            },
            {
                "chamber_slug": "hwk-ostwestfalen-lippe-zu-bielefeld",
                "trade_slug": None,
                "parts": [1, 2],
                "fee": 580.0,
                "fee_max": 3200.0,
            },
        ]
        lookup = build_exam_fee_lookup(rows, [])
        resolved = resolve_exam_fee(
            "hwk-ostwestfalen-lippe-zu-bielefeld", "metallbauer", [1, 2], None, lookup
        )
        self.assertEqual(resolved["fee"], 580.0)
        self.assertEqual(resolved["fee_max"], 3200.0)
        self.assertNotEqual(resolved["fee"], 630.0)

    def test_suedwestfalen_course_page_parsing(self):
        from bs4 import BeautifulSoup

        html = """
        <h1>Meisterkurs Elektrotechnik Vollzeit</h1>
        <p>Lehrgangsdauer: 1250 Unterrichtsstunden</p>
        <p>10.880,00 € (zzgl. Prüfungsgebühr 1.000,00 € )</p>
        <h4>12.10.2026 — 11.06.2027</h4><a href="/buchung/...">ausgebucht</a>
        <h4>11.10.2027 — 09.06.2028</h4><a href="/buchung/.../new-waitlist">Warteliste</a>
        <p>Prüfungsgebühr: 1.000 EUR</p>
        """
        soup = BeautifulSoup(html, "html.parser")
        offers = HwkSuedwestfalenScraper()._parse_course_page(
            soup, "https://www.bbz-arnsberg.de/kurse/meisterkurs-elektrotechnik-vollzeit"
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].duration_hours, 1250)
        self.assertEqual(offers[0].course_fee, 10880.0)
        self.assertEqual(offers[0].exam_fee_scraped, 1000.0)
        self.assertEqual(offers[0].availability, "full")
        self.assertEqual(offers[1].availability, "waitlist")
        self.assertEqual(offers[0].start_date, "2026-10-12")

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
              <svg class="icon icon--course-state icon--course-fully-booked">
                <use xlink:href="#triangle-sharp-solid"></use>
              </svg>
              <span class="date">22.10.27 - 19.01.30</span>
            </label>
          </li>
          <li class="course-detail__dates-list-item">
            <label class="course-detail__date-choice-label">
              <svg class="icon icon--course-state icon--course-open">
                <use xlink:href="#circle-solid"></use>
              </svg>
              <span class="date">06.05.30 - 30.11.30</span>
            </label>
          </li>
        </div>
        """
        runs = HwkMuensterScraper._parse_runs(BeautifulSoup(html, "html.parser"))
        self.assertEqual(runs[0][:2], ("2027-10-22", "2030-01-19"))
        self.assertEqual(runs[0][2], "waitlist")
        self.assertEqual(runs[1][2], "available")

    def test_muenster_structured_fee_parsing(self):
        from bs4 import BeautifulSoup

        html = """
        <ul class="course-detail__fee-list">
          <li class="course-detail__fee-list-item">
            <span class="course-detail__fee-label">Kursgebühr</span>
            <span class="course-detail__fee-value">13.312,69&nbsp;€</span>
          </li>
          <li class="course-detail__fee-list-item">
            <span class="course-detail__fee-label">Prüfungsgebühr</span>
            <span class="course-detail__fee-value">1.850,00&nbsp;€</span>
          </li>
        </ul>
        <p>Durch das Aufstiegs-BAföG erhältst du eine Förderung von bis zu 11.250,00 €</p>
        """
        soup = BeautifulSoup(html, "html.parser")
        course_fee, exam_fee = HwkMuensterScraper._parse_fees(soup)
        self.assertEqual(course_fee, 13312.69)
        self.assertEqual(exam_fee, 1850.0)

    def test_aachen_course_page_exam_fee(self):
        sample = "Hinweis\nPrüfungsgebühr: 610 Euro\nMaterial-/Bücherkosten: ca. 2.200 EUR"
        fee, qualifier = parse_exam_fee(sample, [1, 2])
        self.assertEqual(fee, 610.0)
        self.assertEqual(qualifier, "")

    def test_duesseldorf_course_page_exam_fee(self):
        sample = (
            "zurzeit 1.470,00 Euro Prüfungsgebühren und\n"
            "ca.1.950,00 Euro Lernmittel"
        )
        fee, qualifier = parse_exam_fee(sample, [1, 2])
        self.assertEqual(fee, 1470.0)
        self.assertEqual(qualifier, "")

    def test_dortmund_exam_fee_from_bue_prices(self):
        html = (
            '"bue_additional_prices":[{"bezeichnung":"Kurskosten","gebuehr":10950},'
            '{"bezeichnung":"Prüfungsgebühr","gebuehr":1224}]'
        )
        self.assertEqual(HwkDortmundScraper._parse_exam_fee(html), 1224.0)

    def test_dortmund_fees_prefer_bue_kurskosten_over_zero_display_price(self):
        html = (
            '"display_price":0,"display_regular_price":0,'
            '"display_price":8210,"display_regular_price":8210,'
            '"bue_additional_prices":[{"bezeichnung":"Prüfungsgebühr","gebuehr":1514},'
            '{"bezeichnung":"Kurskosten","gebuehr":6696}]'
        )
        course_fee, exam_fee = HwkDortmundScraper._parse_fees(html)
        self.assertEqual(course_fee, 6696.0)
        self.assertEqual(exam_fee, 1514.0)

    def test_dortmund_format_prefers_title_teilzeit(self):
        self.assertEqual(
            HwkDortmundScraper._parse_format(
                "Dachdecker/in Teilzeitlehrgang(Meistervorbereitung Teile I und II)",
                "AFBG fördert Vollzeit-Lehrgang und Teilzeit-Lehrgang",
            ),
            "part_time",
        )

    def test_dortmund_duration_unterrichtseinheiten(self):
        sample = "Umfang: 1264 Unterrichtseinheiten"
        match = re.search(
            r"([\d.]+)\s+(?:Unterrichtseinheiten|Unterrichtsstunden|UE|Std\.)",
            sample,
            re.IGNORECASE,
        )
        self.assertEqual(int(match.group(1)), 1264)

    def test_dortmund_display_price_parsing(self):
        html = '<script>"display_price":10260,"display_regular_price":10260</script>'
        course_fee, exam_fee = HwkDortmundScraper._parse_fees(html)
        self.assertEqual(course_fee, 10260.0)
        self.assertIsNone(exam_fee)

    def test_dortmund_availability_from_stock_html(self):
        self.assertEqual(
            parse_availability_from_stock_html(
                '<p class="stock in-stock">22 Plätze verfügbar</p>'
            ),
            "available",
        )
        self.assertEqual(
            parse_availability_from_stock_html(
                '<p class="stock in-stock">1 Platz verfügbar</p>'
            ),
            "available",
        )
        self.assertEqual(
            parse_availability_from_stock_html(
                '<p class="stock available-on-backorder">Ausgebucht. Auf Warteliste setzen.</p>'
            ),
            "waitlist",
        )

    def test_dortmund_availability_from_variations_matches_selected_termin(self):
        from bs4 import BeautifulSoup

        html = """
        <form class="variations_form" data-product_variations='[
          {
            "attributes": {"attribute_termin": "18.01.2027 - 08.07.2028 (Bildungszentrum)"},
            "availability_html": "<p class=\\"stock in-stock\\">22 Plätze verfügbar</p>"
          }
        ]'>
          <p>18.01.2027 - 08.07.2028</p>
        </form>
        <footer>Interessentenliste und Ausgebucht in anderen Kursen</footer>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(
            parse_availability_from_variations(soup, "2027-01-18", "2028-07-08"),
            "available",
        )

    def test_dortmund_page_availability_ignores_footer_boilerplate(self):
        from bs4 import BeautifulSoup

        html = """
        <form class="variations_form" data-product_variations='[
          {
            "attributes": {"attribute_termin": "20.07.2026 - 15.09.2026 (Bildungszentrum)"},
            "availability_html": "<p class=\\"stock in-stock\\">1 Platz verfügbar</p>"
          },
          {
            "attributes": {"attribute_termin": "14.09.2026 - 10.11.2026 (Bildungszentrum)"},
            "availability_html": "<p class=\\"stock available-on-backorder\\">Ausgebucht. Auf Warteliste setzen.</p>"
          }
        ]'>
          <p>20.07.2026 - 15.09.2026</p>
        </form>
        <footer>Ausgebucht Interessentenliste Ausgebucht</footer>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(
            parse_availability_from_variations(soup, "2026-07-20", "2026-09-15"),
            "available",
        )

    def test_suedwestfalen_exam_fee_tariff_parsing(self):
        sample = """
        4.  Meisterprüfung
        a)  Teil I 380,00 – 2.300,00
        b)  Teile I und II 580,00 - 2500,00
        c)  ein theoretischer Teil  250,00 -   400,00
        Für Wiederholungsprüfungen gelten die Gebühren entsprechend,
        """
        fees, combo = HwkSuedwestfalenScraper.parse_meister_exam_fees(sample)
        self.assertEqual(fees[1]["fee"], 380.0)
        self.assertEqual(fees[1]["fee_max"], 2300.0)
        self.assertEqual(fees[2]["fee"], 250.0)
        self.assertEqual(combo["fee"], 580.0)
        self.assertEqual(combo["fee_max"], 2500.0)

    def test_suedwestfalen_title_friseure_and_combined_metal(self):
        self.assertEqual(
            parse_suedwestfalen_title("Meisterkurs Friseure"),
            ([1, 2], "Friseur"),
        )
        self.assertEqual(
            parse_suedwestfalen_title("Meisterkurs Feinwerkmechaniker/Metallbauer"),
            ([1, 2], "Feinwerkmechaniker"),
        )
        self.assertEqual(
            parse_suedwestfalen_title("Meisterkurs Stuckateure"),
            ([1, 2], "Stuckateur"),
        )


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

    def test_suedwestfalen_fee_and_run_parsing(self):
        from bs4 import BeautifulSoup

        course_fee, exam_fee = HwkSuedwestfalenScraper._parse_fees(
            "10.880,00 € (zzgl. Prüfungsgebühr 1.000,00 € )"
        )
        self.assertEqual(course_fee, 10880.0)
        self.assertEqual(exam_fee, 1000.0)

        runs = HwkSuedwestfalenScraper._parse_runs(
            BeautifulSoup("", "html.parser"),
            "#### 12.10.2026 — 16.04.2027\nWarteliste\n#### 18.10.2027 — 26.04.2028\nWarteliste",
        )
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0][2], "waitlist")


if __name__ == "__main__":
    unittest.main()
