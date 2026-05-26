"""
scraper/management/commands/run_scrapers.py

Usage:
    python manage.py run_scrapers
    python manage.py run_scrapers --chamber hwk-koblenz
    python manage.py run_scrapers --chamber hwk-trier --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from scraper.hwk_koblenz import HwkKoblenzScraper
from scraper.hwk_trier   import HwkTrierScraper

SCRAPERS = {
    "hwk-koblenz":     HwkKoblenzScraper,
    "hwk-trier":       HwkTrierScraper,
    # "hwk-pfalz":      HwkPfalzScraper,
    # "hwk-rheinhessen": HwkRheinhessenScraper,
}


class Command(BaseCommand):
    help = "Run course scrapers for one or all Handwerkskammern."

    def add_arguments(self, parser):
        parser.add_argument("--chamber", default=None,
                            help=f"Chamber slug. Available: {', '.join(SCRAPERS)}")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and print without writing to DB.")

    def handle(self, *args, **options):
        slug    = options["chamber"]
        dry_run = options["dry_run"]

        if slug:
            if slug not in SCRAPERS:
                raise CommandError(f"Unknown slug '{slug}'. Available: {', '.join(SCRAPERS)}")
            targets = {slug: SCRAPERS[slug]}
        else:
            targets = SCRAPERS

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{'DRY RUN — ' if dry_run else ''}Running {len(targets)} scraper(s)...\n"
        ))

        for slug, cls in targets.items():
            self.stdout.write(f"→ {slug}")
            scraper = cls()
            if dry_run:
                self._dry_run(scraper)
            else:
                run = scraper.run()
                style = self.style.SUCCESS if run.status == "success" else self.style.WARNING
                self.stdout.write(style(
                    f"  {run.get_status_display()} | "
                    f"offers +{run.offers_created} ~{run.offers_updated} | "
                    f"exam fees updated: {run.exam_fees_updated}"
                ))
                if run.error_log:
                    self.stdout.write(self.style.ERROR(f"  Errors:\n{run.error_log}"))

        self.stdout.write(self.style.SUCCESS("\nDone."))

    def _dry_run(self, scraper):
        self.stdout.write("  Fetching courses (dry run — no DB writes)...")
        raw_offers = scraper.fetch_raw_courses()
        self.stdout.write(f"  Found {len(raw_offers)} course offer(s):\n")

        roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
        chamber = scraper.chamber_name or scraper.chamber_slug
        for o in raw_offers:
            trade    = o.trade_name or "[Generic III+IV]"
            parts    = "+".join(roman[p] for p in o.parts)
            fee      = f"{o.course_fee:.2f} €"     if o.course_fee      else "no price"
            exam_fee = f"{o.exam_fee_scraped:.2f} €" if o.exam_fee_scraped else "no exam fee"
            dur      = f"{o.duration_hours} Std."  if o.duration_hours   else "no duration"
            city     = o.city or "no city"
            dates    = f"{o.start_date} → {o.end_date}"

            self.stdout.write(
                f"    [{chamber}] {trade:<45} Parts {parts:<8} "
                f"{o.format_key:<12} {dates}  "
                f"{fee:<14} Prüfung: {exam_fee:<14} {dur:<12} {city} [{o.availability}]"
            )

        self.stdout.write(f"\n  Fetching exam fees (dry run)...")
        fees = scraper.fetch_raw_exam_fees()
        self.stdout.write(f"  Found {len(fees)} exam fee(s) via fetch_raw_exam_fees().\n")