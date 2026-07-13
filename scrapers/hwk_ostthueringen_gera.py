"""Scraper for HWK Ostthüringen's ODAV Meister course catalogues."""

import logging

from .base import ScrapeResult
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    course_id_from_url,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-gera.de"
INFO_URL = f"{BASE_URL}/artikel/wege-zum-meistertitel-5,19,211.html"
TOPICS = (49, 46, 50, 71)  # I+II, III, III+IV, IV


class HwkOstthueringenGeraScraper(BavariaOdavScraper):
    chamber_slug = "hwk-ostthueringen-gera"
    chamber_name = "Handwerkskammer für Ostthüringen"
    chamber_region = "Thüringen"
    chamber_website = BASE_URL
    source_url = INFO_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/5,0,courselist.html?search-filter-template=0"
            "&search-topic=49&limit={limit}&offset={offset}"
        ),
        default_city="Gera",
        page_size=100,
        implicit_trade_parts=True,
    )
    EXAM_FEES = {1: 335.0, 2: 220.0, 3: 190.0, 4: 190.0}

    def fetch_raw_courses(self):
        unique: dict[str, dict] = {}
        for topic in TOPICS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/5,0,courselist.html?search-filter-template=0"
                    f"&search-topic={topic}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK Ostthüringen topic %d failed at offset %d.", topic, offset)
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    key = course_id_from_url(card["detail_url"]) or card["detail_url"]
                    unique[key] = card
                offset += self.catalogue.page_size
                if offset >= total:
                    break

        offers = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Gera course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])
        logger.info("HWK Ostthüringen: parsed %d unique course offers.", len(offers))
        return offers

    def postprocess_offer(self, offer):
        # The detail's "Kurs" amount is a course fee. Exam fees are the
        # chamber-wide values published on INFO_URL and injected by collect().
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "ab" if part == 1 else "",
                "source_url": INFO_URL,
            }
            for part, fee in self.EXAM_FEES.items()
        )
        return result
