"""Scraper for HWK Flensburg's BUE universal-kdb course catalogue."""

import logging
import re

from bs4 import BeautifulSoup

from .base import ScrapeResult
from .hwk_universal_kdb import KdbCatalogue, UniversalKdbScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-flensburg.de"
SOURCE_URL = f"{BASE_URL}/weiterbildung/kurse-seminare#/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/weiterbildung/weiterbildung/der-weg-zum-meister"
GENERIC_EXAM_FEES = {1: 480.0, 2: 480.0, 3: 290.0, 4: 290.0}


class HwkFlensburgScraper(UniversalKdbScraper):
    chamber_slug = "hwk-flensburg"
    chamber_name = "Handwerkskammer Flensburg"
    chamber_region = "Schleswig-Holstein"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    kdb_mandant = "fl"
    kdb_catalogue = KdbCatalogue(
        mandant="fl",
        source_url=SOURCE_URL,
        default_street="Süderfischerstraße 14",
        default_zip="24937",
        default_city="Flensburg",
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
            logger.warning("HWK Flensburg: could not fetch exam-fee page.")
            return {}
        text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Flensburg: could not parse Meister exam fees from page.")
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
