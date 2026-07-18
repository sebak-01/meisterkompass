import unittest
from pathlib import Path
import tempfile

from scrapers.base import ScrapeResult
from scrapers.pipeline import (
    SCRAPE_GROUPS,
    SCRAPERS,
    ScrapeBatch,
    _scrape_workers,
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


if __name__ == "__main__":
    unittest.main()
