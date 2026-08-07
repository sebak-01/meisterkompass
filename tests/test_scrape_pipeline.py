import unittest
from pathlib import Path
import tempfile

from scrapers.base import ScrapeResult
from scrapers.pipeline import (
    SCRAPE_GROUPS,
    SCRAPERS,
    ScrapeBatch,
    _is_online_location,
    _scrape_workers,
    apply_coordinates,
    _to_iso,
    build_course_fees,
    merge_scrape_partials,
    write_scrape_partial,
)


class ScrapeGroupsTests(unittest.TestCase):
    def test_groups_cover_all_scrapers(self):
        grouped = {slug for slugs in SCRAPE_GROUPS.values() for slug in slugs}
        self.assertEqual(grouped, set(SCRAPERS))

    def test_groups_are_disjoint(self):
        seen = []
        for slugs in SCRAPE_GROUPS.values():
            seen.extend(slugs)
        self.assertEqual(len(seen), len(set(seen)))


class ScrapeWorkersTests(unittest.TestCase):
    def test_small_batches_run_fully_parallel(self):
        self.assertEqual(_scrape_workers(13), 13)

    def test_large_batches_are_capped(self):
        self.assertEqual(_scrape_workers(53), 15)


class MergePartialsTests(unittest.TestCase):
    def test_merge_partials_combines_batches(self):
        batch_a = ScrapeBatch(
            fresh_by_chamber={"hwk-berlin": [{"id": "a"}]},
            scraped_exam_rows=[{"chamber_slug": "hwk-berlin", "parts": [1], "fee": 100.0}],
            results={
                "hwk-berlin": ScrapeResult(
                    chamber_slug="hwk-berlin",
                    chamber_name="Handwerkskammer Berlin",
                    chamber_region="Berlin",
                    chamber_website="https://example.de",
                ),
            },
            per_chamber={"hwk-berlin": 1},
        )
        batch_b = ScrapeBatch(
            fresh_by_chamber={"hwk-bremen": [{"id": "b"}]},
            scraped_exam_rows=[],
            results={
                "hwk-bremen": ScrapeResult(
                    chamber_slug="hwk-bremen",
                    chamber_name="Handwerkskammer Bremen",
                    chamber_region="Bremen",
                    chamber_website="https://example.de",
                ),
            },
            per_chamber={"hwk-bremen": 1},
        )

        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "partial-a.json"
            p2 = Path(tmp) / "partial-b.json"
            write_scrape_partial(batch_a, p1, ["hwk-berlin"])
            write_scrape_partial(batch_b, p2, ["hwk-bremen"])
            report = merge_scrape_partials([p1, p2], dry_run=True)

        self.assertEqual(report.per_chamber["hwk-berlin"], 1)
        self.assertEqual(report.per_chamber["hwk-bremen"], 1)
        self.assertEqual(report.total_courses, 2)


class OnlineLocationGeocodeTests(unittest.TestCase):
    def test_online_city_is_detected(self):
        self.assertTrue(_is_online_location("Online"))
        self.assertTrue(_is_online_location(" online "))
        self.assertFalse(_is_online_location("Lübeck"))
        self.assertFalse(_is_online_location("Onlinekursstadt"))

    def test_apply_coordinates_skips_online_venues(self):
        class FakeGeocoder:
            def lookup(self, query):
                raise AssertionError(f"must not geocode online venue: {query}")

        records = [
            {
                "chamber_slug": "hwk-rheinhessen",
                "city": "Online",
                "street": "",
                "zip_code": "",
                "chamber_region": "Rheinland-Pfalz",
                "latitude": 49.19,
                "longitude": 7.60,
            },
            {
                "chamber_slug": "hwk-rheinhessen",
                "city": "Lübeck",
                "street": "Bessemerstraße 3",
                "zip_code": "23562",
                "chamber_region": "Rheinland-Pfalz",
                "latitude": None,
                "longitude": None,
            },
        ]

        class SelectiveGeocoder(FakeGeocoder):
            def lookup(self, query):
                if "Online" in query:
                    raise AssertionError(f"must not geocode online venue: {query}")
                return (53.84, 10.70)

        apply_coordinates(records, SelectiveGeocoder())
        self.assertIsNone(records[0]["latitude"])
        self.assertIsNone(records[0]["longitude"])
        self.assertEqual(records[1]["latitude"], 53.84)
        self.assertEqual(records[1]["longitude"], 10.70)


class DateValidationTests(unittest.TestCase):
    """Scrapers assemble start_date strings from regex groups, so a site changing
    its date format can emit something no calendar accepts. Every downstream
    string comparison tolerates that, but build_course_fees called
    date.fromisoformat() on it and aborted the entire write — after all 60
    chambers had already been scraped."""

    def test_valid_iso_date_passes_through(self):
        self.assertEqual(_to_iso("2026-09-07"), "2026-09-07")

    def test_date_objects_are_serialised(self):
        import datetime

        self.assertEqual(_to_iso(datetime.date(2026, 9, 7)), "2026-09-07")

    def test_none_stays_none(self):
        self.assertIsNone(_to_iso(None))

    def test_impossible_date_is_discarded(self):
        with self.assertLogs("scrapers.pipeline", level="WARNING"):
            self.assertIsNone(_to_iso("2026-13-45"))

    def test_partial_and_prose_dates_are_discarded(self):
        with self.assertLogs("scrapers.pipeline", level="WARNING"):
            self.assertIsNone(_to_iso("2025-05"))
        with self.assertLogs("scrapers.pipeline", level="WARNING"):
            self.assertIsNone(_to_iso("Herbst 2025"))

    def test_lenient_iso_forms_are_rejected(self):
        """date.fromisoformat on 3.11+ accepts these, but the pipeline compares
        dates as plain strings and slices sd[:7] for the month, so anything but
        YYYY-MM-DD corrupts downstream logic."""
        for value in ("20260907", "2026-W37-1", "2026-09-07T10:30:00"):
            with self.subTest(value=value):
                with self.assertLogs("scrapers.pipeline", level="WARNING"):
                    self.assertIsNone(_to_iso(value))

    def test_datetimes_are_narrowed_to_a_plain_date(self):
        import datetime

        self.assertEqual(_to_iso(datetime.datetime(2026, 9, 7, 10, 30)), "2026-09-07")

    def test_non_date_values_are_discarded_not_raised(self):
        with self.assertLogs("scrapers.pipeline", level="WARNING"):
            self.assertIsNone(_to_iso(12345))

    def test_bad_date_does_not_outrank_a_valid_past_course(self):
        """Same chamber/trade/parts, so sort_key actually compares them."""
        records = [
            {
                "chamber_slug": "hwk-x", "trade_slug": "tischler", "parts": [1],
                "course_fee": 999.0, "availability": "unknown",
                "start_date": "2020-99-99",
            },
            {
                "chamber_slug": "hwk-x", "trade_slug": "tischler", "parts": [1],
                "course_fee": 1000.0, "availability": "unknown",
                "start_date": "2026-09-07",
            },
        ]
        picked = build_course_fees(records, "2026-08-07")
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["fee"], 1000.0, "the real upcoming course must win")

    def test_build_course_fees_survives_a_legacy_bad_date(self):
        """Records already committed to data/ predate the _to_iso guard."""
        records = [
            {
                "chamber_slug": "hwk-x",
                "trade_slug": "tischler",
                "parts": [1],
                "course_fee": 1000.0,
                "availability": "unknown",
                "start_date": "2026-13-45",
            },
            {
                "chamber_slug": "hwk-y",
                "trade_slug": "tischler",
                "parts": [1],
                "course_fee": 2000.0,
                "availability": "unknown",
                "start_date": "2026-09-07",
            },
        ]
        self.assertEqual(len(build_course_fees(records, "2026-08-07")), 2)


if __name__ == "__main__":
    unittest.main()
