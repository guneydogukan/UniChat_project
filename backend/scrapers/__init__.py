"""
UniChat Backend — Scrapers
Web scraping modülü: üniversite sitesinden veri toplama.
"""

from scrapers.base_scraper import BaseScraper
from scrapers.utils import clean_html, extract_title, normalize_url, is_allowed_domain

__all__ = [
    "BaseScraper",
    "clean_html",
    "extract_title",
    "normalize_url",
    "is_allowed_domain",
]
