import re
import unittest

from bs4 import BeautifulSoup

from scrapers.base import (
    ancestor_matching,
    canonicalize_trade_name,
    city_between,
    german_amount,
    harmonize_course_record,
    normalize_trade,
)


class TradeNormalizationTests(unittest.TestCase):
    def test_plural_trade_names_map_to_singular(self):
        self.assertEqual(canonicalize_trade_name("Konditoren"), "Konditor")
        self.assertEqual(canonicalize_trade_name("Stuckateure"), "Stuckateur")
        self.assertEqual(canonicalize_trade_name("Friseure"), "Friseur")

    def test_handwerk_suffix_and_partial_trade_names(self):
        self.assertEqual(
            canonicalize_trade_name("Schilder- und Lichtreklamehersteller-Handwerk"),
            "Schilder- und Lichtreklamehersteller",
        )
        self.assertEqual(canonicalize_trade_name("Maler"), "Maler und Lackierer")
        self.assertEqual(canonicalize_trade_name("Zahntechnik"), "Zahntechniker")

    def test_normalize_trade_uses_canonical_slug(self):
        self.assertEqual(normalize_trade("Konditoren"), ("konditor", "Konditor"))
        self.assertEqual(
            normalize_trade("Schilder- und Lichtreklamehersteller-Handwerk"),
            ("schilder-und-lichtreklamehersteller", "Schilder- und Lichtreklamehersteller"),
        )
        self.assertEqual(normalize_trade("Maler"), ("maler-und-lackierer", "Maler und Lackierer"))
        self.assertEqual(normalize_trade("Zahntechnik"), ("zahntechniker", "Zahntechniker"))

    def test_normalize_trade_maps_specialization_slug_to_parent(self):
        self.assertEqual(
            normalize_trade("Maler und Lackierer (Fahrzeuglackierer)"),
            ("maler-und-lackierer", "Maler und Lackierer (Fahrzeuglackierer)"),
        )

    def test_harmonize_course_record_rebuilds_title(self):
        rec = {
            "trade_name": "Konditoren",
            "trade_slug": "konditoren",
            "title": "Konditoren (Teile I + II)",
            "parts": [1, 2],
        }
        harmonize_course_record(rec)
        self.assertEqual(rec["trade_name"], "Konditor")
        self.assertEqual(rec["trade_slug"], "konditor")
        self.assertEqual(rec["title"], "Konditor (Teile I + II)")


class GermanAmountTests(unittest.TestCase):
    def test_thousands_dot_is_a_separator_not_a_decimal_point(self):
        self.assertEqual(german_amount("1.234", "56"), 1234.56)
        self.assertEqual(german_amount("12.345", "00"), 12345.0)

    def test_missing_cents_group_means_whole_euros(self):
        """Chamber pages write "1.234,-", leaving the cents group unmatched."""
        self.assertEqual(german_amount("990", None), 990.0)
        self.assertEqual(german_amount("1.234", None), 1234.0)
        self.assertEqual(german_amount("990"), 990.0)

    def test_cents_are_not_truncated(self):
        self.assertEqual(german_amount("0", "05"), 0.05)


class CityBetweenTests(unittest.TestCase):
    DURATION = re.compile(r"(\d+)[\s\xa0]*(?:Std\.|UE|UStd\.)", re.IGNORECASE)
    AVAIL = re.compile(r"ausgebucht|freie\s+Pl\u00e4tze", re.IGNORECASE)

    def city(self, text, default="Koblenz"):
        return city_between(
            text, self.DURATION.search(text), self.AVAIL.search(text), default=default,
        )

    def test_reads_the_bare_line_between_duration_and_availability(self):
        self.assertEqual(self.city("650 Std.\nMayen\nfreie Pl\u00e4tze"), "Mayen")

    def test_accepts_hyphenated_and_multiword_city_names(self):
        self.assertEqual(
            self.city("650 Std.\nNeustadt-Glewe\nfreie Pl\u00e4tze"), "Neustadt-Glewe",
        )
        self.assertEqual(
            self.city("650 Std.\nBad Kreuznach\nfreie Pl\u00e4tze"), "Bad Kreuznach",
        )

    def test_skips_lines_carrying_digits_dots_or_slashes(self):
        """Course prose shares the gap; only a bare letters-only line is a city."""
        self.assertEqual(
            self.city("650 Std.\nKurs-Nr. 4711\nMayen\nfreie Pl\u00e4tze"), "Mayen",
        )

    def test_falls_back_when_a_marker_is_missing(self):
        self.assertEqual(self.city("650 Std.\nMayen"), "Koblenz")
        self.assertEqual(self.city("Mayen\nfreie Pl\u00e4tze"), "Koblenz")

    def test_falls_back_when_availability_precedes_duration(self):
        self.assertEqual(self.city("freie Pl\u00e4tze\nMayen\n650 Std."), "Koblenz")

    def test_falls_back_when_the_gap_holds_no_city_line(self):
        self.assertEqual(self.city("650 Std.\nKurs-Nr. 4711\nfreie Pl\u00e4tze"), "Koblenz")


class AncestorMatchingTests(unittest.TestCase):
    HTML = """
        <div class="run"><span>Kursnummer 4711</span>
          <section><article><h4 id="d">01.02.2027</h4></article></section>
        </div>
    """

    def heading(self):
        return BeautifulSoup(self.HTML, "html.parser").find(id="d")

    def test_returns_the_first_ancestor_satisfying_the_predicate(self):
        found = ancestor_matching(
            self.heading(), lambda text: "Kursnummer" in text, max_depth=6,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.get("class"), ["run"])

    def test_stops_at_max_depth(self):
        """The marker sits three levels up; a shallower budget must not reach it."""
        self.assertIsNone(
            ancestor_matching(self.heading(), lambda text: "Kursnummer" in text, max_depth=2),
        )

    def test_returns_none_when_no_ancestor_matches(self):
        self.assertIsNone(
            ancestor_matching(self.heading(), lambda text: "Geb\u00fchr" in text, max_depth=6),
        )


if __name__ == "__main__":
    unittest.main()
