"""
UniChat — Görev 3.2.6b: Statik Slug Tabanlı Sayfaların Toplu Canlı Scrape'i

Keşif raporundaki (Bölüm 6) statik sayfaların, 3.2.2–3.2.6'da **zaten kapsanmış
olanlar çıkarıldıktan sonra** kalan sayfalarını canlı siteden scrape eder.

Zaten kapsanmış slug'lar (bu modül tarafından ATLANIR):
  3.2.2: Rektor, rektorunmesaji, RektorYardimcilari, RektorDanismanlari,
         senato, yonetimkurulu, kalitekurulu
  3.2.3: kurumsalkimlik, tarihce, kurumhiyerarsisi, etikdegerlerimiz,
         temeldegerlerimiz, oz, misyon, vizyon, nedengibtu, tanitimfilmi,
         galeri, sayilarlagibtu, siteharitasi, Logo
  3.2.4: yonetmelik, yonerge, usulesas, kvkk, iso27001
  3.2.5: faaliyetraporlari, kurumdisidegerlendirmeraporlari,
         kurumicdegerlendirmeraporlari, stratejikplanlar
  3.2.6: iletisim, sss, harita, telefonrehberi, sosyalag, rimer

Kapsanan slug'lar (bu modülün hedefleri):
  ulasim, yurtlar, yemeklistesi, akademiktakvim, birimrehber,
  akademikbirim, idaribirim, icerikrehberi, personelrehber

Kullanım:
    python -m scrapers.scrape_static_slugs
    python -m scrapers.scrape_static_slugs --ingest
    python -m scrapers.scrape_static_slugs --ingest --dry-run
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


def extract_meaningful_links(html: str, page_url: str) -> list[dict]:
    """
    Sayfa içindeki anlamlı bağlantıları çıkarır.
    JavaScript, anchor, # ve boş linkleri filtreler.
    """
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)

        # Filtrele: boş, anchor, javascript
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        if not text:
            continue

        # Tam URL'ye dönüştür
        if href.startswith("/"):
            full_url = f"https://www.gibtu.edu.tr{href}"
        elif not href.startswith("http"):
            full_url = f"https://www.gibtu.edu.tr/{href}"
        else:
            full_url = href

        if full_url in seen:
            continue
        seen.add(full_url)

        link_type = "page"
        if href.lower().endswith(".pdf"):
            link_type = "pdf"
        elif "gibtu.edu.tr" not in full_url:
            link_type = "external"

        links.append({
            "url": full_url,
            "text": text[:120],
            "type": link_type,
        })

    return links


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

# ── GİBTÜ Genel İletişim Bilgileri ──
GIBTU_CONTACT_INFO = (
    "Tel: +90 342 909 75 00 | "
    "Faks: 0850 258 98 00 | "
    "E-posta: info@gibtu.edu.tr | "
    "Adres: Beştepe Mah. Mustafa Bencan Cad. 6/4, 27010 Şahinbey/Gaziantep"
)

# ── Kapsanmış slug'lar (önceki görevlerde zaten scrape edildi) ──
ALREADY_COVERED_SLUGS = {
    # 3.2.2 — Rektörlük
    "Rektor", "rektorunmesaji", "RektorYardimcilari", "RektorDanismanlari",
    "senato", "yonetimkurulu", "kalitekurulu",
    # 3.2.3 — Kurumsal Kimlik
    "kurumsalkimlik", "tarihce", "kurumhiyerarsisi", "etikdegerlerimiz",
    "temeldegerlerimiz", "oz", "misyon", "vizyon", "nedengibtu",
    "tanitimfilmi", "galeri", "sayilarlagibtu", "siteharitasi", "Logo",
    # 3.2.4 — Mevzuat
    "yonetmelik", "yonerge", "usulesas", "kvkk", "iso27001",
    # 3.2.5 — Raporlar
    "faaliyetraporlari", "kurumdisidegerlendirmeraporlari",
    "kurumicdegerlendirmeraporlari", "stratejikplanlar",
    # 3.2.6 — İletişim
    "iletisim", "sss", "harita", "telefonrehberi", "sosyalag", "rimer",
}

# ── 3.2.6b Hedef Slug Haritası ──
# (slug, category, doc_kind, contact_unit, contact_info, açıklama)
STATIC_SLUG_PAGES = [
    (
        "ulasim",
        "ulasim",
        "rehber",
        "Sağlık Kültür ve Spor Daire Başkanlığı",
        "sks@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "Kampüse ulaşım bilgileri",
    ),
    (
        "yurtlar",
        "kampus",
        "rehber",
        "Sağlık Kültür ve Spor Daire Başkanlığı",
        "sks@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "Yurtlar ve barınma seçenekleri",
    ),
    (
        "yemeklistesi",
        "yemekhane",
        "rehber",
        "Sağlık Kültür ve Spor Daire Başkanlığı",
        "sks@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "Yemekhane güncel yemek listesi",
    ),
    (
        "akademiktakvim",
        "egitim",
        "takvim",
        "Öğrenci İşleri Daire Başkanlığı",
        "ogrenciisleri@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "Akademik takvim",
    ),
    (
        "birimrehber",
        "yonlendirme",
        "rehber",
        "Genel Sekreterlik",
        GIBTU_CONTACT_INFO,
        "Birim rehberi (tüm birimler)",
    ),
    (
        "akademikbirim",
        "yonlendirme",
        "rehber",
        "Genel Sekreterlik",
        GIBTU_CONTACT_INFO,
        "Akademik birimler listesi",
    ),
    (
        "idaribirim",
        "yonlendirme",
        "rehber",
        "Genel Sekreterlik",
        GIBTU_CONTACT_INFO,
        "İdari birimler listesi",
    ),
    (
        "icerikrehberi",
        "yonlendirme",
        "rehber",
        "Genel İletişim",
        GIBTU_CONTACT_INFO,
        "İçerik rehberi (site içi arama)",
    ),
    (
        "personelrehber",
        "yonlendirme",
        "rehber",
        "Personel Daire Başkanlığı",
        "personel@gibtu.edu.tr | " + GIBTU_CONTACT_INFO,
        "Personel rehberi",
    ),
]

# ── Placeholder / düşük kalite tespit anahtar kelimeleri ──
PLACEHOLDER_KEYWORDS = [
    "lorem ipsum", "örnek metin", "içerik eklenecek",
    "yapım aşamasında", "coming soon", "under construction",
    "bu sayfa henüz", "test sayfası",
]

MIN_CONTENT_LENGTH = 20    # Bu değerin altındaki sayfalar atlanır
SHORT_CONTENT_WARN = 50    # Bu değerin altındaki sayfalar "çok kısa" olarak raporlanır


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
    """URL'den sabit source_id üretir."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    query = parsed.query
    netloc = parsed.netloc.lower().replace("www.", "")
    source = f"{netloc}/{path}" if path else netloc
    if query:
        source += f"?{query}"
    return source


def detect_placeholder(content: str) -> str | None:
    """İçerik placeholder/yapım aşamasında ise anahtar kelimeyi döndürür, değilse None."""
    content_lower = content.lower()
    for kw in PLACEHOLDER_KEYWORDS:
        if kw in content_lower:
            return kw
    return None


def detect_duplicate_content(results: list[dict]) -> list[dict]:
    """Yinelenen içerikleri tespit eder. Content hash bazlı."""
    seen_hashes: dict[str, str] = {}  # hash → ilk slug
    dupes = []
    for r in results:
        h = hashlib.md5(r["content"].encode("utf-8")).hexdigest()
        if h in seen_hashes:
            dupes.append({
                "slug": r["slug"],
                "duplicate_of": seen_hashes[h],
            })
        else:
            seen_hashes[h] = r["slug"]
    return dupes


# ── Ana Scraping ──

def scrape_static_slug_pages() -> tuple[list[dict], list[dict]]:
    """
    Tüm statik slug sayfalarını canlı siteden scrape eder.

    Returns:
        (results, failed) — başarılı ve başarısız sonuçlar.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results: list[dict] = []
    failed: list[dict] = []

    logger.info("=" * 60)
    logger.info("Görev 3.2.6b — Statik Slug Sayfaları scraping başlıyor (%d sayfa)", len(STATIC_SLUG_PAGES))
    logger.info("=" * 60)

    for slug, category, doc_kind, contact_unit, contact_info, description in STATIC_SLUG_PAGES:
        # Güvenlik kontrolü: zaten kapsanmış mı?
        if slug in ALREADY_COVERED_SLUGS:
            logger.info("⏭ Zaten kapsanmış, atlanıyor: %s", slug)
            continue

        url = f"{BASE_URL}/{slug}"
        logger.info("→ Scraping: %s (%s)", url, description)

        time.sleep(RATE_LIMIT_DELAY)

        # Fetch
        html = fetch_page(url, session)
        if html is None:
            failed.append({
                "slug": slug, "url": url,
                "reason": "fetch_failed", "description": description,
            })
            continue

        # Parse
        content = clean_html(html)
        title = extract_gibtu_title(html)

        # Boş / çok kısa içerik kontrolü
        if not content or len(content.strip()) < MIN_CONTENT_LENGTH:
            char_count = len(content) if content else 0
            logger.warning("⚠ Boş veya çok kısa içerik: %s (%d karakter)", slug, char_count)
            failed.append({
                "slug": slug, "url": url,
                "reason": f"empty_content ({char_count} kar.)",
                "description": description,
            })
            continue

        # Placeholder kontrolü — uyar ama yine de al
        placeholder = detect_placeholder(content)
        if placeholder:
            logger.warning("⚠ Olası placeholder tespit edildi: %s → '%s'", slug, placeholder)

        # Anlamlı bağlantıları çıkar
        links = extract_meaningful_links(html, url)

        result = {
            "url": url,
            "slug": slug,
            "title": title or f"GİBTÜ — {description}",
            "content": content,
            "category": category,
            "doc_kind": doc_kind,
            "contact_unit": contact_unit,
            "contact_info": contact_info,
            "char_count": len(content),
            "description": description,
            "link_count": len(links),
            "links": links,
            "placeholder_detected": placeholder,
        }
        results.append(result)

        logger.info(
            "  ✅ \"%s\" | %d karakter | category=%s | doc_kind=%s | %d bağlantı",
            result["title"][:50], result["char_count"],
            category, doc_kind, len(links),
        )

    # Özet
    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING ÖZET")
    logger.info("  Toplam hedef:  %d", len(STATIC_SLUG_PAGES))
    logger.info("  Başarılı:      %d", len(results))
    logger.info("  Başarısız:     %d", len(failed))
    if failed:
        for f in failed:
            logger.warning("  ❌ %s — %s", f["slug"], f["reason"])
    logger.info("=" * 60)

    return results, failed


# ── Kalite Raporu ──

def quality_report(results: list[dict], failed: list[dict]) -> dict:
    """Kapsamlı kalite kontrol raporu üretir."""
    report = {
        "total_target": len(STATIC_SLUG_PAGES),
        "total_scraped": len(results),
        "total_failed": len(failed),
        "category_distribution": {},
        "doc_kind_distribution": {},
        "contact_unit_distribution": {},
        "char_count_stats": {},
        "metadata_completeness": {
            "title": 0, "category": 0, "doc_kind": 0,
            "source_url": 0, "contact_unit": 0, "contact_info": 0,
        },
        "issues": [],
        "duplicates": [],
    }

    char_counts: list[int] = []
    cat_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    unit_counts: dict[str, int] = {}

    for r in results:
        # Dağılım sayaçları
        cat = r["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        kind = r["doc_kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        unit = r["contact_unit"]
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
        char_counts.append(r["char_count"])

        # Metadata doluluk
        if r.get("title") and r["title"] != "Başlıksız":
            report["metadata_completeness"]["title"] += 1
        if r.get("category"):
            report["metadata_completeness"]["category"] += 1
        if r.get("doc_kind"):
            report["metadata_completeness"]["doc_kind"] += 1
        if r.get("url"):
            report["metadata_completeness"]["source_url"] += 1
        if r.get("contact_unit"):
            report["metadata_completeness"]["contact_unit"] += 1
        if r.get("contact_info"):
            report["metadata_completeness"]["contact_info"] += 1

        # Sorun tespiti
        if r.get("placeholder_detected"):
            report["issues"].append({
                "slug": r["slug"],
                "issue": f"Placeholder: '{r['placeholder_detected']}'",
            })
        if not r["title"] or r["title"] == "Başlıksız":
            report["issues"].append({
                "slug": r["slug"],
                "issue": "Başlık eksik veya 'Başlıksız'",
            })
        if r["char_count"] < SHORT_CONTENT_WARN:
            report["issues"].append({
                "slug": r["slug"],
                "issue": f"Çok kısa içerik ({r['char_count']} karakter)",
            })
        if not r.get("contact_unit"):
            report["issues"].append({
                "slug": r["slug"],
                "issue": "contact_unit eksik (ZORUNLU)",
            })

    report["category_distribution"] = cat_counts
    report["doc_kind_distribution"] = kind_counts
    report["contact_unit_distribution"] = unit_counts

    if char_counts:
        report["char_count_stats"] = {
            "min": min(char_counts),
            "max": max(char_counts),
            "avg": round(sum(char_counts) / len(char_counts)),
            "total": sum(char_counts),
        }

    # Yinelenen içerik tespiti
    report["duplicates"] = detect_duplicate_content(results)

    return report


def print_quality_report(report: dict):
    """Kalite raporunu terminal çıktısı olarak güzel formatta yazdırır."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("KALİTE KONTROL RAPORU — 3.2.6b Statik Slug Sayfaları")
    logger.info("=" * 60)
    logger.info("Toplam hedef: %d | Scrape: %d | Başarısız: %d",
                report["total_target"], report["total_scraped"], report["total_failed"])

    # Kategori dağılımı
    logger.info("")
    logger.info("📊 category Dağılımı:")
    for cat, count in report["category_distribution"].items():
        logger.info("  %-16s : %d", cat, count)

    # doc_kind dağılımı
    logger.info("📋 doc_kind Dağılımı:")
    for kind, count in report["doc_kind_distribution"].items():
        logger.info("  %-16s : %d", kind, count)

    # contact_unit dağılımı
    logger.info("🏢 contact_unit Dağılımı:")
    for unit, count in report["contact_unit_distribution"].items():
        logger.info("  %-45s : %d", unit, count)

    # İçerik uzunluğu
    stats = report["char_count_stats"]
    if stats:
        logger.info("")
        logger.info("📏 İçerik Uzunluğu İstatistikleri:")
        logger.info("  Min: %d | Max: %d | Ort: %d | Toplam: %d karakter",
                     stats["min"], stats["max"], stats["avg"], stats["total"])

    # Metadata doluluk
    logger.info("")
    logger.info("📝 Metadata Doluluk (%d sayfadan):", report["total_scraped"])
    for field, count in report["metadata_completeness"].items():
        pct = round(count / report["total_scraped"] * 100) if report["total_scraped"] else 0
        status = "✅" if pct == 100 else "⚠" if pct >= 80 else "❌"
        logger.info("  %s %-16s : %d/%d (%d%%)", status, field, count, report["total_scraped"], pct)

    # Yinelenen içerik
    dupes = report["duplicates"]
    if dupes:
        logger.warning("")
        logger.warning("🔁 Yinelenen İçerik (%d):", len(dupes))
        for d in dupes:
            logger.warning("  %s → %s ile aynı içerik", d["slug"], d["duplicate_of"])

    # Sorunlar
    issues = report["issues"]
    if issues:
        logger.warning("")
        logger.warning("⚠ Sorunlar (%d):", len(issues))
        for issue in issues:
            logger.warning("  [%s] %s", issue["slug"], issue["issue"])
    else:
        logger.info("")
        logger.info("✅ Sorun bulunamadı — tüm veriler temiz!")

    logger.info("=" * 60)


# ── Document Builder ──

def build_documents(results: list[dict]):
    """Scrape sonuçlarını Haystack Document listesine dönüştürür."""
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
            "contact_unit": r["contact_unit"],
            "contact_info": r["contact_info"],
        }
        documents.append(Document(id=doc_id, content=r["content"], meta=meta))

    return documents


# ── JSON Kayıt ──

def save_results_json(results: list[dict], failed: list[dict], output_path: str):
    """Scrape sonuçlarını JSON olarak kaydeder."""
    output = {
        "meta": {
            "task": "3.2.6b",
            "description": "Statik Slug Tabanlı Sayfaların Toplu Canlı Scrape'i",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_target": len(STATIC_SLUG_PAGES),
            "total_scraped": len(results),
            "total_failed": len(failed),
        },
        "pages": [],
        "failed": failed,
    }

    for r in results:
        output["pages"].append({
            "url": r["url"],
            "slug": r["slug"],
            "title": r["title"],
            "category": r["category"],
            "doc_kind": r["doc_kind"],
            "contact_unit": r["contact_unit"],
            "contact_info": r["contact_info"][:80] + "..." if len(r["contact_info"]) > 80 else r["contact_info"],
            "char_count": r["char_count"],
            "link_count": r["link_count"],
            "placeholder_detected": r["placeholder_detected"],
            "content_preview": r["content"][:300] + "..." if len(r["content"]) > 300 else r["content"],
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Sonuçlar kaydedildi: %s", output_path)


# ── Main ──

def main():
    parser = argparse.ArgumentParser(
        description="GİBTÜ Statik Slug Tabanlı Sayfalar Scraper (Görev 3.2.6b)"
    )
    parser.add_argument("--ingest", action="store_true", help="Veritabanına yükle")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run modu")
    parser.add_argument(
        "--save-json", type=str, default=None,
        help="JSON çıktı dosyası (varsayılan: scrapers/static_slugs_output.json)",
    )
    args = parser.parse_args()

    # 1. Scrape
    results, failed = scrape_static_slug_pages()

    if not results:
        logger.error("Hiç sayfa scrape edilemedi. Çıkılıyor.")
        sys.exit(1)

    # 2. Kalite raporu
    report = quality_report(results, failed)
    print_quality_report(report)

    # 3. JSON kaydet (her zaman)
    json_path = args.save_json or str(Path(__file__).resolve().parent / "static_slugs_output.json")
    save_results_json(results, failed, json_path)

    # 4. Sayfa özetleri
    logger.info("")
    logger.info("SAYFA ÖZETLERİ")
    logger.info("-" * 60)
    for r in results:
        preview = r["content"][:100].replace("\n", " ")
        logger.info(
            "📄 %-20s | %-28s | %5d kar. | cat=%-14s | %s...",
            r["slug"][:20], r["title"][:28], r["char_count"],
            r["category"][:14], preview[:50],
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

        written = ingest_documents(
            documents,
            policy=DuplicatePolicy.OVERWRITE,
            dry_run=args.dry_run,
        )
        logger.info("✅ %d belge yazıldı (dry_run=%s).", written, args.dry_run)
    else:
        logger.info("")
        logger.info("💡 DB'ye yüklemek için: python -m scrapers.scrape_static_slugs --ingest")
        logger.info("💡 Dry-run için:       python -m scrapers.scrape_static_slugs --ingest --dry-run")

    logger.info("")
    logger.info("🏁 Görev 3.2.6b — Statik Slug Tabanlı Sayfalar scraping tamamlandı.")


if __name__ == "__main__":
    main()
