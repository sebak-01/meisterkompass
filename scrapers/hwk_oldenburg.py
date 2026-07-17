"""Scraper for HWK Oldenburg's BUE universal-kdb course catalogue."""

import logging
import re

from bs4 import BeautifulSoup

from .base import ScrapeResult, normalize_trade
from .hwk_bayern import parse_euro, parse_trade
from .hwk_universal_kdb import KdbCatalogue, UniversalKdbScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-oldenburg.de"
SOURCE_URL = f"{BASE_URL}/weiterbildung/kurse-und-seminare#/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/weiterbildung/meistertitel"
GENERIC_EXAM_FEES = {2: 350.0, 3: 300.0, 4: 300.0}


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
    def parse_exam_fee_table(soup: BeautifulSoup) -> tuple[dict[str, float], dict[int, float]]:
        """Parse the Meisterprüfungsgebühren table on the Meistertitel page."""
        part_i: dict[str, float] = {}
        generic: dict[int, float] = {}

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header = [
                cell.get_text(" ", strip=True).lower()
                for cell in rows[0].find_all(["th", "td"])
            ]
            if not any(re.search(r"teil\s+i\b", label) for label in header):
                continue

            for row in rows[1:]:
                cells = [
                    cell.get_text(" ", strip=True)
                    for cell in row.find_all(["th", "td"])
                ]
                if len(cells) < 5:
                    continue
                trade_name = cells[0].strip()
                if not trade_name or trade_name.lower().startswith("teil"):
                    continue

                fees = [parse_euro(cell) for cell in cells[1:5]]
                if fees[0] is not None:
                    part_i[trade_name] = fees[0]
                if not generic and all(fee is not None for fee in fees[1:]):
                    generic = {2: fees[1], 3: fees[2], 4: fees[3]}

            if part_i:
                break

        return part_i, generic

    def _fetch_exam_fees_from_page(self) -> tuple[dict[str, float], dict[int, float]]:
        response = self.get(EXAM_FEES_PAGE_URL)
        if response is None:
            logger.warning("HWK Oldenburg: could not fetch exam-fee page.")
            return {}, {}
        soup = BeautifulSoup(response.text, "html.parser")
        part_i, generic = self.parse_exam_fee_table(soup)
        if not part_i:
            logger.warning("HWK Oldenburg: could not parse Meister exam fees from page.")
        return part_i, generic

    def published_exam_fee_rows(self) -> list[dict]:
        part_i_fees, generic_fees = self._fetch_exam_fees_from_page()
        if not generic_fees:
            generic_fees = GENERIC_EXAM_FEES

        rows: list[dict] = []
        for trade_name, fee in part_i_fees.items():
            trade = parse_trade(f"Meister {trade_name}", [1]) or trade_name
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": normalize_trade(trade)[0],
                "part": 1,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        for part, fee in generic_fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        return rows

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result
