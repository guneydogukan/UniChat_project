"""YÖK Atlas extraction katmanı.

HTTP client, raw snapshot store, katalog/detay crawler ve mevcut GİBTÜ scraper
bu paketten erişilebilir. Yeni endpoint/HAR veya Playwright fallback işleri
bu katmanda ayrı adapter olarak eklenmelidir.
"""

from __future__ import annotations

from scrapers.yokatlas_gibtu_scraper import (
    ProgramDetailCrawler,
    RawSnapshotStore,
    SnapshotRecord,
    YokatlasGibtuScraper,
    YokatlasHttpClient,
    YokatlasHttpError,
    YokatlasScrapeReport,
)

__all__ = [
    "ProgramDetailCrawler",
    "RawSnapshotStore",
    "SnapshotRecord",
    "YokatlasGibtuScraper",
    "YokatlasHttpClient",
    "YokatlasHttpError",
    "YokatlasScrapeReport",
]
