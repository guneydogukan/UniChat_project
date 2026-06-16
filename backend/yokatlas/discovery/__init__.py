"""YÖK Atlas keşif katmanı.

Mevcut scraper içindeki keşif sınıfları geriye uyumluluk için burada yeniden
dışa açılır. Yeni discovery servisleri bu paketin altında büyütülmelidir.
"""

from __future__ import annotations

from scrapers.yokatlas_gibtu_scraper import (
    ProgramAllowlistEntry,
    ProgramAllowlistValidator,
    ProgramCatalogCrawler,
    UniversityResolver,
    select_allowlist,
)
from yokatlas.contracts import (
    EXPECTED_API_UNIVERSITY_ID,
    LIST_URLS,
    PROGRAM_ALLOWLIST,
    PUBLIC_UNIVERSITY_CODE,
)

__all__ = [
    "EXPECTED_API_UNIVERSITY_ID",
    "LIST_URLS",
    "PROGRAM_ALLOWLIST",
    "PUBLIC_UNIVERSITY_CODE",
    "ProgramAllowlistEntry",
    "ProgramAllowlistValidator",
    "ProgramCatalogCrawler",
    "UniversityResolver",
    "select_allowlist",
]
