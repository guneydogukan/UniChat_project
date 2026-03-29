"""
UniChat — Görev 3.2.2: Rektörlük ve Yönetim Sayfaları Scraping

Rektörlük menüsü altındaki tüm sayfaları kontrollü olarak scrape eder:
  - Rektor, rektorunmesaji, RektorYardimcilari, RektorDanismanlari
  - senato, yonetimkurulu, kalitekurulu

Kullanım:
    # Sadece scrape + kalite raporu (DB'ye yazmadan):
    python -m scrapers.scrape_rektorluk

    # DB'ye yaz:
    python -m scrapers.scrape_rektorluk --ingest

    # Dry-run (DB yazma simülasyonu):
    python -m scrapers.scrape_rektorluk --ingest --dry-run
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Proje kök dizinini path'e ekle
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from scrapers.utils import clean_html, extract_title, normalize_url


def extract_gibtu_title(html: str) -> str:
    """
    GİBTÜ sayfalarından başlık çıkarır.

    GİBTÜ'de sayfa başlığı <span class="page_title"> içinde bulunur.
    Fallback: genel extract_title (h1 > title).
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")

    # GİBTÜ'ye özel: span.page_title
    page_title = soup.find("span", class_="page_title")
    if page_title and page_title.get_text(strip=True):
        return page_title.get_text(strip=True)

    # Ardından div.card-title (bazı sayfalarda ikincil başlık)
    card_title = soup.find("div", class_="card-title")
    if card_title and card_title.get_text(strip=True):
        return card_title.get_text(strip=True)

    # Genel fallback
    return extract_title(html)

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Sabitler ──
BASE_URL = "https://www.gibtu.edu.tr"
USER_AGENT = (
    "Mozilla/5.0 (compatible; UniChatBot/1.0; "
    "+https://github.com/unichat-project)"
)
REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 1.5  # saniye — sunucuya nazik ol

# ── Rektörlük URL Haritası ──
# Her sayfa: (slug, beklenen_doc_kind, açıklama)
REKTORLUK_PAGES = [
    ("Rektor",              "yonetim",  "Rektör tanıtım sayfası"),
    ("rektorunmesaji",      "tanitim",  "Rektörün mesajı"),
    ("RektorYardimcilari",  "yonetim",  "Rektör yardımcıları listesi"),
    ("RektorDanismanlari",  "yonetim",  "Rektör danışmanları listesi"),
    ("senato",              "yonetim",  "Üniversite Senatosu üye listesi"),
    ("yonetimkurulu",       "yonetim",  "Yönetim Kurulu üye listesi"),
    ("kalitekurulu",        "yonetim",  "Kalite Komisyonu üye listesi"),
]

# ── İçerik Türü Sınıflandırma Kuralları ──
# slug → doc_kind eşlemesi (keşif raporu + görev tanımından)
DOC_KIND_MAP = {
    "Rektor":              "yonetim",
    "rektorunmesaji":      "tanitim",
    "RektorYardimcilari":  "yonetim",
    "RektorDanismanlari":  "yonetim",
    "senato":              "yonetim",
    "yonetimkurulu":       "yonetim",
    "kalitekurulu":        "yonetim",
}


def fetch_page(url: str, session: requests.Session) -> str | None:
    """URL'den HTML çeker — retry + rate limit."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("Fetch denemesi %d/%d: %s", attempt, max_retries, url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            # Sunucu charset bildirdiyse onu kullan (GİBTÜ: iso-8859-9)
            # Yalnızca charset bildirilmediyse apparent_encoding'e düş
            if not resp.encoding or resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            logger.warning("HTTP %s — deneme %d/%d: %s", status, attempt, max_retries, url)
            if e.response is not None and 400 <= e.response.status_code < 500:
                logger.error("Kalıcı HTTP hatası %s, atlanıyor: %s", status, url)
                return None
        except requests.exceptions.ConnectionError:
            logger.warning("Bağlantı hatası — deneme %d/%d: %s", attempt, max_retries, url)
        except requests.exceptions.Timeout:
            logger.warning("Zaman aşımı — deneme %d/%d: %s", attempt, max_retries, url)
        except requests.exceptions.RequestException as e:
            logger.error("Beklenmeyen hata: %s — %s", e, url)
            return None

        if attempt < max_retries:
            time.sleep(2 * attempt)

    logger.error("Tüm denemeler başarısız: %s", url)
    return None


def classify_content_type(slug: str, content: str) -> str:
    """
    İçerik türünü belirle: tanitim / iletisim / yonetim.
    Önce slug tabanlı eşleme, ardından içerik analizi.
    """
    # Slug tabanlı kesin eşleme
    if slug in DOC_KIND_MAP:
        return DOC_KIND_MAP[slug]

    # Fallback: içerik analizi
    content_lower = content.lower()
    if any(kw in content_lower for kw in ["telefon", "e-posta", "adres", "faks"]):
        return "iletisim"
    if any(kw in content_lower for kw in ["mesaj", "değerli", "hoş geldiniz"]):
        return "tanitim"
    return "yonetim"


def generate_source_id(url: str) -> str:
    """URL'den sabit source_id üretir."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    netloc = parsed.netloc.lower().replace("www.", "")
    return f"{netloc}/{path}" if path else netloc


def scrape_rektorluk_pages() -> list[dict]:
    """
    Tüm Rektörlük sayfalarını scrape eder.

    Returns:
        Liste: Her eleman {url, slug, title, content, doc_kind, char_count} dict.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results = []
    failed = []

    logger.info("=" * 60)
    logger.info("Rektörlük sayfaları scraping başlıyor (%d sayfa)", len(REKTORLUK_PAGES))
    logger.info("=" * 60)

    for slug, expected_kind, description in REKTORLUK_PAGES:
        url = f"{BASE_URL}/{slug}"
        logger.info("→ Scraping: %s (%s)", url, description)

        # Rate limit
        time.sleep(RATE_LIMIT_DELAY)

        # Fetch
        html = fetch_page(url, session)
        if html is None:
            failed.append({"slug": slug, "url": url, "reason": "fetch_failed"})
            continue

        # Parse
        content = clean_html(html)
        title = extract_gibtu_title(html)

        if not content or len(content.strip()) < 20:
            logger.warning("⚠ Boş veya çok kısa içerik: %s (%d karakter)", slug, len(content))
            failed.append({"slug": slug, "url": url, "reason": "empty_content"})
            continue

        # İçerik türü sınıflandırma
        doc_kind = classify_content_type(slug, content)

        result = {
            "url": url,
            "slug": slug,
            "title": title or f"Rektörlük — {description}",
            "content": content,
            "doc_kind": doc_kind,
            "char_count": len(content),
            "description": description,
        }
        results.append(result)

        logger.info(
            "  ✅ Başarılı: \"%s\" | %d karakter | doc_kind=%s",
            result["title"][:60], result["char_count"], doc_kind,
        )

    # Özet
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef: %d", len(REKTORLUK_PAGES))
    logger.info("  Başarılı:     %d", len(results))
    logger.info("  Başarısız:    %d", len(failed))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results


def quality_report(results: list[dict]) -> dict:
    """
    Scrape sonuçları üzerinde kalite kontrol raporu üretir.

    Kontroller:
    - Metadata doluluk (title, doc_kind, content)
    - Placeholder/boş içerik
    - İçerik uzunluğu dağılımı
    - doc_kind dağılımı
    """
    report = {
        "total_pages": len(results),
        "doc_kind_distribution": {},
        "char_count_stats": {},
        "issues": [],
    }

    char_counts = []
    kind_counts = {}

    for r in results:
        # doc_kind dağılımı
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

        # İçerik uzunluğu
        char_counts.append(r["char_count"])

        # Placeholder kontrolü
        content_lower = r["content"].lower()
        placeholder_keywords = [
            "lorem ipsum", "örnek metin", "içerik eklenecek", "yapım aşamasında",
            "bu sayfa", "coming soon", "under construction",
        ]
        for kw in placeholder_keywords:
            if kw in content_lower:
                report["issues"].append({
                    "slug": r["slug"],
                    "issue": f"Olası placeholder içerik: '{kw}' bulundu",
                })

        # Başlık kontrolü
        if not r["title"] or r["title"] == "Başlıksız":
            report["issues"].append({
                "slug": r["slug"],
                "issue": "Başlık eksik veya 'Başlıksız'",
            })

        # Çok kısa içerik
        if r["char_count"] < 100:
            report["issues"].append({
                "slug": r["slug"],
                "issue": f"Çok kısa içerik ({r['char_count']} karakter)",
            })

    report["doc_kind_distribution"] = kind_counts

    if char_counts:
        report["char_count_stats"] = {
            "min": min(char_counts),
            "max": max(char_counts),
            "avg": round(sum(char_counts) / len(char_counts)),
            "total": sum(char_counts),
        }

    return report


def print_quality_report(report: dict):
    """Kalite raporunu güzel formatta yazdırır."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("KALİTE KONTROL RAPORU")
    logger.info("=" * 60)
    logger.info("Toplam sayfa: %d", report["total_pages"])
    logger.info("")

    logger.info("📊 doc_kind Dağılımı:")
    for kind, count in report["doc_kind_distribution"].items():
        logger.info("  %-12s : %d", kind, count)

    stats = report["char_count_stats"]
    if stats:
        logger.info("")
        logger.info("📏 İçerik Uzunluğu İstatistikleri:")
        logger.info("  Min:     %d karakter", stats["min"])
        logger.info("  Max:     %d karakter", stats["max"])
        logger.info("  Ort:     %d karakter", stats["avg"])
        logger.info("  Toplam:  %d karakter", stats["total"])

    issues = report["issues"]
    logger.info("")
    if issues:
        logger.warning("⚠ Bulunan Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("✅ Sorun bulunamadı — tüm veriler temiz!")

    logger.info("=" * 60)


def build_documents(results: list[dict]):
    """
    Scrape sonuçlarını Haystack Document listesine dönüştürür.
    """
    from haystack import Document

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    documents = []

    for r in results:
        doc_id = hashlib.sha256(r["content"].encode("utf-8")).hexdigest()

        meta = {
            "category": "genel_bilgi",
            "source_url": r["url"],
            "source_type": "web",
            "source_id": generate_source_id(r["url"]),
            "last_updated": now,
            "title": r["title"],
            "doc_kind": r["doc_kind"],
            "language": "tr",
            "department": "Rektörlük",
            "contact_unit": "Rektörlük",
            "contact_info": "info@gibtu.edu.tr | +90 342 909 75 00",
        }

        documents.append(Document(id=doc_id, content=r["content"], meta=meta))

    return documents


def save_results_json(results: list[dict], output_path: str):
    """Scrape sonuçlarını JSON olarak kaydeder (debug/arşiv için)."""
    output = []
    for r in results:
        output.append({
            "url": r["url"],
            "slug": r["slug"],
            "title": r["title"],
            "doc_kind": r["doc_kind"],
            "char_count": r["char_count"],
            "content_preview": r["content"][:300] + "..." if len(r["content"]) > 300 else r["content"],
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Sonuçlar kaydedildi: %s", output_path)


def main():
    parser = argparse.ArgumentParser(
        description="GİBTÜ Rektörlük sayfalarını scrape eder (Görev 3.2.2)"
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="Scrape sonuçlarını veritabanına yükle",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dry-run modu (veritabanına yazmadan rapor ver)",
    )
    parser.add_argument(
        "--save-json", type=str, default=None,
        help="Sonuçları JSON dosyasına kaydet (ör: rektorluk_output.json)",
    )
    args = parser.parse_args()

    # 1. Scrape
    results = scrape_rektorluk_pages()

    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results)
    print_quality_report(report)

    # 3. JSON kaydet (isteğe bağlı)
    if args.save_json:
        save_results_json(results, args.save_json)

    # 4. Her sayfanın kısa özeti
    logger.info("")
    logger.info("=" * 60)
    logger.info("SAYFA ÖZETLERİ")
    logger.info("=" * 60)
    for r in results:
        logger.info("")
        logger.info("📄 %s", r["slug"])
        logger.info("   URL:      %s", r["url"])
        logger.info("   Başlık:   %s", r["title"][:80])
        logger.info("   Tür:      %s", r["doc_kind"])
        logger.info("   Karakter: %d", r["char_count"])
        # İçerik önizleme (ilk 150 karakter)
        preview = r["content"][:150].replace("\n", " ")
        logger.info("   Önizleme: %s...", preview)

    # 5. Ingestion (isteğe bağlı)
    if args.ingest:
        logger.info("")
        logger.info("=" * 60)
        logger.info("VERİTABANINA YÜKLEME")
        logger.info("=" * 60)

        documents = build_documents(results)
        logger.info("%d Document oluşturuldu.", len(documents))

        from app.ingestion.loader import ingest_documents
        from haystack.document_stores.types import DuplicatePolicy

        written = ingest_documents(
            documents,
            policy=DuplicatePolicy.OVERWRITE,
            dry_run=args.dry_run,
        )
        logger.info("✅ %d belge yazıldı (dry_run=%s).", written, args.dry_run)
    else:
        logger.info("")
        logger.info("💡 Veritabanına yüklemek için: python -m scrapers.scrape_rektorluk --ingest")
        logger.info("💡 Dry-run için:               python -m scrapers.scrape_rektorluk --ingest --dry-run")

    logger.info("")
    logger.info("🏁 Görev 3.2.2 — Rektörlük scraping tamamlandı.")


if __name__ == "__main__":
    main()
