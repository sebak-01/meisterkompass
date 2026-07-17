"""Scraper for HWK Hildesheim-Südniedersachsen's ODAV Meister course catalogue."""

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
    parse_availability,
    parse_dates,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-hildesheim.de"
SOURCE_URL = (
    f"{BASE_URL}/artikel/ihr-weg-zum-meistertitel-alles-was-sie-wissen-muessen-24,862,1617.html"
)
LIST_URL = f"{BASE_URL}/24,0,courselist.html?search-filter-template=0&search-type=6"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/oeffentliche-bekanntmachungen-24,657,1283.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenordnung-und-gebuehrentarife-der-handwerkskammer-"
    "hildesheim-suedniedersachsen-vom-09-12-2025-24,2741.pdf"
)
GENERIC_EXAM_FEES = {3: 330.0, 4: 349.0}

HID_TRADE_ALIASES = {
    "maurer und betonbauer": "Maurer und Betonbauer",
    "maler und lackierer": "Maler und Lackierer",
    "metallbauer": "Metallbauer",
    "feinwerkmechaniker": "Feinwerkmechaniker",
    "kraftfahrzeugtechniker": "Kfz.-Techniker",
    "installateur und heizungsbauer": "Installateur- und Heizungsbauer",
    "elektrotechniker": "Elektrotechniker",
    "tischler": "Tischler",
}


def parse_hildesheim_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"^Kurs:\s*", "", title, flags=re.IGNORECASE).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        return [], None

    contexts = (
        cleaned,
        cleaned.replace("Meistervorbereitung", "Meister Meistervorbereitung"),
        f"Meister {cleaned}",
    )
    trade = None
    for context in contexts:
        trade = parse_trade(context, parts)
        if trade:
            break

    if not trade:
        lower = cleaned.lower()
        for source, canonical in HID_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _format_from_titles(*titles: str) -> str | None:
    for title in titles:
        lower = title.lower()
        if "teilzeit" in lower or "hybrid" in lower:
            return "part_time"
        if "vollzeit" in lower:
            return "full_time"
    return None


class HwkHildesheimSuedniedersachsenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-hildesheim-suedniedersachsen"
    chamber_name = "Handwerkskammer Hildesheim-Südniedersachsen"
    chamber_region = "Niedersachsen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/24,0,courselist.html?search-filter-template=0&search-type=6"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Hildesheim",
        default_street="Berliner Straße 27",
        default_zip="31137",
        page_size=100,
        implicit_trade_parts=True,
    )

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        parts, trade_name = parse_hildesheim_title(raw_title)
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

    def _enrich(self, card: dict) -> RawCourseOffer | list[RawCourseOffer] | None:
        soup = self.parse_html(card["detail_url"]) if self.catalogue.details_required else None
        if soup is not None:
            h1 = soup.select_one("h1")
            detail_title = h1.get_text(" ", strip=True) if h1 else card["raw_title"]
            parts, trade_name = parse_hildesheim_title(detail_title)
            if parts:
                card = {**card, "parts": parts}
            if trade_name:
                card = {**card, "trade_name": trade_name}
        return super()._enrich(card)

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

    @staticmethod
    def parse_trade_exam_fees(text: str) -> dict[str, dict[int, float]]:
        fees: dict[str, dict[int, float]] = {}
        for match in re.finditer(
            r"im\s+([A-Za-zÄÖÜäöüß\- ]+?-Handwerk)\s+Teil\s+I\s+Teil\s+II\s+"
            r"([\d.]+),(\d{2})\s*€\s+([\d.]+),(\d{2})\s*€",
            text,
            re.IGNORECASE,
        ):
            trade_label = match.group(1).strip()
            lower = trade_label.lower()
            trade = None
            for source, canonical in HID_TRADE_ALIASES.items():
                if source in lower:
                    trade = canonical
                    break
            if not trade:
                trade = parse_trade(f"Meister {trade_label}", [1, 2])
            if not trade:
                continue
            fees[trade] = {
                1: float(match.group(2).replace(".", "") + "." + match.group(3)),
                2: float(match.group(4).replace(".", "") + "." + match.group(5)),
            }
        return fees

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        block_match = re.search(
            r"3\.1 Abnahme der Meisterprüfung(.*?)(?:3\.1\.1|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if block_match:
            amounts = re.findall(r"([\d.]+),(\d{2})\s*€", block_match.group(1))
            if len(amounts) >= 2:
                return {
                    3: float(amounts[0][0].replace(".", "") + "." + amounts[0][1]),
                    4: float(amounts[1][0].replace(".", "") + "." + amounts[1][1]),
                }

        for part, label in ((3, "a) Teil III"), (4, "b) Teil IV")):
            match = re.search(
                rf"{re.escape(label)}\s+([\d.]+),(\d{{2}})\s*€",
                text,
                re.IGNORECASE,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        candidates: list[tuple[str, str]] = []
        for link in soup.select("a[href*='.pdf']"):
            href = link.get("href", "")
            label = link.get_text(" ", strip=True)
            href_lower = href.lower()
            if (
                "gebuehrenordnung-und-gebuehrentarife" in href_lower
                or label.lower() == "gebührenordnung und gebührentarife"
            ):
                candidates.append((label, urljoin(BASE_URL, href)))
        for label, pdf_url in candidates:
            if label.lower() == "gebührenordnung und gebührentarife":
                return pdf_url
        if candidates:
            return candidates[0][1]
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Hildesheim: pypdf not installed — using fallback exam fees.")
            return {}, {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Hildesheim: could not fetch exam-fee PDF.")
            return {}, {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        trade_fees = self.parse_trade_exam_fees(text)
        generic_fees = self.parse_generic_exam_fees(text) or GENERIC_EXAM_FEES
        return trade_fees, generic_fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        trade_fees, generic_fees = self._fetch_exam_fees_from_pdf()
        rows: list[dict] = []
        for trade_name, parts in trade_fees.items():
            trade_slug = normalize_trade(trade_name)[0]
            for part, fee in parts.items():
                rows.append({
                    "chamber_slug": self.chamber_slug,
                    "trade_slug": trade_slug,
                    "part": part,
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
