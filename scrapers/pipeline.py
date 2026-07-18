"""
scrapers/pipeline.py

Orchestrates a scrape into the checked-in JSON dataset:

    scrape → merge/retention → geocode → resolve exam fees → write data/*.json

No database. Replaces the old ``run_scrapers`` management command + the
DB-based cleanup and coordinate fixes.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .base import (
    GENERIC_TRADE_SLUG,
    ScrapeResult,
    build_course_title,
    harmonize_course_record,
    normalize_trade,
)
from .fees import _fmt, build_exam_fee_lookup, resolve_exam_fee
from .geocode import Geocoder, build_query
from .hwk_koblenz import HwkKoblenzScraper
from .hwk_berlin import HwkBerlinScraper
from .hwk_hamburg import HwkHamburgScraper
from .hwk_bremen import HwkBremenScraper
from .hwk_freiburg import HwkFreiburgScraper
from .hwk_heilbronn import HwkHeilbronnScraper
from .hwk_konstanz import HwkKonstanzScraper
from .hwk_pfalz import HwkPfalzScraper
from .hwk_reutlingen import HwkReutlingenScraper
from .hwk_rheinhessen import (
    HwkRheinhessenScraper,
    resolve_coords as rh_resolve_coords,
    DEFAULT_COORDS as RH_DEFAULT_COORDS,
)
from .hwk_saarland import HWK_SAARLAND_LAT, HWK_SAARLAND_LNG, HwkSaarlandScraper
from .hwk_trier import HwkTrierScraper
from .hwk_kassel import HwkKasselScraper
from .hwk_karlsruhe import HwkKarlsruheScraper
from .hwk_mannheim import HwkMannheimScraper
from .hwk_mittelfranken import HwkMittelfrankenScraper
from .hwk_muenchen_und_oberbayern import HwkMuenchenUndOberbayernScraper
from .hwk_niederbayern_oberpfalz import HwkNiederbayernOberpfalzScraper
from .hwk_oberfranken import HwkOberfrankenScraper
from .hwk_rhein_main import HwkRheinMainScraper
from .hwk_schwaben import HwkSchwabenScraper
from .hwk_stuttgart import HwkStuttgartScraper
from .hwk_ulm import HwkUlmScraper
from .hwk_unterfranken import HwkUnterfrankenScraper
from .hwk_wiesbaden import HwkWiesbadenScraper
from .hwk_erfurt import HwkErfurtScraper
from .hwk_ostthueringen_gera import HwkOstthueringenGeraScraper
from .hwk_suedthueringen_suhl import HwkSuedthueringenSuhlScraper, ROHR_CAMPUS
from .hwk_halle_saale import HwkHalleSaaleScraper
from .hwk_magdeburg import HwkMagdeburgScraper
from .hwk_dresden import HwkDresdenScraper
from .hwk_chemnitz import HwkChemnitzScraper
from .hwk_leipzig import HwkLeipzigScraper
from .hwk_cottbus import HwkCottbusScraper
from .hwk_potsdam import HwkPotsdamScraper
from .hwk_frankfurt_oder_ostbrandenburg import HwkFrankfurtOderOstbrandenburgScraper
from .hwk_schwerin import HwkSchwerinScraper
from .hwk_ostmecklenburg_vorpommern import HwkOstmecklenburgVorpommernScraper
from .hwk_flensburg import HwkFlensburgScraper
from .hwk_luebeck import HwkLuebeckScraper
from .hwk_braunschweig_lueneburg_stade import HwkBraunschweigLueneburgStadeScraper
from .hwk_hannover import HwkHannoverScraper
from .hwk_hildesheim_suedniedersachsen import HwkHildesheimSuedniedersachsenScraper
from .hwk_oldenburg import HwkOldenburgScraper
from .hwk_osnabrueck_emsland_grafschaft_bentheim import HwkOsnabrueckEmslandGrafschaftBentheimScraper
from .hwk_ostfriesland import HwkOstfrieslandScraper
from .hwk_koeln import HwkKoelnScraper
from .hwk_duesseldorf import HwkDuesseldorfScraper
from .hwk_aachen import HwkAachenScraper
from .hwk_ostwestfalen_lippe_zu_bielefeld import HwkOstwestfalenLippeZuBielefeldScraper
from .hwk_muenster import HwkMuensterScraper
from .hwk_suedwestfalen import HwkSuedwestfalenScraper
from .hwk_dortmund import HwkDortmundScraper


logger = logging.getLogger(__name__)

# Cap parallel chamber scrapes when running the full dataset on one runner (GitHub
# Actions egress limits → ConnectTimeout storms at ~50+ simultaneous connections).
# CI matrix jobs scrape ~13 chambers each and run them fully in parallel.
SCRAPE_MAX_WORKERS = max(1, int(os.environ.get("SCRAPE_MAX_WORKERS", "15")))
SCRAPE_PARALLEL_CAP_THRESHOLD = max(1, int(os.environ.get("SCRAPE_PARALLEL_CAP_THRESHOLD", "15")))

SCRAPERS: dict[str, type] = {
    "hwk-koblenz":     HwkKoblenzScraper,
    "hwk-trier":       HwkTrierScraper,
    "hwk-pfalz":       HwkPfalzScraper,
    "hwk-rheinhessen": HwkRheinhessenScraper,
    "hwk-saarland":    HwkSaarlandScraper,
    "hwk-kassel":      HwkKasselScraper,
    "hwk-rhein-main":  HwkRheinMainScraper,
    "hwk-wiesbaden":   HwkWiesbadenScraper,
    "hwk-karlsruhe":   HwkKarlsruheScraper,
    "hwk-mannheim":    HwkMannheimScraper,
    "hwk-stuttgart":   HwkStuttgartScraper,
    "hwk-ulm":         HwkUlmScraper,
    "hwk-freiburg":    HwkFreiburgScraper,
    "hwk-konstanz":    HwkKonstanzScraper,
    "hwk-reutlingen":  HwkReutlingenScraper,
    "hwk-heilbronn-franken": HwkHeilbronnScraper,
    "hwk-muenchen-und-oberbayern": HwkMuenchenUndOberbayernScraper,
    "hwk-niederbayern-oberpfalz": HwkNiederbayernOberpfalzScraper,
    "hwk-oberfranken": HwkOberfrankenScraper,
    "hwk-mittelfranken": HwkMittelfrankenScraper,
    "hwk-unterfranken": HwkUnterfrankenScraper,
    "hwk-schwaben": HwkSchwabenScraper,
    "hwk-erfurt": HwkErfurtScraper,
    "hwk-ostthueringen-gera": HwkOstthueringenGeraScraper,
    "hwk-suedthueringen-suhl": HwkSuedthueringenSuhlScraper,
    "hwk-halle-saale": HwkHalleSaaleScraper,
    "hwk-magdeburg": HwkMagdeburgScraper,
    "hwk-dresden": HwkDresdenScraper,
    "hwk-chemnitz": HwkChemnitzScraper,
    "hwk-leipzig": HwkLeipzigScraper,
    "hwk-cottbus": HwkCottbusScraper,
    "hwk-potsdam": HwkPotsdamScraper,
    "hwk-frankfurt-oder-ostbrandenburg": HwkFrankfurtOderOstbrandenburgScraper,
    "hwk-schwerin": HwkSchwerinScraper,
    "hwk-ostmecklenburg-vorpommern": HwkOstmecklenburgVorpommernScraper,
    "hwk-flensburg": HwkFlensburgScraper,
    "hwk-luebeck": HwkLuebeckScraper,
    "hwk-berlin": HwkBerlinScraper,
    "hwk-hamburg": HwkHamburgScraper,
    "hwk-bremen": HwkBremenScraper,
    "hwk-braunschweig-lueneburg-stade": HwkBraunschweigLueneburgStadeScraper,
    "hwk-hannover": HwkHannoverScraper,
    "hwk-hildesheim-suedniedersachsen": HwkHildesheimSuedniedersachsenScraper,
    "hwk-oldenburg": HwkOldenburgScraper,
    "hwk-osnabrueck-emsland-grafschaft-bentheim": HwkOsnabrueckEmslandGrafschaftBentheimScraper,
    "hwk-ostfriesland": HwkOstfrieslandScraper,
    "hwk-koeln": HwkKoelnScraper,
    "hwk-duesseldorf": HwkDuesseldorfScraper,
    "hwk-aachen": HwkAachenScraper,
    "hwk-ostwestfalen-lippe-zu-bielefeld": HwkOstwestfalenLippeZuBielefeldScraper,
    "hwk-muenster": HwkMuensterScraper,
    "hwk-suedwestfalen": HwkSuedwestfalenScraper,
    "hwk-dortmund": HwkDortmundScraper,
}

# Regional batches for parallel CI matrix jobs — each runner gets its own egress IP.
# Heavy scrapers are spread across groups so wall time stays balanced (~5–8 min).
SCRAPE_GROUPS: dict[str, tuple[str, ...]] = {
    "west": (
        "hwk-koblenz", "hwk-kassel", "hwk-rhein-main", "hwk-wiesbaden", "hwk-trier",
        "hwk-pfalz", "hwk-rheinhessen", "hwk-saarland", "hwk-karlsruhe", "hwk-mannheim",
        "hwk-koeln", "hwk-duesseldorf", "hwk-aachen",
    ),
    "south": (
        "hwk-niederbayern-oberpfalz", "hwk-oberfranken", "hwk-chemnitz",
        "hwk-muenchen-und-oberbayern", "hwk-mittelfranken", "hwk-unterfranken",
        "hwk-schwaben", "hwk-stuttgart", "hwk-ulm", "hwk-freiburg", "hwk-konstanz",
        "hwk-reutlingen", "hwk-heilbronn-franken",
    ),
    "east": (
        "hwk-hannover", "hwk-osnabrueck-emsland-grafschaft-bentheim", "hwk-erfurt",
        "hwk-ostthueringen-gera", "hwk-suedthueringen-suhl", "hwk-halle-saale",
        "hwk-magdeburg", "hwk-dresden", "hwk-leipzig", "hwk-cottbus", "hwk-potsdam",
        "hwk-frankfurt-oder-ostbrandenburg", "hwk-berlin",
    ),
    "north": (
        "hwk-ostwestfalen-lippe-zu-bielefeld", "hwk-muenster", "hwk-suedwestfalen",
        "hwk-dortmund", "hwk-schwerin", "hwk-ostmecklenburg-vorpommern", "hwk-flensburg",
        "hwk-luebeck", "hwk-hamburg", "hwk-bremen", "hwk-braunschweig-lueneburg-stade",
        "hwk-oldenburg", "hwk-hildesheim-suedniedersachsen", "hwk-ostfriesland",
    ),
}


def _validate_scrape_groups() -> None:
    grouped = [slug for slugs in SCRAPE_GROUPS.values() for slug in slugs]
    if len(grouped) != len(set(grouped)):
        raise ValueError("SCRAPE_GROUPS contains duplicate chamber slugs")
    missing = set(SCRAPERS) - set(grouped)
    extra = set(grouped) - set(SCRAPERS)
    if missing or extra:
        raise ValueError(f"SCRAPE_GROUPS mismatch: missing={sorted(missing)}, extra={sorted(extra)}")


_validate_scrape_groups()

FORMAT_DISPLAY = {
    "full_time":    "Vollzeit",
    "part_time":    "Teilzeit",
    "part_or_full": "Teil- oder Vollzeit",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
COURSES_JSON = DATA_DIR / "courses.json"            # upcoming + undated (bundled into the site)
ARCHIVE_JSON = DATA_DIR / "courses_archive.json"    # past courses (lazy-loaded on demand)
MANUAL_FEES_JSON = DATA_DIR / "manual" / "exam_fees_manual.json"
GEOCODE_CACHE = DATA_DIR / "cache" / "geocode_cache.json"

AVAIL_RANK = {"available": 0, "waitlist": 1, "unknown": 2, "full": 3}


def _short_name(name: str) -> str:
    return name.replace("Handwerkskammer", "HWK").strip()


def _to_float(value) -> float | None:
    return float(value) if value is not None else None


def _to_iso(value) -> str | None:
    """Normalise a date to an ISO string. Saarland emits date objects; others emit strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()   # datetime.date / datetime.datetime


def _course_fee_display(fee: float | None) -> str:
    return "—" if fee is None else _fmt(fee)


def _course_key(rec: dict) -> tuple:
    return (
        rec["chamber_slug"],
        rec.get("source_url", ""),
        rec.get("start_date") or "null",
        rec.get("end_date") or "null",
    )


def _is_past(rec: dict, today_iso: str) -> bool:
    sd = rec.get("start_date")
    return sd is not None and sd < today_iso


def offer_to_record(result: ScrapeResult, offer) -> dict:
    """Convert a RawCourseOffer (+ chamber metadata) into a JSON course record."""
    if offer.trade_name is None:
        trade_slug, trade_name = normalize_trade(None)
        title = build_course_title(None, offer.parts)
    else:
        trade_slug, trade_name = normalize_trade(offer.trade_name)
        title = build_course_title(trade_name, offer.parts)
    fee = _to_float(offer.course_fee)
    return {
        "chamber_slug":     result.chamber_slug,
        "chamber_name":     _short_name(result.chamber_name),
        "chamber_region":   result.chamber_region,
        "trade_slug":       trade_slug,
        "trade_name":       trade_name,
        "title":            title,
        "parts":            sorted(offer.parts),
        "format":           offer.format_key,
        "format_display":   FORMAT_DISPLAY.get(offer.format_key, offer.format_key),
        "teaching_mode":    offer.teaching_mode,
        "start_date":       _to_iso(offer.start_date),
        "end_date":         _to_iso(offer.end_date),
        "start_date_note":  offer.start_date_note or "",
        "duration_hours":   offer.duration_hours,
        "course_fee":       fee,
        "course_fee_display": _course_fee_display(fee),
        "exam_fee_scraped": _to_float(offer.exam_fee_scraped),
        "exam_fee_qualifier": offer.exam_fee_qualifier,
        "exam_fee":         None,   # resolved later
        "city":             offer.city,
        "street":           offer.street,
        "zip_code":         offer.zip_code,
        "latitude":         None,
        "longitude":        None,
        "availability":     offer.availability,
        "source_url":       offer.source_url,
    }


# ----------------------------------------------------------------------
# Merge / retention (replaces DB soft-delete cleanup)
# ----------------------------------------------------------------------

def merge_courses(previous: list[dict], fresh_by_chamber: dict[str, list[dict]], today_iso: str) -> list[dict]:
    """
    Rebuild the course set from a fresh scrape while retaining past courses.

    - Chambers NOT scraped this run keep all their previous records untouched.
    - A chamber with an EMPTY scrape keeps its previous records (safety mirror
      of the old ``if not scraped_keys: return``).
    - Otherwise: keep previous PAST records, take all FRESH records (fresh wins
      on key collision), and drop previous FUTURE records absent from the scrape.
    """
    scraped_chambers = set(fresh_by_chamber)
    merged: dict[tuple, dict] = {}

    # Untouched chambers (and empty-scrape chambers) carry forward verbatim.
    for rec in previous:
        cs = rec["chamber_slug"]
        if cs not in scraped_chambers or not fresh_by_chamber.get(cs):
            merged[_course_key(rec)] = rec

    for cs, fresh in fresh_by_chamber.items():
        if not fresh:
            continue
        # Retain previous PAST records for this chamber.
        for rec in previous:
            if rec["chamber_slug"] == cs and _is_past(rec, today_iso):
                merged[_course_key(rec)] = rec
        # Fresh records win on collision.
        for rec in fresh:
            merged[_course_key(rec)] = rec

    return _drop_stale_approx_dates(list(merged.values()), today_iso)


def _drop_stale_approx_dates(records: list[dict], today_iso: str) -> list[dict]:
    """
    Drop future first-of-month (day=01) records when an exact-date record exists
    for the same chamber/trade/parts/format in the same month+year.
    Ports ``_deactivate_stale_approx_dates``.
    """
    def sig(rec: dict) -> tuple:
        return (rec["chamber_slug"], rec.get("trade_slug"), tuple(rec["parts"]), rec["format"])

    exact_months: set[tuple] = set()
    for rec in records:
        sd = rec.get("start_date")
        if sd and sd >= today_iso and not sd.endswith("-01"):
            exact_months.add((*sig(rec), sd[:7]))   # YYYY-MM

    kept = []
    for rec in records:
        sd = rec.get("start_date")
        if sd and sd >= today_iso and sd.endswith("-01") and (*sig(rec), sd[:7]) in exact_months:
            continue   # superseded by an exact-date record
        kept.append(rec)
    return kept


# ----------------------------------------------------------------------
# Geocoding + hardcoded coordinate overrides
# ----------------------------------------------------------------------

def apply_coordinates(records: list[dict], geocoder: Geocoder):
    for rec in records:
        cs = rec["chamber_slug"]
        if cs == "hwk-saarland":
            rec["latitude"], rec["longitude"] = HWK_SAARLAND_LAT, HWK_SAARLAND_LNG
            continue
        if cs == "hwk-rheinhessen":
            rec["latitude"], rec["longitude"] = rh_resolve_coords(rec.get("street", "")) or RH_DEFAULT_COORDS
            continue
        if (
            cs == "hwk-suedthueringen-suhl"
            and rec.get("zip_code") == "98530"
            and (rec.get("city") or "").startswith("Rohr")
        ):
            rec["latitude"] = ROHR_CAMPUS["latitude"]
            rec["longitude"] = ROHR_CAMPUS["longitude"]
            rec["street"] = ROHR_CAMPUS["street"]
            rec["city"] = ROHR_CAMPUS["city"]
            continue
        if not rec.get("city"):
            continue
        query = build_query(rec.get("street", ""), rec.get("zip_code", ""), rec["city"], rec.get("chamber_region", ""))
        coords = geocoder.lookup(query)
        if coords:
            rec["latitude"], rec["longitude"] = coords


# ----------------------------------------------------------------------
# Derived datasets
# ----------------------------------------------------------------------

def _load_manual_fee_rows() -> list[dict]:
    if not MANUAL_FEES_JSON.exists():
        return []
    return json.loads(MANUAL_FEES_JSON.read_text(encoding="utf-8"))


def build_exam_fees_nested(lookup: dict) -> dict:
    """
    Build the nested exam-fee structure the AFBG calculator consumes:
      {chamber_slug: {trade_slug|'null': {part: {fee, fee_max, qualifier}}}}
    """
    nested: dict = {}
    
    # Helper function to turn any part representation (int, set, frozenset) into a sortable tuple
    def sort_key(kv):
        chamber_slug, trade_slug, part = kv[0]
        if isinstance(part, (set, frozenset)):
            part_sort = tuple(sorted(part))
        elif isinstance(part, tuple):
            part_sort = part
        else:
            part_sort = (part,)  # Wrap single int in a tuple
        return (chamber_slug, trade_slug or "", part_sort)

    for (chamber_slug, trade_slug, part), v in sorted(lookup.items(), key=sort_key):
        tkey = trade_slug if trade_slug else "null"
        
        # Format the key cleanly if it's a frozenset/iterable (e.g., "1, 2" instead of "frozenset({1, 2})")
        if isinstance(part, (set, frozenset, tuple)):
            part_str = ",".join(map(str, sorted(part)))
        else:
            part_str = str(part)

        nested.setdefault(chamber_slug, {}).setdefault(tkey, {})[part_str] = {
            "fee": v["fee"], "fee_max": v["fee_max"], "qualifier": v["qualifier"]
        }
    return nested


def build_course_fees(records: list[dict], today_iso: str) -> list[dict]:
    """
    AFBG projection: the next-available course fee per (chamber, trade, parts).
    Ports the ranking logic from the old ``AfbgView``.
    """
    def sort_key(rec: dict):
        sd = rec.get("start_date")
        is_future = sd is None or sd >= today_iso
        avail = AVAIL_RANK.get(rec.get("availability"), AVAIL_RANK["unknown"])
        if sd:
            d = date.fromisoformat(sd).toordinal()
            date_score = d if is_future else (10_000_000 - d)
        else:
            date_score = 5_000_000
        return (0 if is_future else 1, avail, date_score)

    candidates = sorted(
        (r for r in records if r.get("course_fee") is not None),
        key=sort_key,
    )
    seen: dict[tuple, dict] = {}
    for r in candidates:
        key = (r["chamber_slug"], r["trade_slug"], tuple(r["parts"]))
        if key not in seen:
            seen[key] = {
                "chamber_slug":     r["chamber_slug"],
                "trade_slug":       r["trade_slug"],
                "parts":            r["parts"],
                "fee":              r["course_fee"],
                "exam_fee_scraped": r.get("exam_fee_scraped"),
                "is_generic":       all(p in (3, 4) for p in r["parts"]),
            }
    return list(seen.values())


def build_trades_from_records(records: list[dict]) -> list[dict]:
    trades: dict[str, dict] = {}
    for rec in records:
        trades[rec["trade_slug"]] = {"slug": rec["trade_slug"], "name": rec["trade_name"]}
    return sorted(trades.values(), key=lambda t: t["name"])


def build_chambers_and_trades(records: list[dict], results: dict[str, ScrapeResult], previous_chambers: list[dict]) -> tuple[list[dict], list[dict]]:
    # Chambers: union of those seen this run + any retained from previous data.
    chambers: dict[str, dict] = {c["slug"]: c for c in previous_chambers}
    for res in results.values():
        chambers[res.chamber_slug] = {
            "slug":   res.chamber_slug,
            "name":   _short_name(res.chamber_name),
            "region": res.chamber_region,
        }
    return (
        sorted(chambers.values(), key=lambda c: c["name"]),
        build_trades_from_records(records),
    )


# ----------------------------------------------------------------------
# Top-level run
# ----------------------------------------------------------------------

@dataclass
class RunReport:
    per_chamber: dict[str, int]
    total_courses: int


@dataclass
class ScrapeBatch:
    fresh_by_chamber: dict[str, list[dict]]
    scraped_exam_rows: list[dict]
    results: dict[str, ScrapeResult]
    per_chamber: dict[str, int]


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_previous_courses() -> list[dict]:
    # The dataset is split into upcoming (COURSES_JSON) + archived (ARCHIVE_JSON)
    # on disk; the pipeline works on their union so history is never lost.
    records: list[dict] = []
    for path in (COURSES_JSON, ARCHIVE_JSON):
        if path.exists():
            records.extend(json.loads(path.read_text(encoding="utf-8")))
    return records


def _course_sort_key(r: dict) -> tuple:
    return (r["chamber_slug"], r["trade_name"] or "", r.get("start_date") or "9999", r.get("source_url", ""))


def _load_previous_exam_fees_nested() -> dict:
    path = DATA_DIR / "exam_fees.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("nested", {})


def _merge_exam_fees_nested(previous: dict, current: dict, scraped_chambers: set[str] | None) -> dict:
    if scraped_chambers is None:
        return current
    merged = {slug: fees for slug, fees in previous.items() if slug not in scraped_chambers}
    merged.update(current)
    return merged


def _resolve_and_write_derived(
    records: list[dict],
    scraped_rows: list[dict],
    manual_rows: list[dict],
    today_iso: str,
    scraped_chambers: set[str] | None = None,
):
    """Resolve each course's exam fee, then write courses/exam_fees/course_fees JSON."""
    for rec in records:
        harmonize_course_record(rec)
    lookup = build_exam_fee_lookup(scraped_rows, manual_rows)
    for rec in records:
        if scraped_chambers is not None and rec["chamber_slug"] not in scraped_chambers:
            continue
        rec["exam_fee"] = resolve_exam_fee(
            rec["chamber_slug"], rec["trade_slug"], rec["parts"], rec.get("exam_fee_scraped"), lookup,
            rec.get("exam_fee_qualifier", ""),
        )
    records.sort(key=_course_sort_key)
    # Split upcoming/undated (bundled) from past (lazy-loaded archive).
    upcoming = [r for r in records if not _is_past(r, today_iso)]
    archived = [r for r in records if _is_past(r, today_iso)]
    _write_json(COURSES_JSON, upcoming)
    _write_json(ARCHIVE_JSON, archived)
    nested = build_exam_fees_nested(lookup)
    nested = _merge_exam_fees_nested(_load_previous_exam_fees_nested(), nested, scraped_chambers)
    _write_json(DATA_DIR / "exam_fees.json", {"nested": nested})
    _write_json(DATA_DIR / "course_fees.json", build_course_fees(records, today_iso))


def _scraped_rows_from_courses(records: list[dict]) -> list[dict]:
    """
    Re-derive scraped exam-fee rows from existing course records (for --rebake,
    which runs without scraping). Mirrors ``BaseScraper.scraped_exam_fee_rows``:
    single-part courses → per-part rows; multi-part combos → one exact-set
    combo-bundle row at the combined price; the generic trade slug maps back to
    ``None`` so trade-independent Parts III/IV resolve for every trade.
    """
    rows: list[dict] = []
    for r in records:
        if r.get("exam_fee_scraped") is None:
            continue
        trade_slug = None if r["trade_slug"] == GENERIC_TRADE_SLUG else r["trade_slug"]
        parts = r["parts"]
        fee = float(r["exam_fee_scraped"])
        if len(parts) == 1:
            rows.append({
                "chamber_slug": r["chamber_slug"],
                "trade_slug":   trade_slug,
                "part":         parts[0],
                "fee":          fee,
                "qualifier":    r.get("exam_fee_qualifier", ""),
            })
        else:
            rows.append({
                "chamber_slug": r["chamber_slug"],
                "trade_slug":   trade_slug,
                "parts":        sorted(parts),
                "fee":          fee,
                "qualifier":    r.get("exam_fee_qualifier", ""),
            })
    return rows


def _published_exam_fee_rows_from_scrapers() -> list[dict]:
    """Chamber-wide exam fees injected at collect() time, not stored on offers."""
    rows: list[dict] = []
    for cls in SCRAPERS.values():
        published = getattr(cls, "published_exam_fee_rows", None)
        if not callable(published):
            continue
        try:
            rows.extend(cls().published_exam_fee_rows())
        except Exception:
            logger.warning(
                "Could not load published exam fees for %s",
                getattr(cls, "chamber_slug", cls.__name__),
                exc_info=True,
            )
    return rows


def rebake() -> int:
    """
    Re-resolve exam fees and the derived datasets from the existing
    ``data/courses.json`` WITHOUT scraping. Use after editing
    ``data/manual/exam_fees_manual.json`` to apply manual fee changes.
    """
    records = _load_previous_courses()
    if not records:
        raise SystemExit("No data/courses.json to rebake — run a scrape first.")

    today_iso = date.today().isoformat()
    scraped_rows = _scraped_rows_from_courses(records)
    scraped_rows.extend(_published_exam_fee_rows_from_scrapers())
    manual_rows = _load_manual_fee_rows()
    _resolve_and_write_derived(records, scraped_rows, manual_rows, today_iso)
    _write_json(DATA_DIR / "trades.json", build_trades_from_records(records))
    logger.info("Rebaked %d courses with %d manual fee row(s).", len(records), len(manual_rows))
    return len(records)


def _scrape_workers(chamber_count: int) -> int:
    if chamber_count <= SCRAPE_PARALLEL_CAP_THRESHOLD:
        return chamber_count
    return min(SCRAPE_MAX_WORKERS, chamber_count)


def _collect_chamber(slug: str, cls: type) -> ScrapeResult | None:
    """Run one chamber's scraper; on failure log and return None (run continues)."""
    logger.info("▶ %s", slug)
    try:
        result = cls().collect()
        logger.info("  %s: %d offers", slug, len(result.offers))
        return result
    except Exception:
        logger.exception("  %s: scrape failed — keeping previous data for this chamber", slug)
        return None


        return None


def _scrape_selected(selected: dict[str, type]) -> ScrapeBatch:
    workers = _scrape_workers(len(selected))
    logger.info("Scraping %d chamber(s) with max_workers=%d", len(selected), workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {slug: pool.submit(_collect_chamber, slug, cls) for slug, cls in selected.items()}
        raw = {slug: fut.result() for slug, fut in futures.items()}

    results: dict[str, ScrapeResult] = {slug: r for slug, r in raw.items() if r is not None}
    fresh_by_chamber: dict[str, list[dict]] = {}
    scraped_exam_rows: list[dict] = []
    per_chamber: dict[str, int] = {}

    for slug in selected:
        result = results.get(slug)
        if result is None:
            fresh_by_chamber[slug] = []
            per_chamber[slug] = 0
            continue
        fresh_by_chamber[slug] = [offer_to_record(result, o) for o in result.offers]
        scraped_exam_rows.extend(result.exam_fee_rows)
        per_chamber[slug] = len(result.offers)

    return ScrapeBatch(fresh_by_chamber, scraped_exam_rows, results, per_chamber)


def _chamber_meta(result: ScrapeResult) -> dict:
    return {
        "chamber_slug": result.chamber_slug,
        "chamber_name": result.chamber_name,
        "chamber_region": result.chamber_region,
        "chamber_website": result.chamber_website,
    }


def _result_from_meta(meta: dict) -> ScrapeResult:
    return ScrapeResult(
        chamber_slug=meta["chamber_slug"],
        chamber_name=meta["chamber_name"],
        chamber_region=meta["chamber_region"],
        chamber_website=meta["chamber_website"],
    )


def write_scrape_partial(batch: ScrapeBatch, path: Path, chambers: list[str]) -> None:
    payload = {
        "chambers": chambers,
        "fresh_by_chamber": batch.fresh_by_chamber,
        "scraped_exam_rows": batch.scraped_exam_rows,
        "per_chamber": batch.per_chamber,
        "chamber_meta": {
            slug: _chamber_meta(batch.results[slug])
            for slug in chambers
            if slug in batch.results
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_scrape_partial(path: Path) -> ScrapeBatch:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = {slug: _result_from_meta(meta) for slug, meta in payload["chamber_meta"].items()}
    return ScrapeBatch(
        fresh_by_chamber=payload["fresh_by_chamber"],
        scraped_exam_rows=payload["scraped_exam_rows"],
        results=results,
        per_chamber=payload["per_chamber"],
    )


def _finalize_batch(batch: ScrapeBatch, today_iso: str) -> RunReport:
    previous = _load_previous_courses()
    records = merge_courses(previous, batch.fresh_by_chamber, today_iso)

    geocoder = Geocoder(GEOCODE_CACHE)
    apply_coordinates(records, geocoder)
    geocoder.save()

    manual_rows = _load_manual_fee_rows()
    _resolve_and_write_derived(
        records,
        batch.scraped_exam_rows,
        manual_rows,
        today_iso,
        scraped_chambers=set(batch.results.keys()),
    )

    previous_chambers = (
        json.loads((DATA_DIR / "chambers.json").read_text(encoding="utf-8"))
        if (DATA_DIR / "chambers.json").exists()
        else []
    )
    chambers, trades = build_chambers_and_trades(records, batch.results, previous_chambers)
    _write_json(DATA_DIR / "chambers.json", chambers)
    _write_json(DATA_DIR / "trades.json", trades)

    logger.info("Wrote %d courses, %d chambers, %d trades.", len(records), len(chambers), len(trades))
    return RunReport(per_chamber=batch.per_chamber, total_courses=len(records))


def merge_scrape_partials(partial_paths: list[Path], dry_run: bool = False) -> RunReport:
    if not partial_paths:
        raise ValueError("No scrape partial files provided")

    combined = ScrapeBatch({}, [], {}, {})
    per_chamber: dict[str, int] = {}

    for path in partial_paths:
        batch = _load_scrape_partial(path)
        combined.fresh_by_chamber.update(batch.fresh_by_chamber)
        combined.scraped_exam_rows.extend(batch.scraped_exam_rows)
        combined.results.update(batch.results)
        per_chamber.update(batch.per_chamber)

    combined.per_chamber = per_chamber
    logger.info(
        "Merging %d partial scrape(s) covering %d chamber(s).",
        len(partial_paths),
        len(combined.fresh_by_chamber),
    )

    if dry_run:
        logger.info("Dry run — nothing written.")
        return RunReport(per_chamber=per_chamber, total_courses=sum(per_chamber.values()))

    return _finalize_batch(combined, date.today().isoformat())


def run(
    chamber: str | None = None,
    chambers: list[str] | None = None,
    group: str | None = None,
    dry_run: bool = False,
    partial_out: Path | None = None,
) -> RunReport:
    if group is not None:
        if group not in SCRAPE_GROUPS:
            raise ValueError(f"Unknown scrape group {group!r}; choices: {', '.join(SCRAPE_GROUPS)}")
        chambers = list(SCRAPE_GROUPS[group])
    elif chamber is not None:
        chambers = [chamber]
    elif chambers is None:
        chambers = list(SCRAPERS)

    unknown = [slug for slug in chambers if slug not in SCRAPERS]
    if unknown:
        raise ValueError(f"Unknown chamber slug(s): {', '.join(unknown)}")

    selected = {slug: SCRAPERS[slug] for slug in chambers}
    batch = _scrape_selected(selected)

    if partial_out is not None:
        write_scrape_partial(batch, partial_out, chambers)
        logger.info("Wrote scrape partial to %s", partial_out)
        return RunReport(per_chamber=batch.per_chamber, total_courses=sum(batch.per_chamber.values()))

    if dry_run:
        logger.info("Dry run — nothing written.")
        return RunReport(per_chamber=batch.per_chamber, total_courses=sum(batch.per_chamber.values()))

    return _finalize_batch(batch, date.today().isoformat())
