"""
Scraper for Meister courses at the Bildungsakademie HWK Region Stuttgart.

The WordPress listing is filtered client-side, while each course detail page
contains server-rendered appointment cards with authoritative ``data-*``
attributes for dates, fees, duration and learning format.  Courses without a
published appointment are retained as undated placeholders.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bia-stuttgart.de"
LIST_URL = f"{BASE_URL}/kurse/?filter=meisterkurse"

DEFAULT_LOCATION = {
    "street": "Holderäckerstraße 37",
    "zip_code": "70499",
    "city": "Stuttgart",
}


@dataclass(frozen=True)
class CourseSpec:
    slug: str
    trade_name: str | None
    parts: tuple[int, ...]
    placeholder_format: str = "part_time"
    placeholder_fee: float | None = None
    placeholder_availability: str = "unknown"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/kurse/{self.slug}/"


COURSES = (
    CourseSpec("meisterkurs-teil-3", None, (3,)),
    CourseSpec("ausbilderschein-handwerkskammer-meister-teil-4", None, (4,)),
    CourseSpec("kfz-meister", "Kfz.-Techniker", (1, 2, 3, 4), "full_time", 9150.0, "full"),
    CourseSpec("kfz-meister-teil-2", "Kfz.-Techniker", (2,)),
    CourseSpec("berufsspezialist-kfz-servicetechnik", "Kfz.-Techniker", (1,)),
    CourseSpec("shk-meister", "Installateur und Heizungsbauer", (1, 2), "part_time", 6420.0),
    CourseSpec("karosseriebauermeister", "Karosserie- und Fahrzeugbauer", (1, 2)),
    CourseSpec("buchbindermeister", "Buchbinder", (1, 2)),
)

FORMAT_MAP = {
    "vollzeit": ("full_time", "presence"),
    "teilzeit": ("part_time", "presence"),
    "blended learning": ("part_time", "hybrid"),
    "blockunterricht": ("part_time", "presence"),
    "crashkurs": ("full_time", "presence"),
    "e-learning": ("part_time", "online"),
}
DURATION_RE = re.compile(r"Dauer:\s*[^,]+,\s*([\d.]+)\s*Unterrichtseinheiten", re.IGNORECASE)


def parse_format_and_mode(value: str) -> tuple[str, str]:
    return FORMAT_MAP.get(value.strip().lower(), ("part_time", "presence"))


def parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.strptime(value, "%d/%m/%Y").date().isoformat()


class HwkStuttgartScraper(BaseScraper):
    chamber_slug = "hwk-stuttgart"
    chamber_name = "Handwerkskammer Region Stuttgart"
    chamber_region = "Baden-Württemberg"
    chamber_website = "https://www.hwk-stuttgart.de"
    source_url = LIST_URL
    request_delay = 1.0

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for spec in COURSES:
            soup = self.parse_html(spec.url)
            if soup is None:
                logger.warning("Could not fetch Stuttgart course: %s", spec.url)
                continue
            course_offers = self._parse_course(soup, spec)
            if not course_offers:
                course_offers = [self._placeholder(soup, spec)]
            logger.info(
                "  Stuttgart %s, parts %s → %d offer(s)",
                spec.trade_name or "generic",
                "+".join(map(str, spec.parts)),
                len(course_offers),
            )
            offers.extend(course_offers)
        logger.info("HWK Stuttgart: parsed %d course offers total.", len(offers))
        return offers

    def _parse_course(self, soup: BeautifulSoup, spec: CourseSpec) -> list[RawCourseOffer]:
        offers = []
        for card in soup.select(".appointment-listing-container .card[data-appointment-start-date]"):
            learning_method = card.get("data-appointment-learning-method", "")
            format_key, teaching_mode = parse_format_and_mode(learning_method)
            text = card.get_text(" ", strip=True)
            is_full = "ausgebucht" in text.lower()
            availability = "full" if is_full else "available"

            price = card.get("data-appointment-price")
            duration = card.get("data-appointment-teaching-units")
            appointment_id = card.get("data-appointment-id", "")
            source_url = f"{spec.url}#termin-{appointment_id}" if appointment_id else spec.url

            offers.append(
                RawCourseOffer(
                    title=build_course_title(spec.trade_name, list(spec.parts)),
                    trade_name=spec.trade_name,
                    parts=list(spec.parts),
                    format_key=format_key,
                    teaching_mode=teaching_mode,
                    start_date=parse_iso_date(card.get("data-appointment-start-date")),
                    end_date=parse_iso_date(card.get("data-appointment-end-date")),
                    duration_hours=int(float(duration)) if duration else None,
                    course_fee=float(price) if price else None,
                    city=DEFAULT_LOCATION["city"],
                    street=DEFAULT_LOCATION["street"],
                    zip_code=DEFAULT_LOCATION["zip_code"],
                    availability=availability,
                    source_url=source_url,
                    scraped_raw={
                        "course_url": spec.url,
                        "appointment_id": appointment_id,
                        "learning_method": learning_method,
                        "appointment_text": text[:400],
                    },
                )
            )
        return offers

    @staticmethod
    def _placeholder(soup: BeautifulSoup, spec: CourseSpec) -> RawCourseOffer:
        main = soup.select_one("main") or soup
        text = main.get_text(" ", strip=True)
        duration_match = DURATION_RE.search(text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        return RawCourseOffer(
            title=build_course_title(spec.trade_name, list(spec.parts)),
            trade_name=spec.trade_name,
            parts=list(spec.parts),
            format_key=spec.placeholder_format,
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=duration,
            course_fee=spec.placeholder_fee,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability=spec.placeholder_availability,
            source_url=spec.url,
            scraped_raw={"course_url": spec.url, "placeholder": True, "course_text": text[:700]},
        )
