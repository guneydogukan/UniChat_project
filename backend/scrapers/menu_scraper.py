"""
UniChat — Faz 4.2.2: Yemekhane Menü Scraper Modülü

Yemekhane menü sayfasını periyodik olarak scrape eder.
Önceki menü ile diff kontrolü yaparak sadece değişiklikleri günceller.

Kullanım:
    from scrapers.menu_scraper import MenuScraper

    scraper = MenuScraper()
    result = scraper.scrape(dry_run=False)

CLI:
    python -m scrapers.menu_scraper
    python -m scrapers.menu_scraper --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 — Windows stdout UTF-8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
YEMEK_URL = f"{BASE_URL}/yemeklistesi"
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0; +https://github.com/unichat-project)"

# Diff cache dosyası
OUTPUT_DIR = Path(__file__).resolve().parent
DIFF_CACHE_FILE = OUTPUT_DIR / ".menu_last_hash.txt"


@dataclass
class MenuScrapeResult:
    """Yemekhane menü scrape sonucu."""
    success: bool = False
    content_length: int = 0
    menu_items_count: int = 0
    content_changed: bool = False
    documents_created: int = 0
    chunks_written: int = 0
    duration_seconds: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content_length": self.content_length,
            "menu_items_count": self.menu_items_count,
            "content_changed": self.content_changed,
            "documents_created": self.documents_created,
            "chunks_written": self.chunks_written,
            "duration_seconds": round(self.duration_seconds, 1),
            "error": self.error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class MenuScraper:
    """
    Yemekhane menü scraper — canlı sayfayı çeker, menü kartlarını parse eder.
    """

    def __init__(self):
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})
        return self._session

    def _fetch(self, url: str) -> str | None:
        if url != YEMEK_URL:
            raise ValueError("Yemekhane scraper yalnızca sabit yemek listesi URL'sini kullanabilir.")

        session = self._get_session()
        for attempt in range(1, 3):
            try:
                resp = session.get(url, timeout=10)
                resp.raise_for_status()
                if not resp.encoding or resp.encoding == "ISO-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except Exception as e:
                logger.warning("Fetch hata %d/2: %s", attempt, e)
                if attempt < 2:
                    time.sleep(1)
        return None

    def _parse_menu_cards(self, html: str) -> tuple[str, int]:
        """
        Menü kartlarını parse eder.

        Returns:
            (menü metni, menü öğe sayısı)
        """
        soup = BeautifulSoup(html, "html.parser")

        # Boilerplate temizle
        for sel in ["nav", "footer", "header", "script", "style", "noscript",
                     ".side-nav", ".birim-menu", "#birim-menu-slide"]:
            for el in soup.select(sel):
                el.decompose()

        menu_entries = []

        # Menü kartlarını bul (div.card yapısı)
        for card in soup.select("div.card"):
            date_el = card.select_one("div.card-title")
            if not date_el:
                continue
            date_str = date_el.get_text(strip=True)

            items = []
            for col in card.select("div.card-content div.col"):
                text = col.get_text(strip=True)
                if text:
                    items.append(text)

            if items:
                menu_entries.append(f"{date_str}: {', '.join(items)}")

        # Kartlar bulunamazsa fallback: genel içerik çıkar
        if not menu_entries:
            body = (soup.find("div", class_="page_body") or
                    soup.find("div", class_="container") or
                    soup.find("body"))
            if body:
                text = body.get_text(separator="\n", strip=True)
                lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
                if lines:
                    return "\n".join(lines), len(lines)

        if not menu_entries:
            return "", 0

        menu_text = (
            "GİBTÜ Yemekhane Günlük Menü Listesi\n\n"
            + "\n".join(menu_entries)
            + "\n\nNot: Menü bilgileri haftalık olarak güncellenmektedir. "
            "Değişiklik olması halinde yemekhane biriminden bilgi alınabilir."
        )
        return menu_text, len(menu_entries)

    def _check_diff(self, content: str) -> bool:
        """İçerik değişti mi kontrol et."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        if DIFF_CACHE_FILE.exists():
            last_hash = DIFF_CACHE_FILE.read_text().strip()
            if last_hash == content_hash:
                return False  # Değişmemiş

        # Hash'i güncelle
        DIFF_CACHE_FILE.write_text(content_hash)
        return True  # Değişmiş

    def scrape(self, dry_run: bool = False, force: bool = False) -> MenuScrapeResult:
        """
        Yemekhane menüsünü scrape eder ve yeni food_menus tablosuna yazar.

        Not:
            Bu sınıf geriye dönük CLI/scheduler uyumluluğu için korunur.
            Yeni mimaride RAG dokümanı üretilmez; tarih bazlı kalıcı kaynak
            food_menus tablosudur.

        Args:
            dry_run: True ise DB'ye yazmaz.
            force: Geriye dönük uyumluluk için tutulur, yeni akışta kullanılmaz.

        Returns:
            MenuScrapeResult nesnesi.
        """
        start_time = time.time()
        result = MenuScrapeResult()

        logger.info("=" * 65)
        logger.info("YEMEKHANE MENÜ SCRAPE")
        logger.info("=" * 65)

        try:
            from app.repositories.food_menu_repository import FoodMenuRepository
            from scrapers.food_menu_scraper import FoodMenuScraper

            scraper = FoodMenuScraper()
            scrape_result = scraper.fetch_menus()
            if not scrape_result.success:
                result.error = scrape_result.error or "Yemek listesi alınamadı"
                result.duration_seconds = time.time() - start_time
                logger.error("❌ Yemek listesi alınamadı: %s", result.error)
                return result

            result.menu_items_count = len(scrape_result.menus)
            result.content_length = sum(len(menu.raw_text or "") for menu in scrape_result.menus)
            result.documents_created = len(scrape_result.menus)
            result.content_changed = bool(scrape_result.menus)

            if dry_run:
                result.chunks_written = 0
                result.success = True
                result.duration_seconds = time.time() - start_time
                logger.info("DRY-RUN: %d günlük menü parse edildi, DB'ye yazılmadı.", len(scrape_result.menus))
                return result

            repository = FoodMenuRepository()
            written_count = 0
            for menu in scrape_result.menus:
                repository.upsert_menu(
                    menu_date=menu.date,
                    menu_items=menu.menu_items,
                    source_url=menu.source_url,
                    raw_data=menu.raw_data,
                    raw_text=menu.raw_text,
                )
                written_count += 1

            result.chunks_written = written_count
            result.success = True
            result.duration_seconds = time.time() - start_time

            logger.info(
                "\n✅ Menü scrape tamamlandı: %d günlük menü, %d karakter, DB upsert: %d",
                len(scrape_result.menus), result.content_length, written_count,
            )
        except Exception as e:
            result.error = str(e)
            result.duration_seconds = time.time() - start_time
            logger.error("❌ Yemek menüsü güncelleme hatası: %s", e, exc_info=True)

        return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Yemekhane Menü Scraper (Faz 4.2.2)")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan çalıştır")
    parser.add_argument("--force", action="store_true", help="Diff kontrolü atla, her zaman güncelle")
    args = parser.parse_args()

    scraper = MenuScraper()
    result = scraper.scrape(dry_run=args.dry_run, force=args.force)

    output_path = OUTPUT_DIR / "menu_scrape_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Sonuç: %s", output_path)


if __name__ == "__main__":
    main()
