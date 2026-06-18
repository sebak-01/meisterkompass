"""
scraper/hwk_trier.py

Scraper for HWK Trier Meistervorbereitungskurse.

Source structure (verified 2026-05-26):
  1. Overview page lists trades with "mehr lesen" article links.
  2. From each trade article, coursedetail links lead to individual run pages.
  3. Each coursedetail page contains fees, schedule, location, availability.
  4. Exam fees ARE listed on course pages → saved into ExamFee model.

Post-processing:
  - Missing prices/exam fees are filled from the nearest-dated course of the same trade+parts.
"""

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL     = "https://www.hwk-trier.de"
OVERVIEW_URL = f"{BASE_URL}/artikel/meistervorbereitungskurse-54,585,2181.html"

PRICE_PATTERN    = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_PATTERN = re.compile(r"(\d+)[\s\xa0]*Std\.", re.IGNORECASE)
DATE_PATTERN     = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
ZIP_CITY_PATTERN = re.compile(r"(\d{5})\s+(.+)")

FORMAT_MAP = {
    "vollzeit":   "full_time",
    "teilzeit":   "part_time",
    "wochenende": "part_time",
    "block":      "part_time",
}

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
_ROMAN_ALT = r"(?:IV|III|II|I)"
_PARTS_PAT = rf"{_ROMAN_ALT}(?:\s*[+]\s*{_ROMAN_ALT})*"

TRADE_ALIASES = {
    "Elektrotechniker":                "Elektrotechniker",
    "Friseure":                        "Friseur",
    "Installateure und Heizungsbauer": "Installateur- und Heizungsbauer",
    "Kraftfahrzeugtechniker":          "Kfz.-Techniker",
    "KFZ-Techniker":                   "Kfz.-Techniker",   # abbreviated variant
    "Maler und Lackierer":             "Maler und Lackierer",
    "Maurer und Betonbauer":           "Maurer und Betonbauer",
    "Metallbauer":                     "Metallbauer",
    "Tischler":                        "Tischler",
    "Zahntechniker":                   "Zahntechniker",
    "Zimmerer":                        "Zimmerer",
}


def parse_price(text: str) -> float | None:
    m = PRICE_PATTERN.search(text)
    return float(m.group(1).replace(".", "") + "." + m.group(2)) if m else None


def parse_duration(text: str) -> int | None:
    m = DURATION_PATTERN.search(text)
    return int(m.group(1)) if m else None


def parse_format(text: str) -> str:
    """Return format based on the FIRST matching keyword in text."""
    lower = text.lower()
    positions: dict[int, str] = {}
    for key, val in FORMAT_MAP.items():
        pos = lower.find(key)
        if pos >= 0:
            positions[pos] = val
    return positions[min(positions)] if positions else "part_time"


def parse_teaching_mode(page_text: str) -> str:
    """
    Determine teaching mode.
    If a 'Lehrgangsort' section exists the course has a physical location -> Präsenz.
    Only fall through to Online if there is NO location section and 'online'
    appears explicitly in the schedule content (not just in the navigation).

    The HWK Trier navigation always contains 'Weiterbildungen online', so we
    must NOT rely on a simple full-text search for 'online'.
    """
    if re.search(r"Lehrgangsort", page_text, re.IGNORECASE):
        return "presence"
    # No physical location found — check schedule area only (first 3000 chars)
    schedule_area = page_text[:3000].lower()
    if re.search(r"\bonline\b", schedule_area):
        return "online"
    return "presence"  # safe default


def parse_parts_and_trade(h1_text: str) -> tuple[list[int], str | None]:
    """
    Parse h1 like "Teil I+II Elektrotechniker" or "Teil III Wirtschaft und Recht".
    Uses proper Roman numeral alternation (IV|III|II|I).
    Returns ([1, 2], "Elektrotechniker") or ([3], None) for generic parts.
    """
    text = h1_text.strip()
    m = re.match(
        rf"^Teil(?:e)?\s+(?P<parts>{_PARTS_PAT})"
        r"(?:\s*[-–]\s*|\s+)(?P<rest>.+)?$",
        text, re.IGNORECASE,
    )
    if not m:
        return [], None

    parts_str = m.group("parts").strip().upper()
    parts = []
    for token in re.split(r"\s*[+]\s*", parts_str):
        token = token.strip()
        if token in ROMAN:
            parts.append(ROMAN[token])

    rest = (m.group("rest") or "").strip()

    # Parts III and/or IV are trade-independent
    if set(parts) <= {3, 4}:
        return sorted(parts), None

    trade = TRADE_ALIASES.get(rest, rest) if rest else None
    return sorted(parts), trade


class HwkTrierScraper(BaseScraper):
    chamber_slug    = "hwk-trier"
    chamber_name    = "Handwerkskammer Trier"
    chamber_region  = "Rheinland-Pfalz"
    chamber_website = BASE_URL
    source_url      = OVERVIEW_URL
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        overview = self.parse_html(OVERVIEW_URL)
        if overview is None:
            logger.error("Could not fetch HWK Trier overview page.")
            return []

        trade_article_urls = self._collect_trade_article_urls(overview)
        logger.info("HWK Trier: found %d trade article links.", len(trade_article_urls))

        all_detail_urls: list[str] = []
        for art_url in trade_article_urls:
            detail_urls = self._collect_detail_urls_from_article(art_url)
            logger.info("  %s → %d coursedetail links", art_url.split("/")[-1], len(detail_urls))
            all_detail_urls.extend(detail_urls)

        logger.info("HWK Trier: %d course detail pages to scrape.", len(all_detail_urls))

        offers: list[RawCourseOffer] = []
        for url in all_detail_urls:
            offer = self._parse_detail_page(url)
            if offer:
                offers.append(offer)

        # Fill missing prices from nearest-dated course of same trade+parts
        offers = self._fill_missing_prices(offers)

        logger.info("HWK Trier: parsed %d course offers.", len(offers))
        return offers

    # ------------------------------------------------------------------
    # Price fill: propagate from nearest dated course of same type
    # ------------------------------------------------------------------

    def _fill_missing_prices(self, offers: list[RawCourseOffer]) -> list[RawCourseOffer]:
        """
        For any offer with a missing course_fee or exam_fee_scraped, find the
        chronologically nearest offer with the same trade_name and parts and
        copy the missing fee from it.
        """
        def date_distance(a: RawCourseOffer, b: RawCourseOffer) -> int:
            try:
                da = date.fromisoformat(a.start_date) if a.start_date else None
                db = date.fromisoformat(b.start_date) if b.start_date else None
                if da and db:
                    return abs((da - db).days)
            except ValueError:
                pass
            return 99999

        for offer in offers:
            needs_course = offer.course_fee is None
            needs_exam   = offer.exam_fee_scraped is None

            if not needs_course and not needs_exam:
                continue

            # Candidates: same trade and same parts, not itself
            candidates = [
                o for o in offers
                if o is not offer
                and o.trade_name == offer.trade_name
                and o.parts == offer.parts
            ]
            if not candidates:
                continue

            if needs_course:
                with_fee = [c for c in candidates if c.course_fee is not None]
                if with_fee:
                    nearest = min(with_fee, key=lambda c: date_distance(offer, c))
                    offer.course_fee = nearest.course_fee
                    logger.debug(
                        "Filled missing course_fee %.2f for %s from %s",
                        offer.course_fee, offer.title, nearest.start_date,
                    )

            if needs_exam:
                with_fee = [c for c in candidates if c.exam_fee_scraped is not None]
                if with_fee:
                    nearest = min(with_fee, key=lambda c: date_distance(offer, c))
                    offer.exam_fee_scraped = nearest.exam_fee_scraped
                    logger.debug(
                        "Filled missing exam_fee %.2f for %s from %s",
                        offer.exam_fee_scraped, offer.title, nearest.start_date,
                    )

        return offers

    # ------------------------------------------------------------------
    # Crawl helpers
    # ------------------------------------------------------------------

    def _collect_trade_article_urls(self, soup: BeautifulSoup) -> list[str]:
        urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True).lower()
            if ("artikel/meisterkurs" in href or
                "artikel/teil-iii" in href or
                "artikel/teil-iv" in href or
                ("mehr lesen" in text and "artikel" in href)):
                full_url = href if href.startswith("http") else BASE_URL + href
                if full_url not in urls:
                    urls.append(full_url)
        return urls

    def _collect_detail_urls_from_article(self, article_url: str) -> list[str]:
        soup = self.parse_html(article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", article_url)
            return []
        urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "coursedetail" in href:
                full_url = href if href.startswith("http") else BASE_URL + href
                if full_url not in urls:
                    urls.append(full_url)
        return urls

    def _parse_detail_page(self, url: str) -> RawCourseOffer | None:
        soup = self.parse_html(url)
        if soup is None:
            return None
        try:
            return self._extract_offer(soup, url)
        except Exception as exc:
            logger.warning("Error parsing %s: %s", url, exc)
            return None

    def _extract_offer(self, soup: BeautifulSoup, url: str) -> RawCourseOffer | None:
        h1 = soup.find("h1")
        h1_text = h1.get_text(strip=True) if h1 else ""

        parts, trade_name = parse_parts_and_trade(h1_text)
        if not parts:
            logger.debug("Could not parse parts from h1 %r at %s", h1_text, url)
            return None

        title = build_course_title(trade_name, parts)
        page_text    = soup.get_text(separator="\n")
        availability = self._parse_availability(page_text)
        teaching_mode = parse_teaching_mode(page_text)

        # Fees
        course_fee = None
        exam_fee_scraped = None
        kurs_match  = re.search(r"Kurs:\s*([\d.]+),(\d{2})[\s\xa0]*€", page_text)
        pruef_match = re.search(r"Prüfung:\s*([\d.]+),(\d{2})[\s\xa0]*€", page_text)
        if kurs_match:
            course_fee = float(kurs_match.group(1).replace(".", "") + "." + kurs_match.group(2))
        if pruef_match:
            exam_fee_scraped = float(pruef_match.group(1).replace(".", "") + "." + pruef_match.group(2))

        # Schedule
        dates = DATE_PATTERN.findall(page_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if len(dates) >= 1 else None
        end_date   = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) >= 2 else None
        duration_hours = parse_duration(page_text)
        format_key     = parse_format(page_text)

        # Location
        city = "Trier"
        street = ""
        zip_code = ""
        zip_match = re.search(r"(\d{5})\s+([A-ZÄÖÜa-zäöüß][^\n]{1,40})", page_text)
        if zip_match:
            zip_code = zip_match.group(1)
            city     = zip_match.group(2).strip()
            lines    = [l.strip() for l in page_text.split("\n") if l.strip()]
            for i, line in enumerate(lines):
                if line.startswith(zip_match.group(1)) and i > 0:
                    if re.search(r"\d", lines[i - 1]):
                        street = lines[i - 1]
                    break

        return RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=city,
            exam_fee_scraped=exam_fee_scraped,
            street=street,
            zip_code=zip_code,
            availability=availability,
            source_url=url,
            scraped_raw={"h1": h1_text, "url": url,
                         "course_fee": course_fee, "exam_fee": exam_fee_scraped},
        )

    def _parse_availability(self, text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ("ausgebucht", "keine freien", "nicht buchbar")):
            return "full"
        if "warteliste" in lower:
            return "waitlist"
        if any(w in lower for w in ("wenige", "letzte")):
            return "available"
        if any(w in lower for w in ("freie", "ausreichend", "verfügbar", "buchbar")):
            return "available"
        return "unknown"