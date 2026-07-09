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
from urllib.parse import urljoin

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

WORKLOAD_PATTERN = re.compile(r"PT([\d.]+)H", re.IGNORECASE)
TRADE_PATTERN    = re.compile(r"Meistervorbereitung\s+im\s+(.+?)handwerk\b", re.IGNORECASE)

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


def _schema_token(value) -> str:
    """Lowercase a schema.org enum value, tolerating list and full-URI forms
    (e.g. ``["https://schema.org/OnSite"]`` → ``onsite``)."""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].lower()


def parse_workload_hours(workload: str | None) -> int | None:
    if not workload:
        return None
    m = WORKLOAD_PATTERN.search(workload)
    return int(float(m.group(1))) if m else None


def parse_mode(course_mode) -> str:
    return MODE_MAP.get(_schema_token(course_mode), "presence")


def parse_format(course_mode) -> str:
    return FORMAT_BY_MODE.get(_schema_token(course_mode), "full_time")


def parse_price(value) -> float | None:
    """Coerce a schema.org price (number or string like ``"2.490,00"`` / ``"2490 EUR"``)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.,]", "", str(value))
    if not cleaned:
        return None
    # German grouping: strip thousands '.', treat ',' as decimal separator.
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_trade(course_name: str) -> str | None:
    """Extract the trade from a trade page's course name; None if not a trade page."""
    m = TRADE_PATTERN.search(course_name or "")
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
        trade_urls = self._discover_trade_urls(overview)
        logger.info("HWK Hamburg: %d trade page(s) + %d cross-trade page(s).",
                    len(trade_urls), len(GENERIC_PAGES))

        offers: list[RawCourseOffer] = []
        for url in trade_urls:
            offers.extend(self._parse_course_page(url, parts=[1, 2], generic=False))
        for path, part in GENERIC_PAGES.items():
            offers.extend(self._parse_course_page(urljoin(BASE_URL, path), parts=[part], generic=True))

        logger.info("HWK Hamburg: parsed %d course offers total.", len(offers))
        return offers

    def _discover_trade_urls(self, overview: BeautifulSoup) -> list[str]:
        urls: set[str] = set()
        for a in overview.find_all("a", href=True):
            if "/weiterbildung/meistervorbereitung-im-" in a["href"]:
                urls.add(urljoin(BASE_URL, a["href"].split("?")[0]))
        return sorted(urls)

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
        if isinstance(instances, dict):        # single instance serialized as one object
            instances = [instances]
        elif not isinstance(instances, list):
            instances = []
        prices = self._offer_prices(course.get("offers"), instances)

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
    def _is_course(item) -> bool:
        """True if a JSON-LD node is a Course, tolerating list-valued or
        fully-qualified (``https://schema.org/Course``) ``@type``."""
        if not isinstance(item, dict):
            return False
        types = item.get("@type")
        types = types if isinstance(types, list) else [types]
        return any(str(t).rstrip("/").rsplit("/", 1)[-1] == "Course" for t in types)

    @classmethod
    def _extract_course(cls, soup: BeautifulSoup) -> dict | None:
        for block in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(block.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            nodes = data if isinstance(data, list) else [data]
            # Unwrap @graph containers, keeping any bare nodes alongside.
            expanded = []
            for node in nodes:
                if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                    expanded.extend(node["@graph"])
                else:
                    expanded.append(node)
            for item in expanded:
                if cls._is_course(item):
                    return item
        return None

    @staticmethod
    def _offer_prices(course_offers, instances: list) -> list[float | None]:
        """
        Resolve a per-instance price. Prefer an Offer attached to the instance
        itself; otherwise fall back to the Course-level ``offers`` array, which
        is positionally parallel to ``hasCourseInstance``. A single Course-level
        offer is broadcast to every instance (schema.org arrays are unordered
        sets, so one price commonly covers all runs).
        """
        def price_of(entry):
            if isinstance(entry, list):
                entry = entry[0] if entry else None
            if isinstance(entry, dict):
                return parse_price(entry.get("price"))
            return None

        course_offers = course_offers if isinstance(course_offers, list) else None
        single = None
        if course_offers and len(course_offers) == 1:
            single = price_of(course_offers[0])

        prices: list[float | None] = []
        for idx, inst in enumerate(instances):
            inst_price = price_of(inst.get("offers")) if isinstance(inst, dict) else None
            if inst_price is not None:
                prices.append(inst_price)
            elif single is not None:
                prices.append(single)
            elif course_offers and idx < len(course_offers):
                prices.append(price_of(course_offers[idx]))
            else:
                prices.append(None)
        return prices

    def _build_offer(self, inst: dict, price: float | None, trade_name: str | None,
                     parts: list[int], title: str, source_url: str) -> RawCourseOffer:
        course_mode = inst.get("courseMode")
        workload = parse_workload_hours(inst.get("courseWorkload"))

        location = inst.get("location")
        location = location[0] if isinstance(location, list) and location else location
        address = location.get("address") if isinstance(location, dict) else None
        address = address if isinstance(address, dict) else {}
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
