"""
UniChat — Görev 3.2.7.2: Harita Güdümlü Canlı Scraper Sınıfı

Blueprint parser (3.2.7.1) çıktısını kullanarak canlı GİBTÜ sitesini
sistematik olarak tarayan ana scraper sınıfı.

3 aşamalı döngü:
  🗺️  Harita Okuma      → blueprint_parser.py (3.2.7.1)
  🌐  Canlı Deep Scrape → **Bu modül** (3.2.7.2)
  ✅  Doğrula + Yükle   → ingestion pipeline

Kullanım (programatik):
    from scrapers.map_guided_scraper import MapGuidedScraper

    scraper = MapGuidedScraper(
        blueprint_path="doc/gibtu/FAKÜLTELER/.../MDBF.html",
        category="bolumler",
        department="Mühendislik ve Doğa Bilimleri Fakültesi",
    )
    report = scraper.scrape_all(dry_run=True)

CLI:
    python -m scrapers.map_guided_scraper \\
        --blueprint "doc/gibtu/FAKÜLTELER/.../MDBF.html" \\
        --category bolumler \\
        --department "Mühendislik ve Doğa Bilimleri Fakültesi"

    # İlk 5 URL ile sınırlı test:
    python -m scrapers.map_guided_scraper ... --limit 5

    # Canlı ingestion:
    python -m scrapers.map_guided_scraper ... --ingest
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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Proje kök dizinini path'e ekle
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from scrapers.blueprint_parser import (
    MenuTree,
    MenuLink,
    LinkType,
    parse_blueprint,
    extract_sidebar_menu,
    extract_body_content,
    classify_menu_link,
)
from scrapers.utils import clean_html, is_allowed_domain

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Sabitler ──────────────────────────────────────────────────────────────────

BASE_URL = "https://www.gibtu.edu.tr"
USER_AGENT = (
    "Mozilla/5.0 (compatible; UniChatBot/1.0; "
    "+https://github.com/unichat-project)"
)

DEFAULT_ALLOWED_DOMAINS = ["gibtu.edu.tr"]
DEFAULT_MAX_DEPTH = 5
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
DEFAULT_RATE_LIMIT = 1.5   # saniye (istekler arası)

# Encoding fallback sırası (GİBTÜ'nün sunucu charset sorunları için)
ENCODING_FALLBACKS = ["utf-8", "windows-1254", "iso-8859-9"]

# Placeholder anahtar kelimeleri (scrape edilen içerik içinde)
PLACEHOLDER_KEYWORDS = [
    "lorem ipsum", "örnek metin", "içerik eklenecek",
    "yapım aşamasında", "coming soon", "under construction",
    "bu sayfa henüz", "test sayfası",
]

# Boilerplate kalıpları (GİBTÜ header/footer kalıntıları)
_BOILERPLATE_PATTERNS = [
    r"GIBTU Homepage\s*",
    r"GAZİANTEP İSLAM,?\s*BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ\s*",
    r"\"Kariyeriniz Bizimle Başlar\"\s*",
    r"Bilgi Edinme\s*",
    r"E-Devlet Girişi\s*",
    r"Kişisel Veri Korunması\s*",
    r"Üst Menu\s*",
]

# Minimum içerik uzunluğu (bundan kısa sayfalar "boş" sayılır)
MIN_CONTENT_LENGTH = 20

# İçerik kalite uyarı eşiği
SHORT_CONTENT_WARN = 80


# ── Sonuç Dataclass'ları ──────────────────────────────────────────────────────

@dataclass
class ParseResult:
    """Tek bir sayfanın deep_parse sonucu."""
    url: str
    title: str = ""
    body_content: str = ""
    char_count: int = 0
    discovered_urls: list[str] = field(default_factory=list)
    discovered_pdfs: list[MenuLink] = field(default_factory=list)
    external_links: list[MenuLink] = field(default_factory=list)
    depth: int = 0
    is_valid: bool = True
    skip_reason: str = ""
    placeholder_detected: str | None = None


@dataclass
class ScrapeReport:
    """Tam scrape döngüsünün sonuç raporu."""
    blueprint_path: str = ""
    birim_id: int | None = None
    birim_title: str = ""
    category: str = ""
    department: str = ""
    total_blueprint_urls: int = 0
    total_fetched: int = 0
    total_valid: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    total_documents: int = 0
    total_chars: int = 0
    discovered_pdfs: list[dict] = field(default_factory=list)
    external_links: list[dict] = field(default_factory=list)
    failed_urls: list[dict] = field(default_factory=list)
    skipped_urls: list[dict] = field(default_factory=list)
    page_results: list[dict] = field(default_factory=list)
    metadata_completeness: dict = field(default_factory=dict)
    doc_kind_distribution: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serializable dict çıktısı."""
        return {
            "meta": {
                "task": "3.2.7.2",
                "description": "Harita Güdümlü Canlı Scrape",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "blueprint_path": self.blueprint_path,
                "birim_id": self.birim_id,
                "birim_title": self.birim_title,
                "category": self.category,
                "department": self.department,
            },
            "summary": {
                "total_blueprint_urls": self.total_blueprint_urls,
                "total_fetched": self.total_fetched,
                "total_valid": self.total_valid,
                "total_failed": self.total_failed,
                "total_skipped": self.total_skipped,
                "total_documents": self.total_documents,
                "total_chars": self.total_chars,
            },
            "discovered_pdfs": self.discovered_pdfs,
            "external_links": self.external_links,
            "failed_urls": self.failed_urls,
            "skipped_urls": self.skipped_urls,
            "page_results": self.page_results,
            "metadata_completeness": self.metadata_completeness,
            "doc_kind_distribution": self.doc_kind_distribution,
        }


# ── MapGuidedScraper Sınıfı ──────────────────────────────────────────────────

class MapGuidedScraper:
    """
    Blueprint parser çıktısını kullanarak canlı siteyi sistematik tarayan scraper.

    Döngü:
      1. load_blueprint()       → Lokal HTML'den MenuTree parse
      2. build_target_urls()    → Haritadan scrape edilecek URL'leri üret
      3. fetch_live(url)        → Canlı siteden HTML al
      4. deep_parse(html, url)  → İçeriği çıkar + alt menü keşfi
      5. scrape_all()           → Tüm döngüyü çalıştır
    """

    def __init__(
        self,
        blueprint_path: str | Path,
        category: str = "genel_bilgi",
        department: str = "",
        doc_kind: str = "genel",
        contact_unit: str = "",
        contact_info: str = "",
        # Güvenlik parametreleri
        max_depth: int = DEFAULT_MAX_DEPTH,
        allowed_domains: list[str] | None = None,
        # HTTP parametreleri
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        # URL limiti (test/debug)
        url_limit: int | None = None,
    ):
        """
        Args:
            blueprint_path: Lokal HTML blueprint dosyasının yolu.
            category: Belge kategorisi (CATEGORIES enum'undan).
            department: Birim/fakülte adı.
            doc_kind: Varsayılan belge türü.
            contact_unit: Yönlendirme birimi.
            contact_info: İletişim bilgisi.
            max_depth: Recursive sidebar keşif derinliği üst sınırı.
            allowed_domains: İzin verilen alan adları.
            max_retries: HTTP istek tekrar sayısı.
            timeout: HTTP istek timeout süresi (saniye).
            rate_limit: İstekler arası bekleme (saniye).
            url_limit: Test için en fazla bu kadar URL scrape et.
        """
        self.blueprint_path = Path(blueprint_path)
        self.category = category
        self.department = department
        self.doc_kind = doc_kind
        self.contact_unit = contact_unit
        self.contact_info = contact_info

        # Güvenlik
        self.max_depth = max_depth
        self.allowed_domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS
        self.visited_urls: set[str] = set()

        # HTTP
        self.max_retries = max_retries
        self.timeout = timeout
        self.rate_limit = rate_limit

        # Limit
        self.url_limit = url_limit

        # Dahili durum
        self._session: requests.Session | None = None
        self._menu_tree: MenuTree | None = None
        self._all_discovered_pdfs: list[MenuLink] = []
        self._all_external_links: list[MenuLink] = []

    # ── Session yönetimi ──

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})
        return self._session

    # ── 1. Blueprint Yükleme ──

    def load_blueprint(self) -> MenuTree:
        """
        Lokal HTML dosyasından menü ağacını parse eder.

        Returns:
            MenuTree yapısı (birim_id, items, vb. içerir).

        Raises:
            FileNotFoundError: Blueprint dosyası bulunamazsa.
        """
        logger.info("Blueprint yükleniyor: %s", self.blueprint_path.name)
        self._menu_tree = parse_blueprint(self.blueprint_path)

        if not self._menu_tree.items:
            logger.warning("Blueprint menü ağacı boş: %s", self.blueprint_path)

        # Blueprint'teki PDF ve external linkleri hemen topla
        self._all_discovered_pdfs = list(self._menu_tree.get_pdf_links())
        self._all_external_links = list(self._menu_tree.get_external_links())

        logger.info(
            "  MenuTree: %d öğe, BirimID=%s, %d PDF, %d harici link",
            len(self._menu_tree.items),
            self._menu_tree.birim_id,
            len(self._all_discovered_pdfs),
            len(self._all_external_links),
        )

        return self._menu_tree

    # ── 2. Hedef URL Üretimi ──

    def build_target_urls(self) -> list[str]:
        """
        Haritadan canlı scrape edilecek URL listesini üretir.

        Harici/anchor/parent/subdomain linkleri filtrelenir.
        Yalnızca izin verilen domain'deki PAGE linkler döndürülür.

        Returns:
            Deduplicate edilmiş hedef URL listesi.
        """
        if self._menu_tree is None:
            self.load_blueprint()

        assert self._menu_tree is not None

        # Sadece PAGE tipindeki linkler
        raw_urls = self._menu_tree.to_url_list(include_types={LinkType.PAGE})

        # Domain kontrolü
        filtered: list[str] = []
        for url in raw_urls:
            if not is_allowed_domain(url, self.allowed_domains):
                logger.debug("Domain dışı URL atlandı: %s", url)
                continue
            filtered.append(url)

        # URL limiti (test modu)
        if self.url_limit and len(filtered) > self.url_limit:
            logger.info(
                "URL limiti uygulanıyor: %d → %d", len(filtered), self.url_limit
            )
            filtered = filtered[:self.url_limit]

        logger.info("Hedef URL sayısı: %d (blueprint'ten %d)", len(filtered), len(raw_urls))
        return filtered

    # ── 3. Canlı Fetch ──

    def fetch_live(self, url: str) -> str | None:
        """
        Canlı siteden HTML çeker.

        Args:
            url: Hedef URL.

        Returns:
            HTML string veya None (başarısız).
        """
        session = self._get_session()

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = session.get(url, timeout=self.timeout)
                resp.raise_for_status()

                # Encoding düzeltme (GİBTÜ'nün charset sorunları)
                if not resp.encoding or resp.encoding.upper() in ("ISO-8859-1", "ASCII"):
                    # Apparent encoding denemesi
                    detected = resp.apparent_encoding
                    if detected and detected.lower() in ("utf-8", "windows-1254", "iso-8859-9"):
                        resp.encoding = detected
                    else:
                        # Fallback zinciri
                        for enc in ENCODING_FALLBACKS:
                            try:
                                resp.content.decode(enc)
                                resp.encoding = enc
                                break
                            except (UnicodeDecodeError, LookupError):
                                continue
                        else:
                            resp.encoding = "utf-8"

                return resp.text

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else "?"
                logger.warning(
                    "HTTP %s — deneme %d/%d: %s",
                    status, attempt, self.max_retries, url,
                )
                # 4xx → kalıcı hata
                if e.response is not None and 400 <= e.response.status_code < 500:
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning(
                    "Bağlantı hatası — deneme %d/%d: %s",
                    attempt, self.max_retries, url,
                )
            except requests.exceptions.Timeout:
                logger.warning(
                    "Zaman aşımı — deneme %d/%d: %s",
                    attempt, self.max_retries, url,
                )
            except requests.exceptions.RequestException as e:
                logger.error("Beklenmeyen hata: %s — %s", e, url)
                return None

            # Retry delay (exponential backoff)
            if attempt < self.max_retries:
                time.sleep(2 * attempt)

        logger.error("Tüm denemeler başarısız: %s", url)
        return None

    # ── 4. Deep Parse ──

    def deep_parse(self, html: str, url: str, depth: int = 0) -> ParseResult:
        """
        Sayfayı parse eder: içerik çıkarma + sidebar menü keşfi.

        Deep parse, canlı sayfanın kendi sidebar menüsünü de parse ederek
        blueprint'te olmayan alt sayfaları keşfeder (max_depth sınırı ile).

        Args:
            html: Ham HTML içeriği.
            url: Sayfanın URL'si.
            depth: Mevcut recursive derinlik.

        Returns:
            ParseResult nesesi.
        """
        result = ParseResult(url=url, depth=depth)

        if not html:
            result.is_valid = False
            result.skip_reason = "empty_html"
            return result

        soup = BeautifulSoup(html, "lxml")

        # ── Başlık çıkarma (GİBTÜ'ye özel) ──
        title = ""
        for selector_fn, selector_arg in [
            (soup.find, ("span", {"class": "page_title"})),
            (soup.find, ("span", {"class": "sayfa_baslik"})),
            (soup.find, ("div", {"class": "card-title"})),
            (soup.find, ("h1",)),
        ]:
            el = selector_fn(*selector_arg) if isinstance(selector_arg, tuple) else selector_fn(selector_arg)
            if el:
                inner = el.find("span") if el.name in ("span",) and el.find("span") else el
                txt = inner.get_text(strip=True) if inner else el.get_text(strip=True)
                if txt:
                    title = txt
                    break

        result.title = title

        # ── Ana içerik çıkarma ──
        # Önce birim_safya_body_detay, sonra genel clean_html
        body = extract_body_content(html)
        if not body or len(body.strip()) < MIN_CONTENT_LENGTH:
            body = self._clean_page_content(html)

        result.body_content = body
        result.char_count = len(body) if body else 0

        # ── Placeholder kontrolü ──
        if body:
            body_lower = body.lower()
            for kw in PLACEHOLDER_KEYWORDS:
                if kw in body_lower:
                    result.placeholder_detected = kw
                    break

        # ── İçerik geçerlilik kontrolü ──
        if not body or result.char_count < MIN_CONTENT_LENGTH:
            result.is_valid = False
            result.skip_reason = f"too_short ({result.char_count} chars)"

        # ── Canlı sayfanın sidebar'ından yeni URL keşfi ──
        if depth < self.max_depth:
            live_menu = extract_sidebar_menu(html)
            if live_menu.items:
                for link in self._iter_all_links(live_menu):
                    if link.link_type == LinkType.PAGE:
                        clean_url = link.url.split("#")[0]
                        if clean_url and clean_url not in self.visited_urls:
                            if is_allowed_domain(clean_url, self.allowed_domains):
                                result.discovered_urls.append(clean_url)

                    elif link.link_type == LinkType.PDF:
                        if not any(p.url == link.url for p in self._all_discovered_pdfs):
                            self._all_discovered_pdfs.append(link)
                            result.discovered_pdfs.append(link)

                    elif link.link_type in (LinkType.EXTERNAL, LinkType.SUBDOMAIN):
                        if not any(e.url == link.url for e in self._all_external_links):
                            self._all_external_links.append(link)
                            result.external_links.append(link)

        return result

    # ── 5. Tam Scrape Döngüsü ──

    def scrape_all(self, dry_run: bool = False) -> ScrapeReport:
        """
        Blueprint-to-Live tam scrape döngüsü:
          1. Blueprint oku → MenuTree
          2. Hedef URL'leri üret
          3. Her URL'yi canlı fetch + deep parse
          4. Menü haritası Document'ı üret
          5. Kalite raporu oluştur

        Args:
            dry_run: True ise veritabanına yazmaz, sadece raporlar.

        Returns:
            ScrapeReport nesnesi.
        """
        report = ScrapeReport(
            blueprint_path=str(self.blueprint_path),
            category=self.category,
            department=self.department,
        )

        # 1. Blueprint yükle
        tree = self.load_blueprint()
        report.birim_id = tree.birim_id
        report.birim_title = tree.birim_title or self.department

        # 2. Hedef URL'ler
        target_urls = self.build_target_urls()
        report.total_blueprint_urls = len(target_urls)

        logger.info("")
        logger.info("=" * 65)
        logger.info(
            "HARITA GÜDÜMLÜ CANLI SCRAPE BAŞLIYOR — %s",
            report.birim_title or self.blueprint_path.name,
        )
        logger.info("  Blueprint: %s", self.blueprint_path.name)
        logger.info("  BirimID:   %s", report.birim_id)
        logger.info("  Kategori:  %s", self.category)
        logger.info("  Hedef URL: %d", len(target_urls))
        logger.info("  Max depth: %d", self.max_depth)
        logger.info("=" * 65)

        # 3. Canlı fetch + deep parse
        results: list[ParseResult] = []
        all_urls_to_scrape = list(target_urls)

        idx = 0
        while idx < len(all_urls_to_scrape):
            url = all_urls_to_scrape[idx]
            idx += 1

            # URL limiti kontrolü
            if self.url_limit and len(results) >= self.url_limit:
                logger.info("URL limiti (%d) aşıldı, durduruldu.", self.url_limit)
                break

            # Ziyaret kontrolü
            clean_url = url.split("#")[0]
            if clean_url in self.visited_urls:
                continue
            self.visited_urls.add(clean_url)

            logger.info(
                "→ [%d/%d] Fetch: %s",
                len(results) + 1, len(all_urls_to_scrape), url[:90],
            )

            # Rate limit
            time.sleep(self.rate_limit)

            # Fetch
            html = self.fetch_live(url)
            if html is None:
                report.total_failed += 1
                report.failed_urls.append({
                    "url": url, "reason": "fetch_failed",
                })
                logger.warning("  ❌ Fetch başarısız: %s", url[:80])
                continue

            report.total_fetched += 1

            # Deep parse
            parsed = self.deep_parse(html, url, depth=0)

            if not parsed.is_valid:
                report.total_skipped += 1
                report.skipped_urls.append({
                    "url": url,
                    "reason": parsed.skip_reason,
                    "char_count": parsed.char_count,
                })
                logger.warning(
                    "  ⏭ Geçersiz: %s (%s)", url[:60], parsed.skip_reason
                )
                continue

            report.total_valid += 1
            report.total_chars += parsed.char_count
            results.append(parsed)

            logger.info(
                '  ✅ "%s" | %d kar. | %d yeni URL keşfi',
                parsed.title[:45], parsed.char_count, len(parsed.discovered_urls),
            )

            # Keşfedilen yeni URL'leri kuyruğa ekle
            for new_url in parsed.discovered_urls:
                if new_url not in self.visited_urls and new_url not in all_urls_to_scrape:
                    all_urls_to_scrape.append(new_url)

        # 4. Document oluşturma
        documents = self._build_documents(results, tree)
        report.total_documents = len(documents)

        # 5. Kalite raporu
        self._populate_report(report, results, documents)
        self._print_report(report)

        # 6. PDF ve external link raporlama
        report.discovered_pdfs = [
            {"text": p.text, "url": p.url, "type": p.link_type.value}
            for p in self._all_discovered_pdfs
        ]
        report.external_links = [
            {"text": e.text, "url": e.url, "type": e.link_type.value}
            for e in self._all_external_links
        ]

        # 7. Ingestion
        if documents and not dry_run:
            self._ingest(documents)

        return report

    # ── Document Oluşturma ────────────────────────────────────────────────────

    def _build_documents(self, results: list[ParseResult], tree: MenuTree):
        """ParseResult listesini Haystack Document listesine dönüştürür."""
        from haystack import Document

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        documents: list[Document] = []
        birim_id = tree.birim_id

        # ── A. Ana içerik Document'ları ──
        for r in results:
            if not r.is_valid or not r.body_content:
                continue

            source_id = self._generate_source_id(r.url)
            doc_id = hashlib.sha256(
                r.body_content.encode("utf-8")
            ).hexdigest()

            meta = {
                "category": self.category,
                "source_url": r.url,
                "source_type": "web",
                "source_id": source_id,
                "last_updated": now,
                "title": r.title or f"{self.department} — Sayfa",
                "doc_kind": self.doc_kind,
                "language": "tr",
                "department": self.department,
                "contact_unit": self.contact_unit or self.department,
                "contact_info": self.contact_info or "",
            }

            if birim_id:
                meta["birim_id"] = birim_id

            # PDF ve harici link metadata
            if self._all_discovered_pdfs:
                meta["discovered_pdfs"] = [
                    {"text": p.text, "url": p.url}
                    for p in self._all_discovered_pdfs[:20]  # ilk 20
                ]
            if self._all_external_links:
                meta["external_links"] = [
                    {"text": e.text, "url": e.url}
                    for e in self._all_external_links[:10]  # ilk 10
                ]

            documents.append(Document(id=doc_id, content=r.body_content, meta=meta))

        # ── B. Menü haritası Document'ı ──
        menu_text = tree.to_structured_text()
        if menu_text and len(menu_text) > 50:
            menu_source_id = self._generate_source_id(
                f"{BASE_URL}/Birim.aspx?id={birim_id}" if birim_id else str(self.blueprint_path)
            ) + "/menu_haritasi"

            menu_doc_id = hashlib.sha256(menu_text.encode("utf-8")).hexdigest()
            menu_meta = {
                "category": self.category,
                "source_url": f"{BASE_URL}/Birim.aspx?id={birim_id}" if birim_id else "",
                "source_type": "web",
                "source_id": menu_source_id,
                "last_updated": now,
                "title": f"{tree.birim_title or self.department} — Menü Haritası",
                "doc_kind": "menu_haritasi",
                "language": "tr",
                "department": self.department,
                "contact_unit": self.contact_unit or self.department,
                "contact_info": self.contact_info or "",
            }
            if birim_id:
                menu_meta["birim_id"] = birim_id

            documents.append(Document(id=menu_doc_id, content=menu_text, meta=menu_meta))
            logger.info(
                "📋 Menü Haritası Document oluşturuldu: %d karakter", len(menu_text)
            )

        return documents

    # ── İçerik Temizleme ──────────────────────────────────────────────────────

    def _clean_page_content(self, html: str) -> str:
        """
        Tam sayfa HTML'ini temizleyerek ana metni çıkarır.
        Boilerplate kalıplarını kaldırır.
        """
        content = clean_html(html)
        if not content:
            return ""

        for pattern in _BOILERPLATE_PATTERNS:
            content = re.sub(pattern, "", content)

        content = re.sub(r"\n\s*\n+", "\n\n", content)
        content = content.strip()
        return content

    # ── Yardımcı Fonksiyonlar ─────────────────────────────────────────────────

    @staticmethod
    def _generate_source_id(url: str) -> str:
        """URL'den sabit source_id üretir."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        query = parsed.query
        netloc = parsed.netloc.lower().replace("www.", "")
        source = f"{netloc}/{path}" if path else netloc
        if query:
            source += f"?{query}"
        return source

    @staticmethod
    def _iter_all_links(tree: MenuTree):
        """MenuTree'deki tüm linkleri iterate eder."""
        for item in tree.items:
            yield from item.all_links

    # ── Kalite Raporu ─────────────────────────────────────────────────────────

    def _populate_report(
        self, report: ScrapeReport,
        results: list[ParseResult],
        documents,
    ):
        """Rapor metriklerini doldurur."""
        # Metadata doluluk
        fields = ["category", "source_url", "source_type", "source_id",
                  "last_updated", "title", "doc_kind", "department",
                  "contact_unit", "contact_info"]
        completeness = {}
        for f in fields:
            count = sum(
                1 for d in documents
                if d.meta and d.meta.get(f)
            )
            total = len(documents) if documents else 1
            completeness[f] = {
                "count": count,
                "total": total,
                "pct": round(count / total * 100) if total else 0,
            }
        report.metadata_completeness = completeness

        # doc_kind dağılımı
        kind_counts: dict[str, int] = {}
        for d in documents:
            kind = (d.meta or {}).get("doc_kind", "?")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        report.doc_kind_distribution = kind_counts

        # Sayfa sonuçları
        for r in results:
            report.page_results.append({
                "url": r.url,
                "title": r.title,
                "char_count": r.char_count,
                "is_valid": r.is_valid,
                "depth": r.depth,
                "discovered_new_urls": len(r.discovered_urls),
                "placeholder": r.placeholder_detected,
            })

    def _print_report(self, report: ScrapeReport):
        """Raporu terminal'e yazdırır."""
        logger.info("")
        logger.info("=" * 65)
        logger.info("SCRAPE RAPORU — %s", report.birim_title or self.department)
        logger.info("=" * 65)
        logger.info("  Blueprint:        %s", Path(report.blueprint_path).name)
        logger.info("  BirimID:          %s", report.birim_id)
        logger.info("  Hedef URL:        %d", report.total_blueprint_urls)
        logger.info("  Fetch başarılı:   %d", report.total_fetched)
        logger.info("  Geçerli sayfa:    %d", report.total_valid)
        logger.info("  Başarısız:        %d", report.total_failed)
        logger.info("  Atlanan:          %d", report.total_skipped)
        logger.info("  Documents:        %d", report.total_documents)
        logger.info("  Toplam karakter:  %d", report.total_chars)

        # PDF/harici
        logger.info("")
        logger.info("📄 Tespit edilen PDF: %d", len(self._all_discovered_pdfs))
        for p in self._all_discovered_pdfs[:5]:
            logger.info("   • %s → %s", p.text[:40], p.url[:60])
        if len(self._all_discovered_pdfs) > 5:
            logger.info("   ... ve %d tane daha", len(self._all_discovered_pdfs) - 5)

        logger.info("🔗 Harici linkler: %d", len(self._all_external_links))
        for e in self._all_external_links[:5]:
            logger.info("   • [%s] %s → %s", e.link_type.value, e.text[:30], e.url[:50])

        # Metadata doluluk
        logger.info("")
        logger.info("📝 Metadata Doluluk:")
        for field_name, info in report.metadata_completeness.items():
            pct = info["pct"]
            icon = "✅" if pct == 100 else "⚠" if pct >= 80 else "❌"
            logger.info(
                "  %s %-16s : %d/%d (%d%%)",
                icon, field_name, info["count"], info["total"], pct,
            )

        # doc_kind dağılımı
        logger.info("")
        logger.info("📊 doc_kind Dağılımı:")
        for kind, count in report.doc_kind_distribution.items():
            logger.info("  %-16s : %d", kind, count)

        # Başarısız URL'ler
        if report.failed_urls:
            logger.warning("")
            logger.warning("❌ Başarısız URL'ler (%d):", len(report.failed_urls))
            for f in report.failed_urls:
                logger.warning("  %s — %s", f["url"][:70], f["reason"])

        logger.info("=" * 65)

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def _ingest(self, documents):
        """Document listesini veritabanına yükler."""
        from app.ingestion.loader import ingest_documents
        from haystack.document_stores.types import DuplicatePolicy

        logger.info("")
        logger.info("=" * 65)
        logger.info("VERİTABANINA YÜKLEME")
        logger.info("=" * 65)
        logger.info("%d Document yükleniyor...", len(documents))

        written = ingest_documents(
            documents,
            policy=DuplicatePolicy.OVERWRITE,
        )
        logger.info("✅ %d belge yazıldı.", written)
        return written

    # ── JSON Kayıt ────────────────────────────────────────────────────────────

    def save_report_json(self, report: ScrapeReport, output_path: str):
        """Raporu JSON dosyasına kaydeder."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Rapor kaydedildi: %s", output_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GİBTÜ Harita Güdümlü Canlı Scraper (Görev 3.2.7.2)",
    )
    parser.add_argument(
        "--blueprint", required=True,
        help="Blueprint HTML dosya yolu",
    )
    parser.add_argument(
        "--category", default="genel_bilgi",
        help="Belge kategorisi (default: genel_bilgi)",
    )
    parser.add_argument(
        "--department", default="",
        help="Birim/fakülte adı",
    )
    parser.add_argument(
        "--doc-kind", default="genel",
        help="Varsayılan doc_kind (default: genel)",
    )
    parser.add_argument(
        "--contact-unit", default="",
        help="Yönlendirme birimi",
    )
    parser.add_argument(
        "--contact-info", default="",
        help="İletişim bilgisi",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="En fazla bu kadar URL scrape et (test modu)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
        help=f"Maximum recursive derinlik (default: {DEFAULT_MAX_DEPTH})",
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="Veritabanına yükle",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dry-run: DB'ye yazma, sadece raporla",
    )
    parser.add_argument(
        "--save-json", type=str, default=None,
        help="Raporu JSON dosyasına kaydet",
    )
    args = parser.parse_args()

    scraper = MapGuidedScraper(
        blueprint_path=args.blueprint,
        category=args.category,
        department=args.department,
        doc_kind=args.doc_kind,
        contact_unit=args.contact_unit,
        contact_info=args.contact_info,
        max_depth=args.max_depth,
        url_limit=args.limit,
    )

    # Scrape
    is_dry = args.dry_run or not args.ingest
    report = scraper.scrape_all(dry_run=is_dry)

    # JSON kaydet
    json_path = args.save_json or str(
        Path(__file__).resolve().parent / "map_guided_output.json"
    )
    scraper.save_report_json(report, json_path)

    logger.info("")
    logger.info(
        "🏁 Görev 3.2.7.2 — Harita Güdümlü Scrape tamamlandı: %d Document",
        report.total_documents,
    )

    if is_dry and not args.ingest:
        logger.info(
            "💡 DB'ye yüklemek için: --ingest bayrağını ekleyin"
        )


if __name__ == "__main__":
    main()
