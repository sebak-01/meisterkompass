"""Scraper for HWK Cottbus's ODAV Meister course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import Tag

from .base import RawCourseOffer, ScrapeResult
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    canonical_detail_url,
    parse_dates,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    parse_availability,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-cottbus.de"
LIST_URL = (
    f"{BASE_URL}/7,0,courselist.html?search-filter-template=0&search-type=6"
)
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/rechtsgrundlagen-7,719,154.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenverzeichnis-der-handwerkskammer-cottbus-2025-7,2978.pdf"
)
GENERIC_EXAM_FEES = {1: 510.0, 2: 315.0, 3: 200.0, 4: 255.0}

COTTBUS_TRADE_ALIASES = {
    "installateur und heizungsbauer": "Installateur- und Heizungsbauer",
    "kosmetiker": "Kosmetiker",
    "straßenbauer": "Straßenbauer",
    "strassenbauer": "Straßenbauer",
    "gebäudereiniger": "Gebäudereiniger",
    "gebaeudereiniger": "Gebäudereiniger",
    "orthopädietechniker": "Orthopädietechniker",
}

LOCATIONS = {
    "gallinchen": ("Sorbuser Weg 2", "03051", "Cottbus"),
    "großräschen": ("Am Wiesengrund 1", "01983", "Großräschen"),
    "grossraeschen": ("Am Wiesengrund 1", "01983", "Großräschen"),
    "wildau": ("Hochschulring 1", "15745", "Wildau"),
    "cottbus": ("Sorbuser Weg 2", "03051", "Cottbus"),
}


def parse_cottbus_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None

    contexts = (
        title,
        title.replace("Meistervorbereitungslehrgang", "Meister Meistervorbereitungslehrgang"),
        f"Meister {title}",
    )
    trade = None
    for context in contexts:
        trade = parse_trade(context, parts)
        if trade:
            break

    if not trade:
        lower = title.lower()
        for source, canonical in COTTBUS_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _format_from_titles(*titles: str) -> str | None:
    for title in titles:
        lower = title.lower()
        if "teilzeit" in lower or "kombi-lehrgang" in lower:
            return "part_time"
        if "vollzeit" in lower:
            return "full_time"
    return None


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

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        parts, trade_name = parse_cottbus_title(raw_title)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping non-Meister or unknown title %r", raw_title)
            return None

        row = link.find_parent("div", class_="row")
        heading = link.find_parent("h3")
        text = row.get_text("\n", strip=True) if row else raw_title
        heading_text = heading.get_text(" ", strip=True) if heading else text
        start_date, end_date = parse_dates(heading_text)
        format_key = _format_from_titles(raw_title, heading_text) or parse_format_and_mode(
            f"{heading_text} {raw_title}"
        )[0]
        teaching_mode = parse_format_and_mode(f"{heading_text} {raw_title}")[1]
        duration = DURATION_RE.search(text)
        return {
            "raw_title": raw_title,
            "parts": parts,
            "trade_name": trade_name,
            "start_date": start_date,
            "end_date": end_date,
            "format_key": format_key,
            "teaching_mode": teaching_mode,
            "duration_hours": int(duration.group(1).replace(".", "")) if duration else None,
            "course_fee": parse_euro(text),
            "availability": parse_availability(text),
            "detail_url": detail_url or canonical_detail_url(
                self.catalogue.base_url, link.get("href", "")
            ),
            "card_text": text[:1000],
        }

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        format_key = _format_from_titles(
            offer.scraped_raw.get("title", ""),
            offer.scraped_raw.get("card_text", ""),
        )
        if format_key:
            offer.format_key = format_key
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
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        return rows
