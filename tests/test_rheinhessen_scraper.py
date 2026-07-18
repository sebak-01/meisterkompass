import unittest

from scrapers.hwk_rheinhessen import HwkRheinhessenScraper, parse_availability


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


if __name__ == "__main__":
    unittest.main()
