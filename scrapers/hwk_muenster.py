"""Scraper for HBZ Münster Meister courses (HWK Münster)."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hbz-bildung.de"
CHAMBER_URL = "https://www.hwk-muenster.de"
LISTING_URL = f"{BASE_URL}/de/meister/meisterschulen-von-a-bis-z"
EXAM_FEES_PAGE_URL = f"{CHAMBER_URL}/de/ueber-uns/rechtsgrundlagen/pruefungswesen"
FEES_PDF_URL = f"{CHAMBER_URL}/fileadmin/user_upload/Rechtsgrundlagen/Gebuehrenverzeichnis.pdf"
GENERIC_EXAM_FEES = {2: 380.0, 3: 290.0, 4: 220.0}

SHORT_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{2,4})\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{2,4})"
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*(?:€|&nbsp;€)")
DURATION_RE = re.compile(r"([\d.]+)\s+Unterrichtsstunden", re.IGNORECASE)

DEFAULT_LOCATION = {
    "street": "Albrecht-Thaer-Straße 9",
    "zip_code": "48147",
    "city": "Münster",
}


def _expand_year(two_or_four: str) -> str:
    if len(two_or_four) == 4:
        return two_or_four
    value = int(two_or_four)
    return str(2000 + value if value < 70 else 1900 + value)


def parse_muenster_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"\*+", "", title).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        return [], None

    trade = parse_trade(cleaned, parts)
    if not trade:
        trade = parse_trade(cleaned.replace("-Meisterschule", " Meister"), parts)
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_course(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in ("industriemeister", "infoabend", "infoveranstaltung")):
        return False
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return False
    if set(parts) <= {3, 4}:
        return "ada" in lower or "betriebswirt" in lower or "ausbilder" in lower
    return "meisterschule" in lower


class HwkMuensterScraper(BaseScraper):
    chamber_slug = "hwk-muenster"
    chamber_name = "Handwerkskammer Münster"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = CHAMBER_URL
    source_url = LISTING_URL
    request_delay = 0.3

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        listing = self.parse_html(LISTING_URL)
        if listing is None:
            logger.error("Could not fetch HBZ Münster course listing.")
            return []

        course_urls = self._discover_course_urls(listing)
        offers: list[RawCourseOffer] = []
        for url in course_urls:
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("Could not fetch HBZ Münster course %s.", url)
                continue
            try:
                offers.extend(self._parse_course_page(soup, url))
            except Exception as exc:
                logger.warning("Could not parse HBZ Münster course %s: %s", url, exc)
        logger.info("HWK Münster: parsed %d offers from %d courses.", len(offers), len(course_urls))
        return offers

    @staticmethod
    def _discover_course_urls(soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for link in soup.select("a[href*='/de/weiterbildung/']"):
            href = urljoin(BASE_URL, link.get("href", ""))
            title = link.get_text(" ", strip=True)
            if href in seen or title.startswith("Details zu"):
                continue
            if not _is_meister_course(title):
                continue
            seen.add(href)
            urls.append(href)
        return urls

    def _parse_course_page(self, soup: BeautifulSoup, url: str) -> list[RawCourseOffer]:
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        parts, trade = parse_muenster_title(title)
        if not parts:
            return []

        page_text = soup.get_text("\n", strip=True)
        duration_match = DURATION_RE.search(page_text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        course_fee, exam_fee = self._parse_fees(page_text)
        lower = title.lower()
        default_format = "full_time" if "vollzeit" in lower else "part_time"
        if "online" in lower:
            teaching_mode = "online"
        elif "hybrid" in lower or "wechselunterricht" in lower:
            teaching_mode = "hybrid"
        else:
            teaching_mode = "presence"

        runs = self._parse_runs(soup)
        if not runs:
            return [RawCourseOffer(
                title=build_course_title(trade, parts),
                trade_name=trade,
                parts=parts,
                format_key=default_format,
                teaching_mode=teaching_mode,
                start_date=None,
                end_date=None,
                duration_hours=duration,
                course_fee=course_fee,
                exam_fee_scraped=exam_fee,
                city=DEFAULT_LOCATION["city"],
                street=DEFAULT_LOCATION["street"],
                zip_code=DEFAULT_LOCATION["zip_code"],
                availability="unknown",
                source_url=url,
                scraped_raw={"title": title, "note": "Keine Termine veröffentlicht"},
            )]

        offers: list[RawCourseOffer] = []
        for index, (start_date, end_date) in enumerate(runs):
            offers.append(RawCourseOffer(
                title=build_course_title(trade, parts),
                trade_name=trade,
                parts=parts,
                format_key=default_format,
                teaching_mode=teaching_mode,
                start_date=start_date,
                end_date=end_date,
                duration_hours=duration,
                course_fee=course_fee,
                exam_fee_scraped=exam_fee,
                city=DEFAULT_LOCATION["city"],
                street=DEFAULT_LOCATION["street"],
                zip_code=DEFAULT_LOCATION["zip_code"],
                availability="unknown",
                source_url=f"{url}#termin-{index + 1}",
                scraped_raw={"title": title, "run_label": f"{start_date} - {end_date}"},
            ))
        return offers

    @staticmethod
    def _parse_fees(text: str) -> tuple[float | None, float | None]:
        course_fee = None
        exam_fee = None
        lower = text.lower()
        if "kursgebühr" in lower:
            block = text[lower.index("kursgebühr"):]
            match = PRICE_RE.search(block)
            if match:
                course_fee = float(match.group(1).replace(".", "") + "." + match.group(2))
        if "prüfungsgebühr" in lower:
            block = text[lower.index("prüfungsgebühr"):]
            amounts = [
                float(match.group(1).replace(".", "") + "." + match.group(2))
                for match in PRICE_RE.finditer(block[:500])
            ]
            if amounts:
                exam_fee = max(amounts)
        return course_fee, exam_fee

    @staticmethod
    def _parse_runs(soup: BeautifulSoup) -> list[tuple[str, str]]:
        runs: list[tuple[str, str]] = []
        for item in soup.select(".course-detail__dates-list-item .date, .course-detail__date-choice-label .date"):
            match = SHORT_DATE_RE.search(item.get_text(" ", strip=True))
            if not match:
                continue
            start = (
                f"{_expand_year(match.group(3))}-{match.group(2)}-{match.group(1)}"
            )
            end = (
                f"{_expand_year(match.group(6))}-{match.group(5)}-{match.group(4)}"
            )
            runs.append((start, end))
        return runs

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV")):
            match = re.search(
                rf"Teil\s+{roman}.*?([\d.]+),(\d{{2}})\s*€",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehr'], a[href*='Gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(CHAMBER_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Münster: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Münster: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_generic_exam_fees(text)
        if not fees:
            logger.warning("HWK Münster: could not parse exam fees from PDF.")
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
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        ]
