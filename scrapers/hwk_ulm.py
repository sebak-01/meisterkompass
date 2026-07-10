"""
Scraper for HWK Ulm Meister preparation seminars.

The overview links to one server-rendered detail page per course.  A detail can
contain several independent runs; each run has a compact summary containing
dates, format, duration, location, course number, fee and availability.
"""

import logging
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-ulm.de"
OVERVIEW_URL = f"{BASE_URL}/meister-teil1-und2/"

DATE_RANGE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4})"
)
DURATION_RE = re.compile(r"(\d{2,4})\s*UE\b", re.IGNORECASE)
PRICE_RE = re.compile(r"Gebühr\s+([\d.]+)(?:,(\d{2}))?\s*(?:Euro|€)", re.IGNORECASE)
COURSE_NO_RE = re.compile(r"Kurs-Nr\.\s*(?:Kurs\s*\d+,?\s*)?([^\s]+)", re.IGNORECASE)

LOCATIONS = {
    "ulm": {
        "street": "Köllestraße 55",
        "zip_code": "89077",
        "city": "Ulm",
    },
    "friedrichshafen": {
        "street": "Steinbeisstraße 38",
        "zip_code": "88046",
        "city": "Friedrichshafen",
    },
}

TRADE_PATTERNS = (
    ("Fliesen-, Platten- und Mosaikleger", "Fliesen-, Platten- und Mosaikleger"),
    ("Installateur und Heizungsbauer", "Installateur und Heizungsbauer"),
    ("Karosserie", "Karosserie- und Fahrzeugbauer"),
    ("Kraftfahrzeug", "Kfz.-Techniker"),
    ("Feinwerkmechanik", "Feinwerkmechaniker"),
    ("Maler und Lackierer", "Maler und Lackierer"),
    ("Maurer und Betonbauer", "Maurer und Betonbauer"),
    ("Elektrotechnik", "Elektrotechniker"),
    ("Metallbau", "Metallbauer"),
    ("Bäcker", "Bäcker"),
    ("Klempner", "Klempner"),
    ("Tischler", "Tischler"),
)


def parse_title(title: str) -> tuple[str | None, list[int]]:
    if re.search(r"Teil\s+III\b", title, re.IGNORECASE):
        return None, [3]
    if re.search(r"Teil\s+IV\b|Ausbilderschein|AEVO", title, re.IGNORECASE):
        return None, [4]

    if re.search(r"Teil\s+I\s+(?:und|\+|&)\s+II\b", title, re.IGNORECASE):
        parts = [1, 2]
    elif re.search(r"Teil\s+II\b", title, re.IGNORECASE):
        parts = [2]
    else:
        return None, []

    for needle, canonical in TRADE_PATTERNS:
        if needle.lower() in title.lower():
            return canonical, parts
    return None, []


def parse_format(text: str) -> str:
    lower = text.lower()
    if "vollzeitlehrgang" in lower or "vollzeit" in lower:
        return "full_time"
    return "part_time"


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "kurs ausgebucht" in lower or "ausgebucht" in lower:
        return "full"
    if "es gibt noch freie plätze" in lower or "freie plätze" in lower:
        return "available"
    if "warteliste" in lower:
        return "waitlist"
    return "unknown"


def parse_location(text: str, source_url: str) -> dict:
    lower = text.lower()
    if "friedrichshafen" in lower or "/seminar/3-" in source_url:
        return LOCATIONS["friedrichshafen"]
    return LOCATIONS["ulm"]


class HwkUlmScraper(BaseScraper):
    chamber_slug = "hwk-ulm"
    chamber_name = "Handwerkskammer Ulm"
    chamber_region = "Baden-Württemberg"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 1.0

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        overview = self.parse_html(OVERVIEW_URL)
        if overview is None:
            logger.error("Could not fetch HWK Ulm Meister overview.")
            return []

        courses = self._discover_courses(overview)
        offers: list[RawCourseOffer] = []
        for url, listing_title in courses:
            response = self.get(url)
            if response is None:
                logger.warning("Could not fetch Ulm seminar: %s", url)
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            canonical_url = self._canonical_url(response.url)
            heading = soup.select_one("main h1, h1")
            title = heading.get_text(" ", strip=True) if heading else listing_title
            trade_name, parts = parse_title(title)
            if not parts:
                logger.warning("Could not identify Ulm Meister course %r (%s)", title, canonical_url)
                continue

            course_offers = self._parse_runs(soup, canonical_url, title, trade_name, parts)
            logger.info("  Ulm %s → %d offer(s)", title, len(course_offers))
            offers.extend(course_offers)

        logger.info("HWK Ulm: parsed %d course offers from %d course page(s).", len(offers), len(courses))
        return offers

    @staticmethod
    def _canonical_url(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _discover_courses(self, soup: BeautifulSoup) -> list[tuple[str, str]]:
        courses: dict[str, str] = {}
        for link in soup.select("main a[href*='/seminar/'], a[href*='/seminar/']"):
            title = link.get_text(" ", strip=True)
            if "meister" not in title.lower() or "trei 80" in title.lower():
                continue
            url = self._canonical_url(urljoin(BASE_URL, link.get("href", "")))
            courses.setdefault(url, title)
        return list(courses.items())

    def _parse_runs(
        self,
        soup: BeautifulSoup,
        source_url: str,
        source_title: str,
        trade_name: str | None,
        parts: list[int],
    ) -> list[RawCourseOffer]:
        offers = []
        markers = [
            strong
            for strong in soup.find_all("strong")
            if strong.get_text(" ", strip=True) in {"Nächster Termin", "Termin"}
        ]
        seen: set[tuple[str | None, str]] = set()
        for marker in markers:
            container = self._run_container(marker)
            if container is None:
                continue
            text = container.get_text(" ", strip=True)
            date_match = DATE_RANGE_RE.search(text)
            start_date = (
                f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
                if date_match
                else None
            )
            end_date = (
                f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}"
                if date_match
                else None
            )
            course_no_match = COURSE_NO_RE.search(text)
            course_no = course_no_match.group(1).strip(" ,") if course_no_match else ""
            dedup_key = (start_date, course_no)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            duration_match = DURATION_RE.search(text)
            price_match = PRICE_RE.search(text)
            fee = None
            if price_match:
                fee = float(price_match.group(1).replace(".", "") + "." + (price_match.group(2) or "00"))
            location = parse_location(text, source_url)
            run_url = f"{source_url}#kurs-{course_no}" if course_no else source_url

            offers.append(
                RawCourseOffer(
                    title=build_course_title(trade_name, parts),
                    trade_name=trade_name,
                    parts=parts,
                    format_key=parse_format(text or source_title),
                    teaching_mode="presence",
                    start_date=start_date,
                    end_date=end_date,
                    duration_hours=int(duration_match.group(1)) if duration_match else None,
                    course_fee=fee,
                    city=location["city"],
                    street=location["street"],
                    zip_code=location["zip_code"],
                    availability=parse_availability(text),
                    source_url=run_url,
                    scraped_raw={
                        "title": source_title,
                        "course_url": source_url,
                        "course_no": course_no,
                        "run_text": text[:700],
                    },
                )
            )
        return offers

    @staticmethod
    def _run_container(marker: Tag) -> Tag | None:
        node: Tag | None = marker
        for _ in range(4):
            node = node.parent if node is not None else None
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if "Kurstyp" in text and "Kursort" in text and "Kurs-Nr." in text:
                return node
        return None
