"""
scrapers/hwk_rhein_main.py

Scraper for Handwerkskammer Frankfurt-Rhein-Main Meisterkurse.
Source: https://portal.hwk-rhein-main.de/seminare/suche/

"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL     = "https://portal.hwk-rhein-main.de"
OVERVIEW_URL = f"{BASE_URL}/seminare/suche/"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
ROMAN_ORDER = ["I", "II", "III", "IV"]

TITLE_RE = re.compile(
    r"^(?P<trade>.*?)\s*[-–]?\s*Meisterkurs\s+Teile?\s+"
    r"(?P<parts>(?:IV|III|II|I)(?:\s*(?:bis|und|\+|,)\s*(?:IV|III|II|I))*)"
    r"(?:\s+Schwerpunkt\s+(?P<schwerpunkt>[A-Za-zÄÖÜäöüß]+))?",
    re.IGNORECASE,
)
FORMAT_TAIL_RE = re.compile(r"\(([^)]+)\)\s*$")

# Strictly scoped match patterns for single blocks
ORT_RE = re.compile(r"Lehrgangsort:\s*(?P<ort>.+)", re.IGNORECASE)
ZEITEN_DATES_RE = re.compile(r"(?P<start>\d{2}\.\d{2}\.\d{4})\s*[-–]\s*(?P<end>\d{2}\.\d{2}\.\d{4})")
GEBUEHR_RE = re.compile(r"Gebühr:\s*(?P<fee>Kostenlos|[\d.]+,\d{2}\s*€)", re.IGNORECASE)
ANMELDEGEBUEHR_RE = re.compile(r"Zzgl\.\s*(?P<anmeldegebuehr>[\d.]+(?:,\d{2})?)\s*€\s*Anmeldegebühr", re.IGNORECASE)

MODULE_TAB_LABEL_RE = re.compile(
    r"Termine\s+Teile?\s+(?P<parts>(?:IV|III|II|I)(?:\s*[-–+]\s*(?:IV|III|II|I))*)",
    re.IGNORECASE,
)

KURSGEBUEHR_RE = re.compile(r"Kursgebühr[:\s]*([\d.]+),(\d{2})\s*€")

LOCATION_MAP: dict[str, dict] = {
    "frankfurt":   {"city": "Frankfurt am Main", "zip_code": "60327", "street": "Schönstraße 21"},
    "weiterstadt": {"city": "Weiterstadt",        "zip_code": "64331", "street": "Rudolf-Diesel-Straße 30"},
    "bensheim":    {"city": "Bensheim",           "zip_code": "64625", "street": "Werner-von-Siemens-Straße 30"},
}
DEFAULT_LOCATION = LOCATION_MAP["frankfurt"]

FORMAT_KEYWORDS = {
    "vollzeit": "full_time",
    "teilzeit": "part_time",
    "sprinter": "part_time",
}


def parse_parts(raw: str) -> list[int]:
    raw = raw.strip().upper()
    for sep in (" BIS ", " - ", " – "):
        if sep in raw:
            a, b = (t.strip() for t in raw.split(sep, 1))
            if a in ROMAN and b in ROMAN:
                return list(range(ROMAN[a], ROMAN[b] + 1))
    tokens = re.split(r"\s*(?:UND|\+|,)\s*", raw)
    return sorted({ROMAN[t] for t in tokens if t in ROMAN})


def parse_title(h1_text: str) -> tuple[str | None, list[int]] | None:
    m = TITLE_RE.match(h1_text.strip())
    if not m:
        return None
    parts = parse_parts(m.group("parts"))
    if not parts:
        return None
    trade_raw = m.group("trade").strip().strip("-–").strip()
    schwerpunkt = m.group("schwerpunkt")
    trade_name = trade_raw or None
    if trade_name and schwerpunkt:
        trade_name = f"{trade_name} ({schwerpunkt.strip()})"
    if trade_name and set(parts) <= {3, 4}:
        trade_name = None
    return trade_name, parts


def parse_format_and_mode(h1_text: str) -> tuple[str, str]:
    m = FORMAT_TAIL_RE.search(h1_text.strip())
    raw = m.group(1).lower() if m else h1_text.lower()
    format_key = "part_time"
    for kw, val in FORMAT_KEYWORDS.items():
        if kw in raw:
            format_key = val
            break
    has_online = "online" in raw
    has_presence = "präsenz" in raw or not has_online
    teaching_mode = "hybrid" if (has_online and "präsenz" in raw) else ("online" if has_online else "presence")
    return format_key, teaching_mode


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

    def _scrape_detail_page(self, url: str) -> list[RawCourseOffer]:
        soup = self.parse_html(url)
        if soup is None:
            logger.warning("Could not fetch %s", url)
            return []

        h1 = soup.find("h1")
        h1_text = h1.get_text(strip=True) if h1 else ""
        if "meisterkurs" not in h1_text.lower():
            return []

        parsed = parse_title(h1_text)
        if parsed is None:
            logger.debug("Could not parse trade/parts from %r at %s", h1_text, url)
            return []
        trade_name, parts = parsed
        format_key, teaching_mode = parse_format_and_mode(h1_text)
        title = build_course_title(trade_name, parts)

        # Detect structural tabs / multi-module divs
        tab_containers = soup.find_all("div", class_="tab-pane")
        
        if tab_containers:
            offers: list[RawCourseOffer] = []
            for container in tab_containers:
                tab_id = container.get("id", "")
                # Find matching link for label to determine part variations
                tab_link = soup.find("a", href=f"#{tab_id}")
                tab_label = tab_link.get_text(strip=True) if tab_link else ""
                
                tab_m = MODULE_TAB_LABEL_RE.search(tab_label)
                tab_parts = parse_parts(tab_m.group("parts")) if tab_m else parts
                
                t_name = None if set(tab_parts) <= {3, 4} else trade_name
                t_title = build_course_title(t_name, tab_parts)
                
                offers.extend(self._parse_container_termine(container, url, t_name, tab_parts, t_title, format_key, teaching_mode))
            return offers

        return self._parse_container_termine(soup, url, trade_name, parts, title, format_key, teaching_mode)

    def _parse_container_termine(
        self, container: BeautifulSoup, url: str, trade_name: str | None, parts: list[int],
        title: str, format_key: str, teaching_mode: str,
    ) -> list[RawCourseOffer]:
        groups: dict[tuple[str, str, str], dict] = {}
        order: list[tuple[str, str, str]] = []

        # Find individual structural blocks or rows containing course items
        # Typically structured as rows, tables, or generic paragraphs with Lehrgangsort
        paragraphs = container.find_all(["p", "div", "tr"])
        
        current_ort = None
        current_dates = None
        
        for elem in paragraphs:
            text = re.sub(r"\s+", " ", elem.get_text(separator=" ", strip=True))
            
            ort_m = ORT_RE.search(text)
            if ort_m:
                current_ort = ort_m.group("ort").strip()
                # Try to clean up tail end if elements are packed together
                if "Zeiten:" in current_ort:
                    current_ort = current_ort.split("Zeiten:")[0].strip()

            dates_m = ZEITEN_DATES_RE.search(text)
            if dates_m:
                current_dates = (dates_m.group("start"), dates_m.group("end"))

            fee_m = GEBUEHR_RE.search(text)
            if fee_m and current_ort and current_dates:
                start_raw, end_raw = current_dates
                
                # Check expiration date right here:
                try:
                    start_dt = datetime.strptime(start_raw, "%d.%m.%Y")
                    if start_dt < datetime.now():
                        continue  # Skip expired runs!
                except ValueError:
                    pass

                key = (current_ort, start_raw, end_raw)
                fee = parse_price(fee_m.group("fee"))
                
                amb_m = ANMELDEGEBUEHR_RE.search(text)
                anmeldegebuehr = amb_m.group("anmeldegebuehr") if amb_m else None

                if key not in groups:
                    groups[key] = {"fee": fee, "anmeldegebuehr": anmeldegebuehr}
                    order.append(key)
                elif fee is not None and (groups[key]["fee"] is None or fee > groups[key]["fee"]):
                    groups[key]["fee"] = fee
                    groups[key]["anmeldegebuehr"] = anmeldegebuehr

        offers: list[RawCourseOffer] = []
        for key in order:
            ort, start_raw, end_raw = key
            loc = parse_location(ort)
            offers.append(RawCourseOffer(
                title=title,
                trade_name=trade_name,
                parts=parts,
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=fmt_date(start_raw),
                end_date=fmt_date(end_raw),
                duration_hours=None,
                course_fee=groups[key]["fee"],
                city=loc["city"],
                street=loc["street"],
                zip_code=loc["zip_code"],
                exam_fee_scraped=None,
                availability="unknown",
                source_url=url,
                scraped_raw={
                    "h1": title, "lehrgangsort": ort,
                    "anmeldegebuehr": groups[key]["anmeldegebuehr"],
                },
            ))

        if not offers:
            # Fallback out to general page text if no dated blocks match active conditions
            page_text = container.get_text(separator=" ")
            fee_m = KURSGEBUEHR_RE.search(page_text)
            if fee_m:
                course_fee = float(fee_m.group(1).replace(".", "") + "." + fee_m.group(2))
                loc = parse_location(current_ort) if current_ort else DEFAULT_LOCATION
                offers.append(RawCourseOffer(
                    title=title, trade_name=trade_name, parts=parts,
                    format_key=format_key, teaching_mode=teaching_mode,
                    start_date=None, end_date=None, duration_hours=None,
                    course_fee=course_fee, city=loc["city"], street=loc["street"], zip_code=loc["zip_code"],
                    exam_fee_scraped=None, availability="unknown", source_url=url,
                    scraped_raw={"h1": title, "note": "Termine vergangen oder nicht verfügbar", "course_fee": course_fee},
                ))
        return offers