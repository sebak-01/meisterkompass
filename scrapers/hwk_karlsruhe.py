"""
Scraper for Meister preparation courses at the Bildungsakademie of HWK Karlsruhe.

The supplied overview is a hub rather than a course list.  It links to one
stable article per Meister section; those articles embed current course cards.
Sections without a published date still produce one undated placeholder so the
course offering does not disappear while the next intake is being prepared.
"""

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bia-karlsruhe.de"
OVERVIEW_URL = f"{BASE_URL}/artikel/meistervorbereitungskurse-3631,57,43.html"

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_RE = re.compile(r"(\d+)[\s\xa0]*(?:UE|Std\.?|UStd\.?)", re.IGNORECASE)

DEFAULT_LOCATION = {
    "city": "Karlsruhe",
    "street": "Hertzstraße 177",
    "zip_code": "76187",
}


@dataclass(frozen=True)
class CourseSection:
    url: str
    trade_name: str | None
    parts: tuple[int, ...]
    placeholder_format: str = "part_time"


COURSE_SECTIONS = (
    CourseSection(
        f"{BASE_URL}/artikel/gepruefte-r-berufsspezialist-in-fuer-kraftfahrzeug-servicetechnik-3631,0,32.html",
        "Kfz.-Techniker",
        (1,),
        "part_or_full",
    ),
    CourseSection(
        f"{BASE_URL}/artikel/kfz-technik-teil-ii-3631,0,31.html",
        "Kfz.-Techniker",
        (2,),
        "part_or_full",
    ),
    CourseSection(
        f"{BASE_URL}/artikel/karosserie-und-fahrzeugbau-teile-iii-3631,0,30.html",
        "Karosserie- und Fahrzeugbauer",
        (1, 2),
        "part_or_full",
    ),
    CourseSection(
        f"{BASE_URL}/artikel/elektrotechnik-teile-i-iv-3631,0,29.html",
        "Elektrotechniker",
        (1, 2, 3, 4),
    ),
    CourseSection(
        f"{BASE_URL}/artikel/meistervorbereitung-teile-iiiiv-3631,0,398.html",
        None,
        (3, 4),
    ),
    CourseSection(
        f"{BASE_URL}/artikel/meistervorbereitung-teil-iii-3631,0,399.html",
        None,
        (3,),
    ),
)


def parse_format_and_mode(text: str) -> tuple[str, str]:
    lower = text.lower()
    if "vollzeit" in lower:
        format_key = "full_time"
    elif any(word in lower for word in ("abend", "wochenende", "teilzeit", "block")):
        format_key = "part_time"
    else:
        format_key = "part_time"

    if "online-anteil" in lower or "hybrid" in lower:
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


class HwkKarlsruheScraper(BaseScraper):
    chamber_slug = "hwk-karlsruhe"
    chamber_name = "Handwerkskammer Karlsruhe"
    chamber_region = "Baden-Württemberg"
    chamber_website = "https://www.hwk-karlsruhe.de"
    source_url = OVERVIEW_URL
    request_delay = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for section in COURSE_SECTIONS:
            soup = self.parse_html(section.url)
            if soup is None:
                logger.warning("Could not fetch Karlsruhe course section: %s", section.url)
                continue
            section_offers = self._parse_section(soup, section)
            if not section_offers:
                section_offers = [self._placeholder(section)]
            logger.info(
                "  Karlsruhe %s, parts %s → %d offer(s)",
                section.trade_name or "generic",
                "+".join(map(str, section.parts)),
                len(section_offers),
            )
            offers.extend(section_offers)
        logger.info("HWK Karlsruhe: parsed %d course offers total.", len(offers))
        return offers

    def _parse_section(self, soup: BeautifulSoup, section: CourseSection) -> list[RawCourseOffer]:
        offers = []
        seen_urls: set[str] = set()
        for link in soup.select("a[href*='coursedetail']"):
            detail_url = link.get("href", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = BASE_URL + detail_url
            if not detail_url or detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            try:
                offers.append(self._parse_card(link, section, detail_url))
            except Exception as exc:
                logger.warning("Error parsing Karlsruhe card %r: %s", link.get_text(strip=True)[:60], exc)
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

    def _parse_card(self, link: Tag, section: CourseSection, detail_url: str) -> RawCourseOffer:
        source_title = link.get_text(" ", strip=True)
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

        return RawCourseOffer(
            title=build_course_title(section.trade_name, list(section.parts)),
            trade_name=section.trade_name,
            parts=list(section.parts),
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
            scraped_raw={"title": source_title, "card_text": card_text[:500], "section_url": section.url},
        )

    @staticmethod
    def _placeholder(section: CourseSection) -> RawCourseOffer:
        return RawCourseOffer(
            title=build_course_title(section.trade_name, list(section.parts)),
            trade_name=section.trade_name,
            parts=list(section.parts),
            format_key=section.placeholder_format,
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=None,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability="unknown",
            source_url=section.url,
            scraped_raw={"section_url": section.url, "placeholder": True},
        )
