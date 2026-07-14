"""Scraper for HWK Chemnitz's Meister course catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import MONTHS, parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-chemnitz.de"
OVERVIEW_URL = f"{BASE_URL}/weiterbildung/meisterschule/"
PROGRAM_URL = (
    f"{BASE_URL}/weiterbildung/bildungsprogramm/?search=1&statisticGroups%5B%5D=meister12"
)
FEES_PDF_URL = (
    f"{BASE_URL}/fileadmin/user_upload/Top_nav/Ueber-uns/Rechtsgrundlagen/"
    "260630_Geb%C3%BChrenverzeichnis_03-2026_G.pdf"
)
MONTH_DATE_RE = re.compile(
    rf"(\d{{1,2}})\.\s+({'|'.join(MONTHS)})\s+(\d{{4}})", re.IGNORECASE
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*€")
DURATION_RE = re.compile(r"([\d.]+)\s+Unterrichtseinheiten", re.IGNORECASE)
COURSE_NO_RE = re.compile(r"Kursnummer\s+(\S+)", re.IGNORECASE)

CHEMNITZ_TRADE_ALIASES = {
    "informationstechnik": "Informationstechniker",
    "elektrotechnik": "Elektrotechniker",
    "strassenbauer": "Straßenbauer",
    "straßenbauer": "Straßenbauer",
    "drechsler": "Drechsler",
    "baecker": "Bäcker",
    "bäcker": "Bäcker",
    "gold- und silberschmied": "Gold- und Silberschmiede",
}

GENERIC_EXAM_FEES = {1: 410.0, 2: 320.0, 3: 215.0, 4: 205.0}

SKIP_SLUGS = (
    "auffrischungskurs-mathematik-fuer-meisterschueler",
    "lernen-lernen-die-basis-fuer-eine-aufstiegsfortbildung",
    "pruefungsvorbereitung-auf-die-praktische-gesellenpruefung",
)


def _parse_month_date(text: str) -> str | None:
    match = MONTH_DATE_RE.search(text)
    if not match:
        return None
    month_key = match.group(2).lower()
    if month_key not in MONTHS:
        normalized = (
            month_key.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        )
        if normalized not in MONTHS:
            return None
        month_key = normalized
    return f"{match.group(3)}-{MONTHS[month_key]:02d}-{int(match.group(1)):02d}"


def parse_chemnitz_title(title: str) -> tuple[list[int], str | None]:
    lower = title.lower()
    if "ausbildung der ausbilder" in lower:
        return [4], None
    normalized = title.replace("kfm.", "kaufmännische")
    parts = parse_parts(normalized, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if not trade:
        trade = parse_trade(normalized, parts)
    if not trade:
        lower = title.lower()
        for source, canonical in CHEMNITZ_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
        if not trade:
            trade = parse_trade(re.sub(r"meister\b", " meister ", title, flags=re.I), parts)
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower or "keine plätze" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "plätze verfügbar" in lower or "wenige plätze" in lower:
        return "available"
    return "unknown"


def _parse_location(block: Tag) -> tuple[str, str, str]:
    text = block.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    street = ""
    zip_code = ""
    city = ""
    for index, line in enumerate(lines):
        zip_match = re.match(r"(\d{5})\s+(.+)", line)
        if zip_match:
            zip_code = zip_match.group(1)
            city = zip_match.group(2).strip()
            if index > 0:
                street = lines[index - 1]
            break
    return street, zip_code, city


class HwkChemnitzScraper(BaseScraper):
    chamber_slug = "hwk-chemnitz"
    chamber_name = "Handwerkskammer Chemnitz"
    chamber_region = "Sachsen"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 0.5

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        urls = self._discover_course_urls()
        offers: list[RawCourseOffer] = []
        for url in sorted(urls):
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("Could not fetch Chemnitz course %s.", url)
                continue
            try:
                parsed = self._parse_course_page(soup, url)
            except Exception as exc:
                logger.warning("Could not parse Chemnitz course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info("HWK Chemnitz: parsed %d offers from %d courses.", len(offers), len(urls))
        return offers

    def _discover_course_urls(self) -> set[str]:
        found: set[str] = set()
        for source_url in (PROGRAM_URL, OVERVIEW_URL):
            soup = self.parse_html(source_url)
            if soup is None:
                continue
            for link in soup.select('a[href*="/weiterbildung/kurs/"]'):
                href = link.get("href", "").split("#")[0]
                if not href or href.endswith(".pdf"):
                    continue
                slug = href.rstrip("/").split("/")[-1]
                if any(slug.startswith(prefix) for prefix in SKIP_SLUGS):
                    continue
                found.add(urljoin(BASE_URL, href))
        return found

    def _parse_course_page(self, soup: BeautifulSoup, url: str) -> list[RawCourseOffer]:
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        parts, trade = parse_chemnitz_title(title)
        if not parts:
            logger.debug("Skipping unknown Chemnitz title %r.", title)
            return []

        offers: list[RawCourseOffer] = []
        for block in soup.select("details[id^='termin_']"):
            offer = self._parse_termin(block, title, parts, trade, url)
            if offer:
                offers.append(offer)
        return offers

    def _parse_termin(
        self,
        block: Tag,
        page_title: str,
        parts: list[int],
        trade: str | None,
        url: str,
    ) -> RawCourseOffer | None:
        summary = block.select_one("summary")
        summary_text = summary.get_text(" ", strip=True) if summary else block.get_text(" ", strip=True)
        info_text = block.get_text("\n", strip=True)

        lower = summary_text.lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        teaching_mode = "presence"

        start_date = _parse_month_date(summary_text)
        end_date = None
        termin_match = re.search(
            r"Termin\s+(.+?)(?:\nHinweis|\nOrt|\Z)",
            info_text,
            re.DOTALL | re.IGNORECASE,
        )
        if termin_match:
            dates = MONTH_DATE_RE.findall(termin_match.group(1))
            if dates:
                start_date = _parse_month_date(
                    f"{dates[0][0]}. {dates[0][1]} {dates[0][2]}"
                )
                if len(dates) > 1:
                    end_date = _parse_month_date(
                        f"{dates[1][0]}. {dates[1][1]} {dates[1][2]}"
                    )
        if not end_date:
            end_match = re.search(r"\bbis\s+(.+)$", summary_text, re.IGNORECASE)
            if end_match:
                end_date = _parse_month_date(end_match.group(1))

        street, zip_code, city = _parse_location(block)
        if not city:
            city_match = re.search(r"\bin\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß -]+)\b", summary_text)
            city = city_match.group(1).strip() if city_match else "Chemnitz"

        duration_match = DURATION_RE.search(info_text)
        fee_match = re.search(r"Gebühr\s+([\d.]+),(\d{2})\s*€", info_text, re.IGNORECASE)
        number_match = COURSE_NO_RE.search(info_text)
        termin_id = block.get("id", "").replace("termin_", "")

        return RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=(
                int(duration_match.group(1).replace(".", "")) if duration_match else None
            ),
            course_fee=(
                float(fee_match.group(1).replace(".", "") + "." + fee_match.group(2))
                if fee_match else None
            ),
            city=city,
            street=street,
            zip_code=zip_code,
            availability=_availability(info_text),
            source_url=f"{url}#termin_{termin_id}" if termin_id else url,
            scraped_raw={"title": page_title, "course_no": number_match.group(1) if number_match else ""},
        )

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV")):
            match = re.search(
                rf"[a-d]\)\s*Teil\s+{roman}\s+([\d.]+)\s*€",
                text,
                re.IGNORECASE,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", ""))
        return fees

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Chemnitz: pypdf not installed — using fallback exam fees.")
            return {}

        response = self.get(FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Chemnitz: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Chemnitz: could not parse Meister exam fees from PDF.")
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
