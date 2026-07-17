"""Scraper for HWK zu Leipzig's ODAV Meister course catalogues."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from .base import RawCourseOffer, ScrapeResult
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper, course_id_from_url

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-leipzig.de"
INFO_URL = (
    f"{BASE_URL}/artikel/kurse-und-seminare-der-handwerkskammer-zu-leipzig-3,952,635.html"
)
EXAM_FEES_PAGE_URL = (
    f"{BASE_URL}/artikel/gebuehrenordnung-die-rechtliche-basis-fuer-die-erhebung-von-"
    "gebuehren-3,0,99.html"
)
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenverzeichnis-der-handwerkskammer-zu-leipzig-"
    "stand-dezember-2025-3,3307.pdf"
)
TOPICS = (41, 42, 43, 45, 46, 47, 48, 49, 60)
GENERIC_EXAM_FEES = {1: 450.0, 2: 380.0, 3: 230.0, 4: 190.0}


class HwkLeipzigScraper(BavariaOdavScraper):
    chamber_slug = "hwk-leipzig"
    chamber_name = "Handwerkskammer zu Leipzig"
    chamber_region = "Sachsen"
    chamber_website = BASE_URL
    source_url = INFO_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/3,0,courselist.html?search-filter-template=0"
            "&search-topic={topic}&limit={limit}&offset={offset}"
        ),
        default_city="Leipzig",
        default_street="Dresdner Straße 11/13",
        default_zip="04103",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[str, dict] = {}
        for topic in TOPICS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/3,0,courselist.html?search-filter-template=0"
                    f"&search-topic={topic}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK Leipzig topic %d failed at offset %d.", topic, offset)
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    key = course_id_from_url(card["detail_url"]) or card["detail_url"]
                    unique[key] = card
                offset += self.catalogue.page_size
                if offset >= total:
                    break

        offers: list[RawCourseOffer] = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Leipzig course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Leipzig: parsed %d unique course offers.", len(offers))
        return offers

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"a\)\s*Meisterprüfung\s+Teil\s+I\s+([\d.]+),(\d{2})\s*Euro"),
            (2, r"b\)\s*Meisterprüfung\s+Teil\s+II\s+([\d.]+),(\d{2})\s*Euro"),
            (3, r"c\)\s*Meisterprüfung\s+Teil\s+III\s+([\d.]+),(\d{2})\s*Euro"),
            (4, r"d\)\s*Meisterprüfung\s+Teil\s+IV\s+([\d.]+),(\d{2})\s*Euro"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrenverzeichnis']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Leipzig: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Leipzig: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Leipzig: could not parse Meister exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_pdf() or GENERIC_EXAM_FEES
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
