"""
scraper/hwk_koblenz.py

Scraper for HWK Koblenz Meistervorbereitungskurse.
Source: https://www.hwk-koblenz.de/52,0,courselist.html?search-filter-template=0&search-type=6

HTML structure (verified 2026-05-20 via debug_koblenz.py):
  Each course card lives in a <div class='row'> containing:
    - Contact person (col left)
    - <div class='col-sm-5'> with <h3> → date range + format + course title link
    - Details col → price (6.990,00 €), duration (650 Std.), city, availability

  Exam fees are NOT listed on course pages; enter manually from the PDF
  Gebührenverzeichnis at https://wisum.hwk-koblenz.de/bildung/pdf/meisterakademie/
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

LIST_URL = (
    "https://www.hwk-koblenz.de/52,0,courselist.html"
    "?search-filter-template=0&search-type=6&limit=20&offset={offset}"
)
PAGE_SIZE = 20

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
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + m.group(2))


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


def parse_city(text: str) -> str:
    """
    City appears between duration ('650 Std.') and availability text.
    Valid city names contain only letters, spaces, hyphens — no dots or slashes.
    """
    text = text.replace("\xa0", " ")
    dur_match   = DURATION_PATTERN.search(text)
    avail_match = re.search(
        r"ausgebucht|warteliste|freie\s+Plätze|wenige\s+Plätze", text, re.IGNORECASE
    )
    if dur_match and avail_match and dur_match.end() < avail_match.start():
        between = text[dur_match.end():avail_match.start()]
        valid_city = re.compile(r"^[A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-]+$")
        for line in between.split("\n"):
            line = line.strip()
            if line and 2 < len(line) < 60 and valid_city.match(line):
                return line
    return "Koblenz"  # fallback: all HWK Koblenz courses are in Koblenz


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

        # Fetch detail page to get exact Lehrgangsort address
        street, zip_code = self._parse_detail_address(detail_url, city)

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

    def _parse_detail_address(self, url: str, fallback_city: str) -> tuple[str, str]:
        """
        Fetch the course detail page and extract the Lehrgangsort address.
        Returns (street, zip_code). Falls back to known default if not found.
        """
        import time
        DEFAULT_STREET  = "Friedrich-Ebert-Ring 33"
        DEFAULT_ZIP     = "56068"

        try:
            time.sleep(0.5)  # polite delay
            soup = self.parse_html(url)
            if soup is None:
                return DEFAULT_STREET, DEFAULT_ZIP
            text = soup.get_text("\n")
            # Look for ZIP+street pattern near "Lehrgangsort"
            idx = text.find("Lehrgangsort")
            if idx >= 0:
                block = text[idx:idx + 300]
                zip_m = re.search(r"(\d{5})\s+(\S+.*)", block)
                if zip_m:
                    zip_code = zip_m.group(1)
                    city_line = zip_m.group(2).strip().split("\n")[0]
                    # Street is the line just before the ZIP
                    lines = block[:zip_m.start()].strip().split("\n")
                    street = lines[-1].strip() if lines else ""
                    # Valid street: contains a number (house number)
                    if street and re.search(r"\d", street):
                        return street, zip_code
        except Exception as exc:
            logger.warning("Could not fetch detail address from %s: %s", url, exc)

        return DEFAULT_STREET, DEFAULT_ZIP