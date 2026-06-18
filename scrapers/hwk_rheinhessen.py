"""
scraper/hwk_rheinhessen.py

Scraper for Handwerkskammer Rheinhessen Meistervorbereitungskurse.
Source: https://www.hwk.de/meisterkurse/

This is a WordPress site — completely different structure from the other
three RLP chambers which all use the same HWK-standard CMS.

Architecture:
  - /meisterkurse/ lists known trade URLs as <a> links
  - Each trade URL (e.g. /seminar/elektrotechniker-teil-i-und-ii-eli/) is a
    WordPress page containing one or more course runs
  - Each course run block contains:
      date range, availability, full address, duration (Stunden), fee (EURO)
  - Exam fees are not reliably listed on course pages; they require a
    separate page per trade (e.g. /meisterpruefung-dachdecker/).
    For now, exam fees are left blank and can be entered manually in admin.

Course run detection strategy:
  Since the WordPress pages have no standard container class per run,
  we split the main content on date-range patterns and extract each
  run's data from the surrounding text block.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL      = "https://www.hwk.de"
OVERVIEW_URL  = f"{BASE_URL}/meisterkurse/"

# -----------------------------------------------------------------------
# Known trade pages with their canonical trade name and parts.
# Derived from the links on /meisterkurse/ (verified 2026-05-27).
# Note: duplicate URLs (same page, different menu entry) are deduplicated.
# -----------------------------------------------------------------------
TRADE_PAGES: list[dict] = [
    # Trade-specific Parts I + II
    {"slug": "dd",                                               "trade": "Dachdecker",                      "parts": [1, 2]},
    {"slug": "elektrotechniker-teil-i-und-ii-eli",              "trade": "Elektrotechniker",                "parts": [1, 2]},
    {"slug": "fliesenleger-i-und-ii-fli",                       "trade": "Fliesen-, Platten- und Mosaikleger", "parts": [1, 2]},
    {"slug": "fri-tz",                                          "trade": "Friseur",                         "parts": [1, 2]},
    {"slug": "meisterkurs-friseure-teile-iii-vollzeit-fri-vz",  "trade": "Friseur",                         "parts": [1, 2]},
    {"slug": "installateur-und-heizungsbauer-teile-i-und-ii-inst", "trade": "Installateur- und Heizungsbauer", "parts": [1, 2]},
    {"slug": "kraftfahrzeugtechniker-teile-i-und-ii-kfz",       "trade": "Kfz.-Techniker",                  "parts": [1, 2]},
    {"slug": "mal",                                             "trade": "Maler und Lackierer",             "parts": [1, 2]},
    {"slug": "maurer-und-betonbauer-teile-i-und-ii-mau",        "trade": "Maurer und Betonbauer",           "parts": [1, 2]},
    {"slug": "metallbauer-teile-i-und-ii-met",                  "trade": "Metallbauer",                     "parts": [1, 2]},
    {"slug": "tischler-teile-i-und-ii-ti",                      "trade": "Tischler",                        "parts": [1, 2]},
    {"slug": "zimmerer-teile-i-und-ii-zim",                     "trade": "Zimmerer",                        "parts": [1, 2]},
    # Generic Part III (Wirtschaft und Recht)
    {"slug": "teil-iii-tz",                                     "trade": None, "parts": [3]},
    {"slug": "teil-iii-vz",                                     "trade": None, "parts": [3]},
    # Part III via FKM track
    {"slug": "fachmann-frau-fuer-kaufmaennische-betriebsfuehrung-fkm-tz",  "trade": None, "parts": [3], "title_override": "Fachmann/-frau für kaufmännische Betriebsführung"},
    {"slug": "fachmann-frau-fuer-kaufmaennsche-betriebsfuehrung-fkm-vz",   "trade": None, "parts": [3], "title_override": "Fachmann/-frau für kaufmännische Betriebsführung"},
    # Generic Part IV (Berufs- und Arbeitspädagogik / AEVO)
    {"slug": "ausbildereignung-nach-aevo-teilzeit-ada-tz",      "trade": None, "parts": [4]},
    {"slug": "vorbereitung-ausbildereignung-in-vollzeit-aevo-ada-vz", "trade": None, "parts": [4]},
]

# Regex patterns
DATE_RE       = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE      = re.compile(r"([\d.]+),(\d{2})\s*EURO", re.IGNORECASE)
# Broader price regex for pages without dates — handles "7.300€" and "7.300,00 €"
KURSGEBUEHR_RE = re.compile(
    r"Kursgebühr[:\s]*([\d.]+)(?:,(\d{2}))?[\s\xa0]*€",
    re.IGNORECASE,
)
DURATION_RE   = re.compile(r"(\d+)\s*Stunden?", re.IGNORECASE)
ZIP_CITY_RE   = re.compile(r"(\d{5})\s+([A-ZÄÖÜa-zäöüß][^\n]{1,50})")
# Known HWK Rheinhessen locations with exact coordinates
# These bypass Nominatim geocoding to ensure consistent map pins.
KNOWN_COORDS: dict[str, tuple[float, float]] = {
    "robert-bosch": (49.959692, 8.260685),   # Robert-Bosch-Str./Straße 8
    "dekan-laist":  (49.966844, 8.267110),   # Dekan-Laist-Str. 5
}
# Fallback for courses whose street couldn't be parsed. All HWK Rheinhessen
# courses run at the Hechtsheim Bildungszentrum, so default there rather than
# let city-level geocoding drop the pin on the A60 motorway through Mainz.
DEFAULT_COORDS: tuple[float, float] = KNOWN_COORDS["robert-bosch"]

def resolve_coords(street: str) -> tuple[float, float] | None:
    """Return hardcoded coordinates for known HWK Rheinhessen streets."""
    s = street.lower()
    for key, coords in KNOWN_COORDS.items():
        if key in s:
            return coords
    return None

STREET_RE     = re.compile(r"[A-ZÄÖÜa-zäöüß][^\n]{2,50}\s+\d+[a-zA-Z]?$")

# Date-range pattern: "03.09.2026 — 18.01.2028" (em dash, en dash, hyphen, or "bis")
DATE_RANGE_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})\s*(?:[—–\-]+|bis)\s*(\d{2}\.\d{2}\.\d{4})"
)


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def parse_price(text: str) -> float | None:
    m = PRICE_RE.search(text)
    return float(m.group(1).replace(".", "") + "." + m.group(2)) if m else None


def parse_duration(text: str) -> int | None:
    m = DURATION_RE.search(text)
    return int(m.group(1)) if m else None


def parse_availability(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ("ausgebucht", "keine freien", "nicht buchbar", "voll")):
        return "full"
    if any(w in lower for w in ("wenige", "letzte")):
        return "available"
    if any(w in lower for w in ("freie", "verfügbar", "plätze frei")):
        return "available"
    return "unknown"


def parse_format_from_url(slug: str) -> str:
    """Detect format from URL slug keywords."""
    slug_lower = slug.lower()
    if "vollzeit" in slug_lower or "-vz" in slug_lower:
        return "full_time"
    return "part_time"


class HwkRheinhessenScraper(BaseScraper):
    """
    Scraper for HWK Rheinhessen.

    Strategy:
      1. Scrape each known trade page URL.
      2. Extract course run blocks by splitting on date-range patterns.
      3. Parse each block for dates, address, price, duration, availability.

    Exam fees: Not reliably available on course pages.
    Enter manually via admin from https://www.hwk.de/meisterpruefung-[trade]/
    """

    chamber_slug    = "hwk-rheinhessen"
    chamber_name    = "Handwerkskammer Rheinhessen"
    chamber_region  = "Rheinland-Pfalz"
    chamber_website = BASE_URL
    source_url      = OVERVIEW_URL
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        # Optionally refresh the trade page list from /meisterkurse/
        # For now, use the hardcoded list (stable WordPress URLs).
        offers: list[RawCourseOffer] = []

        for trade_page in TRADE_PAGES:
            url  = f"{BASE_URL}/seminar/{trade_page['slug']}/"
            page_offers = self._scrape_trade_page(
                url,
                trade_name=trade_page["trade"],
                parts=trade_page["parts"],
                default_format=parse_format_from_url(trade_page["slug"]),
                title_override=trade_page.get("title_override"),
            )
            logger.info("  %s → %d offer(s)", trade_page["slug"], len(page_offers))
            offers.extend(page_offers)

        logger.info("HWK Rheinhessen: parsed %d course offers total.", len(offers))
        return offers

    # ------------------------------------------------------------------
    # Fallback: price-only offer for pages without scheduled dates
    # ------------------------------------------------------------------

    def _extract_static_offer(
        self,
        text: str,
        source_url: str,
        trade_name: str | None,
        parts: list[int],
        default_format: str = "part_time",
        title_override: str | None = None,
    ) -> RawCourseOffer | None:
        """
        For trade pages that list a Kursgebühr but have no scheduled dates yet,
        create a single CourseOffer with no dates so the price remains visible
        in comparisons. start_date=None indicates "Termine nicht verfügbar".
        """
        m = KURSGEBUEHR_RE.search(text)
        if not m:
            return None

        integer_part = m.group(1).replace(".", "")
        decimal_part = m.group(2) or "00"
        course_fee = float(f"{integer_part}.{decimal_part}")

        # Try to get location from ZIP pattern
        city = "Mainz"
        zip_code = "55129"
        street = "Robert-Bosch-Straße 8"
        zip_m = ZIP_CITY_RE.search(text)
        if zip_m:
            zip_code = zip_m.group(1)
            city     = zip_m.group(2).strip()
            if city.startswith("Mainz-"):
                city = "Mainz"

        logger.info(
            "No course dates found for %s — creating price-only offer (%.2f €).",
            source_url, course_fee,
        )

        return RawCourseOffer(
            title=title_override or build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=default_format,
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=course_fee,
            city=city,
            exam_fee_scraped=None,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=source_url,
            scraped_raw={"note": "Termine nicht verfügbar", "course_fee": course_fee},
        )

    # ------------------------------------------------------------------
    # Trade page scraping
    # ------------------------------------------------------------------

    def _scrape_trade_page(
        self,
        url: str,
        trade_name: str | None,
        parts: list[int],
        default_format: str = "part_time",
        title_override: str | None = None,
    ) -> list[RawCourseOffer]:
        soup = self.parse_html(url)
        if soup is None:
            logger.warning("Could not fetch trade page: %s", url)
            return []

        # Extract the main content area (skip navigation)
        main = (
            soup.find("main")
            or soup.find(id="content")
            or soup.find("div", class_=re.compile(r"entry-content|page-content|site-content", re.I))
            or soup.find("div", class_="container")
            or soup
        )

        content_text = main.get_text(separator="\n")
        offers = self._extract_runs(content_text, url, trade_name, parts, default_format, title_override=title_override)

        # Deduplicate: WordPress renders some blocks twice (preview + full content).
        seen: set[tuple] = set()
        unique: list[RawCourseOffer] = []
        for o in offers:
            key = (o.start_date, o.end_date)
            if key not in seen:
                seen.add(key)
                unique.append(o)

        # Fallback: if no dated runs found, create a price-only offer so the
        # course and its fee remain visible for comparison purposes.
        if not unique:
            fallback = self._extract_static_offer(
                content_text, url, trade_name, parts, default_format,
                title_override=title_override,
            )
            if fallback:
                unique.append(fallback)

        return unique

    # ------------------------------------------------------------------
    # Course run extraction
    # ------------------------------------------------------------------

    def _extract_runs(
        self,
        text: str,
        source_url: str,
        trade_name: str | None,
        parts: list[int],
        default_format: str = "part_time",
        title_override: str | None = None,
    ) -> list[RawCourseOffer]:
        """
        Split page text on date-range patterns to isolate each course run.
        Each block between two date-ranges (or between date-range and end of text)
        is parsed as one course run.
        """
        offers = []

        # Find all date-range positions
        matches = list(DATE_RANGE_RE.finditer(text))
        if not matches:
            logger.debug("No date ranges found at %s", source_url)
            return []

        # Build blocks: from each match start to the next match start (or end)
        for i, match in enumerate(matches):
            block_start = match.start()
            block_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block       = text[block_start:block_end]

            offer = self._parse_run_block(
                block, match, source_url, trade_name, parts, default_format
            )
            if offer:
                offers.append(offer)

        return offers

    def _parse_run_block(
        self,
        block: str,
        date_match: re.Match,
        source_url: str,
        trade_name: str | None,
        parts: list[int],
        default_format: str = "part_time",
        title_override: str | None = None,
    ) -> RawCourseOffer | None:
        # Dates from the matched date range
        start_raw, end_raw = date_match.group(1), date_match.group(2)

        def fmt(d: str) -> str:  # "03.09.2026" → "2026-09-03"
            dd, mm, yyyy = d.split(".")
            return f"{yyyy}-{mm}-{dd}"

        start_date = fmt(start_raw)
        end_date   = fmt(end_raw)

        # Price
        course_fee = parse_price(block)

        # Duration
        duration_hours = parse_duration(block)
        if duration_hours is None:
            logger.debug("No duration found in block starting %s", start_date)

        # Availability
        availability = parse_availability(block)

        # Location: look for ZIP+city pattern
        city        = "Mainz"
        street      = "Robert-Bosch-Straße 8"  # Rheinhessen default location
        zip_code    = "55129"
        location_name = ""

        zip_m = ZIP_CITY_RE.search(block)
        if zip_m:
            zip_code = zip_m.group(1)
            city     = zip_m.group(2).strip()
            # Normalize Mainz districts (e.g. "Mainz-Hechtsheim") → "Mainz"
            if city.startswith("Mainz-"):
                city = "Mainz"

            # Try to find street line just before the ZIP line
            lines = block.split("\n")
            for idx, line in enumerate(lines):
                if zip_m.group(1) in line:
                    if idx > 0 and STREET_RE.search(lines[idx - 1].strip()):
                        street = lines[idx - 1].strip()
                    # Location name: two lines before ZIP (if present and not an availability line)
                    if idx > 1:
                        candidate = lines[idx - 2].strip()
                        if candidate and len(candidate) > 4 and not re.search(
                            r"freie|wenige|ausgebucht|Plätze|Stunden|€|EURO|\d{2}\.\d{2}", candidate
                        ):
                            location_name = candidate
                    break

        if not (course_fee or duration_hours):
            # Block has no useful data — skip (likely a boilerplate section)
            return None

        coords = resolve_coords(street)
        return RawCourseOffer(
            title=title_override or build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=default_format,
            teaching_mode="presence",
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=city,
            exam_fee_scraped=None,  # must be entered manually
            street=street,
            zip_code=zip_code,

            availability=availability,
            source_url=source_url,
            scraped_raw={
                "start":          start_date,
                "end":            end_date,
                "price":          course_fee,
                "location_name":  location_name,
                "block_preview":  block[:300],
            },
        )