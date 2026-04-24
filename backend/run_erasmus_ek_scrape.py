"""
Gorev 3.3-B — Erasmus Ek Sayfalari Scrape
Mevcut Erasmus verilerine ek olarak anlasma listeleri ve detay sayfalari.
"""
import sys, hashlib, time, json, logging, io
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
import psycopg2, os
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BIRIM_ID = 45
CATEGORY = "erasmus"
DEPARTMENT = "Erasmus Koordinatorlugu"
CONTACT_UNIT = "Erasmus+ Koordinatorlugu"
CONTACT_INFO = "erasmus@gibtu.edu.tr"

# Ek Erasmus sayfalari (mevcut scrape'de eksik olanlar)
EXTRA_URLS = [
    # Duyuru detay sayfalari
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=33158",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=33036",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=33032",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=33013",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=32999",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=32962",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=33115",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31600",
    # Gelen ogrenci/personel bilgileri
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31580",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31588",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31589",
    # KA171 detay
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31590",
    "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=45&icid=31572",
    # Anlasma taslak + icerik
    "http://www.gibtu.edu.tr/erasmus/icerik/31664/ka171-ortak-ulkeler-listesi",
    "http://www.gibtu.edu.tr/erasmus/icerik/31555/icerme-destegi",
    "http://www.gibtu.edu.tr/erasmus/icerik/31437/giden-ogrenci",
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0)"})

def get_existing_urls():
    """DB'de zaten mevcut olan Erasmus source_url'lerini al."""
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT meta->>'source_url' FROM haystack_docs
        WHERE meta->>'category' = 'erasmus' AND meta->>'source_url' IS NOT NULL
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

def parse_page(html, url):
    if not html: return None, ""
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    body = extract_body_content(html)
    if not body or len(body.strip()) < 20:
        body = clean_html(html)
    return title, body

def main():
    print("=" * 65)
    print("3.3-B: Erasmus Ek Sayfalari Scrape")
    print("=" * 65)

    # Check existing URLs
    existing = get_existing_urls()
    print(f"  DB'de mevcut Erasmus URL: {len(existing)}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_docs = []
    new_count = 0; skip_count = 0; fail_count = 0

    for url in EXTRA_URLS:
        # Normalize URL for comparison
        norm = url.replace("http://", "https://").replace("&amp;", "&")
        already = any(norm in ex or ex in norm for ex in existing)
        if already:
            skip_count += 1
            logger.info(f"  [SKIP] Zaten DB'de: {url[:70]}")
            continue

        time.sleep(1.5)
        html = fetch(url)
        if not html:
            fail_count += 1; continue

        title, body = parse_page(html, url)
        if not body or len(body.strip()) < 20:
            skip_count += 1
            logger.info(f"  [SKIP] Cok kisa: {url[:60]}")
            continue

        new_count += 1
        doc_kind = "duyuru" if "icid" in url else "genel"
        if "icerik" in url.lower() and "icid" not in url:
            doc_kind = "rehber"
        doc_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
        meta = {
            "category": CATEGORY, "source_url": url,
            "source_type": "web",
            "source_id": f"gibtu_erasmus_ek_{doc_id[:8]}",
            "last_updated": now,
            "title": title or f"Erasmus+ Ek Sayfa",
            "doc_kind": doc_kind, "language": "tr",
            "department": DEPARTMENT,
            "contact_unit": CONTACT_UNIT,
            "contact_info": CONTACT_INFO,
            "birim_id": BIRIM_ID,
        }
        all_docs.append(Document(id=doc_id, content=body, meta=meta))
        logger.info(f'  [NEW] "{title[:50]}" | {len(body)} kar.')

    print(f"\nToplam: {len(all_docs)} yeni | {skip_count} skip | {fail_count} fail")
    written = 0
    if all_docs:
        written = ingest_documents(all_docs, policy=DuplicatePolicy.OVERWRITE)
        print(f"DB'ye {written} chunk yazildi")

    summary = {
        "task": "3.3-B", "description": "Erasmus Ek Sayfalari",
        "new_pages": new_count, "skipped": skip_count,
        "failed": fail_count, "total_written": written,
    }
    out = Path(__file__).parent / "scrapers" / "erasmus_ek_summary.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Ozet: {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
