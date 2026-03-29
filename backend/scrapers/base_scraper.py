"""
UniChat Backend — Base Scraper
Minimum çalışan scraper: fetch → parse → to_documents → ingest.

Faz 3.2.0 kapsamında yalnızca temel veri toplama yeteneği sağlar.
Discovery, quality_checker, scheduling → Faz 4'te eklenir.
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy

from scrapers.utils import clean_html, extract_title, normalize_url, is_allowed_domain

logger = logging.getLogger(__name__)


class BaseScraper:
    """
    Basit web scraper — tek bir kategori/bölüm için veri toplar.

    Kullanım:
        scraper = BaseScraper(
            category="bolumler",
            doc_kind="tanitim",
            department="Bilgisayar Mühendisliği",
        )
        count = scraper.scrape(["https://www.gibtu.edu.tr/tr/bolum/..."])
    """

    # ── Sınıf Sabitleri ──
    ALLOWED_DOMAINS: list[str] = ["gibtu.edu.tr"]
    REQUEST_TIMEOUT: int = 30            # saniye
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 2                 # saniye (retry arası bekleme)
    RATE_LIMIT_DELAY: float = 1.0        # saniye (istekler arası bekleme)

    USER_AGENT: str = (
        "Mozilla/5.0 (compatible; UniChatBot/1.0; "
        "+https://github.com/unichat-project)"
    )

    def __init__(
        self,
        category: str,
        doc_kind: str = "genel",
        department: str | None = None,
        contact_unit: str | None = None,
        contact_info: str | None = None,
    ):
        """
        Args:
            category: Belge kategorisi (19 kategoriden biri).
            doc_kind: Belge türü (yonetmelik, duyuru, tanitim, vb.).
            department: İlgili bölüm/fakülte adı.
            contact_unit: Yönlendirme birimi.
            contact_info: Yönlendirme iletişim bilgisi.
        """
        self.category = category
        self.doc_kind = doc_kind
        self.department = department
        self.contact_unit = contact_unit
        self.contact_info = contact_info

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.USER_AGENT})
        self._last_request_time: float = 0.0

    # ── Fetch ──

    def fetch(self, url: str) -> str | None:
        """
        URL'den HTML çeker. Retry + timeout + rate limit uygular.

        Args:
            url: Çekilecek sayfa URL'si.

        Returns:
            Ham HTML string veya hata durumunda None.
        """
        # Alan adı kontrolü
        if not is_allowed_domain(url, self.ALLOWED_DOMAINS):
            logger.warning("URL izin verilen alan dışında, atlanıyor: %s", url)
            return None

        # Rate limit — istekler arası bekleme
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.debug("Fetch denemesi %d/%d: %s", attempt, self.MAX_RETRIES, url)
                response = self._session.get(url, timeout=self.REQUEST_TIMEOUT)
                self._last_request_time = time.time()

                response.raise_for_status()

                # Encoding düzeltme: sunucu charset bildirdiyse onu kullan,
                # bildirmediyse apparent_encoding'e düş (Türkçe için önemli)
                if not response.encoding or response.encoding == "ISO-8859-1":
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "?"
                logger.warning(
                    "HTTP hatası %s — deneme %d/%d: %s",
                    status, attempt, self.MAX_RETRIES, url,
                )
                # 4xx hatalarında retry yapma (404, 403 vb.)
                if e.response is not None and 400 <= e.response.status_code < 500:
                    logger.error("Kalıcı HTTP hatası %s, atlanıyor: %s", status, url)
                    return None

            except requests.exceptions.ConnectionError:
                logger.warning(
                    "Bağlantı hatası — deneme %d/%d: %s",
                    attempt, self.MAX_RETRIES, url,
                )

            except requests.exceptions.Timeout:
                logger.warning(
                    "Zaman aşımı (%ds) — deneme %d/%d: %s",
                    self.REQUEST_TIMEOUT, attempt, self.MAX_RETRIES, url,
                )

            except requests.exceptions.RequestException as e:
                logger.error("Beklenmeyen istek hatası: %s — %s", e, url)
                return None

            # Retry arası bekleme
            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY * attempt)

        logger.error("Tüm denemeler başarısız, atlanıyor: %s", url)
        return None

    # ── Parse ──

    def parse(self, html: str, url: str) -> dict | None:
        """
        HTML'den temiz metin, başlık ve metadata çıkarır.

        Args:
            html: Ham HTML string.
            url: Sayfanın URL'si (metadata için).

        Returns:
            Dict: {url, title, content} veya içerik boşsa None.
        """
        content = clean_html(html)
        title = extract_title(html)

        if not content:
            logger.warning("Boş içerik, atlanıyor: %s", url)
            return None

        return {
            "url": url,
            "title": title,
            "content": content,
        }

    # ── To Documents ──

    def _generate_source_id(self, url: str) -> str:
        """
        URL'den sabit bir source_id üretir.

        Örnek: https://www.gtu.edu.tr/tr/bolum/bm → gtu.edu.tr/tr/bolum/bm
        """
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        netloc = parsed.netloc.lower().replace("www.", "")
        return f"{netloc}/{path}" if path else netloc

    def to_documents(self, pages: list[dict]) -> list[Document]:
        """
        Parse sonuçlarını Haystack Document listesine dönüştürür.

        DocumentMetadata şemasıyla uyumlu metadata atar.

        Args:
            pages: parse() çıktılarının listesi [{url, title, content}, ...].

        Returns:
            Haystack Document listesi.
        """
        documents = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for page in pages:
            url = page["url"]
            content = page["content"]
            title = page.get("title", "")

            # Document ID — içerikten SHA-256
            doc_id = hashlib.sha256(content.encode("utf-8")).hexdigest()

            meta = {
                "category": self.category,
                "source_url": url,
                "source_type": "web",
                "source_id": self._generate_source_id(url),
                "last_updated": now,
                "title": title or "Başlıksız",
                "doc_kind": self.doc_kind,
                "language": "tr",
            }

            # Opsiyonel metadata ekle
            if self.department:
                meta["department"] = self.department
            if self.contact_unit:
                meta["contact_unit"] = self.contact_unit
            if self.contact_info:
                meta["contact_info"] = self.contact_info

            documents.append(Document(id=doc_id, content=content, meta=meta))

        logger.info("%d sayfa → %d Document oluşturuldu.", len(pages), len(documents))
        return documents

    # ── Ana Döngü ──

    def scrape(
        self,
        urls: list[str],
        policy: DuplicatePolicy = DuplicatePolicy.OVERWRITE,
        dry_run: bool = False,
    ) -> int:
        """
        Tam scraping döngüsü: fetch → parse → to_documents → ingest.

        Args:
            urls: Taranacak URL listesi.
            policy: Duplicate politikası (varsayılan OVERWRITE — web verisi güncellenir).
            dry_run: True ise veritabanına yazmadan rapor ver.

        Returns:
            Yazılan belge sayısı.
        """
        if not urls:
            logger.warning("Boş URL listesi, işlem atlanıyor.")
            return 0

        logger.info(
            "Scraping başlıyor: %d URL, category=%s, doc_kind=%s",
            len(urls), self.category, self.doc_kind,
        )

        # URL'leri normalleştir ve deduplicate et
        normalized = []
        seen = set()
        for url in urls:
            norm = normalize_url(url)
            if norm and norm not in seen:
                seen.add(norm)
                normalized.append(norm)

        if len(normalized) < len(urls):
            logger.info(
                "URL normalleştirme: %d → %d (duplicate çıkarıldı).",
                len(urls), len(normalized),
            )

        # Fetch + Parse
        pages = []
        failed_urls = []

        for url in normalized:
            html = self.fetch(url)
            if html is None:
                failed_urls.append(url)
                continue

            parsed = self.parse(html, url)
            if parsed is None:
                failed_urls.append(url)
                continue

            pages.append(parsed)

        # Rapor
        logger.info(
            "Fetch+Parse tamamlandı: %d başarılı, %d başarısız / %d toplam.",
            len(pages), len(failed_urls), len(normalized),
        )
        if failed_urls:
            for furl in failed_urls:
                logger.warning("  ❌ Başarısız URL: %s", furl)

        if not pages:
            logger.warning("Parse edilen sayfa yok, ingestion atlanıyor.")
            return 0

        # To Documents
        documents = self.to_documents(pages)

        # Ingest — ingestion pipeline'a gönder
        from app.ingestion.loader import ingest_documents
        written = ingest_documents(documents, policy=policy, dry_run=dry_run)

        logger.info(
            "✅ Scraping tamamlandı: %d belge yazıldı (dry_run=%s).",
            written, dry_run,
        )
        return written
