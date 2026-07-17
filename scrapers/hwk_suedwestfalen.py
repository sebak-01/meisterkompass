"""Scraper for BBZ Arnsberg Meister courses (HWK Südwestfalen)."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BBZ_BASE = "https://www.bbz-arnsberg.de"
CHAMBER_URL = "https://www.hwk-swf.de"
LISTING_URL = f"{BBZ_BASE}/kurse"
MEISTER_HUB_URL = f"{BBZ_BASE}/meisterkurse"
EXAM_FEES_PAGE_URL = f"{CHAMBER_URL}/artikel/rechtsgrundlagen-38,0,100.html"
FEES_PDF_URL = f"{CHAMBER_URL}/downloads/gebuehrenordnung-handwerkskammer-suedwestfalen-38,4332.pdf"
GENERIC_EXAM_FEES = {2: 380.0, 3: 290.0, 4: 220.0}

PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*€")
DURATION_RE = re.compile(r"([\d.]+)\s+Unterrichtsstunden", re.IGNORECASE)
DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4})"
)

DEFAULT_LOCATION = {
    "street": "Im Hülsenfeld 42",
    "zip_code": "59755",
    "city": "Arnsberg",
}

SWF_TRADE_ALIASES = {
    "elektrotechnik": "Elektrotechniker",
    "kfz": "Kfz.-Techniker",
    "kraftfahrzeugtechniker": "Kfz.-Techniker",
    "installateur": "Installateur- und Heizungsbauer",
    "heizungsbauer": "Installateur- und Heizungsbauer",
    "maler": "Maler und Lackierer",
    "lackierer": "Maler und Lackierer",
    "fahrzeuglackierer": "Fahrzeuglackierer",
    "maurer": "Maurer und Betonbauer",
    "betonbauer": "Maurer und Betonbauer",
    "metallbauer": "Metallbauer",
    "feinwerkmechaniker": "Feinwerkmechaniker",
    "tischler": "Tischler",
    "zimmerer": "Zimmerer",
    "stuckateur": "Stuckateur",
    "fliesenleger": "Fliesen-, Platten- und Mosaikleger",
    "friseur": "Friseur",
}


def parse_suedwestfalen_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"\*+", "", title).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        if "teil iii" in cleaned.lower():
            parts = [3]
        elif "teil iv" in cleaned.lower() or "aevo" in cleaned.lower():
            parts = [4]

    if not parts:
        return [], None

    trade = parse_trade(cleaned, parts)
    if not trade:
        lower = cleaned.lower()
        for source, canonical in SWF_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_course(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in ("industriemeister", "infoabend", "infoveranstaltung")):
        return False
    return "meisterkurs" in lower or "meisterschule" in lower or "aevo" in lower or "betriebsführung" in lower


class HwkSuedwestfalenScraper(BaseScraper):
    chamber_slug = "hwk-suedwestfalen"
    chamber_name = "Handwerkskammer Südwestfalen"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = CHAMBER_URL
    source_url = MEISTER_HUB_URL
    request_delay = 0.3

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        cards = self._discover_course_cards()
        offers: list[RawCourseOffer] = []
        for card in cards:
            try:
                parsed = self._parse_card(card)
            except Exception as exc:
                logger.warning("Could not parse Südwestfalen card %s: %s", card.get("url"), exc)
                continue
            if parsed:
                offers.extend(parsed)
        logger.info("HWK Südwestfalen: parsed %d offers from %d cards.", len(offers), len(cards))
        return offers

    def _discover_course_cards(self) -> list[dict]:
        cards: dict[str, dict] = {}
        for url in (LISTING_URL, MEISTER_HUB_URL):
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("Could not fetch Südwestfalen listing %s.", url)
                continue
            cards.update(self._cards_from_listing(soup, url))

        for link in self._discover_trade_pages():
            soup = self.parse_html(link)
            if soup is None:
                continue
            cards.update(self._cards_from_listing(soup, link))
        return list(cards.values())

    def _discover_trade_pages(self) -> list[str]:
        soup = self.parse_html(MEISTER_HUB_URL)
        if soup is None:
            return []
        pages: list[str] = []
        for link in soup.select("a[href*='/meisterkurse/']"):
            href = urljoin(BBZ_BASE, link.get("href", ""))
            if href.rstrip("/") != MEISTER_HUB_URL.rstrip("/"):
                pages.append(href)
        return pages

    def _cards_from_listing(self, soup: BeautifulSoup, page_url: str) -> dict[str, dict]:
        cards: dict[str, dict] = {}
        for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
            title = heading.get_text(" ", strip=True)
            if not _is_meister_course(title):
                continue
            block = self._card_block(heading)
            if block is None:
                continue
            text = block.get_text("\n", strip=True)
            detail_url = page_url
            for link in block.select("a[href]"):
                href = urljoin(BBZ_BASE, link.get("href", ""))
                if BBZ_BASE in href:
                    detail_url = href
                    break
            key = f"{title}|{detail_url}"
            cards[key] = {"title": title, "text": text, "url": detail_url}
        return cards

    @staticmethod
    def _card_block(heading: Tag) -> Tag | None:
        node: Tag | None = heading
        for _ in range(4):
            node = node.parent if node is not None else None
            if node is None:
                return None
            text = node.get_text(" ", strip=True)
            if PRICE_RE.search(text) or DURATION_RE.search(text) or DATE_RE.search(text):
                return node
        return heading.parent

    def _parse_card(self, card: dict) -> list[RawCourseOffer]:
        title = card["title"]
        text = card["text"]
        url = card["url"]
        parts, trade = parse_suedwestfalen_title(title)
        if not parts:
            return []

        duration_match = DURATION_RE.search(text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        price_match = PRICE_RE.search(text)
        course_fee = (
            float(price_match.group(1).replace(".", "") + "." + price_match.group(2))
            if price_match else None
        )
        lower = title.lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        teaching_mode = "presence"

        date_match = DATE_RE.search(text)
        if date_match:
            start = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            end = f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}"
            start_date, end_date = start, end
        else:
            start_date = end_date = None

        return [RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration,
            course_fee=course_fee,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability="unknown",
            source_url=url,
            scraped_raw={"title": title, "card_text": text[:1000]},
        )]

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV")):
            match = re.search(
                rf"Teil\s+{roman}.*?([\d.]+),(\d{{2}})\s*€",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehr'], a[href*='Gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(CHAMBER_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Südwestfalen: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Südwestfalen: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_generic_exam_fees(text)
        if not fees:
            logger.warning("HWK Südwestfalen: could not parse exam fees from PDF.")
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
