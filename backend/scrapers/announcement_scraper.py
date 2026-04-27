"""
UniChat — Faz 4.2.1: Duyuru Arşivi Scraper Modülü

run_duyuru_scrape.py'deki mantığı modüler, yeniden kullanılabilir sınıfa taşır.
APScheduler'dan çağrılabilir API sağlar.

Özellikler:
  - Son 10 sayfa sınırı (varsayılan), delta modu (3 sayfa)
  - Bilinen birim listesinden arşiv tarama
  - Detay sayfası scrape + boilerplate temizleme
  - OVERWRITE ile DB güncelleme
  - Kalite raporu entegrasyonu

Kullanım:
    from scrapers.announcement_scraper import AnnouncementScraper

    scraper = AnnouncementScraper()
    result = scraper.scrape(mode="delta")          # Son 3 sayfa
    result = scraper.scrape(mode="full")           # Son 10 sayfa
    result = scraper.scrape(mode="full", dry_run=True)

CLI:
    python -m scrapers.announcement_scraper --mode delta
    python -m scrapers.announcement_scraper --mode full --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
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

# Birimler — BirimID'lere göre duyuru kaynakları
DEFAULT_DUYURU_BIRIMLERI = [
    {"id": 1,   "name": "Rektörlük",                      "k": "duyuru"},
    {"id": 1,   "name": "Rektörlük",                      "k": "haber"},
    {"id": 15,  "name": "Mühendislik ve Doğa Bilimleri",  "k": "duyuru"},
    {"id": 11,  "name": "İlahiyat Fakültesi",             "k": "duyuru"},
    {"id": 20,  "name": "Tıp Fakültesi",                  "k": "duyuru"},
    {"id": 21,  "name": "Sağlık Bilimleri Fakültesi",     "k": "duyuru"},
    {"id": 22,  "name": "İİSBF",                          "k": "duyuru"},
    {"id": 24,  "name": "Güzel Sanatlar Fakültesi",       "k": "duyuru"},
    {"id": 4,   "name": "Öğrenci İşleri",                 "k": "duyuru"},
    {"id": 8,   "name": "SKS",                            "k": "duyuru"},
    {"id": 31,  "name": "Sağlık Hizmetleri MYO",          "k": "duyuru"},
    {"id": 36,  "name": "Teknik Bilimler MYO",            "k": "duyuru"},
]


@dataclass
class AnnouncementResult:
    """Duyuru scrape sonucu."""
    mode: str = "full"
    max_pages: int = 10
    archive_pages_scanned: int = 0
    detail_urls_found: int = 0
    documents_created: int = 0
    chunks_written: int = 0
    errors: int = 0
    skipped: int = 0
    birim_distribution: dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "max_pages": self.max_pages,
            "archive_pages_scanned": self.archive_pages_scanned,
            "detail_urls_found": self.detail_urls_found,
            "documents_created": self.documents_created,
            "chunks_written": self.chunks_written,
            "errors": self.errors,
            "skipped": self.skipped,
            "birim_distribution": self.birim_distribution,
            "duration_seconds": round(self.duration_seconds, 1),
            "success": self.success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class AnnouncementScraper:
    """
    Duyuru arşivi scraper — birim bazlı arşiv sayfalarını tarar,
    detay sayfalarını scrape eder ve DB'ye yükler.
    """

    MAX_PAGES_FULL = 10
    MAX_PAGES_DELTA = 3
    RATE_LIMIT = 1.2  # saniye
    MIN_CONTENT_LENGTH = 30
    MAX_CONTENT_LENGTH = 30000

    def __init__(
        self,
        birimler: list[dict] | None = None,
        rate_limit: float | None = None,
    ):
        self.birimler = birimler or DEFAULT_DUYURU_BIRIMLERI
        self.rate_limit = rate_limit or self.RATE_LIMIT
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})
        return self._session

    def _fetch(self, url: str) -> str | None:
        """Canlı fetch with retry + encoding fallback."""
        session = self._get_session()
        for attempt in range(1, 4):
            try:
                resp = session.get(url, timeout=20)
                resp.raise_for_status()
                if not resp.encoding or resp.encoding == "ISO-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                if e.response is not None and 400 <= e.response.status_code < 500:
                    return None
                logger.warning("HTTP %s — deneme %d/3: %s", status, attempt, url[:70])
            except Exception as e:
                logger.warning("Fetch hata %d/3: %s — %s", attempt, e, url[:60])
            if attempt < 3:
                time.sleep(2 * attempt)
        return None

    def _clean_text(self, html: str) -> str:
        """Boilerplate temizle, ana içerik çıkar."""
        soup = BeautifulSoup(html, "html.parser")
        for sel in ["nav", "footer", "header", "script", "style", "noscript",
                     ".side-nav", ".birim-menu", "#birim-menu-slide",
                     ".breadcrumb", ".footer", ".ust-menu"]:
            for el in soup.select(sel):
                el.decompose()

        body = (soup.find("div", class_="birim_safya_body_detay") or
                soup.find("div", class_="page_body") or
                soup.find("section", class_="birim_safya_body") or
                soup.find("div", class_="container") or
                soup.find("body"))

        if not body:
            return ""

        text = body.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 2]
        return "\n".join(lines)

    def _extract_title(self, html: str) -> str:
        """Detay sayfasından başlık çıkar."""
        soup = BeautifulSoup(html, "html.parser")

        el = soup.select_one("span.sayfa_baslik")
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

        el = soup.select_one("div.card-panel span")
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

        el = soup.find("h1")
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

        el = soup.find("title")
        if el:
            t = el.get_text(strip=True)
            t = re.sub(r"\s*[-–]\s*G[İi]BT[ÜU].*$", "", t)
            if t:
                return t

        return "Duyuru"

    def _scan_archive_pages(self, max_pages: int) -> list[tuple]:
        """Arşiv sayfalarından detay URL'lerini toplar."""
        all_items = []  # (url, title, date_str, birim_name, kind)
        seen_urls = set()
        total_pages = 0

        for birim in self.birimler:
            birim_id = birim["id"]
            birim_name = birim["name"]
            kind = birim["k"]
            birim_items = 0
            empty_streak = 0

            for page_num in range(1, max_pages + 1):
                archive_url = (
                    f"{BASE_URL}/BirimDuyuruArsivi.aspx?"
                    f"id={birim_id}&k={kind}&p={page_num}"
                )

                html = self._fetch(archive_url)
                if not html:
                    break

                total_pages += 1
                soup = BeautifulSoup(html, "html.parser")

                # Duyuru kartları
                detail_links = []
                for a_tag in soup.select("a[href*='BirimIcerik']"):
                    href = a_tag.get("href", "")
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = f"{BASE_URL}/{href.lstrip('/')}"
                    if href in seen_urls:
                        continue

                    seen_urls.add(href)
                    title_el = a_tag.select_one("div.duyuru-baslik")
                    title = title_el.get_text(strip=True) if title_el else "Duyuru"
                    gun_el = a_tag.select_one("span.gun")
                    ay_el = a_tag.select_one("span.ay")
                    date_str = ""
                    if gun_el and ay_el:
                        date_str = f"{gun_el.get_text(strip=True)} {ay_el.get_text(strip=True)}"

                    detail_links.append((href, title, date_str, birim_name, kind))
                    birim_items += 1

                if not detail_links:
                    empty_streak += 1
                    if empty_streak >= 2:
                        break
                    continue
                else:
                    empty_streak = 0

                all_items.extend(detail_links)
                time.sleep(self.rate_limit)

            logger.info("  [%s] %d duyuru tespit", birim_name, birim_items)

        logger.info("  TOPLAM: %d duyuru URL, %d arşiv sayfası", len(all_items), total_pages)
        return all_items

    def scrape(
        self,
        mode: str = "full",
        dry_run: bool = False,
    ) -> AnnouncementResult:
        """
        Duyuru arşivini scrape eder.

        Args:
            mode: "full" (10 sayfa) veya "delta" (3 sayfa).
            dry_run: True ise DB'ye yazmaz.

        Returns:
            AnnouncementResult nesnesi.
        """
        start_time = time.time()
        max_pages = self.MAX_PAGES_FULL if mode == "full" else self.MAX_PAGES_DELTA

        result = AnnouncementResult(mode=mode, max_pages=max_pages)

        logger.info("=" * 65)
        logger.info("DUYURU SCRAPE — mod: %s, max sayfa: %d", mode.upper(), max_pages)
        logger.info("=" * 65)

        # 1. Arşiv sayfalarını tara
        items = self._scan_archive_pages(max_pages)
        result.archive_pages_scanned = len(items)
        result.detail_urls_found = len(items)

        if not items:
            logger.warning("Hiç duyuru URL tespit edilmedi!")
            result.duration_seconds = time.time() - start_time
            return result

        # 2. Detay sayfalarını scrape et
        from haystack import Document

        documents = []
        birim_dist: dict[str, int] = {}

        for i, (url, card_title, date_str, birim_name, kind) in enumerate(items):
            try:
                html = self._fetch(url)
                if not html:
                    result.errors += 1
                    continue

                content = self._clean_text(html)
                if len(content) < self.MIN_CONTENT_LENGTH:
                    result.skipped += 1
                    continue

                page_title = self._extract_title(html)
                if page_title in ("Duyuru", "Haber", ""):
                    page_title = card_title

                doc_kind = "duyuru" if kind == "duyuru" else "haber"
                safe_title = re.sub(r'[^a-z0-9]', '_', page_title.lower()[:50])
                source_id = f"duyuru_{birim_name.lower().replace(' ', '_')[:20]}_{safe_title}"

                doc = Document(
                    id=hashlib.sha256(f"{url}_{content[:200]}".encode()).hexdigest()[:16],
                    content=content[:self.MAX_CONTENT_LENGTH],
                    meta={
                        "category": "duyurular",
                        "source_url": url,
                        "source_type": "web",
                        "source_id": source_id,
                        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "title": page_title,
                        "doc_kind": doc_kind,
                        "department": birim_name,
                        "contact_unit": birim_name,
                        "announcement_date": date_str,
                        "announcement_type": kind,
                    },
                )
                documents.append(doc)
                birim_dist[birim_name] = birim_dist.get(birim_name, 0) + 1

                if (i + 1) % 25 == 0:
                    logger.info("  İlerleme: %d/%d", i + 1, len(items))

                time.sleep(self.rate_limit)

            except Exception as e:
                logger.error("Detay hata %s: %s", url[:60], e)
                result.errors += 1

        result.documents_created = len(documents)
        result.birim_distribution = birim_dist

        # 3. DB'ye yaz
        if documents and not dry_run:
            from app.ingestion.loader import ingest_documents
            from haystack.document_stores.types import DuplicatePolicy
            result.chunks_written = ingest_documents(
                documents, policy=DuplicatePolicy.OVERWRITE
            )

        if dry_run:
            result.chunks_written = len(documents)
            logger.info("DRY-RUN: %d document oluşturuldu", len(documents))

        result.duration_seconds = time.time() - start_time
        result.success = result.documents_created > 0

        logger.info("\n" + "=" * 65)
        logger.info("DUYURU SCRAPE %s — %d doc, %d chunk, %.1fs",
                     "BAŞARILI" if result.success else "BAŞARISIZ",
                     result.documents_created, result.chunks_written,
                     result.duration_seconds)
        logger.info("=" * 65)

        return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Duyuru Arşivi Scraper (Faz 4.2.1)")
    parser.add_argument("--mode", choices=["full", "delta"], default="full",
                        help="full: 10 sayfa, delta: 3 sayfa")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan çalıştır")
    args = parser.parse_args()

    scraper = AnnouncementScraper()
    result = scraper.scrape(mode=args.mode, dry_run=args.dry_run)

    # Özet kaydet
    output_path = Path(__file__).parent / "announcement_scrape_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Sonuç: %s", output_path)


if __name__ == "__main__":
    main()
