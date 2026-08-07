import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from scrapers.geocode import Geocoder


def _photon_response(features):
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"features": features}

    return _R()


_HIT = [{"geometry": {"coordinates": [13.7373, 51.0504]}}]


class GeocoderCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "cache" / "geocode_cache.json"

    def _geocoder(self):
        # DELAY is a politeness sleep between live lookups; irrelevant here.
        patcher = patch("scrapers.geocode.DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        return Geocoder(self.cache_path)

    def test_successful_lookup_is_cached(self):
        g = self._geocoder()
        with patch("scrapers.geocode.requests.get", return_value=_photon_response(_HIT)) as get:
            self.assertEqual(g.lookup("Am Lagerplatz 8, 01099 Dresden"), (51.0504, 13.7373))
            self.assertEqual(g.lookup("Am Lagerplatz 8, 01099 Dresden"), (51.0504, 13.7373))
        self.assertEqual(get.call_count, 1, "second lookup must be served from cache")

    def test_authoritative_miss_is_cached(self):
        """Photon answering with zero features is a real answer — cache it so we
        stop re-asking for addresses that genuinely do not exist."""
        g = self._geocoder()
        with patch("scrapers.geocode.requests.get", return_value=_photon_response([])) as get:
            self.assertIsNone(g.lookup("00000 keine Angabe, Brandenburg, Deutschland"))
            self.assertIsNone(g.lookup("00000 keine Angabe, Brandenburg, Deutschland"))
        self.assertEqual(get.call_count, 1)
        self.assertIsNone(g.cache["00000 keine Angabe, Brandenburg, Deutschland"])

    def test_transient_failure_is_not_cached_and_retries(self):
        """A network error must not pin the address to "no coordinates" forever."""
        g = self._geocoder()
        with patch("scrapers.geocode.requests.get", side_effect=requests.Timeout("boom")):
            self.assertIsNone(g.lookup("Preuschwitzer Straße 20, 02625 Bautzen"))
        self.assertNotIn("Preuschwitzer Straße 20, 02625 Bautzen", g.cache)
        self.assertEqual(g.failures, 1)

        with patch("scrapers.geocode.requests.get", return_value=_photon_response(_HIT)):
            self.assertEqual(g.lookup("Preuschwitzer Straße 20, 02625 Bautzen"), (51.0504, 13.7373))

    def test_failed_lookup_alone_does_not_dirty_the_cache(self):
        g = self._geocoder()
        with patch("scrapers.geocode.requests.get", side_effect=requests.ConnectionError("down")):
            g.lookup("Musterweg 1, 12345 Musterstadt")
        g.save()
        self.assertFalse(self.cache_path.exists(), "nothing definitive was learned")

    def test_unusable_geometry_counts_as_answered(self):
        g = self._geocoder()
        malformed = [{"geometry": {"coordinates": []}}]
        with patch("scrapers.geocode.requests.get", return_value=_photon_response(malformed)):
            self.assertIsNone(g.lookup("Irgendwo 1, 00000 Nirgendwo"))
        self.assertIn("Irgendwo 1, 00000 Nirgendwo", g.cache)
        self.assertEqual(g.failures, 0)

    def test_unreadable_cache_is_discarded_rather_than_fatal(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text('{"truncated": ', encoding="utf-8")
        g = self._geocoder()
        self.assertEqual(g.cache, {})

    def test_save_replaces_cache_atomically(self):
        g = self._geocoder()
        with patch("scrapers.geocode.requests.get", return_value=_photon_response(_HIT)):
            g.lookup("Am Lagerplatz 8, 01099 Dresden")
        g.save()
        self.assertEqual(
            json.loads(self.cache_path.read_text(encoding="utf-8")),
            {"Am Lagerplatz 8, 01099 Dresden": [51.0504, 13.7373]},
        )
        self.assertEqual(list(self.cache_path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
