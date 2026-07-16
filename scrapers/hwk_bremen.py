"""Scraper for HWK Bremen Meistervorbereitungslehrgänge via the universal KDB bulk feed."""

import logging
import re
import xml.etree.ElementTree as ET

from .base import BaseScraper, RawCourseOffer, build_course_title
from .hwk_bayern import parse_format_and_mode
from .hwk_universal_kdb import build_kdb_detail_url, parse_kdb_availability

logger = logging.getLogger(__name__)

KDB_URL = "https://www.hwk-universal.de/universal-kdb-rest/v1/vorlagen/hwb"
SOURCE_URL = "https://www.handwerkbremen.de/service-center/kurse-und-seminare#/"

DEFAULT_STREET = "Schongauerstr. 2"
DEFAULT_ZIP = "28219"
DEFAULT_CITY = "Bremen"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
MEISTER_PATTERN = re.compile(r"(?:Meisterprüfung|Handwerksmeister)\s+Teile?\b", re.IGNORECASE)
PARTS_PATTERN = re.compile(
    r"Teile?\s+((?:IV|III|II|I)(?:\s*\+\s*(?:IV|III|II|I))*)", re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"(\d[\d.]*)(?:,(\d{2}))?")
FORMAT_MAP = {"vollzeit": "full_time", "teilzeit": "part_time"}


def parse_parts(titel: str, abschluss: str) -> list[int]:
    for source in (titel, abschluss):
        match = PARTS_PATTERN.search(source or "")
        if not match:
            continue
        parts = {
            ROMAN[token.strip().upper()]
            for token in re.split(r"\s*\+\s*", match.group(1))
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
    return text or None


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


class HwkBremenScraper(BaseScraper):
    chamber_slug = "hwk-bremen"
    chamber_name = "Handwerkskammer Bremen"
    chamber_region = "Bremen"
    chamber_website = "https://www.hwk-bremen.de"
    source_url = SOURCE_URL
    request_delay = 1.0

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
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
            if not MEISTER_PATTERN.search(vorlage.findtext("abschluss") or ""):
                continue
            meister += 1
            offers.extend(self._parse_vorlage(vorlage))

        logger.info(
            "HWK Bremen: %d Meister template(s) of %d, parsed %d offers.",
            meister,
            len(templates),
            len(offers),
        )
        return offers

    def _parse_vorlage(self, vorlage: ET.Element) -> list[RawCourseOffer]:
        titel = (vorlage.findtext("titel") or "").strip()
        abschluss = (vorlage.findtext("abschluss") or "").strip()
        parts = parse_parts(titel, abschluss)
        if not parts:
            logger.warning("HWK Bremen: no parts parsed from %r", titel)
            return []

        generic = set(parts) <= {3, 4}
        trade_name = None if generic else parse_trade(titel)
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
