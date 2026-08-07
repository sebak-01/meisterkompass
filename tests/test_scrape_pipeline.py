import unittest
import unittest.mock
from pathlib import Path
import tempfile

from scrapers.base import ScrapeResult
from scrapers.pipeline import (
    SCRAPE_GROUPS,
    SCRAPERS,
    ScrapeBatch,
    _is_online_location,
    _scrape_workers,
    _merge_exam_fees_nested,
    _to_iso,
    apply_coordinates,
    build_course_fees,
    collapsed_chambers,
    merge_courses,
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


TODAY = "2026-08-07"


def _rec(slug, i, start_date="2026-12-01"):
    return {
        "chamber_slug": slug,
        "trade_slug": "tischler",
        "trade_name": "Tischler",
        "parts": [1],
        "format": "full_time",
        "start_date": start_date,
        "end_date": None,
        "source_url": f"https://example.test/{slug}/{i}",
        "city": "Musterstadt",
    }


class CollapseGuardTests(unittest.TestCase):
    """BaseScraper.get() returns None per failed page instead of raising, so a
    chamber whose detail pages start failing reports fewer offers rather than an
    error. Committing that silently deletes the chamber's catalogue."""

    def test_collapsed_scrape_retains_previous_records(self):
        previous = [_rec("hwk-x", i) for i in range(200)]
        fresh = {"hwk-x": [_rec("hwk-x", i) for i in range(3)]}

        self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {"hwk-x": (3, 200)})
        with self.assertLogs("scrapers.pipeline", level="ERROR"):
            merged = merge_courses(previous, fresh, TODAY)
        self.assertEqual(len(merged), 200)

    def test_plausible_shrink_is_accepted(self):
        previous = [_rec("hwk-x", i) for i in range(200)]
        fresh = {"hwk-x": [_rec("hwk-x", i) for i in range(120)]}

        self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {})
        self.assertEqual(len(merge_courses(previous, fresh, TODAY)), 120)

    def test_small_chambers_are_below_the_floor(self):
        """A chamber with a handful of courses swings wildly by nature; guarding
        it would pin its catalogue permanently."""
        previous = [_rec("hwk-small", i) for i in range(4)]
        fresh = {"hwk-small": [_rec("hwk-small", 0)]}

        self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {})
        self.assertEqual(len(merge_courses(previous, fresh, TODAY)), 1)

    def test_courses_that_merely_started_are_not_counted_as_loss(self):
        """Only previously-upcoming courses can reappear in a fresh scrape, so a
        catalogue that rolled into the past must not look like a collapse."""
        previous = [_rec("hwk-x", i, start_date="2026-01-01") for i in range(200)]
        previous += [_rec("hwk-x", 900 + i) for i in range(10)]
        fresh = {"hwk-x": [_rec("hwk-x", 900 + i) for i in range(10)]}

        self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {})

    def test_collapse_is_per_chamber(self):
        previous = [_rec("hwk-x", i) for i in range(200)]
        previous += [_rec("hwk-y", i) for i in range(50)]
        fresh = {
            "hwk-x": [_rec("hwk-x", i) for i in range(2)],
            "hwk-y": [_rec("hwk-y", i) for i in range(40)],
        }

        with self.assertLogs("scrapers.pipeline", level="ERROR"):
            merged = merge_courses(previous, fresh, TODAY)
        by_chamber = {}
        for rec in merged:
            by_chamber[rec["chamber_slug"]] = by_chamber.get(rec["chamber_slug"], 0) + 1
        self.assertEqual(by_chamber["hwk-x"], 200, "collapsed chamber retained")
        self.assertEqual(by_chamber["hwk-y"], 40, "healthy chamber still updates")

    def test_empty_scrape_still_retains_without_being_flagged(self):
        previous = [_rec("hwk-x", i) for i in range(200)]
        fresh = {"hwk-x": []}

        self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {})
        self.assertEqual(len(merge_courses(previous, fresh, TODAY)), 200)

    def test_retained_chambers_keep_their_exam_fees(self):
        """merge_courses keeps a collapsed or empty chamber's courses, so those
        courses' fees must survive too — treating the chamber as "scraped" would
        replace its exam_fees.json entry with the nothing the scrape produced."""
        previous_fees = {
            "hwk-collapsed": {"tischler": {"1": 500.0}},
            "hwk-empty": {"maler": {"1": 400.0}},
            "hwk-healthy": {"maurer": {"1": 300.0}},
        }
        # Only the healthy chamber actually produced fresh rows.
        current_fees = {"hwk-healthy": {"maurer": {"1": 300.0}}}

        merged = _merge_exam_fees_nested(previous_fees, current_fees, {"hwk-healthy"})

        self.assertEqual(merged["hwk-collapsed"], {"tischler": {"1": 500.0}})
        self.assertEqual(merged["hwk-empty"], {"maler": {"1": 400.0}})
        self.assertEqual(merged["hwk-healthy"], {"maurer": {"1": 300.0}})

    def test_ratio_zero_disables_the_guard(self):
        """Escape hatch for a real collapse (a chamber genuinely retiring its
        programme) so the dataset can never be permanently pinned."""
        previous = [_rec("hwk-x", i) for i in range(200)]
        fresh = {"hwk-x": [_rec("hwk-x", 0)]}

        with unittest.mock.patch("scrapers.pipeline.SCRAPE_COLLAPSE_RATIO", 0.0):
            self.assertEqual(collapsed_chambers(previous, fresh, TODAY), {})
            self.assertEqual(len(merge_courses(previous, fresh, TODAY)), 1)


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
