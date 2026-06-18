"""
scraper/hwk_saarland.py — HWK Saarland

Page structure (WordPress, www.hwk-saarland.de):
  - portal.hwk-saarland.de/seminar/* all redirect 301 → www.hwk-saarland.de/seminar/*
  - Price:        "Unterrichtsgebühr: zurzeit 1.390€"
  - Exam fee:     "Prüfungsgebühr: zurzeit 560€"
  - Date:         "Ab April 2027"  (first of that month)
  - Availability: "Noch 1 freier Platz" / "Es gibt noch freie Plätze" / "Ausgebucht"
  - Duration:     "520 Unterrichtseinheiten à 45 Minuten"
  - Location:     always Saarbrücken
"""

import re
from datetime import date
from decimal import Decimal
from typing import Optional

from bs4 import BeautifulSoup

import logging
logger = logging.getLogger(__name__)

from .base import BaseScraper, RawCourseOffer, build_course_title

BASE = "https://www.hwk-saarland.de"

# HWK Saarland — Hohenzollernstraße 47-49, 66117 Saarbrücken
HWK_SAARLAND_LAT = 49.2297
HWK_SAARLAND_LNG = 6.9967

MONTH_DE = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

TRADE_ALIASES: dict[str, str] = {
    "Kraftfahrzeugtechniker": "Kfz.-Techniker",
    "Friseure": "Friseur",
    "Konditor": "Konditor",
    "Maurer und Betonbauer": "Maurer und Betonbauer",
    "Fliesen-, Platten- und Mosaikleger": "Fliesen-, Platten- und Mosaikleger",
}

# (slug, trade_name_or_None, parts, format)
# trade_name=None → generic course (Teil III / IV)
# All slugs resolve to www.hwk-saarland.de/seminar/{slug}/
TRADE_PAGES: list[tuple] = [
    # ── Berufsbegleitend / Teilzeit — Teil I ────────────────────────
    ("mv-teil-i-baecker-m1ba",                         "Bäcker",                            [1], "part_time"),
    ("mv-teil-i-dachdecker-m1da",                      "Dachdecker",                        [1], "part_time"),
    ("mv-teil-i-elektrotechniker-m1et",                "Elektrotechniker",                  [1], "part_time"),
    ("mv-fahrzeuglackierer-teil-i-m1fa",               "Fahrzeuglackierer",                 [1], "part_time"),
    ("mv-teil-i-feinwerkmechaniker-m1fm",              "Feinwerkmechaniker",                [1], "part_time"),
    ("mv-teil-i-fliesenleger-m1fl",                    "Fliesen-, Platten- und Mosaikleger", [1], "part_time"),
    ("mv-teil-i-installateur-und-heizungsbauer-m1ih",  "Installateur und Heizungsbauer",    [1], "part_time"),
    ("mv-teil-i-kraftfahrzeugtechniker-m1km",          "Kraftfahrzeugtechniker",            [1], "part_time"),
    ("mv-teil-i-maler-und-lackierer-m1ml",             "Maler und Lackierer",               [1], "part_time"),
    ("mv-teil-i-maurer-m1ma",                          "Maurer und Betonbauer",             [1], "part_time"),
    ("mv-teil-i-metallbauer-m1mb",                     "Metallbauer",                       [1], "part_time"),
    ("mv-teil-i-strassenbauer-m1sb",                   "Straßenbauer",                      [1], "part_time"),
    ("m1st",                                            "Stuckateure",                       [1], "part_time"),
    ("mv-teil-i-tischler-m1ti",                        "Tischler",                          [1], "part_time"),
    ("mv-konditoren-teil-i-m1ko",                      "Konditor",                          [1], "part_time"),
    # I + II combined (only offered as combo)
    ("friseure-teil-i-und-ii-montagsklasse-msfrmo",    "Friseur",                           [1, 2], "part_time"),
    ("mv-schornsteinfeger-teil-i-ii-m2sf",             "Schornsteinfeger",                  [1, 2], "part_time"),

    # ── Berufsbegleitend / Teilzeit — Teil II ───────────────────────
    ("mv-teil-ii-baecker-m2ba",                        "Bäcker",                            [2], "part_time"),
    ("mv-teil-ii-dachdecker-m2da",                     "Dachdecker",                        [2], "part_time"),
    ("mv-teil-ii-elektrotechniker-m2et",               "Elektrotechniker",                  [2], "part_time"),
    ("mv-teil-ii-feinwerkmechaniker-m2fm1",            "Feinwerkmechaniker",                [2], "part_time"),
    ("mv-teil-ii-fliesenleger-m2fl",                   "Fliesen-, Platten- und Mosaikleger", [2], "part_time"),
    ("mv-teil-ii-installateur-und-heizungsbauer-m2ih", "Installateur und Heizungsbauer",    [2], "part_time"),
    ("mv-teil-ii-kraftfahrzeugtechniker-m2km",         "Kraftfahrzeugtechniker",            [2], "part_time"),
    ("mv-teil-ii-maler-und-lackierer-m2ml",            "Maler und Lackierer",               [2], "part_time"),
    ("mv-teil-ii-maurer-und-betonbauer-m2ma",          "Maurer und Betonbauer",             [2], "part_time"),
    ("mv-teil-ii-metallbauer-m2mb",                    "Metallbauer",                       [2], "part_time"),
    ("mv-teil-ii-strassenbauer-m2sb",                  "Straßenbauer",                      [2], "part_time"),
    ("mv-teil-ii-stuckateure-m2st1",                   "Stuckateure",                       [2], "part_time"),
    ("mv-teil-ii-tischler-m2ti",                       "Tischler",                          [2], "part_time"),
    ("mv-teil-ii-konditoren-m2ko",                     "Konditor",                          [2], "part_time"),

    # ── Generic — Teil III + IV ──────────────────────────────────────
    ("m3",                                              None,                                [3], "part_time"),
    ("mv-teil-iv-ada-m4tz",                            None,                                [4], "part_time"),
    ("mv-teil-iv-m4vz",                                None,                                [4], "full_time"),

    # ── Vollzeit — Teile I + II (III + IV are taken separately) ─────
    ("ms-tischler-vollzeit-msvzti",                    "Tischler",                          [1, 2, 3, 4], "full_time"),
    ("ms-kraftfahrzeugtechnik-vollzeit-msvzkfz",       "Kraftfahrzeugtechniker",            [1, 2, 3, 4], "full_time"),
    ("ms-metallbauer-vz-msvzmb",                       "Metallbauer",                       [1, 2, 3, 4], "full_time"),
    ("ms-feinwerkmechaniker-vz-msvzfm",                "Feinwerkmechaniker",                [1, 2, 3, 4], "full_time"),
    ("ms-installateur-und-heizungsbauer-vz-msvzshk",   "Installateur und Heizungsbauer",    [1, 2, 3, 4], "full_time"),
    ("ms-elektrotechnik-vollzeit-msvzet",              "Elektrotechniker",                  [1, 2, 3, 4], "full_time"),
    ("ms-maler-und-lackierer-vz-msvzml",               "Maler und Lackierer",               [1, 2, 3, 4], "full_time"),
    ("ms-friseure-vollzeit-msvzfri",                   "Friseur",                           [1, 2, 3, 4], "full_time"),
]


class HwkSaarlandScraper(BaseScraper):
    chamber_slug    = "hwk-saarland"
    chamber_name    = "Handwerkskammer des Saarlandes"
    chamber_region  = "Saarland"
    chamber_website = BASE

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for slug, trade_name, parts, fmt in TRADE_PAGES:
            url = f"{BASE}/seminar/{slug}/"
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}: {url}")
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                raw_list = self._parse_page(soup, url, trade_name, parts, fmt)
                if raw_list:
                    offers.extend(raw_list)
                    for raw in raw_list:
                        logger.info(
                            f"  {raw.title} | {raw.start_date}"
                            f"{' bis ' + str(raw.end_date) if raw.end_date else ''} | "
                            f"Kurs: {raw.course_fee} € | "
                            f"Pruef: {raw.exam_fee_scraped} € | {raw.availability}"
                        )
            except Exception as exc:
                logger.error(f"Error scraping {url}: {exc}")
        return offers

    # ── Page parser ──────────────────────────────────────────────────

    def _parse_page(
        self,
        soup: BeautifulSoup,
        url: str,
        trade_name: Optional[str],
        parts: list[int],
        fmt: str,
    ) -> list[RawCourseOffer]:
        """Return one RawCourseOffer per course run found on the page."""
        resolved = TRADE_ALIASES.get(trade_name, trade_name) if trade_name else None
        text = soup.get_text("\n")
        title         = build_course_title(resolved, parts)
        course_fee    = self._parse_course_fee(text)
        exam_fee      = self._parse_exam_fee(text)
        duration_hrs  = self._parse_duration(text)

        addr = self._parse_address(text)
        runs = self._parse_runs(text)

        if not runs:
            # Fallback: single entry — only if start date is in the future or None
            fb_start = self._parse_date(text)
            if fb_start and fb_start < date.today():
                fb_start = None  # discard past dates
            fb_end = self._parse_end_date(text)
            return [RawCourseOffer(
                trade_name=resolved, title=title, parts=parts, format_key=fmt,
                start_date=fb_start, end_date=fb_end,
                course_fee=course_fee, exam_fee_scraped=exam_fee,
                duration_hours=duration_hrs, availability=self._parse_availability(text),
                teaching_mode="presence",
                city=addr["city"], street=addr["street"], zip_code=addr["zip_code"],
                source_url=url,
            )]

        return [
            RawCourseOffer(
                trade_name=resolved, title=title, parts=parts, format_key=fmt,
                start_date=run["start"], end_date=run["end"],
                course_fee=course_fee, exam_fee_scraped=exam_fee,
                duration_hours=duration_hrs, availability=run["availability"],
                teaching_mode="presence",
                city=addr["city"], street=addr["street"], zip_code=addr["zip_code"],
                source_url=url,
            )
            for run in runs
        ]

    def _parse_runs(self, text: str) -> list[dict]:
        """
        Each "Termin im Kalender speichern" marks one course run.
        Strategy 1: look for "DD.MM.YYYY bis DD.MM.YYYY" near each marker.
        Strategy 2: single DD.MM.YYYY per marker (tight 200-char window).
        Strategy 3: "Ab Monat Jahr" patterns (for pages without full dates).
        Only future start dates are used; past dates are discarded.
        """
        today = date.today()
        runs = []
        segments = re.split(r"Termin im Kalender speichern", text)

        def to_date(d, m, y):
            try:
                return date(int(y), int(m), int(d))
            except ValueError:
                return None

        # ── Strategy 0: "DD.MM.YYYY — DD.MM.YYYY" (em/en-dash) ───────
        # HWK Saarland right-column format: "19.10.2026 — 17.01.2028\nKurstyp: ..."
        dash_re = re.compile(
            r"(\d{2})\.(\d{2})\.(\d{4})\s*[\u2013\u2014\-]\s*(\d{2})\.(\d{2})\.(\d{4})"
        )
        for mm in dash_re.finditer(text):
            start = to_date(mm.group(1), mm.group(2), mm.group(3))
            end   = to_date(mm.group(4), mm.group(5), mm.group(6))
            if not start or start < today:
                continue
            ctx   = text[mm.end():mm.end() + 300]
            avail = self._parse_availability(ctx)
            runs.append({"start": start, "end": end, "availability": avail})
        if runs:
            return runs

        # ── Strategy 1: "DD.MM.YYYY bis DD.MM.YYYY" ──────────────────
        range_re = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+bis\s+(\d{2})\.(\d{2})\.(\d{4})")
        for i, seg in enumerate(segments[:-1]):
            m = range_re.search(seg[-300:])
            if m:
                start = to_date(m.group(1), m.group(2), m.group(3))
                end   = to_date(m.group(4), m.group(5), m.group(6))
                if start and start >= today:
                    next_seg = segments[i + 1][:400]
                    runs.append({"start": start, "end": end,
                                 "availability": self._parse_availability(next_seg)})
        if runs:
            return runs

        # ── Strategy 2: single DD.MM.YYYY per marker ─────────────────
        for i, seg in enumerate(segments[:-1]):
            found = []
            for d, m, y in re.findall(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", seg[-200:]):
                dt = to_date(d, m, y)
                if dt and dt >= today:
                    found.append(dt)
            if not found:
                continue
            start = min(found)
            next_seg = segments[i + 1][:400]
            runs.append({"start": start, "end": None,
                         "availability": self._parse_availability(next_seg)})
        if runs:
            return runs

        # ── Strategy 3: find all "Ab Monat Jahr" in full text ──────
        month_re = re.compile(
            r"Ab\s+(Januar|Februar|M\xe4rz|April|Mai|Juni|Juli|August|"
            r"September|Oktober|November|Dezember)\s+(\d{4})",
            re.IGNORECASE,
        )
        seen_starts = set()
        for mm in month_re.finditer(text):
            start = date(int(mm.group(2)), MONTH_DE[mm.group(1)], 1)
            if start < today or start in seen_starts:
                continue
            seen_starts.add(start)
            # Look at surrounding 400 chars (before + after) for availability
            ctx_start = max(0, mm.start() - 200)
            ctx_end   = min(len(text), mm.end() + 300)
            avail = self._parse_availability(text[ctx_start:ctx_end])
            runs.append({"start": start, "end": None, "availability": avail})

        # Deduplicate: same start_date appearing multiple times on same page
        seen_starts = set()
        deduped = []
        for r in runs:
            if r["start"] not in seen_starts:
                seen_starts.add(r["start"])
                deduped.append(r)
        return deduped


    # ── Address helpers ──────────────────────────────────────────────

    def _parse_address(self, text: str) -> dict:
        """All HWK Saarland courses take place at the HWK headquarters."""
        return {
            "city":     "Saarbrücken",
            "zip_code": "66117",
            "street":   "Hohenzollernstraße 47-49",
        }

    # ── Fee helpers ──────────────────────────────────────────────────

    def _parse_course_fee(self, text: str) -> Optional[Decimal]:
        # "Unterrichtsgebühr: zurzeit 1.390€"
        m = re.search(
            r"Unterrichtsgebühr[^€\n]*?zurzeit\s*([\d.]+)\s*€",
            text, re.IGNORECASE,
        )
        if m:
            return self._to_decimal(m.group(1))
        # fallback: "1390,00 €" after "Kosten" block
        m2 = re.search(r"([\d]{1,2}\.[\d]{3}|[\d]{3,5}),00\s*€", text)
        if m2:
            return self._to_decimal(m2.group(1))
        return None

    def _parse_exam_fee(self, text: str) -> Optional[Decimal]:
        # "Prüfungsgebühr: zurzeit 560€"
        m = re.search(
            r"Prüfungsgebühr[^€\n]*?zurzeit\s*([\d.]+)\s*€",
            text, re.IGNORECASE,
        )
        return self._to_decimal(m.group(1)) if m else None

    @staticmethod
    def _to_decimal(raw: str) -> Optional[Decimal]:
        try:
            return Decimal(raw.replace(".", "").replace(",", "."))
        except Exception:
            return None

    # ── Date helper ──────────────────────────────────────────────────

    def _parse_date(self, text: str) -> Optional[date]:
        """
        Try DD.MM.YYYY first (exact date), then fall back to "Ab Monat Jahr"
        (first of that month). Returns the earliest future-leaning date found.
        """
        # Collect all DD.MM.YYYY dates on the page
        dmy = re.findall(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
        if dmy:
            dates = []
            for d, m, y in dmy:
                try:
                    dates.append(date(int(y), int(m), int(d)))
                except ValueError:
                    pass
            if dates:
                return min(dates)  # earliest = start date
        # Fallback: "Ab Monat Jahr"
        m2 = re.search(
            r"Ab\s+(Januar|Februar|März|April|Mai|Juni|Juli|August|"
            r"September|Oktober|November|Dezember)\s+(\d{4})",
            text,
        )
        if m2:
            return date(int(m2.group(2)), MONTH_DE[m2.group(1)], 1)
        return None

    def _parse_end_date(self, text: str) -> Optional[date]:
        """Return the latest DD.MM.YYYY date on the page as end date."""
        dmy = re.findall(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
        if len(dmy) < 2:
            return None
        dates = []
        for d, m, y in dmy:
            try:
                dates.append(date(int(y), int(m), int(d)))
            except ValueError:
                pass
        if len(dates) < 2:
            return None
        return max(dates)  # latest = end date

    # ── Duration helper ──────────────────────────────────────────────

    def _parse_duration(self, text: str) -> Optional[int]:
        m = re.search(r"(\d{2,4})\s+Unterrichtseinheiten\s+à\s+45\s+Minuten", text)
        if not m:
            return None
        ue = int(m.group(1))
        return ue  # store UE count as-is, same as other scrapers

    # ── Availability helper ──────────────────────────────────────────

    def _parse_availability(self, text: str) -> str:
        t = text.lower()
        if "ausgebucht" in t:
            return "full"
        if "warteliste" in t:
            return "waitlist"
        # "Noch 1 freier Platz" or "Noch 3 freie Plätze"
        m = re.search(r"noch\s+(\d+)\s+freie?r?\s+pl[äa]tze?", t)
        if m:
            return "available" if int(m.group(1)) <= 3 else "available"
        if re.search(r"es gibt noch freie plätze|freie plätze vorhanden", t):
            return "available"
        return "unknown"