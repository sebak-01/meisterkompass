"""Scraper for HWK Ostmecklenburg-Vorpommern's ODAV Meister course catalogue."""

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
    parse_availability,
    parse_dates,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-omv.de"
LIST_URL = (
    f"{BASE_URL}/kurse/liste-18,0,courselist.html?search-filter-template=0&search-type=6"
)
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/gebuehren-und-beitraege-18,945,2052.html"
FEES_PDF_URL = f"{BASE_URL}/downloads/gebuehrenverzeichnis-18,419.pdf"
GENERIC_EXAM_FEES = {1: 380.0, 2: 330.0, 3: 190.0, 4: 190.0}

OMV_TRADE_ALIASES = {
    "kfz": "Kfz.-Techniker",
    "elektrotechnik": "Elektrotechniker",
    "metallbau": "Metallbauer",
    "maler-/lackierer": "Maler und Lackierer",
    "maler/lackierer": "Maler und Lackierer",
    "installateur- u. heizungsbau": "Installateur- und Heizungsbauer",
    "land- und baumaschinenmechatroniker": "Land- und Baumaschinenmechatroniker",
    "boots-und schiffbauer": "Boots- und Schiffbauer",
    "boots- und schiffbauer": "Boots- und Schiffbauer",
}

LOCATIONS = {
    "rostock": ("Schwaaner Landstraße 8", "18055", "Rostock"),
    "neubrandenburg": ("Friedrich-Engels-Ring 11", "17033", "Neubrandenburg"),
    "neustrelitz": ("", "17235", "Neustrelitz"),
}


def parse_omv_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        lower = title.lower()
        if "land- und baumaschinenmechatroniker" in lower:
            parts = parse_parts(f"Meister {title}", implicit_trade_parts=True)
        if not parts:
            return [], None

    contexts = (
        title,
        title.replace("Meistervorbereitung", "Meister Meistervorbereitung"),
        f"Meister {title}",
    )
    trade = None
    for context in contexts:
        trade = parse_trade(context, parts)
        if trade:
            break

    if not trade:
        lower = title.lower()
        for source, canonical in OMV_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    if trade:
        return parts, trade
    if set(parts) <= {1, 2}:
        return parts, None
    return [], None


def _format_from_titles(*titles: str) -> str | None:
    for title in titles:
        lower = title.lower()
        if "teilzeit" in lower or "wochenende" in lower:
            return "part_time"
        if "vollzeit" in lower:
            return "full_time"
    return None


def _city_from_card_text(text: str) -> str | None:
    if "|" not in text:
        return None
    city = text.rsplit("|", 1)[-1].strip().split("\n", 1)[0].strip()
    return city or None


class HwkOstmecklenburgVorpommernScraper(BavariaOdavScraper):
    chamber_slug = "hwk-ostmecklenburg-vorpommern"
    chamber_name = "Handwerkskammer Ostmecklenburg-Vorpommern"
    chamber_region = "Mecklenburg-Vorpommern"
    chamber_website = BASE_URL
    source_url = LIST_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/kurse/liste-18,0,courselist.html?search-filter-template=0&search-type=6"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Rostock",
        default_street="Schwaaner Landstraße 8",
        default_zip="18055",
        page_size=100,
        implicit_trade_parts=True,
    )

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        parts, trade_name = parse_omv_title(raw_title)
        if not parts:
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
            parts, trade_name = parse_omv_title(detail_title)
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

    def listing_location(self, card: dict, teaching_mode: str) -> tuple[str, str, str]:
        if teaching_mode == "online":
            return "", "", "Online"
        text = f"{card.get('raw_title', '')} {card.get('card_text', '')}"
        city = _city_from_card_text(text)
        if city:
            for key, location in LOCATIONS.items():
                if key in city.lower():
                    return location
        lower = text.lower()
        for key, location in LOCATIONS.items():
            if key in lower:
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
            (1, r"Teil\s+I\s+praktische\s+Prüfung\s+([\d.]+),(\d{2})"),
            (2, r"Teil\s+II\s+Prüfung\s+der\s+fachtheoretischen\s+Kenntnisse\s+([\d.]+),(\d{2})"),
            (
                3,
                r"Teil\s+III\s+Prüfung\s+der\s+betriebswirtschaftlichen,.*?([\d.]+),(\d{2})",
            ),
            (4, r"Ausbildereignungsprüfung\s+([\d.]+),(\d{2})"),
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

        candidates: list[str] = []
        for link in soup.select("a[href*='.pdf']"):
            href = link.get("href", "")
            lower = href.lower()
            if not lower.endswith(".pdf"):
                continue
            if "gebuehrenverzeichnis" in lower and "aenderung" not in lower and "genehmigung" not in lower:
                candidates.append(urljoin(BASE_URL, href))

        if candidates:
            return candidates[-1]
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK OMV: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK OMV: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK OMV: could not parse Meister exam fees from PDF.")
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
