"""Scraper for HWK Frankfurt (Oder) / Ostbrandenburg's WordPress Meisterschule."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.weiterbildung-ostbrandenburg.de"
CHAMBER_URL = "https://www.hwk-ff.de"
OVERVIEW_URL = f"{BASE_URL}/meisterschule/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/pruefungen/meisterpruefungen/"
EXAM_FEES_PDF_URL = f"{CHAMBER_URL}/wp-content/uploads/2025/08/Gebuehrenverzeichnis.pdf"
DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})$"
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*(?:€|EUR)", re.IGNORECASE)
DURATION_RE = re.compile(
    r"(?:ca\.\s*)?([\d.]+)\s+Unterrichtsstunden", re.IGNORECASE
)
DEFAULT_LOCATION = {
    "street": "Spiekerstraße 11",
    "zip_code": "15230",
    "city": "Frankfurt (Oder)",
}
GENERIC_EXAM_FEES = {1: 340.0, 2: 340.0, 3: 200.0, 4: 275.0}
EXAM_FEE_QUALIFIER = "Werkstatt- und Materialkosten gesondert"

OB_TRADE_ALIASES = {
    "land- und baumaschinenmechatroniker": "Land- und Baumaschinenmechatroniker",
    "gebäudereiniger": "Gebäudereiniger",
    "strassenbauer": "Straßenbauer",
    "straßenbauer": "Straßenbauer",
    "kosmetiker": "Kosmetiker",
}

EXCLUDE_LINK_RE = re.compile(
    r"fortbildung-|industriemeister|infoabend|mathematik",
    re.IGNORECASE,
)


def _canonical_course_url(href: str) -> str:
    split = urlsplit(urljoin(BASE_URL, href))
    path = split.path.rstrip("/") + "/"
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def parse_ostbrandenburg_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if not trade:
        lower = title.lower()
        for source, canonical in OB_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_course(title: str, href: str) -> bool:
    if EXCLUDE_LINK_RE.search(href) or EXCLUDE_LINK_RE.search(title):
        return False
    lower = title.lower()
    return any(
        phrase in lower
        for phrase in (
            "meisterkurs",
            "ausbildereignung",
            "aevo",
            "kaufmännische betriebsführung",
            "kaufmaennische betriebsfuehrung",
            "teil iii",
            "teil iv",
        )
    )


def _availability(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in ("ausgebucht", "keine plätze")):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "kurs buchen" in lower:
        return "available"
    return "unknown"


def _run_city(text: str) -> str:
    for city in ("Frankfurt (Oder)", "Hennickendorf"):
        if city in text:
            return city
    return DEFAULT_LOCATION["city"]


class HwkFrankfurtOderOstbrandenburgScraper(BaseScraper):
    chamber_slug = "hwk-frankfurt-oder-ostbrandenburg"
    chamber_name = "Handwerkskammer Frankfurt (Oder) – Region Ostbrandenburg"
    chamber_region = "Brandenburg"
    chamber_website = CHAMBER_URL
    source_url = OVERVIEW_URL
    request_delay = 0.6

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        soup = self.parse_html(OVERVIEW_URL)
        if soup is None:
            logger.error("Could not fetch Ostbrandenburg Meisterschule overview.")
            return []

        courses = self._discover(soup)
        offers: list[RawCourseOffer] = []
        for title, url in courses:
            detail = self.parse_html(url)
            if detail is None:
                logger.warning("Could not fetch Ostbrandenburg course %s.", url)
                continue
            try:
                parsed = self._parse_course(detail, title, url)
            except Exception as exc:
                logger.warning("Could not parse Ostbrandenburg course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info(
            "HWK Frankfurt (Oder) / Ostbrandenburg: parsed %d offers from %d courses.",
            len(offers),
            len(courses),
        )
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for link in soup.select("a[href*='/lehrgang/']"):
            title = " ".join(link.get_text(" ", strip=True).split())
            href = link.get("href", "")
            if not title or not href or not _is_meister_course(title, href):
                continue
            found.setdefault(_canonical_course_url(href), title)
        return [(title, url) for url, title in found.items()]

    def _parse_course(
        self, soup: BeautifulSoup, discovery_title: str, url: str
    ) -> list[RawCourseOffer]:
        main = soup.select_one("main") or soup
        h1 = main.select_one("h1")
        source_title = h1.get_text(" ", strip=True) if h1 else discovery_title
        parts, trade = parse_ostbrandenburg_title(f"{source_title} {discovery_title}")
        if not parts:
            logger.debug("Skipping unknown Ostbrandenburg title %r.", source_title)
            return []

        page_text = main.get_text(" ", strip=True)
        duration_match = DURATION_RE.search(page_text)
        duration = (
            int(duration_match.group(1).replace(".", "")) if duration_match else None
        )
        fee_match = re.search(
            r"Lehrgangskosten:\s*([\d.]+),(\d{2})\s*(?:€|EUR)?",
            page_text,
            re.IGNORECASE,
        )
        course_fee = (
            float(fee_match.group(1).replace(".", "") + "." + fee_match.group(2))
            if fee_match
            else None
        )

        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str, str]] = set()
        wrappers = main.select(".hwk-course-app-wrapper")
        if not wrappers:
            wrappers = [
                node
                for node in main.select("div")
                if DATE_RE.match(node.get_text("\n", strip=True).split("\n", 1)[0])
            ]

        for index, wrapper in enumerate(wrappers, start=1):
            offer = self._parse_run(
                wrapper,
                source_title,
                parts,
                trade,
                url,
                duration,
                course_fee,
                index,
            )
            if offer is None:
                continue
            key = (offer.start_date or "", offer.end_date or "", offer.format_key)
            if key in seen:
                continue
            seen.add(key)
            offers.append(offer)

        if offers:
            return offers

        return [RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key="part_time",
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=duration,
            course_fee=course_fee,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability="unknown",
            source_url=url,
            scraped_raw={"title": source_title, "note": "Keine Termine veröffentlicht"},
        )]

    def _parse_run(
        self,
        wrapper: Tag,
        source_title: str,
        parts: list[int],
        trade: str | None,
        url: str,
        duration: int | None,
        course_fee: float | None,
        index: int,
    ) -> RawCourseOffer | None:
        lines = [line.strip() for line in wrapper.get_text("\n", strip=True).splitlines() if line.strip()]
        if not lines:
            return None
        date_match = DATE_RE.match(lines[0])
        if not date_match:
            return None

        text = wrapper.get_text(" ", strip=True)
        lower = text.lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        city = _run_city(text)
        street = DEFAULT_LOCATION["street"]
        zip_code = DEFAULT_LOCATION["zip_code"]
        if city != DEFAULT_LOCATION["city"]:
            street, zip_code = "", ""

        return RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            start_date=f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}",
            end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
            duration_hours=duration,
            course_fee=course_fee,
            city=city,
            street=street,
            zip_code=zip_code,
            availability=_availability(text),
            source_url=f"{url}#termin-{index}",
            scraped_raw={"title": source_title, "run_text": text[:1000]},
        )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        html_patterns = (
            (1, r"Teil\s+I:\s*([\d.]+)\s*Euro"),
            (2, r"Teil\s+II:\s*([\d.]+)\s*Euro"),
            (3, r"Teil\s+III:\s*([\d.]+)\s*Euro"),
            (4, r"Teil\s+IV:\s*([\d.]+)\s*Euro"),
        )
        for part, pattern in html_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fees[part] = float(match.group(1).replace(".", ""))

        if len(fees) == 4:
            return fees

        pdf_match = re.search(
            r"340\s+Euro\s+340\s+Euro\s+200\s+Euro\s+275\s+Euro",
            text,
            re.IGNORECASE,
        )
        if pdf_match:
            return dict(GENERIC_EXAM_FEES)

        pdf_patterns = (
            (1, r"Prüfung\s+Teil\s+I.*?340\s+Euro"),
            (2, r"Prüfung\s+Teil\s+II.*?340\s+Euro"),
            (3, r"Prüfung\s+Teil\s+III.*?200\s+Euro"),
            (4, r"Prüfung\s+Teil\s+IV.*?275\s+Euro"),
        )
        amounts = {1: 340.0, 2: 340.0, 3: 200.0, 4: 275.0}
        for part, pattern in pdf_patterns:
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                fees[part] = amounts[part]
        return fees

    def _fetch_exam_fees(self) -> dict[int, float]:
        page = self.parse_html(EXAM_FEES_PAGE_URL)
        if page is not None:
            fees = self.parse_meister_exam_fees(page.get_text(" ", strip=True))
            if len(fees) == 4:
                return fees

        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Ostbrandenburg: pypdf not installed — using fallback exam fees.")
            return {}

        response = self.get(EXAM_FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Ostbrandenburg: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Ostbrandenburg: could not parse Meister exam fees.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees() or GENERIC_EXAM_FEES
        return [
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": EXAM_FEE_QUALIFIER,
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        ]
