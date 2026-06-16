"""YÖK Atlas domain modülü.

Bu paket mevcut UniChat scraper/import hattını bozmadan GİBTÜ YÖK Atlas
işlerini ayrı discovery, extraction, normalization, validation, versioning,
reporting ve storage katmanlarına ayırır.
"""

from __future__ import annotations

from yokatlas.contracts import (
    CITY,
    EXPECTED_API_UNIVERSITY_ID,
    PUBLIC_UNIVERSITY_CODE,
    SOURCE_SYSTEM,
    UNIVERSITY_NAME,
    UNIVERSITY_TYPE,
)

__all__ = [
    "CITY",
    "EXPECTED_API_UNIVERSITY_ID",
    "PUBLIC_UNIVERSITY_CODE",
    "SOURCE_SYSTEM",
    "UNIVERSITY_NAME",
    "UNIVERSITY_TYPE",
]
