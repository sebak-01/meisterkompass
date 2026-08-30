"""
scrapers/hwk_koblenz.py

Scraper for HWK Koblenz Meistervorbereitungskurse.
Source: https://www.hwk-koblenz.de/52,0,courselist.html?search-filter-template=0&search-type=6

HTML structure (verified 2026-05-20 via debug_koblenz.py):
  Each course card lives in a <div class='row'> containing:
    - Contact person (col left)
    - <div class='col-sm-5'> with <h3> → date range + format + course title link
    - Details col → price (6.990,00 €), duration (650 Std.), city, availability

  Exam fees are NOT listed on course pages; weekly tariff scrape reads the
  Gebührenverzeichnis PDF from the Rechtsgrundlagen page.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title, city_between, euro_from_groups
from .exam_fee_tariff import (
    download_pdf_text,
    parse_koblenz_meister_fees,
    part_fee_rows,
    resolve_pdf_url_from_page,
)

logger = logging.getLogger(__name__)

LIST_URL = (
    "https://www.hwk-koblenz.de/52,0,courselist.html"
    "?search-filter-template=0&search-type=6&limit=20&offset={offset}"
)
PAGE_SIZE = 20
EXAM_FEES_PAGE_URL = (
    "https://www.hwk-koblenz.de/artikel/rechtsgrundlagen-52,86,199.html#gebuehren"
)
EXAM_FEES_PDF_FALLBACK = (
    "https://www.hwk-koblenz.de/downloads/gebuehrenverzeichnis-2025-52,1964.pdf"
)
GENERIC_EXAM_FEES = {1: 1200.0, 2: 600.0, 3: 400.0, 4: 400.0}

# HWK Koblenz Bildungsstätte — used when a detail page omits Lehrgangsort.
DEFAULT_STREET = "Friedrich-Ebert-Ring 33"
DEFAULT_ZIP    = "56068"

# Maps title/heading keywords to (format_key, teaching_mode)
FORMAT_MAP = {
    "vollzeit":   ("full_time",  "presence"),
    "teilzeit":   ("part_time",  "presence"),
    "online":     ("part_time",  "online"),
    "hybrid":     ("part_time",  "hybrid"),
    "wochenende": ("part_time",  "presence"),
    "block":      ("part_time",  "presence"),
}

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

TITLE_PATTERN = re.compile(
    r"^(?P<trade>.*?)\s*Teile?\s+(?P<parts_str>(?:IV|III|II|I)(?:\s+und\s+(?:IV|III|II|I))*)",
    re.IGNORECASE,
)
PRICE_PATTERN    = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_PATTERN = re.compile(r"(\d+)[\s\xa0]*(?:Std\.|UE|Ustd\.)", re.IGNORECASE)
DATE_PATTERN     = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_title(title: str) -> tuple[str | None, list[int]]:
    m = TITLE_PATTERN.match(title.strip())
    if not m:
        return None, []
    trade_raw = m.group("trade").strip()
    trade_name = trade_raw if trade_raw else None
    parts = []
    for token in re.split(r"\s+und\s+", m.group("parts_str"), flags=re.IGNORECASE):
        token = token.strip().upper()
        if token in ROMAN:
            parts.append(ROMAN[token])
    return trade_name, sorted(parts)


def parse_format_and_mode(text: str) -> tuple[str, str]:
    """
    Returns (format_key, teaching_mode) based on keywords in text.
    Defaults to ("part_time", "presence") if no keyword matches.
    """
    lower = text.lower()
    for key, (fmt, mode) in FORMAT_MAP.items():
        if key in lower:
            return fmt, mode
    return "part_time", "presence"


def parse_price(text: str) -> float | None:
    m = PRICE_PATTERN.search(text)
    return euro_from_groups(m.group(1), m.group(2)) if m else None


def parse_duration(text: str) -> int | None:
    m = DURATION_PATTERN.search(text)
    return int(m.group(1)) if m else None


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht"  in lower: return "full"
    if "warteliste"  in lower: return "waitlist"
    if "wenige"      in lower: return "available"
    if "freie"       in lower: return "available"
    return "unknown"


AVAILABILITY_MARKER_RE = re.compile(
    r"ausgebucht|warteliste|freie\s+Plätze|wenige\s+Plätze", re.IGNORECASE
)


def parse_city(text: str) -> str:
    text = text.replace("\xa0", " ")
    return city_between(
        text,
        DURATION_PATTERN.search(text),
        AVAILABILITY_MARKER_RE.search(text),
        default="Koblenz",
    )


class HwkKoblenzScraper(BaseScraper):
    chamber_slug    = "hwk-koblenz"
    chamber_name    = "Handwerkskammer Koblenz"
    chamber_region  = "Rheinland-Pfalz"
    chamber_website = "https://www.hwk-koblenz.de"
    source_url      = LIST_URL.format(offset=0)

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        first = self.parse_html(LIST_URL.format(offset=0))
        if first is None:
            logger.error("Could not fetch HWK Koblenz course list.")
            return []

        total = self._parse_total(first)
        logger.info("HWK Koblenz: %d courses, %d page(s).", total, -(-total // PAGE_SIZE))

        all_offers = self._parse_page(first)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            soup = self.parse_html(LIST_URL.format(offset=offset))
            if soup is None:
                logger.warning("Failed at offset=%d, stopping.", offset)
                break
            all_offers.extend(self._parse_page(soup))

        logger.info("HWK Koblenz: parsed %d course offers total.", len(all_offers))
        return all_offers

    def _parse_total(self, soup: BeautifulSoup) -> int:
        m = re.search(r"von\s+(\d+);\s*Seite", soup.get_text())
        return int(m.group(1)) if m else len(soup.select("a[href*='coursedetail']"))

    def _parse_page(self, soup: BeautifulSoup) -> list[RawCourseOffer]:
        offers = []
        for link in soup.select("a[href*='coursedetail']"):
            try:
                offer = self._parse_card(link)
                if offer:
                    offers.append(offer)
            except Exception as exc:
                logger.warning("Error parsing card '%s': %s",
                               link.get_text(strip=True)[:60], exc)
        return offers

    def _parse_card(self, link: Tag) -> RawCourseOffer | None:
        title_text = link.get_text(strip=True)
        detail_url = link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = "https://www.hwk-koblenz.de" + detail_url

        trade_name, parts = parse_title(title_text)
        if not parts:
            return None

        title_clean = build_course_title(trade_name, parts)

        card_row = link.find_parent("div", class_="row")
        if card_row is None:
            return None

        h3 = link.find_parent("h3")
        h3_text = h3.get_text(separator=" ", strip=True) if h3 else ""

        format_key, teaching_mode = parse_format_and_mode(h3_text)

        dates = DATE_PATTERN.findall(h3_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if len(dates) >= 1 else None
        end_date   = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) >= 2 else None

        card_text  = card_row.get_text(separator="\n", strip=True)
        price          = parse_price(card_text)
        duration_hours = parse_duration(card_text)
        city           = parse_city(card_text)
        availability   = parse_availability(card_text)

        street, zip_code = self.lehrgangsort_address(
            detail_url, default_street=DEFAULT_STREET, default_zip=DEFAULT_ZIP,
        )

        return RawCourseOffer(
            title=title_clean,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=price,
            city=city,
            street=street,
            zip_code=zip_code,
            availability=availability,
            source_url=detail_url,
            scraped_raw={
                "title":     title_text,
                "h3_text":   h3_text,
                "card_text": card_text[:500],
            },
        )

    def published_exam_fee_rows(self) -> list[dict]:
        pdf_url = resolve_pdf_url_from_page(
            self,
            EXAM_FEES_PAGE_URL,
            fallback_url=EXAM_FEES_PDF_FALLBACK,
            href_substrings=("gebuehrenverzeichnis",),
            label="HWK Koblenz",
        ) or EXAM_FEES_PDF_FALLBACK
        text = download_pdf_text(self, pdf_url, label="HWK Koblenz")
        fees, qualifier = parse_koblenz_meister_fees(text) if text else ({}, "bis zu")
        if not fees:
            logger.warning("HWK Koblenz: using fallback Meister exam fees.")
            fees, qualifier = GENERIC_EXAM_FEES, "bis zu"
        return part_fee_rows(
            self.chamber_slug,
            fees,
            source_url=EXAM_FEES_PAGE_URL,
            qualifier=qualifier,
        )
