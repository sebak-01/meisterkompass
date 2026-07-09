"""
scrapers/hwk_bremen.py

Scraper for HWK Bremen Meistervorbereitungslehrgänge.
Source: the "universal KDB" course database behind handwerkbremen.de, run by
the chamber's education arm HandWERK gemeinnützige GmbH.

The public course pages (``handwerkbremen.de/meister-in/meisterkurse/…``)
render their schedule client-side from a JS widget that calls a REST backend:

    https://www.hwk-universal.de/universal-kdb-rest/v1/vorlagen/hwb

That single endpoint returns every course template (``<vorlage>``) for the
chamber as XML, each with its fee history, metadata (``abschluss``, ``titel``,
``zeitablauf``, ``stundenzahl``) and — inline — its scheduled runs as ``<kurs>``
elements (``beginn`` / ``ende`` / ``gebuehrentext`` / ``lehrgangsort``). The
scraper reads that structured feed rather than the rendered HTML, so it needs
just one request and is resilient to page-layout changes.

Only genuine Meistervorbereitung templates are kept: those whose ``abschluss``
names a "Meisterprüfung Teil …" / "Handwerksmeister Teil …". Templates with no
currently-scheduled ``<kurs>`` run are skipped (nothing to compare). Teile I/II
courses name a trade (taken from the title); Teile III/IV are cross-trade
(generic). Exam fees aren't part of the feed, so — like HWK Koblenz — they're
left for manual curation in ``data/manual/exam_fees_manual.json``.
"""

import logging
import re
import xml.etree.ElementTree as ET

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

KDB_URL = "https://www.hwk-universal.de/universal-kdb-rest/v1/vorlagen/hwb"

DEFAULT_STREET = "Schongauerstr. 2"
DEFAULT_ZIP    = "28219"
DEFAULT_CITY   = "Bremen"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# A template is Meistervorbereitung iff its Abschluss names a Meister part.
MEISTER_PATTERN = re.compile(r"(?:Meisterprüfung|Handwerksmeister)\s+Teil", re.IGNORECASE)
# One or more part tokens joined by '+', e.g. "Teil III + IV", "Teil I+II".
PARTS_PATTERN = re.compile(
    r"Teil\s+((?:IV|III|II|I)(?:\s*\+\s*(?:IV|III|II|I))*)", re.IGNORECASE,
)
PRICE_PATTERN = re.compile(r"([\d.]+),(\d{2})")

# Vollzeit/Teilzeit lives on the template (``zeitablauf``), not the run.
FORMAT_MAP = {"vollzeit": "full_time", "teilzeit": "part_time"}


def parse_parts(titel: str, abschluss: str) -> list[int]:
    """
    Parts for a template. The title's ``Teil …`` clause is authoritative (the
    Abschluss field has occasional typos, e.g. Friseur's "Teil  + II"); fall
    back to the Abschluss when the title has no explicit clause.
    """
    for source in (titel, abschluss):
        m = PARTS_PATTERN.search(source or "")
        if not m:
            continue
        parts = {ROMAN[t.strip().upper()] for t in re.split(r"\s*\+\s*", m.group(1))
                 if t.strip().upper() in ROMAN}
        if parts:
            return sorted(parts)
    return []


def parse_trade(titel: str) -> str | None:
    """
    Trade name from a Teil I/II template title, e.g.
    ``22462 - Meistervorbereitung im Tischlerhandwerk Teil I + II`` → ``Tischler``.
    """
    t = titel or ""
    t = re.sub(r"^\s*\w+\s*-\s*", "", t)                    # drop leading course number
    t = re.sub(r"^\s*Online\s*-\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:MV|Meistervorbereitung)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bim\b", "", t, flags=re.IGNORECASE)
    t = re.split(r"\bTeil\b", t, flags=re.IGNORECASE)[0]
    t = re.sub(r"\s{2,}", " ", t).strip(" -/")
    t = re.sub(r"handwerk$", "", t, flags=re.IGNORECASE).strip(" -")
    return t or None


def parse_price(gebuehrentext: str | None) -> float | None:
    if not gebuehrentext:
        return None
    m = PRICE_PATTERN.search(gebuehrentext.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + m.group(2))


def parse_format(zeitablauf: str | None) -> str:
    return FORMAT_MAP.get((zeitablauf or "").strip().lower(), "part_time")


class HwkBremenScraper(BaseScraper):
    chamber_slug    = "hwk-bremen"
    chamber_name    = "Handwerkskammer Bremen"
    chamber_region  = "Bremen"
    chamber_website = "https://www.hwk-bremen.de"
    source_url      = "https://www.handwerkbremen.de/meister-in/meisterkurse"
    request_delay   = 1.0

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

        templates = [v for v in root if v.tag == "vorlage"]
        offers: list[RawCourseOffer] = []
        meister = 0
        for vorlage in templates:
            if not MEISTER_PATTERN.search(vorlage.findtext("abschluss") or ""):
                continue
            meister += 1
            offers.extend(self._parse_vorlage(vorlage))

        logger.info("HWK Bremen: %d Meister template(s) of %d, parsed %d offers.",
                    meister, len(templates), len(offers))
        return offers

    def _parse_vorlage(self, vorlage: ET.Element) -> list[RawCourseOffer]:
        titel     = (vorlage.findtext("titel") or "").strip()
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
        source_url = (f"https://www.handwerkbremen.de/service-center/kurse-und-seminare"
                      f"#/vorlage/MVK/{vorlage_id}")

        offers: list[RawCourseOffer] = []
        for kurs in vorlage.findall("kurs"):
            try:
                offers.append(self._build_offer(
                    kurs, trade_name, parts, title, format_key, duration_hours, source_url,
                ))
            except Exception as exc:
                logger.warning("HWK Bremen: error parsing run of %r: %s", titel, exc)
        return offers

    def _build_offer(self, kurs: ET.Element, trade_name: str | None, parts: list[int],
                     title: str, format_key: str, duration_hours: int | None,
                     source_url: str) -> RawCourseOffer:
        street, zip_code, city = self._parse_location(kurs.find("lehrgangsort"))
        return RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            start_date=(kurs.findtext("beginn") or None),
            end_date=(kurs.findtext("ende") or None),
            duration_hours=duration_hours,
            course_fee=parse_price(kurs.findtext("gebuehrentext")),
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=source_url,
            scraped_raw={
                "titel":    title,
                "kursid":   kurs.findtext("kursid"),
                "gebuehr":  kurs.findtext("gebuehrentext"),
            },
        )

    @staticmethod
    def _parse_location(lehrgangsort: ET.Element | None) -> tuple[str, str, str]:
        if lehrgangsort is None:
            return DEFAULT_STREET, DEFAULT_ZIP, DEFAULT_CITY
        strasse = (lehrgangsort.findtext("strasse") or "").strip()
        hausnr  = (lehrgangsort.findtext("hausnummer") or "").strip()
        street  = f"{strasse} {hausnr}".strip()
        zip_code = (lehrgangsort.findtext("plz") or "").strip()
        city     = (lehrgangsort.findtext("ort") or "").strip()
        return (
            street or DEFAULT_STREET,
            zip_code or DEFAULT_ZIP,
            city or DEFAULT_CITY,
        )

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        if not value:
            return None
        m = re.search(r"\d+", value)
        return int(m.group()) if m else None
