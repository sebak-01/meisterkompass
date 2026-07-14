"""Scraper for HWK Cottbus's ODAV Meister course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from .base import RawCourseOffer, ScrapeResult
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-cottbus.de"
LIST_URL = (
    f"{BASE_URL}/7,0,courselist.html?search-filter-template=0&search-type=6"
)
EXAM_FEES_PAGE_URL = (
    f"{BASE_URL}/artikel/gebuehren-die-rechtliche-basis-fuer-die-erhebung-von-"
    "gebuehren-7,0,7033.html"
)
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenverzeichnis-der-handwerkskammer-cottbus-2025-7,2978.pdf"
)
GENERIC_EXAM_FEES = {1: 510.0, 2: 315.0, 3: 200.0, 4: 255.0}
PART_I_QUALIFIER = "Grundgebühr zzgl. gewerkebezogener Zusatzgebühr"

LOCATIONS = {
    "gallinchen": ("Sorbuser Weg 2", "03051", "Cottbus"),
    "großräschen": ("Am Wiesengrund 1", "01983", "Großräschen"),
    "grossraeschen": ("Am Wiesengrund 1", "01983", "Großräschen"),
    "wildau": ("Hochschulring 1", "15745", "Wildau"),
    "cottbus": ("Sorbuser Weg 2", "03051", "Cottbus"),
}


class HwkCottbusScraper(BavariaOdavScraper):
    chamber_slug = "hwk-cottbus"
    chamber_name = "Handwerkskammer Cottbus"
    chamber_region = "Brandenburg"
    chamber_website = BASE_URL
    source_url = LIST_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/7,0,courselist.html?search-filter-template=0&search-type=6"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Cottbus",
        default_street="Sorbuser Weg 2",
        default_zip="03051",
        page_size=100,
        implicit_trade_parts=True,
    )

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def listing_location(self, card: dict, teaching_mode: str) -> tuple[str, str, str]:
        if teaching_mode == "online":
            return "", "", "Online"
        text = f"{card.get('raw_title', '')} {card.get('card_text', '')}".lower()
        for key, location in LOCATIONS.items():
            if key in text:
                return location
        return (
            self.catalogue.default_street,
            self.catalogue.default_zip,
            self.catalogue.default_city,
        )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"B\.III\.3\.1\s+Prüfungsgebühr\s+Teil\s+I.*?([\d.]+),(\d{2})"),
            (2, r"B\.III\.3\.2\s+Prüfungsgebühr\s+Teil\s+II\s+([\d.]+),(\d{2})"),
            (3, r"B\.III\.3\.3\s+Prüfungsgebühr\s+Teil\s+III\s+([\d.]+),(\d{2})"),
            (4, r"B\.III\.3\.4\s+Prüfungsgebühr\s+Teil\s+IV\s+([\d.]+),(\d{2})"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
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
            logger.warning("HWK Cottbus: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Cottbus: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Cottbus: could not parse Meister exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_pdf() or GENERIC_EXAM_FEES
        rows: list[dict] = []
        for part, fee in fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": PART_I_QUALIFIER if part == 1 else "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        return rows
