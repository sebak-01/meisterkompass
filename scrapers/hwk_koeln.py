"""Scraper for HWK zu Köln's ODAV Meister course catalogues."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import Tag

from .base import RawCourseOffer, ScrapeResult, normalize_trade
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    canonical_detail_url,
    course_id_from_url,
    parse_availability,
    parse_dates,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-koeln.de"
SOURCE_URL = f"{BASE_URL}/artikel/meisterpruefung-32,0,99.html"
EXAM_FEES_PAGE_URL = SOURCE_URL
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenverzeichnis-der-handwerkskammer-zu-koeln-32,3307.pdf"
)
GENERIC_EXAM_FEES = {1: 450.0, 2: 380.0, 3: 230.0, 4: 190.0}

KOL_TRADE_ALIASES = {
    "friseur-handwerk": "Friseur",
    "zahntechniker-handwerk": "Zahntechniker",
    "karosserie- und fahrzeugbauer-handwerk": "Karosserie- und Fahrzeugbauer",
    "konditoren-handwerk": "Konditor",
    "straßenbauer-handwerk": "Straßenbauer",
    "strassenbauer-handwerk": "Straßenbauer",
    "maler und lackierer-handwerk": "Maler und Lackierer",
    "elektrotechniker-handwerk": "Elektrotechniker",
    "installateur- und heizungsbauer-handwerk": "Installateur- und Heizungsbauer",
    "metallbauer-handwerk": "Metallbauer",
    "tischler-handwerk": "Tischler",
    "maurer und betonbauer-handwerk": "Maurer und Betonbauer",
    "maurer- und betonbauer-handwerk": "Maurer und Betonbauer",
    "kfz-handwerk": "Kfz.-Techniker",
    "kraftfahrzeugtechniker-handwerk": "Kfz.-Techniker",
}


def parse_koeln_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None

    contexts = (
        title,
        title.replace("Vorbereitung auf die Meisterprüfung im", "Meister Meistervorbereitung im"),
        title.replace("Vorbereitung auf die Meisterprüfung", "Meister Meistervorbereitung"),
        f"Meister {title}",
    )
    trade = None
    for context in contexts:
        trade = parse_trade(context, parts)
        if trade:
            break

    if not trade:
        lower = title.lower()
        for source, canonical in KOL_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_listing(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in (
        "infoveranstaltung", "informationsveranstaltung", "infoabend",
        "auffrischungskurs", "aufstiegs-bafög", "ausbildereignung",
        "kombikurs geprüfte", "geprüfte/r fachfrau", "gepr. fachmann",
        "sachkundenachweis", "knx -", "netzanschluss",
    )):
        return False
    return (
        "vorbereitung auf die meisterprüfung" in lower
        or "meistervorbereitung" in lower
        or (set(parse_parts(title, implicit_trade_parts=True)) <= {3, 4} and "teil" in lower)
    )


class HwkKoelnScraper(BavariaOdavScraper):
    chamber_slug = "hwk-koeln"
    chamber_name = "Handwerkskammer zu Köln"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/32,0,courselist.html?search-filter-template=0"
            "&search-searchterm=Meistervorbereitung&limit={limit}&offset={offset}"
        ),
        default_city="Köln",
        default_street="Heumarkt 12",
        default_zip="50667",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[str, dict] = {}
        offset = 0
        while True:
            url = (
                f"{BASE_URL}/32,0,courselist.html?search-filter-template=0"
                f"&search-searchterm=Meistervorbereitung&limit={self.catalogue.page_size}"
                f"&offset={offset}"
            )
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("HWK Köln listing failed at offset %d.", offset)
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
                logger.warning("Could not parse Köln course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Köln: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        if not _is_meister_listing(raw_title):
            logger.debug("Skipping non-Meister Köln title %r", raw_title)
            return None

        parts, trade_name = parse_koeln_title(raw_title)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping unknown Köln title %r", raw_title)
            return None

        row = link.find_parent("div", class_="row")
        heading = link.find_parent("h3")
        text = row.get_text("\n", strip=True) if row else raw_title
        heading_text = heading.get_text(" ", strip=True) if heading else text
        start_date, end_date = parse_dates(heading_text)
        format_key, teaching_mode = parse_format_and_mode(f"{heading_text} {raw_title}")
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

    def _enrich(self, card: dict) -> RawCourseOffer | list[RawCourseOffer] | None:
        soup = self.parse_html(card["detail_url"]) if self.catalogue.details_required else None
        if soup is not None:
            h1 = soup.select_one("h1")
            detail_title = h1.get_text(" ", strip=True) if h1 else card["raw_title"]
            parts, trade_name = parse_koeln_title(detail_title)
            if parts:
                card = {**card, "parts": parts}
            if trade_name:
                card = {**card, "trade_name": trade_name}
        return super()._enrich(card)

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
        for link in soup.select("a[href*='gebuehrenverzeichnis'], a[href*='gebuehren']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Köln: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Köln: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Köln: could not parse Meister exam fees from PDF.")
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
