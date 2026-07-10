"""Scraper for official HWK Reutlingen Meister preparation courses."""

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-reutlingen.de"
OVERVIEW_URL = f"{BASE_URL}/weiterbildung/der-weg-zum-meister/vorbereitung-und-pruefung/"

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})$")
DURATION_RE = re.compile(r"Seminardauer\s+([\d.]+)\s+Unterrichtseinheiten", re.IGNORECASE)
PRICE_RE = re.compile(r"Kosten\s+([\d.]+),(\d{2})\s*€", re.IGNORECASE)
COURSE_NO_RE = re.compile(r"Kursnummer\s+(\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class CourseSpec:
    slug: str
    trade_name: str | None
    parts: tuple[int, ...]
    default_format: str

    @property
    def url(self) -> str:
        return f"{BASE_URL}/seminar/{self.slug}/"


COURSES = (
    CourseSpec("t-mv-i-ii_elo-tz", "Elektrotechniker", (1, 2), "part_time"),
    CourseSpec("t-mv-i-ii_elo-we", "Elektrotechniker", (1, 2), "part_time"),
    CourseSpec("t-mv-i-ii_metall-tz", "Metallbauer", (1, 2), "part_time"),
    CourseSpec("r-mv-i-ii_friseur-tz", "Friseur", (1, 2), "part_time"),
    CourseSpec("r-mv-i-ii_massschn-vz", "Maßschneider", (1, 2), "full_time"),
    CourseSpec("r-mv-i-ii_shk-tz", "Installateur und Heizungsbauer", (1, 2), "part_time"),
    CourseSpec("r-mv-ii_kfz-tz", "Kfz.-Techniker", (2,), "part_time"),
    CourseSpec("r-mv-iii-iv-tz", None, (3, 4), "part_time"),
    CourseSpec("r-mv-iii-iv-vz", None, (3, 4), "full_time"),
)

LOCATIONS = {
    "tübingen": {"street": "Raichbergstraße 87", "zip_code": "72072", "city": "Tübingen"},
    "sigmaringen": {"street": "Römerstraße 22", "zip_code": "72488", "city": "Sigmaringen"},
    "reutlingen": {"street": "Hindenburgstraße 58", "zip_code": "72762", "city": "Reutlingen"},
}


def parse_availability(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in ("keine plätze mehr frei", "bereits ausgebucht", "buchung ist nicht mehr möglich")):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "freier platz" in lower or "in den warenkorb" in lower:
        return "available"
    return "unknown"


def parse_location(text: str) -> dict:
    lower = text.lower()
    if "sigmaringen" in lower or "modefachschule hopf" in lower:
        return LOCATIONS["sigmaringen"]
    if "tübingen" in lower:
        return LOCATIONS["tübingen"]
    return LOCATIONS["reutlingen"]


class HwkReutlingenScraper(BaseScraper):
    chamber_slug = "hwk-reutlingen"
    chamber_name = "Handwerkskammer Reutlingen"
    chamber_region = "Baden-Württemberg"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 0.8

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for spec in COURSES:
            soup = self.parse_html(spec.url)
            if soup is None:
                logger.warning("Could not fetch Reutlingen course: %s", spec.url)
                continue
            parsed = self._parse_course(soup, spec)
            if not parsed:
                parsed = [self._placeholder(spec)]
            logger.info("  Reutlingen %s → %d offer(s)", spec.slug, len(parsed))
            offers.extend(parsed)
        logger.info("HWK Reutlingen: parsed %d offers.", len(offers))
        return offers

    def _parse_course(self, soup: BeautifulSoup, spec: CourseSpec) -> list[RawCourseOffer]:
        main = soup.select_one("main") or soup
        offers = []
        seen: set[tuple[str, str]] = set()
        for heading in main.find_all("h4"):
            heading_text = heading.get_text(" ", strip=True)
            date_match = DATE_RE.fullmatch(heading_text)
            if not date_match:
                continue
            container = self._run_container(heading)
            if container is None:
                continue
            text = container.get_text(" ", strip=True)
            course_no_match = COURSE_NO_RE.search(text)
            course_no = course_no_match.group(1) if course_no_match else ""
            start_date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            if (start_date, course_no) in seen:
                continue
            seen.add((start_date, course_no))
            duration_match = DURATION_RE.search(text)
            price_match = PRICE_RE.search(text)
            format_key = "full_time" if "Kurstyp Vollzeit" in text else "part_time"
            location = parse_location(text)
            offers.append(RawCourseOffer(
                title=build_course_title(spec.trade_name, list(spec.parts)),
                trade_name=spec.trade_name,
                parts=list(spec.parts),
                format_key=format_key,
                teaching_mode="presence",
                start_date=start_date,
                end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
                duration_hours=int(duration_match.group(1).replace(".", "")) if duration_match else None,
                course_fee=float(price_match.group(1).replace(".", "") + "." + price_match.group(2)) if price_match else None,
                city=location["city"],
                street=location["street"],
                zip_code=location["zip_code"],
                availability=parse_availability(text),
                source_url=f"{spec.url}#kurs-{course_no}" if course_no else spec.url,
                scraped_raw={"title": heading_text, "course_no": course_no, "run_text": text[:800]},
            ))
        return offers

    @staticmethod
    def _run_container(heading: Tag) -> Tag | None:
        node: Tag | None = heading
        for _ in range(5):
            node = node.parent if node is not None else None
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if "Seminardauer" in text and ("Kursnummer" in text or "Kurstyp" in text):
                return node
        return None

    @staticmethod
    def _placeholder(spec: CourseSpec) -> RawCourseOffer:
        location = LOCATIONS["reutlingen"]
        return RawCourseOffer(
            title=build_course_title(spec.trade_name, list(spec.parts)),
            trade_name=spec.trade_name,
            parts=list(spec.parts),
            format_key=spec.default_format,
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=None,
            city=location["city"],
            street=location["street"],
            zip_code=location["zip_code"],
            availability="unknown",
            source_url=spec.url,
            scraped_raw={"placeholder": True},
        )
