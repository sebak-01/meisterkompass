"""
scraper/hwk_pfalz.py

Scraper for Handwerkskammer der Pfalz Meistervorbereitungskurse.
Source: https://www.hwk-pfalz.de/kurse/liste-51,0,courselist.html?search-type=6

HTML structure (verified 2026-05-27 via debug_pfalz.py):
  Identical CMS to HWK Koblenz — same div.row card container.

  List page card text (Level 3 div.row):
    "[Contact] | [Date]: [Format] | [Title] | [Price] (inkl. Prüfung) | [UStd.] | [City] | [Availability]"

  Key differences from HWK Koblenz:
  - Title prefix: "Meistervorbereitung" instead of a trade-first pattern
  - Title parts separator: " - " (hyphen) instead of " und "
  - Price includes exam fee on list page: "2.900,00 € （inkl. Prüfung）" (Japanese brackets)
  - Duration: "340 UStd." (UStd. = Unterrichtsstunden, same value as Std.)
  - Extra flag "Garantierte Durchführung" in card text (stored in notes)

  Strategy:
  1. Parse all list pages for card metadata (title, dates, city, availability, detail URL).
  2. Fetch each detail page to get the separate Kurs/Prüfung fee breakdown.
     (Same "Kurs: X €  Prüfung: X €" pattern as HWK Trier.)
  3. Use the combined list-page price as fallback when detail parsing fails.

  Total courses: ~32 → two list pages, ~32 detail pages (~40 s runtime at 1.2 s/request).
"""

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL  = "https://www.hwk-pfalz.de"
LIST_URL  = (
    f"{BASE_URL}/kurse/liste-51,0,courselist.html"
    "?search-type=6&limit=20&offset={offset}"
)
PAGE_SIZE = 20

FORMAT_MAP = {
    "vollzeit":   "full_time",
    "teilzeit":   "part_time",
    "wochenende": "part_time",
    "block":      "part_time",
    "online":     "part_time",
}

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# "Meistervorbereitung Teile III - IV"
# "Meistervorbereitung Kraftfahrzeugtechniker Teil II"
# "Meistervorbereitung Elektrotechniker Teile I - II"
PFALZ_TITLE_RE = re.compile(
    r"^Meistervorbereitung\s+"
    r"(?P<trade>.*?)\s*"
    r"Teile?\s+(?P<parts>(?:IV|III|II|I)(?:\s*[-–]\s*(?:IV|III|II|I))*)",
    re.IGNORECASE,
)

PRICE_RE    = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_RE = re.compile(r"(\d+)[\s\xa0]*(?:UStd\.|Std\.|UE)", re.IGNORECASE)
DATE_RE     = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")

TRADE_ALIASES = {
    "Elektrotechniker":                "Elektrotechniker",
    "Kraftfahrzeugtechniker":          "Kfz.-Techniker",
    "KFZ-Techniker":                   "Kfz.-Techniker",
    "Friseure":                        "Friseur",
    "Friseur":                         "Friseur",
    "Installateure und Heizungsbauer": "Installateur- und Heizungsbauer",
    "Installateur- und Heizungsbauer": "Installateur- und Heizungsbauer",
    "Installateur und Heizungsbauer":  "Installateur- und Heizungsbauer",
    "Maler und Lackierer":             "Maler und Lackierer",
    "Maurer und Betonbauer":           "Maurer und Betonbauer",
    "Metallbauer":                     "Metallbauer",
    "Tischler":                        "Tischler",
    "Zimmerer":                        "Zimmerer",
    "Dachdecker":                      "Dachdecker",
    "Elektroniker":                    "Elektrotechniker",
    "Sanitär- und Heizungstechnik":    "Installateur- und Heizungsbauer",
    "SHK":                             "Installateur- und Heizungsbauer",
}


def parse_pfalz_title(raw_title: str) -> tuple[list[int], str | None]:
    """
    Parse HWK Pfalz title like "Meistervorbereitung Kraftfahrzeugtechniker Teil II".
    Returns (parts, canonical_trade_name).
    Parts separator is " - " (hyphen), e.g. "Teile III - IV" → [3, 4].
    """
    m = PFALZ_TITLE_RE.match(raw_title.strip())
    if not m:
        return [], None

    trade_raw = m.group("trade").strip()
    trade_name = TRADE_ALIASES.get(trade_raw, trade_raw) if trade_raw else None

    parts = []
    for token in re.split(r"\s*[-–]\s*", m.group("parts")):
        token = token.strip().upper()
        if token in ROMAN:
            parts.append(ROMAN[token])

    # Parts III/IV without a trade name → generic
    if trade_name and set(parts) <= {3, 4}:
        trade_name = None

    return sorted(parts), trade_name


def parse_price(text: str) -> float | None:
    m = PRICE_RE.search(text)
    return float(m.group(1).replace(".", "") + "." + m.group(2)) if m else None


def parse_duration(text: str) -> int | None:
    m = DURATION_RE.search(text)
    return int(m.group(1)) if m else None


def parse_format(text: str) -> str:
    lower = text.lower()
    positions: dict[int, str] = {}
    for key, val in FORMAT_MAP.items():
        pos = lower.find(key)
        if pos >= 0:
            positions[pos] = val
    return positions[min(positions)] if positions else "part_time"


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "warteliste"  in lower: return "waitlist"
    if "ausgebucht" in lower:   return "full"
    if "wenige"     in lower:   return "available"
    if "freie"      in lower:   return "available"
    return "unknown"


def parse_city(text: str) -> str:
    """
    City appears between the duration value and the availability keyword.
    Same positional approach as HWK Koblenz.
    """
    text = text.replace("\xa0", " ")
    dur_m   = DURATION_RE.search(text)
    avail_m = re.search(
        r"ausgebucht|warteliste|freie\s+Plätze|wenige\s+Plätze|Garantierte\s+Durchführung",
        text, re.IGNORECASE,
    )
    if dur_m and avail_m and dur_m.end() < avail_m.start():
        between = text[dur_m.end():avail_m.start()]
        valid = re.compile(r"^[A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-]+$")
        for line in between.split("\n"):
            line = line.strip()
            if line and 2 < len(line) < 60 and valid.match(line):
                return line
    return "Kaiserslautern"  # fallback: HWK Pfalz main location


class HwkPfalzScraper(BaseScraper):
    """
    Scraper for HWK der Pfalz.

    Two-pass strategy:
      Pass 1 (list pages): collect card metadata + detail URLs.
      Pass 2 (detail pages): fetch each detail page to get separate
                             Kurs/Prüfung fee breakdown.

    Exam fees are saved into ExamFee via _save_courses override (same as Trier).
    """

    chamber_slug    = "hwk-pfalz"
    chamber_name    = "Handwerkskammer der Pfalz"
    chamber_region  = "Rheinland-Pfalz"
    chamber_website = BASE_URL
    source_url      = LIST_URL.format(offset=0)
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        # --- Pass 1: list pages ---
        first = self.parse_html(LIST_URL.format(offset=0))
        if first is None:
            logger.error("Could not fetch HWK Pfalz course list.")
            return []

        total = self._parse_total(first)
        logger.info("HWK Pfalz: %d courses, %d page(s).",
                    total, -(-total // PAGE_SIZE))

        raw_cards = self._parse_page(first)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            soup = self.parse_html(LIST_URL.format(offset=offset))
            if soup is None:
                logger.warning("Failed at offset=%d, stopping.", offset)
                break
            raw_cards.extend(self._parse_page(soup))

        logger.info("HWK Pfalz: parsed %d cards from list pages.", len(raw_cards))

        # --- Pass 2: detail pages for fee breakdown ---
        offers: list[RawCourseOffer] = []
        for card in raw_cards:
            offer = self._enrich_with_detail(card)
            offers.append(offer)

        logger.info("HWK Pfalz: finalised %d course offers.", len(offers))
        return offers

    # ------------------------------------------------------------------
    # List page helpers
    # ------------------------------------------------------------------

    def _parse_total(self, soup: BeautifulSoup) -> int:
        m = re.search(r"von\s+(\d+);\s*Seite", soup.get_text())
        return int(m.group(1)) if m else len(soup.select("a[href*='coursedetail']"))

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards = []
        for link in soup.select("a[href*='coursedetail']"):
            try:
                card = self._parse_card(link)
                if card:
                    cards.append(card)
            except Exception as exc:
                logger.warning("Error parsing card '%s': %s",
                               link.get_text(strip=True)[:60], exc)
        return cards

    def _parse_card(self, link: Tag) -> dict | None:
        raw_title = link.get_text(strip=True)
        detail_url = link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        parts, trade_name = parse_pfalz_title(raw_title)
        if not parts:
            logger.debug("Could not parse parts from Pfalz title %r", raw_title)
            return None

        # Card container: div.row (Level 3 — same as Koblenz)
        card_row = link.find_parent("div", class_="row")
        if card_row is None:
            return None

        h3 = link.find_parent("h3")
        h3_text = h3.get_text(separator=" ", strip=True) if h3 else ""

        format_key = parse_format(h3_text)

        dates = DATE_RE.findall(h3_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if len(dates) >= 1 else None
        end_date   = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) >= 2 else None

        card_text = card_row.get_text(separator="\n", strip=True)

        # Combined price from list (inkl. Prüfung) — used as fallback
        combined_price = parse_price(card_text)
        duration_hours = parse_duration(card_text)
        city           = parse_city(card_text)
        availability   = parse_availability(card_text)

        # "Garantierte Durchführung" flag
        guaranteed = bool(re.search(r"Garantierte\s+Durchführung", card_text, re.IGNORECASE))

        return {
            "raw_title":      raw_title,
            "trade_name":     trade_name,
            "parts":          parts,
            "format_key":     format_key,
            "start_date":     start_date,
            "end_date":       end_date,
            "duration_hours": duration_hours,
            "combined_price": combined_price,   # includes exam fee
            "city":           city,
            "availability":   availability,
            "guaranteed":     guaranteed,
            "detail_url":     detail_url,
        }

    # ------------------------------------------------------------------
    # Pass 2: enrich one card with detail-page fee breakdown
    # ------------------------------------------------------------------

    def _enrich_with_detail(self, card: dict) -> RawCourseOffer:
        """
        Fetch the detail page and parse the Kurs/Prüfung breakdown.
        Falls back to combined_price if detail page is unavailable or
        if no breakdown pattern is found.
        """
        course_fee   = None
        exam_fee     = None

        # Known HWK Pfalz locations — used when page has no specific street
        CITY_DEFAULTS = {
            "kaiserslautern": ("Am Altenhof 15",    "67655", "Kaiserslautern"),
            "landau":         ("Im Grein 5",         "76829", "Landau in der Pfalz"),
            "ludwigshafen":   ("Karlsbader Str. 2",  "67065", "Ludwigshafen am Rhein"),
        }

        def city_default(city_name: str) -> tuple[str, str, str]:
            for key, vals in CITY_DEFAULTS.items():
                if key in city_name.lower():
                    return vals
            return CITY_DEFAULTS["kaiserslautern"]

        street, zip_code, city = city_default(card["city"] or "kaiserslautern")

        soup = self.parse_html(card["detail_url"])
        if soup:
            page_text = soup.get_text(separator="\n")
            kurs_m  = re.search(r"Kurs(?:gebühr)?:\s*([\d.]+),(\d{2})[\s\xa0]*€",
                                 page_text, re.IGNORECASE)
            pruef_m = re.search(r"Prüfung(?:sgebühr)?:\s*([\d.]+),(\d{2})[\s\xa0]*€",
                                 page_text, re.IGNORECASE)
            if kurs_m:
                course_fee = float(kurs_m.group(1).replace(".", "") + "." + kurs_m.group(2))
            if pruef_m:
                exam_fee = float(pruef_m.group(1).replace(".", "") + "." + pruef_m.group(2))

            # Extract Lehrgangsort address
            idx = page_text.find("Lehrgangsort")
            if idx >= 0:
                block = page_text[idx:idx + 300]
                zip_m = re.search(r"(\d{5})\s+([^\n]+)", block)
                if zip_m:
                    extracted_zip  = zip_m.group(1)
                    extracted_city = zip_m.group(2).strip()
                    lines = block[:zip_m.start()].strip().split("\n")
                    candidate = lines[-1].strip() if lines else ""
                    if candidate and re.search(r"\d", candidate):
                        # Full address found on page — use it
                        street, zip_code, city = candidate, extracted_zip, extracted_city
                    else:
                        # City/zip found but no street — use city default
                        street, zip_code, city = city_default(extracted_city)
                else:
                    # No zip in Lehrgangsort — keep card-city default (already set above)
                    pass

        # Fallback: use combined price if no breakdown found
        if course_fee is None:
            course_fee = card["combined_price"]

        notes = "Garantierte Durchführung" if card["guaranteed"] else ""

        return RawCourseOffer(
            title=build_course_title(card["trade_name"], card["parts"]),
            trade_name=card["trade_name"],
            parts=card["parts"],
            format_key=card["format_key"],
            teaching_mode="presence",    # Pfalz courses are all Präsenz
            start_date=card["start_date"],
            end_date=card["end_date"],
            duration_hours=card["duration_hours"],
            course_fee=course_fee,
            city=city,
            street=street,
            zip_code=zip_code,
            exam_fee_scraped=exam_fee,
            availability=card["availability"],
            source_url=card["detail_url"],
            scraped_raw={
                "raw_title":      card["raw_title"],
                "combined_price": card["combined_price"],
                "course_fee":     course_fee,
                "exam_fee":       exam_fee,
            },
        )