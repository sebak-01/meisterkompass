"""
Shared helpers for Baden-Württemberg HWK seminar CMS scrapers
(Heilbronn, Reutlingen and similar ``/seminar/<slug>/`` pages).

``ancestor_matching`` is CMS-agnostic and is also used by chambers outside
Baden-Württemberg (Halle, Südthüringen, Ulm) that bury run details the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable

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


def ancestor_matching(
    start: Tag,
    predicate: Callable[[str], bool],
    *,
    max_depth: int,
) -> Tag | None:
    """
    Walk up from ``start`` and return the first ancestor whose text satisfies
    ``predicate``, or None within ``max_depth`` levels.

    Chamber CMSes bury a course run's details in an ancestor of its date
    heading, but neither the nesting depth nor the marker tokens agree between
    chambers — hence both are supplied by the caller.
    """
    node: Tag | None = start
    for _ in range(max_depth):
        node = node.parent if node is not None else None
        if not isinstance(node, Tag):
            return None
        if predicate(node.get_text(" ", strip=True)):
            return node
    return None


def nearest_run_container(heading: Tag, *, max_depth: int = 6) -> Tag | None:
    """Walk up from an h4 date heading to the block that contains the run details."""
    container = ancestor_matching(
        heading,
        lambda text: any(
            token in text for token in ("Kursnummer", "Gebühr", "Kosten", "Seminardauer")
        ),
        max_depth=max_depth,
    )
    if container is not None:
        return container
    return heading.parent if isinstance(heading.parent, Tag) else None
