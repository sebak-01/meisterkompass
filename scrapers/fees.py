"""
scrapers/fees.py

Pure (Django-free) port of ``CourseOffer.resolved_exam_fee_info``.

Builds the per-part exam-fee lookup from scraped rows overlaid with the
hand-curated ``data/manual/exam_fees_manual.json`` (manual always wins, which
subsumes the old ``scraper_may_overwrite`` / ``manually_verified`` flags), then
resolves a single display object per course offer.
"""

from decimal import Decimal

# lookup key: (chamber_slug, trade_slug_or_None, part) -> fee dict
#   fee dict: {"fee": float, "fee_max": float|None, "qualifier": str}
ExamFeeLookup = dict[tuple[str, str | None, int], dict]


def _fmt(amount: Decimal) -> str:
    """German number without decimals, e.g. '1.130 €'."""
    return f"{amount:,.0f}".replace(",", ".") + " €"


def build_exam_fee_lookup(scraped_rows: list[dict], manual_rows: list[dict]) -> ExamFeeLookup:
    """
    Merge scraped per-part exam fees with manual entries. Manual wins on
    collision. Each row carries chamber_slug, part, fee and optionally
    trade_slug (None/"" => all-trades), fee_max, qualifier.
    """
    lookup: ExamFeeLookup = {}

    def add(row: dict):
        trade = row.get("trade_slug") or None
        key = (row["chamber_slug"], trade, int(row["part"]))
        lookup[key] = {
            "fee":       float(row["fee"]),
            "fee_max":   float(row["fee_max"]) if row.get("fee_max") else None,
            "qualifier": row.get("qualifier") or "",
        }

    for row in scraped_rows:
        add(row)
    for row in manual_rows:   # manual overlay wins
        add(row)
    return lookup


def resolve_exam_fee(
    chamber_slug: str,
    trade_slug: str | None,
    included_parts: list[int],
    exam_fee_scraped: float | None,
    lookup: ExamFeeLookup,
) -> dict:
    """
    Returns the best exam-fee display info for a course offer.

    Priority:
      1. ``exam_fee_scraped`` stated on the course page (Trier/Pfalz/Saarland)
      2. ExamFee lookup — summed across the offer's parts; trade-specific first,
         then all-trades (trade=None) fallback.

    Mirrors the original ``CourseOffer.resolved_exam_fee_info`` output exactly:
        {fee, fee_max, qualifier, display}
    """
    # Priority 1: scraped fee on the page
    if exam_fee_scraped is not None:
        fee = Decimal(str(exam_fee_scraped))
        return {"fee": float(fee), "fee_max": None, "qualifier": "", "display": _fmt(fee)}

    # Priority 2: per-part ExamFee lookup
    total_min = Decimal("0")
    total_max = Decimal("0")
    qualifier = ""
    found = False
    has_range = False

    for part in included_parts:
        ef = lookup.get((chamber_slug, trade_slug, part)) or lookup.get((chamber_slug, None, part))
        if not ef:
            continue
        fee = Decimal(str(ef["fee"]))
        fee_max = Decimal(str(ef["fee_max"])) if ef["fee_max"] is not None else None
        total_min += fee
        total_max += fee_max if fee_max is not None else fee
        if fee_max is not None:
            has_range = True
        if ef["qualifier"] and not qualifier:
            qualifier = ef["qualifier"]
        found = True

    if not found:
        return {"fee": None, "fee_max": None, "qualifier": "", "display": ""}

    if has_range:
        display = f"{_fmt(total_min)} bis {_fmt(total_max)}"
        return {"fee": float(total_min), "fee_max": float(total_max), "qualifier": "", "display": display}

    fee_str = _fmt(total_min)
    display = f"{qualifier} {fee_str}".strip() if qualifier else fee_str
    return {"fee": float(total_min), "fee_max": None, "qualifier": qualifier, "display": display}
