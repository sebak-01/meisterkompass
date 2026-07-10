"""
Scraper for HWK Freiburg's Gewerbe Akademie Meister courses.

The catalogue uses one family URL per course and a numeric URL per appointment.
Family URLs redirect to the currently selected appointment and link all sibling
appointments, which are fetched separately so fees and availability stay tied
to the correct run.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gewerbeakademie.de"
CATEGORY_URL = f"{BASE_URL}/weiterbildung/kursangebot/kategorie/meister-kompetenz/"

DATE_LOCATION_RE = re.compile(
    r"Termine:\s*(\d{2})\.(\d{2})\.(\d{4})\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4}),\s*([^()]+?)(?=\s*(?:\(|Freie Plätze:|Zeiten:))",
    re.IGNORECASE,
)
DURATION_RE = re.compile(r"Dauer:\s*([\d.]+)\s*Unterrichtsstunden", re.IGNORECASE)
PRICE_RE = re.compile(r"Preis:\s*€?\s*([\d.]+),(\d{2})", re.IGNORECASE)
FREE_RE = re.compile(r"Freie Plätze:\s*(\d+)", re.IGNORECASE)
APPOINTMENT_RE = re.compile(r"/seminar/(?P<slug>[^/]+)/(?P<id>\d+)/?$")


@dataclass(frozen=True)
class CourseSpec:
    trade_name: str | None
    parts: tuple[int, ...]
    default_format: str
    teaching_mode: str = "presence"
    hybrid_in_offenburg: bool = False


COURSES = {
    "mvkel-technik": CourseSpec("Elektrotechniker", (1, 2), "part_time"),
    "mvkfeinwerk": CourseSpec("Feinwerkmechaniker", (1, 2), "full_time"),
    "mvkinstheiz": CourseSpec("Installateur und Heizungsbauer", (1, 2), "part_time"),
    "mvkmetallb": CourseSpec("Metallbauer", (1, 2), "full_time", hybrid_in_offenburg=True),
    "mvk-schreiner": CourseSpec("Tischler", (1, 2), "part_time", "hybrid"),
    "mvkteiliii-tz": CourseSpec(None, (3,), "part_time", "hybrid"),
    "mvkteiliii-vz": CourseSpec(None, (3,), "full_time"),
    "mvkteiliv-tz": CourseSpec(None, (4,), "part_time", "hybrid"),
    "mvkteiliv-vz": CourseSpec(None, (4,), "full_time"),
    "mvk-zahntechnik": CourseSpec("Zahntechniker", (1, 2), "full_time"),
}

LOCATIONS = {
    "offenburg": {"street": "Wasserstraße 19", "zip_code": "77652", "city": "Offenburg"},
    "freiburg": {"street": "Wirthstraße 28", "zip_code": "79110", "city": "Freiburg"},
}


def clean_url(url: str) -> str:
    parts = urlsplit(urljoin(BASE_URL, url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    free = FREE_RE.search(text)
    if free:
        return "available" if int(free.group(1)) > 0 else "full"
    return "unknown"


class HwkFreiburgScraper(BaseScraper):
    chamber_slug = "hwk-freiburg"
    chamber_name = "Handwerkskammer Freiburg"
    chamber_region = "Baden-Württemberg"
    chamber_website = "https://www.hwk-freiburg.de"
    source_url = CATEGORY_URL
    request_delay = 0.8

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        category = self.parse_html(CATEGORY_URL)
        if category is None:
            logger.error("Could not fetch Freiburg Meister category.")
            return []
        families = self._discover_families(category)
        offers: list[RawCourseOffer] = []
        for slug, family_url in families.items():
            family_response = self.get(family_url)
            if family_response is None:
                logger.warning("Could not fetch Freiburg family: %s", family_url)
                continue
            family_soup = BeautifulSoup(family_response.text, "html.parser")
            appointment_urls = self._appointment_urls(family_soup, family_response.url, slug)
            family_offers = []
            for url in appointment_urls:
                response = family_response if clean_url(family_response.url) == clean_url(url) else self.get(url)
                if response is None:
                    continue
                soup = family_soup if clean_url(response.url) == clean_url(family_response.url) else BeautifulSoup(response.text, "html.parser")
                offer = self._parse_appointment(soup, clean_url(response.url), COURSES[slug])
                if offer:
                    family_offers.append(offer)
            if not family_offers:
                family_offers = [self._placeholder(clean_url(family_response.url), COURSES[slug])]
            logger.info("  Freiburg %s → %d offer(s)", slug, len(family_offers))
            offers.extend(family_offers)
        logger.info("HWK Freiburg: parsed %d offers from %d course families.", len(offers), len(families))
        return offers

    @staticmethod
    def _discover_families(soup: BeautifulSoup) -> dict[str, str]:
        found = {}
        for link in soup.select("a[href*='/seminar/']"):
            url = clean_url(link.get("href", ""))
            match = re.search(r"/seminar/([^/]+)/?$", url)
            if match and match.group(1) in COURSES:
                found[match.group(1)] = url
        return found

    @staticmethod
    def _appointment_urls(soup: BeautifulSoup, selected_url: str, slug: str) -> list[str]:
        urls = {clean_url(selected_url)}
        for link in soup.select("a[href*='/seminar/']"):
            url = clean_url(link.get("href", ""))
            match = APPOINTMENT_RE.search(url)
            if match and match.group("slug") == slug:
                urls.add(url)
        return sorted(urls)

    @staticmethod
    def _parse_appointment(soup: BeautifulSoup, url: str, spec: CourseSpec) -> RawCourseOffer | None:
        main = soup.select_one("main") or soup
        text = main.get_text(" ", strip=True)
        date_match = DATE_LOCATION_RE.search(text)
        if not date_match:
            return None
        duration_match = DURATION_RE.search(text)
        price_match = PRICE_RE.search(text)
        city_raw = date_match.group(7).strip()
        location = LOCATIONS["offenburg"] if "offenburg" in city_raw.lower() else LOCATIONS["freiburg"]
        mode = "hybrid" if spec.hybrid_in_offenburg and location["city"] == "Offenburg" else spec.teaching_mode
        format_key = spec.default_format
        if mode == "hybrid":
            format_key = "part_time"
        elif re.search(r"Mo\s*[-–]\s*Do\s+\d{1,2}:\d{2}", text, re.IGNORECASE):
            format_key = "full_time"
        return RawCourseOffer(
            title=build_course_title(spec.trade_name, list(spec.parts)),
            trade_name=spec.trade_name,
            parts=list(spec.parts),
            format_key=format_key,
            teaching_mode=mode,
            start_date=f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}",
            end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
            duration_hours=int(duration_match.group(1).replace(".", "")) if duration_match else None,
            course_fee=float(price_match.group(1).replace(".", "") + "." + price_match.group(2)) if price_match else None,
            city=location["city"],
            street=location["street"],
            zip_code=location["zip_code"],
            availability=parse_availability(text),
            source_url=url,
            scraped_raw={"appointment_url": url, "course_text": text[:800]},
        )

    @staticmethod
    def _placeholder(url: str, spec: CourseSpec) -> RawCourseOffer:
        location = LOCATIONS["freiburg"]
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
            source_url=url,
            scraped_raw={"placeholder": True},
        )
