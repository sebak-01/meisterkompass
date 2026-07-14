"""Scraper for HWK Potsdam's ODAV Meister course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from .base import RawCourseOffer, ScrapeResult
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-potsdam.de"
LIST_URL = (
    f"{BASE_URL}/9,0,courselist.html?search-filter-template=0&search-type=6"
)
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/gebuehren-9,0,2654.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/anlage-gebuehrenordnung-gueltig-ab-25-01-2025-pdf-9,14460.pdf"
)
GENERIC_EXAM_FEES = {1: 370.0, 2: 370.0, 3: 220.0, 4: 215.0}
EXAM_FEE_QUALIFIER = "zzgl. Auslagen"


def _availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower or "anmeldeschluss bereits erreicht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if any(
        phrase in lower
        for phrase in (
            "ausreichend freie plätze",
            "freie plätze",
            "wenige plätze",
        )
    ):
        return "available"
    return "unknown"


class HwkPotsdamScraper(BavariaOdavScraper):
    chamber_slug = "hwk-potsdam"
    chamber_name = "Handwerkskammer Potsdam"
    chamber_region = "Brandenburg"
    chamber_website = BASE_URL
    source_url = LIST_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/9,0,courselist.html?search-filter-template=0&search-type=6"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Groß Kreutz (Havel)",
        default_street="Am Mühlenberg 15",
        default_zip="14550",
        page_size=100,
        implicit_trade_parts=True,
    )

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        offer.availability = _availability(detail_text)
        return offer

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"Prüfungsteil\s+I\s+([\d.]+),(\d{2})"),
            (2, r"Prüfungsteil\s+II\s+([\d.]+),(\d{2})"),
            (3, r"Prüfungsteil\s+III\s+([\d.]+),(\d{2})"),
            (4, r"Prüfungsteil\s+IV\s+([\d.]+),(\d{2})"),
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
        for link in soup.select("a[href*='gebuehren']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf") and "anlage" in href.lower():
                return urljoin(BASE_URL, href)
        for link in soup.select("a[href*='.pdf']"):
            href = link.get("href", "")
            if "gebuehren" in href.lower():
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Potsdam: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Potsdam: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Potsdam: could not parse Meister exam fees from PDF.")
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
                "qualifier": EXAM_FEE_QUALIFIER,
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        ]
