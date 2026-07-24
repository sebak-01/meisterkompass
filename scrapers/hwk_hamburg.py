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

Exam fees are parsed from the course-page prose when stated (e.g. ELBCAMPUS
``Für Ihren Lehrgang betragen diese z. Zt. … €``); otherwise they fall back to
manual curation in ``data/manual/exam_fees_manual.json``.
"""

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title
from .format_keys import parse_format_key

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
APPOINTMENT_DATE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*[-–—]\s*(\d{2})\.(\d{2})\.(\d{4})"
)
EXAM_FEE_PAGE_RE = re.compile(
    r"Für Ihren Lehrgang betragen diese z\.\s*Zt\.\s*([\d.]+),(\d{2})\s*€",
    re.IGNORECASE,
)

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


def parse_availability_label(text: str, light_class: str = "") -> str:
    """Map ELBCAMPUS traffic-light labels to the project's availability enum."""
    lower = f"{text} {light_class}".lower()
    if "warteliste" in lower or "traffic-light--red" in lower:
        return "waitlist"
    if any(
        token in lower
        for token in (
            "keine buchbaren",
            "ausgebucht",
            "traffic-light--gray",
            "traffic-light--grey",
        )
    ):
        return "full"
    if any(
        token in lower
        for token in (
            "freie plätze",
            "wenige plätze",
            "traffic-light--green",
            "traffic-light--yellow",
        )
    ):
        return "available"
    return "unknown"


def parse_exam_fee_from_page(text: str) -> float | None:
    """Parse ELBCAMPUS course-page exam-fee prose."""
    match = EXAM_FEE_PAGE_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(".", "") + "." + match.group(2))


def _section_format_from_item(item: Tag) -> str | None:
    """Map Termine section headings (Tageskurs / Teilzeitkurs / Abendkurs) to format."""
    heading = item.find_previous("h3")
    if heading is None:
        return None
    return parse_format_key(heading.get_text(" ", strip=True), default="")


def parse_appointments(soup: BeautifulSoup) -> list[tuple[str, str, str, str | None]]:
    """
    Parse Termine cards: ``(start_iso, end_iso, availability, format_key)``.

    ELBCAMPUS shows availability in ``li.wyn-appointment`` traffic lights
    (``Freie Plätze`` / ``Wenige Plätze`` / ``Warteliste`` /
    ``Keine buchbaren Plätze``). JSON-LD has no availability field.

    Displayed run dates under ``Tageskurs`` / ``Teilzeitkurs`` / ``Abendkurs``
    headings are authoritative; JSON-LD ``startDate`` is often the late-entry
    deadline rather than the first teaching day.
    """
    appointments: list[tuple[str, str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for item in soup.select("li.wyn-appointment"):
        time_el = item.select_one(".wyn-appointment__time")
        if time_el is None:
            continue
        match = APPOINTMENT_DATE_RE.search(time_el.get_text(" ", strip=True))
        if not match:
            continue
        start = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        end = f"{match.group(6)}-{match.group(5)}-{match.group(4)}"
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        label_el = item.select_one(".traffic-light-text")
        light_el = item.select_one("[class*='traffic-light--']")
        label = label_el.get_text(" ", strip=True) if label_el else ""
        light_class = " ".join(light_el.get("class") or []) if light_el else ""
        section_format = _section_format_from_item(item)
        appointments.append((
            start,
            end,
            parse_availability_label(label, light_class),
            section_format or None,
        ))
    return appointments


def match_appointment(
    appointments: list[tuple[str, str, str, str | None]],
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str, str, str | None] | None:
    """Match a JSON-LD course instance to a Termine card by end date, then start."""
    if end_date:
        for appointment in appointments:
            if appointment[1] == end_date:
                return appointment
    if start_date:
        for appointment in appointments:
            if appointment[0] == start_date:
                return appointment
    if len(appointments) == 1:
        return appointments[0]
    return None


def match_appointment_availability(
    appointments: list[tuple[str, str, str]],
    start_date: str | None,
    end_date: str | None,
) -> str:
    """
    Match a JSON-LD course instance to a Termine card.

    Display dates on the page often differ from schema.org ``startDate``
    (entry window vs first teaching day), but ``endDate`` usually aligns.
    """
    if not appointments:
        return "unknown"
    if end_date:
        for _start, end, availability, _format in appointments:
            if end == end_date:
                return availability
    if start_date:
        for start, _end, availability, _format in appointments:
            if start == start_date:
                return availability
    if len(appointments) == 1:
        return appointments[0][2]
    return "unknown"


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
        appointments = parse_appointments(soup)
        exam_fee_scraped = parse_exam_fee_from_page(soup.get_text(" ", strip=True))

        instances = course.get("hasCourseInstance") or []
        if isinstance(instances, dict):        # single instance serialized as one object
            instances = [instances]
        elif not isinstance(instances, list):
            instances = []
        prices = self._offer_prices(course.get("offers"), instances)

        offers: list[RawCourseOffer] = []
        seen_runs: set[tuple] = set()
        for idx, inst in enumerate(instances):
            try:
                offer = self._build_offer(
                    inst, prices[idx], trade_name, parts, title, url, appointments,
                    exam_fee_scraped,
                )
            except Exception as exc:
                logger.warning("HWK Hamburg: error parsing instance %d of %s: %s",
                               idx, url, exc)
                continue
            run_key = (
                offer.start_date,
                offer.end_date,
                offer.format_key,
                offer.teaching_mode,
                offer.street,
                offer.zip_code,
                offer.course_fee,
            )
            if run_key in seen_runs:
                continue
            seen_runs.add(run_key)
            offers.append(offer)
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

    def _build_offer(
        self,
        inst: dict,
        price: float | None,
        trade_name: str | None,
        parts: list[int],
        title: str,
        source_url: str,
        appointments: list[tuple[str, str, str, str | None]] | None = None,
        exam_fee_scraped: float | None = None,
    ) -> RawCourseOffer:
        course_mode = inst.get("courseMode")
        workload = parse_workload_hours(inst.get("courseWorkload"))

        location = inst.get("location")
        location = location[0] if isinstance(location, list) and location else location
        address = location.get("address") if isinstance(location, dict) else None
        address = address if isinstance(address, dict) else {}
        street   = (address.get("streetAddress") or "").strip()
        zip_code = (address.get("postalCode") or "").strip()
        city     = (address.get("addressLocality") or "Hamburg").strip()
        start_date = iso_date(inst.get("startDate"))
        end_date = iso_date(inst.get("endDate"))
        matched = match_appointment(appointments or [], start_date, end_date)
        if matched:
            start_date, end_date, availability, section_format = matched
            format_key = section_format or parse_format(course_mode)
        else:
            availability = match_appointment_availability(
                appointments or [], start_date, end_date,
            )
            format_key = parse_format(course_mode)

        return RawCourseOffer(
            title=title,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=parse_mode(course_mode),
            start_date=start_date,
            end_date=end_date,
            duration_hours=workload,
            course_fee=price,
            exam_fee_scraped=exam_fee_scraped,
            city=city,
            street=street,
            zip_code=zip_code,
            availability=availability,
            source_url=source_url,
            scraped_raw={
                "course_name":  title,
                "courseMode":   inst.get("courseMode"),
                "workload":     inst.get("courseWorkload"),
                "availability_label": availability,
            },
        )
