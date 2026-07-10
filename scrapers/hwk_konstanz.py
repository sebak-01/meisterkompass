"""Scraper for Meister courses offered by the Bildungsakademie HWK Konstanz."""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bildungsakademie.de"
LIST_URL = f"{BASE_URL}/seminare/suche/?__name_category=4000"

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*[–—-]\s*(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE = re.compile(r"Kosten\s+([\d.]+),(\d{2})\s*€", re.IGNORECASE)
DURATION_RE = re.compile(r"Lehrgangsdauer\s*([\d.]+)\s*UE", re.IGNORECASE)
ADDRESS_RE = re.compile(r"Lehrgangsort\s+(.+?)\s+(\d{5})\s+(.+?)(?=\s+(?:ausgebucht|wenige|ausreichend|Kursinformation|Kurs buchen|Infomaterial))", re.IGNORECASE)


@dataclass(frozen=True)
class CourseSpec:
    trade_name: str | None
    parts: tuple[int, ...]


COURSES = {
    "mv_baecker": CourseSpec("Bäcker", (1, 2)),
    "mv_dachdecker": CourseSpec("Dachdecker", (1, 2)),
    "mv_elektro": CourseSpec("Elektrotechniker", (1, 2)),
    "mv_feinwerk": CourseSpec("Feinwerkmechaniker", (1, 2)),
    "mv_fliesenleger": CourseSpec("Fliesen-, Platten- und Mosaikleger", (1, 2)),
    "mv_friseur": CourseSpec("Friseur", (1, 2)),
    "mv_installateur": CourseSpec("Installateur- und Heizungsbauer", (1, 2)),
    "mv_klempner": CourseSpec("Klempner", (1, 2)),
    "mv_konditor": CourseSpec("Konditor", (1, 2)),
    "mv_maler": CourseSpec("Maler und Lackierer", (1, 2)),
    "mv_maurer": CourseSpec("Maurer und Betonbauer", (1, 2)),
    "mv_metall": CourseSpec("Metallbauer", (1, 2)),
    "mv_schreiner": CourseSpec("Tischler", (1, 2)),
    "mv_stuckateur": CourseSpec("Stuckateur", (1, 2)),
    "mv_zimmerer_tz": CourseSpec("Zimmerer", (1, 2)),
    "mv_zimmerer": CourseSpec("Zimmerer", (1, 2)),
    "mv_dach_zweitmstr": CourseSpec("Dachdecker", (1, 2)),
    "mv_iv_bl_rw": CourseSpec(None, (4,)),
    "mv_iv_tz": CourseSpec(None, (4,)),
    "mv_iiiiv_si": CourseSpec(None, (3, 4)),
    "mv_iiiiv_rw": CourseSpec(None, (3, 4)),
    "mv_iiiiv_wt": CourseSpec(None, (3, 4)),
}

LOCATIONS = {
    "singen": {"street": "Lange Straße 20", "zip_code": "78224", "city": "Singen"},
    "rottweil": {"street": "Steinhauserstraße 18", "zip_code": "78628", "city": "Rottweil"},
    "waldshut": {"street": "Friedrichstraße 3", "zip_code": "79761", "city": "Waldshut-Tiengen"},
}


def canonical_url(url: str) -> str:
    parts = urlsplit(urljoin(BASE_URL, url))
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", "www.bildungsakademie.de", path, "", ""))


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "wenige plätze" in lower or "freie plätze" in lower:
        return "available"
    return "unknown"


def parse_format_and_mode(summary: str, text: str) -> tuple[str, str]:
    combined = f"{summary} {text}".lower()
    format_key = "full_time" if "vollzeit" in summary.lower() else "part_time"
    hybrid_words = ("hybrid", "online-unterricht", "online-seminar", "selbstlernphase", "blended learning")
    teaching_mode = "hybrid" if any(word in combined for word in hybrid_words) else "presence"
    return format_key, teaching_mode


def parse_location(text: str) -> dict:
    match = ADDRESS_RE.search(text)
    if match:
        city_raw = match.group(3).strip()
        city = "Singen" if city_raw.startswith("Singen") else city_raw
        return {"street": match.group(1).strip(), "zip_code": match.group(2), "city": city}
    lower = text.lower()
    if "waldshut" in lower:
        return LOCATIONS["waldshut"]
    if "rottweil" in lower:
        return LOCATIONS["rottweil"]
    return LOCATIONS["singen"]


class HwkKonstanzScraper(BaseScraper):
    chamber_slug = "hwk-konstanz"
    chamber_name = "Handwerkskammer Konstanz"
    chamber_region = "Baden-Württemberg"
    chamber_website = "https://www.hwk-konstanz.de"
    source_url = LIST_URL
    request_delay = 0.8

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        listing = self.parse_html(LIST_URL)
        if listing is None:
            logger.error("Could not fetch HWK Konstanz course list.")
            return []
        discovered = self._discover(listing)
        offers: list[RawCourseOffer] = []
        for slug, url in discovered.items():
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("Could not fetch Konstanz course: %s", url)
                continue
            course_offers = self._parse_course(soup, url, COURSES[slug])
            if not course_offers:
                course_offers = [self._placeholder(url, COURSES[slug])]
            logger.info("  Konstanz %s → %d offer(s)", slug, len(course_offers))
            offers.extend(course_offers)
        logger.info("HWK Konstanz: parsed %d offers from %d pages.", len(offers), len(discovered))
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> dict[str, str]:
        found: dict[str, str] = {}
        for link in soup.select("a[href*='/seminar/']"):
            url = canonical_url(link.get("href", ""))
            match = re.search(r"/seminar/([^/]+)/", url)
            if match and match.group(1) in COURSES:
                found[match.group(1)] = url
        return found

    def _parse_course(self, soup: BeautifulSoup, detail_url: str, spec: CourseSpec) -> list[RawCourseOffer]:
        offers = []
        seen: set[str] = set()
        for link in soup.select("a.termin_details[vernr]"):
            vernr = link.get("vernr", "")
            if not vernr or vernr in seen:
                continue
            seen.add(vernr)
            card = soup.select_one(f"#uni-kurs-{vernr}")
            if card is None:
                continue
            text = card.get_text(" ", strip=True)
            date_match = DATE_RE.search(text)
            price_match = PRICE_RE.search(text)
            duration_match = DURATION_RE.search(text)
            if not date_match:
                continue
            format_key, teaching_mode = parse_format_and_mode(link.get_text(" ", strip=True), text)
            location = parse_location(text)
            offers.append(RawCourseOffer(
                title=build_course_title(spec.trade_name, list(spec.parts)),
                trade_name=spec.trade_name,
                parts=list(spec.parts),
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}",
                end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
                duration_hours=int(duration_match.group(1).replace(".", "")) if duration_match else None,
                course_fee=float(price_match.group(1).replace(".", "") + "." + price_match.group(2)) if price_match else None,
                city=location["city"],
                street=location["street"],
                zip_code=location["zip_code"],
                availability=parse_availability(text),
                source_url=f"{detail_url}#uni-kurs-{vernr}",
                scraped_raw={"detail_url": detail_url, "vernr": vernr, "summary": link.get_text(" ", strip=True), "run_text": text[:700]},
            ))
        return offers

    @staticmethod
    def _placeholder(url: str, spec: CourseSpec) -> RawCourseOffer:
        return RawCourseOffer(
            title=build_course_title(spec.trade_name, list(spec.parts)),
            trade_name=spec.trade_name,
            parts=list(spec.parts),
            format_key="part_time",
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=None,
            city="Singen",
            street=LOCATIONS["singen"]["street"],
            zip_code=LOCATIONS["singen"]["zip_code"],
            availability="unknown",
            source_url=url,
            scraped_raw={"detail_url": url, "placeholder": True},
        )
