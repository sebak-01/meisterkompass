"""
scrapers/hwk_kassel.py

Scraper for Handwerkskammer Kassel Meistervorbereitungskurse.

Unlike the other RLP/Saarland chambers, HWK Kassel does not run its own
course-listing CMS. Courses are delivered by eight independent education
providers (https://www.hwk-kassel.de/weiterbildung/bildungszentren-kurse),
each with its own website. This module is structured so each provider gets
its own self-contained fetch method; a failure in one provider is logged
and skipped rather than aborting the whole chamber scrape.

Providers (verified 2026-07-09):
  - BZ Bildungszentrum Kassel GmbH   — bz-kassel.de            [IMPLEMENTED]
  - Berufsbildungszentrum Marburg    — bbz-marburg.de          [IMPLEMENTED]
  - Bubiza (Zimmerer/Ausbau)         — bubiza.de               [IMPLEMENTED]
  - FTZ / Innung Kfz-Gewerbe Kassel  — kfz-innung-kassel.de    [BLOCKED: info page only]
  - BBZ Mitte GmbH                   — bbz-mitte.de            [BLOCKED: JS-rendered]
  - Kreishandwerkerschaft Waldeck-Frankenberg — khkb.de        [BLOCKED: PDF-only]
  - Holzfachschule Bad Wildungen     — holzfachschule.de       [BLOCKED: JS/JSF]
  - Beratungsstelle Handwerk u. Denkmalpflege — denkmalpflegeberatung.de
    (no Meistervorbereitungskurse offered — intentionally not scraped)

BZ Bildungszentrum Kassel GmbH (bz-kassel.de):
  - TYPO3 CMS. A single, non-paginated course listing at
    /bildungsangebot/kurs-suchen/ lists every current course (all subjects,
    not just Meisterkurse) as a table: title link / Unterrichtsform /
    Beginn / Entgelt.
  - Each course's "kursdetail" page (URL pattern
    bz-kassel.de/bildungsangebot/<category-slug>/kursdetail/kurs-<id>)
    contains a "Kursinformationen" key/value table with the authoritative
    Lehrgangsdauer (start - end), Lehrgangsgebühr, Unterrichtsstunden and
    Unterrichtsform. Its "Prüfungsgebühr" field is always 0,00 € — BZ Kassel
    does not collect/display the HWK exam fee, so it is NOT used.

Berufsbildungszentrum Marburg GmbH (bbz-marburg.de):
  - WordPress. The custom-post-type archive at /kurs/?post_types=kurs
    renders every current course (all subjects) server-side as a single
    non-paginated page. Each course card has a title, short description,
    an "Eckdaten" table (Dauer/Intervall/Kosten) and a "Details" link to
    /kurs/<slug>/. (The JS-rendered /kursangebote/ search page must NOT be
    used as the listing URL — it renders its results client-side and is
    invisible to BeautifulSoup.)
  - Filtering: a course is treated as a Meisterkurs if its title contains
    "meister" (case-insensitive) — this also catches AEVO/Ausbildereignung
    courses that double as Teil IV ("... Teil IV d. Meisterausbildung ...").
    "Industriemeister" courses are explicitly excluded: despite containing
    the substring "meister", Industriemeister is an IHK industrial-foreman
    qualification, not a HwO Meisterprüfung, and is out of scope.
  - Unlike BZ Kassel, course titles do NOT reliably state "Teil X" in a
    single uniform pattern — parts are parsed from a combination of title
    and body text, supporting plain lists ("Teil I und II"), comma lists
    ("Teile I, II und IV"), and bare parenthesised ranges ("(I-IV)" → all
    of I..IV inclusive).
  - The Eckdaten table has no start date. The actual scheduled run(s) live
    further down each detail page under "Verfügbare Kurse" as one or more
    "DD.MM.YYYY - DD.MM.YYYY" ranges; a course with no currently scheduled
    run yields a single dateless (start_date=None) offer so its price still
    appears in comparisons, mirroring the HWK Rheinhessen fallback pattern.

Exam fees:
  HWK Kassel publishes one fee schedule per Meisterprüfung part that is
  (https://www.hwk-kassel.de/weiterbildung/meister/-in-im-handwerk,
  verified 2026-06-24). Because this is chamber-wide rather than per-offer,
  it is injected as trade_slug=None rows via an overridden collect() rather
  than via exam_fee_scraped on individual offers (see CLAUDE.md notes on
  the HWK Kassel double-counting/placement pattern).
"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# BZ Bildungszentrum Kassel GmbH
# ----------------------------------------------------------------------

BZ_BASE      = "https://www.bz-kassel.de"
BZ_LIST_URL  = f"{BZ_BASE}/bildungsangebot/kurs-suchen/"

# BZ Kassel's HQ — used as the default location for all its courses since
# "Lehrgangsort" on detail pages is just a venue label ("BZ Kassel"), not a
# full street address.
BZ_DEFAULT_STREET = "Falderbaumstraße 18-20"
BZ_DEFAULT_ZIP     = "34123"
BZ_DEFAULT_CITY    = "Kassel"

FORMAT_MAP = {
    "vollzeit": "full_time",
    "teilzeit": "part_time",
}

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
_ROMAN_ALT  = r"(?:IV|III|II|I)"
_PARTS_SEP  = r"(?:\s*(?:\+|und)\s*)"
_PARTS_PAT  = rf"{_ROMAN_ALT}(?:{_PARTS_SEP}{_ROMAN_ALT})*"

# "Meistervorbereitungslehrgang im Elektrotechnikerhandwerk Teil I und II TZ 2026"
# "Meistervorbereitungslehrgang Feinwerkmechanikerhandwerk Teil I und II 2027"
# "Meistervorbereitungslehrgang Maler- und Lackiererhandwerk Teil I und II VZ 2027"
# "Meistervorbereitungslehrgang Teil III VZ Klasse 2"   (no trade -> generic)
TITLE_RE = re.compile(
    rf"^Meistervorbereitungslehrgang\s+(?:im\s+)?(?:(?P<trade>.+?)handwerk\s+)?"
    rf"Teil(?:e)?\s+(?P<parts>{_PARTS_PAT})",
    re.IGNORECASE,
)

TRADE_ALIASES = {
    "Elektrotechniker":       "Elektrotechniker",
    "Fleischer":              "Fleischer",
    "Friseur":                "Friseur",
    "Metallbauer":            "Metallbauer",
    "Feinwerkmechaniker":     "Feinwerkmechaniker",
    "Maler- und Lackierer":   "Maler und Lackierer",
    "Maler und Lackierer":    "Maler und Lackierer",
}

# Cents are optional: BZ Kassel always shows them ("9.450,00 €"), BBZ Marburg
# never does ("4.710 €") — both are handled by the same parse_price().
PRICE_RE       = re.compile(r"([\d.]+)(?:,(\d{2}))?\s*€")
DATE_RANGE_RE  = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4})")
DATE_SINGLE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_bz_title(title: str) -> tuple[list[int], str | None]:
    """
    Parse a BZ Kassel "Meistervorbereitungslehrgang" title into
    (parts, trade_name). Returns ([], None) if it isn't a recognised
    Meistervorbereitungslehrgang title.
    """
    m = TITLE_RE.match(title.strip())
    if not m:
        return [], None

    parts_str = m.group("parts").upper()
    parts = []
    for token in re.split(r"\s*(?:\+|UND)\s*", parts_str):
        token = token.strip()
        if token in ROMAN:
            parts.append(ROMAN[token])

    trade_raw = (m.group("trade") or "").strip()
    trade_name = TRADE_ALIASES.get(trade_raw, trade_raw) if trade_raw else None

    # Parts III/IV are trade-independent even if a trade phrase slipped through.
    if trade_name and set(parts) <= {3, 4}:
        trade_name = None

    return sorted(set(parts)), trade_name


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    if "kostenlos" in text.lower():
        return 0.0
    # Pattern 1: € after number — "9.450,00 €" / "4.710 €"
    m = re.search(r"([\d.]+)(?:,(\d{2}))?\s*€", text)
    if m:
        return float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
    # Pattern 2: € before number — "€ 9.450,00" (BZ Kassel table header style)
    m = re.search(r"€\s*([\d.]+)(?:,(\d{2}))?", text)
    if m:
        return float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
    # Pattern 3: plain German decimal without any € sign — "9.450,00"
    # (BZ Kassel puts € in the key label, leaving only the bare number as value)
    # Require either thousands-dot grouping or explicit comma-cents to avoid
    # false matches on plain integers.
    m = re.search(r"\b(\d{1,3}(?:\.\d{3})*),(\d{2})\b", text)
    if m:
        return float(m.group(1).replace(".", "") + "." + m.group(2))
    return None


def parse_date_range(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    m = DATE_RANGE_RE.search(text)
    if m:
        start = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        end   = f"{m.group(6)}-{m.group(5)}-{m.group(4)}"
        return start, end
    m2 = DATE_SINGLE_RE.search(text)
    if m2:
        return f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}", None
    return None, None


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------
# Bubiza (Zimmerer/Ausbaugewerbe)
# ----------------------------------------------------------------------

BUBIZA_BASE     = "https://www.bubiza.de"
BUBIZA_LIST_URL = f"{BUBIZA_BASE}/kurse/vollzeit-hoehere-berufsbildung.html"

BUBIZA_DEFAULT_STREET = "Auedamm 18"
BUBIZA_DEFAULT_ZIP    = "34123"
BUBIZA_DEFAULT_CITY   = "Kassel"


def _parse_bubiza_label_parts(text: str) -> list[int]:
    """Extract Meisterprüfung parts from a Bubiza Kosten/Termine line label.
    The label must lead the line as "Teil(e) …" or "T[.] …", e.g.
    "Teile I+II" → [1,2], "T I - IV" → [1,2,3,4], "Teil III" → [3].
    Returns [] when the line carries no leading part label (so a bare dated
    run or a flat price line is not misread as covering some parts)."""
    m = re.match(
        rf"\s*(?:Teile?|T\.?)\s+(?P<p>{_ROMAN_ALT}(?:\s*(?:[-–+]|und|bis)\s*{_ROMAN_ALT})*)",
        text, re.I,
    )
    if not m:
        return []
    raw = m.group("p").upper()
    rng = re.search(rf"({_ROMAN_ALT})\s*(?:-|–|BIS)\s*({_ROMAN_ALT})", raw)
    if rng:
        lo, hi = sorted((ROMAN[rng.group(1)], ROMAN[rng.group(2)]))
        return list(range(lo, hi + 1))
    tokens = re.split(r"\s*(?:\+|UND)\s*", raw)
    return sorted({ROMAN[t] for t in tokens if t in ROMAN})


def _parse_bubiza_price(text: str) -> float | None:
    """Parse a Bubiza "zzt. 10.490,00 Euro" / "zzt. 7.990,- Euro" price."""
    m = re.search(r"zzt\.\s*([\d.]+)(?:,(\d{2})|,-|-)?\s*Euro", text, re.I)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))


def _parse_bubiza_sub(text: str) -> str | None:
    """Return the run sub-type ("grund"/"aufbau") when a part-group has more
    than one scheduling variant on the same page, else None."""
    m = re.search(r"\b(Grund|Aufbau)", text, re.I)
    return m.group(1).lower() if m else None


def _extract_bubiza_trade(title: str) -> str | None:
    """Extract the trade name from a Bubiza Meisterkurs title.
    Maps 'Zimmermeister' → 'Zimmerer', 'Dachdeckermeister' → 'Dachdecker'."""
    t = title.lower()
    if "zimm" in t:
        return "Zimmerer"
    if "dachdeck" in t:
        return "Dachdecker"
    return None


# ----------------------------------------------------------------------
# Berufsbildungszentrum Marburg GmbH
# ----------------------------------------------------------------------

BBZ_BASE      = "https://www.bbz-marburg.de"
# /kursangebote/ is a JS-filtered search page whose course list is rendered
# client-side and therefore invisible to BeautifulSoup. The WordPress custom-
# post-type archive at /kurs/?post_types=kurs renders all courses server-side
# as a single static page — confirmed by direct fetch (2026-07-03).
BBZ_LIST_URL  = f"{BBZ_BASE}/kurs/?post_types=kurs"

BBZ_DEFAULT_STREET = "Umgehungsstraße 1-3"
BBZ_DEFAULT_ZIP     = "35043"
BBZ_DEFAULT_CITY    = "Marburg"

# A course qualifies as a Meisterkurs if "meister" appears in its title —
# this also catches AEVO courses that double as Teil IV ("... Teil IV d.
# Meisterausbildung ..."). "Industriemeister" (an IHK foreman qualification,
# unrelated to the HwO Meisterprüfung) is explicitly excluded even though
# it contains the substring "meister".
MEISTER_RE                   = re.compile(r"meister", re.IGNORECASE)
EXCLUDE_INDUSTRIEMEISTER_RE  = re.compile(r"industriemeister", re.IGNORECASE)

# "Teil I und II", "Teile I, II und IV", "Teil IV d. Meisterausbildung"
PARTS_LIST_RE = re.compile(
    rf"Teile?\s+(?P<list>{_ROMAN_ALT}(?:\s*(?:,|\+|und)\s*{_ROMAN_ALT})*)",
    re.IGNORECASE,
)
# Bare parenthesised range with no "Teil" keyword, e.g. "(I-IV)" — inclusive.
RANGE_RE = re.compile(rf"({_ROMAN_ALT})\s*(?:[-–]|bis)\s*({_ROMAN_ALT})", re.IGNORECASE)

BBZ_TRADE_ALIASES = {
    "Friseur":                          "Friseur",
    "Kfz-Techniker":                    "Kfz.-Techniker",
    "Maler + Lackierer":                "Maler und Lackierer",
    "Installateur- und Heizungsbauer":  "Installateur- und Heizungsbauer",
}


def parse_parts_from_text(text: str) -> list[int]:
    """
    Parse Meisterprüfung parts out of free text. Tries the explicit
    "Teil(e) <list>" pattern first (handles "und"/"+"/"," separated lists,
    e.g. "Teile I, II und IV"), then falls back to a bare parenthesised
    roman-numeral range like "(I-IV)", which is treated as inclusive of
    every part between the two ends.
    """
    list_m = PARTS_LIST_RE.search(text)
    if list_m:
        tokens = re.split(r"\s*(?:,|\+|und)\s*", list_m.group("list"), flags=re.IGNORECASE)
        parts = sorted({ROMAN[t.upper()] for t in tokens if t.upper() in ROMAN})
        if parts:
            return parts

    range_m = RANGE_RE.search(text)
    if range_m:
        a, b = range_m.group(1).upper(), range_m.group(2).upper()
        lo, hi = sorted((ROMAN[a], ROMAN[b]))
        return list(range(lo, hi + 1))

    return []


def extract_bbz_trade(title: str) -> str | None:
    """
    Pull the trade name out of a BBZ Marburg "Meistervorbereitung ..."
    title, e.g. "Meistervorbereitung Kfz-Techniker (I-IV) Vollzeit" ->
    "Kfz-Techniker". Returns None for generic titles with no trade phrase
    (e.g. "Meistervorbereitung Teil III - Teilzeit").
    """
    if not title.lower().startswith("meistervorbereitung"):
        return None
    rest = title[len("meistervorbereitung"):].strip()
    rest = re.sub(r"\([^)]*\)", " ", rest)                                  # "(Teil I und II)" / "(I-IV)"
    rest = re.sub(r"\b(?:Teilzeit|Vollzeit)\b", " ", rest, flags=re.IGNORECASE)
    rest = re.sub(r"[-–]?\s*Handwerk\s*$", "", rest.strip(), flags=re.IGNORECASE)
    rest = re.sub(r"\bTeile?\b.*$", "", rest, flags=re.IGNORECASE)          # trailing "Teil ..." -> generic
    rest = rest.strip(" -–\t")
    return rest or None


def parse_format_from_text(text: str) -> str:
    """Return format based on the FIRST matching keyword in text."""
    lower = text.lower()
    positions: dict[int, str] = {}
    for key, val in FORMAT_MAP.items():
        pos = lower.find(key)
        if pos >= 0:
            positions[pos] = val
    return positions[min(positions)] if positions else "part_time"


class HwkKasselScraper(BaseScraper):
    chamber_slug    = "hwk-kassel"
    chamber_name    = "Handwerkskammer Kassel"
    chamber_region  = "Hessen"
    chamber_website = "https://www.hwk-kassel.de"
    source_url      = BZ_LIST_URL
    request_delay   = 1.2

    # Generic (trade-independent) Meisterprüfung exam fees — identical for
    # every trade and provider in the HWK Kassel district.
    # Source: https://www.hwk-kassel.de/weiterbildung/meister/-in-im-handwerk
    # (verified 2026-06-24).
    EXAM_FEES_SOURCE_URL = "https://www.hwk-kassel.de/weiterbildung/meister/-in-im-handwerk"
    EXAM_FEES: dict[int, float] = {1: 420.0, 2: 420.0, 3: 340.0, 4: 235.0}

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []

        # ---- Provider: BZ Bildungszentrum Kassel GmbH ----------------
        try:
            bz_offers = self._fetch_bz_kassel()
            logger.info("HWK Kassel/BZ Kassel: %d course offers.", len(bz_offers))
            offers.extend(bz_offers)
        except Exception:
            logger.exception("HWK Kassel/BZ Kassel: provider failed — skipping.")

        # ---- Provider: Berufsbildungszentrum Marburg GmbH -------------
        try:
            bbz_offers = self._fetch_bbz_marburg()
            logger.info("HWK Kassel/BBZ Marburg: %d course offers.", len(bbz_offers))
            offers.extend(bbz_offers)
        except Exception:
            logger.exception("HWK Kassel/BBZ Marburg: provider failed — skipping.")

        # ---- Provider: Bubiza (Zimmerer/Ausbaugewerbe) ---------------
        try:
            bubiza_offers = self._fetch_bubiza()
            logger.info("HWK Kassel/Bubiza: %d course offers.", len(bubiza_offers))
            offers.extend(bubiza_offers)
        except Exception:
            logger.exception("HWK Kassel/Bubiza: provider failed — skipping.")

        # ---- Remaining providers: not yet implemented -----------------
        # Each should follow the same pattern: its own _fetch_<provider>()
        # method, wrapped in try/except here, contributing RawCourseOffers
        # to the same `offers` list.
        #   FTZ / Innung Kfz-Gewerbe Kassel — www.kfz-innung-kassel.de
        #     (info page only — no structured course listing; blocked)
        #   BBZ Mitte GmbH               — www.bbz-mitte.de
        #     (JS-rendered kursfinder; blocked on raw HTML / API endpoint)
        #   Kreishandwerkerschaft Waldeck-Frankenberg — www.khkb.de
        #     (Meistervorbereitungslehrgänge only via PDF; blocked)
        #   Holzfachschule Bad Wildungen — www.holzfachschule.de
        #     (PrimeFaces JSF; JS-rendered; blocked)

        logger.info("HWK Kassel: %d course offers total.", len(offers))
        return offers

    def collect(self) -> ScrapeResult:
        """Run the scrape, then inject the chamber-wide exam-fee schedule."""
        result = super().collect()
        result.exam_fee_rows.extend(
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug":   None,
                "part":         part,
                "fee":          fee,
                "source_url":   self.EXAM_FEES_SOURCE_URL,
            }
            for part, fee in self.EXAM_FEES.items()
        )
        return result

    # ------------------------------------------------------------------
    # BZ Bildungszentrum Kassel GmbH
    # ------------------------------------------------------------------

    def _fetch_bz_kassel(self) -> list[RawCourseOffer]:
        soup = self.parse_html(BZ_LIST_URL)
        if soup is None:
            logger.error("BZ Kassel: could not fetch course list at %s", BZ_LIST_URL)
            return []

        rows = self._collect_bz_meister_rows(soup)
        logger.info("BZ Kassel: %d Meistervorbereitungslehrgang row(s) found.", len(rows))

        offers: list[RawCourseOffer] = []
        for row in rows:
            try:
                offer = self._parse_bz_detail(row)
            except Exception as exc:
                logger.warning("BZ Kassel: error parsing %s: %s", row["detail_url"], exc)
                continue
            if offer:
                offers.append(offer)
        return offers

    def _collect_bz_meister_rows(self, soup: BeautifulSoup) -> list[dict]:
        """
        The course-search page lists every BZ Kassel course (all subjects)
        in one un-paginated table. Filter down to Meistervorbereitungslehrgang
        rows and capture each one's detail URL.
        """
        rows: list[dict] = []
        seen_urls: set[str] = set()

        for link in soup.select("a[href*='kursdetail']"):
            title = link.get_text(strip=True)
            if not title.startswith("Meistervorbereitungslehrgang"):
                continue

            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = BZ_BASE + href
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)

            rows.append({"title": title, "detail_url": href})

        return rows

    def _parse_bz_detail(self, row: dict) -> RawCourseOffer | None:
        parts, trade_name = parse_bz_title(row["title"])
        if not parts:
            logger.debug("BZ Kassel: could not parse parts from title %r", row["title"])
            return None

        soup = self.parse_html(row["detail_url"])
        if soup is None:
            logger.warning("BZ Kassel: could not fetch detail page %s", row["detail_url"])
            return None

        info = self._parse_bz_info_table(soup)

        start_date, end_date = parse_date_range(info.get("Lehrgangsdauer"))
        course_fee            = parse_price(info.get("Lehrgangsgebühr"))
        duration_hours         = parse_int(info.get("Unterrichtsstunden"))

        unterrichtsform = (info.get("Unterrichtsform") or "").strip().lower()
        format_key      = FORMAT_MAP.get(unterrichtsform, "part_time")
        teaching_mode   = "online" if "online" in row["title"].lower() else "presence"

        return RawCourseOffer(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=BZ_DEFAULT_CITY,
            street=BZ_DEFAULT_STREET,
            zip_code=BZ_DEFAULT_ZIP,
            exam_fee_scraped=None,  # resolved chamber-wide — see collect()
            availability="available",  # BZ Kassel does not publish seat counts; assume available
            source_url=row["detail_url"],
            scraped_raw={"title": row["title"], "info": info},
        )

    def _parse_bz_info_table(self, soup: BeautifulSoup) -> dict:
        """
        Parse the "Kursinformationen" key/value table on a kursdetail page
        into a dict, e.g. {"Lehrgangsdauer": "08.09.2026 - 04.11.2028", ...}.
        """
        info: dict = {}
        table: Tag | None = None
        for t in soup.find_all("table"):
            if t.find(string=re.compile("Lehrgangsdauer")):
                table = t
                break
        if table is None:
            return info

        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                # BZ Kassel puts the € sign in the label cell ("Lehrgangsgebühr €")
                # rather than in the value cell — strip it so key lookups work.
                key = re.sub(r"\s*€\s*$", "", cells[0].get_text(strip=True)).strip()
                val = cells[1].get_text(" ", strip=True)
                if key:
                    info[key] = val
        return info

    # ------------------------------------------------------------------
    # Berufsbildungszentrum Marburg GmbH
    # ------------------------------------------------------------------

    def _fetch_bbz_marburg(self) -> list[RawCourseOffer]:
        soup = self.parse_html(BBZ_LIST_URL)
        if soup is None:
            logger.error("BBZ Marburg: could not fetch course list at %s", BBZ_LIST_URL)
            return []

        cards = self._collect_bbz_meister_cards(soup)
        logger.info("BBZ Marburg: %d Meisterkurs card(s) found.", len(cards))

        offers: list[RawCourseOffer] = []
        for card in cards:
            try:
                offers.extend(self._parse_bbz_offer(card))
            except Exception as exc:
                logger.warning("BBZ Marburg: error parsing %s: %s", card["detail_url"], exc)
        return offers

    def _collect_bbz_meister_cards(self, soup: BeautifulSoup) -> list[dict]:
        """
        The WordPress CPT archive at /kurs/?post_types=kurs renders every
        BBZ Marburg course as an <article> element containing an <h2> title,
        an Eckdaten table, and a "Details" link to /kurs/<slug>/. We scan all
        "Details" links, resolve the enclosing <article>, and keep only those
        whose h2 title matches MEISTER_RE without matching
        EXCLUDE_INDUSTRIEMEISTER_RE.

        Container detection:
          1. find_parent("article")  — correct for any WordPress CPT archive.
          2. Fallback: walk up and stop at the first ancestor that has an <h2>
             as a *direct child* (recursive=False). This prevents the walk-up
             from escaping past the current card into a parent that contains
             all cards, which would cause card.find("h2") to return the first
             h2 on the entire page rather than the one for this specific card.
        """
        cards: list[dict] = []
        seen_urls: set[str] = set()

        for link in soup.find_all("a", href=True):
            if link.get_text(strip=True).lower() != "details":
                continue
            href = link["href"]
            if not href:
                continue
            if not href.startswith("http"):
                href = BBZ_BASE + href
            if "/kurs/" not in href or href in seen_urls:
                continue

            # Strategy 1: WordPress standard — each post is an <article>.
            article = link.find_parent("article")

            # Strategy 2: non-standard markup — walk up, stopping only when
            # the candidate has an <h2> as a direct (non-recursive) child so
            # we don't accidentally grab a heading from a sibling card.
            if article is None:
                candidate = link.parent
                while candidate and candidate.name not in ("body", "[document]"):
                    if candidate.find("h2", recursive=False):
                        article = candidate
                        break
                    candidate = candidate.parent

            if article is None:
                logger.debug("BBZ Marburg: no card container found for %s", href)
                continue

            h2 = article.find("h2")
            title = h2.get_text(strip=True) if h2 else ""
            if not title:
                continue
            if not MEISTER_RE.search(title) or EXCLUDE_INDUSTRIEMEISTER_RE.search(title):
                continue

            seen_urls.add(href)
            cards.append({
                "title": title,
                "detail_url": href,
                "card_text": article.get_text(separator="\n", strip=True),
            })

        return cards

    def _parse_bbz_offer(self, card: dict) -> list[RawCourseOffer]:
        title = card["title"]

        soup = self.parse_html(card["detail_url"])
        if soup is None:
            logger.warning("BBZ Marburg: could not fetch detail page %s", card["detail_url"])
            return []

        page_text = soup.get_text("\n")
        combined  = f"{title}\n{card['card_text']}\n{page_text}"

        parts = parse_parts_from_text(combined)
        if not parts:
            logger.debug("BBZ Marburg: could not parse parts for %r", title)
            return []

        trade_name = extract_bbz_trade(title)
        if set(parts) <= {3, 4}:
            trade_name = None
        elif trade_name:
            trade_name = BBZ_TRADE_ALIASES.get(trade_name, trade_name)

        info           = self._parse_bbz_info_table(soup)
        course_fee     = parse_price(info.get("Kosten"))
        duration_hours = parse_int(info.get("Dauer des Kurses"))
        format_key     = parse_format_from_text(combined)

        runs = self._parse_bbz_runs(page_text)

        base = dict(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=BBZ_DEFAULT_CITY,
            street=BBZ_DEFAULT_STREET,
            zip_code=BBZ_DEFAULT_ZIP,
            exam_fee_scraped=None,  # resolved chamber-wide — see collect()
            availability="available",  # BBZ Marburg does not publish seat counts; assume available
            source_url=card["detail_url"],
        )

        if not runs:
            # No currently scheduled run — keep the price-only offer visible
            # for comparison, same fallback pattern as HWK Rheinhessen.
            return [RawCourseOffer(
                **base, start_date=None, end_date=None,
                scraped_raw={"title": title, "note": "Keine Termine veröffentlicht"},
            )]

        return [
            RawCourseOffer(**base, start_date=start, end_date=end,
                           scraped_raw={"title": title})
            for start, end in runs
        ]

    def _parse_bbz_info_table(self, soup: BeautifulSoup) -> dict:
        """
        Parse the "Eckdaten" key/value table on a /kurs/<slug>/ page into a
        dict, e.g. {"Dauer des Kurses": "430 Stunden", "Kosten": "4.710 €"}.
        """
        info: dict = {}
        table: Tag | None = None
        for t in soup.find_all("table"):
            if t.find(string=re.compile("Dauer des Kurses")):
                table = t
                break
        if table is None:
            return info

        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(" ", strip=True)
                if key:
                    info[key] = val
        return info

    def _parse_bbz_runs(self, page_text: str) -> list[tuple[str, str]]:
        """
        Scheduled runs live under the "Verfügbare Kurse" heading as one or
        more "DD.MM.YYYY - DD.MM.YYYY" ranges. Returns an empty list if the
        course currently has no scheduled run.
        """
        idx = page_text.find("Verfügbare Kurse")
        if idx < 0:
            return []
        window = page_text[idx:idx + 2000]
        runs = []
        for m in DATE_RANGE_RE.finditer(window):
            start = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            end   = f"{m.group(6)}-{m.group(5)}-{m.group(4)}"
            runs.append((start, end))
        return runs

    # ------------------------------------------------------------------
    # Bubiza (Zimmerer/Ausbaugewerbe)
    # ------------------------------------------------------------------

    def _fetch_bubiza(self) -> list[RawCourseOffer]:
        soup = self.parse_html(BUBIZA_LIST_URL)
        if soup is None:
            logger.error("Bubiza: could not fetch course list at %s", BUBIZA_LIST_URL)
            return []

        cards = self._collect_bubiza_cards(soup)
        logger.info("Bubiza: %d Meisterkurs page(s) found.", len(cards))

        offers: list[RawCourseOffer] = []
        for card in cards:
            try:
                offers.extend(self._parse_bubiza_page(card))
            except Exception as exc:
                logger.warning("Bubiza: error parsing %s: %s", card["url"], exc)
        return offers

    def _collect_bubiza_cards(self, soup: BeautifulSoup) -> list[dict]:
        """Collect Bubiza Meisterkurs course links from the Vollzeit listing.
        Each <li> contains an <a> to a detail page.  Only courses whose
        title contains "meister" (excluding Industriemeister) qualify."""
        cards: list[dict] = []
        seen: set[str] = set()
        for li in soup.find_all("li"):
            a = li.find("a", href=True)
            if a is None:
                continue
            href = a["href"]
            if not href.endswith(".html") or "/vollzeit-hoehere-berufsbildung/" not in href:
                continue
            full = href if href.startswith("http") else BUBIZA_BASE + href
            if full in seen:
                continue
            title = a.get_text(strip=True)
            if not MEISTER_RE.search(title) or EXCLUDE_INDUSTRIEMEISTER_RE.search(title):
                continue
            seen.add(full)
            cards.append({"title": title, "url": full})
        return cards

    def _parse_bubiza_page(self, card: dict) -> list[RawCourseOffer]:
        """Parse a Bubiza Meisterkurs detail page into one or more offers.

        Bubiza pages come in two shapes:
          * per-part pricing — a "Kosten" block lists a fee per part-group
            ("Teile I+II", "Teil III", "Teil IV"), and dated runs are
            labelled with the same part-groups. A combined run ("Teile I-IV")
            is priced as the sum of its component groups.
          * flat pricing — a single course fee with no part breakdown; every
            dated run shares that fee (parts inferred from the run labels or,
            failing that, the course body).
        """
        soup = self.parse_html(card["url"])
        if soup is None:
            logger.warning("Bubiza: could not fetch %s", card["url"])
            return []

        page_text = soup.get_text("\n")
        title = card["title"]
        trade_name = _extract_bubiza_trade(title)
        today = datetime.today().strftime("%Y-%m-%d")

        groups, flat_fee = self._parse_bubiza_kosten(page_text)
        runs = self._parse_bubiza_runs(page_text)
        labelled = [r for r in runs if r[0]]

        def make_offer(parts: list[int], fee: float | None, start, end, avail: str, note=None):
            resolved_trade = None if set(parts) <= {3, 4} else trade_name
            raw = {"title": title}
            if note:
                raw["note"] = note
            return RawCourseOffer(
                title=build_course_title(resolved_trade, parts),
                trade_name=resolved_trade, parts=parts,
                format_key="full_time", teaching_mode="presence",
                start_date=start, end_date=end, duration_hours=None,
                course_fee=fee,
                city=BUBIZA_DEFAULT_CITY, street=BUBIZA_DEFAULT_STREET,
                zip_code=BUBIZA_DEFAULT_ZIP,
                exam_fee_scraped=None, availability=avail,
                source_url=card["url"], scraped_raw=raw,
            )

        offers: list[RawCourseOffer] = []
        seen: set[tuple] = set()

        # Shape 1: per-part pricing with labelled runs.
        if groups and labelled:
            for parts, sub, start, end in labelled:
                if start < today:
                    continue
                key = (tuple(parts), start, end)
                if key in seen:
                    continue
                seen.add(key)
                fee = self._resolve_bubiza_fee(groups, flat_fee, parts, sub)
                offers.append(make_offer(parts, fee, start, end, "available"))
            return offers

        # Shape 2: flat pricing.
        if flat_fee is not None:
            future_labelled = [r for r in labelled if r[2] >= today]
            if future_labelled:
                # Emit each future part-I run (the actual course intake);
                # component Teil III/IV runs share the same flat fee and are
                # part of the same programme, so only the leading part-I run
                # represents a bookable course offer here.
                for parts, sub, start, end in future_labelled:
                    if 1 not in parts:
                        continue
                    key = (tuple(parts), start, end)
                    if key in seen:
                        continue
                    seen.add(key)
                    offers.append(make_offer(parts, flat_fee, start, end, "available"))
                if offers:
                    return offers
            # No usable labelled runs — a single price-only offer.
            bare_future = [r for r in runs if not r[0] and r[2] >= today]
            parts = self._infer_bubiza_parts(title, page_text)
            if bare_future:
                for _p, _s, start, end in bare_future:
                    offers.append(make_offer(parts, flat_fee, start, end, "available"))
                return offers
            return [make_offer(parts, flat_fee, None, None, "unknown",
                               note="Keine Termine veröffentlicht")]

        return []

    def _parse_bubiza_kosten(self, page_text: str) -> tuple[dict, float | None]:
        """Parse the "Kosten" block into ``({(frozenset(parts), sub): fee}, flat_fee)``.
        A fee line with no part prefix becomes the flat fee. Lines mentioning
        "Prüfung" (exam fees, not course fees) are skipped."""
        idx = page_text.find("Kosten")
        if idx < 0:
            return {}, None
        window = page_text[idx:idx + 800]
        groups: dict = {}
        flat: float | None = None
        for line in window.splitlines():
            line = line.strip()
            if not line or "prüfung" in line.lower():
                continue
            fee = _parse_bubiza_price(line)
            if fee is None:
                continue
            parts = _parse_bubiza_label_parts(line)
            if parts:
                groups[(frozenset(parts), _parse_bubiza_sub(line))] = fee
            else:
                flat = fee
        return groups, flat

    def _parse_bubiza_runs(self, page_text: str) -> list[tuple]:
        """Parse every dated run on the page into
        ``[(parts, sub_type, start, end)]``; ``parts`` is ``[]`` for a run
        whose line carries no "Teil …" label."""
        result: list[tuple] = []
        for line in page_text.splitlines():
            line = line.strip()
            dm = DATE_RANGE_RE.search(line)
            if not dm:
                continue
            start = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
            end   = f"{dm.group(6)}-{dm.group(5)}-{dm.group(4)}"
            result.append((_parse_bubiza_label_parts(line), _parse_bubiza_sub(line), start, end))
        return result

    @staticmethod
    def _resolve_bubiza_fee(
        groups: dict, flat_fee: float | None,
        run_parts: list[int], run_sub: str | None,
    ) -> float | None:
        """Resolve a run's fee: exact (parts, sub) match, else sum of the
        component part-groups (for a combined "Teile I-IV" run), else flat."""
        run_set = frozenset(run_parts)
        for key in ((run_set, run_sub), (run_set, None)):
            if key in groups:
                return groups[key]
        total = 0.0
        matched = False
        for (ks, _sub), fee in groups.items():
            if ks < run_set:      # strict subset → a component of this combo
                total += fee
                matched = True
        return total if matched else flat_fee

    @staticmethod
    def _infer_bubiza_parts(title: str, page_text: str) -> list[int]:
        """Best-effort parts for a flat-priced Bubiza page with no usable run
        labels. Collects every distinct "Teil <roman>" body mention that
        heads a real content phrase (Fachpraxis/Fachtheorie/…), defaulting to
        I+II (the fachpraxis/fachtheorie core) when nothing is found."""
        found: set[int] = set()
        for m in re.finditer(
            rf"Teil\s+({_ROMAN_ALT})\s+(?:Fachpraxis|Fachtheorie|der\s+Meister)",
            page_text, re.I,
        ):
            found.add(ROMAN[m.group(1).upper()])
        return sorted(found) or [1, 2]