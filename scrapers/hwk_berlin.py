"""
scrapers/hwk_berlin.py

Scraper for HWK Berlin Meistervorbereitungslehrgänge.
Source: https://www.bildung4u.de (the chamber's Bildungsportal), org number 3911.

HWK Berlin runs the same course-management CMS as HWK Koblenz — the course
list lives at ``.../courselist.html`` (paginated, ``search-type=6`` selects
Meistervorbereitung) and each card links to a ``coursedetail.html?id=`` page.
The card layout is identical to Koblenz (``<div class='row'>`` → ``<h3>`` with
date range + format + title link → price / duration / city / availability),
so the field-extraction helpers mirror ``hwk_koblenz.py``.

The one meaningful difference is the title format. Berlin titles carry a
``Meistervorbereitungslehrgang`` / ``MVL`` prefix, repeat the ``Teil`` keyword
(``Teil I und Teil II``), and append a course number and format qualifier
(``… Vollzeit 1-26``, ``… Digital/ Live 2-27``), so this scraper uses its own
``parse_title``. Teile III and IV are cross-trade (generic) here; only Teile
I/II courses name a trade.

Exam fees are NOT listed on the course pages (only the Kursgebühr is); they
are curated manually in ``data/manual/exam_fees_manual.json`` like HWK Koblenz.
All courses are taught at the chamber's Bildungsstätte, Mehringdamm 14 in Berlin.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bildung4u.de"
LIST_URL = (
    BASE_URL + "/kurse/liste-3911,0,courselist.html"
    "?search-type=6&limit=20&offset={offset}"
)
PAGE_SIZE = 20

DEFAULT_STREET = "Mehringdamm 14"
DEFAULT_ZIP    = "10961"
DEFAULT_CITY   = "Berlin"

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# Prefix stripped before extracting the trade name from Teil I/II titles.
PREFIX_PATTERN = re.compile(r"^(?:Meistervorbereitungslehrgang|MVL)\s*", re.IGNORECASE)

# Matches one or more consecutive part tokens, each optionally re-prefixed with
# "Teil" (Berlin writes "Teil I und Teil II", not Koblenz's "Teile I und II").
PARTS_PATTERN = re.compile(
    r"Teile?\s+((?:\bIV\b|\bIII\b|\bII\b|\bI\b)(?:\s+und\s+(?:Teil\s+)?(?:\bIV\b|\bIII\b|\bII\b|\bI\b))*)",
    re.IGNORECASE,
)
# Anchors the start of the parts clause, used to slice off the trade name.
FIRST_PART_PATTERN = re.compile(r"\bTeile?\s+(?:IV|III|II|I)\b", re.IGNORECASE)

PRICE_PATTERN    = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_PATTERN = re.compile(r"(\d+)[\s\xa0]*(?:Std\.|UE|Ustd\.)", re.IGNORECASE)
DATE_PATTERN     = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def parse_title(title: str) -> tuple[str | None, list[int]]:
    """
    Extract (trade_name, parts) from a Berlin course title.

    Teile III/IV are cross-trade, so they yield no trade name (``build_course_title``
    then uses the official generic part names). Only when Teil I or II is present
    is the text between the prefix and the first ``Teil`` token taken as the trade.
    """
    t = title.strip()

    parts: set[int] = set()
    for m in PARTS_PATTERN.finditer(t):
        for token in re.split(r"\s+und\s+", m.group(1), flags=re.IGNORECASE):
            token = re.sub(r"Teile?", "", token, flags=re.IGNORECASE).strip().upper()
            if token in ROMAN:
                parts.add(ROMAN[token])
    if not parts:
        return None, []

    trade_name: str | None = None
    if {1, 2} & parts:
        body = PREFIX_PATTERN.sub("", t)
        first = FIRST_PART_PATTERN.search(body)
        if first:
            candidate = body[: first.start()].strip(" -–")
            trade_name = candidate or None

    return trade_name, sorted(parts)


def parse_format_and_mode(text: str) -> tuple[str, str]:
    """
    Returns (format_key, teaching_mode). Format (Voll-/Teilzeit) and delivery
    mode (online/hybrid/presence) are orthogonal in Berlin's titles, so they're
    detected independently. Defaults to part-time in presence.
    """
    lower = text.lower()
    format_key = "full_time" if "vollzeit" in lower else "part_time"
    if "hybrid" in lower:
        teaching_mode = "hybrid"
    elif "digital" in lower or "online" in lower:
        teaching_mode = "online"
    else:
        teaching_mode = "presence"
    return format_key, teaching_mode


def parse_price(text: str) -> float | None:
    m = PRICE_PATTERN.search(text)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + m.group(2))


def parse_duration(text: str) -> int | None:
    m = DURATION_PATTERN.search(text)
    return int(m.group(1)) if m else None


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht"  in lower: return "full"
    if "warteliste"  in lower: return "waitlist"
    if "wenige"      in lower: return "available"
    if "freie"       in lower: return "available"
    return "unknown"


class HwkBerlinScraper(BaseScraper):
    chamber_slug    = "hwk-berlin"
    chamber_name    = "Handwerkskammer Berlin"
    chamber_region  = "Berlin"
    chamber_website = "https://www.hwk-berlin.de"
    source_url      = LIST_URL.format(offset=0)
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        first = self.parse_html(LIST_URL.format(offset=0))
        if first is None:
            logger.error("Could not fetch HWK Berlin course list.")
            return []

        total = self._parse_total(first)
        logger.info("HWK Berlin: %d courses, %d page(s).", total, -(-total // PAGE_SIZE))

        all_offers = self._parse_page(first)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            soup = self.parse_html(LIST_URL.format(offset=offset))
            if soup is None:
                logger.warning("Failed at offset=%d, stopping.", offset)
                break
            all_offers.extend(self._parse_page(soup))

        logger.info("HWK Berlin: parsed %d course offers total.", len(all_offers))
        return all_offers

    def _parse_total(self, soup: BeautifulSoup) -> int:
        m = re.search(r"von\s+(\d+);\s*Seite", soup.get_text())
        if m:
            return int(m.group(1))
        # No total-count marker: fall back to the first page's card count. This
        # silently caps the scrape at one page, so surface it rather than hide it.
        fallback = len(soup.select("a[href*='coursedetail']"))
        logger.warning("HWK Berlin: total-count marker not found; falling back to "
                       "first-page count (%d) — pagination may be truncated.", fallback)
        return fallback

    def _parse_page(self, soup: BeautifulSoup) -> list[RawCourseOffer]:
        offers = []
        for link in soup.select("a[href*='coursedetail']"):
            try:
                offer = self._parse_card(link)
                if offer:
                    offers.append(offer)
            except Exception as exc:
                logger.warning("Error parsing card '%s': %s",
                               link.get_text(strip=True)[:60], exc)
        return offers

    def _parse_card(self, link: Tag) -> RawCourseOffer | None:
        title_text = link.get_text(strip=True)
        detail_url = link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        trade_name, parts = parse_title(title_text)
        if not parts:
            return None

        title_clean = build_course_title(trade_name, parts)

        card_row = link.find_parent("div", class_="row")
        if card_row is None:
            return None

        h3 = link.find_parent("h3")
        h3_text = h3.get_text(separator=" ", strip=True) if h3 else ""

        format_key, teaching_mode = parse_format_and_mode(f"{title_text} {h3_text}")

        dates = DATE_PATTERN.findall(h3_text)
        start_date = f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}" if len(dates) >= 1 else None
        end_date   = f"{dates[1][2]}-{dates[1][1]}-{dates[1][0]}" if len(dates) >= 2 else None

        card_text      = card_row.get_text(separator="\n", strip=True)
        price          = parse_price(card_text)
        duration_hours = parse_duration(card_text)
        availability   = parse_availability(card_text)

        street, zip_code = self._parse_detail_address(detail_url)

        return RawCourseOffer(
            title=title_clean,
            trade_name=trade_name,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=price,
            city=DEFAULT_CITY,
            street=street,
            zip_code=zip_code,
            availability=availability,
            source_url=detail_url,
            scraped_raw={
                "title":     title_text,
                "h3_text":   h3_text,
                "card_text": card_text[:500],
            },
        )

    def _parse_detail_address(self, url: str) -> tuple[str, str]:
        """
        Fetch the course detail page and extract the Lehrgangsort address.
        Returns (street, zip_code), falling back to the chamber's Bildungsstätte.
        """
        if not url:
            return DEFAULT_STREET, DEFAULT_ZIP
        try:
            soup = self.parse_html(url)
            if soup is None:
                return DEFAULT_STREET, DEFAULT_ZIP
            text = soup.get_text("\n")
            idx = text.find("Lehrgangsort")
            if idx >= 0:
                block = text[idx:idx + 300]
                zip_m = re.search(r"(\d{5})\s+(\S+.*)", block)
                if zip_m:
                    zip_code = zip_m.group(1)
                    lines = block[:zip_m.start()].strip().split("\n")
                    street = lines[-1].strip() if lines else ""
                    if street and re.search(r"\d", street):
                        return street, zip_code
        except Exception as exc:
            logger.warning("Could not fetch detail address from %s: %s", url, exc)

        return DEFAULT_STREET, DEFAULT_ZIP
