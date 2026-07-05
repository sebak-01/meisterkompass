"""
scrapers/hwk_wiesbaden.py

Scraper for Handwerkskammer Wiesbaden Meistervorbereitungskurse.
Overview: https://www.hwk-wiesbaden.de/artikel/die-meisterschaft-im-handwerk-44,0,4281.html

Same family of CMS as HWK Koblenz/Pfalz/Trier (artikel/...-44,X,Y.html article
pages, kurse/...,coursedetail.html course pages, kurse/liste-...,courselist.html
search results) — different chamber instance/theme though, so card markup is
parsed defensively (by locating the smallest ancestor of each coursedetail
link that contains both a price and a date, rather than assuming a fixed
class name like Koblenz's "div.row").

Page structure (verified 2026-06-21):
  1. The overview article lists one sub-article per trade ("Dachdecker",
     "Elektrotechnik", ... ) plus one generic "Teil III + IV" article that
     bundles Part III / Part IV / Part III+IV / AEVO ("Ausbildereignungs-
     prüfung") courses — these are hardcoded below (TRADE_PAGES), mirroring
     the hwk_saarland.py / hwk_rheinhessen.py approach for chambers with a
     small, stable set of trade pages.
  2. Each trade article shows up to ~4 course cards plus a "weitere Kurse"
     link to the full courselist.html search for that trade — we always
     follow that link and paginate it (limit/offset) rather than relying on
     the truncated preview on the article page.
  3. Each card: "<start> - <end>: <Format><Title>" heading + price + duration
     + optional "Anmeldeschluss <date>" + city ("Wetzlar" or "Wiesbaden") +
     availability, linking to a coursedetail.html page (id= the run's PK).

  Title patterns seen:
    "Meistervorbereitung im Dachdeckerhandwerk Teil I - Vollzeit"
    "Meistervorbereitung Teil III - Vollzeit"                      (generic)
    "Meistervorbereitung Teile III + IV - Vollzeit"                (generic combo)
    "Ausbildereignungsprüfung - Vollzeit"                          (generic, = Teil IV/AEVO)
  Trade name comes from the per-page TRADE_PAGES hint (not parsed from the
  title) since it's both more reliable and simpler; only parts/format are
  parsed per-card.

  Unlike the HWK Frankfurt-Rhein-Main "ml-99*" pages, every course run here
  is its own separate card/link with its own unambiguous title — there is
  no multi-module-tab attribution problem on this chamber's pages.

  Exam fees are not listed on these pages — left for manual entry, same as
  HWK Kassel and HWK Frankfurt-Rhein-Main. All HWK in Hesse seem to have the same exam fees.
"""

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

BASE_URL     = "https://www.hwk-wiesbaden.de"
OVERVIEW_URL = f"{BASE_URL}/artikel/die-meisterschaft-im-handwerk-44,0,4281.html"
PAGE_SIZE    = 20

# (trade article URL, canonical trade name or None for the generic Teil III/IV page)
TRADE_PAGES: list[tuple[str, str | None]] = [
    (f"{BASE_URL}/artikel/dachdeckerhandwerk-44,1013,4277.html",                          "Dachdecker"),
    (f"{BASE_URL}/artikel/elektrotechnikerhandwerk-44,1014,4278.html",                    "Elektrotechniker"),
    (f"{BASE_URL}/artikel/fahrzeuglackierer-44,1015,4280.html",                           "Fahrzeuglackierer"),
    (f"{BASE_URL}/artikel/feinwerkmechanikerhandwerk-44,1016,4284.html",                  "Feinwerkmechaniker"),
    (f"{BASE_URL}/artikel/fliesen-platten-und-mosaiklegerhandwerk-44,1017,4285.html",     "Fliesen-, Platten- und Mosaikleger"),
    (f"{BASE_URL}/artikel/friseurhandwerk-44,1018,4287.html",                             "Friseur"),
    (f"{BASE_URL}/artikel/kosmetikerhandwerk-44,1019,4288.html",                          "Kosmetiker"),
    (f"{BASE_URL}/artikel/kraftfahrzeugtechnikerhandwerk-44,1020,4289.html",              "Kfz.-Techniker"),
    (f"{BASE_URL}/artikel/maler-und-lackierer-handwerk-44,1021,4290.html",                "Maler und Lackierer"),
    (f"{BASE_URL}/artikel/maurer-und-betonbauer-handwerk-44,1030,4295.html",              "Maurer und Betonbauer"),
    (f"{BASE_URL}/artikel/metallbauerhandwerk-44,1022,4291.html",                         "Metallbauer"),
    (f"{BASE_URL}/artikel/tischlerhandwerk-44,1023,4292.html",                            "Tischler"),
    (f"{BASE_URL}/artikel/meistervorbereitungskurse-teil-iii-iv-44,1024,4286.html",       None),
    (f"{BASE_URL}/artikel/rollladen-und-sonnenschutztechnikerhandwerk-44,1025,4293.html", "Rollladen- und Sonnenschutztechniker"),
    (f"{BASE_URL}/artikel/sanitaer-heizung-klimatechnik-shk-44,1026,4272.html",           "Installateur- und Heizungsbauer"),
]

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

PARTS_RE   = re.compile(r"Teile?\s+(?P<parts>(?:IV|III|II|I)(?:\s*\+\s*(?:IV|III|II|I))*)", re.IGNORECASE)
AEVO_RE    = re.compile(r"Ausbildereignungspr[üu]fung", re.IGNORECASE)
DATE_RANGE_FORMAT_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4}):\s*(Vollzeit|Teilzeit)", re.IGNORECASE,
)
PRICE_RE    = re.compile(r"([\d.]+),(\d{2})\s*€")
DURATION_RE = re.compile(r"(\d+)\s*Std\.", re.IGNORECASE)

FORMAT_MAP = {"vollzeit": "full_time", "teilzeit": "part_time"}

# Only two locations are used by this chamber's Meisterkurse.
LOCATIONS = {
    "wetzlar":   {"city": "Wetzlar",   "zip_code": "35576", "street": "Dillufer 40"},
    "wiesbaden": {"city": "Wiesbaden", "zip_code": "65189", "street": "Brunhildenstraße 110"},
}
DEFAULT_LOCATION = LOCATIONS["wiesbaden"]


def parse_parts(title: str) -> list[int] | None:
    if AEVO_RE.search(title):
        return [4]
    m = PARTS_RE.search(title)
    if not m:
        return None
    tokens = re.split(r"\s*\+\s*", m.group("parts").strip().upper())
    parts = sorted({ROMAN[t] for t in tokens if t in ROMAN})
    return parts or None


def parse_format_and_mode(title: str) -> tuple[str, str]:
    lower = title.lower()
    format_key = "part_time"
    for kw, val in FORMAT_MAP.items():
        if kw in lower:
            format_key = val
            break
    teaching_mode = "hybrid" if ("virtuelles klassenzimmer" in lower or "online" in lower) else "presence"
    return format_key, teaching_mode


def parse_location(text: str) -> dict:
    # Card text contains exactly one of these two place names.
    last_match = None
    for m in re.finditer(r"\b(Wetzlar|Wiesbaden)\b", text):
        last_match = m
    if last_match:
        return LOCATIONS[last_match.group(1).lower()]
    return DEFAULT_LOCATION


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "wenige" in lower or "freie" in lower:
        return "available"
    return "unknown"


def add_query_params(url: str, extra: dict) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in extra.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class HwkWiesbadenScraper(BaseScraper):
    chamber_slug    = "hwk-wiesbaden"
    chamber_name    = "Handwerkskammer Wiesbaden"
    chamber_region  = "Hessen"
    chamber_website = BASE_URL
    source_url      = OVERVIEW_URL
    request_delay   = 1.2

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for article_url, trade_name in TRADE_PAGES:
            article = self.parse_html(article_url)
            if article is None:
                logger.warning("Could not fetch trade article: %s", article_url)
                continue

            list_url = self._find_courselist_url(article)
            if list_url is None:
                logger.warning("No 'weitere Kurse' link on %s — skipping.", article_url)
                continue

            trade_offers = self._scrape_courselist(list_url, trade_name)
            logger.info("  %s → %d offer(s)", trade_name or "Teil III/IV (generic)", len(trade_offers))
            offers.extend(trade_offers)

        logger.info("HWK Wiesbaden: parsed %d course offers total.", len(offers))
        return offers

    # ------------------------------------------------------------------
    # Article page → "weitere Kurse" search URL
    # ------------------------------------------------------------------

    def _find_courselist_url(self, article: BeautifulSoup) -> str | None:
        link = article.find("a", string=re.compile(r"weitere\s+Kurse", re.IGNORECASE))
        if link is None:
            link = article.find("a", href=re.compile(r"courselist\.html"))
        if link is None or not link.get("href"):
            return None
        href = link["href"]
        return href if href.startswith("http") else BASE_URL + href

    # ------------------------------------------------------------------
    # Paginated course-list search
    # ------------------------------------------------------------------

    def _scrape_courselist(self, list_url: str, trade_name: str | None) -> list[RawCourseOffer]:
        first = self.parse_html(list_url)
        if first is None:
            logger.warning("Could not fetch course list: %s", list_url)
            return []

        total = self._parse_total(first)
        offers = self._parse_list_page(first, trade_name)

        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            soup = self.parse_html(add_query_params(list_url, {"limit": PAGE_SIZE, "offset": offset}))
            if soup is None:
                logger.warning("Failed at offset=%d for %s, stopping.", offset, list_url)
                break
            offers.extend(self._parse_list_page(soup, trade_name))

        return offers

    def _parse_total(self, soup: BeautifulSoup) -> int:
        m = re.search(r"von\s+(\d+);\s*Seite", soup.get_text())
        return int(m.group(1)) if m else len(soup.select("a[href*='coursedetail']"))

    def _parse_list_page(self, soup: BeautifulSoup, trade_name: str | None) -> list[RawCourseOffer]:
        offers = []
        for link in soup.select("a[href*='coursedetail']"):
            try:
                offer = self._parse_card(link, trade_name)
                if offer:
                    offers.append(offer)
            except Exception as exc:
                logger.warning("Error parsing card '%s': %s", link.get_text(strip=True)[:60], exc)
        return offers

    # ------------------------------------------------------------------
    # One card
    # ------------------------------------------------------------------

    def _card_container(self, link: Tag) -> Tag | None:
        """
        Walk up from the coursedetail link until we find the smallest
        ancestor whose text contains both a price and a date — i.e. the
        full card — without assuming a specific wrapper class name.
        """
        node = link
        for _ in range(6):
            node = node.parent
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if "€" in text and re.search(r"\d{2}\.\d{2}\.\d{4}", text):
                return node
        return None

    def _parse_card(self, link: Tag, trade_name: str | None) -> RawCourseOffer | None:
        title = link.get_text(strip=True)
        parts = parse_parts(title)
        if not parts:
            logger.debug("Could not parse parts from title %r", title)
            return None

        detail_url = link.get("href", "")
        if detail_url and not detail_url.startswith("http"):
            detail_url = BASE_URL + detail_url

        container = self._card_container(link)
        card_text = container.get_text(" ", strip=True) if container else title

        format_key, teaching_mode = parse_format_and_mode(title)

        dm = DATE_RANGE_FORMAT_RE.search(card_text)
        start_date = f"{dm.group(1)[6:10]}-{dm.group(1)[3:5]}-{dm.group(1)[0:2]}" if dm else None
        end_date   = f"{dm.group(2)[6:10]}-{dm.group(2)[3:5]}-{dm.group(2)[0:2]}" if dm else None

        price_m = PRICE_RE.search(card_text)
        course_fee = float(price_m.group(1).replace(".", "") + "." + price_m.group(2)) if price_m else None

        dur_m = DURATION_RE.search(card_text)
        duration_hours = int(dur_m.group(1)) if dur_m else None

        loc = parse_location(card_text)
        availability = parse_availability(card_text)

        resolved_trade = trade_name
        if resolved_trade and set(parts) <= {3, 4}:
            resolved_trade = None  # generic page occasionally mixes in trade-independent parts

        return RawCourseOffer(
            title=build_course_title(resolved_trade, parts),
            trade_name=resolved_trade,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration_hours,
            course_fee=course_fee,
            city=loc["city"],
            street=loc["street"],
            zip_code=loc["zip_code"],
            exam_fee_scraped=None,  # not listed; enter manually
            availability=availability,
            source_url=detail_url,
            scraped_raw={"title": title, "card_text": card_text[:400]},
        )
