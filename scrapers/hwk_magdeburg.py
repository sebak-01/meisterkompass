"""Scraper for HWK Magdeburg's ODAV Meister course catalogues."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import Tag

from .base import RawCourseOffer, ScrapeResult, normalize_trade
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    DATE_RE,
    MONTH_DATE_RE,
    NUMERIC_MONTH_RE,
    TENTATIVE_DATE_NOTE,
    canonical_detail_url,
    course_id_from_url,
    parse_dates_with_note,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    parse_availability,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-magdeburg.de"
LANDING_URL = (
    f"{BASE_URL}/artikel/hier-werden-sie-meister-ihres-fachs-16,1155,7480.html"
)
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehren-und-entgeltordnung-der-handwerkskammer-magdeburg-2026-16,5916.pdf"
)

MAG_TRADE_FEES_FALLBACK = {
    "Elektrotechniker": {1: 625.0, 2: 230.0},
    "Friseur": {1: 335.0, 2: 195.0},
    "Installateur- und Heizungsbauer": {1: 650.0, 2: 240.0},
    "Maler und Lackierer": {1: 690.0, 2: 235.0},
    "Maurer und Betonbauer": {1: 505.0, 2: 270.0},
    "Metallbauer": {1: 380.0, 2: 210.0},
    "Tischler": {1: 570.0, 2: 295.0},
    "Gerüstbauer": {1: 350.0, 2: 235.0},
}
GENERIC_EXAM_FEES = {3: 250.0, 4: 240.0}

CARD_PREFIX_RE = re.compile(
    r"^.*?(?=\d{2}\.\d{2}\.\d{4}|[A-Za-zÄÖÜäöü]+\s+\d{4})",
    re.DOTALL,
)


def _clean_card_title(raw_title: str) -> str:
    cleaned = CARD_PREFIX_RE.sub("", raw_title, count=1).strip(" :\u00a0")
    return cleaned or raw_title


class HwkMagdeburgScraper(BavariaOdavScraper):
    chamber_slug = "hwk-magdeburg"
    chamber_name = "Handwerkskammer Magdeburg"
    chamber_region = "Sachsen-Anhalt"
    chamber_website = BASE_URL
    source_url = LANDING_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/16,0,courselist.html?search-filter-template=0"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Magdeburg",
        default_street="Gareisstraße 10",
        default_zip="39106",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        landing = self.parse_html(LANDING_URL)
        if landing is None:
            logger.error("Could not fetch HWK Magdeburg landing page.")
            return []

        unique: dict[str, dict] = {}
        for link in landing.select("a"):
            if link.get_text(" ", strip=True).lower() != "mehr lesen":
                continue
            article_url = urljoin(BASE_URL, link.get("href", ""))
            article = self.parse_html(article_url)
            if article is None:
                logger.warning("Could not fetch Magdeburg article %s.", article_url)
                continue
            article_title = ""
            h1 = article.select_one("h1")
            if h1 is not None:
                article_title = h1.get_text(" ", strip=True)

            for course_link in article.select("a[href*='coursedetail']"):
                href = course_link.get("href", "")
                if "id=" not in href:
                    continue
                detail_url = canonical_detail_url(BASE_URL, href)
                course_id = course_id_from_url(detail_url)
                if not course_id:
                    continue
                card = self._parse_magdeburg_card(
                    course_link, detail_url, article_title=article_title
                )
                if card:
                    unique[course_id] = card

        offers: list[RawCourseOffer] = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Magdeburg course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Magdeburg: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_magdeburg_card(
        self,
        link: Tag,
        detail_url: str,
        *,
        article_title: str = "",
    ) -> dict | None:
        raw_title = _clean_card_title(link.get_text(" ", strip=True))
        context = f"{article_title} {raw_title}".strip()
        parts = parse_parts(context, implicit_trade_parts=self.catalogue.implicit_trade_parts)
        trade_name = parse_trade(context, parts)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping non-Meister or unknown Magdeburg title %r.", context)
            return None

        row = link.find_parent("div", class_="row")
        text = row.get_text("\n", strip=True) if row else raw_title
        start_date, end_date, start_date_note = parse_dates_with_note(text)
        format_key, teaching_mode = parse_format_and_mode(f"{text} {raw_title}")
        duration = DURATION_RE.search(text)
        return {
            "raw_title": raw_title,
            "parts": parts,
            "trade_name": trade_name,
            "start_date": start_date,
            "end_date": end_date,
            "start_date_note": start_date_note,
            "format_key": format_key,
            "teaching_mode": teaching_mode,
            "duration_hours": int(duration.group(1).replace(".", "")) if duration else None,
            "course_fee": parse_euro(text),
            "availability": parse_availability(text),
            "detail_url": detail_url,
            "card_text": text[:1000],
        }

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        return offer

    def resolve_schedule_dates(
        self,
        soup,
        card: dict,
        main_text: str,
    ) -> tuple[str | None, str | None, str]:
        """Prefer MM.YYYY course windows over Anmeldeschluss or other exact dates."""
        month_range = re.search(
            r"(\d{2})\.(\d{4})\s*[-–]\s*(\d{2})\.(\d{4})",
            main_text,
        )
        if month_range:
            start_month, start_year, end_month, end_year = month_range.groups()
            return (
                f"{start_year}-{start_month}-01",
                f"{end_year}-{end_month}-01",
                TENTATIVE_DATE_NOTE,
            )

        schedule_text = re.sub(
            r"Anmeldeschluss\s*\n?\s*\d{2}\.\d{2}\.\d{4}",
            "",
            main_text,
            count=1,
            flags=re.IGNORECASE,
        )
        alle_termine = re.search(r"\nAlle Termine\b", schedule_text, re.IGNORECASE)
        if alle_termine:
            schedule_text = schedule_text[:alle_termine.start()]
        return parse_dates_with_note(schedule_text)

    @staticmethod
    def parse_trade_exam_fees(text: str) -> dict[str, dict[int, float]]:
        section_trades = {
            "1": "Elektrotechniker",
            "2": "Friseur",
            "3": "Installateur- und Heizungsbauer",
            "4": "Maler und Lackierer",
            "5": "Maurer und Betonbauer",
            "6": "Metallbauer",
            "7": "Tischler",
            "8": "Gerüstbauer",
        }
        fees: dict[str, dict[int, float]] = {}
        for section, trade_name in section_trades.items():
            part_fees: dict[int, float] = {}
            for part, suffix in ((1, "1"), (2, "2")):
                match = re.search(
                    rf"2\.{section}\.{suffix}\.\s*Teil\s+{['I', 'II'][part - 1]}\s+"
                    rf"([\d.]+),(\d{{2}})",
                    text,
                    re.IGNORECASE,
                )
                if match:
                    part_fees[part] = float(
                        match.group(1).replace(".", "") + "." + match.group(2)
                    )
            if part_fees:
                fees[trade_name] = part_fees
        return fees

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, pattern in (
            (3, r"2\.9\.\s*Teil\s+III\s+([\d.]+),(\d{2})"),
            (4, r"2\.10\.\s*Teil\s+IV\s+([\d.]+),(\d{2})"),
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _fetch_exam_fees_from_pdf(self) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Magdeburg: pypdf not installed — using fallback exam fees.")
            return {}, {}

        response = self.get(FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Magdeburg: could not fetch exam-fee PDF.")
            return {}, {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        trade_fees = self.parse_trade_exam_fees(text)
        generic_fees = self.parse_generic_exam_fees(text)
        if not trade_fees:
            logger.warning("HWK Magdeburg: could not parse trade-specific exam fees from PDF.")
        if not generic_fees:
            logger.warning("HWK Magdeburg: could not parse generic Teil III/IV exam fees from PDF.")
        return trade_fees, generic_fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        trade_fees, generic_fees = self._fetch_exam_fees_from_pdf()
        if not trade_fees:
            trade_fees = MAG_TRADE_FEES_FALLBACK
        if not generic_fees:
            generic_fees = GENERIC_EXAM_FEES

        rows: list[dict] = []
        for trade_name, parts in trade_fees.items():
            trade_slug = normalize_trade(trade_name)[0]
            for part, fee in parts.items():
                rows.append({
                    "chamber_slug": self.chamber_slug,
                    "trade_slug": trade_slug,
                    "part": part,
                    "fee": fee,
                    "qualifier": "",
                    "source_url": FEES_PDF_URL,
                })
        for part, fee in generic_fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": FEES_PDF_URL,
            })
        return rows
