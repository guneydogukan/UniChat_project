"""
UniChat — Görev 3.2.4: Mevzuat Sayfaları Scraping

Yönetmelik, yönerge, usul-esas, KVKK, İSO 27001 sayfalarını scrape eder.
Bu sayfalar büyük olasılıkla PDF bağlantıları içerir — PDF linkleri ayrıca
raporlanır ve isteğe bağlı olarak indirilip pdf_parser ile işlenir.

Kullanım:
    python -m scrapers.scrape_mevzuat
    python -m scrapers.scrape_mevzuat --ingest
    python -m scrapers.scrape_mevzuat --ingest --dry-run
    python -m scrapers.scrape_mevzuat --download-pdfs   # PDF'leri indir
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from scrapers.utils import clean_html, extract_title, normalize_url

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

PDF_DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "pdfs" / "mevzuat_web"


def extract_gibtu_title(html: str) -> str:
    """GİBTÜ sayfalarından başlık çıkarır."""
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


# ── Mevzuat URL Haritası ──
MEVZUAT_PAGES = [
    ("yonetmelik", "yonetmelik", "egitim",      "Yönetmelikler listesi"),
    ("yonerge",    "yonerge",    "egitim",      "Yönergeler listesi"),
    ("usulesas",   "yonetmelik", "egitim",      "Usuller ve Esaslar listesi"),
    ("kvkk",       "yonetmelik", "genel_bilgi", "KVKK (Kişisel Verilerin Korunması)"),
    ("iso27001",   "yonetmelik", "genel_bilgi", "İSO 27001 Bilgi Güvenliği"),
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
    return None


def extract_pdf_links(html: str, page_url: str) -> list[dict]:
    """
    HTML'den PDF bağlantılarını çıkarır.

    Returns:
        [{url, text, filename}, ...]
    """
    soup = BeautifulSoup(html, "lxml")
    pdf_links = []
    seen_urls = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # PDF bağlantı tespiti: .pdf uzantısı veya Medya/GibtuDosya kalıbı
        if href.lower().endswith(".pdf") or "GibtuDosya" in href or "gibtu" in href.lower() and ".pdf" in href.lower():
            full_url = urljoin(page_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            link_text = a_tag.get_text(strip=True)
            # Dosya adını URL'den çıkar
            parsed = urlparse(full_url)
            filename = os.path.basename(parsed.path)

            pdf_links.append({
                "url": full_url,
                "text": link_text or filename,
                "filename": filename,
            })

    return pdf_links


def generate_source_id(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    netloc = parsed.netloc.lower().replace("www.", "")
    return f"{netloc}/{path}" if path else netloc


def download_pdf(url: str, session: requests.Session, output_dir: Path) -> str | None:
    """PDF'i indirir ve dosya yolunu döndürür."""
    try:
        resp = session.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        # Dosya adı
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if not filename.endswith(".pdf"):
            filename += ".pdf"

        # Güvenli dosya adı
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filepath = output_dir / filename

        # Zaten varsa atla
        if filepath.exists():
            logger.info("  ⏭ PDF zaten mevcut: %s", filename)
            return str(filepath)

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info("  📥 PDF indirildi: %s (%d KB)", filename, filepath.stat().st_size // 1024)
        return str(filepath)

    except Exception as e:
        logger.error("  ❌ PDF indirilemedi: %s — %s", url, e)
        return None


def scrape_mevzuat_pages(session: requests.Session) -> tuple[list[dict], list[dict]]:
    """
    Mevzuat sayfalarını scrape eder ve PDF bağlantılarını toplar.

    Returns:
        (page_results, all_pdf_links)
    """
    results = []
    all_pdf_links = []
    failed = []

    logger.info("=" * 60)
    logger.info("Mevzuat sayfaları scraping başlıyor (%d sayfa)", len(MEVZUAT_PAGES))
    logger.info("=" * 60)

    for slug, doc_kind, category, description in MEVZUAT_PAGES:
        url = f"{BASE_URL}/{slug}"
        logger.info("→ Scraping: %s (%s)", url, description)

        time.sleep(RATE_LIMIT_DELAY)

        html = fetch_page(url, session)
        if html is None:
            failed.append({"slug": slug, "url": url, "reason": "fetch_failed"})
            continue

        # PDF bağlantılarını çıkar
        pdf_links = extract_pdf_links(html, url)
        for pl in pdf_links:
            pl["source_page"] = slug
            pl["doc_kind"] = doc_kind
            pl["category"] = category
        all_pdf_links.extend(pdf_links)

        if pdf_links:
            logger.info("  📎 %d PDF bağlantısı bulundu", len(pdf_links))
            for pl in pdf_links[:5]:  # İlk 5'ini göster
                logger.info("     • %s", pl["text"][:70])
            if len(pdf_links) > 5:
                logger.info("     ... ve %d tane daha", len(pdf_links) - 5)

        # Sayfa içeriği
        content = clean_html(html)
        title = extract_gibtu_title(html)

        if not content or len(content.strip()) < 20:
            logger.warning("⚠ Boş içerik: %s", slug)
            failed.append({"slug": slug, "url": url, "reason": "empty_content"})
            continue

        result = {
            "url": url,
            "slug": slug,
            "title": title or f"Mevzuat — {description}",
            "content": content,
            "doc_kind": doc_kind,
            "category": category,
            "char_count": len(content),
            "description": description,
            "pdf_count": len(pdf_links),
        }
        results.append(result)

        logger.info(
            "  ✅ \"%s\" | %d kar. | %d PDF | doc_kind=%s",
            result["title"][:50], result["char_count"], len(pdf_links), doc_kind,
        )

    # Özet
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef sayfa: %d", len(MEVZUAT_PAGES))
    logger.info("  Başarılı:           %d", len(results))
    logger.info("  Başarısız:          %d", len(failed))
    logger.info("  Toplam PDF linki:   %d", len(all_pdf_links))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results, all_pdf_links


def quality_report(results: list[dict], pdf_links: list[dict]) -> dict:
    report = {
        "total_pages": len(results),
        "total_pdfs": len(pdf_links),
        "doc_kind_distribution": {},
        "char_count_stats": {},
        "pdf_per_page": {},
        "issues": [],
    }

    char_counts = []
    kind_counts = {}

    for r in results:
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        char_counts.append(r["char_count"])
        report["pdf_per_page"][r["slug"]] = r["pdf_count"]

        if not r["title"] or r["title"] == "Başlıksız":
            report["issues"].append({"slug": r["slug"], "issue": "Başlık eksik"})
        if r["char_count"] < 50:
            report["issues"].append({"slug": r["slug"], "issue": f"Çok kısa ({r['char_count']} kar.)"})

    report["doc_kind_distribution"] = kind_counts
    if char_counts:
        report["char_count_stats"] = {
            "min": min(char_counts), "max": max(char_counts),
            "avg": round(sum(char_counts) / len(char_counts)),
            "total": sum(char_counts),
        }
    return report


def print_quality_report(report: dict):
    logger.info("")
    logger.info("=" * 60)
    logger.info("KALİTE KONTROL RAPORU")
    logger.info("=" * 60)
    logger.info("Toplam sayfa: %d | Toplam PDF linki: %d", report["total_pages"], report["total_pdfs"])

    logger.info("📊 doc_kind Dağılımı:")
    for kind, count in report["doc_kind_distribution"].items():
        logger.info("  %-12s : %d", kind, count)

    logger.info("📎 Sayfa başına PDF sayısı:")
    for slug, count in report["pdf_per_page"].items():
        logger.info("  %-18s : %d PDF", slug, count)

    stats = report["char_count_stats"]
    if stats:
        logger.info("📏 İçerik: Min=%d | Max=%d | Ort=%d | Toplam=%d kar.",
                     stats["min"], stats["max"], stats["avg"], stats["total"])

    issues = report["issues"]
    if issues:
        logger.warning("⚠ Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("✅ Sorun bulunamadı!")
    logger.info("=" * 60)


def build_documents(results: list[dict]):
    from haystack import Document
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    documents = []

    for r in results:
        doc_id = hashlib.sha256(r["content"].encode("utf-8")).hexdigest()
        meta = {
            "category": r["category"],
            "source_url": r["url"],
            "source_type": "web",
            "source_id": generate_source_id(r["url"]),
            "last_updated": now,
            "title": r["title"],
            "doc_kind": r["doc_kind"],
            "language": "tr",
            "department": "Genel",
            "contact_unit": "Hukuk Müşavirliği",
            "contact_info": "hukukmusavirligi@gibtu.edu.tr",
        }
        documents.append(Document(id=doc_id, content=r["content"], meta=meta))
    return documents


def save_results_json(results: list[dict], pdf_links: list[dict], output_path: str):
    output = {
        "pages": [],
        "pdf_links": pdf_links,
    }
    for r in results:
        output["pages"].append({
            "url": r["url"], "slug": r["slug"], "title": r["title"],
            "doc_kind": r["doc_kind"], "category": r["category"],
            "char_count": r["char_count"], "pdf_count": r["pdf_count"],
            "content_preview": r["content"][:300] + "..." if len(r["content"]) > 300 else r["content"],
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Sonuçlar kaydedildi: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="GİBTÜ Mevzuat scraper (Görev 3.2.4)")
    parser.add_argument("--ingest", action="store_true", help="Veritabanına yükle")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run modu")
    parser.add_argument("--save-json", type=str, default=None, help="JSON çıktı dosyası")
    parser.add_argument("--download-pdfs", action="store_true", help="Tespit edilen PDF'leri indir")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. Scrape
    results, pdf_links = scrape_mevzuat_pages(session)

    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results, pdf_links)
    print_quality_report(report)

    # 3. PDF listesi
    if pdf_links:
        logger.info("")
        logger.info("=" * 60)
        logger.info("TESPİT EDİLEN PDF BAĞLANTILARI (%d adet)", len(pdf_links))
        logger.info("=" * 60)
        for i, pl in enumerate(pdf_links, 1):
            logger.info("  %2d. [%s] %s", i, pl["source_page"], pl["text"][:70])
            logger.info("      URL: %s", pl["url"][:100])

    # 4. JSON kaydet
    if args.save_json:
        save_results_json(results, pdf_links, args.save_json)

    # 5. PDF indirme (isteğe bağlı)
    if args.download_pdfs and pdf_links:
        logger.info("")
        logger.info("=" * 60)
        logger.info("PDF İNDİRME")
        logger.info("=" * 60)
        PDF_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        for pl in pdf_links:
            time.sleep(1.0)
            path = download_pdf(pl["url"], session, PDF_DOWNLOAD_DIR)
            if path:
                downloaded += 1
        logger.info("✅ %d / %d PDF indirildi → %s", downloaded, len(pdf_links), PDF_DOWNLOAD_DIR)

    # 6. Ingestion
    if args.ingest:
        logger.info("")
        logger.info("=" * 60)
        logger.info("VERİTABANINA YÜKLEME (web sayfaları)")
        logger.info("=" * 60)
        documents = build_documents(results)
        logger.info("%d Document oluşturuldu.", len(documents))

        from app.ingestion.loader import ingest_documents
        from haystack.document_stores.types import DuplicatePolicy
        written = ingest_documents(documents, policy=DuplicatePolicy.OVERWRITE, dry_run=args.dry_run)
        logger.info("✅ %d belge yazıldı (dry_run=%s).", written, args.dry_run)

        if pdf_links and not args.download_pdfs:
            logger.info("")
            logger.info("💡 PDF'leri indirmek için: python -m scrapers.scrape_mevzuat --download-pdfs")
            logger.info("   İndirilen PDF'ler load_all_pdfs.py ile ayrıca yüklenebilir.")
    else:
        logger.info("")
        logger.info("💡 DB'ye yüklemek için: python -m scrapers.scrape_mevzuat --ingest")

    logger.info("🏁 Görev 3.2.4 — Mevzuat scraping tamamlandı.")


if __name__ == "__main__":
    main()
