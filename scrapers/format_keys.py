"""Shared Vollzeit/Teilzeit detection from course-page prose."""

import re

PART_TIME_WORDS = (
    "teilzeit",
    "berufsbegleitend",
    "abendkurs",
    "abendkurse",
    "abendschule",
    "wochenend",
)
FULL_TIME_WORDS = (
    "vollzeit",
    "tageskurs",
)

ALLE_TERMINE_RE = re.compile(r"\nAlle Termine\b", re.IGNORECASE)


def strip_odav_alternate_runs(text: str) -> str:
    """Drop ODAV detail-page sections listing other course runs."""
    match = ALLE_TERMINE_RE.search(text)
    return text[: match.start()] if match else text


def parse_format_key(text: str, *, default: str = "part_time") -> str:
    """
    Derive ``full_time`` vs ``part_time`` from page/run text.

    Part-time keywords win when both appear (e.g. Ostbrandenburg runs labelled
    ``Berufsbegleitend`` that mention short ``Vollzeit`` blocks in parentheses).
    """
    lower = text.lower()
    if any(word in lower for word in PART_TIME_WORDS):
        return "part_time"
    if any(word in lower for word in FULL_TIME_WORDS):
        return "full_time"
    return default
