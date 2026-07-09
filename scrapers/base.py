"""
scrapers/base.py

"""

import logging
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

GENERIC_TRADE_SLUG = "allgemein-teil-iii-iv"
GENERIC_TRADE_NAME = "Wirtschaft, Recht, Pädagogik"

# Human-readable names for generic (trade-independent) exam parts
_GENERIC_PART_NAMES: dict[tuple[int, ...], str] = {
    (3,):    "Wirtschaft und Recht",
    (4,):    "Berufs- und Arbeitspädagogik",
    (3, 4):  "Wirtschaft und Recht, Pädagogik",
}

_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def slugify(value: str) -> str:
    """
    Minimal ASCII slugify matching Django's ``django.utils.text.slugify``
    output for the trade names this project sees (umlauts transliterate via
    NFKD, then non-word chars collapse to single hyphens).
    """
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def normalize_trade(trade_name: str | None) -> tuple[str, str]:
    """
    Pure replacement for the old DB-backed ``_resolve_trade``.

    Returns ``(slug, display_name)``. ``None`` (generic Parts III/IV course)
    resolves to the shared generic trade.
    """
    if trade_name is None:
        return GENERIC_TRADE_SLUG, GENERIC_TRADE_NAME
    return slugify(trade_name), trade_name


def build_course_title(trade_name: str | None, parts: list[int]) -> str:
    """
    Build a normalised, human-readable course title without the
    "Meistervorbereitungskurs" prefix (redundant on a platform dedicated
    to these courses).

    Trade-specific courses:
        "Metallbauer (Teile I + II)"
        "Friseur (Teil I)"

    Generic (trade-independent) courses use the official German part names:
        Part III only  → "Wirtschaft und Recht (Teil III)"
        Part IV only   → "Berufs- und Arbeitspädagogik (Teil IV)"
        Parts III + IV → "Wirtschaft und Recht, Pädagogik (Teile III + IV)"
    """
    parts_label = " + ".join(_ROMAN[p] for p in parts)
    prefix = "Teile" if len(parts) > 1 else "Teil"

    if trade_name:
        base = trade_name
    else:
        base = _GENERIC_PART_NAMES.get(tuple(sorted(parts)), "Allgemein")

    return f"{base} ({prefix} {parts_label})"


@dataclass
class RawCourseOffer:
    title:            str
    trade_name:       str | None
    parts:            list[int]
    format_key:       str
    teaching_mode:    str
    start_date:       str | None
    end_date:         str | None
    duration_hours:   int | None
    course_fee:       float | None
    city:             str
    # Fields with defaults (must come after all non-default fields)
    exam_fee_scraped: float | None = None   # stated on course page (e.g. HWK Trier)
    street:           str = ""
    zip_code:         str = ""
    availability:     str = "unknown"
    source_url:       str = ""
    scraped_raw:      dict = field(default_factory=dict)


@dataclass
class ScrapeResult:
    """In-memory output of one chamber scrape."""
    chamber_slug:    str
    chamber_name:    str
    chamber_region:  str
    chamber_website: str
    offers:          list[RawCourseOffer] = field(default_factory=list)
    exam_fee_rows:   list[dict] = field(default_factory=list)


class BaseScraper(ABC):
    chamber_slug:    str = ""
    chamber_name:    str = ""
    chamber_region:  str = ""
    chamber_website: str = ""
    source_url:      str = ""
    request_delay:   float = 1.0

    def __init__(self):
        if not self.chamber_slug:
            raise ValueError(f"{self.__class__.__name__} must define chamber_slug")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; MeistervergleichBot/1.0; "
                "+https://meistervergleich.de/bot)"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
        })

    @abstractmethod
    def fetch_raw_courses(self) -> list[RawCourseOffer]: ...

    max_retries: int = 3

    def get(self, url: str, **kwargs) -> requests.Response | None:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.request_delay)
                r = self.session.get(url, timeout=20, **kwargs)
                r.raise_for_status()
                return r
            except requests.RequestException as exc:
                last_exc = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))   # back off before retrying transient errors
        logger.warning("GET %s failed after %d attempts: %s", url, self.max_retries, last_exc)
        return None

    def parse_html(self, url: str, **kwargs) -> BeautifulSoup | None:
        r = self.get(url, **kwargs)
        return BeautifulSoup(r.text, "html.parser") if r else None

    def scraped_exam_fee_rows(self, offers: list[RawCourseOffer]) -> list[dict]:
        """
        Derive exam-fee lookup rows from any offer carrying ``exam_fee_scraped``.

        Any scraper that sets ``exam_fee_scraped`` on its offers contributes
        scraped exam fees automatically (replacing the old per-chamber
        ``_save_courses`` overrides).

        Two offer shapes map to two different row kinds, matching how
        ``resolve_exam_fee`` consumes them:

        - **Single-part offer** (e.g. HWK Saarland's "Elektrotechniker Teil I",
          990 €) → a per-part row ``{part, fee}``. These feed the per-part sum.
        - **Multi-part combo offer** (e.g. the "Teile I+II+III+IV" Vollzeit
          course at one combined, discounted 1.790 €) → a single combo-bundle
          row ``{parts, fee}`` keyed on the exact set of parts.

        Emitting a combo as one exact-set row is essential: the combined fee is
        *not* the sum of its parts, and spreading it as a per-part fee onto each
        part (the previous behaviour) both overstated any part lacking its own
        single-part course and, once summed back up, produced a total far above
        the real combined price (Saarland Tischler resolved to 3.660 € instead
        of the scraped 1.300 €). Parts III/IV, which no trade sells on their own,
        still resolve via the trade-independent generic rows below.

        Trade-independent courses (Parts III/IV, ``trade_name is None``) are
        keyed with ``trade_slug=None`` — the same convention as the manual fee
        rows and the ``(chamber, None, part)`` fallback in ``resolve_exam_fee``
        — so that e.g. "Teil IV" resolves for every trade, not only when the
        literal generic slug happens to be queried.
        """
        rows: list[dict] = []
        for raw in offers:
            if raw.exam_fee_scraped is None:
                continue
            trade_slug = None if raw.trade_name is None else normalize_trade(raw.trade_name)[0]
            fee = float(raw.exam_fee_scraped)
            if len(raw.parts) == 1:
                rows.append({
                    "chamber_slug": self.chamber_slug,
                    "trade_slug":   trade_slug,
                    "part":         raw.parts[0],
                    "fee":          fee,
                    "source_url":   raw.source_url,
                })
            else:
                rows.append({
                    "chamber_slug": self.chamber_slug,
                    "trade_slug":   trade_slug,
                    "parts":        sorted(raw.parts),
                    "fee":          fee,
                    "source_url":   raw.source_url,
                })
        return rows

    def collect(self) -> ScrapeResult:
        """Run the scraper and return its in-memory result (no persistence)."""
        logger.info("Starting scraper: %s", self.__class__.__name__)
        offers = self.fetch_raw_courses()
        return ScrapeResult(
            chamber_slug=self.chamber_slug,
            chamber_name=self.chamber_name or self.chamber_slug,
            chamber_region=self.chamber_region,
            chamber_website=self.chamber_website,
            offers=offers,
            exam_fee_rows=self.scraped_exam_fee_rows(offers),
        )