"""
Shared helpers for Baden-Württemberg HWK seminar CMS scrapers
(Heilbronn, Reutlingen and similar ``/seminar/<slug>/`` pages).
"""

from __future__ import annotations

import re

from bs4 import Tag

DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})$"
)


def parse_bw_availability(text: str) -> str:
    lower = text.lower()
    if any(
        value in lower
        for value in (
            "keine plätze mehr frei",
            "bereits ausgebucht",
            "buchung ist nicht mehr möglich",
        )
    ):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if (
        "freie plätze" in lower
        or "freier platz" in lower
        or "in den warenkorb" in lower
    ):
        return "available"
    return "unknown"


def iso_date_from_match(match: re.Match, day_g: int, month_g: int, year_g: int) -> str:
    return f"{match.group(year_g)}-{match.group(month_g)}-{match.group(day_g)}"


def nearest_run_container(heading: Tag, *, max_depth: int = 6) -> Tag | None:
    """Walk up from an h4 date heading to the block that contains the run details."""
    node: Tag | None = heading
    for _ in range(max_depth):
        if node is None:
            return None
        parent = node.parent
        if parent is None:
            return None
        text = parent.get_text(" ", strip=True)
        if any(token in text for token in ("Kursnummer", "Gebühr", "Kosten", "Seminardauer")):
            return parent
        node = parent if isinstance(parent, Tag) else None
    return heading.parent if isinstance(heading.parent, Tag) else None
