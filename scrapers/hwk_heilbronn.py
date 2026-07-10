"""Scraper for Meister preparation courses at HWK Heilbronn-Franken."""

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-heilbronn.de"
OVERVIEW_URL = f"{BASE_URL}/meistervorbereitung/"

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})$")
DURATION_RE = re.compile(r"Seminardauer\s+(\d{2,4})\s+(?:Stunden|Unterrichtseinheiten)", re.IGNORECASE)
FEE_RE = re.compile(r"Gebühr\s+([\d.]+)(?:,(\d{2}))?\s*(?:EURO|€)", re.IGNORECASE)
COURSE_NO_RE = re.compile(r"Kursnummer\s+(\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class CourseSpec:
    slug: str
    trade_name: str | None
    parts: tuple[int, ...]
    format_key: str
    teaching_mode: str = "presence"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/seminar/{self.slug}/"


COURSES = (
    CourseSpec("mv-metallbau-iii-tz", "Metallbauer", (1, 2), "part_time"),
    CourseSpec("mv-lamas-iii-tz", "Land- und Baumaschinenmechatroniker", (1, 2), "part_time"),
    CourseSpec("mv-karobau-iii-tz-hn", "Karosserie- und Fahrzeugbauer", (1, 2), "part_time"),
    CourseSpec("mv-instheiz-iii-tz", "Installateur und Heizungsbauer", (1, 2), "part_time"),
    CourseSpec("mv-friseure-iii-vz", "Friseur", (1, 2), "full_time"),
    CourseSpec("mv-friseure-iii-tz", "Friseur", (1, 2), "part_time"),
    CourseSpec("mv-zimmer-iii-vz", "Zimmerer", (1, 2), "full_time"),
    CourseSpec("mv-iiiiv-vz-herbst", None, (3, 4), "full_time"),
    CourseSpec("mv-iiiiv-vz-fruehjahr", None, (3, 4), "full_time"),
    CourseSpec("mv-iiiiv-tz-1", None, (3, 4), "part_time"),
    CourseSpec("mv-iiiiv-tz-2", None, (3, 4), "part_time"),
    CourseSpec("mv-iiiiv-e-learning", None, (3, 4), "part_time", "hybrid"),
)

DEFAULT_LOCATION = {
    "street": "Wannenäckerstraße 62",
    "zip_code": "74078",
    "city": "Heilbronn",
}
CITY_LOCATION = {
    "street": "Allee 76",
    "zip_code": "74072",
    "city": "Heilbronn",
}


def parse_availability(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in ("keine plätze mehr frei", "bereits ausgebucht", "buchung ist nicht mehr möglich")):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "in den warenkorb" in lower:
        return "available"
    return "unknown"


class HwkHeilbronnScraper(BaseScraper):
    chamber_slug = "hwk-heilbronn-franken"
    chamber_name = "Handwerkskammer Heilbronn-Franken"
    chamber_region = "Baden-Württemberg"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 0.8

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for spec in COURSES:
            soup = self.parse_html(spec.url)
            if soup is None:
                logger.warning("Could not fetch Heilbronn course: %s", spec.url)
                continue
            parsed = self._parse_course(soup, spec)
            if not parsed:
                parsed = [self._placeholder(spec)]
            logger.info("  Heilbronn %s → %d offer(s)", spec.slug, len(parsed))
            offers.extend(parsed)
        logger.info("HWK Heilbronn-Franken: parsed %d offers.", len(offers))
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
            fee_match = FEE_RE.search(text)
            format_key = "full_time" if "Kurstyp Vollzeit" in text else spec.format_key
            lower = text.lower()
            teaching_mode = "hybrid" if spec.teaching_mode == "hybrid" or ("online" in lower and "präsenz" in lower) else "presence"
            location = CITY_LOCATION if "allee 76" in lower else DEFAULT_LOCATION
            offers.append(RawCourseOffer(
                title=build_course_title(spec.trade_name, list(spec.parts)),
                trade_name=spec.trade_name,
                parts=list(spec.parts),
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=start_date,
                end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
                duration_hours=int(duration_match.group(1)) if duration_match else None,
                course_fee=float(fee_match.group(1).replace(".", "") + "." + (fee_match.group(2) or "00")) if fee_match else None,
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
            if "Seminardauer" in text and "Kursnummer" in text and "Kurstyp" in text:
                return node
        return None

    @staticmethod
    def _placeholder(spec: CourseSpec) -> RawCourseOffer:
        return RawCourseOffer(
            title=build_course_title(spec.trade_name, list(spec.parts)),
            trade_name=spec.trade_name,
            parts=list(spec.parts),
            format_key=spec.format_key,
            teaching_mode=spec.teaching_mode,
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=None,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability="unknown",
            source_url=spec.url,
            scraped_raw={"placeholder": True},
        )
