import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.base import RawCourseOffer
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
        elektro = (
            "Elektrotechnikermeister/in (Energie- und Gebäudetechnik) - Teile I und II"
        )
        self.assertEqual(
            parse_trade(elektro, parse_parts(elektro)),
            "Elektrotechniker (Energie- und Gebäudetechnik)",
        )
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
            "/kurse/example-78,0,coursedetail.html?id=458053&search-onr=78&img=4",
        )
        self.assertEqual(
            url,
            "https://www.hwk-ufr.de/78,0,coursedetail.html?id=458053",
        )

    def test_exam_fee_prose_patterns(self):
        from scrapers.hwk_bayern import parse_address, parse_exam_fee

        muenchen = (
            "Prüfungsgebühr 240,00 Euro Teil I und 200,00 Euro Teil II"
        )
        fee, qualifier = parse_exam_fee(muenchen, [1, 2])
        self.assertEqual(fee, 440.0)
        self.assertEqual(qualifier, "")

        schwaben = (
            "Prüfungsgebühr für Teil I: € 270,00 "
            "Prüfungsgebühr für Teil II: € 230,00 zzgl. gewerkspezifischer Prüfungsgebühr"
        )
        fee, qualifier = parse_exam_fee(schwaben, [1, 2])
        self.assertEqual(fee, 500.0)
        self.assertEqual(qualifier, "ca.")

        mittelfranken = "Prüfungsgebühr Teile I und II (zirka 680,00 €)"
        fee, qualifier = parse_exam_fee(mittelfranken, [1, 2])
        self.assertEqual(fee, 680.0)
        self.assertEqual(qualifier, "ca.")

        oberfranken_addr = parse_address(
            "Lehrgangsort\nKulmbach\nKontakt\nMarco Pollog\nTel. 0921 910127"
        )
        self.assertEqual(oberfranken_addr, ("", "", "Kulmbach"))

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

        schwaben = resolve_exam_fee(
            "hwk-schwaben", "any-trade", [3, 4], None, lookup
        )
        self.assertEqual(schwaben["fee"], 350.0)

    def test_niederbayern_disambiguates_parallel_city_runs(self):
        offers = [
            RawCourseOffer(
                title="Elektrotechniker (Teile I + II)",
                trade_name="Elektrotechniker",
                parts=[1, 2],
                format_key="full_time",
                teaching_mode="presence",
                start_date="2026-10-14",
                end_date="2027-06-18",
                duration_hours=1216,
                course_fee=8980.0,
                city=city,
            )
            for city in ("Landshut", "Regensburg")
        ]
        result = HwkNiederbayernOberpfalzScraper._disambiguate_parallel_runs(offers)
        self.assertTrue(all(" — " in offer.title for offer in result))

    def test_niederbayern_uses_listing_location_without_detail_request(self):
        soup = BeautifulSoup(
            """
            <div class="row">
              <h3>20.08.2026 - 01.12.2026: Vollzeit
                <a href="/kurse/example-76,0,coursedetail.html?id=42">
                  Fahrzeuglackierermeister/in - Teile I und II
                </a>
              </h3>
              <div>6.850,00 €</div>
              <div>584 Std.</div>
              <div>Regensburg</div>
              <div>freie Plätze</div>
            </div>
            """,
            "html.parser",
        )
        scraper = HwkNiederbayernOberpfalzScraper()
        scraper.parse_html = lambda _url: self.fail("detail page must not be requested")
        card = scraper._parse_card(soup.select_one("a"))
        offer = scraper._enrich(card)

        self.assertFalse(scraper.catalogue.details_required)
        self.assertEqual(offer.city, "Regensburg")
        self.assertEqual(offer.street, "Ditthornstraße 10")
        self.assertEqual(offer.zip_code, "93055")
        self.assertEqual(offer.course_fee, 6850.0)
        self.assertEqual(offer.duration_hours, 584)


if __name__ == "__main__":
    unittest.main()
