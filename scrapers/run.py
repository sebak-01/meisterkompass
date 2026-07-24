"""
scrapers/run.py

CLI entry point. Replaces the old ``python manage.py run_scrapers``.

Usage:
    python -m scrapers.run                       # daily course scrape → data/*.json
    python -m scrapers.run --mode fees           # weekly Gebührenverzeichnis scrape
    python -m scrapers.run --chamber hwk-pfalz   # one chamber only
    python -m scrapers.run --group west          # CI matrix batch (scrape + write subset)
    python -m scrapers.run --group west --partial-out partial-west.json
    python -m scrapers.run --merge-partials partials/*.json
    python -m scrapers.run --dry-run             # scrape + log counts, write nothing
"""

import argparse
import logging
import sys
from glob import glob
from pathlib import Path

from .pipeline import SCRAPE_GROUPS, SCRAPERS, merge_scrape_partials, rebake, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MeisterKompass scrapers → JSON.")
    parser.add_argument("--chamber", choices=list(SCRAPERS), help="Run only one chamber's scraper.")
    parser.add_argument(
        "--group",
        choices=list(SCRAPE_GROUPS),
        help="Run a predefined regional batch (used by CI matrix jobs).",
    )
    parser.add_argument(
        "--mode",
        choices=("courses", "fees", "all"),
        default="courses",
        help="courses=daily offers (default); fees=weekly Gebührenverzeichnis; "
             "all=both in one pass (local/debug).",
    )
    parser.add_argument(
        "--partial-out",
        type=Path,
        help="Write scraped chamber data to a JSON partial (skip merge/geocode/write).",
    )
    parser.add_argument(
        "--merge-partials",
        nargs="+",
        help="Merge scrape partial JSON files and write data/*.json once.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Scrape and log counts but write nothing.")
    parser.add_argument(
        "--rebake", action="store_true",
        help="Re-resolve exam fees from existing data/courses.json (no course scraping). "
             "Uses data/scraped_exam_fees.json + manual overlay by default.",
    )
    parser.add_argument(
        "--refresh-tariffs",
        action="store_true",
        help="With --rebake: re-fetch Gebührenverzeichnis PDFs before resolving.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.rebake:
        n = rebake(refresh_tariffs=args.refresh_tariffs)
        print(f"Rebaked {n} courses.")
        return 0

    if args.merge_partials:
        if args.mode == "fees":
            raise SystemExit("--merge-partials is only for course scrape partials.")
        paths: list[Path] = []
        for pattern in args.merge_partials:
            matches = [Path(p) for p in glob(pattern)]
            if not matches:
                raise SystemExit(f"No partial files matched: {pattern!r}")
            paths.extend(matches)
        report = merge_scrape_partials(sorted(paths), dry_run=args.dry_run)
    else:
        if args.chamber and args.group:
            raise SystemExit("Use only one of --chamber or --group.")
        if args.partial_out is not None and args.mode == "fees":
            raise SystemExit("--partial-out is not supported with --mode fees.")
        report = run(
            chamber=args.chamber,
            group=args.group,
            dry_run=args.dry_run,
            partial_out=args.partial_out,
            mode=args.mode,
        )

    print("\nScrape summary:")
    for slug, count in report.per_chamber.items():
        label = "offers" if args.mode != "fees" else "fee rows"
        print(f"  {slug}: {count} {label}")
    print(f"  total courses written: {report.total_courses}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
