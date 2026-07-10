"""
Scraper for Meister preparation courses offered by HWK Mannheim.

The chamber exposes all current Meister courses through one filtered page in
the standard HWK course-list CMS.  Each scheduled run is a separate card, so
the list page contains all data needed by MeisterKompass.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-mannheim.de"
LIST_URL = (
    f"{BASE_URL}/65,0,courselist.html"
    "?search-filter-template=0&search-topic=7&limit=20&offset={offset}"
)
PAGE_SIZE = 20

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
PARTS_RE = re.compile(
    r"Teile?\s+(?P<parts>(?:IV|III|II|I)(?:\s*(?:\+|und|-)\s*(?:IV|III|II|I))*)",
    re.IGNORECASE,
)
AEVO_RE = re.compile(r"(?:AEVO|Ausbilderschein)", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_RE = re.compile(r"(\d+)[\s\xa0]*(?:UE|Std\.?|UStd\.?)", re.IGNORECASE)

TRADE_ALIASES = {
    "Konditoren": "Konditor",
    "Kraftfahrzeugtechnik": "Kfz.-Techniker",
    "Maler und Lackierer": "Maler und Lackierer",
}

DEFAULT_LOCATION = {
    "city": "Mannheim",
    "street": "Gutenbergstraße 49",
    "zip_code": "68167",
}


def parse_parts(title: str) -> list[int]:
    if AEVO_RE.search(title):
        return [4]
    match = PARTS_RE.search(title)
    if not match:
        return []
    tokens = re.split(r"\s*(?:\+|und|-)\s*", match.group("parts").upper())
    return sorted({ROMAN[token] for token in tokens if token in ROMAN})


def parse_trade(title: str, parts: list[int]) -> str | None:
    if not parts or set(parts) <= {3, 4}:
        return None
    match = re.search(
        r"Meistervorbereitung\s+(?P<trade>.+?)\s+Teile?\s+(?:IV|III|II|I)",
        title,
        re.IGNORECASE,
    )
    if not match:
        return None
    trade = match.group("trade").strip(" -")
    return TRADE_ALIASES.get(trade, trade)


def parse_format_and_mode(text: str) -> tuple[str, str]:
    lower = text.lower()
    if "vollzeit" in lower:
        format_key = "full_time"
    elif any(word in lower for word in ("teilzeit", "wochenende", "blockunterricht", "abend")):
        format_key = "part_time"
    else:
        format_key = "part_time"

    if "hybrid" in lower or "online-anteil" in lower:
        teaching_mode = "hybrid"
    elif "online" in lower:
        teaching_mode = "online"
    else:
        teaching_mode = "presence"
    return format_key, teaching_mode


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "wenige plätze" in lower:
        return "available"
    return "unknown"


class HwkMannheimScraper(BaseScraper):
    chamber_slug = "hwk-mannheim"
    chamber_name = "Handwerkskammer Mannheim Rhein-Neckar-Odenwald"
    chamber_region = "Baden-Württemberg"
    chamber_website = BASE_URL
    source_url = LIST_URL.format(offset=0)
    request_delay = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        first = self.parse_html(LIST_URL.format(offset=0))
        if first is None:
            logger.error("Could not fetch HWK Mannheim course list.")
            return []

        total = self._parse_total(first)
        logger.info("HWK Mannheim: %d courses, %d page(s).", total, max(1, -(-total // PAGE_SIZE)))
        offers = self._parse_page(first)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            soup = self.parse_html(LIST_URL.format(offset=offset))
            if soup is None:
                logger.warning("Failed at offset=%d, stopping.", offset)
                break
            offers.extend(self._parse_page(soup))
        logger.info("HWK Mannheim: parsed %d course offers total.", len(offers))
        return offers

    @staticmethod
    def _parse_total(soup: BeautifulSoup) -> int:
        match = re.search(r"von\s+(\d+);\s*Seite", soup.get_text())
        return int(match.group(1)) if match else len(soup.select("a[href*='coursedetail']"))

    def _parse_page(self, soup: BeautifulSoup) -> list[RawCourseOffer]:
        offers = []
        for link in soup.select("a[href*='coursedetail']"):
            try:
                offer = self._parse_card(link)
                if offer:
                    offers.append(offer)
            except Exception as exc:
                logger.warning("Error parsing Mannheim card %r: %s", link.get_text(strip=True)[:60], exc)
        return offers

    @staticmethod
    def _card_container(link: Tag) -> Tag | None:
        row = link.find_parent("div", class_="row")
        if row is not None:
            return row
        node: Tag | None = link
        for _ in range(7):
            node = node.parent if node is not None else None
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if DATE_RE.search(text) and (
                DURATION_RE.search(text) or re.search(r"Plätze|Warteliste|ausgebucht", text, re.IGNORECASE)
            ):
                return node
        return None

    def _parse_card(self, link: Tag) -> RawCourseOffer | None:
        source_title = link.get_text(" ", strip=True)
        parts = parse_parts(source_title)
        if not parts:
            logger.debug("Could not parse parts from Mannheim title %r", source_title)
            return None
        trade_name = parse_trade(source_title, parts)

        container = self._card_container(link)
        card_text = container.get_text(" ", strip=True) if container else source_title
        dates = DATE_RE.findall(card_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if dates else None
        end_date = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) > 1 else None

        price_match = PRICE_RE.search(card_text)
        course_fee = (
            float(price_match.group(1).replace(".", "") + "." + price_match.group(2))
            if price_match
            else None
        )
        duration_match = DURATION_RE.search(card_text)
        duration_hours = int(duration_match.group(1)) if duration_match else None
        format_key, teaching_mode = parse_format_and_mode(card_text)

        detail_url = link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        return RawCourseOffer(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability=parse_availability(card_text),
            source_url=detail_url,
            scraped_raw={"title": source_title, "card_text": card_text[:500]},
        )
