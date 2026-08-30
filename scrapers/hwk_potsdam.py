"""Scraper for HWK Potsdam's ODAV Meister course catalogue."""

import logging
import re
from urllib.parse import urljoin

from .base import RawCourseOffer
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper
from .exam_fee_tariff import download_pdf_text, part_fee_rows

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-potsdam.de"
LIST_URL = (
    f"{BASE_URL}/9,0,courselist.html?search-filter-template=0&search-type=6"
)
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/gebuehren-9,783,2654.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/anlage-gebuehrenordnung-gueltig-ab-13-september-2025-9,14516.pdf"
)
GENERIC_EXAM_FEES = {1: 370.0, 2: 370.0, 3: 220.0, 4: 215.0}
EXAM_FEE_QUALIFIER = "zzgl. Auslagen"

POTSDAM_CITY_ALIASES = {
    "groß kreutz (havel) ortsteil götz": "Groß Kreutz (Havel)",
    "gross kreutz (havel) ortsteil goetz": "Groß Kreutz (Havel)",
    "nuthetal ortsteil bergholz-rehbrücke": "Nuthetal",
    "nuthetal ortsteil bergholz-rehbruecke": "Nuthetal",
}


def _normalize_city(city: str) -> str:
    cleaned = re.sub(r"\s+Ortsteil\s+.+$", "", city, flags=re.IGNORECASE).strip(" ,")
    return POTSDAM_CITY_ALIASES.get(cleaned.lower(), cleaned or city)


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
    detail_pages_state_exam_fees = False


    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        offer.availability = _availability(detail_text)
        offer.city = _normalize_city(offer.city)
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

        candidates: list[str] = []
        for link in soup.select("a[href*='.pdf']"):
            href = link.get("href", "")
            lower = href.lower()
            if not lower.endswith(".pdf"):
                continue
            if "anlage-gebuehrenordnung-gueltig-ab" in lower:
                candidates.append(urljoin(BASE_URL, href))
                continue
            if "gebuehrenverzeichnis" in lower and "aenderung" not in lower:
                candidates.append(urljoin(BASE_URL, href))

        if candidates:
            return candidates[-1]
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        text = download_pdf_text(self, self._resolve_exam_fees_pdf_url(), label="HWK Potsdam")
        if not text:
            return {}
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Potsdam: could not parse Meister exam fees from PDF.")
        return fees


    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_pdf() or GENERIC_EXAM_FEES
        return part_fee_rows(
            self.chamber_slug,
            fees,
            source_url=EXAM_FEES_PAGE_URL,
            qualifier=EXAM_FEE_QUALIFIER,
        )
