"""
UniChat Backend — Scrapers
Web scraping modülü: üniversite sitesinden veri toplama.

Modüller:
  - base_scraper          — Temel scraper sınıfı
  - map_guided_scraper    — Blueprint güdümlü gelişmiş scraper
  - blueprint_parser      — Blueprint HTML parse
  - blueprint_cache       — Parse edilmiş menü ağaçları önbelleği (Faz 4.1.3)
  - quality_checker       — Scrape sonrası kalite raporu (Faz 4.1.1)
  - department_scraper    — Toplu birim scraper (Faz 4.1.2)
  - announcement_scraper  — Duyuru arşivi scraper (Faz 4.2.1)
  - menu_scraper          — Yemekhane menü scraper (Faz 4.2.2)
  - staff_scraper         — Akademik kadro scraper (Faz 4.2.3)
  - coverage_tools        — Kapsam analizi araçları (Faz 4.3)
  - scheduler             — APScheduler periyodik güncelleme (Faz 4.4)
  - utils                 — HTML temizleme, URL normalleştirme
"""

__all__ = [
    "BaseScraper",
    "clean_html",
    "extract_title",
    "normalize_url",
    "is_allowed_domain",
]


def __getattr__(name):
    """Ağır scraper bağımlılıklarını paket import anında yükleme."""
    if name == "BaseScraper":
        from scrapers.base_scraper import BaseScraper

        return BaseScraper

    if name in {"clean_html", "extract_title", "normalize_url", "is_allowed_domain"}:
        from importlib import import_module

        utils = import_module("scrapers.utils")
        return getattr(utils, name)

    raise AttributeError(f"module 'scrapers' has no attribute {name!r}")
