"""
Gorev 3.4-B — Akademik Kadro Detay Sayfalari Scrape
Bilinen fakülte BirimID'lerinden BirimAkademikPersonel sayfalarini ceker.
Mevcut 'personel' doc_kind verileri ile karsilastirip eksik olanlari ekler.
"""
import sys, io, hashlib, time, json, logging, os
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import extract_body_content
from scrapers.utils import clean_html
from bs4 import BeautifulSoup
import requests
from app.ingestion.loader import ingest_documents
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy
import psycopg2
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tum fakülte/birim -> BirimID eslemesi
BIRIM_MAP = {
    # Fakulteler
    "Muhendislik ve Doga Bilimleri Fakultesi": 3,
    "Guzel Sanatlar Tasarim ve Mimarlik Fakultesi": 2,
    "Iktisadi Idari ve Sosyal Bilimler Fakultesi": 4,
    "Ilahiyat Fakultesi": 5,
    "Saglik Bilimleri Fakultesi": 6,
    "Tip Fakultesi": 7,
    # Enstitu
    "Lisansustu Egitim Enstitusu": 35,
    # Yuksekokullar & MYO
    "Yabanci Diller Yuksekokulu": 9,
    "Saglik Hizmetleri MYO": 10,
    "Teknik Bilimler MYO": 11,
    # Koordinatorlukler
    "Erasmus Koordinatorlugu": 45,
    "Dis Iliskiler Koordinatorlugu": 79,
    # Daire Baskanliklari
    "Saglik Kultur ve Spor Daire Baskanligi": 8,
    "Kutuphane ve Dokumantasyon Daire Baskanligi": 12,
    "Ogrenci Isleri Daire Baskanligi": 13,
    "Bilgi Islem Daire Baskanligi": 14,
    "Strateji Gelistirme Daire Baskanligi": 15,
    "Personel Daire Baskanligi": 16,
    "Idari ve Mali Isler Daire Baskanligi": 17,
    "Yapi Isleri ve Teknik Daire Baskanligi": 18,
    "Hukuk Musavirligi": 19,
    # Rektorluk birimleri
    "Kalite ve Akreditasyon Koordinatorlugu": 80,
    "Uzaktan Egitim Merkezi": 81,
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0)"})


def get_existing_personel_urls():
    """DB'de halihazirda olan personel source_url'lerini al."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT meta->>'source_url' FROM haystack_docs
        WHERE meta->>'doc_kind' = 'personel' AND meta->>'source_url' IS NOT NULL
    """)
    urls = {r[0] for r in cur.fetchall()}
    cur.close(); conn.close()
    return urls


def fetch(url):
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=30)
            r.raise_for_status()
            if not r.encoding or r.encoding.upper() in ("ISO-8859-1","ASCII"):
                r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            logger.warning(f"  Fetch error ({attempt+1}/3): {e}")
            time.sleep(2*(attempt+1))
    return None


def parse_akademik_page(html, url):
    """Akademik personel sayfasini parse eder."""
    if not html:
        return None, ""
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    body = extract_body_content(html)
    if not body or len(body.strip()) < 20:
        body = clean_html(html)
    return title, body


def main():
    print("=" * 65)
    print("3.4-B: Akademik Kadro Detay Sayfalari Scrape")
    print("=" * 65)

    existing_urls = get_existing_personel_urls()
    print(f"  DB'de mevcut personel URL: {len(existing_urls)}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_docs = []
    new_count = 0; skip_count = 0; fail_count = 0

    # Her birim icin BirimAkademikPersonel ve BirimIdariPersonel cek
    page_types = [
        ("BirimAkademikPersonel.aspx", "akademik_personel"),
        ("BirimIdariPersonel.aspx", "idari_personel"),
    ]

    for dept_name, birim_id in BIRIM_MAP.items():
        for page_template, page_label in page_types:
            url = f"https://www.gibtu.edu.tr/{page_template}?id={birim_id}"

            # Zaten var mi kontrol
            if url in existing_urls:
                skip_count += 1
                continue

            time.sleep(1.2)
            html = fetch(url)
            if not html:
                fail_count += 1
                logger.info(f"  [FAIL] {dept_name} - {page_label}")
                continue

            title, body = parse_akademik_page(html, url)
            if not body or len(body.strip()) < 30:
                skip_count += 1
                logger.info(f"  [SKIP] {dept_name} - {page_label}: cok kisa ({len(body or '')} kar.)")
                continue

            new_count += 1
            doc_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
            meta = {
                "category": "genel_bilgi",
                "source_url": url,
                "source_type": "web",
                "source_id": f"gibtu_personel_{birim_id}_{page_label}",
                "last_updated": now,
                "title": f"{dept_name} - {page_label.replace('_', ' ').title()}",
                "doc_kind": "personel",
                "language": "tr",
                "department": dept_name,
                "contact_unit": dept_name,
                "contact_info": "",
                "birim_id": birim_id,
            }
            all_docs.append(Document(id=doc_id, content=body, meta=meta))
            logger.info(f'  [NEW] {dept_name} - {page_label} | {len(body)} kar.')

    print(f"\nToplam: {len(all_docs)} yeni | {skip_count} skip | {fail_count} fail")

    written = 0
    if all_docs:
        written = ingest_documents(all_docs, policy=DuplicatePolicy.OVERWRITE)
        print(f"DB'ye {written} chunk yazildi")
    else:
        print("Yeni veri yok (tum personel verileri zaten mevcut)")

    summary = {
        "task": "3.4-B", "description": "Akademik Kadro Detay Sayfalari",
        "new_pages": new_count, "skipped": skip_count,
        "failed": fail_count, "total_written": written,
        "birim_count": len(BIRIM_MAP),
    }
    out = Path(__file__).parent / "scrapers" / "akademik_kadro_summary.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Ozet: {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
