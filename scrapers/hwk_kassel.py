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
  - BBZ Mitte GmbH                   — bbz-mitte.de            [IMPLEMENTED]
  - Holzfachschule Bad Wildungen     — holzfachschule.de       [IMPLEMENTED]
  - FTZ / Innung Kfz-Gewerbe Kassel  — kfz-innung-kassel.de    [IMPLEMENTED: dateless/priceless only]
  - Kreishandwerkerschaft Waldeck-Frankenberg — khkb.de        [BLOCKED: PDF-only]
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

BBZ Mitte GmbH (bbz-mitte.de):
  - Neos/Flow CMS. Its /de/kursfinder listing renders results client-side,
    but the underlying AJAX endpoint /de/seminar-navigator/search-results
    returns them server-side as a static HTML fragment (one
    <div.seminar-list-entry> per course). Results are scoped by the repeated
    ``c[]`` category param (c[]=600 → "Meisterschule") and paginated via
    ``seite=N``, with an ``a.aw-load-more-link`` present while another page
    exists — so no headless browser is needed.
  - Filtering: the Meisterschule category still bundles in IHK
    Industriemeister courses and "Infoabend" info evenings; both are dropped
    (Industriemeister is out of scope as on BBZ Marburg; Infoabende are not
    courses). A remaining course is kept only if its title/run-headings yield
    at least one Meisterprüfung part.
  - Each course detail page lists one or more scheduled runs as
    <div.seminar-date> boxes, each carrying its own date range, price
    ("… €"), Unterrichtsform and "(NNN UE)" hours; one RawCourseOffer is
    emitted per run, mirroring the BBZ Marburg multi-run pattern.

Holzfachschule Bad Wildungen (holzfachschule.de):
  - holzfachschule.de is a Jimdo marketing site, but the actual course
    catalogue lives on a separate booking system at
    veranstaltung.holzfachschule.de (PrimeFaces/JSF, yet fully server-
    rendered — PrimeFaces only supplies the CSS theme; the seminar list and
    detail markup are static HTML). The Meistervorbereitung target group is
    selected by URL (index?zielGruppe=Meistervorbereitung).
  - Filtering: the list still includes IHK Industriemeister courses (out of
    scope, dropped) and a standalone AEVO Ausbilderlehrgang (no Meister part,
    dropped for lack of a parseable Teil). Each remaining <article> links to
    a /seminar/<slug>_<id> detail page.
  - The detail "Termine" section lists scheduled runs as <div data-vid> rows
    (date range + price + availability badge: ``availibility-red`` =
    "ausgebucht" → full, otherwise available); one RawCourseOffer per run,
    with a dateless placeholder when no run is scheduled ("auf Anfrage").

FTZ / Innung des Kfz-Gewerbes Kassel (kfz-innung-kassel.de):
  - TYPO3 site; its Seminare page is fully server-rendered (courses are
    accordion items: button trigger = title, sibling content div = body).
    FTZ is the ONLY HWK Kassel provider that lists Kfz-Meister courses — BZ
    Kassel carries none — so scraping it is what makes Kfz-Meister visible.
  - CAVEATS: FTZ publishes no schedule or price on this page. All three
    Kfz-Meister courses are "auf Anfrage", so every offer is a dateless,
    priceless placeholder (start_date/end_date/course_fee = None,
    availability="unknown"), kept visible via the same fallback as elsewhere.
  - Part wording is non-standard: "Servicetechniker"/"Berufsspezialist"/"ST"
    denotes the fachpraktische Teil-1-Stufe and "ST+II" the I+II combo, so a
    dedicated parse_ftz_parts() maps them (the shared parser only sees the
    written-out "Teil II"). Industriemeister titles are excluded as usual.
  - The three courses share one page, so each offer's source_url carries the
    accordion item's anchor fragment to keep dedup keys distinct.

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


# ----------------------------------------------------------------------
# BBZ Mitte GmbH
# ----------------------------------------------------------------------

BBZM_BASE = "https://www.bbz-mitte.de"
# /de/kursfinder renders its result list client-side (invisible to
# BeautifulSoup), but its underlying AJAX endpoint returns the exact same
# results server-side as a static HTML fragment: one <div.seminar-list-entry>
# per course. Results are scoped by the repeated ``c[]`` category param and
# paginated via ``seite=N``; a "mehr laden" link (a.aw-load-more-link) is
# emitted while another page exists. c[]=600 is the "Meisterschule" category
# (confirmed 2026-07-09). Filter category, not keyword: it already excludes
# the unrelated Fachkurse the site offers.
BBZM_SEARCH_URL       = f"{BBZM_BASE}/de/seminar-navigator/search-results"
BBZM_MEISTER_CATEGORY = 600

BBZM_DEFAULT_STREET = "Goerdelerstraße 139"
BBZM_DEFAULT_ZIP     = "36100"
BBZM_DEFAULT_CITY    = "Petersberg"

# Map a course title to a canonical trade name (aligned to data/trades.json
# slugs); ordered, first match wins. Generic Teil III/IV courses ("... für
# alle Gewerke im Handwerk") carry no trade and resolve to the shared generic
# trade. BBZ Mitte's Meisterschule catalogue only covers these four trades;
# extend this list as new trades appear.
BBZM_TRADE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"elektrotechnik", re.IGNORECASE),                            "Elektrotechniker"),
    (re.compile(r"kfz|kraftfahrzeug", re.IGNORECASE),                         "Kfz.-Techniker"),
    (re.compile(r"land-?\s*und\s*baumaschinen|landmaschinen", re.IGNORECASE), "Land- und Baumaschinenmechatroniker"),
    (re.compile(r"tischler|schreiner", re.IGNORECASE),                        "Tischler"),
]

# Unterrichtsstunden appear only as "(530 UE)" inside a run heading / Zeiten
# text — a bare parse_int() would wrongly grab the "08" from an "08:00" time.
BBZM_UE_RE = re.compile(r"(\d+)\s*UE")


def extract_bbzm_trade(title: str, parts: list[int]) -> str | None:
    """
    Resolve a BBZ Mitte course title to a canonical trade name, or None for
    generic Teil III/IV-only courses (which resolve to the shared generic
    trade downstream). See BBZM_TRADE_PATTERNS.
    """
    if set(parts) <= {3, 4}:
        return None
    for pattern, name in BBZM_TRADE_PATTERNS:
        if pattern.search(title):
            return name
    return None


def parse_bbzm_format(text: str) -> str:
    """
    BBZ Mitte labels runs "Vollzeit" / "Berufsbegleitend" (there is no
    "Teilzeit" wording); anything berufsbegleitend/weekend is part-time.
    """
    lower = text.lower()
    if "vollzeit" in lower:
        return "full_time"
    return "part_time"


def parse_bbzm_hours(text: str) -> int | None:
    m = BBZM_UE_RE.search(text)
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------
# Holzfachschule Bad Wildungen
# ----------------------------------------------------------------------

# holzfachschule.de itself is a Jimdo marketing site, but its actual course
# catalogue lives on a separate booking system at veranstaltung.holzfachschule.de
# (a PrimeFaces/JSF app whose PAGES are nonetheless fully server-rendered —
# PrimeFaces here only styles the theme, the seminar list/detail markup is
# static HTML). The Meistervorbereitung target group is filtered by URL:
# index?zielGruppe=Meistervorbereitung. Each result <article> links to a
# /seminar/<slug>_<id> detail page whose "Termine" section lists scheduled
# runs as <div data-vid> rows (date range + price + availability badge).
HFS_BASE      = "https://veranstaltung.holzfachschule.de"
HFS_LIST_URL  = f"{HFS_BASE}/index?zielGruppe=Meistervorbereitung&veranstalter=Holzfachschule"

HFS_DEFAULT_STREET = "Auf der Roten Erde 9"
HFS_DEFAULT_ZIP     = "34537"
HFS_DEFAULT_CITY    = "Bad Wildungen"

# Map a course title to a canonical trade name (aligned to data/trades.json
# slugs); ordered, first match wins. Generic Teil III/IV courses ("Meister
# Teil III + IV") carry no trade and resolve to the shared generic trade.
HFS_TRADE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"tischler|schreiner", re.IGNORECASE), "Tischler"),
    (re.compile(r"modellbauer", re.IGNORECASE),        "Modellbauer"),
]


def extract_hfs_trade(title: str, parts: list[int]) -> str | None:
    """
    Resolve a Holzfachschule course title to a canonical trade name, or None
    for generic Teil III/IV-only courses (which resolve to the shared generic
    trade downstream). See HFS_TRADE_PATTERNS.
    """
    if set(parts) <= {3, 4}:
        return None
    for pattern, name in HFS_TRADE_PATTERNS:
        if pattern.search(title):
            return name
    return None


def parse_hfs_format(text: str) -> str:
    """
    Holzfachschule Meistervorbereitung runs full-time by default; only a
    Teilzeit/berufsbegleitend/Abendschule wording downgrades to part_time.
    """
    lower = text.lower()
    if any(w in lower for w in ("teilzeit", "berufsbegleitend", "abendschule", "wochenend")):
        return "part_time"
    return "full_time"


# ----------------------------------------------------------------------
# FTZ / Innung des Kfz-Gewerbes Kassel
# ----------------------------------------------------------------------

# TYPO3 site. Its Seminare page is fully server-rendered — courses are
# accordion items (button trigger = title, sibling content div = body). Three
# of them are Kfz-Meister courses; FTZ is the ONLY HWK Kassel provider that
# lists Kfz-Meister courses at all (BZ Kassel has none). BIG CAVEATS, all
# because FTZ publishes no schedule here — every offer is a dateless, priceless
# placeholder ("auf Anfrage"):
#   - No dates: start_date/end_date are always None.
#   - No prices: course_fee is always None.
#   - Non-standard part wording ("ST" = Servicetechniker = fachpraktischer
#     Teil 1; "II" = Teil II) needs a dedicated parts resolver.
# The three courses share one page, so each offer's source_url carries the
# accordion item's anchor fragment to stay distinct in the dedup key
# (chamber_slug, source_url, start_date) — without it all three collapse to one.
FTZ_BASE      = "https://www.kfz-innung-kassel.de"
FTZ_LIST_URL  = f"{FTZ_BASE}/aus-und-weiterbildung-im-ftz/seminare-im-ftz"

FTZ_DEFAULT_STREET = "Falderbaumstraße 20"
FTZ_DEFAULT_ZIP     = "34123"
FTZ_DEFAULT_CITY    = "Kassel"

FTZ_TRADE_NAME = "Kfz.-Techniker"

# A course qualifies as a Kfz-Meister course if its title mentions "meister"
# or the Servicetechniker/Berufsspezialist stage (fachpraktischer Teil 1).
FTZ_MEISTER_RE = re.compile(r"meister|servicetechnik|berufsspezialist", re.IGNORECASE)


def parse_ftz_parts(title: str) -> list[int]:
    """
    Resolve Meisterprüfung parts from an FTZ Kfz title. FTZ labels the
    fachpraktische Teil-1-Stufe "Servicetechniker"/"Berufsspezialist"/"ST"
    rather than "Teil I", and combines it as "ST+II"; "Teil II" is written
    out. Returns [] for the non-Meister Kfz seminars (AU, HV, Klima, …).
    """
    lower = title.lower()
    parts: set[int] = set()
    if "servicetechnik" in lower or "berufsspezialist" in lower or re.search(r"\bst\b", lower) or "(st" in lower:
        parts.add(1)
    if re.search(r"teil\s*ii\b", lower) or re.search(r"\+\s*ii\b", lower) or "st+ii" in lower:
        parts.add(2)
    return sorted(parts)


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

        # ---- Provider: BBZ Mitte GmbH ---------------------------------
        try:
            bbzm_offers = self._fetch_bbz_mitte()
            logger.info("HWK Kassel/BBZ Mitte: %d course offers.", len(bbzm_offers))
            offers.extend(bbzm_offers)
        except Exception:
            logger.exception("HWK Kassel/BBZ Mitte: provider failed — skipping.")

        # ---- Provider: Holzfachschule Bad Wildungen -------------------
        try:
            hfs_offers = self._fetch_holzfachschule()
            logger.info("HWK Kassel/Holzfachschule: %d course offers.", len(hfs_offers))
            offers.extend(hfs_offers)
        except Exception:
            logger.exception("HWK Kassel/Holzfachschule: provider failed — skipping.")

        # ---- Provider: FTZ / Innung des Kfz-Gewerbes Kassel -----------
        try:
            ftz_offers = self._fetch_ftz_kfz()
            logger.info("HWK Kassel/FTZ Kfz-Innung: %d course offers.", len(ftz_offers))
            offers.extend(ftz_offers)
        except Exception:
            logger.exception("HWK Kassel/FTZ Kfz-Innung: provider failed — skipping.")

        # ---- Remaining providers: not yet implemented -----------------
        # Each should follow the same pattern: its own _fetch_<provider>()
        # method, wrapped in try/except here, contributing RawCourseOffers
        # to the same `offers` list.
        #   Kreishandwerkerschaft Waldeck-Frankenberg — www.khkb.de
        #     (Meistervorbereitungslehrgänge only via PDF; blocked)

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

    # ------------------------------------------------------------------
    # BBZ Mitte GmbH
    # ------------------------------------------------------------------

    def _fetch_bbz_mitte(self) -> list[RawCourseOffer]:
        listings = self._collect_bbzm_listings()
        logger.info("BBZ Mitte: %d Meisterkurs listing(s) found.", len(listings))

        offers: list[RawCourseOffer] = []
        for listing in listings:
            try:
                offers.extend(self._parse_bbzm_offer(listing))
            except Exception as exc:
                logger.warning("BBZ Mitte: error parsing %s: %s", listing["detail_url"], exc)
        return offers

    def _collect_bbzm_listings(self) -> list[dict]:
        """
        Page through the Meisterschule category (c[]=600) of the seminar
        navigator's server-side result fragment, one <div.seminar-list-entry>
        per course, following the "mehr laden" link until it disappears.
        Industriemeister (out of scope) and Infoabend (info evenings, not
        courses) entries are dropped here.
        """
        listings: list[dict] = []
        seen_urls: set[str] = set()
        page = 1
        while True:
            soup = self.parse_html(
                BBZM_SEARCH_URL,
                params={"c[]": BBZM_MEISTER_CATEGORY, "seite": page},
            )
            if soup is None:
                logger.warning("BBZ Mitte: could not fetch result page %d", page)
                break

            entries = soup.select("div.seminar-list-entry")
            for entry in entries:
                listing = self._parse_bbzm_listing_entry(entry)
                if listing is None or listing["detail_url"] in seen_urls:
                    continue
                seen_urls.add(listing["detail_url"])
                listings.append(listing)

            # The result fragment emits a "mehr laden" link only while a
            # further page exists; its absence terminates pagination.
            if not entries or soup.select_one("a.aw-load-more-link") is None:
                break
            page += 1

        return listings

    def _parse_bbzm_listing_entry(self, entry: Tag) -> dict | None:
        heading = entry.select_one("span.heading b")
        title = heading.get_text(strip=True) if heading else ""
        link = entry.select_one("a.seminar-link")
        href = link.get("href", "") if link else ""
        if not title or not href:
            return None
        if not href.startswith("http"):
            href = BBZM_BASE + href

        categories = [pill.get_text(strip=True) for pill in entry.select(".categories .pill")]
        event_type = entry.select_one("span.event-type")
        event_text = event_type.get_text(" ", strip=True) if event_type else ""

        is_infoabend = "Infoabend" in categories or title.lower().startswith("kostenloser infoabend")
        if is_infoabend or EXCLUDE_INDUSTRIEMEISTER_RE.search(title):
            return None

        return {
            "title":      title,
            "detail_url": href,
            "event_type": event_text,
        }

    def _parse_bbzm_offer(self, listing: dict) -> list[RawCourseOffer]:
        title = listing["title"]

        soup = self.parse_html(listing["detail_url"])
        if soup is None:
            logger.warning("BBZ Mitte: could not fetch detail page %s", listing["detail_url"])
            return []

        runs = self._parse_bbzm_run_boxes(soup)

        # Parts come from the title plus every run heading — a title like
        # "Vorbereitungslehrgang zum Tischler- / Schreinermeister(in)" states
        # no part, but its run heading does ("… Teil I + II").
        heading_text = " ".join(run["heading"] for run in runs)
        parts = parse_parts_from_text(f"{title} {heading_text}")
        if not parts:
            logger.debug("BBZ Mitte: could not parse parts for %r", title)
            return []

        trade_name = extract_bbzm_trade(title, parts)

        base = dict(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            teaching_mode="presence",  # BBZ Mitte Meisterkurse are all Präsenz
            city=BBZM_DEFAULT_CITY,
            street=BBZM_DEFAULT_STREET,
            zip_code=BBZM_DEFAULT_ZIP,
            exam_fee_scraped=None,  # resolved chamber-wide — see collect()
            availability="available",  # BBZ Mitte does not publish seat counts; assume available
            source_url=listing["detail_url"],
        )

        if not runs:
            # No scheduled run ("Auf Anfrage") — keep a price-less, dateless
            # offer visible for comparison, same fallback as BBZ Marburg.
            return [RawCourseOffer(
                **base,
                format_key=parse_bbzm_format(f"{title} {listing['event_type']}"),
                start_date=None, end_date=None,
                duration_hours=None, course_fee=None,
                scraped_raw={"title": title, "note": "Keine Termine veröffentlicht"},
            )]

        offers: list[RawCourseOffer] = []
        for run in runs:
            format_context = " ".join([
                title, listing["event_type"], run["heading"], run["form"], run["zeiten"],
            ])
            offers.append(RawCourseOffer(
                **base,
                format_key=parse_bbzm_format(format_context),
                start_date=run["start_date"],
                end_date=run["end_date"],
                duration_hours=parse_bbzm_hours(f"{run['heading']} {run['zeiten']}"),
                course_fee=parse_price(run["fee"]),
                scraped_raw={"title": title, "run_heading": run["heading"]},
            ))
        return offers

    def _parse_bbzm_run_boxes(self, soup: BeautifulSoup) -> list[dict]:
        """
        Each scheduled run is a <div.seminar-date> box carrying its date range
        (data-date + heading), a "(NNN UE)" hours hint, and labelled columns
        for Zeiten / Unterrichtsform / Standort / Gebühr.
        """
        runs: list[dict] = []
        for box in soup.select("div.seminar-date"):
            heading_el = box.select_one(".seminar-heading")
            heading = heading_el.get_text(" ", strip=True) if heading_el else ""

            start_date, end_date = parse_date_range(box.get("data-date", "") or heading)

            fields: dict[str, str] = {}
            for col in box.select(".box-border .row > div"):
                label = col.select_one(".text-bold")
                if label is None:
                    fee_el = col.select_one(".gebuehreninfo-area")
                    if fee_el is not None:
                        fields["fee"] = fee_el.get_text(" ", strip=True)
                    continue
                key = label.get_text(strip=True)
                value = col.get_text(" ", strip=True).replace(key, "", 1).strip()
                fields[key] = value

            runs.append({
                "heading":    heading,
                "start_date": start_date,
                "end_date":   end_date,
                "fee":        fields.get("fee"),
                "form":       fields.get("Unterrichtsform", ""),
                "zeiten":     fields.get("Zeiten", ""),
            })
        return runs

    # ------------------------------------------------------------------
    # Holzfachschule Bad Wildungen
    # ------------------------------------------------------------------

    def _fetch_holzfachschule(self) -> list[RawCourseOffer]:
        soup = self.parse_html(HFS_LIST_URL)
        if soup is None:
            logger.error("Holzfachschule: could not fetch course list at %s", HFS_LIST_URL)
            return []

        cards = self._collect_hfs_cards(soup)
        logger.info("Holzfachschule: %d Meisterkurs card(s) found.", len(cards))

        offers: list[RawCourseOffer] = []
        for card in cards:
            try:
                offers.extend(self._parse_hfs_offer(card))
            except Exception as exc:
                logger.warning("Holzfachschule: error parsing %s: %s", card["detail_url"], exc)
        return offers

    def _collect_hfs_cards(self, soup: BeautifulSoup) -> list[dict]:
        """
        The Meistervorbereitung result list renders each course as an
        <article> with an <h2.event-title> and a link to /seminar/<slug>_<id>.
        Industriemeister (IHK, out of scope) and any card whose title yields
        no Meisterprüfung part (e.g. the standalone AEVO Ausbilderlehrgang)
        are dropped.
        """
        cards: list[dict] = []
        seen_urls: set[str] = set()

        for article in soup.select("article"):
            heading = article.select_one("h2.event-title")
            link = article.select_one("a[href*='seminar/']")
            title = heading.get_text(strip=True) if heading else ""
            href = link.get("href", "") if link else ""
            if not title or not href:
                continue
            if not href.startswith("http"):
                href = f"{HFS_BASE}/{href.lstrip('/')}"
            if href in seen_urls:
                continue
            if EXCLUDE_INDUSTRIEMEISTER_RE.search(title):
                continue
            seen_urls.add(href)
            cards.append({"title": title, "detail_url": href})

        return cards

    def _parse_hfs_offer(self, card: dict) -> list[RawCourseOffer]:
        title = card["title"]
        parts = parse_parts_from_text(title)
        if not parts:
            logger.debug("Holzfachschule: could not parse parts for %r", title)
            return []

        soup = self.parse_html(card["detail_url"])
        if soup is None:
            logger.warning("Holzfachschule: could not fetch detail page %s", card["detail_url"])
            return []

        trade_name = extract_hfs_trade(title, parts)
        # Meistervorbereitung at Holzfachschule is offered in full-time day
        # form only (the listing's Zeitmodell filter offers just "Vollzeit");
        # detect a part-time wording defensively but default to full_time.
        format_key = parse_hfs_format(soup.get_text(" ", strip=True))

        base = dict(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            duration_hours=None,  # not published per course
            city=HFS_DEFAULT_CITY,
            street=HFS_DEFAULT_STREET,
            zip_code=HFS_DEFAULT_ZIP,
            exam_fee_scraped=None,  # resolved chamber-wide — see collect()
            source_url=card["detail_url"],
        )

        runs = self._parse_hfs_runs(soup)
        if not runs:
            # No scheduled run ("Aktuell sind keine Termine verfügbar") — keep
            # a dateless placeholder visible, same fallback as BBZ Marburg.
            return [RawCourseOffer(
                **base, start_date=None, end_date=None, course_fee=None,
                availability="unknown",
                scraped_raw={"title": title, "note": "Keine Termine veröffentlicht"},
            )]

        return [
            RawCourseOffer(
                **base,
                start_date=run["start_date"],
                end_date=run["end_date"],
                course_fee=run["fee"],
                availability=run["availability"],
                scraped_raw={"title": title},
            )
            for run in runs
        ]

    def _parse_hfs_runs(self, soup: BeautifulSoup) -> list[dict]:
        """
        The "Termine" section lists each scheduled run as a <div data-vid>
        carrying "Zeitraum: DD.MM.YYYY - DD.MM.YYYY", "Preis: N,NN €" and an
        availability badge (``availibility-red`` = "ausgebucht" → full; any
        other colour shows an "in den Warenkorb" button → available).
        """
        runs: list[dict] = []
        for row in soup.select("div[data-vid]"):
            text = row.get_text(" ", strip=True)
            start_date, end_date = parse_date_range(text)
            if not start_date:
                continue
            badge = row.select_one("[class*='availibility-']")
            badge_cls = " ".join(badge.get("class", [])) if badge else ""
            availability = "full" if "availibility-red" in badge_cls else "available"
            runs.append({
                "start_date":   start_date,
                "end_date":     end_date,
                "fee":          parse_price(text),
                "availability": availability,
            })
        return runs

    # ------------------------------------------------------------------
    # FTZ / Innung des Kfz-Gewerbes Kassel
    # ------------------------------------------------------------------

    def _fetch_ftz_kfz(self) -> list[RawCourseOffer]:
        soup = self.parse_html(FTZ_LIST_URL)
        if soup is None:
            logger.error("FTZ Kfz-Innung: could not fetch Seminare page at %s", FTZ_LIST_URL)
            return []

        offers: list[RawCourseOffer] = []
        for item in soup.select("div.m-accordion-kfz-1__item"):
            try:
                offer = self._parse_ftz_item(item)
            except Exception as exc:
                logger.warning("FTZ Kfz-Innung: error parsing accordion item: %s", exc)
                continue
            if offer:
                offers.append(offer)
        return offers

    def _parse_ftz_item(self, item: Tag) -> RawCourseOffer | None:
        """
        Parse one Seminare accordion item into a Kfz-Meister offer, or None for
        the non-Meister Kfz seminars (AU, HV, Klimaanlagen, …). FTZ publishes
        no schedule or price here, so every offer is a dateless, priceless
        "auf Anfrage" placeholder — kept visible so Kfz-Meister availability
        shows up at all (no other HWK Kassel provider lists it).
        """
        trigger = item.select_one("button.js-accordion-trigger")
        content = item.select_one("div.js-accordion-content")
        if trigger is None or content is None:
            return None

        title = trigger.get_text(" ", strip=True)
        if not FTZ_MEISTER_RE.search(title) or EXCLUDE_INDUSTRIEMEISTER_RE.search(title):
            return None

        parts = parse_ftz_parts(title)
        if not parts:
            logger.debug("FTZ Kfz-Innung: could not parse parts for %r", title)
            return None

        # The three Kfz-Meister courses live on one page; anchor the source_url
        # to this item so its dedup key (chamber_slug, source_url, start_date)
        # stays distinct — otherwise all dateless offers collapse into one.
        anchor = content.get("id", "")
        source_url = f"{FTZ_LIST_URL}#{anchor}" if anchor else FTZ_LIST_URL

        format_key = "full_time" if "vollzeit" in title.lower() else "part_time"

        return RawCourseOffer(
            title=build_course_title(FTZ_TRADE_NAME, parts),
            trade_name=FTZ_TRADE_NAME,
            parts=parts,
            format_key=format_key,
            teaching_mode="presence",
            start_date=None,       # FTZ publishes no schedule ("auf Anfrage")
            end_date=None,
            duration_hours=None,
            course_fee=None,       # price "auf Anfrage" — not published
            city=FTZ_DEFAULT_CITY,
            street=FTZ_DEFAULT_STREET,
            zip_code=FTZ_DEFAULT_ZIP,
            exam_fee_scraped=None,  # resolved chamber-wide — see collect()
            availability="unknown",
            source_url=source_url,
            scraped_raw={"title": title, "note": "auf Anfrage — keine Termine/Preise veröffentlicht"},
        )
