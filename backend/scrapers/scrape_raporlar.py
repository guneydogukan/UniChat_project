"""
UniChat — Görev 3.2.5: Raporlar Sayfaları Scraping

Faaliyet raporları, kurum iç/dış değerlendirme raporları ve stratejik planları
scrape eder. Bu sayfalar büyük olasılıkla PDF bağlantıları içerir — PDF linkleri
ayrıca raporlanır ve isteğe bağlı olarak indirilip pdf_parser ile işlenir.

Hedef sayfalar (gibtu_yapisal_kesif_raporu.md § 6):
  faaliyetraporlari, kurumdisidegerlendirmeraporlari,
  kurumicdegerlendirmeraporlari, stratejikplanlar

Kullanım:
    python -m scrapers.scrape_raporlar
    python -m scrapers.scrape_raporlar --ingest
    python -m scrapers.scrape_raporlar --ingest --dry-run
    python -m scrapers.scrape_raporlar --download-pdfs
    python -m scrapers.scrape_raporlar --save-json scrapers/raporlar_output.json
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
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from scrapers.utils import clean_html, extract_title, normalize_url  # noqa: E402

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Sabitler ─────────────────────────────────────────────────────────────────
BASE_URL        = "https://www.gibtu.edu.tr"
USER_AGENT      = (
    "Mozilla/5.0 (compatible; UniChatBot/1.0; "
    "+https://github.com/unichat-project)"
)
REQUEST_TIMEOUT   = 30      # saniye
RATE_LIMIT_DELAY  = 1.5     # saniye (sayfa istekleri arası)
PDF_RATE_DELAY    = 1.0     # saniye (PDF indirme arası)
MAX_RETRIES       = 3

PDF_DOWNLOAD_DIR = (
    Path(__file__).resolve().parent.parent
    / "data" / "pdfs" / "raporlar_web"
)

# ── Site genelinde tekrarlanan (header/footer) PDF'ler — bu linkleri atla ──
# Bu linkler her rapor sayfasında site navigasyonu gereği tekrar eder.
_GLOBAL_PDF_PATTERNS = {
    "Kalite Komisyonu",
    "Birim Kalite Komisyonları Yönergesi",
    "Mühendislik ve Doğa Bilimleri Dergisi",
}

# ── Raporlar URL Haritası ─────────────────────────────────────────────────────
# (slug, doc_kind, category, description)
RAPORLAR_PAGES = [
    (
        "faaliyetraporlari",
        "rapor",
        "genel_bilgi",
        "Faaliyet Raporları",
    ),
    (
        "kurumdisidegerlendirmeraporlari",
        "rapor",
        "genel_bilgi",
        "Kurum Dışı Değerlendirme Raporları",
    ),
    (
        "kurumicdegerlendirmeraporlari",
        "rapor",
        "genel_bilgi",
        "Kurum İç Değerlendirme Raporları",
    ),
    (
        "stratejikplanlar",
        "rapor",
        "genel_bilgi",
        "Stratejik Planlar",
    ),
]

# ── Boilerplate temizleme kalıpları ──────────────────────────────────────────
_BOILERPLATE_PATTERNS = [
    r"GIBTU Homepage\s*",
    r"GAZİANTEP İSLAM,?\s*BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ\s*",
    r"\"Kariyeriniz Bizimle Başlar\"\s*",
    r"Bilgi Edinme\s*",
    r"E-Devlet Girişi\s*",
    r"Kişisel Veri Korunması\s*",
    r"Üst Menu\s*",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_gibtu_title(html: str) -> str:
    """GİBTÜ sayfalarından başlık çıkarır (page_title → card-title → <title>)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for selector in ["span.page_title", "div.card-title", "h1"]:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return extract_title(html)


def clean_gibtu_content(html: str) -> str:
    """
    GİBTÜ sayfası için gelişmiş içerik temizleme.
    
    1. Temel HTML temizleme (clean_html)
    2. Site geneli boilerplate kalıplarını kaldırma
    3. Ardışık boş satırları normalleştirme
    """
    content = clean_html(html)
    if not content:
        return ""

    # Boilerplate kalıplarını kaldır
    for pattern in _BOILERPLATE_PATTERNS:
        content = re.sub(pattern, "", content)

    # Başta/sonda boşlukları ve ardışık boş satırları temizle
    content = re.sub(r"\n\s*\n+", "\n\n", content)
    content = content.strip()

    return content


def fetch_page(url: str, session: requests.Session) -> str | None:
    """URL'den HTML çeker — retry + encoding düzeltme."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.upper() == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            logger.warning(
                "HTTP %s — deneme %d/%d: %s", status, attempt, MAX_RETRIES, url
            )
            if e.response is not None and 400 <= e.response.status_code < 500:
                return None  # 4xx → kesin hata, retry yok
        except requests.exceptions.ConnectionError:
            logger.warning(
                "Bağlantı hatası — deneme %d/%d: %s", attempt, MAX_RETRIES, url
            )
        except requests.exceptions.Timeout:
            logger.warning(
                "Zaman aşımı — deneme %d/%d: %s", attempt, MAX_RETRIES, url
            )
        except requests.exceptions.RequestException as e:
            logger.error("Beklenmeyen hata: %s — %s", e, url)
            return None

        if attempt < MAX_RETRIES:
            time.sleep(2 * attempt)

    logger.error("Tüm denemeler başarısız: %s", url)
    return None


def resolve_pdf_url(url: str) -> str:
    """
    PdfViewer.aspx wrapper URL'lerini gerçek PDF URL'sine dönüştürür.
    
    Örnek:
      .../PdfViewer/web/PdfViewer.aspx?file=../../20250228150522_xxx.pdf
      → https://www.gibtu.edu.tr/Medya/GibtuDosya/20250228150522_xxx.pdf
    """
    parsed = urlparse(url)
    if "PdfViewer.aspx" not in parsed.path:
        return url

    # file= parametresindeki relative path'i çöz
    qs = parse_qs(parsed.query)
    file_param = qs.get("file", [None])[0]
    if not file_param:
        return url

    # PdfViewer/web/ dizininden ../../ ile üst dizine çıkılır
    # Base path: .../Medya/GibtuDosya/PdfViewer/web/
    viewer_base = url.split("PdfViewer.aspx")[0]  # .../PdfViewer/web/
    resolved = urljoin(viewer_base, file_param)
    return resolved


def is_global_nav_pdf(link_text: str) -> bool:
    """Bu PDF bağlantısının site genelinde tekrar eden bir nav linki olup olmadığını kontrol eder."""
    for pattern in _GLOBAL_PDF_PATTERNS:
        if pattern.lower() in link_text.lower():
            return True
    return False


def extract_pdf_links(html: str, page_url: str) -> list[dict]:
    """
    HTML'den PDF bağlantılarını çıkarır. PdfViewer URL'lerini çözer,
    site genelindeki tekrarlanan navigasyon PDF'lerini atlar.

    Returns:
        [{url, text, filename, resolved_url}, ...]
    """
    soup = BeautifulSoup(html, "lxml")
    pdf_links: list[dict] = []
    seen_urls: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"]

        is_pdf = (
            href.lower().endswith(".pdf")
            or "GibtuDosya" in href
            or ("gibtu" in href.lower() and ".pdf" in href.lower())
        )
        if not is_pdf:
            continue

        full_url = urljoin(page_url, href)
        link_text = a_tag.get_text(strip=True)

        # Site genelindeki navigasyon/header PDF'lerini atla
        if is_global_nav_pdf(link_text):
            continue

        # PdfViewer.aspx URL'lerini gerçek PDF URL'sine dönüştür
        resolved_url = resolve_pdf_url(full_url)

        if resolved_url in seen_urls:
            continue
        seen_urls.add(resolved_url)

        # Dosya adını resolved URL'den çıkar
        filename = os.path.basename(urlparse(resolved_url).path)

        pdf_links.append({
            "url":          full_url,
            "resolved_url": resolved_url,
            "text":         link_text or filename,
            "filename":     filename,
        })

    return pdf_links


def generate_source_id(url: str) -> str:
    parsed = urlparse(url)
    path   = parsed.path.strip("/")
    netloc = parsed.netloc.lower().replace("www.", "")
    return f"{netloc}/{path}" if path else netloc


def safe_filename(name: str) -> str:
    """Dosya adından geçersiz karakterleri temizler."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def download_pdf(url: str, link_text: str, session: requests.Session, output_dir: Path) -> str | None:
    """PDF'i indirir, mevcut ise atlar. Dosya yolunu döndürür."""
    try:
        parsed   = urlparse(url)
        filename = safe_filename(os.path.basename(parsed.path))
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        # Daha anlamlı dosya adı: link metnini kullan
        if filename.startswith("20") and "_" in filename and link_text:
            # timestamp_hash.pdf şeklindeki isimler yerine link metnini kullan
            clean_name = safe_filename(link_text.strip()[:80])
            if clean_name:
                filename = f"{clean_name}.pdf"

        filepath = output_dir / filename
        if filepath.exists():
            logger.info("  ⏭ Mevcut, atlandı: %s", filename)
            return str(filepath)

        resp = session.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        # Content-Type kontrolü — gerçekten PDF mi?
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
            logger.warning(
                "  ⚠ Beklenmeyen Content-Type: %s — %s", content_type, url
            )

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(
            "  📥 İndirildi: %s (%d KB)", filename, filepath.stat().st_size // 1024
        )
        return str(filepath)

    except Exception as e:
        logger.error("  ❌ PDF indirilemedi: %s — %s", url, e)
        return None


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_raporlar_pages(
    session: requests.Session,
) -> tuple[list[dict], list[dict]]:
    """
    Raporlar sayfalarını scrape eder.

    Returns:
        (page_results, all_pdf_links)
    """
    results:       list[dict] = []
    all_pdf_links: list[dict] = []
    failed:        list[dict] = []
    global_seen_pdf_urls: set[str] = set()  # sayfa-arası PDF dedup

    logger.info("=" * 60)
    logger.info(
        "Raporlar sayfaları scraping başlıyor (%d sayfa)", len(RAPORLAR_PAGES)
    )
    logger.info("=" * 60)

    for slug, doc_kind, category, description in RAPORLAR_PAGES:
        url = f"{BASE_URL}/{slug}"
        logger.info("→ Scraping: %s (%s)", url, description)

        time.sleep(RATE_LIMIT_DELAY)

        html = fetch_page(url, session)
        if html is None:
            failed.append({"slug": slug, "url": url, "reason": "fetch_failed"})
            logger.warning("  ❌ Sayfa alınamadı: %s", url)
            continue

        # ── PDF bağlantılarını çıkar (sayfa-arası dedup ile) ──
        page_pdf_links = extract_pdf_links(html, url)
        unique_page_pdfs = []
        for pl in page_pdf_links:
            resolved = pl["resolved_url"]
            if resolved not in global_seen_pdf_urls:
                global_seen_pdf_urls.add(resolved)
                pl["source_page"] = slug
                pl["doc_kind"]    = doc_kind
                pl["category"]    = category
                unique_page_pdfs.append(pl)
        all_pdf_links.extend(unique_page_pdfs)

        if unique_page_pdfs:
            logger.info("  📎 %d PDF bağlantısı tespit edildi", len(unique_page_pdfs))
            for pl in unique_page_pdfs[:5]:
                logger.info("     • %s", pl["text"][:80])
            if len(unique_page_pdfs) > 5:
                logger.info("     ... ve %d tane daha", len(unique_page_pdfs) - 5)

        # ── Sayfa metin içeriği (gelişmiş temizleme ile) ──
        content = clean_gibtu_content(html)
        title   = extract_gibtu_title(html)

        if not content or len(content.strip()) < 20:
            logger.warning("  ⚠ Boş / çok kısa içerik: %s", slug)
            failed.append({"slug": slug, "url": url, "reason": "empty_content"})
            continue

        result = {
            "url":         url,
            "slug":        slug,
            "title":       title or f"Rapor — {description}",
            "content":     content,
            "doc_kind":    doc_kind,
            "category":    category,
            "char_count":  len(content),
            "description": description,
            "pdf_count":   len(unique_page_pdfs),
        }
        results.append(result)

        logger.info(
            "  ✅ \"%s\" | %d kar. | %d PDF | doc_kind=%s",
            result["title"][:55],
            result["char_count"],
            len(unique_page_pdfs),
            doc_kind,
        )

    # ── Özet ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef sayfa : %d", len(RAPORLAR_PAGES))
    logger.info("  Başarılı           : %d", len(results))
    logger.info("  Başarısız          : %d", len(failed))
    logger.info("  Toplam PDF bağlantı: %d (deduplicated)", len(all_pdf_links))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results, all_pdf_links


# ── Kalite Raporu ─────────────────────────────────────────────────────────────

def quality_report(results: list[dict], pdf_links: list[dict]) -> dict:
    report: dict = {
        "total_pages":           len(results),
        "total_pdfs":            len(pdf_links),
        "doc_kind_distribution": {},
        "char_count_stats":      {},
        "pdf_per_page":          {},
        "issues":                [],
    }

    char_counts: list[int] = []
    kind_counts: dict[str, int] = {}

    for r in results:
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        char_counts.append(r["char_count"])
        report["pdf_per_page"][r["slug"]] = r["pdf_count"]

        if not r["title"] or r["title"] in ("Başlıksız", ""):
            report["issues"].append(
                {"slug": r["slug"], "issue": "Başlık eksik"}
            )
        if r["char_count"] < 50:
            report["issues"].append(
                {"slug": r["slug"], "issue": f"Çok kısa ({r['char_count']} kar.)"}
            )
        if r["pdf_count"] == 0:
            report["issues"].append(
                {"slug": r["slug"], "issue": "PDF bağlantısı bulunamadı"}
            )

    report["doc_kind_distribution"] = kind_counts
    if char_counts:
        report["char_count_stats"] = {
            "min":   min(char_counts),
            "max":   max(char_counts),
            "avg":   round(sum(char_counts) / len(char_counts)),
            "total": sum(char_counts),
        }
    return report


def print_quality_report(report: dict) -> None:
    logger.info("")
    logger.info("=" * 60)
    logger.info("KALİTE KONTROL RAPORU")
    logger.info("=" * 60)
    logger.info(
        "Toplam sayfa: %d | Toplam PDF bağlantı: %d",
        report["total_pages"], report["total_pdfs"],
    )

    logger.info("📊 doc_kind Dağılımı:")
    for kind, count in report["doc_kind_distribution"].items():
        logger.info("  %-15s : %d", kind, count)

    logger.info("📎 Sayfa başına PDF sayısı:")
    for slug, count in report["pdf_per_page"].items():
        logger.info("  %-35s : %d PDF", slug, count)

    stats = report["char_count_stats"]
    if stats:
        logger.info(
            "📏 İçerik: Min=%d | Max=%d | Ort=%d | Toplam=%d kar.",
            stats["min"], stats["max"], stats["avg"], stats["total"],
        )

    issues = report["issues"]
    if issues:
        logger.warning("⚠ Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("✅ Sorun bulunamadı!")
    logger.info("=" * 60)


# ── Document Builder ──────────────────────────────────────────────────────────

def build_documents(results: list[dict]):
    from haystack import Document

    now       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    documents = []

    for r in results:
        doc_id = hashlib.sha256(r["content"].encode("utf-8")).hexdigest()
        meta = {
            "category":     r["category"],
            "source_url":   r["url"],
            "source_type":  "web",
            "source_id":    generate_source_id(r["url"]),
            "last_updated": now,
            "title":        r["title"],
            "doc_kind":     r["doc_kind"],
            "language":     "tr",
            "department":   "Genel",
            # Raporlar ve stratejik planların sorumlusu Strateji Geliştirme Daire Başkanlığı
            "contact_unit": "Strateji Geliştirme Daire Başkanlığı",
            "contact_info": "strateji@gibtu.edu.tr",
        }
        documents.append(Document(id=doc_id, content=r["content"], meta=meta))

    return documents


# ── JSON Kaydı ────────────────────────────────────────────────────────────────

def save_results_json(
    results: list[dict],
    pdf_links: list[dict],
    output_path: str,
) -> None:
    output = {"pages": [], "pdf_links": pdf_links}
    for r in results:
        output["pages"].append({
            "url":             r["url"],
            "slug":            r["slug"],
            "title":           r["title"],
            "doc_kind":        r["doc_kind"],
            "category":        r["category"],
            "char_count":      r["char_count"],
            "pdf_count":       r["pdf_count"],
            "content_preview": (
                r["content"][:300] + "…"
                if len(r["content"]) > 300
                else r["content"]
            ),
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Sonuçlar kaydedildi → %s", output_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GİBTÜ Raporlar scraper (Görev 3.2.5)"
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="Scrape edilen sayfaları veritabanına yükle",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dry-run: DB'ye yazma, yalnızca raporla",
    )
    parser.add_argument(
        "--save-json", type=str, default=None,
        help="Sonuçları JSON dosyasına kaydet (örn. scrapers/raporlar_output.json)",
    )
    parser.add_argument(
        "--download-pdfs", action="store_true",
        help="Tespit edilen PDF bağlantılarını indir",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. Scrape
    results, pdf_links = scrape_raporlar_pages(session)

    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results, pdf_links)
    print_quality_report(report)

    # 3. PDF listesini göster
    if pdf_links:
        logger.info("")
        logger.info("=" * 60)
        logger.info("TESPİT EDİLEN PDF BAĞLANTILARI (%d adet — deduplicated)", len(pdf_links))
        logger.info("=" * 60)
        for i, pl in enumerate(pdf_links, 1):
            logger.info("  %2d. [%s] %s", i, pl["source_page"], pl["text"][:75])
            logger.info("      Orijinal : %s", pl["url"][:110])
            logger.info("      İndirme  : %s", pl["resolved_url"][:110])

    # 4. JSON kaydet
    if args.save_json:
        save_results_json(results, pdf_links, args.save_json)
    else:
        # Varsayılan olarak scrapers/ dizinine kaydet
        default_out = Path(__file__).parent / "raporlar_output.json"
        save_results_json(results, pdf_links, str(default_out))

    # 5. PDF indirme (isteğe bağlı)
    if args.download_pdfs and pdf_links:
        logger.info("")
        logger.info("=" * 60)
        logger.info("PDF İNDİRME")
        logger.info("=" * 60)
        PDF_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        for pl in pdf_links:
            time.sleep(PDF_RATE_DELAY)
            # resolved_url ile indir (gerçek PDF yolu)
            path = download_pdf(pl["resolved_url"], pl["text"], session, PDF_DOWNLOAD_DIR)
            if path:
                downloaded += 1
        logger.info(
            "✅ %d / %d PDF indirildi → %s",
            downloaded, len(pdf_links), PDF_DOWNLOAD_DIR,
        )

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

        written = ingest_documents(
            documents,
            policy=DuplicatePolicy.OVERWRITE,
            dry_run=args.dry_run,
        )
        logger.info(
            "✅ %d belge yazıldı (dry_run=%s).", written, args.dry_run
        )

        if pdf_links and not args.download_pdfs:
            logger.info("")
            logger.info(
                "💡 PDF'leri indirmek için: "
                "python -m scrapers.scrape_raporlar --download-pdfs"
            )
            logger.info(
                "   İndirilen PDF'ler load_all_pdfs.py ile ayrıca yüklenebilir."
            )
    else:
        logger.info("")
        logger.info(
            "💡 DB'ye yüklemek için: python -m scrapers.scrape_raporlar --ingest"
        )

    logger.info("🏁 Görev 3.2.5 — Raporlar scraping tamamlandı.")


if __name__ == "__main__":
    main()
