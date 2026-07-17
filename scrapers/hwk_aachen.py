"""Scraper for HWK Aachen's ODAV Meister course catalogues."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import Tag

from .base import RawCourseOffer, ScrapeResult, normalize_trade
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    canonical_detail_url,
    course_id_from_url,
    parse_availability,
    parse_dates,
    parse_euro,
    parse_format_and_mode,
    parse_parts,
    parse_trade,
    DURATION_RE,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-aachen.de"
LANDING_URL = f"{BASE_URL}/artikel/meisterschulen-kurse-33,0,244.html"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/meisterpruefung-33,0,55.html"
FEES_PDF_URL = f"{BASE_URL}/downloads/gebuehrenverzeichnis-handwerkskammer-aachen-33,4332.pdf"
SEARCH_TERMS = ("Meisterschule", "Meistervorbereitung", "Teil I", "Teil II", "Teil III")
GENERIC_EXAM_FEES = {3: 250.0, 4: 240.0}


def parse_aachen_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if not trade:
        trade = parse_trade(title.replace("Meisterschule", "Meister Meisterschule"), parts)
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_card(title: str, href: str) -> bool:
    lower = f"{title} {href}".lower()
    if any(value in lower for value in (
        "infoveranstaltung", "infotag", "infoabend", "schnupperstudium", "aevo",
        "gestalter im handwerk", "asbest-sachkunde", "schmiedetechnik",
        "kommunikations- und präsentationstechniken", "betriebswirt",
        "geprüfte/r betriebswirt",
    )):
        return False
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return False
    if set(parts) <= {3, 4}:
        return "teil iii" in lower or "teil iv" in lower or "betriebswirtschaft" in lower
    _, trade = parse_aachen_title(title)
    return trade is not None


class HwkAachenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-aachen"
    chamber_name = "Handwerkskammer Aachen"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = BASE_URL
    source_url = LANDING_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/33,0,courselist.html?search-filter-template=0"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Aachen",
        default_street="Sandkaulbach 21",
        default_zip="52062",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[str, dict] = {}

        landing = self.parse_html(LANDING_URL)
        if landing is not None:
            for link in landing.select(
                "a.list-group-item[href*='coursedetail'], a[href*='coursedetail']"
            ):
                href = link.get("href", "")
                if "id=" not in href:
                    continue
                raw_title = link.get_text(" ", strip=True)
                if not _is_meister_card(raw_title, href):
                    continue
                detail_url = canonical_detail_url(BASE_URL, href)
                course_id = course_id_from_url(detail_url)
                if not course_id:
                    continue
                card = self._parse_aachen_card(link, detail_url, raw_title=raw_title)
                if card:
                    unique[course_id] = card

        for term in SEARCH_TERMS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/33,0,courselist.html?search-filter-template=0"
                    f"&search-searchterm={term}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK Aachen listing failed for %r at offset %d.", term, offset)
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    key = course_id_from_url(card["detail_url"]) or card["detail_url"]
                    unique[key] = card
                offset += self.catalogue.page_size
                if offset >= total:
                    break

        offers: list[RawCourseOffer] = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Aachen course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Aachen: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        if not _is_meister_card(raw_title, link.get("href", "")):
            logger.debug("Skipping non-Meister Aachen title %r", raw_title)
            return None
        return self._parse_aachen_card(
            link,
            detail_url or canonical_detail_url(self.catalogue.base_url, link.get("href", "")),
            raw_title=raw_title,
        )

    def _parse_aachen_card(
        self,
        link: Tag,
        detail_url: str,
        *,
        raw_title: str = "",
    ) -> dict | None:
        raw_title = raw_title or link.get_text(" ", strip=True)
        parts, trade_name = parse_aachen_title(raw_title)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            return None

        row = link.find_parent("div", class_="row") or link.find_parent("li")
        text = row.get_text("\n", strip=True) if row else raw_title
        start_date, end_date = parse_dates(text)
        format_key, teaching_mode = parse_format_and_mode(f"{text} {raw_title}")
        duration = DURATION_RE.search(text)
        return {
            "raw_title": raw_title,
            "parts": parts,
            "trade_name": trade_name,
            "start_date": start_date,
            "end_date": end_date,
            "format_key": format_key,
            "teaching_mode": teaching_mode,
            "duration_hours": int(duration.group(1).replace(".", "")) if duration else None,
            "course_fee": parse_euro(text),
            "availability": parse_availability(text),
            "detail_url": detail_url,
            "card_text": text[:1000],
        }

    @staticmethod
    def parse_trade_exam_fees(text: str) -> dict[str, dict[int, float]]:
        fees: dict[str, dict[int, float]] = {}
        for match in re.finditer(
            r"([A-Za-zÄÖÜäöüß\-,/ ]+?)\s+Teil\s+I\s+([\d.]+),(\d{2})\s*€",
            text,
            re.IGNORECASE,
        ):
            trade = parse_trade(f"Meister {match.group(1).strip()}", [1])
            if trade:
                fees.setdefault(trade, {})[1] = float(
                    match.group(2).replace(".", "") + "." + match.group(3)
                )
        return fees

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, roman in ((2, "II"), (3, "III"), (4, "IV")):
            match = re.search(
                rf"Teil\s+{roman}\s+([\d.]+),(\d{{2}})\s*€",
                text,
                re.IGNORECASE,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrenverzeichnis'], a[href*='gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Aachen: pypdf not installed — using fallback exam fees.")
            return {}, {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Aachen: could not fetch exam-fee PDF.")
            return {}, {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        trade_fees = self.parse_trade_exam_fees(text)
        generic_fees = self.parse_generic_exam_fees(text) or GENERIC_EXAM_FEES
        return trade_fees, generic_fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        trade_fees, generic_fees = self._fetch_exam_fees_from_pdf()
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
                    "source_url": EXAM_FEES_PAGE_URL,
                })
        for part, fee in generic_fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        return rows
