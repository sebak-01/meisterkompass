import unittest

from scrapers.hwk_saarland import HwkSaarlandScraper


class SaarlandScraperTests(unittest.TestCase):
    def test_availability_keine_plaetze_mehr_frei_is_full(self):
        scraper = HwkSaarlandScraper()
        self.assertEqual(
            scraper._parse_availability("Kurstyp: Teilzeit\n(Keine Plätze mehr frei)\nDetails"),
            "full",
        )

    def test_availability_buchung_nicht_mehr_moeglich_is_full(self):
        scraper = HwkSaarlandScraper()
        self.assertEqual(
            scraper._parse_availability(
                "Eine Buchung ist nicht mehr möglich\nBereits ausgebucht"
            ),
            "full",
        )

    def test_availability_es_gibt_noch_freie_plaetze_is_available(self):
        scraper = HwkSaarlandScraper()
        self.assertEqual(
            scraper._parse_availability("Kurstyp: Teilzeit\nEs gibt noch freie Plätze"),
            "available",
        )

    def test_parse_runs_stops_context_before_next_termin(self):
        text = """
        24.11.2026 — 22.04.2027
        Kurstyp: Teilzeit
        (Keine Plätze mehr frei)
        Details
        15.01.2028 — 20.06.2028
        Kurstyp: Teilzeit
        Es gibt noch freie Plätze
        Details
        """
        runs = HwkSaarlandScraper()._parse_runs(text)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["availability"], "full")
        self.assertEqual(runs[1]["availability"], "available")

    def test_parse_runs_m2ih_three_termin_blocks(self):
        """Live m2ih page: two fully booked runs must not bleed into the open run."""
        text = """
        22.08.2026 — 27.11.2027
        Kurstyp: Teilzeit
        (Keine Plätze mehr frei)
        Details
        17.08.2027 — 23.11.2028
        Kurstyp: Teilzeit
        (Keine Plätze mehr frei)
        Details
        19.08.2028 — 22.11.2029
        Kurstyp: Teilzeit
        Es gibt noch freie Plätze
        Details
        """
        runs = HwkSaarlandScraper()._parse_runs(text)
        self.assertEqual(len(runs), 3)
        self.assertEqual([r["availability"] for r in runs], ["full", "full", "available"])


if __name__ == "__main__":
    unittest.main()
