import unittest

from scrapers.format_keys import parse_format_key


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


if __name__ == "__main__":
    unittest.main()
