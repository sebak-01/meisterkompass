import unittest

from scrapers.format_keys import parse_format_key, strip_odav_alternate_runs


class FormatKeyTests(unittest.TestCase):
    def test_berufsbegleitend_wins_over_vollzeit_mention(self):
        text = (
            "05.04.2027 - 15.01.2028 Berufsbegleitend Frankfurt (Oder) "
            "Mo. und Sa.:08:00 - 15:00 Uhr (ca. 2 Wochen in Vollzeit)"
        )
        self.assertEqual(parse_format_key(text), "part_time")

    def test_vollzeit_run(self):
        self.assertEqual(parse_format_key("14.06.2027 - 06.05.2028 Vollzeit"), "full_time")

    def test_abendkurs_is_part_time(self):
        self.assertEqual(parse_format_key("Abendkurs Mo-Do"), "part_time")

    def test_tageskurs_is_full_time(self):
        self.assertEqual(parse_format_key("Tageskurs"), "full_time")

    def test_strip_odav_alternate_runs_removes_other_formats(self):
        text = (
            "Unterricht\n05.10.2026 - 15.05.2027\nVollzeit\n"
            "Alle Termine\n19.02.2027 - 15.07.2028: Teilzeit"
        )
        self.assertEqual(
            parse_format_key(strip_odav_alternate_runs(text)),
            "full_time",
        )


if __name__ == "__main__":
    unittest.main()
