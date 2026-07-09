"""
scrapers/hwk_hamburg.py

Scraper for HWK Hamburg Meistervorbereitungslehrgänge.
Source: https://www.elbcampus.de — the ELBCAMPUS Kompetenzzentrum, the chamber's
in-house education provider.

Unlike the ...courselist.html CMS chambers (Koblenz, Berlin), ELBCAMPUS is a
bespoke site with one page per course under ``/weiterbildung/<slug>/``. Each of
those pages embeds a schema.org ``Course`` object in an ``application/ld+json``
block, with a ``hasCourseInstance`` array (one entry per scheduled run: start/
end date, ``courseWorkload`` as an ISO-8601 ``PT<n>H`` duration, ``courseMode``,
and the ``location`` address) and a positionally-parallel ``offers`` array
carrying the price. This scraper reads that structured data rather than the
rendered HTML, so it's resilient to layout changes.

Three kinds of Meistervorbereitung page are collected:

- one page per trade (``…/meistervorbereitung-im-<trade>handwerk/``), discovered
  from the Meistervorbereitung overview — these are the fachspezifischen Teile
  I + II, with the trade taken from the course name;
- the cross-trade Teil III (``Gepr. Fachmann/-frau für kaufmännische
  Betriebsführung (HwO)``) and Teil IV (``AdA – Ausbildung der Ausbilder``),
  which every gewerk shares.

Exam fees are not part of the structured data (only the Kursentgelt), so — like
HWK Koblenz — they're left for manual curation in
``data/manual/exam_fees_manual.json``.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL     = "https://www.elbcampus.de"
OVERVIEW_URL = BASE_URL + "/weiterbildung/meistervorbereitung/"

# Cross-trade course pages: URL slug → generic exam part it prepares for.
GENERIC_PAGES: dict[str, int] = {
    "/weiterbildung/gepr.-fachmann-frau-fuer-kaufmaennische-betriebsfuehrung-hwo/": 3,
    "/weiterbildung/ada-ausbildung-der-ausbilder/": 4,
}

WORKLOAD_PATTERN = re.compile(r"PT(\d+)H", re.IGNORECASE)
TRADE_PATTERN    = re.compile(r"Meistervorbereitung\s+im\s+(.+?)(?:handwerk)?$", re.IGNORECASE)

# Delivery mode (schema.org courseMode) → the project's teaching_mode.
MODE_MAP = {
    "onsite":  "presence",
    "blended": "hybrid",
    "online":  "online",
}

# The JSON-LD carries no Vollzeit/Teilzeit label, and the page's format keywords
# (Tageskurs/Abendkurs/…) aren't tied to individual instances — so format is
# derived from the one per-instance signal that exists, the delivery mode:
# onsite Meister courses run as full-time day courses, blended-learning runs are
# berufsbegleitend (part-time).
FORMAT_BY_MODE = {
    "onsite":  "full_time",
    "blended": "part_time",
    "online":  "part_time",
}


def parse_workload_hours(workload: str | None) -> int | None:
    if not workload:
        return None
    m = WORKLOAD_PATTERN.search(workload)
    return int(m.group(1)) if m else None


def parse_mode(course_mode: str | None) -> str:
    return MODE_MAP.get((course_mode or "").strip().lower(), "presence")


def parse_format(course_mode: str | None) -> str:
    return FORMAT_BY_MODE.get((course_mode or "").strip().lower(), "full_time")


def parse_trade(course_name: str) -> str | None:
    """Extract the trade from a trade page's course name; None if not a trade page."""
    m = TRADE_PATTERN.match(course_name.strip())
    if not m:
        return None
    trade = m.group(1).strip().rstrip("- ").strip()
    return trade or None


def iso_date(value: str | None) -> str | None:
    """Trim an ISO datetime (``2026-10-12T00:00:00+00:00``) to its date part."""
    return value[:10] if value else None


class HwkHamburgScraper(BaseScraper):
    chamber_slug    = "hwk-hamburg"
    chamber_name    = "Handwerkskammer Hamburg"
    chamber_region  = "Hamburg"
    chamber_website = "https://www.hwk-hamburg.de"
    source_url      = OVERVIEW_URL
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        overview = self.parse_html(OVERVIEW_URL)
        if overview is None:
            logger.error("Could not fetch ELBCAMPUS Meistervorbereitung overview.")
            return []

        # Trade pages (Teile I + II) are discovered from the overview; the two
        # cross-trade pages (Teile III / IV) are fixed entry points.
        trade_paths = self._discover_trade_paths(overview)
        logger.info("HWK Hamburg: %d trade page(s) + %d cross-trade page(s).",
                    len(trade_paths), len(GENERIC_PAGES))

        offers: list[RawCourseOffer] = []
        for path in trade_paths:
            offers.extend(self._parse_course_page(BASE_URL + path, parts=[1, 2], generic=False))
        for path, part in GENERIC_PAGES.items():
            offers.extend(self._parse_course_page(BASE_URL + path, parts=[part], generic=True))

        logger.info("HWK Hamburg: parsed %d course offers total.", len(offers))
        return offers

    def _discover_trade_paths(self, overview: BeautifulSoup) -> list[str]:
        paths: set[str] = set()
        for a in overview.find_all("a", href=True):
            href = a["href"]
            if "/weiterbildung/meistervorbereitung-im-" in href:
                paths.add(href.replace(BASE_URL, "").split("?")[0])
        return sorted(paths)

    def _parse_course_page(self, url: str, parts: list[int], generic: bool) -> list[RawCourseOffer]:
        soup = self.parse_html(url)
        if soup is None:
            logger.warning("HWK Hamburg: could not fetch %s", url)
            return []

        course = self._extract_course(soup)
        if course is None:
            logger.warning("HWK Hamburg: no Course JSON-LD on %s", url)
            return []

        trade_name = None if generic else parse_trade(course.get("name", ""))
        title = build_course_title(trade_name, parts)

        instances = course.get("hasCourseInstance") or []
        prices = self._offer_prices(course.get("offers"), len(instances))

        offers: list[RawCourseOffer] = []
        for idx, inst in enumerate(instances):
            try:
                offers.append(self._build_offer(
                    inst, prices[idx], trade_name, parts, title, url,
                ))
            except Exception as exc:
                logger.warning("HWK Hamburg: error parsing instance %d of %s: %s",
                               idx, url, exc)
        return offers

    @staticmethod
    def _extract_course(soup: BeautifulSoup) -> dict | None:
        for block in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(block.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and item.get("@type") == "Course":
                    return item
        return None

    @staticmethod
    def _offer_prices(offers, count: int) -> list[float | None]:
        """
        Normalise the ``offers`` array (which is positionally parallel to
        ``hasCourseInstance``) into a per-instance price list. Each entry is
        either an Offer dict or a single-element list wrapping one.
        """
        prices: list[float | None] = [None] * count
        if not isinstance(offers, list):
            return prices
        for idx in range(min(count, len(offers))):
            entry = offers[idx]
            if isinstance(entry, list):
                entry = entry[0] if entry else None
            if isinstance(entry, dict) and entry.get("price") is not None:
                try:
                    prices[idx] = float(entry["price"])
                except (TypeError, ValueError):
                    pass
        return prices

    def _build_offer(self, inst: dict, price: float | None, trade_name: str | None,
                     parts: list[int], title: str, source_url: str) -> RawCourseOffer:
        course_mode = inst.get("courseMode")
        workload = parse_workload_hours(inst.get("courseWorkload"))

        address = (inst.get("location") or {}).get("address") or {}
        street   = (address.get("streetAddress") or "").strip()
        zip_code = (address.get("postalCode") or "").strip()
        city     = (address.get("addressLocality") or "Hamburg").strip()

        return RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=parse_format(course_mode),
            teaching_mode=parse_mode(course_mode),
            start_date=iso_date(inst.get("startDate")),
            end_date=iso_date(inst.get("endDate")),
            duration_hours=workload,
            course_fee=price,
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=source_url,
            scraped_raw={
                "course_name":  title,
                "courseMode":   inst.get("courseMode"),
                "workload":     inst.get("courseWorkload"),
            },
        )
