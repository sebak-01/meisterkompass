"""Shared scraper for HWK chambers using the BUE universal-kdb REST API."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import parse_format_and_mode, parse_parts, parse_trade

logger = logging.getLogger(__name__)

KDB_REST_BASE = "https://www.hwk-universal.de/universal-kdb-rest/v1"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
PRICE_RE = re.compile(r"([\d.]+),(\d{2})")
VORLAGE_RE = re.compile(
    r"<vorlagen>\s*<mandant>(?P<mandant>[^<]+)</mandant>\s*<modul>(?P<modul>[^<]+)</modul>"
    r"\s*<titel>(?P<titel>[^<]+)</titel>\s*<vorlageid>(?P<vorlageid>\d+)</vorlageid>\s*</vorlagen>",
    re.S,
)
KURS_RE = re.compile(r"<kurs>(.*?)</kurs>", re.S)

SH_TRADE_ALIASES = {
    "kraftfahrzeugtechniker-handwerk": "Kfz.-Techniker",
    "kraftfahrzeugtechniker": "Kfz.-Techniker",
    "metallbauerhandwerk": "Metallbauer",
    "zimmererhandwerk": "Zimmerer",
    "straßenbauerhandwerk": "Straßenbauer",
    "maurer- und betonbauerhandwerk": "Maurer und Betonbauer",
    "maurer und betonbauer-handwerk": "Maurer und Betonbauer",
    "elektrotechniker-handwerk": "Elektrotechniker",
    "elektrotechnikerhandwerk": "Elektrotechniker",
    "informationstechnikerhandwerk": "Informationstechniker",
    "friseur-handwerk": "Friseur",
    "friseurhandwerk": "Friseur",
    "tischler-handwerk": "Tischler",
    "tischlerhandwerk": "Tischler",
    "land- und baumaschinenmechatronikerhandwerk": "Land- und Baumaschinenmechatroniker",
    "maler-handwerk": "Maler und Lackierer",
    "malerhandwerk": "Maler und Lackierer",
    "feinwerkmechanikerhandwerk": "Feinwerkmechaniker",
    "installateur- und heizungsbauerhandwerk": "Installateur- und Heizungsbauer",
    "installateur und heizungsbauer-handwerk": "Installateur- und Heizungsbauer",
    "fliesen-, platten- und mosaikleger-handwerk": "Fliesen-, Platten- und Mosaikleger",
}

EXCLUDE_TITLE_RE = re.compile(
    r"industriemeister|"
    r"konflikte meistern|"
    r"stress.*meistern|"
    r"abschlussprüfung.*büromanagement|"
    r"vorbereitung abschlussprüfung|"
    r"schweißfachmann|"
    r"schweiß- und fügetechnik|"
    r"elektrofachkraft|"
    r"bootselektrik|"
    r"zurück in den friseurberuf|"
    r"fachverkaufslehrgang",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KdbCatalogue:
    mandant: str
    source_url: str
    default_street: str
    default_zip: str
    default_city: str


def _xml_field(block: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).strip())


def _part_number(token: str) -> int:
    token = token.upper()
    if token in ROMAN:
        return ROMAN[token]
    return int(token)


def parse_sh_parts(title: str) -> list[int]:
    range_match = re.search(
        r"Teile?\s*(IV|III|II|I|[1-4])\s*(?:bis|-|–)\s*(IV|III|II|I|[1-4])\b",
        title,
        re.IGNORECASE,
    )
    if range_match:
        lo = _part_number(range_match.group(1))
        hi = _part_number(range_match.group(2))
        return list(range(min(lo, hi), max(lo, hi) + 1))

    parts = parse_parts(title, implicit_trade_parts=True)
    if parts:
        return parts

    match = re.search(
        r"(?:^|[\s(])((?:IV|III|II|I|[1-4])"
        r"(?:\s*(?:\+|und|u\.?|/|,&|sowie)\s*(?:IV|III|II|I|[1-4]))+)",
        title,
        re.IGNORECASE,
    )
    if match:
        tokens = re.findall(r"IV|III|II|I|[1-4]", match.group(1).upper())
        return sorted({_part_number(token) for token in tokens})

    single = re.search(r"\bTeil\s*(IV|III|II|I|[1-4])\b", title, re.IGNORECASE)
    if single:
        return [_part_number(single.group(1))]
    return []


def parse_sh_trade(title: str, parts: list[int]) -> str | None:
    trade = parse_trade(title, parts)
    if trade:
        return trade

    lower = title.lower()
    for source, canonical in sorted(SH_TRADE_ALIASES.items(), key=lambda item: -len(item[0])):
        if source in lower:
            return canonical
    return None


def parse_sh_title(title: str) -> tuple[list[int], str | None]:
    if EXCLUDE_TITLE_RE.search(title):
        return [], None

    parts = parse_sh_parts(title)
    if not parts:
        return [], None

    trade = parse_sh_trade(title, parts)
    if set(parts) <= {3, 4}:
        return parts, None
    if trade:
        return parts, trade
    if set(parts) <= {1, 2}:
        return parts, None
    return [], None


def parse_kdb_price(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    return float(match.group(1).replace(".", "") + "." + match.group(2))


def parse_kdb_location(block: str) -> tuple[str, str, str]:
    street = _xml_field(block, "strasse") or ""
    hausnummer = _xml_field(block, "hausnummer") or ""
    if street and hausnummer:
        street = f"{street} {hausnummer}"
    zip_code = _xml_field(block, "plz") or ""
    city = _xml_field(block, "ort") or ""
    if not city:
        names = re.findall(r"<lehrgangsort>([^<]+)</lehrgangsort>", block)
        city = names[-1] if names else ""
    return street, zip_code, city


def parse_kdb_availability(enrolled: str | None, max_capacity: str | None) -> str:
    """Derive seat availability from enrolled count vs. capacity.

    In the KDB API ``teilnehmer`` is the number already enrolled, not free
    spots. ``teilnehmermax`` is usually published on the vorlage, not inside
    each ``<kurs>`` block.
    """
    if enrolled is None or max_capacity is None:
        return "unknown"
    try:
        free_spots = int(max_capacity) - int(enrolled)
    except ValueError:
        return "unknown"
    if free_spots <= 0:
        return "full"
    return "available"


class UniversalKdbScraper(BaseScraper):
    """Scrape Meister courses from the hwk-universal.de KDB REST catalogue."""

    kdb_mandant: str
    kdb_catalogue: KdbCatalogue
    request_delay = 0.15

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str | None]] = set()

        for entry in self._list_vorlagen():
            title = entry["titel"]
            parts, trade_name = parse_sh_title(title)
            if not parts:
                logger.debug("%s: skipping %r", self.chamber_slug, title)
                continue

            detail_xml = self._fetch_vorlage(entry["modul"], entry["vorlageid"])
            if detail_xml is None:
                continue

            duration_hours = self._parse_duration_hours(detail_xml)
            runs = self._parse_kurse(
                detail_xml,
                entry["modul"],
                entry["vorlageid"],
                title,
                parts,
                trade_name,
                duration_hours,
            )
            for offer in runs:
                key = (offer.source_url, offer.start_date)
                if key in seen:
                    continue
                seen.add(key)
                offers.append(offer)

        logger.info("%s: parsed %d course runs.", self.chamber_name, len(offers))
        return offers

    def _list_vorlagen(self) -> list[dict[str, str]]:
        response = self.get(f"{KDB_REST_BASE}/bereiche/{self.kdb_mandant}")
        if response is None:
            logger.error("%s: could not fetch KDB bereiche.", self.chamber_name)
            return []
        return [match.groupdict() for match in VORLAGE_RE.finditer(response.text)]

    def _fetch_vorlage(self, modul: str, vorlageid: str) -> str | None:
        response = self.get(f"{KDB_REST_BASE}/vorlagen/{self.kdb_mandant}/{modul}/{vorlageid}")
        if response is None or response.status_code != 200:
            logger.warning(
                "%s: could not fetch vorlage %s/%s.", self.chamber_name, modul, vorlageid
            )
            return None
        return response.text

    def _parse_duration_hours(self, detail_xml: str) -> int | None:
        values = re.findall(r"<stundenzahl>(\d+)</stundenzahl>", detail_xml)
        if not values:
            return None
        return int(values[0])

    def _detail_url(self, modul: str, vorlageid: str, kursid: str | None = None) -> str:
        page_url = self.kdb_catalogue.source_url.split("#", 1)[0].rstrip("/")
        url = f"{page_url}#/vorlage/{modul}/{vorlageid}"
        if kursid:
            url = f"{url}?kurs={kursid}"
        return url

    def _parse_kurse(
        self,
        detail_xml: str,
        modul: str,
        vorlageid: str,
        title: str,
        parts: list[int],
        trade_name: str | None,
        duration_hours: int | None,
    ) -> list[RawCourseOffer]:
        runs: list[RawCourseOffer] = []
        blocks = KURS_RE.findall(detail_xml)
        if not blocks:
            return runs

        vorlage_max = _xml_field(detail_xml, "teilnehmermax")

        for block in blocks:
            kursid = _xml_field(block, "kursid")
            start_date = _xml_field(block, "beginn")
            end_date = _xml_field(block, "ende")
            street, zip_code, city = parse_kdb_location(block)
            if not city:
                street, zip_code, city = (
                    self.kdb_catalogue.default_street,
                    self.kdb_catalogue.default_zip,
                    self.kdb_catalogue.default_city,
                )

            schedule_text = " ".join(
                filter(None, (title, _xml_field(block, "unterrichtszeit") or ""))
            )
            format_key, teaching_mode = parse_format_and_mode(schedule_text)
            if teaching_mode == "online":
                street, zip_code, city = "", "", "Online"

            course_fee = parse_kdb_price(_xml_field(block, "gebuehrentext"))
            if course_fee is None:
                course_fee = self._fee_for_start(detail_xml, start_date)

            runs.append(
                RawCourseOffer(
                    title=build_course_title(trade_name, parts),
                    trade_name=trade_name,
                    parts=parts,
                    format_key=format_key or "part_time",
                    teaching_mode=teaching_mode,
                    start_date=start_date,
                    end_date=end_date,
                    duration_hours=duration_hours,
                    course_fee=course_fee,
                    exam_fee_scraped=None,
                    exam_fee_qualifier="",
                    city=city,
                    street=street,
                    zip_code=zip_code,
                    availability=parse_kdb_availability(
                        _xml_field(block, "teilnehmer"),
                        _xml_field(block, "teilnehmermax") or vorlage_max,
                    ),
                    source_url=self._detail_url(modul, vorlageid, kursid),
                    scraped_raw={
                        "title": title,
                        "kursid": kursid,
                        "unterrichtszeit": _xml_field(block, "unterrichtszeit"),
                    },
                )
            )
        return runs

    @staticmethod
    def _fee_for_start(detail_xml: str, start_date: str | None) -> float | None:
        if not start_date:
            return None
        try:
            run_start = date.fromisoformat(start_date)
        except ValueError:
            return None

        candidates: list[tuple[date | None, date | None, float]] = []
        for block in re.findall(r"<gebuehr>(.*?)</gebuehr>", detail_xml, re.S):
            fee = parse_kdb_price(_xml_field(block, "gebuehr"))
            if fee is None:
                continue
            valid_from = _xml_field(block, "gueltigvon")
            valid_to = _xml_field(block, "gueltigbis")
            start = date.fromisoformat(valid_from) if valid_from else None
            end = date.fromisoformat(valid_to) if valid_to else None
            candidates.append((start, end, fee))

        for start, end, fee in candidates:
            if start and run_start < start:
                continue
            if end and run_start > end:
                continue
            return fee
        return candidates[0][2] if candidates else None

    def published_exam_fee_rows(self) -> list[dict]:
        return []

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result
