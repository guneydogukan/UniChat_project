"""
UniChat — Görev 3.2.3: Kurumsal Kimlik Sayfaları Scraping

Üniversite genel bilgi / kurumsal kimlik sayfalarını scrape eder:
  kurumsalkimlik, tarihce, kurumhiyerarsisi, etikdegerlerimiz,
  temeldegerlerimiz, oz, misyon, vizyon, nedengibtu,
  tanitimfilmi, galeri, sayilarlagibtu, siteharitasi, Logo

Kullanım:
    python -m scrapers.scrape_kurumsal
    python -m scrapers.scrape_kurumsal --ingest
    python -m scrapers.scrape_kurumsal --ingest --dry-run
"""

import argparse
import hashlib
import json
import logging
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


# ── GİBTÜ'ye özel başlık çıkarma ──

def extract_gibtu_title(html: str) -> str:
    """GİBTÜ sayfalarından başlık çıkarır (span.page_title > div.card-title > h1 > title)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    page_title = soup.find("span", class_="page_title")
    if page_title and page_title.get_text(strip=True):
        return page_title.get_text(strip=True)

    card_title = soup.find("div", class_="card-title")
    if card_title and card_title.get_text(strip=True):
        return card_title.get_text(strip=True)

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
RATE_LIMIT_DELAY = 1.5

# ── Kurumsal Kimlik URL Haritası ──
# (slug, doc_kind, açıklama)
KURUMSAL_PAGES = [
    ("kurumsalkimlik",    "tanitim",  "Kurumsal Kimlik ana sayfası"),
    ("tarihce",           "tanitim",  "Üniversite tarihçesi"),
    ("kurumhiyerarsisi",  "tanitim",  "Teşkilat şeması / kurum hiyerarşisi"),
    ("etikdegerlerimiz",  "tanitim",  "Etik değerler"),
    ("temeldegerlerimiz", "tanitim",  "Temel değerler"),
    ("oz",                "tanitim",  "Üniversite özü"),
    ("misyon",            "tanitim",  "Misyon"),
    ("vizyon",            "tanitim",  "Vizyon"),
    ("nedengibtu",        "tanitim",  "Neden GİBTÜ?"),
    ("tanitimfilmi",      "tanitim",  "Tanıtım filmi sayfası"),
    ("galeri",            "tanitim",  "Fotoğraf galerisi"),
    ("sayilarlagibtu",    "tanitim",  "Sayılarla GİBTÜ"),
    ("siteharitasi",      "rehber",   "Site haritası"),
    ("Logo",              "tanitim",  "Logo ve kurumsal görsel kimlik"),
]


def fetch_page(url: str, session: requests.Session) -> str | None:
    """URL'den HTML çeker — retry + rate limit."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
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


def generate_source_id(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    netloc = parsed.netloc.lower().replace("www.", "")
    return f"{netloc}/{path}" if path else netloc


def scrape_kurumsal_pages() -> list[dict]:
    """Tüm Kurumsal Kimlik sayfalarını scrape eder."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results = []
    failed = []

    logger.info("=" * 60)
    logger.info("Kurumsal Kimlik sayfaları scraping başlıyor (%d sayfa)", len(KURUMSAL_PAGES))
    logger.info("=" * 60)

    for slug, expected_kind, description in KURUMSAL_PAGES:
        url = f"{BASE_URL}/{slug}"
        logger.info("→ Scraping: %s (%s)", url, description)

        time.sleep(RATE_LIMIT_DELAY)

        html = fetch_page(url, session)
        if html is None:
            failed.append({"slug": slug, "url": url, "reason": "fetch_failed"})
            continue

        content = clean_html(html)
        title = extract_gibtu_title(html)

        if not content or len(content.strip()) < 20:
            logger.warning("⚠ Boş veya çok kısa içerik: %s (%d karakter)", slug, len(content))
            failed.append({"slug": slug, "url": url, "reason": "empty_content"})
            continue

        result = {
            "url": url,
            "slug": slug,
            "title": title or f"Kurumsal — {description}",
            "content": content,
            "doc_kind": expected_kind,
            "char_count": len(content),
            "description": description,
        }
        results.append(result)

        logger.info(
            "  ✅ \"%s\" | %d karakter | doc_kind=%s",
            result["title"][:60], result["char_count"], expected_kind,
        )

    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef: %d", len(KURUMSAL_PAGES))
    logger.info("  Başarılı:     %d", len(results))
    logger.info("  Başarısız:    %d", len(failed))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results


def quality_report(results: list[dict]) -> dict:
    report = {
        "total_pages": len(results),
        "doc_kind_distribution": {},
        "char_count_stats": {},
        "issues": [],
    }

    char_counts = []
    kind_counts = {}

    for r in results:
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        char_counts.append(r["char_count"])

        content_lower = r["content"].lower()
        for kw in ["lorem ipsum", "örnek metin", "içerik eklenecek", "yapım aşamasında", "coming soon"]:
            if kw in content_lower:
                report["issues"].append({"slug": r["slug"], "issue": f"Placeholder: '{kw}'"})

        if not r["title"] or r["title"] == "Başlıksız":
            report["issues"].append({"slug": r["slug"], "issue": "Başlık eksik"})

        if r["char_count"] < 50:
            report["issues"].append({"slug": r["slug"], "issue": f"Çok kısa ({r['char_count']} kar.)"})

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
    logger.info("")
    logger.info("=" * 60)
    logger.info("KALİTE KONTROL RAPORU")
    logger.info("=" * 60)
    logger.info("Toplam sayfa: %d", report["total_pages"])

    logger.info("📊 doc_kind Dağılımı:")
    for kind, count in report["doc_kind_distribution"].items():
        logger.info("  %-12s : %d", kind, count)

    stats = report["char_count_stats"]
    if stats:
        logger.info("📏 İçerik Uzunluğu:")
        logger.info("  Min: %d | Max: %d | Ort: %d | Toplam: %d", stats["min"], stats["max"], stats["avg"], stats["total"])

    issues = report["issues"]
    if issues:
        logger.warning("⚠ Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("✅ Sorun bulunamadı — tüm veriler temiz!")
    logger.info("=" * 60)


def build_documents(results: list[dict]):
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
            "department": "Genel",
            "contact_unit": "Kurumsal İletişim",
            "contact_info": "info@gibtu.edu.tr | +90 342 909 75 00",
        }
        documents.append(Document(id=doc_id, content=r["content"], meta=meta))
    return documents


def save_results_json(results: list[dict], output_path: str):
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
    parser = argparse.ArgumentParser(description="GİBTÜ Kurumsal Kimlik scraper (Görev 3.2.3)")
    parser.add_argument("--ingest", action="store_true", help="Veritabanına yükle")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run modu")
    parser.add_argument("--save-json", type=str, default=None, help="JSON çıktı dosyası")
    args = parser.parse_args()

    # 1. Scrape
    results = scrape_kurumsal_pages()
    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results)
    print_quality_report(report)

    # 3. JSON kaydet
    if args.save_json:
        save_results_json(results, args.save_json)

    # 4. Sayfa özetleri
    logger.info("")
    logger.info("SAYFA ÖZETLERİ")
    logger.info("-" * 60)
    for r in results:
        preview = r["content"][:120].replace("\n", " ")
        logger.info("📄 %-22s | %-25s | %5d kar. | %s...", r["slug"], r["title"][:25], r["char_count"], preview[:60])

    # 5. Ingestion
    if args.ingest:
        logger.info("")
        logger.info("=" * 60)
        logger.info("VERİTABANINA YÜKLEME")
        logger.info("=" * 60)
        documents = build_documents(results)
        logger.info("%d Document oluşturuldu.", len(documents))

        from app.ingestion.loader import ingest_documents
        from haystack.document_stores.types import DuplicatePolicy
        written = ingest_documents(documents, policy=DuplicatePolicy.OVERWRITE, dry_run=args.dry_run)
        logger.info("✅ %d belge yazıldı (dry_run=%s).", written, args.dry_run)
    else:
        logger.info("")
        logger.info("💡 DB'ye yüklemek için: python -m scrapers.scrape_kurumsal --ingest")

    logger.info("🏁 Görev 3.2.3 — Kurumsal Kimlik scraping tamamlandı.")


if __name__ == "__main__":
    main()
