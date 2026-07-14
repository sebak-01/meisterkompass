"""Scraper for HWK Dresden's njumii Meister course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.njumii.de"
LISTING_URL = f"{BASE_URL}/kurs-finden.html"
CHAMBER_URL = "https://www.hwk-dresden.de"
FEES_PDF_URL = (
    f"{CHAMBER_URL}/fileadmin/user_upload/mb/Recht/Dokumente/"
    "Gebuehrenverzeichnis_Handwerkskammer-Dresden.pdf"
)
DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})"
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*€")

GENERIC_EXAM_FEES = {1: 440.0, 2: 300.0, 3: 240.0, 4: 240.0}

DRESDEN_TRADE_ALIASES = {
    "gold- und silberschmied": "Gold- und Silberschmiede",
    "land- und baumaschinenmechatroniker": "Land- und Baumaschinenmechatroniker",
}

EXCLUDE_TITLE_RE = re.compile(
    r"industriemeister|infoabend|vorschaltkurs|schwei(?:ß|ss)werkmeister|"
    r"schwei(?:ß|ss)fachmann|arbeitsschutz|praktische meisterpr(?:ü|ue)fung|"
    r"nachschulung|ausbildereignung nach aevo(?!\s*-\s*meister)",
    re.IGNORECASE,
)


def parse_dresden_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if not trade:
        trade = parse_trade(title.replace("handwerk", "handwerk meister"), parts)
    if not trade:
        lower = title.lower()
        for source, canonical in DRESDEN_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower or "keine plätze" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "plätze verfügbar" in lower or "freie plätze" in lower:
        return "available"
    return "unknown"


def _parse_address(text: str) -> tuple[str, str, str]:
    street_match = re.search(
        r"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .-]+(?:straße|str\.|weg|platz|gasse)\s+\d+[A-Za-z]?)"
        r"\s+(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß ()-]+)",
        text,
        re.IGNORECASE,
    )
    if street_match:
        return (
            street_match.group(1).strip(),
            street_match.group(2),
            street_match.group(3).strip(),
        )
    zip_match = re.search(r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß ()-]+)", text)
    if zip_match:
        return "", zip_match.group(1), zip_match.group(2).strip()
    return "Am Lagerplatz 8", "01099", "Dresden"


class HwkDresdenScraper(BaseScraper):
    chamber_slug = "hwk-dresden"
    chamber_name = "Handwerkskammer Dresden"
    chamber_region = "Sachsen"
    chamber_website = CHAMBER_URL
    source_url = LISTING_URL
    request_delay = 0.5

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        listing = self.parse_html(LISTING_URL)
        if listing is None:
            logger.error("Could not fetch HWK Dresden course listing.")
            return []

        courses = self._discover(listing)
        offers: list[RawCourseOffer] = []
        for title, url in courses:
            detail = self.parse_html(url)
            if detail is None:
                logger.warning("Could not fetch Dresden course %s.", url)
                continue
            try:
                parsed = self._parse_course(detail, title, url)
            except Exception as exc:
                logger.warning("Could not parse Dresden course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info("HWK Dresden: parsed %d offers from %d courses.", len(offers), len(courses))
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for link in soup.select("a[href*='kursdetails']"):
            title = link.get_text(" ", strip=True)
            href = link.get("href", "")
            if not title or not href or EXCLUDE_TITLE_RE.search(title):
                continue
            if not re.search(r"meister|teil\s+(i{1,3}|iv|1|2|3|4)\b", title, re.I):
                continue
            url = urljoin(BASE_URL, href)
            found.setdefault(url, title)
        return [(title, url) for url, title in found.items()]

    def _parse_course(
        self, soup: BeautifulSoup, discovery_title: str, url: str
    ) -> list[RawCourseOffer]:
        title = self._page_title(soup) or discovery_title
        parts, trade = parse_dresden_title(title)
        if not parts:
            logger.debug("Skipping unknown Dresden title %r.", title)
            return []

        page_text = soup.get_text(" ", strip=True)
        default_street, default_zip, default_city = _parse_address(page_text)
        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str, str | None]] = set()

        featured = self._parse_featured_run(
            soup, title, parts, trade, url, default_street, default_zip, default_city
        )
        if featured:
            key = (featured.start_date or "", featured.end_date or "", featured.course_fee)
            if key not in seen:
                seen.add(key)
                offers.append(featured)

        for item in soup.select(".accordion-item"):
            offer = self._parse_accordion_run(
                item, title, parts, trade, url, default_street, default_zip, default_city
            )
            if not offer:
                continue
            key = (offer.start_date or "", offer.end_date or "", offer.course_fee)
            if key in seen:
                continue
            seen.add(key)
            offers.append(offer)

        return offers

    @staticmethod
    def _page_title(soup: BeautifulSoup) -> str | None:
        header = soup.select_one(".sliderheader")
        if header is None:
            return None
        title = header.get_text(" ", strip=True)
        return re.sub(r"\s*Meisterkurs\s*$", "", title, flags=re.IGNORECASE).strip()

    def _parse_featured_run(
        self,
        soup: BeautifulSoup,
        title: str,
        parts: list[int],
        trade: str | None,
        url: str,
        default_street: str,
        default_zip: str,
        default_city: str,
    ) -> RawCourseOffer | None:
        row = soup.select_one(".row.g-5")
        if row is None:
            return None
        text = row.get_text("\n", strip=True)
        date_match = DATE_RE.search(text)
        if not date_match:
            return None
        price_match = PRICE_RE.search(text)
        lower = text.lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        city = "Dresden"
        for line in text.splitlines():
            if line.strip().lower() == "kursort":
                continue
            if "dresden" in line.lower() and len(line) < 40:
                city = line.strip()
                break
        return RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            start_date=f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}",
            end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
            duration_hours=self._parse_duration(text),
            course_fee=self._parse_fee(price_match),
            city=city,
            street=default_street,
            zip_code=default_zip,
            availability=_availability(text),
            source_url=url,
            scraped_raw={"title": title, "run_text": text[:1000]},
        )

    def _parse_accordion_run(
        self,
        item: Tag,
        title: str,
        parts: list[int],
        trade: str | None,
        url: str,
        default_street: str,
        default_zip: str,
        default_city: str,
    ) -> RawCourseOffer | None:
        button = item.select_one(".accordion-button")
        text = item.get_text("\n", strip=True)
        heading = button.get_text(" ", strip=True) if button else text.split("\n", 1)[0]
        date_match = DATE_RE.search(heading)
        if not date_match:
            return None
        price_match = PRICE_RE.search(text)
        lower = f"{heading} {text}".lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        city = default_city
        city_match = re.search(r"\b(Dresden|Pirna|Bautzen|Görlitz|Riesa)\b", heading)
        if city_match:
            city = city_match.group(1)
        return RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            start_date=f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}",
            end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
            duration_hours=self._parse_duration(text),
            course_fee=self._parse_fee(price_match),
            city=city,
            street=default_street,
            zip_code=default_zip,
            availability=_availability(text),
            source_url=url,
            scraped_raw={"title": title, "run_text": text[:1000]},
        )

    @staticmethod
    def _parse_duration(text: str) -> int | None:
        match = re.search(r"Dauer\s+([\d.]+)\s+Teilnehmerstunden", text, re.IGNORECASE)
        return int(match.group(1).replace(".", "")) if match else None

    @staticmethod
    def _parse_fee(match: re.Match | None) -> float | None:
        if not match:
            return None
        return float(match.group(1).replace(".", "") + "." + match.group(2))

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        block = re.search(
            r"Meisterprüfungsgebühr.*?Teil I\s+([\d.]+),\d{2}\s*€.*?Teil II\s+([\d.]+),\d{2}\s*€"
            r".*?Teil III\s+([\d.]+),\d{2}\s*€.*?Teil IV\s+([\d.]+),\d{2}\s*€",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if block:
            for index, part in enumerate((1, 2, 3, 4), start=1):
                fees[part] = float(block.group(index).replace(".", ""))
        return fees

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Dresden: pypdf not installed — using fallback exam fees.")
            return {}

        response = self.get(FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Dresden: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Dresden: could not parse Meister exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_pdf() or GENERIC_EXAM_FEES
        return [
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": FEES_PDF_URL,
            }
            for part, fee in fees.items()
        ]
