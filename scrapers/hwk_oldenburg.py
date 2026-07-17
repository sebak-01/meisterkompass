"""Scraper for HWK Oldenburg's BUE universal-kdb course catalogue."""

import logging
import re

from bs4 import BeautifulSoup

from .base import ScrapeResult
from .hwk_universal_kdb import KdbCatalogue, UniversalKdbScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-oldenburg.de"
SOURCE_URL = f"{BASE_URL}/weiterbildung/kurse-und-seminare#/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/weiterbildung/meistertitel"
GENERIC_EXAM_FEES = {1: 450.0, 2: 420.0, 3: 280.0, 4: 260.0}


class HwkOldenburgScraper(UniversalKdbScraper):
    chamber_slug = "hwk-oldenburg"
    chamber_name = "Handwerkskammer Oldenburg"
    chamber_region = "Niedersachsen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    kdb_mandant = "ol"
    kdb_catalogue = KdbCatalogue(
        mandant="ol",
        source_url=SOURCE_URL,
        default_street="Stau 3",
        default_zip="26122",
        default_city="Oldenburg",
    )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"Teil\s+I\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (2, r"Teil\s+II\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (3, r"Teil\s+III\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (4, r"Teil\s+IV\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _fetch_exam_fees_from_page(self) -> dict[int, float]:
        response = self.get(EXAM_FEES_PAGE_URL)
        if response is None:
            logger.warning("HWK Oldenburg: could not fetch exam-fee page.")
            return {}
        text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Oldenburg: could not parse Meister exam fees from page.")
        return fees

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_page() or GENERIC_EXAM_FEES
        return [
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        ]

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result
