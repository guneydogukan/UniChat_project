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
YEMEK_URL_ALT = f"{BASE_URL}/yemek"
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
        session = self._get_session()
        for attempt in range(1, 4):
            try:
                resp = session.get(url, timeout=20)
                resp.raise_for_status()
                if not resp.encoding or resp.encoding == "ISO-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except Exception as e:
                logger.warning("Fetch hata %d/3: %s", attempt, e)
                if attempt < 3:
                    time.sleep(2 * attempt)
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
        Yemekhane menüsünü scrape eder.

        Args:
            dry_run: True ise DB'ye yazmaz.
            force: True ise diff kontrolü atlanır, her zaman günceller.

        Returns:
            MenuScrapeResult nesnesi.
        """
        start_time = time.time()
        result = MenuScrapeResult()

        logger.info("=" * 65)
        logger.info("YEMEKHANE MENÜ SCRAPE")
        logger.info("=" * 65)

        # 1. Canlı sayfayı çek
        html = self._fetch(YEMEK_URL)
        if not html:
            html = self._fetch(YEMEK_URL_ALT)
        if not html:
            result.error = "Yemek sayfası erişilemedi"
            result.duration_seconds = time.time() - start_time
            logger.error("❌ Yemek sayfası erişilemedi")
            return result

        # 2. Menü kartlarını parse et
        menu_text, menu_count = self._parse_menu_cards(html)
        result.content_length = len(menu_text)
        result.menu_items_count = menu_count

        if not menu_text or len(menu_text) < 30:
            result.error = "Menü içeriği boş veya çok kısa"
            result.duration_seconds = time.time() - start_time
            logger.warning("⚠️ Menü içeriği yetersiz: %d karakter", len(menu_text))
            return result

        # 3. Diff kontrolü
        content_changed = self._check_diff(menu_text) if not force else True
        result.content_changed = content_changed

        if not content_changed:
            logger.info("ℹ️ Menü değişmemiş, güncelleme atlanıyor")
            result.success = True
            result.duration_seconds = time.time() - start_time
            return result

        # 4. Document oluştur
        from haystack import Document

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = Document(
            id=hashlib.sha256(menu_text.encode("utf-8")).hexdigest(),
            content=menu_text,
            meta={
                "category": "yemekhane",
                "source_url": YEMEK_URL,
                "source_type": "web",
                "source_id": "yemek_listesi_canli",
                "last_updated": now,
                "title": "GİBTÜ Yemekhane Günlük Menü Listesi",
                "doc_kind": "genel",
                "language": "tr",
                "department": "Sağlık Kültür ve Spor Daire Başkanlığı",
                "contact_unit": "Sağlık Kültür ve Spor Daire Başkanlığı",
                "contact_info": "sks@gibtu.edu.tr",
            },
        )

        documents = [doc]
        result.documents_created = len(documents)

        # 5. DB'ye yaz
        if not dry_run:
            from app.ingestion.loader import ingest_documents
            from haystack.document_stores.types import DuplicatePolicy
            result.chunks_written = ingest_documents(
                documents, policy=DuplicatePolicy.OVERWRITE
            )
        else:
            result.chunks_written = len(documents)

        result.success = True
        result.duration_seconds = time.time() - start_time

        logger.info("\n✅ Menü scrape tamamlandı: %d öğe, %d karakter, değişiklik: %s",
                     menu_count, len(menu_text), "EVET" if content_changed else "HAYIR")

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
