"""Scraper for BBZ OWL Meister courses (HWK Ostwestfalen-Lippe zu Bielefeld)."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import RawCourseOffer
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

BASE_URL = "https://bbz.handwerk-owl.de"
CHAMBER_URL = "https://www.handwerk-owl.de"
LANDING_URL = f"{BASE_URL}/artikel/meisterin-werden-3351,0,59.html"
EXAM_FEES_PAGE_URL = f"{CHAMBER_URL}/artikel/beitraege-gebuehren-35,0,67.html"
FEES_PDF_URL = f"{CHAMBER_URL}/downloads/gebuehrentarif-2026-35,715.pdf"
GENERIC_EXAM_FEES = {
    1: {"fee": 380.0, "fee_max": 2450.0},
    2: {"fee": 250.0, "fee_max": 980.0},
    3: {"fee": 250.0, "fee_max": 980.0},
    4: {"fee": 250.0, "fee_max": 980.0},
}
# Tariff line (a): Teil I + Teile II/III/IV as one package — lower than summing I+II.
GENERIC_COMBO_EXAM_FEE = {"fee": 580.0, "fee_max": 3200.0}

OWL_HUB_ARTICLES = (
    "teile-iii-und-iv-3351,180,52.html",
)

OWL_SEARCH_TERMS = (
    "Meistervorbereitung",
    "Teil III",
    "Teil IV",
    "Betriebsführung",
    "AEVO",
    "Ausbildung der Ausbilder",
    "AdA",
)

OWL_TRADE_ARTICLES = (
    "elektrotechnik",
    "metallbau",
    "kfz",
    "friseure",
    "shk",
    "konditoren",
    "feinwerkmechanik",
)

OWL_TRADE_ALIASES = {
    "elektrotechnik": "Elektrotechniker",
    "metallbau": "Metallbauer",
    "kfz": "Kfz.-Techniker",
    "friseure": "Friseur",
    "shk": "Installateur- und Heizungsbauer",
    "konditoren": "Konditor",
    "feinwerkmechanik": "Feinwerkmechaniker",
}


def parse_owl_title(title: str, article_trade: str | None = None) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None

    trade = parse_trade(title, parts)
    if not trade and article_trade:
        trade = OWL_TRADE_ALIASES.get(article_trade.lower())
    if not trade:
        lower = title.lower()
        for source, canonical in OWL_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_card(title: str) -> bool:
    lower = title.lower()
    if "infoveranstaltung" in lower:
        return False
    if "meistervorbereitung" in lower or "meisterschule" in lower:
        return True
    if "fachmann" in lower and (
        "betriebsführung" in lower or "betriebsfuehrung" in lower
    ):
        return True
    if "ada" in lower and "ausbilder" in lower:
        return True
    if "ausbildereignung" in lower or (
        "ausbilder" in lower and ("aevo" in lower or "teil iv" in lower)
    ):
        return True
    parts = parse_parts(title, implicit_trade_parts=True)
    return bool(parts and set(parts) <= {3, 4})


def _card_text_scope(link: Tag, raw_title: str) -> str:
    """Return page text scoped to a single listing/run, not an entire course hub."""
    if "list-group-item" in (link.get("class") or []):
        return link.get_text("\n", strip=True)
    row = link.find_parent("div", class_="row")
    if row is not None:
        return row.get_text("\n", strip=True)
    li = link.find_parent("li")
    if li is not None:
        return li.get_text("\n", strip=True)
    return raw_title or link.get_text("\n", strip=True)


def _parse_schedule_from_title(raw_title: str) -> tuple[str | None, str | None, str | None]:
    """Parse ``DD.MM.YYYY - DD.MM.YYYY: Vollzeit/Teilzeit/Wochenende`` from link titles."""
    match = re.search(
        r"(\d{2}\.\d{2}\.\d{4}\s*-\s*\d{2}\.\d{2}\.\d{4})\s*:\s*"
        r"(Vollzeit|Teilzeit|Wochenende|Berufsbegleitend)",
        raw_title,
        re.IGNORECASE,
    )
    if not match:
        return None, None, None
    start_date, end_date = parse_dates(match.group(1))
    label = match.group(2).lower()
    format_key = "full_time" if label == "vollzeit" else "part_time"
    return start_date, end_date, format_key


SCHEDULE_LINE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})\s*:\s*"
    r"(Vollzeit|Teilzeit|Wochenende|Berufsbegleitend)",
    re.IGNORECASE,
)


def _format_from_schedule_line(text: str, start_date: str | None) -> str | None:
    """Match a detail-page schedule line to the listing start date."""
    if not start_date or not text:
        return None
    for match in SCHEDULE_LINE_RE.finditer(text):
        line_start = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        if line_start != start_date:
            continue
        label = match.group(7).lower()
        return "full_time" if label == "vollzeit" else "part_time"
    return None


def _card_key(card: dict) -> tuple:
    """Unique key for listing cards that share one detail page."""
    return (
        course_id_from_url(card["detail_url"]) or card["detail_url"],
        card.get("start_date"),
        card.get("end_date"),
        card.get("format_key"),
    )


class HwkOstwestfalenLippeZuBielefeldScraper(BavariaOdavScraper):
    chamber_slug = "hwk-ostwestfalen-lippe-zu-bielefeld"
    chamber_name = "Handwerkskammer Ostwestfalen-Lippe zu Bielefeld"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = CHAMBER_URL
    source_url = LANDING_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/3351,0,courselist.html?search-filter-template=0"
            "&limit={limit}&offset={offset}"
        ),
        default_city="Bielefeld",
        default_street="Herforder Straße 69",
        default_zip="33602",
        page_size=100,
        implicit_trade_parts=True,
    )

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        unique: dict[tuple, dict] = {}

        for term in OWL_SEARCH_TERMS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/3351,0,courselist.html?search-filter-template=0"
                    f"&search-searchterm={term}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK OWL listing failed for %r at offset %d.", term, offset)
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    unique[_card_key(card)] = card
                offset += self.catalogue.page_size
                if offset >= total:
                    break

        for list_url in self._discover_keyword_listings():
            offset = 0
            while True:
                sep = "&" if "?" in list_url else "?"
                url = (
                    f"{list_url}{sep}limit={self.catalogue.page_size}&offset={offset}"
                    if "offset=" not in list_url
                    else list_url
                )
                soup = self.parse_html(url)
                if soup is None:
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    unique[_card_key(card)] = card
                offset += self.catalogue.page_size
                if offset >= total or "offset=" in list_url:
                    break

        article_urls = self._discover_trade_articles()
        for article_url, article_trade in article_urls:
            article = self.parse_html(article_url)
            if article is None:
                logger.warning("Could not fetch OWL article %s.", article_url)
                continue
            for link in article.select("a[href*='coursedetail']"):
                href = link.get("href", "")
                if "id=" not in href:
                    continue
                raw_title = link.get_text(" ", strip=True)
                if not _is_meister_card(raw_title):
                    continue
                detail_url = canonical_detail_url(BASE_URL, href)
                card = self._parse_owl_card(
                    link, detail_url, raw_title=raw_title, article_trade=article_trade
                )
                if card:
                    unique[_card_key(card)] = card

        offers: list[RawCourseOffer] = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse OWL course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        logger.info("HWK OWL: parsed %d unique course offers.", len(offers))
        return offers

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards: list[dict] = []
        seen: set[tuple] = set()
        for link in soup.select("a[href*='coursedetail']"):
            detail_url = canonical_detail_url(self.catalogue.base_url, link.get("href", ""))
            if not detail_url:
                continue
            card = self._parse_owl_listing_card(link, detail_url)
            if not card:
                continue
            key = _card_key(card)
            if key in seen:
                continue
            seen.add(key)
            cards.append(card)
        return cards

    def _parse_owl_listing_card(self, link: Tag, detail_url: str) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        if not _is_meister_card(raw_title):
            return None
        return self._parse_owl_card(link, detail_url, raw_title=raw_title)

    def _discover_trade_articles(self) -> list[tuple[str, str]]:
        landing = self.parse_html(LANDING_URL)
        if landing is None:
            return []

        found: dict[str, str] = {}
        for slug in OWL_TRADE_ARTICLES:
            for link in landing.select(f"a[href*='{slug}-3351']"):
                href = urljoin(BASE_URL, link.get("href", ""))
                found[href] = slug

        for link in landing.select("a[href*='artikel/']"):
            href = link.get("href", "")
            title = link.get_text(" ", strip=True).lower()
            if "teile iii" in title or "teile-iii" in href.lower():
                found[urljoin(BASE_URL, href)] = "teile-iii-iv"

        weiterbildung = self.parse_html(f"{BASE_URL}/artikel/weiterbildung-im-handwerk-3351,0,53.html")
        if weiterbildung is not None:
            for link in weiterbildung.select("a[href*='artikel/']"):
                href = link.get("href", "")
                title = link.get_text(" ", strip=True).lower()
                for slug in OWL_TRADE_ARTICLES:
                    if slug in href.lower() or slug in title.replace(" ", ""):
                        found[urljoin(BASE_URL, href)] = slug
                if "teile iii" in title or "teile-iii" in href.lower():
                    found[urljoin(BASE_URL, href)] = "teile-iii-iv"

        for article_path in OWL_HUB_ARTICLES:
            found[urljoin(BASE_URL, f"/artikel/{article_path}")] = "teile-iii-iv"
        return [(url, trade) for url, trade in found.items()]

    def _discover_keyword_listings(self) -> list[str]:
        """Follow ``weitere Kurse`` keyword list links from Part III/IV hubs."""
        urls: list[str] = []
        for article_path in OWL_HUB_ARTICLES:
            article = self.parse_html(urljoin(BASE_URL, f"/artikel/{article_path}"))
            if article is None:
                continue
            for link in article.select("a[href*='courselist'][href*='search-keyword']"):
                href = urljoin(BASE_URL, link.get("href", ""))
                if href not in urls:
                    urls.append(href)
        return urls

    def _parse_owl_card(
        self,
        link: Tag,
        detail_url: str,
        *,
        raw_title: str = "",
        article_trade: str | None = None,
    ) -> dict | None:
        raw_title = raw_title or link.get_text(" ", strip=True)
        parts, trade_name = parse_owl_title(raw_title, article_trade)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            return None

        text = _card_text_scope(link, raw_title)
        title_start, title_end, title_format = _parse_schedule_from_title(raw_title)
        start_date, end_date = parse_dates(text)
        if title_start:
            start_date, end_date = title_start, title_end
        format_key, teaching_mode = parse_format_and_mode(f"{text} {raw_title}")
        if title_format:
            format_key = title_format
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

    def _enrich(self, card: dict) -> RawCourseOffer | list[RawCourseOffer] | None:
        listing_format = card.get("format_key")
        listing_teaching_mode = card.get("teaching_mode")
        listing_start = card.get("start_date")
        soup = self.parse_html(card["detail_url"]) if self.catalogue.details_required else None
        detail_format = None
        if soup is not None:
            h1 = soup.select_one("h1")
            detail_title = h1.get_text(" ", strip=True) if h1 else card["raw_title"]
            parts, trade_name = parse_owl_title(detail_title)
            if parts:
                card = {**card, "parts": parts}
            if trade_name:
                card = {**card, "trade_name": trade_name}
            main_text = (soup.select_one("main") or soup).get_text("\n", strip=True)
            detail_format = _format_from_schedule_line(main_text, listing_start)
        result = super()._enrich(card)
        resolved_format = listing_format or detail_format
        if result and resolved_format:
            for offer in (result if isinstance(result, list) else [result]):
                offer.format_key = resolved_format
                if listing_teaching_mode:
                    offer.teaching_mode = listing_teaching_mode
        return result

    def resolve_schedule_dates(
        self,
        soup: BeautifulSoup | None,
        card: dict,
        main_text: str,
    ) -> tuple[str | None, str | None, str]:
        if card.get("start_date"):
            return (
                card["start_date"],
                card.get("end_date"),
                card.get("start_date_note", ""),
            )
        return super().resolve_schedule_dates(soup, card, main_text)

    @staticmethod
    def _amount_pair(match: re.Match, low_group: int = 1) -> dict[str, float]:
        return {
            "fee": float(
                match.group(low_group).replace(".", "") + "." + match.group(low_group + 1)
            ),
            "fee_max": float(
                match.group(low_group + 2).replace(".", "") + "." + match.group(low_group + 3)
            ),
        }

    @classmethod
    def parse_meister_exam_fees(
        cls, text: str
    ) -> tuple[dict[int, dict[str, float]], dict[str, float] | None]:
        """
        Parse OWL Gebührentarif §5 Meisterprüfung.

        Returns ``(per_part_fees, combo_i_plus_theoretical)``.

        Line (a) covers Teil I together with Teile II/III/IV as one package and
        is preferred for Teile I+II courses over summing the individual lines.
        """
        fees: dict[int, dict[str, float]] = {}
        combo: dict[str, float] | None = None
        section = re.search(
            r"5\.\s*Meisterprüfung(.*?)6\.\s*Fortbildungsprüfung",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        chunk = section.group(1) if section else text

        package = re.search(
            r"Teil I \(praktischer Teil\) und Teil II, III oder IV\s*"
            r"\(theoretische Teile\)\s+"
            r"([\d.]+),(\d{2})\s+bis\s+([\d.]+),(\d{2})\s+Euro",
            chunk,
            re.IGNORECASE,
        )
        if package:
            combo = cls._amount_pair(package)

        part_i = re.search(
            r"Teil I \(praktischer Teil\)\s+([\d.]+),(\d{2})\s+bis\s+([\d.]+),(\d{2})\s+Euro",
            chunk,
            re.IGNORECASE,
        )
        if part_i:
            fees[1] = cls._amount_pair(part_i)

        generic = re.search(
            r"Teil II, III oder IV \(theoretische Teile\)\s+"
            r"([\d.]+),(\d{2})\s+bis\s+([\d.]+),(\d{2})\s+Euro",
            chunk,
            re.IGNORECASE,
        )
        if generic:
            values = cls._amount_pair(generic)
            for part in (2, 3, 4):
                fees[part] = dict(values)
        return fees, combo

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrentarif'], a[href*='gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf") and "gebuehrentarif" in href.lower():
                return urljoin(CHAMBER_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(
        self,
    ) -> tuple[dict[int, dict[str, float]], dict[str, float] | None] | None:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK OWL: pypdf not installed — using fallback exam fees.")
            return None

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK OWL: could not fetch exam-fee PDF.")
            return None

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees, combo = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK OWL: could not parse Meister exam fee ranges from PDF.")
            return None
        return fees, combo


    def published_exam_fee_rows(self) -> list[dict]:
        fetched = self._fetch_exam_fees_from_pdf()
        if fetched:
            fees, combo = fetched
        else:
            fees, combo = GENERIC_EXAM_FEES, GENERIC_COMBO_EXAM_FEE
        if not fees:
            fees, combo = GENERIC_EXAM_FEES, GENERIC_COMBO_EXAM_FEE
        if combo is None:
            combo = GENERIC_COMBO_EXAM_FEE

        rows: list[dict] = []
        for part, values in fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": values["fee"],
                "fee_max": values.get("fee_max"),
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        # Prefer the package fee for Teile I+II (and full I–IV) over summing parts.
        for parts in ([1, 2], [1, 2, 3, 4]):
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "parts": parts,
                "fee": combo["fee"],
                "fee_max": combo.get("fee_max"),
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            })
        return rows
