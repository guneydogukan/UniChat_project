"""
UniChat — Görev 3.2.6: İletişim ve Rehber Sayfaları Scraping

Genel iletişim, SSS, harita, telefon rehberi, sosyal ağlar, RİMER ve
Kurumsal İletişim Koordinatörlüğü (kik) sayfalarını scrape eder.

Hedef sayfalar (slug tabanlı):
  iletisim, sss, harita, telefonrehberi, sosyalag, rimer

Birim tabanlı (kik — Kurumsal İletişim Koordinatörlüğü, BirimID=76):
  Birim.aspx?id=76  (ana sayfa)
  + ilgili alt sayfalar

Metadata:
  category : yonlendirme
  doc_kind : iletisim
  contact_unit + contact_info : zorunlu

Kullanım:
    python -m scrapers.scrape_iletisim
    python -m scrapers.scrape_iletisim --ingest
    python -m scrapers.scrape_iletisim --ingest --dry-run
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

# ── GİBTÜ Genel İletişim Bilgileri (keşif raporundan — Bölüm 7.4) ──
GIBTU_CONTACT_INFO = (
    "Tel: +90 342 909 75 00 | "
    "Faks: 0850 258 98 00 | "
    "E-posta: info@gibtu.edu.tr | "
    "KEP: gibtuni@hs01.kep.tr | "
    "Adres: Beştepe Mah. Mustafa Bencan Cad. 6/4, 27010 Şahinbey/Gaziantep"
)

# ── İletişim / Rehber Sayfaları URL Haritası ──
# (slug_or_path, contact_unit, contact_info, doc_kind, açıklama)
ILETISIM_PAGES = [
    # Slug tabanlı statik sayfalar
    (
        "iletisim",
        "Genel İletişim",
        GIBTU_CONTACT_INFO,
        "iletisim",
        "Genel iletişim bilgileri sayfası",
    ),
    (
        "sss",
        "Genel İletişim",
        GIBTU_CONTACT_INFO,
        "iletisim",
        "Sıkça Sorulan Sorular (SSS)",
    ),
    (
        "harita",
        "Genel İletişim",
        GIBTU_CONTACT_INFO,
        "iletisim",
        "Kampüs haritası / konum bilgisi",
    ),
    (
        "telefonrehberi",
        "Genel İletişim",
        GIBTU_CONTACT_INFO,
        "iletisim",
        "Telefon rehberi",
    ),
    (
        "sosyalag",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Sosyal ağlarımız (sosyal medya hesapları)",
    ),
    (
        "rimer",
        "RİMER (Rektörlük İletişim Merkezi)",
        GIBTU_CONTACT_INFO,
        "iletisim",
        "RİMER — Rektörlük İletişim Merkezi",
    ),
    # Birim tabanlı: Kurumsal İletişim Koordinatörlüğü (BirimID=76)
    (
        "Birim.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü ana sayfası",
    ),
    (
        "BirimYonetim.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — Yönetim",
    ),
    (
        "BirimMisyon.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — Misyon",
    ),
    (
        "BirimVizyon.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — Vizyon",
    ),
    (
        "BirimAkademikPersonel.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — Akademik Personel",
    ),
    (
        "BirimIdariPersonel.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — İdari Personel",
    ),
    (
        "BirimForm.aspx?id=76",
        "Kurumsal İletişim Koordinatörlüğü",
        "kik@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "iletisim",
        "Kurumsal İletişim Koordinatörlüğü — Formlar",
    ),
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
    query = parsed.query
    netloc = parsed.netloc.lower().replace("www.", "")
    source = f"{netloc}/{path}" if path else netloc
    if query:
        source += f"?{query}"
    return source


def scrape_iletisim_pages() -> list[dict]:
    """Tüm İletişim ve Rehber sayfalarını scrape eder."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results = []
    failed = []

    logger.info("=" * 60)
    logger.info("İletişim ve Rehber sayfaları scraping başlıyor (%d sayfa)", len(ILETISIM_PAGES))
    logger.info("=" * 60)

    for slug_or_path, contact_unit, contact_info, doc_kind, description in ILETISIM_PAGES:
        url = f"{BASE_URL}/{slug_or_path}"
        logger.info("→ Scraping: %s (%s)", url, description)

        time.sleep(RATE_LIMIT_DELAY)

        html = fetch_page(url, session)
        if html is None:
            failed.append({"slug": slug_or_path, "url": url, "reason": "fetch_failed"})
            continue

        content = clean_html(html)
        title = extract_gibtu_title(html)

        if not content or len(content.strip()) < 20:
            logger.warning("⚠ Boş veya çok kısa içerik: %s (%d karakter)", slug_or_path, len(content))
            failed.append({"slug": slug_or_path, "url": url, "reason": "empty_content"})
            continue

        result = {
            "url": url,
            "slug": slug_or_path,
            "title": title or f"İletişim — {description}",
            "content": content,
            "doc_kind": doc_kind,
            "contact_unit": contact_unit,
            "contact_info": contact_info,
            "char_count": len(content),
            "description": description,
        }
        results.append(result)

        logger.info(
            "  ✅ \"%s\" | %d karakter | doc_kind=%s | contact_unit=%s",
            result["title"][:60], result["char_count"], doc_kind, contact_unit[:30],
        )

    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef: %d", len(ILETISIM_PAGES))
    logger.info("  Başarılı:     %d", len(results))
    logger.info("  Başarısız:    %d", len(failed))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results


def quality_report(results: list[dict]) -> dict:
    """Kalite kontrol raporu üretir."""
    report = {
        "total_pages": len(results),
        "doc_kind_distribution": {},
        "contact_unit_distribution": {},
        "char_count_stats": {},
        "issues": [],
    }

    char_counts = []
    kind_counts = {}
    unit_counts = {}

    for r in results:
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

        unit = r["contact_unit"]
        unit_counts[unit] = unit_counts.get(unit, 0) + 1

        char_counts.append(r["char_count"])

        content_lower = r["content"].lower()
        for kw in ["lorem ipsum", "örnek metin", "içerik eklenecek", "yapım aşamasında", "coming soon"]:
            if kw in content_lower:
                report["issues"].append({"slug": r["slug"], "issue": f"Placeholder: '{kw}'"})

        if not r["title"] or r["title"] == "Başlıksız":
            report["issues"].append({"slug": r["slug"], "issue": "Başlık eksik"})

        if r["char_count"] < 50:
            report["issues"].append({"slug": r["slug"], "issue": f"Çok kısa ({r['char_count']} kar.)"})

        # contact_unit ve contact_info zorunluluk kontrolü
        if not r.get("contact_unit"):
            report["issues"].append({"slug": r["slug"], "issue": "contact_unit eksik (ZORUNLU)"})
        if not r.get("contact_info"):
            report["issues"].append({"slug": r["slug"], "issue": "contact_info eksik (ZORUNLU)"})

    report["doc_kind_distribution"] = kind_counts
    report["contact_unit_distribution"] = unit_counts
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

    logger.info("📋 contact_unit Dağılımı:")
    for unit, count in report["contact_unit_distribution"].items():
        logger.info("  %-40s : %d", unit, count)

    stats = report["char_count_stats"]
    if stats:
        logger.info("📏 İçerik Uzunluğu:")
        logger.info(
            "  Min: %d | Max: %d | Ort: %d | Toplam: %d",
            stats["min"], stats["max"], stats["avg"], stats["total"],
        )

    issues = report["issues"]
    if issues:
        logger.warning("⚠ Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("✅ Sorun bulunamadı — tüm veriler temiz!")
    logger.info("=" * 60)


def build_documents(results: list[dict]):
    """Scrape sonuçlarını Haystack Document listesine dönüştürür."""
    from haystack import Document

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    documents = []

    for r in results:
        doc_id = hashlib.sha256(r["content"].encode("utf-8")).hexdigest()
        meta = {
            "category": "yonlendirme",
            "source_url": r["url"],
            "source_type": "web",
            "source_id": generate_source_id(r["url"]),
            "last_updated": now,
            "title": r["title"],
            "doc_kind": r["doc_kind"],
            "language": "tr",
            "department": "Genel",
            "contact_unit": r["contact_unit"],
            "contact_info": r["contact_info"],
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
            "contact_unit": r["contact_unit"],
            "contact_info": r["contact_info"][:80] + "..." if len(r["contact_info"]) > 80 else r["contact_info"],
            "char_count": r["char_count"],
            "content_preview": r["content"][:300] + "..." if len(r["content"]) > 300 else r["content"],
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Sonuçlar kaydedildi: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="GİBTÜ İletişim ve Rehber Sayfaları Scraper (Görev 3.2.6)")
    parser.add_argument("--ingest", action="store_true", help="Veritabanına yükle")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run modu")
    parser.add_argument("--save-json", type=str, default=None, help="JSON çıktı dosyası")
    args = parser.parse_args()

    # 1. Scrape
    results = scrape_iletisim_pages()
    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results)
    print_quality_report(report)

    # 3. JSON kaydet (varsayılan olarak her zaman kaydet)
    json_path = args.save_json or str(Path(__file__).resolve().parent / "iletisim_output.json")
    save_results_json(results, json_path)

    # 4. Sayfa özetleri
    logger.info("")
    logger.info("SAYFA ÖZETLERİ")
    logger.info("-" * 60)
    for r in results:
        preview = r["content"][:120].replace("\n", " ")
        logger.info(
            "📄 %-28s | %-25s | %5d kar. | %s...",
            r["slug"][:28], r["title"][:25], r["char_count"], preview[:60],
        )

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
        logger.info("💡 DB'ye yüklemek için: python -m scrapers.scrape_iletisim --ingest")

    logger.info("🏁 Görev 3.2.6 — İletişim ve Rehber scraping tamamlandı.")


if __name__ == "__main__":
    main()
