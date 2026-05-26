"""
scraper/management/commands/geocode_offers.py

Geocodes CourseOffer records that have a city but no coordinates,
using the free Nominatim API (OpenStreetMap). No API key required.

Usage:
    python manage.py geocode_offers
    python manage.py geocode_offers --force   # re-geocode all, even existing coords
"""

import time
import requests
from django.core.management.base import BaseCommand
from courses.models import CourseOffer


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "MeistervergleichBot/1.0 (+https://meistervergleich.de)"}
DELAY = 1.1  # Nominatim rate limit: max 1 request/second


class Command(BaseCommand):
    help = "Geocode CourseOffer records using city name via Nominatim (OpenStreetMap)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Re-geocode offers that already have coordinates.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        qs = CourseOffer.objects.filter(city__gt="")
        if not force:
            qs = qs.filter(latitude__isnull=True)

        total = qs.count()
        self.stdout.write(f"Geocoding {total} offer(s)...\n")

        # Cache city → (lat, lng) to avoid duplicate API calls
        cache: dict[str, tuple | None] = {}
        success = skipped = failed = 0

        for offer in qs.iterator():
            city_key = f"{offer.city}, Rheinland-Pfalz, Deutschland"

            if city_key not in cache:
                coords = self._geocode(city_key)
                cache[city_key] = coords
                time.sleep(DELAY)
            else:
                coords = cache[city_key]

            if coords:
                offer.latitude, offer.longitude = coords
                offer.save(update_fields=["latitude", "longitude"])
                success += 1
                self.stdout.write(f"  ✔ {offer.city} → {coords[0]:.4f}, {coords[1]:.4f}")
            else:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(f"  ✘ Could not geocode: {offer.city}")
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Success: {success} | Failed: {failed} | Skipped: {skipped}"
        ))

    def _geocode(self, query: str) -> tuple[float, float] | None:
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers=HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Nominatim error for {query!r}: {exc}"))
        return None