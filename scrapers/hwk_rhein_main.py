"""
scrapers/hwk_rhein_main.py

Scraper for Handwerkskammer Frankfurt-Rhein-Main Meisterkurse.
Source: https://portal.hwk-rhein-main.de/seminare/suche/

Page structure (verified 2026-07-09):
  - Each Meisterkurs detail page hosts one or more purchasable modules
    (e.g. "Teile I - IV", "Teil III + IV", "Teil IV only") distinguished
    by a free-form ``with-modul`` attribute shared across three element types:
      * ``<a with-modul="X">`` inside the module-selector ``<tr>`` row
        (selector anchors for the user-facing "Modul wählen" toggle);
      * ``<div with-modul="X">`` — the BAföG-Rechner price card per module
        (the single source of truth for each module's Kursgebühr);
      * ``<tbody with-modul="X">`` — one per scheduled run, containing
        the date-range, inline fee ("Gebühr:"), location, and availability.
  - Pages with zero modules (``auf Anfrage`` / ``in Planung``) have no
    ``div[with-modul]`` and no ``tbody[with-modul]`` elements.
  - There are NO ``div.tab-pane`` elements on any current page.
"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL     = "https://portal.hwk-rhein-main.de"
OVERVIEW_URL = f"{BASE_URL}/seminare/suche/"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
_ROMAN_ALT = r"(?:IV|III|II|I)"

# Meisterkurs h1 title: "Bäcker - Meisterkurs Teile I bis IV (Vollzeit)"
TITLE_RE = re.compile(
    r"^(?P<trade>.*?)\s*[-–]?\s*Meisterkurs\s+Teile?\s+"
    r"(?P<parts>(?:IV|III|II|I)(?:\s*(?:bis|und|\+|,)\s*(?:IV|III|II|I))*)",
    re.IGNORECASE,
)
# Module-selector label: "Termine Teil III + IV", "Termine Teile I - IV"
# Excludes labels starting with "Teil" followed by a bare number ("Teil 1")
MODULE_TAB_LABEL_RE = re.compile(
    rf"Termine\s+Teile?\s+(?P<parts>{_ROMAN_ALT}(?:\s*(?:[-–+]|und|bis)\s*{_ROMAN_ALT})*)",
    re.IGNORECASE,
)
# Feld: Lehrgangsort / Zeiten / Gebühr / Anmeldegebühr in tbody text
ORT_RE           = re.compile(r"Lehrgangsort:\s*(?P<ort>.+)", re.IGNORECASE)
DATES_RE         = re.compile(r"(?P<start>\d{2}\.\d{2}\.\d{4})\s*[-–]\s*(?P<end>\d{2}\.\d{2}\.\d{4})")
GEBUEHR_RE       = re.compile(r"Gebühr:\s*(?P<fee>Kostenlos|[\d.]+,\d{2}\s*€)", re.IGNORECASE)
ANMELDEGEBUEHR_RE = re.compile(r"Zzgl\.\s*(?P<anmeldegebuehr>[\d.]+(?:,\d{2})?)\s*€\s*Anmeldegebühr", re.IGNORECASE)
KURSGEBUEHR_RE   = re.compile(r"Kursgebühr\s*([\d.]+),(\d{2})\s*€")

# Location lookup — Lehrgangsort contains the venue name, not a street
# address, so match the keyword inside the text.
LOCATION_MAP: dict[str, dict] = {
    "frankfurt":   {"city": "Frankfurt am Main", "zip_code": "60327", "street": "Schönstraße 21"},
    "weiterstadt": {"city": "Weiterstadt",       "zip_code": "64331", "street": "Rudolf-Diesel-Straße 30"},
    "bensheim":    {"city": "Bensheim",          "zip_code": "64625", "street": "Werner-von-Siemens-Straße 30"},
}
DEFAULT_LOCATION = LOCATION_MAP["frankfurt"]

FORMAT_KEYWORDS = {
    "vollzeit": "full_time",
    "teilzeit": "part_time",
    "sprinter": "part_time",
}

# Shared vocabulary used by every scraper + web/src/render.js's availabilityBadge():
# "available" | "waitlist" | "full" | "unknown". Do NOT invent new values here —
# anything else renders as a blank badge on the site.
def _detect_availability(text_lower: str) -> str:
    if "ausgebucht" in text_lower:
        return "full"
    if "warteliste" in text_lower:
        return "waitlist"
    return "available"


# ---------------------------------------------------------------------------
# Parts parsing
# ---------------------------------------------------------------------------

def parse_parts(raw: str) -> list[int]:
    """Parse roman-numeral parts list from a free-form string like "III + IV"
    or "I bis IV" or "I und II". Returns a sorted list of ints."""
    raw = raw.strip().upper()
    # Range: "I - IV", "I bis IV"
    m = re.search(rf"\b({_ROMAN_ALT})\s*(?:-|–|BIS)\s*({_ROMAN_ALT})\b", raw)
    if m:
        lo, hi = sorted((ROMAN[m.group(1)], ROMAN[m.group(2)]))
        return list(range(lo, hi + 1))
    # Individual list: "III + IV", "I und II"
    tokens = re.split(r"\s*(?:UND|\+|,)\s*", raw)
    return sorted({ROMAN[t] for t in tokens if t in ROMAN})


def parse_h1_parts(h1_text: str) -> list[int]:
    """Extract parts from the Meisterkurs h1 heading."""
    m = TITLE_RE.match(h1_text.strip())
    return parse_parts(m.group("parts")) if m else []


def parse_title_and_trade(h1_text: str, parts: list[int]) -> tuple[str | None, list[int]]:
    """Parse trade name and *effective* parts from h1.  Returns
    ``(trade_name, parts)`` — for generic parts III/IV, trade_name is None."""
    m = TITLE_RE.match(h1_text.strip())
    if not m:
        return None, parts
    trade_raw = m.group("trade").strip().strip("-–").strip()
    trade_name = trade_raw or None
    if trade_name and set(parts) <= {3, 4}:
        trade_name = None
    return trade_name, parts


# ---------------------------------------------------------------------------
# Format / teaching mode
# ---------------------------------------------------------------------------

def parse_format_and_mode(h1_text: str) -> tuple[str, str]:
    m = re.search(r"\(([^)]+)\)\s*$", h1_text.strip())
    raw = m.group(1).lower() if m else h1_text.lower()
    format_key = "part_time"
    for kw, val in FORMAT_KEYWORDS.items():
        if kw in raw:
            format_key = val
            break
    has_online  = "online" in raw
    teaching_mode = (
        "hybrid" if (has_online and "präsenz" in raw)
        else ("online" if has_online else "presence")
    )
    return format_key, teaching_mode


# ---------------------------------------------------------------------------
# Price / date / location helpers
# ---------------------------------------------------------------------------

def parse_price(text: str) -> float | None:
    if text.strip().lower() == "kostenlos":
        return None
    m = re.search(r"([\d.]+),(\d{2})", text)
    return float(m.group(1).replace(".", "") + "." + m.group(2)) if m else None


def parse_location(ort_name: str) -> dict:
    lower = ort_name.lower()
    for key, loc in LOCATION_MAP.items():
        if key in lower:
            return loc
    return DEFAULT_LOCATION


def fmt_date(d: str) -> str:
    dd, mm, yyyy = d.split(".")
    return f"{yyyy}-{mm}-{dd}"


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class HwkRheinMainScraper(BaseScraper):
    chamber_slug    = "hwk-rhein-main"
    chamber_name    = "Handwerkskammer Frankfurt-Rhein-Main"
    chamber_region  = "Hessen"
    chamber_website = BASE_URL
    source_url      = OVERVIEW_URL
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        overview = self.parse_html(OVERVIEW_URL)
        if overview is None:
            logger.error("Could not fetch HWK Frankfurt-Rhein-Main overview page.")
            return []

        seminar_urls = self._collect_seminar_urls(overview)
        logger.info("HWK Frankfurt-Rhein-Main: found %d seminar links.", len(seminar_urls))

        offers: list[RawCourseOffer] = []
        for url in seminar_urls:
            offers.extend(self._scrape_detail_page(url))

        logger.info("HWK Frankfurt-Rhein-Main: parsed %d course offers.", len(offers))
        return offers

    def _collect_seminar_urls(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/seminar/" not in href or href.rstrip("/").endswith("/suche"):
                continue
            full_url = href if href.startswith("http") else BASE_URL + href
            full_url = full_url.split("?")[0].split("#")[0]
            if not full_url.endswith("/"):
                full_url += "/"
            if full_url not in urls:
                urls.append(full_url)
        return urls

    # ------------------------------------------------------------------
    # Detail page parsing
    # ------------------------------------------------------------------

    def _scrape_detail_page(self, url: str) -> list[RawCourseOffer]:
        soup = self.parse_html(url)
        if soup is None:
            logger.warning("Could not fetch %s", url)
            return []

        h1 = soup.find("h1")
        h1_text = h1.get_text(strip=True) if h1 else ""
        if "meisterkurs" not in h1_text.lower():
            return []

        h1_parts = parse_h1_parts(h1_text)
        if not h1_parts:
            logger.debug("Could not parse parts from h1 %r at %s", h1_text, url)
            return []
        h1_trade, h1_parts = parse_title_and_trade(h1_text, h1_parts)
        format_key, teaching_mode = parse_format_and_mode(h1_text)

        # Build the code → label lookup from selector anchors.
        # Each <a with-modul="X"> sits inside a <tr> containing a label
        # like "Termine Teil III + IV"; the label's roman-numeral content
        # encodes the module's parts.
        code2label: dict[str, str] = {}
        for anchor in soup.find_all("a", attrs={"with-modul": True}):
            tr = anchor.find_parent("tr")
            if tr is None:
                continue
            label_text = tr.get_text(" ", strip=True)
            lbl_match = MODULE_TAB_LABEL_RE.search(label_text)
            if lbl_match:
                code2label.setdefault(anchor["with-modul"].strip(), lbl_match.group("parts"))

        # Enumerate purchasable modules: one <div with-modul> per module,
        # each carrying the Kursgebühr from the BAföG-Rechner card.
        module_divs = soup.find_all("div", attrs={"with-modul": True})

        if not module_divs:
            # Pages with zero modules ("auf Anfrage" / "in Planung"):
            # emit a single dateless offer so the price shows up, or skip.
            page_text = soup.get_text(separator=" ")
            if "auf anfrage" in page_text.lower() or "planung" in page_text.lower():
                return []
            kurs_m = KURSGEBUEHR_RE.search(page_text)
            if kurs_m:
                fee = float(kurs_m.group(1).replace(".", "") + "." + kurs_m.group(2))
                title = build_course_title(h1_trade, h1_parts)
                return [RawCourseOffer(
                    title=title, trade_name=h1_trade, parts=h1_parts,
                    format_key=format_key, teaching_mode=teaching_mode,
                    start_date=None, end_date=None, duration_hours=None,
                    course_fee=fee,
                    city=DEFAULT_LOCATION["city"],
                    street=DEFAULT_LOCATION["street"],
                    zip_code=DEFAULT_LOCATION["zip_code"],
                    exam_fee_scraped=None,
                    availability=_detect_availability(page_text.lower()),
                    source_url=url,
                    scraped_raw={"h1": h1_text, "note": "Keine Termininformation"},
                )]
            return []

        offers: list[RawCourseOffer] = []
        for div in module_divs:
            code = div["with-modul"].strip()

            # Module parts: prefer the selector label (roman numerals),
            # fall back to parsing the raw module code, then the h1.
            label_parts = parse_parts(code2label.get(code, ""))
            code_parts  = parse_parts(code)
            parts = label_parts or code_parts or h1_parts
            if not parts:
                continue

            trade_name = None if set(parts) <= {3, 4} else h1_trade
            title = build_course_title(trade_name, parts)

            # Module Kursgebühr from the BAföG-Rechner card.
            kurs_m = KURSGEBUEHR_RE.search(div.get_text(separator=" "))
            module_fee = (
                float(kurs_m.group(1).replace(".", "") + "." + kurs_m.group(2))
                if kurs_m else None
            )

            # Scheduled runs: <tbody with-modul="…"> matching this code.
            tbodies = [
                tb for tb in soup.find_all("tbody", attrs={"with-modul": True})
                if tb["with-modul"].strip() == code
            ]
            for tb in tbodies:
                offers.extend(
                    self._parse_tbody_run(tb, url, trade_name, parts, title,
                                          format_key, teaching_mode, module_fee)
                )

        return offers

    def _parse_tbody_run(
        self,
        tb: Tag,
        url: str,
        trade_name: str | None,
        parts: list[int],
        title: str,
        format_key: str,
        teaching_mode: str,
        module_fee: float | None,
    ) -> list[RawCourseOffer]:
        """Parse a single ``<tbody with-modul>`` (one scheduled run) into
        zero or one ``RawCourseOffer``."""
        text = re.sub(r"\s+", " ", tb.get_text(separator=" ", strip=True))

        dm = DATES_RE.search(text)
        if not dm:
            return []

        # Skip past runs.
        try:
            start_dt = datetime.strptime(dm.group("start"), "%d.%m.%Y")
            if start_dt < datetime.now():
                return []
        except ValueError:
            pass

        fm = GEBUEHR_RE.search(text)
        fee = parse_price(fm.group("fee")) if fm else None
        # Prefer inline fee; fall back to the module-level Kursgebühr.
        if fee is None:
            fee = module_fee

        ort_m = ORT_RE.search(text)
        ort_text = ort_m.group("ort").strip() if ort_m else ""
        if "Zeiten:" in ort_text:
            ort_text = ort_text.split("Zeiten:")[0].strip()

        amb_m = ANMELDEGEBUEHR_RE.search(text)
        anmeldegebuehr = amb_m.group("anmeldegebuehr") if amb_m else None

        availability = _detect_availability(text.lower())
        loc = parse_location(ort_text)

        return [RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=fmt_date(dm.group("start")),
            end_date=fmt_date(dm.group("end")),
            duration_hours=None,
            course_fee=fee,
            city=loc["city"],
            street=loc["street"],
            zip_code=loc["zip_code"],
            exam_fee_scraped=None,
            availability=availability,
            source_url=url,
            scraped_raw={
                "h1": title,
                "lehrgangsort": ort_text,
                "anmeldegebuehr": anmeldegebuehr,
            },
        )]
