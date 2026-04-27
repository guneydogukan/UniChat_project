"""
UniChat — Faz 4.2.3: Akademik Kadro Listesi Scraper Modülü

run_akademik_kadro_scrape.py mantığını modüler sınıfa taşır.
Tüm birimlerin akademik ve idari personel sayfalarını tarar.
Değişiklik tespiti (diff-based update) ile sadece güncellenenleri yazar.

Kullanım:
    from scrapers.staff_scraper import StaffScraper

    scraper = StaffScraper()
    result = scraper.scrape(dry_run=False)

CLI:
    python -m scrapers.staff_scraper
    python -m scrapers.staff_scraper --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
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
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0; +https://github.com/unichat-project)"

# Tüm birim BirimID eşleştirmesi (run_akademik_kadro_scrape.py'den genişletildi)
BIRIM_MAP = {
    # Fakülteler
    "İlahiyat Fakültesi": 11,
    "Mühendislik ve Doğa Bilimleri Fakültesi": 15,
    "Elektrik-Elektronik Mühendisliği Bölümü": 16,
    "İnşaat Mühendisliği Bölümü": 17,
    "Bilgisayar Mühendisliği Bölümü": 18,
    "Endüstri Mühendisliği Bölümü": 19,
    "Tıp Fakültesi": 20,
    "Sağlık Bilimleri Fakültesi": 21,
    "İktisadi İdari ve Sosyal Bilimler Fakültesi": 22,
    "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi": 24,
    # MYO
    "Sağlık Hizmetleri MYO": 31,
    "Yabancı Diller Yüksekokulu": 34,
    "Lisansüstü Eğitim Enstitüsü": 35,
    "Teknik Bilimler MYO": 36,
    # Koordinatörlükler
    "Erasmus+ Koordinatörlüğü": 45,
    "Dış İlişkiler Koordinatörlüğü": 79,
    # Daire Başkanlıkları
    "Öğrenci İşleri Daire Başkanlığı": 4,
    "Kütüphane ve Dokümantasyon Daire Başkanlığı": 7,
    "Sağlık Kültür ve Spor Daire Başkanlığı": 8,
}

# Personel sayfası türleri
PAGE_TYPES = [
    ("BirimAkademikPersonel.aspx", "akademik_personel"),
    ("BirimIdariPersonel.aspx", "idari_personel"),
]

OUTPUT_DIR = Path(__file__).resolve().parent


@dataclass
class StaffScrapeResult:
    """Kadro scrape sonucu."""
    success: bool = False
    total_birimler: int = 0
    pages_scraped: int = 0
    new_documents: int = 0
    skipped_existing: int = 0
    skipped_empty: int = 0
    failed: int = 0
    chunks_written: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "total_birimler": self.total_birimler,
            "pages_scraped": self.pages_scraped,
            "new_documents": self.new_documents,
            "skipped_existing": self.skipped_existing,
            "skipped_empty": self.skipped_empty,
            "failed": self.failed,
            "chunks_written": self.chunks_written,
            "duration_seconds": round(self.duration_seconds, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class StaffScraper:
    """
    Akademik kadro scraper — tüm birimlerin personel sayfalarını tarar.
    """

    RATE_LIMIT = 1.2

    def __init__(self, birim_map: dict | None = None):
        self.birim_map = birim_map or BIRIM_MAP
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
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                if not resp.encoding or resp.encoding.upper() in ("ISO-8859-1", "ASCII"):
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except requests.exceptions.HTTPError as e:
                if e.response is not None and 400 <= e.response.status_code < 500:
                    return None
                logger.warning("HTTP hata %d/3: %s", attempt, url[:60])
            except Exception as e:
                logger.warning("Fetch hata %d/3: %s — %s", attempt, e, url[:60])
            if attempt < 3:
                time.sleep(2 * attempt)
        return None

    def _parse_personel_page(self, html: str) -> tuple[str, str]:
        """Personel sayfasını parse eder. (title, body) döndürür."""
        if not html:
            return "", ""

        soup = BeautifulSoup(html, "lxml")

        # Başlık
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Ana içerik
        from scrapers.blueprint_parser import extract_body_content
        body = extract_body_content(html)
        if not body or len(body.strip()) < 20:
            from scrapers.utils import clean_html
            body = clean_html(html)

        return title, body

    def _get_existing_urls(self) -> set[str]:
        """DB'de halihazırda olan personel source_url'lerini al."""
        try:
            import psycopg2
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent.parent / ".env")

            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT meta->>'source_url' FROM haystack_docs
                WHERE meta->>'doc_kind' = 'personel' AND meta->>'source_url' IS NOT NULL
            """)
            urls = {r[0] for r in cur.fetchall()}
            cur.close()
            conn.close()
            return urls
        except Exception as e:
            logger.warning("DB'den mevcut URL'ler okunamadı: %s", e)
            return set()

    def scrape(
        self,
        dry_run: bool = False,
        force: bool = False,
    ) -> StaffScrapeResult:
        """
        Tüm birimlerin personel sayfalarını tarar.

        Args:
            dry_run: True ise DB'ye yazmaz.
            force: True ise mevcut URL kontrolü atlanır.

        Returns:
            StaffScrapeResult nesnesi.
        """
        start_time = time.time()
        result = StaffScrapeResult(total_birimler=len(self.birim_map))

        logger.info("=" * 65)
        logger.info("AKADEMİK KADRO SCRAPE — %d birim", len(self.birim_map))
        logger.info("=" * 65)

        # Mevcut URL'leri kontrol et
        existing_urls = set() if force else self._get_existing_urls()
        logger.info("  DB'de mevcut personel URL: %d", len(existing_urls))

        from haystack import Document

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        all_docs = []

        for dept_name, birim_id in self.birim_map.items():
            for page_template, page_label in PAGE_TYPES:
                url = f"{BASE_URL}/{page_template}?id={birim_id}"

                if url in existing_urls and not force:
                    result.skipped_existing += 1
                    continue

                time.sleep(self.RATE_LIMIT)
                html = self._fetch(url)
                if not html:
                    result.failed += 1
                    continue

                title, body = self._parse_personel_page(html)
                if not body or len(body.strip()) < 30:
                    result.skipped_empty += 1
                    continue

                result.pages_scraped += 1
                doc_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
                meta = {
                    "category": "genel_bilgi",
                    "source_url": url,
                    "source_type": "web",
                    "source_id": f"gibtu_personel_{birim_id}_{page_label}",
                    "last_updated": now,
                    "title": f"{dept_name} - {page_label.replace('_', ' ').title()}",
                    "doc_kind": "personel",
                    "language": "tr",
                    "department": dept_name,
                    "contact_unit": dept_name,
                    "contact_info": "",
                    "birim_id": birim_id,
                }
                all_docs.append(Document(id=doc_id, content=body, meta=meta))
                logger.info("  [NEW] %s — %s | %d kar", dept_name, page_label, len(body))

        result.new_documents = len(all_docs)

        # DB'ye yaz
        if all_docs and not dry_run:
            from app.ingestion.loader import ingest_documents
            from haystack.document_stores.types import DuplicatePolicy
            result.chunks_written = ingest_documents(
                all_docs, policy=DuplicatePolicy.OVERWRITE
            )
        elif dry_run:
            result.chunks_written = len(all_docs)

        result.duration_seconds = time.time() - start_time
        result.success = True

        logger.info("\n" + "=" * 65)
        logger.info(
            "KADRO SCRAPE TAMAMLANDI: %d yeni, %d skip, %d fail, %d chunk, %.1fs",
            result.new_documents, result.skipped_existing,
            result.failed, result.chunks_written, result.duration_seconds,
        )
        logger.info("=" * 65)

        return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Akademik Kadro Scraper (Faz 4.2.3)")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan çalıştır")
    parser.add_argument("--force", action="store_true", help="Mevcut URL kontrolü atla")
    args = parser.parse_args()

    scraper = StaffScraper()
    result = scraper.scrape(dry_run=args.dry_run, force=args.force)

    output_path = OUTPUT_DIR / "staff_scrape_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Sonuç: %s", output_path)


if __name__ == "__main__":
    main()
