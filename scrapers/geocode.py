"""
scrapers/geocode.py

Geocodes course locations via Photon (Komoot, OSM-based — more reliable for
German addresses than Nominatim and needs no API key). Backed by a committed
cache so CI only hits the network for new addresses.

Photon returns GeoJSON; coordinates are ``features[0].geometry.coordinates``
in ``[lon, lat]`` order (the reverse of lat/lng).
"""

import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PHOTON_URL = "https://photon.komoot.io/api/"
HEADERS = {"User-Agent": "MeisterKompassBot/1.0 (+https://meisterkompass.de)"}
DELAY = 1.0   # polite delay between live lookups


def build_query(street: str, zip_code: str, city: str, region: str) -> str:
    """
    Full address (street + ZIP + city) when available gives pin-level accuracy;
    falls back to city + region for city-centre coordinates.
    """
    street = (street or "").strip()
    zip_code = (zip_code or "").strip()
    city = (city or "").strip()
    region = region or "Deutschland"

    if street and zip_code:
        return f"{street}, {zip_code} {city}, Deutschland"
    if street:
        return f"{street}, {city}, Deutschland"
    if zip_code:
        return f"{zip_code} {city}, Deutschland"
    return f"{city}, {region}, Deutschland"


class Geocoder:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.cache: dict[str, list | None] = {}
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self._dirty = False
        self.hits = 0
        self.misses = 0

    def lookup(self, query: str) -> tuple[float, float] | None:
        """Return (lat, lng) for an address query, using the cache first."""
        if query in self.cache:
            self.hits += 1
            coords = self.cache[query]
            return (coords[0], coords[1]) if coords else None

        self.misses += 1
        coords = self._geocode(query)
        time.sleep(DELAY)
        self.cache[query] = list(coords) if coords else None
        self._dirty = True
        return coords

    def _geocode(self, query: str) -> tuple[float, float] | None:
        try:
            r = requests.get(
                PHOTON_URL,
                params={"q": query, "limit": 1, "lang": "de"},
                headers=HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            features = r.json().get("features", [])
            if features:
                lon, lat = features[0]["geometry"]["coordinates"]
                return float(lat), float(lon)
        except Exception as exc:  # noqa: BLE001 — network/parse errors are non-fatal
            logger.warning("Photon error for %r: %s", query, exc)
        return None

    def save(self):
        if self._dirty:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "Geocode cache saved (%d entries, %d hits, %d misses).",
                len(self.cache), self.hits, self.misses,
            )
