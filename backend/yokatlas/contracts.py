"""GİBTÜ YÖK Atlas domain sözleşmeleri.

Bu dosya kod içinde tekrar eden kimlik, URL ve durum değerlerini tek bir yerde
tutar. Canlı run başlangıcında bu değerler YÖK Atlas kaynağıyla yeniden
doğrulanmalıdır.
"""

from __future__ import annotations

from scrapers.yokatlas_gibtu_scraper import (
    API_BASE_URL,
    BASE_URL,
    BIRIM_TURU_ID_BY_LEVEL,
    EXPECTED_UNIVERSITY_ID,
    LEVEL_LISANS,
    LEVEL_ONLISANS,
    PROGRAM_ALLOWLIST,
    SEARCH_PATH,
    UNIVERSITIES_PATH,
    UNIVERSITY_NAME,
)

SOURCE_SYSTEM = "YÖK Atlas"
PUBLIC_UNIVERSITY_CODE = "1112"
EXPECTED_API_UNIVERSITY_ID = EXPECTED_UNIVERSITY_ID
CITY = "GAZİANTEP"
UNIVERSITY_TYPE = "DEVLET"

LIST_URLS = {
    LEVEL_LISANS: f"{BASE_URL}/lisans-univ.php?u={PUBLIC_UNIVERSITY_CODE}",
    LEVEL_ONLISANS: f"{BASE_URL}/onlisans-univ.php?u={PUBLIC_UNIVERSITY_CODE}",
}
DETAIL_URL_PATTERNS = {
    LEVEL_LISANS: f"{BASE_URL}/lisans.php?y={{osym_code}}",
    LEVEL_ONLISANS: f"{BASE_URL}/onlisans.php?y={{osym_code}}",
}
PANEL_URL_PATTERNS = {
    LEVEL_LISANS: f"{BASE_URL}/lisans-panel.php?y={{osym_code}}",
    LEVEL_ONLISANS: f"{BASE_URL}/onlisans-panel.php?y={{osym_code}}",
}

REQUIRED_METADATA_FIELDS = (
    "source_url",
    "source_system",
    "university",
    "data_year",
    "crawl_run_id",
    "retrieved_at",
    "checksum",
    "validation_status",
    "manual_review_required",
)

STATUS_NEW_PROGRAM = "new_program_candidate"
STATUS_PASSIVE_PROGRAM = "passive_candidate"
STATUS_IDENTITY_CHANGED = "identity_field_changed"
STATUS_UNIT_CHANGED = "unit_changed"
STATUS_CODE_CHANGE_CANDIDATE = "possible_code_change"
STATUS_SOURCE_URL_CHANGED = "source_url_changed"
STATUS_IMPORT_READY = "import_ready"
STATUS_IMPORT_BLOCKED = "import_blocked"

EXPECTED_SCORE_TYPES = {"SAY", "EA", "SÖZ", "DİL", "TYT"}

__all__ = [
    "API_BASE_URL",
    "BASE_URL",
    "BIRIM_TURU_ID_BY_LEVEL",
    "CITY",
    "DETAIL_URL_PATTERNS",
    "EXPECTED_API_UNIVERSITY_ID",
    "EXPECTED_SCORE_TYPES",
    "LEVEL_LISANS",
    "LEVEL_ONLISANS",
    "LIST_URLS",
    "PANEL_URL_PATTERNS",
    "PROGRAM_ALLOWLIST",
    "PUBLIC_UNIVERSITY_CODE",
    "REQUIRED_METADATA_FIELDS",
    "SEARCH_PATH",
    "SOURCE_SYSTEM",
    "STATUS_CODE_CHANGE_CANDIDATE",
    "STATUS_IDENTITY_CHANGED",
    "STATUS_IMPORT_BLOCKED",
    "STATUS_IMPORT_READY",
    "STATUS_NEW_PROGRAM",
    "STATUS_PASSIVE_PROGRAM",
    "STATUS_SOURCE_URL_CHANGED",
    "STATUS_UNIT_CHANGED",
    "UNIVERSITIES_PATH",
    "UNIVERSITY_NAME",
    "UNIVERSITY_TYPE",
]
