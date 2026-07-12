import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_bayern import (
    canonical_detail_url,
    parse_dates,
    parse_parts,
    parse_trade,
)
from scrapers.hwk_mittelfranken import HwkMittelfrankenScraper
from scrapers.hwk_muenchen_und_oberbayern import HwkMuenchenUndOberbayernScraper
from scrapers.hwk_niederbayern_oberpfalz import HwkNiederbayernOberpfalzScraper
from scrapers.hwk_oberfranken import HwkOberfrankenScraper
from scrapers.hwk_schwaben import HwkSchwabenScraper
from scrapers.hwk_unterfranken import HwkUnterfrankenScraper
from scrapers.pipeline import SCRAPERS


def course_card(title: str, details: str = "") -> BeautifulSoup:
    return BeautifulSoup(
        f"""
        <div class="row">
          <h3>07.12.2026 - 19.11.2027: Blended Learning
            <a href="/kurse/example,coursedetail.html?id=458053&search-onr=78&img=4">
              {title}
            </a>
          </h3>
          <p>{details}</p>
        </div>
        """,
        "html.parser",
    )


class BavariaParserTests(unittest.TestCase):
    def test_part_variants_and_implicit_schwaben_parts(self):
        self.assertEqual(parse_parts("Meisterkurs Teil I/II"), [1, 2])
        self.assertEqual(parse_parts("Meisterschule Teile I - IV"), [1, 2, 3, 4])
        self.assertEqual(parse_parts("Ausbildereignung (AdA)"), [4])
        self.assertEqual(
            parse_parts("Metallbauer-Meisterkurs", implicit_trade_parts=True),
            [1, 2],
        )

    def test_trade_aliases_and_generic_parts(self):
        title = "Schreiner-/Tischlermeister/in - Teile I und II"
        parts = parse_parts(title)
        self.assertEqual(parts, [1, 2])
        self.assertEqual(parse_trade(title, parts), "Tischler")
        mk_title = "MK Installateur-/ Heizungsbauerhandwerk Teil I u. II"
        self.assertEqual(
            parse_trade(mk_title, parse_parts(mk_title)),
            "Installateur- und Heizungsbauer",
        )
        self.assertIsNone(parse_trade("Teile III und IV für alle Gewerke", [3, 4]))

    def test_exact_and_approximate_dates(self):
        self.assertEqual(
            parse_dates("31.08.2026 - 30.10.2026"),
            ("2026-08-31", "2026-10-30"),
        )
        self.assertEqual(
            parse_dates("September 2027 - Februar 2029"),
            ("2027-09-01", "2029-02-01"),
        )

    def test_detail_url_drops_volatile_listing_parameters(self):
        url = canonical_detail_url(
            "https://www.hwk-ufr.de",
            "/kurse/example,coursedetail.html?id=458053&search-onr=78&img=4",
        )
        self.assertEqual(
            url,
            "https://www.hwk-ufr.de/kurse/example,coursedetail.html?id=458053",
        )

    def test_detail_enrichment_splits_course_and_exam_fees(self):
        scraper = HwkUnterfrankenScraper()
        card_soup = course_card(
            "Online/Hybrid Metallbauer-Meister Teil I und II, Teilzeit",
            "9.770,00 € (inkl. Prüfung) 800 UE Schweinfurt freie Plätze",
        )
        card = scraper._parse_card(card_soup.select_one("a"))
        detail = BeautifulSoup(
            """
            <main>
              <h1>Online/Hybrid Metallbauer-Meister Teil I und II, Teilzeit</h1>
              <p>ausreichend freie Plätze</p>
              <h3>Gebühren</h3><p>Kurs: 9.140,00 €<br>Prüfung: 630,00 €</p>
              <h3>Unterricht</h3>
              <p>07.12.2026 - 19.11.2027<br>Präsenz und Online in Teilzeit<br>
                 Lehrgangsdauer 800 UE</p>
              <h3>Lehrgangsort</h3><p>Galgenleite 3<br>97424 Schweinfurt</p>
            </main>
            """,
            "html.parser",
        )
        scraper.parse_html = lambda _url: detail
        offer = scraper._enrich(card)

        self.assertEqual(offer.trade_name, "Metallbauer")
        self.assertEqual(offer.parts, [1, 2])
        self.assertEqual(offer.course_fee, 9140.0)
        self.assertEqual(offer.exam_fee_scraped, 630.0)
        self.assertEqual(offer.teaching_mode, "hybrid")
        self.assertEqual(offer.street, "Galgenleite 3")
        self.assertEqual(offer.zip_code, "97424")
        self.assertEqual(offer.city, "Schweinfurt")

    def test_mittelfranken_joint_course_gets_distinct_identities(self):
        scraper = HwkMittelfrankenScraper()
        card_soup = course_card(
            "Meisterlehrgang im Feinwerkmechanikerhandwerk und "
            "Metallbauerhandwerk, Teile I und II",
            "8.000,00 € 800 UE Nürnberg freie Plätze",
        )
        card = scraper._parse_card(card_soup.select_one("a"))
        detail = BeautifulSoup(
            """
            <main>
              <h1>Meisterlehrgang im Feinwerkmechanikerhandwerk und
                  Metallbauerhandwerk, Teile I und II</h1>
              <p>freie Plätze</p>
              <h3>Gebühren</h3><p>Kurs: 8.000,00 €</p>
              <h3>Unterricht</h3><p>07.12.2026 - 19.11.2027 Teilzeit 800 UE</p>
              <h3>Lehrgangsort</h3><p>Sieboldstraße 9<br>90411 Nürnberg</p>
            </main>
            """,
            "html.parser",
        )
        scraper.parse_html = lambda _url: detail
        offers = scraper._enrich(card)

        self.assertEqual({offer.trade_name for offer in offers}, {"Feinwerkmechaniker", "Metallbauer"})
        self.assertEqual(len({offer.source_url for offer in offers}), 2)


class BavariaRegistrationTests(unittest.TestCase):
    def test_all_six_chambers_are_registered(self):
        expected = {
            "hwk-muenchen-und-oberbayern": HwkMuenchenUndOberbayernScraper,
            "hwk-niederbayern-oberpfalz": HwkNiederbayernOberpfalzScraper,
            "hwk-oberfranken": HwkOberfrankenScraper,
            "hwk-mittelfranken": HwkMittelfrankenScraper,
            "hwk-unterfranken": HwkUnterfrankenScraper,
            "hwk-schwaben": HwkSchwabenScraper,
        }
        for slug, scraper_class in expected.items():
            self.assertIs(SCRAPERS[slug], scraper_class)
            self.assertEqual(scraper_class.chamber_region, "Bayern")

    def test_published_generic_exam_fee_schedules(self):
        fee_path = Path(__file__).resolve().parents[1] / "data/manual/exam_fees_manual.json"
        lookup = build_exam_fee_lookup([], json.loads(fee_path.read_text(encoding="utf-8")))

        mittelfranken = resolve_exam_fee(
            "hwk-mittelfranken", "metallbauer", [1, 2], None, lookup
        )
        schwaben = resolve_exam_fee(
            "hwk-schwaben", "any-trade", [3, 4], None, lookup
        )
        self.assertEqual(mittelfranken["fee"], 630.0)
        self.assertEqual(schwaben["fee"], 350.0)


if __name__ == "__main__":
    unittest.main()
