"""Scraper for HWK Ostfriesland's BUE universal-kdb course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ScrapeResult
from .hwk_universal_kdb import KdbCatalogue, UniversalKdbScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-aurich.de"
SOURCE_URL = f"{BASE_URL}/weiterbildung/kurse-and-seminare-finden#/"
EXAM_FEES_PAGE_URL = (
    f"{BASE_URL}/service-center/uber-uns/amtliche-bekanntmachungen-rechtsgrundlagen"
)
FEES_PDF_URL = (
    f"{BASE_URL}/_Resources/Persistent/8/6/3/5/8635ceb4da4c195ddb133ec1ed48829e8e3f0682/"
    "Geb%C3%BChrenordnung%20mit%20Geb%C3%BChrentarif%20vom%2022.12.2025.pdf"
)
GENERIC_EXAM_FEES = {1: 390.0, 2: 360.0, 3: 250.0, 4: 200.0}


class HwkOstfrieslandScraper(UniversalKdbScraper):
    chamber_slug = "hwk-ostfriesland"
    chamber_name = "Handwerkskammer Ostfriesland"
    chamber_region = "Niedersachsen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    kdb_mandant = "aur"
    kdb_catalogue = KdbCatalogue(
        mandant="aur",
        source_url=SOURCE_URL,
        default_street="Straße des Handwerks 2",
        default_zip="26603",
        default_city="Aurich",
    )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"4\.1\.1\s+Teil\s+I\s+([\d.]+),(\d{2})"),
            (2, r"4\.1\.2\s+Teil\s+II\s+([\d.]+),(\d{2})"),
            (3, r"4\.1\.3\s+Teil\s+III\s+([\d.]+),(\d{2})"),
            (4, r"4\.1\.4\s+Teil\s+IV\s+([\d.]+),(\d{2})"),
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
        for link in soup.select("a[href*='Geb%C3%BChrenordnung'], a[href*='Gebuehrenordnung']"):
            href = link.get("href", "")
            if "gebuehrentarif" in href.lower() or "gebührentarif" in href.lower():
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Ostfriesland: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Ostfriesland: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Ostfriesland: could not parse Meister exam fees from PDF.")
        return fees

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

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result
