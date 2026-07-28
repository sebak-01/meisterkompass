import unittest

from bs4 import BeautifulSoup

from scrapers.hwk_rheinhessen import (
    HwkRheinhessenScraper,
    _afh_enrich_listing_from_detail,
    _afh_infer_format_and_mode,
    _afh_infer_parts,
    _afh_listing_to_offer,
    _afh_parse_search_page,
    parse_availability,
)


AFH_SEARCH_SNIPPET = """
<div class="" style="padding: 15px;">
  <div class="searchhit-header">
    <h3><a href="https://portal.afh-luebeck.de/kurs/seminar-mvk-kurs-31/">
      Meistervollzeitkurs Teile I - IV 2026/2027</a></h3>
  </div>
  <div class="searchhit-text clearfix">
    <p class="lead">Lübeck</p>
    <p class="margin-right-l">Das Meisterstudium dient zur gründlichen Vorbereitung …</p>
  </div>
  <div class="searchhit-text clearfix row">
    <div class="searchhit-text-item-key col-xs-6"><label>Termin</label></div>
    <div class="searchhit-text-item-value col-xs-6"><span>14.09.2026</span></div>
    <div class="searchhit-text-item-key col-xs-6"><label>Gebühren</label></div>
    <div class="searchhit-text-item-value col-xs-6"><span>15.950,00 &euro;</span></div>
  </div>
</div>
<hr>
<div class="" style="padding: 15px;">
  <div class="searchhit-header">
    <h3><a href="https://portal.afh-luebeck.de/kurs/seminar-mvik-iii-iv-kurs-26/">
      MVIK-III/IV 2026/2027 Online</a></h3>
  </div>
  <div class="searchhit-text clearfix">
    <p class="lead">ONLINE</p>
    <p class="margin-right-l">Vorbereitung auf die Teile III und IV der Meisterprüfung …</p>
  </div>
  <div class="searchhit-text clearfix row">
    <div class="searchhit-text-item-key col-xs-6"><label>Termin</label></div>
    <div class="searchhit-text-item-value col-xs-6"><span>14.12.2026</span></div>
    <div class="searchhit-text-item-key col-xs-6"><label>Gebühren</label></div>
    <div class="searchhit-text-item-value col-xs-6"><span>2.160,00 &euro;</span></div>
  </div>
</div>
"""

AFH_DETAIL_SNIPPET = """
<div id="uebersicht">
  <h3>Meistervollzeitkurs Lübeck</h3>
  <h4>14.09.2026 &mdash; 11.06.2027</h4>
  <label>afh Lübeck<br> Akademie für Hörakustik </label>
  <br>Bessemerstraße 3<br>23562 Lübeck
  <h4>Seminardauer</h4>
  <p>1313 Stunden</p>
  <h4>Gebühr</h4>
  <p>15.950,00 &euro;</p>
  <form class="uni_warenkorb_buy_form">
    <input type="hidden" name="waitlist" value="false" />
  </form>
</div>
"""


class RheinhessenAvailabilityTests(unittest.TestCase):
    def test_freie_plaetze_is_available(self):
        self.assertEqual(
            parse_availability("06.09.2027 - 24.11.2028\nEs gibt noch freie Plätze\nKurs buchen"),
            "available",
        )

    def test_kurs_buchen_without_badge_is_available(self):
        self.assertEqual(
            parse_availability("01.09.2026 - 13.11.2027\nKurs buchen\n750 Stunden"),
            "available",
        )

    def test_ausgebucht_is_full(self):
        self.assertEqual(
            parse_availability("01.09.2026 - 13.11.2027\nAusgebucht\nWarteliste"),
            "full",
        )

    def test_afbg_vollzeit_boilerplate_does_not_mark_full(self):
        block = (
            "06.09.2028 - 28.11.2029\n"
            "Es gibt noch freie Plätze\n"
            "Kurs buchen\n"
            "Kurstyp\nTeilzeit\n"
            "Seminardauer\n750 Stunden\n"
            "Gebühr zur Zeit\n6.700,00 Euro\n"
            "Aufstiegs-BAföG fördert Vollzeit- und Teilzeitmaßnahmen "
            "bei Lehrgangs- und Prüfungsgebühren.\n"
        )
        self.assertEqual(parse_availability(block), "available")


class RheinhessenRunExtractionTests(unittest.TestCase):
    def test_shared_fee_applies_to_all_date_runs(self):
        text = """
        Nächste Termine
        06.09.2027 - 24.11.2028
        Es gibt noch freie Plätze
        Kurs buchen
        06.09.2028 - 28.11.2029
        Es gibt noch freie Plätze
        Kurs buchen
        Kurstyp
        Teilzeit
        Seminardauer
        750 Stunden
        Gebühr zur Zeit
        6.700,00 Euro
        Aufstiegs-BAföG fördert Vollzeit- und Teilzeitmaßnahmen.
        """
        offers = HwkRheinhessenScraper()._extract_runs(
            text,
            "https://www.hwk.de/seminar/tischler-teile-i-und-ii-ti/",
            "Tischler",
            [1, 2],
            "part_time",
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(
            [(o.start_date, o.end_date, o.availability, o.course_fee, o.duration_hours) for o in offers],
            [
                ("2027-09-06", "2028-11-24", "available", 6700.0, 750),
                ("2028-09-06", "2029-11-28", "available", 6700.0, 750),
            ],
        )

    def test_mixed_availability_across_runs(self):
        text = """
        03.09.2026 - 18.01.2028
        Ausgebucht
        02.09.2027 - 23.01.2029
        Es gibt noch freie Plätze
        Kurs buchen
        Seminardauer
        800 Stunden
        6.600,00 Euro
        """
        offers = HwkRheinhessenScraper()._extract_runs(
            text,
            "https://www.hwk.de/seminar/dd/",
            "Dachdecker",
            [1, 2],
            "part_time",
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].availability, "full")
        self.assertEqual(offers[1].availability, "available")
        self.assertEqual(offers[0].course_fee, 6600.0)
        self.assertEqual(offers[1].course_fee, 6600.0)


class AfhHorakustikerParserTests(unittest.TestCase):
    def test_parse_search_page_extracts_meister_courses(self):
        listings = _afh_parse_search_page(BeautifulSoup(AFH_SEARCH_SNIPPET, "html.parser"))
        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0]["title"], "Meistervollzeitkurs Teile I - IV 2026/2027")
        self.assertEqual(listings[0]["parts"], [1, 2, 3, 4])
        self.assertEqual(listings[0]["format_key"], "full_time")
        self.assertEqual(listings[0]["course_fee"], 15950.0)
        self.assertEqual(listings[1]["parts"], [3, 4])
        self.assertEqual(listings[1]["teaching_mode"], "online")

    def test_detail_enrichment_adds_end_date_and_luebeck_address(self):
        listing = _afh_parse_search_page(BeautifulSoup(AFH_SEARCH_SNIPPET, "html.parser"))[0]
        _afh_enrich_listing_from_detail(listing, BeautifulSoup(AFH_DETAIL_SNIPPET, "html.parser"))
        self.assertEqual(listing["start_date"], "2026-09-14")
        self.assertEqual(listing["end_date"], "2027-06-11")
        self.assertEqual(listing["duration_hours"], 1313)
        self.assertEqual(listing["location"]["city"], "Lübeck")
        self.assertEqual(listing["location"]["street"], "Bessemerstraße 3")
        self.assertEqual(listing["availability"], "available")

    def test_listing_to_offer_uses_horakustiker_trade(self):
        listing = _afh_parse_search_page(BeautifulSoup(AFH_SEARCH_SNIPPET, "html.parser"))[0]
        _afh_enrich_listing_from_detail(listing, BeautifulSoup(AFH_DETAIL_SNIPPET, "html.parser"))
        offer = _afh_listing_to_offer(listing)
        self.assertEqual(offer.trade_name, "Hörakustiker")
        self.assertEqual(offer.parts, [1, 2, 3, 4])
        self.assertEqual(offer.city, "Lübeck")
        self.assertEqual(offer.scraped_raw["provider"], "Akademie für Hörakustik")

    def test_infer_parts_and_format_helpers(self):
        self.assertEqual(_afh_infer_parts("MVIK Lübeck Teile I & II 2027"), [1, 2])
        self.assertEqual(_afh_infer_parts("MVIK-III/IV 2026/2027 Online"), [3, 4])
        self.assertEqual(
            _afh_infer_format_and_mode("Meistervollzeitkurs Teile I - IV", "Lübeck")[0],
            "full_time",
        )
        self.assertEqual(
            _afh_infer_format_and_mode("MVIK Lübeck Teile I & II", "Lübeck", "Hybridformat")[1],
            "hybrid",
        )


if __name__ == "__main__":
    unittest.main()
