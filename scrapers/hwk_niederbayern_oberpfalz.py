"""Courses from the Handwerkskammer Niederbayern-Oberpfalz."""

import re
from collections import Counter

from bs4 import Tag

from .base import RawCourseOffer, build_course_title
from .hwk_bayern import DURATION_RE, BavariaCatalogue, BavariaOdavScraper

# Issue #54: list Elektrotechniker/Feinwerkmechaniker without Fachrichtung suffix.
_BASE_TRADE_RE = {
    "Elektrotechniker": re.compile(r"^Elektrotechniker\b", re.IGNORECASE),
    "Feinwerkmechaniker": re.compile(r"^Feinwerkmechaniker\b", re.IGNORECASE),
}


LOCATIONS = {
    "cham": ("Frühlingstraße 13", "93413", "Cham"),
    "deggendorf": ("Graflinger Straße 105", "94469", "Deggendorf"),
    "landshut": ("Am Lurzenhof 10 b", "84036", "Landshut"),
    "landshut-schönbrunn": ("Am Lurzenhof 10 b", "84036", "Landshut"),
    "neumarkt i. d. opf.": ("Kerschensteinerstraße 5", "92318", "Neumarkt i.d.OPf."),
    "neumarkt i.d.opf.": ("Kerschensteinerstraße 5", "92318", "Neumarkt i.d.OPf."),
    "passau": ("Simmerlingweg 4 und 15", "94036", "Passau"),
    "pfarrkirchen": ("Christangerstraße 12", "84347", "Pfarrkirchen"),
    "regensburg": ("Ditthornstraße 10", "93055", "Regensburg"),
    "schwandorf": ("Charlottenhof 1", "92421", "Schwandorf"),
    "straubing": ("Johannes-Kepler-Straße 14", "94315", "Straubing"),
    "vilshofen an der donau": ("Kapuziner Straße 66 a", "94474", "Vilshofen an der Donau"),
    "waldkirchen": ("Freyunger Straße 8", "94065", "Waldkirchen"),
    "weiden": ("Bernhard-Suttner-Straße 5", "92637", "Weiden"),
    "weiden i.d.opf.": ("Bernhard-Suttner-Straße 5", "92637", "Weiden"),
    "wiesau": ("Pestalozzistraße 2", "95676", "Wiesau"),
    "zwiesel": ("Fachschulstraße 15", "94227", "Zwiesel"),
}


class HwkNiederbayernOberpfalzScraper(BavariaOdavScraper):
    chamber_slug = "hwk-niederbayern-oberpfalz"
    chamber_name = "Handwerkskammer Niederbayern-Oberpfalz"
    chamber_website = "https://www.hwkno.de"
    source_url = (
        "https://www.hwkno.de/76,0,courselist.html"
        "?search-filter-template=0&search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwkno.de",
        list_url=source_url + "&limit={limit}&offset={offset}",
        default_city="Regensburg",
        default_street="Ditthornstraße 10",
        default_zip="93055",
        details_required=False,
    )

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        card = super()._parse_card(link, detail_url)
        if card is None:
            return None
        row = link.find_parent("div", class_="row")
        lines = [
            line.strip()
            for line in (row.get_text("\n", strip=True) if row else "").splitlines()
            if line.strip()
        ]
        for index, line in enumerate(lines):
            if DURATION_RE.fullmatch(line) and index + 1 < len(lines):
                card["listing_city"] = lines[index + 1]
                break
        return card

    def listing_location(self, card: dict, teaching_mode: str) -> tuple[str, str, str]:
        raw_city = card.get("listing_city", "").strip()
        if teaching_mode == "online" or raw_city.lower().startswith("online"):
            return "", "", "Online"
        location = LOCATIONS.get(raw_city.lower())
        if location:
            return location
        if raw_city:
            return "", "", raw_city
        return super().listing_location(card, teaching_mode)

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers = super().fetch_raw_courses()
        return self._disambiguate_parallel_runs(offers)

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        if offer.trade_name:
            for base, pattern in _BASE_TRADE_RE.items():
                if pattern.match(offer.trade_name):
                    offer.trade_name = base
                    offer.title = build_course_title(base, offer.parts)
                    break
        return offer

    @staticmethod
    def _disambiguate_parallel_runs(offers: list[RawCourseOffer]) -> list[RawCourseOffer]:
        """Parallel runs share a title/date/fee but take place in different cities."""
        counts = Counter((offer.title, offer.start_date, offer.course_fee) for offer in offers)
        disambiguated: list[RawCourseOffer] = []
        for offer in offers:
            if counts[(offer.title, offer.start_date, offer.course_fee)] > 1 and offer.city:
                offer.title = f"{offer.title} — {offer.city}"
            disambiguated.append(offer)
        return disambiguated
