"""Scraper for HWK Lübeck's BUE universal-kdb course catalogue."""

import logging
import re

from bs4 import BeautifulSoup

from .base import ScrapeResult
from .hwk_universal_kdb import KdbCatalogue, UniversalKdbScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-luebeck.de"
SOURCE_URL = f"{BASE_URL}/weiterbildung/fort-und-weiterbildungskurse#/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/weiterbildung/der-weg-zum-meister/pruefung-gebuehren"
GENERIC_EXAM_FEES = {1: 585.0, 2: 585.0, 3: 380.0, 4: 380.0}


class HwkLuebeckScraper(UniversalKdbScraper):
    chamber_slug = "hwk-luebeck"
    chamber_name = "Handwerkskammer Lübeck"
    chamber_region = "Schleswig-Holstein"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    kdb_mandant = "hl"
    kdb_catalogue = KdbCatalogue(
        mandant="hl",
        source_url=SOURCE_URL,
        default_street="Willy-Brandt-Allee 13-15",
        default_zip="23552",
        default_city="Lübeck",
    )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"Teil\s+I\s*:\s*([\d.]+),(\d{2})\s*€"),
            (2, r"Teil\s+II\s*:\s*([\d.]+),(\d{2})\s*€"),
            (3, r"Teil\s+III\s*:\s*([\d.]+),(\d{2})\s*€"),
            (4, r"Teil\s+IV\s*:\s*([\d.]+),(\d{2})\s*€"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _fetch_exam_fees_from_page(self) -> dict[int, float]:
        response = self.get(EXAM_FEES_PAGE_URL)
        if response is None:
            logger.warning("HWK Lübeck: could not fetch exam-fee page.")
            return {}
        text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Lübeck: could not parse Meister exam fees from page.")
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
