"""Scraper for HWK Bremen Meistervorbereitungslehrgänge.

Primary source: universal KDB bulk feed (scheduled runs with dates/fees).
Secondary source: handwerkbremen.de Meisterkurs overview pages — used as
dateless placeholders when the KDB feed has no published run yet (e.g.
Elektrotechnik Teilzeit).
"""

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title, normalize_trade
from .hwk_bayern import parse_format_and_mode
from .hwk_universal_kdb import build_kdb_detail_url, parse_kdb_availability

logger = logging.getLogger(__name__)

KDB_URL = "https://www.hwk-universal.de/universal-kdb-rest/v1/vorlagen/hwb"
SOURCE_URL = "https://www.handwerkbremen.de/service-center/kurse-und-seminare#/"
MEISTERKURSE_BASE = "https://www.handwerkbremen.de"
MEISTERKURSE_OVERVIEW = f"{MEISTERKURSE_BASE}/meister-in/meisterkurse"

DEFAULT_STREET = "Schongauerstr. 2"
DEFAULT_ZIP = "28219"
DEFAULT_CITY = "Bremen"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
MEISTER_PATTERN = re.compile(r"(?:Meisterprüfung|Handwerksmeister)\s+Teile?\b", re.IGNORECASE)
BERUFSSPEZIALIST_PATTERN = re.compile(
    r"berufsspezialist|servicetechnik",
    re.IGNORECASE,
)
PARTS_PATTERN = re.compile(
    r"(?:Teile?|Meisterprüfung)\s+((?:IV|III|II|I)(?:\s*(?:\+|und|,)\s*(?:IV|III|II|I))*)",
    re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"(\d[\d.]*)(?:,(\d{2}))?")
FORMAT_MAP = {"vollzeit": "full_time", "teilzeit": "part_time"}
DURATION_HOURS_RE = re.compile(
    r"ca\.?\s*\d+\s*Monate;\s*ca\.?\s*(\d[\d.]*)\s*Unterrichtsstunden",
    re.IGNORECASE,
)

# KDB titles abbreviate some trades; exam fees in Gebührentarif use the full names.
TRADE_ALIASES = {
    "Bau": "Maurer und Betonbauer",
    "Maler": "Maler und Lackierer",
    "Elektrotechnik": "Elektrotechniker",
    "Installateur- und Heizungsbau": "Installateur und Heizungsbauer",
    "KFZ-Techniker": "Kfz.-Techniker",
    "Kraftfahrzeugtechnik": "Kfz.-Techniker",
}

# Fallback when the page title is generic but the URL slug is explicit.
URL_TRADE_ALIASES = {
    "elektrotechnik": "Elektrotechniker",
    "maler": "Maler und Lackierer",
    "maurer-und-betonbauer": "Maurer und Betonbauer",
    "installateur-und-heizungsbauer": "Installateur und Heizungsbauer",
    "tischler": "Tischler",
    "zimmerer": "Zimmerer",
    "kraftfahrzeugtechnik": "Kfz.-Techniker",
}


KFZ_TRADE_NAME = "Kfz.-Techniker"


def resolve_trade_name(trade_name: str | None) -> str | None:
    if not trade_name:
        return None
    return TRADE_ALIASES.get(trade_name, trade_name)


def is_berufsspezialist_course(*texts: str | None) -> bool:
    combined = " ".join(text for text in texts if text)
    return bool(BERUFSSPEZIALIST_PATTERN.search(combined))


def normalize_course_metadata(
    titel: str,
    abschluss: str,
    url: str,
    trade_name: str | None,
    parts: list[int],
) -> tuple[str | None, list[int]]:
    """Present Berufsspezialist Kfz-Servicetechnik as Kfz.-Techniker (Teil I)."""
    if is_berufsspezialist_course(titel, abschluss, url):
        return KFZ_TRADE_NAME, [1]
    return trade_name, parts


def parse_parts(titel: str, abschluss: str) -> list[int]:
    for source in (titel, abschluss):
        match = PARTS_PATTERN.search(source or "")
        if not match:
            continue
        parts = {
            ROMAN[token.strip().upper()]
            for token in re.split(r"\s*(?:\+|und|,)\s*", match.group(1))
            if token.strip().upper() in ROMAN
        }
        if parts:
            return sorted(parts)
    return []


def parse_trade(titel: str) -> str | None:
    text = titel or ""
    text = re.sub(r"^\s*\w+\s*-\s*", "", text)
    text = re.sub(r"^\s*Online\s*-\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:MV|Meistervorbereitung)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bim\b", "", text, flags=re.IGNORECASE)
    text = re.split(r"\bTeile?\b", text, flags=re.IGNORECASE)[0]
    text = re.sub(r"\s{2,}", " ", text).strip(" -/")
    text = re.sub(r"handwerk$", "", text, flags=re.IGNORECASE).strip(" -")
    return resolve_trade_name(text or None)


def parse_price(gebuehrentext: str | None) -> float | None:
    if not gebuehrentext:
        return None
    match = PRICE_PATTERN.search(gebuehrentext.replace("\xa0", " "))
    if not match:
        return None
    euros = match.group(1).replace(".", "")
    cents = match.group(2) or "00"
    return float(f"{euros}.{cents}")


def parse_format(zeitablauf: str | None) -> str:
    return FORMAT_MAP.get((zeitablauf or "").strip().lower(), "part_time")


def _offer_key(offer: RawCourseOffer) -> tuple[str, tuple[int, ...], str]:
    trade_slug, _ = normalize_trade(offer.trade_name)
    return trade_slug, tuple(offer.parts), offer.format_key


def _merge_offers(kdb_offers: list[RawCourseOffer], web_offers: list[RawCourseOffer]) -> list[RawCourseOffer]:
    """Keep all KDB runs; add web placeholders only when KDB has no run for that combo."""
    seen = {_offer_key(offer) for offer in kdb_offers}
    merged = list(kdb_offers)
    added = 0
    for offer in web_offers:
        key = _offer_key(offer)
        if key in seen:
            continue
        merged.append(offer)
        seen.add(key)
        added += 1
    if added:
        logger.info("HWK Bremen: added %d dateless Meisterkurs placeholder(s).", added)
    return merged


class HwkBremenScraper(BaseScraper):
    chamber_slug = "hwk-bremen"
    chamber_name = "Handwerkskammer Bremen"
    chamber_region = "Bremen"
    chamber_website = "https://www.hwk-bremen.de"
    source_url = SOURCE_URL
    request_delay = 1.0

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        kdb_offers = self._fetch_kdb_offers()
        web_offers = self._fetch_meisterkurse_offers()
        offers = _merge_offers(kdb_offers, web_offers)
        logger.info("HWK Bremen: parsed %d course offers total.", len(offers))
        return offers

    def _fetch_kdb_offers(self) -> list[RawCourseOffer]:
        response = self.get(KDB_URL)
        if response is None:
            logger.error("Could not fetch HWK Bremen course database.")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            logger.error("HWK Bremen: could not parse KDB XML: %s", exc)
            return []

        for elem in root.iter():
            elem.tag = elem.tag.rsplit("}", 1)[-1]

        templates = list(root.iter("vorlage"))
        offers: list[RawCourseOffer] = []
        meister = 0
        for vorlage in templates:
            titel = vorlage.findtext("titel") or ""
            abschluss = vorlage.findtext("abschluss") or ""
            if is_berufsspezialist_course(titel, abschluss):
                meister += 1
                offers.extend(self._parse_vorlage(vorlage))
                continue
            if not MEISTER_PATTERN.search(abschluss):
                continue
            meister += 1
            offers.extend(self._parse_vorlage(vorlage))

        logger.info(
            "HWK Bremen KDB: %d Meister template(s) of %d, parsed %d offers.",
            meister,
            len(templates),
            len(offers),
        )
        return offers

    def _fetch_meisterkurse_offers(self) -> list[RawCourseOffer]:
        soup = self.parse_html(MEISTERKURSE_OVERVIEW)
        if soup is None:
            logger.warning("Could not fetch HWK Bremen Meisterkurse overview.")
            return []

        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "/meisterkurs-" in href or href.endswith("mv-teil-iv-wochenend-lehrgang-fuer-alle-gewerke"):
                url = urljoin(MEISTERKURSE_BASE, href.split("?", 1)[0])
                if url not in links:
                    links.append(url)

        offers: list[RawCourseOffer] = []
        for url in sorted(links):
            page = self.parse_html(url)
            if page is None:
                logger.warning("Could not fetch HWK Bremen Meisterkurs page: %s", url)
                continue
            offer = self._parse_meisterkurs_page(page, url)
            if offer is not None:
                offers.append(offer)

        logger.info("HWK Bremen Meisterkurse: parsed %d placeholder(s) from %d page(s).", len(offers), len(links))
        return offers

    def _parse_meisterkurs_page(self, soup: BeautifulSoup, url: str) -> RawCourseOffer | None:
        heading = soup.find("h2")
        title_text = heading.get_text(" ", strip=True) if heading else ""
        abschluss = self._table_value(soup, "abschluss")
        parts = parse_parts(title_text, abschluss)
        if not parts and is_berufsspezialist_course(title_text, abschluss, url):
            parts = [1]
        if not parts:
            logger.warning("HWK Bremen: no parts parsed from Meisterkurs page %s", url)
            return None

        generic = set(parts) <= {3, 4}
        trade_name = None if generic else self._trade_from_meisterkurs_page(title_text, url)
        trade_name, parts = normalize_course_metadata(title_text, abschluss, url, trade_name, parts)
        format_key = self._format_from_meisterkurs_page(title_text, url, soup)
        _, teaching_mode = parse_format_and_mode(title_text)
        duration_hours = self._duration_from_page(soup)
        street, zip_code, city = DEFAULT_STREET, DEFAULT_ZIP, DEFAULT_CITY
        if teaching_mode == "online":
            street, zip_code, city = "", "", "Online"

        return RawCourseOffer(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=None,
            end_date=None,
            duration_hours=duration_hours,
            course_fee=None,
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=url,
            scraped_raw={
                "source": "meisterkurse_page",
                "heading": title_text,
                "abschluss": abschluss,
                "placeholder": True,
            },
        )

    @staticmethod
    def _table_value(soup: BeautifulSoup, label_prefix: str) -> str:
        prefix = label_prefix.lower()
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0].lower().startswith(prefix):
                return cells[1]
        return ""

    def _trade_from_meisterkurs_page(self, title_text: str, url: str) -> str | None:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"-(?:teilzeit|vollzeit|in)$", "", slug)
        slug = re.sub(r"^meisterkurs-", "", slug)
        for key, canonical in URL_TRADE_ALIASES.items():
            if key in slug:
                return canonical

        trade_name = parse_trade(title_text)
        if trade_name:
            return trade_name

        lowered = title_text.lower()
        for key, canonical in sorted(TRADE_ALIASES.items(), key=lambda item: -len(item[0])):
            if key.lower() in lowered:
                return canonical
        return None

    @staticmethod
    def _format_from_meisterkurs_page(title_text: str, url: str, soup: BeautifulSoup) -> str:
        haystack = f"{title_text} {url}".lower()
        if "vollzeit" in haystack:
            return "full_time"
        if "teilzeit" in haystack:
            return "part_time"

        lehrgangsart = ""
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) >= 2 and cells[0].lower().startswith("lehrgangsart"):
                lehrgangsart = cells[1].lower()
                break
        if "vollzeit" in lehrgangsart:
            return "full_time"
        return "part_time"

    @staticmethod
    def _duration_from_page(soup: BeautifulSoup) -> int | None:
        text = soup.get_text("\n", strip=True)
        match = DURATION_HOURS_RE.search(text)
        if not match:
            return None
        return int(match.group(1).replace(".", ""))

    def _parse_vorlage(self, vorlage: ET.Element) -> list[RawCourseOffer]:
        titel = (vorlage.findtext("titel") or "").strip()
        abschluss = (vorlage.findtext("abschluss") or "").strip()
        parts = parse_parts(titel, abschluss)
        generic = bool(parts) and set(parts) <= {3, 4}
        trade_name = None if generic else parse_trade(titel)
        trade_name, parts = normalize_course_metadata(titel, abschluss, "", trade_name, parts)
        if not parts:
            logger.warning("HWK Bremen: no parts parsed from %r", titel)
            return []
        title = build_course_title(trade_name, parts)
        format_key = parse_format(vorlage.findtext("zeitablauf"))
        duration_hours = self._parse_int(vorlage.findtext("stundenzahl"))
        vorlage_id = vorlage.findtext("vorlageid") or ""
        max_capacity = vorlage.findtext("teilnehmermax")

        offers: list[RawCourseOffer] = []
        for kurs in vorlage.findall("kurs"):
            try:
                offers.append(
                    self._build_offer(
                        kurs,
                        trade_name,
                        parts,
                        title,
                        format_key,
                        duration_hours,
                        vorlage_id,
                        max_capacity,
                        titel,
                    )
                )
            except Exception as exc:
                logger.warning("HWK Bremen: error parsing run of %r: %s", titel, exc)
        return offers

    def _build_offer(
        self,
        kurs: ET.Element,
        trade_name: str | None,
        parts: list[int],
        title: str,
        format_key: str,
        duration_hours: int | None,
        vorlage_id: str,
        max_capacity: str | None,
        template_title: str,
    ) -> RawCourseOffer:
        kursid = kurs.findtext("kursid") or ""
        street, zip_code, city = self._parse_location(kurs.find("lehrgangsort"))
        _, teaching_mode = parse_format_and_mode(template_title)
        if teaching_mode == "online":
            street, zip_code, city = "", "", "Online"

        enrolled = kurs.findtext("teilnehmer")
        capacity = kurs.findtext("teilnehmermax") or max_capacity

        return RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=self._clean_date(kurs.findtext("beginn")),
            end_date=self._clean_date(kurs.findtext("ende")),
            duration_hours=duration_hours,
            course_fee=parse_price(kurs.findtext("gebuehrentext")),
            city=city,
            street=street,
            zip_code=zip_code,
            availability=parse_kdb_availability(enrolled, capacity),
            source_url=build_kdb_detail_url(SOURCE_URL, "MVK", vorlage_id, kursid or None),
            scraped_raw={
                "titel": template_title,
                "kursid": kursid,
                "gebuehr": kurs.findtext("gebuehrentext"),
            },
        )

    @staticmethod
    def _parse_location(lehrgangsort: ET.Element | None) -> tuple[str, str, str]:
        if lehrgangsort is None:
            return DEFAULT_STREET, DEFAULT_ZIP, DEFAULT_CITY
        street = (lehrgangsort.findtext("strasse") or "").strip()
        hausnr = (lehrgangsort.findtext("hausnummer") or "").strip()
        street = f"{street} {hausnr}".strip()
        zip_code = (lehrgangsort.findtext("plz") or "").strip()
        city = (lehrgangsort.findtext("ort") or "").strip()
        if not (street or zip_code or city):
            return DEFAULT_STREET, DEFAULT_ZIP, DEFAULT_CITY
        return street, zip_code, city

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"\d+", value.replace(".", ""))
        return int(match.group()) if match else None

    @staticmethod
    def _clean_date(value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().split("T")[0] or None
