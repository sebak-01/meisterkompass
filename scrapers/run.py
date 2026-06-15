"""
scrapers/run.py

CLI entry point. Replaces the old ``python manage.py run_scrapers``.

Usage:
    python -m scrapers.run                       # all chambers → write data/*.json
    python -m scrapers.run --chamber hwk-pfalz   # one chamber only
    python -m scrapers.run --dry-run             # scrape + log counts, write nothing
"""

import argparse
import logging
import sys

from .pipeline import SCRAPERS, rebake, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MeisterKompass scrapers → JSON.")
    parser.add_argument("--chamber", choices=list(SCRAPERS), help="Run only one chamber's scraper.")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and log counts but write nothing.")
    parser.add_argument(
        "--rebake", action="store_true",
        help="Re-resolve exam fees from existing data/courses.json (no scraping). "
             "Use after editing data/manual/exam_fees_manual.json.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.rebake:
        n = rebake()
        print(f"Rebaked {n} courses.")
        return 0

    report = run(chamber=args.chamber, dry_run=args.dry_run)
    print("\nScrape summary:")
    for slug, count in report.per_chamber.items():
        print(f"  {slug}: {count} offers")
    print(f"  total courses written: {report.total_courses}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
