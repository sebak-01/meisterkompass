"""Scraper for HWK Südthüringen's WordPress seminar catalogue."""

import logging
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-suedthueringen.de"
OVERVIEW_URL = f"{BASE_URL}/kurse-und-seminare/"
EXAM_FEES_URL = f"{BASE_URL}/ihr-weg-zum-meister/"
DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})$"
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*(?:€|Euro)", re.IGNORECASE)
DURATION_RE = re.compile(
    r"Seminardauer\s+([\d.]+)\s+Unterrichtseinheiten", re.IGNORECASE
)
COURSE_NO_RE = re.compile(r"Kursnummer\s+([A-Za-z0-9_-]+)", re.IGNORECASE)


def _canonical_seminar_url(href: str) -> str:
    split = urlsplit(urljoin(BASE_URL, href))
    path = split.path.rstrip("/") + "/"
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def parse_suhl_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_link(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in (
        "mathematik für meister", "infoabend", "informationsveranstaltung",
        "meisterbonus", "meisterprämie",
    )):
        return False
    return (
        ("meister" in lower and "industriemeister" not in lower)
        or "kaufmännische betriebsführung" in lower
        or "fachmann" in lower and "handwerksordnung" in lower
        or "ausbildereign" in lower
        or "aevo" in lower
    )


def _availability(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in (
        "keine plätze mehr frei", "bereits ausgebucht",
        "buchung ist nicht mehr möglich",
    )):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "in den warenkorb" in lower:
        return "available"
    return "unknown"


def _location(text: str, teaching_mode: str) -> tuple[str, str, str]:
    if teaching_mode == "online":
        return "", "", "Online"
    matches = re.findall(
        r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß -]*?)"
        r"(?=\s+(?:Kosten|Kursnummer|Kurstyp|Eine|Telefon|E-Mail|Seminardauer)\b|$)",
        text,
    )
    if matches:
        zip_code, city = matches[0]
        city = city.strip()
        if city == "Rohr":
            return "Kloster 1", zip_code, city
        street_match = re.search(
            rf"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .-]+(?:straße|str\.|weg|platz|gasse)\s+\d+[A-Za-z]?)"
            rf"\s+{zip_code}\s+{re.escape(city)}",
            text,
            re.IGNORECASE,
        )
        return (street_match.group(1).strip() if street_match else "", zip_code, city)
    return "Kloster 1", "98530", "Rohr"


class HwkSuedthueringenSuhlScraper(BaseScraper):
    chamber_slug = "hwk-suedthueringen-suhl"
    chamber_name = "Handwerkskammer Südthüringen"
    chamber_region = "Thüringen"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 0.8
    EXAM_FEES = {1: 335.0, 2: 220.0, 3: 205.0, 4: 165.0}

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        soup = self.parse_html(OVERVIEW_URL)
        if soup is None:
            logger.error("Could not fetch HWK Südthüringen course overview.")
            return []

        courses = self._discover(soup)
        offers: list[RawCourseOffer] = []
        for title, url in courses:
            detail = self.parse_html(url)
            if detail is None:
                logger.warning("Could not fetch Südthüringen course %s.", url)
                continue
            try:
                parsed = self._parse_course(detail, title, url)
            except Exception as exc:
                logger.warning("Could not parse Südthüringen course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info("HWK Südthüringen: parsed %d offers from %d courses.", len(offers), len(courses))
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for link in soup.select("a[href*='/seminar/']"):
            title = link.get_text(" ", strip=True) or link.get("title", "")
            href = link.get("href", "")
            if not href or not _is_meister_link(title):
                continue
            found.setdefault(_canonical_seminar_url(href), title)
        return [(title, url) for url, title in found.items()]

    def _parse_course(
        self, soup: BeautifulSoup, discovery_title: str, url: str
    ) -> list[RawCourseOffer]:
        main = soup.select_one("main") or soup
        h1 = main.select_one("h1")
        source_title = h1.get_text(" ", strip=True) if h1 else discovery_title
        # The h1 is a family name and can omit the part number (notably the
        # separately bookable Kfz Teil II page); the overview title retains it.
        parts, trade = parse_suhl_title(f"{source_title} {discovery_title}")
        if not parts:
            logger.debug("Skipping unknown Südthüringen title %r.", source_title)
            return []

        page_text = main.get_text(" ", strip=True)
        duration_match = DURATION_RE.search(page_text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        offers: list[RawCourseOffer] = []
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
            number_match = COURSE_NO_RE.search(text)
            number = number_match.group(1) if number_match else ""
            start = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            key = (start, number)
            if key in seen:
                continue
            seen.add(key)

            lower = f"{source_title} {text}".lower()
            format_key = "full_time" if "vollzeit" in lower else "part_time"
            if "hybrid" in lower or ("online" in lower and "präsenz" in lower):
                teaching_mode = "hybrid"
            elif "online" in lower and "keine onlineschulung" not in lower:
                teaching_mode = "online"
            else:
                teaching_mode = "presence"
            street, zip_code, city = _location(text, teaching_mode)
            price_match = PRICE_RE.search(text)
            offers.append(RawCourseOffer(
                title=build_course_title(trade, parts),
                trade_name=trade,
                parts=parts,
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=start,
                end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
                duration_hours=duration,
                course_fee=(
                    float(price_match.group(1).replace(".", "") + "." + price_match.group(2))
                    if price_match else None
                ),
                city=city,
                street=street,
                zip_code=zip_code,
                availability=_availability(text),
                source_url=f"{url}#kurs-{number}" if number else url,
                scraped_raw={"title": source_title, "course_no": number, "run_text": text[:1000]},
            ))

        if offers:
            return offers
        street, zip_code, city = _location(page_text, "presence")
        return [RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key="part_time",
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=duration,
            course_fee=None,
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=url,
            scraped_raw={"title": source_title, "note": "Keine Termine veröffentlicht"},
        )]

    @staticmethod
    def _run_container(heading: Tag) -> Tag | None:
        node: Tag | None = heading
        for _ in range(6):
            node = node.parent if node is not None else None
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if "Kursnummer" in text and ("Kosten" in text or "Kurstyp" in text):
                return node
        return None

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "ab" if part == 1 else "",
                "source_url": EXAM_FEES_URL,
            }
            for part, fee in self.EXAM_FEES.items()
        )
        return result
