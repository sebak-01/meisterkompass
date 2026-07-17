"""Scraper for HWK Braunschweig-Lüneburg-Stade's ODAV Meister course catalogue."""

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

BASE_URL = "https://weiterbildung.hwk-bls.de"
SOURCE_URL = f"{BASE_URL}/artikel/meistervorbereitung-22,0,263.html"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/artikel/meisterpruefung-im-handwerk-22,609,1093.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehrenuebersicht-meisterpruefungen-der-handwerkskammer-"
    "braunschweig-lueneburg-stade-pdf-22,2045.pdf"
)
GENERIC_EXAM_FEES = {2: 590.0, 3: 690.0, 4: 590.0}

BLS_TRADE_ALIASES = {
    "kraftfahrzeugtechnikerhandwerk": "Kfz.-Techniker",
    "installateur- und heizungsbauerhandwerk": "Installateur- und Heizungsbauer",
    "installateur und heizungsbauerhandwerk": "Installateur- und Heizungsbauer",
    "land- und baumaschinenmechatroniker-handwerk": "Land- und Baumaschinenmechatroniker",
    "landmaschinenmechatroniker": "Land- und Baumaschinenmechatroniker",
    "maurer und betonbauer-handwerk": "Maurer und Betonbauer",
    "maurer- und betonbauer-handwerk": "Maurer und Betonbauer",
    "karosserie- und fahrzeugbauer": "Karosserie- und Fahrzeugbauer",
    "maler- und lackierer": "Maler und Lackierer",
    "fliesenleger": "Fliesen-, Platten- und Mosaikleger",
    "steinmetz und steinbildhauer": "Steinmetz und Steinbildhauer",
}


def parse_bls_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None

    contexts = (
        title,
        title.replace("Meistervorbereitung im", "Meister Meistervorbereitung im"),
        f"Meister {title}",
    )
    trade = None
    for context in contexts:
        trade = parse_trade(context, parts)
        if trade:
            break

    if not trade:
        lower = title.lower()
        for source, canonical in BLS_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _format_from_titles(*titles: str) -> str | None:
    for title in titles:
        lower = title.lower()
        if "teilzeit" in lower or "berufsbegleitend" in lower:
            return "part_time"
        if "vollzeit" in lower:
            return "full_time"
    return None


class HwkBraunschweigLueneburgStadeScraper(BavariaOdavScraper):
    chamber_slug = "hwk-braunschweig-lueneburg-stade"
    chamber_name = "Handwerkskammer Braunschweig-Lüneburg-Stade"
    chamber_region = "Niedersachsen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/22,0,courselist.html?search-filter-template=0"
            "&search-searchterm=Meistervorbereitung&limit={limit}&offset={offset}"
        ),
        default_city="Braunschweig",
        default_street="Falkenbergstraße 28",
        default_zip="38108",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[str, dict] = {}
        offset = 0
        while True:
            url = (
                f"{BASE_URL}/22,0,courselist.html?search-filter-template=0"
                f"&search-searchterm=Meistervorbereitung&limit={self.catalogue.page_size}"
                f"&offset={offset}"
            )
            soup = self.parse_html(url)
            if soup is None:
                logger.warning("HWK BLS listing failed at offset %d.", offset)
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
                logger.warning("Could not parse BLS course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK Braunschweig-Lüneburg-Stade: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        parts, trade_name = parse_bls_title(raw_title)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping non-Meister or unknown title %r", raw_title)
            return None

        row = link.find_parent("div", class_="row")
        heading = link.find_parent("h3")
        text = row.get_text("\n", strip=True) if row else raw_title
        heading_text = heading.get_text(" ", strip=True) if heading else text
        start_date, end_date = parse_dates(heading_text)
        format_key = _format_from_titles(raw_title, heading_text) or parse_format_and_mode(
            f"{heading_text} {raw_title}"
        )[0]
        teaching_mode = parse_format_and_mode(f"{heading_text} {raw_title}")[1]
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
            parts, trade_name = parse_bls_title(detail_title)
            if parts:
                card = {**card, "parts": parts}
            if trade_name:
                card = {**card, "trade_name": trade_name}
        return super()._enrich(card)

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        format_key = _format_from_titles(
            offer.scraped_raw.get("title", ""),
            offer.scraped_raw.get("card_text", ""),
        )
        if format_key:
            offer.format_key = format_key
        return offer

    @staticmethod
    def parse_part_i_exam_fees(text: str) -> dict[str, float]:
        fees: dict[str, float] = {}
        block_match = re.search(
            r"Meisterprüfung Teil 1(.*?)(?:Art der Meisterprüfung|Teil II)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not block_match:
            return fees
        for match in re.finditer(
            r"^([A-Za-zÄÖÜäöüß\- ]+?)\s+([\d.]+),(\d{2})\s*€",
            block_match.group(1),
            re.MULTILINE,
        ):
            label = match.group(1).strip()
            if label.lower().startswith(("rahmen", "gebühr", "max")):
                continue
            amount = float(match.group(2).replace(".", "") + "." + match.group(3))
            lower = label.lower()
            for source, canonical in BLS_TRADE_ALIASES.items():
                if source.split("-")[0] in lower or source.replace("-", " ") in lower:
                    fees[canonical] = amount
                    break
            else:
                trade = parse_trade(f"Meister {label}", [1])
                if trade:
                    fees[trade] = amount
        return fees

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, pattern in (
            (2, r"Teil\s+II\s+([\d.]+),(\d{2})\s*€"),
            (3, r"Teil\s+III\s+([\d.]+),(\d{2})\s*€"),
            (4, r"Teil\s+IV\s+([\d.]+),(\d{2})\s*€"),
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrenuebersicht-meisterpruefungen']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> tuple[dict[str, float], dict[int, float]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK BLS: pypdf not installed — using fallback exam fees.")
            return {}, {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK BLS: could not fetch exam-fee PDF.")
            return {}, {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        part_i_fees = self.parse_part_i_exam_fees(text)
        generic_fees = self.parse_generic_exam_fees(text) or GENERIC_EXAM_FEES
        if not part_i_fees:
            logger.warning("HWK BLS: could not parse trade-specific Teil-I exam fees from PDF.")
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
