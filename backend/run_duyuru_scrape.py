"""
Gorev 3.2.20 — Duyuru ve Haber Arsivleri: Canli Scrape

Harita gerek yok — duyuru URL kalibi belli:
  Arsiv:  BirimDuyuruArsivi.aspx?id={BirimID}&k=duyuru  (veya k=haber)
  Detay:  BirimIcerik.aspx?id={BirimID}&icid={ContentID}

Strateji:
  1) Bilinen BirimID'lerle arsiv sayfalarini tara (son 15 sayfa siniri)
  2) Her arsiv sayfasindaki duyuru kartlarindan detay URL'lerini topla
  3) Her detay sayfasini canli scrape et -> Document olustur
  4) Tum Document'lari DB'ye yaz (category=duyurular, doc_kind=duyuru/haber)

Sayfalama kalıbı: &p=1, &p=2, ... (sayfa numarası)
  Eger sayfa bos gelirse veya duyuru yoksa dur.
"""
import sys
import argparse
import json
import hashlib
import time
import logging
import re
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
MAX_PAGES_FULL = 15
MAX_PAGES_DELTA = 3
MAX_PAGES = MAX_PAGES_FULL  # default, overridden by CLI
RATE_LIMIT = 1.2  # seconds between requests
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0)"

# Birimler — kesif raporundan dogrulanmis BirimID'ler
# Rektorluk (1) ana duyuru kaynagi; diger onemli birimler de eklendi
DUYURU_BIRIMLERI = [
    {"id": 1,   "slug": "rektorluk",           "name": "Rektorluk",               "k": "duyuru"},
    {"id": 1,   "slug": "rektorluk",           "name": "Rektorluk",               "k": "haber"},
    {"id": 15,  "slug": "mdbf",                "name": "Muhendislik ve Doga Bil.", "k": "duyuru"},
    {"id": 11,  "slug": "ilahiyatfakultesi",   "name": "Ilahiyat Fakultesi",      "k": "duyuru"},
    {"id": 20,  "slug": "tip",                 "name": "Tip Fakultesi",           "k": "duyuru"},
    {"id": 21,  "slug": "sbf",                 "name": "Saglik Bilimleri Fak.",   "k": "duyuru"},
    {"id": 22,  "slug": "iii",                 "name": "IISBF",                   "k": "duyuru"},
    {"id": 24,  "slug": "gsmf",                "name": "Guzel Sanatlar Fak.",     "k": "duyuru"},
    {"id": 4,   "slug": "ogrenciisleri",       "name": "Ogrenci Isleri",          "k": "duyuru"},
    {"id": 8,   "slug": "sks",                 "name": "SKS",                     "k": "duyuru"},
    {"id": 31,  "slug": "shmyo",               "name": "Saglik Hizmetleri MYO",   "k": "duyuru"},
    {"id": 36,  "slug": "teknikbilimler",      "name": "Teknik Bilimler MYO",     "k": "duyuru"},
]


def _doc_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fetch(url: str, session: requests.Session) -> str | None:
    """Canli fetch with retry + encoding fallback."""
    for attempt in range(1, 4):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            # Encoding fix for Turkish
            if not resp.encoding or resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if e.response is not None and 400 <= e.response.status_code < 500:
                logger.warning(f"  HTTP {status} (kalici hata): {url}")
                return None
            logger.warning(f"  HTTP {status} deneme {attempt}/3: {url}")
        except Exception as e:
            logger.warning(f"  Hata deneme {attempt}/3: {e}")
        if attempt < 3:
            time.sleep(2 * attempt)
    return None


def _clean_text(html_text: str) -> str:
    """Boilerplate-free temiz metin cikar."""
    soup = BeautifulSoup(html_text, "html.parser")
    
    # Remove boilerplate
    for sel in ["nav", "footer", "header", "script", "style", "noscript",
                ".side-nav", ".birim-menu", "#birim-menu-slide",
                ".breadcrumb", ".footer", ".ust-menu"]:
        for el in soup.select(sel):
            el.decompose()
    
    # Ana icerik bolgesi
    body = (soup.find("div", class_="birim_safya_body_detay") or
            soup.find("div", class_="page_body") or
            soup.find("section", class_="birim_safya_body") or
            soup.find("div", class_="container") or
            soup.find("body"))
    
    if not body:
        return ""
    
    text = body.get_text(separator="\n", strip=True)
    # Multi-whitespace cleanup
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 2]
    return "\n".join(lines)


def _extract_title_from_detail(html_text: str) -> str:
    """Detay sayfasindan baslik cikar."""
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 1. span.sayfa_baslik
    el = soup.select_one("span.sayfa_baslik")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    
    # 2. div.card-panel > span
    el = soup.select_one("div.card-panel span")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    
    # 3. h1
    el = soup.find("h1")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    
    # 4. title tag
    el = soup.find("title")
    if el:
        t = el.get_text(strip=True)
        # Remove " - GİBTÜ" suffix
        t = re.sub(r"\s*[-–]\s*G[İi]BT[ÜU].*$", "", t)
        if t:
            return t
    
    return "Duyuru"


def phase1_scrape_archives(session: requests.Session):
    """Arsiv sayfalarindan tum duyuru detay URL'lerini topla."""
    logger.info("=" * 65)
    logger.info("FAZ 1: Duyuru Arsiv Sayfalarini Tara (son %d sayfa)", MAX_PAGES)
    logger.info("=" * 65)
    
    all_items = []  # (detail_url, title, date_str, birim_name, kind)
    seen_urls = set()
    total_archive_pages = 0
    
    for birim in DUYURU_BIRIMLERI:
        birim_id = birim["id"]
        birim_name = birim["name"]
        kind = birim["k"]
        
        logger.info(f"\n  [{birim_name}] BirimID={birim_id}, k={kind}")
        birim_items = 0
        empty_streak = 0
        
        for page_num in range(1, MAX_PAGES + 1):
            archive_url = f"{BASE_URL}/BirimDuyuruArsivi.aspx?id={birim_id}&k={kind}&p={page_num}"
            
            html = _fetch(archive_url, session)
            if not html:
                logger.info(f"    Sayfa {page_num}: fetch basarisiz, birim sonu")
                break
            
            total_archive_pages += 1
            soup = BeautifulSoup(html, "html.parser")
            
            # Duyuru kartlarini bul
            cards = soup.select("div.card.horizontal.hoverable")
            if not cards:
                # Alternatif: a etiketleri icinde card
                cards_a = soup.select("a[href*='BirimIcerik']")
                if not cards_a:
                    empty_streak += 1
                    if empty_streak >= 2:
                        logger.info(f"    Sayfa {page_num}: bos, birim sonu")
                        break
                    continue
                
                # a etiketlerinden detay URL'lerini cikar
                for a_tag in cards_a:
                    href = a_tag.get("href", "")
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = f"{BASE_URL}/{href.lstrip('/')}"
                    
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    
                    # Baslik
                    title_el = a_tag.select_one("div.duyuru-baslik")
                    title = title_el.get_text(strip=True) if title_el else "Duyuru"
                    
                    # Tarih
                    gun_el = a_tag.select_one("span.gun")
                    ay_el = a_tag.select_one("span.ay")
                    date_str = ""
                    if gun_el and ay_el:
                        date_str = f"{gun_el.get_text(strip=True)} {ay_el.get_text(strip=True)}"
                    
                    all_items.append((href, title, date_str, birim_name, kind))
                    birim_items += 1
                
                empty_streak = 0
                continue
            
            empty_streak = 0
            
            for card in cards:
                # Parent <a> tag
                parent_a = card.find_parent("a")
                if parent_a:
                    href = parent_a.get("href", "")
                else:
                    a_tag = card.find("a")
                    href = a_tag.get("href", "") if a_tag else ""
                
                if not href:
                    continue
                if not href.startswith("http"):
                    href = f"{BASE_URL}/{href.lstrip('/')}"
                
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                # Baslik
                title_el = card.select_one("div.duyuru-baslik")
                title = title_el.get_text(strip=True) if title_el else "Duyuru"
                
                # Tarih
                gun_el = card.select_one("span.gun")
                ay_el = card.select_one("span.ay")
                date_str = ""
                if gun_el and ay_el:
                    date_str = f"{gun_el.get_text(strip=True)} {ay_el.get_text(strip=True)}"
                
                all_items.append((href, title, date_str, birim_name, kind))
                birim_items += 1
            
            time.sleep(RATE_LIMIT)
        
        logger.info(f"    [{birim_name}] {birim_items} duyuru/haber tespit edildi")
    
    logger.info(f"\n  TOPLAM: {len(all_items)} duyuru/haber URL, {total_archive_pages} arsiv sayfasi tarandi")
    return all_items


def phase2_scrape_details(items, session: requests.Session):
    """Her detay sayfasini canli scrape et, Document olustur."""
    logger.info("\n" + "=" * 65)
    logger.info("FAZ 2: Detay Sayfalarini Scrape Et (%d sayfa)", len(items))
    logger.info("=" * 65)
    
    documents = []
    ok_count = 0
    skip_count = 0
    err_count = 0
    
    for i, (url, card_title, date_str, birim_name, kind) in enumerate(items):
        try:
            html = _fetch(url, session)
            if not html:
                err_count += 1
                continue
            
            content = _clean_text(html)
            if len(content) < 30:
                skip_count += 1
                continue
            
            # Baslik: detay sayfasindan cikar, fallback: kart basligi
            page_title = _extract_title_from_detail(html)
            if page_title in ("Duyuru", "Haber", ""):
                page_title = card_title
            
            # doc_kind belirle
            doc_kind = "duyuru" if kind == "duyuru" else "haber"
            
            # Unique source_id
            safe_title = re.sub(r'[^a-z0-9]', '_', page_title.lower()[:50])
            source_id = f"duyuru_{birim_name.lower().replace(' ','_')[:20]}_{safe_title}"
            
            doc = Document(
                id=_doc_id(f"{url}_{content[:200]}"),
                content=content[:30000],
                meta={
                    "category": "duyurular",
                    "source_url": url,
                    "source_type": "web",
                    "source_id": source_id,
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "title": page_title,
                    "doc_kind": doc_kind,
                    "department": birim_name,
                    "contact_unit": birim_name,
                    "announcement_date": date_str,
                    "announcement_type": kind,
                },
            )
            documents.append(doc)
            ok_count += 1
            
            # Progress her 20 sayfada bir
            if (i + 1) % 20 == 0:
                logger.info(f"  Ilerleme: {i+1}/{len(items)} islem ({ok_count} ok, {skip_count} skip, {err_count} err)")
            
            time.sleep(RATE_LIMIT)
            
        except Exception as e:
            logger.error(f"  Hata {url}: {e}")
            err_count += 1
    
    logger.info(f"\n  Detay scrape tamamlandi: {ok_count} basarili, {skip_count} skip, {err_count} hata")
    return documents


def phase3_ingest(all_documents):
    """Document'lari DB'ye yaz."""
    logger.info("\n" + "=" * 65)
    logger.info("FAZ 3: DB Yukleme (%d Document)", len(all_documents))
    logger.info("=" * 65)
    
    if not all_documents:
        logger.warning("  Yuklenecek document yok!")
        return 0
    
    result = ingest_documents(all_documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)
    logger.info(f"  Yazilan chunk: {result}")
    return result


def phase4_validation(all_documents, chunks_written):
    """Dogrulama kontrolleri."""
    logger.info("\n" + "=" * 65)
    logger.info("FAZ 4: Dogrulama")
    logger.info("=" * 65)
    
    checks = []
    
    def check(label, cond, detail=""):
        checks.append(cond)
        status = "PASS" if cond else "FAIL"
        msg = f"  [{status}] {label}"
        if not cond and detail:
            msg += f" -- {detail}"
        logger.info(msg)
    
    # Minimum document sayisi
    check("docs >= 10", len(all_documents) >= 10, f"got {len(all_documents)}")
    
    # chunks > 0
    check("chunks > 0", chunks_written > 0, f"got {chunks_written}")
    
    # Metadata doluluk
    required = ["category", "source_url", "source_type", "title", "doc_kind", "department"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents)
    check("metadata doluluk 100%", all_ok)
    
    # category=duyurular
    cats = set(d.meta.get("category") for d in all_documents)
    check("category=duyurular", "duyurular" in cats)
    
    # doc_kind distribution
    kinds = {}
    for d in all_documents:
        k = d.meta.get("doc_kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    check("doc_kind duyuru/haber varlik", "duyuru" in kinds or "haber" in kinds,
          f"kinds={kinds}")
    
    # Birim dagilimi
    depts = {}
    for d in all_documents:
        dep = d.meta.get("department", "?")
        depts[dep] = depts.get(dep, 0) + 1
    
    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    logger.info(f"\n  SONUC: {passed} PASS / {failed} FAIL")
    logger.info(f"  doc_kind dagilimi: {kinds}")
    logger.info(f"  birim dagilimi: {depts}")
    
    return failed == 0


def main():
    global MAX_PAGES

    parser = argparse.ArgumentParser(description="Duyuru ve Haber Arsivleri Canli Scrape")
    parser.add_argument(
        "--mode", choices=["full", "delta"], default="full",
        help="full: tum arsiv (15 sayfa), delta: son 3 sayfa (periyodik guncelleme)"
    )
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan calistir")
    args = parser.parse_args()

    # Mode'a gore MAX_PAGES ayarla
    if args.mode == "delta":
        MAX_PAGES = MAX_PAGES_DELTA
        logger.info("DELTA modu: son %d sayfa taranacak", MAX_PAGES)
    else:
        MAX_PAGES = MAX_PAGES_FULL
        logger.info("FULL modu: son %d sayfa taranacak", MAX_PAGES)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    
    # Faz 1: Arsiv sayfalarindan detay URL'lerini topla
    items = phase1_scrape_archives(session)
    
    if not items:
        logger.error("Hic duyuru/haber bulunamadi!")
        return 1
    
    # Faz 2: Detay sayfalarini scrape et
    documents = phase2_scrape_details(items, session)
    
    if not documents:
        logger.error("Hic Document olusturulamadi!")
        return 1
    
    # Faz 3: DB'ye yaz
    if args.dry_run:
        logger.info("DRY-RUN: %d document olusturuldu, DB'ye yazilmadi.", len(documents))
        chunks = len(documents)
    else:
        chunks = phase3_ingest(documents)
    
    # Faz 4: Dogrulama
    success = phase4_validation(documents, chunks)
    
    # Ozet
    logger.info("\n" + "=" * 65)
    status = "TAMAMLANDI" if success else "BASARISIZ"
    logger.info(f"GOREV 3.2.20 -- Duyuru ve Haber Arsivleri ({args.mode.upper()}) {status}!")
    logger.info("=" * 65)
    
    summary = {
        "task": "3.2.20",
        "description": f"Duyuru ve Haber Arsivleri Canli Scrape ({args.mode})",
        "mode": args.mode,
        "max_pages": MAX_PAGES,
        "archive_items": len(items),
        "documents_created": len(documents),
        "chunks_written": chunks,
        "birim_count": len(DUYURU_BIRIMLERI),
        "success": success,
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = OUTPUT_DIR / "duyuru_haber_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"\nOzet rapor: {summary_path}")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
