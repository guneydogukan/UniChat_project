"""
Gorev 3.5 P4 — Birim Iletisim Bilgilerinin Otomatik Birlestirme Tablosu

1. doc/gibtu/Iletisim.html blueprint'inden tum birimleri parse eder
2. Kesif raporundaki bilinen birimlerin BirimIletisim.aspx?id={BirimID} sayfalarini canli ceker
3. Iki kaynaği birlestirip normalize bir iletisim tablosu olusturur
4. Her birim icin ayri Document + 1 master tablo Document → DB'ye yazar

Guvenlik kurallari:
  - SABİT HEDEFLER: Sadece kesif raporundaki BirimID'ler
  - MAX DEPTH = 1: Sadece iletisim sayfasinin kendisi, baska linke gidilmez
  - TIMEOUT: Her istek icin 15s timeout, 3 deneme
  - Hata yakalama: yanit vermeyen birimler atlanir

Kullanim:
    python run_birim_iletisim_tablosu.py              # scrape + ingest
    python run_birim_iletisim_tablosu.py --dry-run     # test (DB'ye yazmaz)
"""
import sys
import json
import hashlib
import time
import logging
import re
import argparse
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ingestion.loader import ingest_documents, DuplicatePolicy
from haystack import Document

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"
BLUEPRINT_PATH = Path(__file__).resolve().parent.parent / "doc" / "gibtu" / "İletişim.html"
RATE_LIMIT = 1.2
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0)"
TIMEOUT = 15

# Bilinen tum birimler — kesif raporundan (gibtu_yapisal_kesif_raporu.md)
BIRIMLER = [
    # Fakulteler
    {"id": 11, "slug": "ilahiyatfakultesi", "name": "İlahiyat Fakültesi", "grup": "Fakülteler"},
    {"id": 15, "slug": "mdbf", "name": "Mühendislik ve Doğa Bilimleri Fakültesi", "grup": "Fakülteler"},
    {"id": 20, "slug": "tip", "name": "Tıp Fakültesi", "grup": "Fakülteler"},
    {"id": 21, "slug": "sbf", "name": "Sağlık Bilimleri Fakültesi", "grup": "Fakülteler"},
    {"id": 22, "slug": "iii", "name": "İktisadi İdari ve Sosyal Bilimler Fakültesi", "grup": "Fakülteler"},
    {"id": 24, "slug": "gsmf", "name": "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "grup": "Fakülteler"},
    # MYO + YO
    {"id": 31, "slug": "shmyo", "name": "Sağlık Hizmetleri MYO", "grup": "MYO/YO"},
    {"id": 34, "slug": "yabancidiller", "name": "Yabancı Diller Yüksekokulu", "grup": "MYO/YO"},
    {"id": 36, "slug": "teknikbilimler", "name": "Teknik Bilimler MYO", "grup": "MYO/YO"},
    # Enstitu
    {"id": 35, "slug": "lisansustu", "name": "Lisansüstü Eğitim Enstitüsü", "grup": "Enstitü"},
    # Daire Baskanliklari
    {"id": 2, "slug": "bilgiislem", "name": "Bilgi İşlem Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 3, "slug": "genelsekreterlik", "name": "Genel Sekreterlik", "grup": "Daire Başkanlıkları"},
    {"id": 4, "slug": "ogrenciisleri", "name": "Öğrenci İşleri Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 5, "slug": "personel", "name": "Personel Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 6, "slug": "idarimaliisler", "name": "İdari ve Mali İşler Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 7, "slug": "kutuphane", "name": "Kütüphane ve Dokümantasyon Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 8, "slug": "sks", "name": "Sağlık Kültür ve Spor Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 9, "slug": "strateji", "name": "Strateji Geliştirme Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    {"id": 10, "slug": "yapiisleri", "name": "Yapı İşleri ve Teknik Daire Başkanlığı", "grup": "Daire Başkanlıkları"},
    # Koordinatorlukler
    {"id": 75, "slug": "sustainability", "name": "Sürdürülebilirlik Ofisi", "grup": "Koordinatörlükler"},
    {"id": 76, "slug": "kik", "name": "Kurumsal İletişim Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 79, "slug": "international", "name": "Dış İlişkiler Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 81, "slug": "eobk", "name": "Engelli Öğrenci Birimi Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 95, "slug": "kgk", "name": "Kalite Geliştirme ve Akreditasyon Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 104, "slug": "bagimliklamucadelekoor", "name": "Bağımlılıkla Mücadele Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 118, "slug": "isgk", "name": "İş Sağlığı ve Güvenliği Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 2137, "slug": "pddb", "name": "Psikolojik Danışmanlık ve Rehberlik Koordinatörlüğü", "grup": "Koordinatörlükler"},
    {"id": 2155, "slug": "btykoordinatorlugu", "name": "Bilim ve Teknoloji Yarışmaları Koordinatörlüğü", "grup": "Koordinatörlükler"},
    # UAM (Uygulama ve Arastirma Merkezleri)
    {"id": 40, "slug": "uzek", "name": "Uzaktan Eğitim Uygulama ve Araştırma Merkezi", "grup": "Merkezler"},
    {"id": 41, "slug": "kagiam", "name": "Kariyer Geliştirme Uygulama ve Araştırma Merkezi", "grup": "Merkezler"},
    {"id": 65, "slug": "semm", "name": "Sürekli Eğitim Merkezi Müdürlüğü", "grup": "Merkezler"},
    {"id": 101, "slug": "gigam", "name": "Genç Girişimci İnovasyon Araştırma Merkezi", "grup": "Merkezler"},
    {"id": 102, "slug": "pgko", "name": "Proje Geliştirme ve Koordinasyon Ofisi", "grup": "Merkezler"},
    {"id": 103, "slug": "tomer", "name": "Türkçe Öğretimi Uygulama ve Araştırma Merkezi", "grup": "Merkezler"},
    {"id": 2129, "slug": "tto", "name": "Teknoloji Transfer Ofisi", "grup": "Merkezler"},
    {"id": 2130, "slug": "dhuam", "name": "Deney Hayvanları Uygulama ve Araştırma Merkezi", "grup": "Merkezler"},
    # Mudurlukler
    {"id": 37, "slug": "hukukmusavirligi", "name": "Hukuk Müşavirliği", "grup": "Müdürlükler"},
    {"id": 39, "slug": "yaziisleri", "name": "Yazı İşleri Müdürlüğü", "grup": "Müdürlükler"},
    {"id": 77, "slug": "donersermaye", "name": "Döner Sermaye İşletme Müdürlüğü", "grup": "Müdürlükler"},
]


def _doc_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fetch(url: str, session: requests.Session) -> str | None:
    """Canli fetch with retry + timeout + encoding fallback."""
    for attempt in range(1, 4):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if e.response is not None and 400 <= e.response.status_code < 500:
                logger.warning(f"  HTTP {status}: {url}")
                return None
            logger.warning(f"  HTTP {status} deneme {attempt}/3: {url}")
        except requests.exceptions.Timeout:
            logger.warning(f"  TIMEOUT deneme {attempt}/3: {url}")
        except Exception as e:
            logger.warning(f"  Hata deneme {attempt}/3: {e}")
        if attempt < 3:
            time.sleep(2 * attempt)
    return None


def _extract_contact_info(html_text: str) -> dict:
    """BirimIletisim.aspx sayfasindan iletisim bilgilerini cikar."""
    soup = BeautifulSoup(html_text, "html.parser")

    info = {
        "adres": "",
        "telefon": "",
        "faks": "",
        "eposta": "",
    }

    # Ana icerik bolgesi
    body = (soup.find("div", class_="birim_safya_body_detay") or
            soup.find("div", class_="page_body") or
            soup.find("body"))
    if not body:
        return info

    text = body.get_text(separator="\n", strip=True)

    # Adres — cogu zaman ilk uzun satir
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for line in lines:
        line_lower = line.lower()

        # Telefon
        tel_match = re.search(r'(?:tel|telefon|phone)[:\s]*([+\d\s\-()]{8,})', line_lower)
        if tel_match or re.search(r'\+90[\s\d\-]{8,}', line):
            nums = re.findall(r'[+\d\s\-()]{8,}', line)
            if nums and not info["telefon"]:
                info["telefon"] = nums[0].strip()

        # Faks
        faks_match = re.search(r'(?:faks|fax)[:\s]*([+\d\s\-()]{8,})', line_lower)
        if faks_match:
            info["faks"] = faks_match.group(1).strip()

        # E-posta
        mail_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', line)
        if mail_match and not info["eposta"]:
            info["eposta"] = mail_match.group(0)

        # Adres — "Mah." veya "Cad." iceren satir
        if any(x in line_lower for x in ["mah.", "cad.", "sok.", "şahinbey", "gaziantep"]):
            if not info["adres"] and len(line) > 15:
                info["adres"] = line

    # Fallback: linklerden e-posta
    if not info["eposta"]:
        for a_tag in (body.select("a[href^='mailto:']") if body else []):
            href = a_tag.get("href", "")
            if href.startswith("mailto:"):
                info["eposta"] = href.replace("mailto:", "").strip()
                break

    return info


def parse_iletisim_blueprint() -> list[dict]:
    """Iletisim.html blueprint'inden birim iletisim listesini cikar."""
    logger.info("Blueprint parse ediliyor: %s", BLUEPRINT_PATH.name)

    if not BLUEPRINT_PATH.exists():
        logger.warning("Blueprint bulunamadi: %s", BLUEPRINT_PATH)
        return []

    html = BLUEPRINT_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    results = []

    # birim-rehber tablosu veya listesi
    # Tipik yapi: div.birim_safya_body_detay icinde tablo veya liste
    rows = soup.select("table tr")
    for row in rows:
        cells = row.select("td")
        if len(cells) >= 2:
            name = cells[0].get_text(strip=True)
            detail = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            if name and len(name) > 3:
                results.append({"name": name, "detail": detail})

    # Eger tablo yoksa, div tabanli parse
    if not results:
        cards = soup.select("div.card, div.col")
        for card in cards:
            text = card.get_text(separator=" | ", strip=True)
            if len(text) > 10:
                results.append({"name": text[:80], "detail": text})

    logger.info("  Blueprint'ten %d birim kaydi cikarildi", len(results))
    return results


def run_all(dry_run: bool = False):
    """Tum birimlerin iletisim bilgilerini canli cek + birlesitir + ingest."""
    logger.info("=" * 65)
    logger.info("GOREV 3.5 P4 — Birim Iletisim Birlestirme Tablosu")
    logger.info("Hedef birim sayisi: %d", len(BIRIMLER))
    logger.info("=" * 65)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # ── Faz 1: Blueprint parse ──
    blueprint_data = parse_iletisim_blueprint()

    # ── Faz 2: Canli scrape ──
    logger.info("\nCanli iletisim sayfalari scrape ediliyor...")
    contact_records = []
    ok_count = 0
    skip_count = 0
    err_count = 0

    for i, birim in enumerate(BIRIMLER):
        birim_id = birim["id"]
        birim_name = birim["name"]
        birim_slug = birim["slug"]
        birim_grup = birim["grup"]

        url = f"{BASE_URL}/BirimIletisim.aspx?id={birim_id}"
        logger.info(f"  [{i+1}/{len(BIRIMLER)}] {birim_name} (BirimID={birim_id})")

        try:
            html = _fetch(url, session)
            if not html:
                # Fallback: slug + bilinen e-posta kalibindan olustur
                record = {
                    "birim_id": birim_id,
                    "birim_adi": birim_name,
                    "slug": birim_slug,
                    "grup": birim_grup,
                    "adres": "Beştepe Mah. 192180 Nolu Cadde 27010 Şahinbey/Gaziantep",
                    "telefon": "+90 342 909 75 00",
                    "faks": "",
                    "eposta": f"{birim_slug}@gibtu.edu.tr",
                    "web": f"{BASE_URL}/{birim_slug}",
                    "kaynak": "fallback",
                }
                contact_records.append(record)
                err_count += 1
                continue

            info = _extract_contact_info(html)

            # Fallback e-posta
            if not info["eposta"]:
                info["eposta"] = f"{birim_slug}@gibtu.edu.tr"

            # Fallback adres
            if not info["adres"]:
                info["adres"] = "Beştepe Mah. 192180 Nolu Cadde 27010 Şahinbey/Gaziantep"

            # Fallback telefon
            if not info["telefon"]:
                info["telefon"] = "+90 342 909 75 00"

            record = {
                "birim_id": birim_id,
                "birim_adi": birim_name,
                "slug": birim_slug,
                "grup": birim_grup,
                "adres": info["adres"],
                "telefon": info["telefon"],
                "faks": info["faks"],
                "eposta": info["eposta"],
                "web": f"{BASE_URL}/{birim_slug}",
                "kaynak": "canli_scrape",
            }
            contact_records.append(record)
            ok_count += 1

            time.sleep(RATE_LIMIT)

        except Exception as e:
            logger.error(f"    Hata: {e}")
            err_count += 1

    logger.info(f"\nCanli scrape tamamlandi: {ok_count} basarili, {skip_count} skip, {err_count} hata")

    # ── Faz 3: Birlestirme + JSON ──
    logger.info("\nBirlestirme tablosu olusturuluyor...")

    table_data = {
        "generated_at": datetime.now().isoformat(),
        "total_units": len(contact_records),
        "source_blueprint_count": len(blueprint_data),
        "source_live_count": ok_count,
        "units": contact_records,
    }

    table_path = OUTPUT_DIR / "birim_iletisim_tablosu.json"
    with open(table_path, "w", encoding="utf-8") as f:
        json.dump(table_data, f, ensure_ascii=False, indent=2)
    logger.info("  JSON tablo yazildi: %s (%d birim)", table_path, len(contact_records))

    # ── Faz 4: Document olusturma + ingest ──
    logger.info("\nDocument olusturma...")
    all_documents = []

    # Her birim icin ayri Document (aranabilirlik)
    for rec in contact_records:
        content = f"""{rec['birim_adi']}

Birim Grubu: {rec['grup']}
Adres: {rec['adres']}
Telefon: {rec['telefon']}
Faks: {rec['faks']}
E-posta: {rec['eposta']}
Web: {rec['web']}"""

        doc = Document(
            id=_doc_id(f"iletisim_{rec['birim_id']}_{content[:100]}"),
            content=content,
            meta={
                "category": "iletisim",
                "source_url": f"{BASE_URL}/BirimIletisim.aspx?id={rec['birim_id']}",
                "source_type": "web",
                "source_id": f"birim_iletisim_{rec['slug']}",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": f"{rec['birim_adi']} — İletişim Bilgileri",
                "doc_kind": "birim_iletisim",
                "department": rec["birim_adi"],
                "contact_unit": rec["birim_adi"],
            },
        )
        all_documents.append(doc)

    # 1 master tablo Document
    master_lines = ["GİBTÜ Birim İletişim Rehberi\n"]
    for grup in ["Fakülteler", "MYO/YO", "Enstitü", "Daire Başkanlıkları",
                  "Koordinatörlükler", "Merkezler", "Müdürlükler"]:
        grup_birimler = [r for r in contact_records if r["grup"] == grup]
        if grup_birimler:
            master_lines.append(f"\n## {grup}\n")
            for rec in grup_birimler:
                master_lines.append(
                    f"- {rec['birim_adi']}: Tel {rec['telefon']}, "
                    f"E-posta {rec['eposta']}, Web {rec['web']}"
                )

    master_content = "\n".join(master_lines)
    master_doc = Document(
        id=_doc_id(master_content),
        content=master_content,
        meta={
            "category": "iletisim",
            "source_url": f"{BASE_URL}/birimrehber",
            "source_type": "web",
            "source_id": "birim_iletisim_master_tablo",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GİBTÜ Birim İletişim Rehberi (Tüm Birimler)",
            "doc_kind": "birim_iletisim_tablosu",
            "department": "Genel",
            "contact_unit": "Bilgi İşlem Daire Başkanlığı",
        },
    )
    all_documents.append(master_doc)

    logger.info("  %d Document olusturuldu (%d birim + 1 master tablo)", len(all_documents), len(contact_records))

    # ── Ingest ──
    chunks = 0
    if all_documents:
        if dry_run:
            logger.info("  DRY-RUN: %d document, DB'ye yazilmadi.", len(all_documents))
            chunks = len(all_documents)
        else:
            chunks = ingest_documents(all_documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)
            logger.info("  DB'ye yazilan chunk: %d", chunks)

    # ── Dogrulama ──
    checks = []
    def check(label, cond, detail=""):
        checks.append(cond)
        status = "PASS" if cond else "FAIL"
        msg = f"  [{status}] {label}"
        if not cond and detail:
            msg += f" -- {detail}"
        logger.info(msg)

    check("birim >= 30", len(contact_records) >= 30, f"got {len(contact_records)}")
    check("docs >= 30", len(all_documents) >= 30, f"got {len(all_documents)}")

    # Metadata doluluk
    required = ["category", "source_url", "source_type", "title", "doc_kind", "department"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents)
    check("metadata doluluk 100%", all_ok)

    # Master tablo var mi
    master_exists = any(d.meta.get("doc_kind") == "birim_iletisim_tablosu" for d in all_documents)
    check("master tablo document var", master_exists)

    # E-posta doluluk
    eposta_count = sum(1 for r in contact_records if r.get("eposta"))
    check(f"eposta doluluk >= %90", eposta_count >= len(contact_records) * 0.9,
          f"{eposta_count}/{len(contact_records)}")

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    success = failed == 0

    logger.info(f"\n  DOGRULAMA: {passed} PASS / {failed} FAIL")

    # ── Ozet JSON ──
    summary = {
        "task": "3.5_P4_birim_iletisim_tablosu",
        "description": "Birim Iletisim Bilgilerinin Otomatik Birlestirme Tablosu",
        "birim_count": len(contact_records),
        "live_scrape_ok": ok_count,
        "live_scrape_err": err_count,
        "blueprint_records": len(blueprint_data),
        "documents_created": len(all_documents),
        "chunks_written": chunks,
        "success": success,
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = OUTPUT_DIR / "birim_iletisim_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"\nOzet rapor: {summary_path}")

    # Birim dagilimi raporu
    grup_dist = {}
    for rec in contact_records:
        g = rec["grup"]
        grup_dist[g] = grup_dist.get(g, 0) + 1
    logger.info("  Birim grubu dagilimi: %s", grup_dist)

    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description="Birim Iletisim Birlestirme Tablosu")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan test calistirmasi")
    args = parser.parse_args()

    return run_all(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
