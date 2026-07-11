"""
Scraper for Meister preparation courses attributed to HWK Karlsruhe.

The Bildungsakademie articles embed current course cards.  The chamber's
provider directory also delegates Parts I/II preparation to external schools;
providers with authoritative current listings are parsed here as additional
offers. Sections without a published date can produce an undated placeholder
so the course offering does not disappear while the next intake is prepared.
"""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bia-karlsruhe.de"
OVERVIEW_URL = f"{BASE_URL}/artikel/meistervorbereitungskurse-3631,57,43.html"
PROVIDER_OVERVIEW_URL = "https://www.hwk-karlsruhe.de/artikel/vorbereitungsmassnahmen-teil-i-und-ii-63,0,85.html"

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_RE = re.compile(r"(\d+)[\s\xa0]*(?:UE|Std\.?|UStd\.?)", re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4}).{0,80}?"
    r"(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE | re.DOTALL,
)

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

IFB_COURSES = (
    ("https://ifb-karlsruhe.de/meisterkurs-augenoptik-vollzeit/", "full_time", "presence"),
    ("https://ifb-karlsruhe.de/meisterkurs-augenoptik-teilzeit-block/", "part_time", "presence"),
    ("https://ifb-karlsruhe.de/meisterkurs-augenoptik-teilzeit-internet/", "part_time", "hybrid"),
)
BFW_COURSE_URL = (
    "https://www.bfw.de/angebot/aufstiegsfortbildung/karlsruhe/"
    "augenoptikmeister-in-teil-1-und-2-wochenendunterricht/"
)
BAKER_COURSE_URL = "https://bivsuedwest.de/meistervorbereitungskurse/"
CALW_COURSE_URL = "https://www.handwerk-calw.de/seminare/meistervorbereitungskurse"

IFB_MANNHEIM_LOCATION = {
    "city": "Mannheim",
    "street": "Theodor-Heuss-Anlage 12",
    "zip_code": "68165",
}
BFW_LOCATION = {
    "city": "Karlsruhe",
    "street": "Daimlerstraße 46",
    "zip_code": "76185",
}
BAKER_LOCATION = {
    "city": "Karlsruhe",
    "street": "Ottostraße 9",
    "zip_code": "76227",
}
CALW_LOCATION = {
    "city": "Nagold",
    "street": "Max-Eyth-Straße 23",
    "zip_code": "72202",
}


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


def _iso_date(groups: tuple[str, str, str]) -> str:
    day, month, year = groups
    return f"{year}-{month}-{day}"


def _euro_amount(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


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
        offers.extend(self._fetch_external_provider_courses())
        logger.info("HWK Karlsruhe: parsed %d course offers total.", len(offers))
        return offers

    def _fetch_external_provider_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        providers = [
            *[
                (url, lambda soup, source_url, fmt=fmt, mode=mode: self._parse_ifb_courses(
                    soup, source_url, fmt, mode,
                ))
                for url, fmt, mode in IFB_COURSES
            ],
            (BFW_COURSE_URL, self._parse_bfw_course),
            (BAKER_COURSE_URL, self._parse_baker_course),
            (CALW_COURSE_URL, self._parse_calw_courses),
        ]
        for url, parser in providers:
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("Could not fetch Karlsruhe external provider: %s", url)
                continue
            try:
                parsed = parser(soup, url)
            except Exception as exc:
                logger.warning("Error parsing Karlsruhe external provider %s: %s", url, exc)
                continue
            logger.info("  Karlsruhe external provider %s → %d offer(s)", url, len(parsed))
            offers.extend(parsed)
        return offers

    @staticmethod
    def _external_offer(
        *,
        trade_name: str,
        format_key: str,
        teaching_mode: str,
        start_date: str | None,
        end_date: str | None,
        course_fee: float | None,
        location: dict,
        availability: str,
        source_url: str,
        provider: str,
    ) -> RawCourseOffer:
        return RawCourseOffer(
            title=build_course_title(trade_name, [1, 2]),
            trade_name=trade_name,
            parts=[1, 2],
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=None,
            course_fee=course_fee,
            city=location["city"],
            street=location["street"],
            zip_code=location["zip_code"],
            availability=availability,
            source_url=source_url,
            scraped_raw={"provider": provider, "provider_overview": PROVIDER_OVERVIEW_URL},
        )

    def _parse_ifb_courses(
        self,
        soup: BeautifulSoup,
        source_url: str,
        format_key: str,
        teaching_mode: str,
    ) -> list[RawCourseOffer]:
        # IFB renders its Elementor content next to an empty <main> element.
        text = soup.get_text(" ", strip=True)
        fee_match = re.search(
            r"Kurs-Gebühr(?:\s*\(Teil\s*1\s*und\s*2\))?\s*:\s*([\d.]+(?:,\d{2})?)(?:,-)?\s*(?:EUR|€)",
            text,
            re.IGNORECASE,
        )
        fee = _euro_amount(fee_match.group(1)) if fee_match else None
        run_re = re.compile(
            r"Kurs-Beginn\s*:\s*(\d{2})\.(\d{2})\.(\d{4}).{0,300}?"
            r"Kurs-(?:Abschluss|Ende)\s*:\s*(\d{2})\.(\d{2})\.(\d{4})",
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(run_re.finditer(text))
        offers = []
        for index, match in enumerate(matches):
            start_date = _iso_date(match.groups()[:3])
            end_date = _iso_date(match.groups()[3:6])
            segment_end = matches[index + 1].start() if index + 1 < len(matches) else match.end() + 500
            run_text = text[match.start():segment_end]
            location = (
                {"city": "Karlsruhe", "street": "Kriegsstraße 216a", "zip_code": "76135"}
                if start_date < "2026-08-01"
                else IFB_MANNHEIM_LOCATION
            )
            offers.append(self._external_offer(
                trade_name="Augenoptiker",
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=start_date,
                end_date=end_date,
                course_fee=fee,
                location=location,
                availability=parse_availability(run_text),
                source_url=source_url,
                provider="Institut für Berufsbildung",
            ))
        return offers

    def _parse_bfw_course(self, soup: BeautifulSoup, source_url: str) -> list[RawCourseOffer]:
        text = (soup.select_one("main") or soup).get_text(" ", strip=True)
        dates = re.search(
            r"Nächster Kurstermin\s+" + DATE_RANGE_RE.pattern,
            text,
            re.IGNORECASE,
        )
        fee_match = re.search(r"Kosten\s+€?\s*([\d.]+,\d{2})", text, re.IGNORECASE)
        if dates is None:
            return []
        return [self._external_offer(
            trade_name="Augenoptiker",
            format_key="part_time",
            teaching_mode="hybrid",
            start_date=_iso_date(dates.groups()[:3]),
            end_date=_iso_date(dates.groups()[3:6]),
            course_fee=_euro_amount(fee_match.group(1)) if fee_match else None,
            location=BFW_LOCATION,
            availability=parse_availability(text),
            source_url=source_url,
            provider="bfw – Unternehmen für Bildung",
        )]

    def _parse_baker_course(self, soup: BeautifulSoup, source_url: str) -> list[RawCourseOffer]:
        text = (soup.select_one("main") or soup).get_text(" ", strip=True)
        section_match = re.search(
            r"Standort Karlsruhe\s+\(Teilzeitkurs\)\s*:(.*?)(?:Prüfungsgebühren|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if section_match is None:
            return []
        section = section_match.group(1)
        fee_match = re.search(r"beträgt\s+([\d.]+,\d{2})\s+Euro", section, re.IGNORECASE)
        return [self._external_offer(
            trade_name="Bäcker",
            format_key="part_time",
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            course_fee=_euro_amount(fee_match.group(1)) if fee_match else None,
            location=BAKER_LOCATION,
            availability=parse_availability(section),
            source_url=source_url,
            provider="ADB Südwest e.V. Standort Karlsruhe",
        )]

    def _parse_calw_courses(self, soup: BeautifulSoup, source_url: str) -> list[RawCourseOffer]:
        page_text = (soup.select_one("main") or soup).get_text(" ", strip=True)
        fee_match = re.search(
            r"Meistervorbereitungskurse im Kfz-Handwerk.{0,600}?"
            r"Kursgebühr:\s*([\d.]+,\d{2})\s*€",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        fee = _euro_amount(fee_match.group(1)) if fee_match else None
        offers = []
        for card in soup.select(".ph-event"):
            text = card.get_text(" ", strip=True)
            if not re.search(r"Kfz-Handwerk|Kraftfahrzeugtechniker", text, re.IGNORECASE):
                continue
            dates = DATE_RANGE_RE.search(text)
            detail = card.select_one("a[href*='termindetails']")
            if dates is None or detail is None:
                continue
            offers.append(self._external_offer(
                trade_name="Kfz.-Techniker",
                format_key="part_time",
                teaching_mode="presence",
                start_date=_iso_date(dates.groups()[:3]),
                end_date=_iso_date(dates.groups()[3:6]),
                course_fee=fee,
                location=CALW_LOCATION,
                availability=parse_availability(text),
                source_url=urljoin(source_url, detail.get("href", "")),
                provider="Kreishandwerkerschaft Calw",
            ))
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
        detail = self.parse_html(detail_url)
        detail_text = detail.get_text(" ", strip=True) if detail is not None else ""
        authoritative_text = detail_text or card_text

        dates = DATE_RE.findall(authoritative_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if dates else None
        end_date = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) > 1 else None
        price_match = PRICE_RE.search(authoritative_text)
        course_fee = (
            float(price_match.group(1).replace(".", "") + "." + price_match.group(2))
            if price_match
            else None
        )
        duration_match = DURATION_RE.search(authoritative_text)
        duration_hours = int(duration_match.group(1)) if duration_match else None
        # Detail pages contain recommendations for other courses, so their
        # format keywords can conflict with this run.  The card heading names
        # this run's format; the detail page remains authoritative for online
        # or hybrid delivery information.
        format_key, _ = parse_format_and_mode(source_title)
        _, teaching_mode = parse_format_and_mode(authoritative_text)
        location = self._parse_detail_location(detail_text)

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
            city=location["city"],
            street=location["street"],
            zip_code=location["zip_code"],
            availability=parse_availability(authoritative_text),
            source_url=detail_url,
            scraped_raw={
                "title": source_title,
                "card_text": card_text[:500],
                "detail_text": detail_text[:700],
                "section_url": section.url,
            },
        )

    @staticmethod
    def _parse_detail_location(detail_text: str) -> dict:
        if detail_text:
            match = re.search(
                r"Lehrgangsort\s+(.+?)\s+(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß -]+?)(?=\s+[A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ]|"
                r"\s+Tel\.|\s+Servicezeiten|\s+ausgebucht|\s+freie Plätze|\s+wenige Plätze)",
                detail_text,
            )
            if match:
                return {
                    "street": match.group(1).strip(),
                    "zip_code": match.group(2),
                    "city": match.group(3).strip(),
                }
        return DEFAULT_LOCATION

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
