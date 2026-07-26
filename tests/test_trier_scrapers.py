import unittest
from unittest.mock import patch

from scrapers.fees import build_exam_fee_lookup, resolve_exam_fee
from scrapers.hwk_trier import (
    EXAM_FEES_PAGE_URL,
    EXAM_FEES_PDF_FALLBACK,
    HwkTrierScraper,
)


class HwkTrierExamFeeTests(unittest.TestCase):
    def test_published_exam_fee_rows_use_rechtsgrundlagen_source(self):
        scraper = HwkTrierScraper()
        with patch(
            "scrapers.hwk_trier.resolve_pdf_url_from_page",
            return_value=EXAM_FEES_PDF_FALLBACK,
        ), patch(
            "scrapers.hwk_trier.download_pdf_text",
            return_value="",
        ):
            rows = scraper.published_exam_fee_rows()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["source_url"] == EXAM_FEES_PAGE_URL for row in rows))
        self.assertEqual(
            {row["part"]: row["fee"] for row in rows},
            {1: 615.0, 2: 515.0, 3: 180.0, 4: 215.0},
        )

    def test_resolve_exam_fee_uses_tariff_for_part_iii_without_course_fee(self):
        rows = [
            {
                "chamber_slug": "hwk-trier",
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in ((1, 615.0), (2, 515.0), (3, 180.0), (4, 215.0))
        ]
        lookup = build_exam_fee_lookup(rows, [])
        resolved = resolve_exam_fee("hwk-trier", "elektrotechniker", [3], None, lookup)
        self.assertEqual(resolved["fee"], 180.0)
        self.assertTrue(resolved["from_tariff"])


if __name__ == "__main__":
    unittest.main()
