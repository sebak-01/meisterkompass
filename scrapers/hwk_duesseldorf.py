"""Scraper for HWK Düsseldorf's ODAV Meister course catalogues."""

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

BASE_URL = "https://www.hwk-duesseldorf.de"
SOURCE_URL = f"{BASE_URL}/artikel/meisterschulen-31,0,113.html"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/meisterpruefungen-im-handwerk-31,0,643.html"
FEES_PDF_URL = f"{BASE_URL}/downloads/gebuehrentarif-beschluss-vom-20-11-2025-31,4332.pdf"
SEARCH_TERMS = (
    "Meisterschule",
    "Meistervorbereitung",
    "Teil I",
    "Teil II",
    "Teil III",
    "Teil IV",
)
GENERIC_EXAM_FEES = {2: 380.0, 3: 280.0, 4: 220.0}

DUS_TRADE_ALIASES = {
    "fleischer/in": "Fleischer",
    "friseur/in": "Friseur",
    "kfz-techniker/in": "Kfz.-Techniker",
    "orthopädieschuhmacher/in": "Orthopädieschuhmacher",
    "graveur/in": "Graveur",
    "dachdecker/in": "Dachdecker",
    "maler/in und lackierer/in": "Maler und Lackierer",
    "tischler/in": "Tischler",
    "feinwerkmechaniker/in": "Feinwerkmechaniker",
    "metallbauer/in": "Metallbauer",
    "elektrotechniker/in": "Elektrotechniker",
    "installateur/in und heizungsbauer/in": "Installateur- und Heizungsbauer",
    "maurer/in und betonbauer/in": "Maurer und Betonbauer",
    "land- und baumaschinenmechatroniker/in": "Land- und Baumaschinenmechatroniker",
    "zimmerer/in": "Zimmerer",
    "fliesen-, platten- und mosaikleger/in": "Fliesen-, Platten- und Mosaikleger",
    "karosserie- u. fahrzeugbauer/in": "Karosserie- und Fahrzeugbauer",
    "bäcker/in": "Bäcker",
    "baecker/in": "Bäcker",
    "konditor/in": "Konditor",
    "zahntechniker/in": "Zahntechniker",
    "gold- und silberschmied/in": "Gold- und Silberschmiede",
    "uhrmacher/in": "Uhrmacher",
    "ofen- und luftheizungsbauer/in": "Ofen- und Luftheizungsbauer",
    "fahrzeuglackierer/in": "Fahrzeuglackierer",
    "gebäudereiniger/in": "Gebäudereiniger",
    "gebaeudereiniger/in": "Gebäudereiniger",
}

PARTS_PAREN_RE = re.compile(
    r"\((I(?:\+II)?(?:\+III)?(?:\+IV)?|II(?:\+III)?(?:\+IV)?|III(?:\+IV)?|IV)\)",
    re.IGNORECASE,
)


def _normalize_dus_title(title: str) -> str:
    def _replace(match: re.Match) -> str:
        tokens = re.split(r"\+", match.group(1).upper())
        return "Teile " + " und ".join(tokens)

    return PARTS_PAREN_RE.sub(_replace, title)


def parse_duesseldorf_title(title: str) -> tuple[list[int], str | None]:
    normalized = _normalize_dus_title(title)
    parts = parse_parts(normalized, implicit_trade_parts=True)
    if not parts:
        return [], None

    trade = parse_trade(normalized, parts)
    if not trade:
        trade = parse_trade(f"Meister {normalized}", parts)

    if not trade:
        lower = normalized.lower()
        for source, canonical in DUS_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
        if not trade:
            head = re.split(r"\s*\(", normalized, maxsplit=1)[0].strip(" /")
            trade = parse_trade(f"Meister {head}", parts)

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_listing(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in (
        "infoveranstaltung", "informationsveranstaltung", "infoabend",
        "kombinationslehrgang", "wahlmodul", "gebäudeenergieberater",
        "sachkundenachweis", "elektrofachkraft", "schweißfachmann",
        "auffrischungskurs", "grundkurs", "ausbildereignung",
    )):
        return False
    parts = parse_parts(_normalize_dus_title(title), implicit_trade_parts=True)
    if not parts:
        return False
    if set(parts) <= {3, 4}:
        return True
    _, trade = parse_duesseldorf_title(title)
    return trade is not None


class HwkDuesseldorfScraper(BavariaOdavScraper):
    chamber_slug = "hwk-duesseldorf"
    chamber_name = "Handwerkskammer Düsseldorf"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/31,0,courselist.html?search-filter-template=0"
            "&search-searchterm={{term}}&limit={{limit}}&offset={{offset}}"
        ),
        default_city="Düsseldorf",
        default_street="Georg-Schneider-Platz 1",
        default_zip="40212",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[str, dict] = {}
        for term in SEARCH_TERMS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/31,0,courselist.html?search-filter-template=0"
                    f"&search-searchterm={term}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK Düsseldorf listing failed for %r at offset %d.", term, offset)
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
                logger.warning("Could not parse Düsseldorf course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Düsseldorf: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        if not _is_meister_listing(raw_title):
            logger.debug("Skipping non-Meister Düsseldorf title %r", raw_title)
            return None

        parts, trade_name = parse_duesseldorf_title(raw_title)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping unknown Düsseldorf title %r", raw_title)
            return None

        row = link.find_parent("div", class_="row")
        heading = link.find_parent("h3")
        text = row.get_text("\n", strip=True) if row else raw_title
        heading_text = heading.get_text(" ", strip=True) if heading else text
        start_date, end_date = parse_dates(heading_text)
        format_key, teaching_mode = parse_format_and_mode(f"{heading_text} {raw_title}")
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
            "detail_url": detail_url or canonical_detail_url(
                self.catalogue.base_url, link.get("href", "")
            ),
            "card_text": text[:1000],
        }

    def _enrich(self, card: dict) -> RawCourseOffer | list[RawCourseOffer] | None:
        soup = self.parse_html(card["detail_url"]) if self.catalogue.details_required else None
        if soup is not None:
            h1 = soup.select_one("h1")
            detail_title = h1.get_text(" ", strip=True) if h1 else card["raw_title"]
            parts, trade_name = parse_duesseldorf_title(detail_title)
            if parts:
                card = {**card, "parts": parts}
            if trade_name:
                card = {**card, "trade_name": trade_name}
        return super()._enrich(card)

    @staticmethod
    def parse_part_i_exam_fees(text: str) -> dict[str, float]:
        fees: dict[str, float] = {}
        for match in re.finditer(
            r"^([A-Za-zÄÖÜäöüß\-,/ ]+?)/in\s+([\d.]+),(\d{2})\s*€",
            text,
            re.MULTILINE,
        ):
            label = match.group(1).strip(" -")
            amount = float(match.group(2).replace(".", "") + "." + match.group(3))
            trade = parse_trade(f"Meister {label}", [1])
            if trade:
                fees[trade] = amount
        return fees

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (2, r"Teil\s+II(?:\s+der\s+Meisterprüfung)?.*?([\d.]+),(\d{2})\s*€"),
            (3, r"Teil\s+III(?:\s+der\s+Meisterprüfung)?.*?([\d.]+),(\d{2})\s*€"),
            (4, r"Teil\s+IV(?:\s+der\s+Meisterprüfung)?.*?([\d.]+),(\d{2})\s*€"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrentarif'], a[href*='gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> tuple[dict[str, float], dict[int, float]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Düsseldorf: pypdf not installed — using fallback exam fees.")
            return {}, {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Düsseldorf: could not fetch exam-fee PDF.")
            return {}, {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        part_i_fees = self.parse_part_i_exam_fees(text)
        generic_fees = self.parse_generic_exam_fees(text) or GENERIC_EXAM_FEES
        return part_i_fees, generic_fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        part_i_fees, generic_fees = self._fetch_exam_fees_from_pdf()
        rows: list[dict] = []
        for trade_name, fee in part_i_fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": normalize_trade(trade_name)[0],
                "part": 1,
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
