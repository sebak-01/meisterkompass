"""
Shared ODAV catalogue scraper engine.

Historically named ``BavariaOdavScraper`` because the first adopters were the
six Bavarian chambers. The same CMS powers catalogues in Brandenburg, MV,
Niedersachsen, NRW, Sachsen, Sachsen-Anhalt and Thüringen — use these aliases
for new code.
"""

from .hwk_bayern import BavariaCatalogue as OdavCatalogue
from .hwk_bayern import BavariaOdavScraper as OdavCatalogueScraper

# Back-compat re-exports under the legacy names.
BavariaCatalogue = OdavCatalogue
BavariaOdavScraper = OdavCatalogueScraper

__all__ = [
    "OdavCatalogue",
    "OdavCatalogueScraper",
    "BavariaCatalogue",
    "BavariaOdavScraper",
]
