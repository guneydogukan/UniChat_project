"""
Görev 3.3-A — Lisansüstü Eğitim Enstitüsü Ek Yönetmelik Scrape
BirimID=35, haritasız doğrudan canlı scrape.
"""
import sys, hashlib, time, json, logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.map_guided_scraper import MapGuidedScraper, BASE_URL
from scrapers.blueprint_parser import extract_body_content
from scrapers.utils import clean_html
from bs4 import BeautifulSoup
import requests
from app.ingestion.loader import ingest_documents
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BIRIM_ID = 35
CATEGORY = "lisansustu"
DEPARTMENT = "Lisansustu Egitim Enstitusu"
CONTACT_UNIT = "Lisansustu Egitim Enstitusu"
CONTACT_INFO = "enstitu@gibtu.edu.tr"

# Bilinen Lisansüstü sayfaları (BirimID=35)
TARGET_URLS = [
    f"https://www.gibtu.edu.tr/Birim.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimYonetim.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimMevzuat.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimForm.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimIletisim.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimTelefonRehberi.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimDuyuru.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimHaber.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimDuyuruArsivi.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimRapor.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimMisyon.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimFaydaliLink.aspx?id={BIRIM_ID}",
    f"https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id={BIRIM_ID}",
]

URL_DOC_KIND = {
    "birimyonetim": "yonetim", "birimmevzuat": "yonetmelik",
    "birimform": "form", "birimiletisim": "iletisim",
    "birimtelefonrehberi": "iletisim", "birimduyuru": "duyuru",
    "birimhaber": "haber", "birimduyuruarsivi": "duyuru",
    "birimrapor": "rapor", "birimmisyon": "tanitim",
    "birimfaydalilink": "genel", "birimakademikpersonel": "personel",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0)"})

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

def infer_doc_kind(url):
    url_l = url.lower()
    for pat, dk in URL_DOC_KIND.items():
        if pat in url_l:
            return dk
    return "genel"

def parse_page(html, url):
    if not html: return None, "", [], []
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    # Try birim_safya_body_detay first
    body = extract_body_content(html)
    if not body or len(body.strip()) < 20:
        body = clean_html(html)
    # Discover sidebar links
    new_urls = []
    pdfs = []
    sidebar = soup.select("span.birim-menu a, span#birim-menu-slide a, ul.collapsible a")
    for a in sidebar:
        href = a.get("href","")
        if not href or href.startswith("#"): continue
        if not href.startswith("http"):
            href = f"https://www.gibtu.edu.tr/{href.lstrip('/')}"
        text = a.get_text(strip=True)
        if href.lower().endswith(".pdf"):
            pdfs.append({"text": text, "url": href})
        elif "gibtu.edu.tr" in href and f"id={BIRIM_ID}" in href:
            new_urls.append(href.split("#")[0])
    return title, body, new_urls, pdfs

def main():
    print("=" * 65)
    print("3.3-A: Lisansüstü Eğitim Enstitüsü — Canlı Scrape")
    print("=" * 65)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_docs = []
    all_pdfs = []
    visited = set()
    queue = list(TARGET_URLS)
    valid = 0; failed = 0; skipped = 0

    idx = 0
    while idx < len(queue):
        url = queue[idx]; idx += 1
        clean_url = url.split("#")[0]
        if clean_url in visited: continue
        visited.add(clean_url)

        logger.info(f"[{len(visited)}/{len(queue)}] {url[:90]}")
        time.sleep(1.5)
        html = fetch(url)
        if not html:
            failed += 1; continue

        title, body, new_urls, pdfs = parse_page(html, url)
        all_pdfs.extend(pdfs)

        if not body or len(body.strip()) < 20:
            skipped += 1
            logger.info(f"  ⏭ Çok kısa: {len(body or '')} karakter")
            continue

        valid += 1
        doc_kind = infer_doc_kind(url)
        doc_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
        meta = {
            "category": CATEGORY,
            "source_url": url,
            "source_type": "web",
            "source_id": f"gibtu_lisansustu_{BIRIM_ID}_{doc_id[:8]}",
            "last_updated": now,
            "title": title or f"Lisansüstü — Sayfa",
            "doc_kind": doc_kind,
            "language": "tr",
            "department": DEPARTMENT,
            "contact_unit": CONTACT_UNIT,
            "contact_info": CONTACT_INFO,
            "birim_id": BIRIM_ID,
        }
        all_docs.append(Document(id=doc_id, content=body, meta=meta))
        logger.info(f'  ✅ "{title[:50]}" | {len(body)} kar. | {doc_kind}')

        # Add discovered sidebar URLs to queue
        for nu in new_urls:
            if nu not in visited and nu not in queue:
                queue.append(nu)

    # PDF download & parse
    unique_pdfs = {p["url"]: p for p in all_pdfs}
    logger.info(f"\n📄 {len(unique_pdfs)} PDF keşfedildi, indiriliyor...")
    from app.ingestion.pdf_parser import parse_pdf
    import tempfile, os
    for pdf_info in unique_pdfs.values():
        try:
            r = SESSION.get(pdf_info["url"], timeout=30)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=".") as f:
                f.write(r.content)
                tmp_path = f.name
            pdf_docs = parse_pdf(tmp_path, doc_kind="yonetmelik")
            for d in pdf_docs:
                d.meta.update({
                    "category": CATEGORY, "department": DEPARTMENT,
                    "contact_unit": CONTACT_UNIT, "contact_info": CONTACT_INFO,
                    "source_url": pdf_info["url"],
                    "title": pdf_info["text"] or "Lisansüstü PDF",
                    "doc_kind": "yonetmelik", "birim_id": BIRIM_ID,
                })
            all_docs.extend(pdf_docs)
            logger.info(f'  📄 {pdf_info["text"][:40]} → {len(pdf_docs)} doc')
            os.unlink(tmp_path)
        except Exception as e:
            logger.warning(f'  ❌ PDF hata: {pdf_info["url"][:60]} — {e}')

    # Ingest
    print(f"\n{'='*65}")
    print(f"Toplam: {len(all_docs)} document | Valid: {valid} | Failed: {failed} | Skip: {skipped}")
    print(f"PDF: {len(unique_pdfs)} | Keşfedilen URL: {len(visited)}")

    if all_docs:
        written = ingest_documents(all_docs, policy=DuplicatePolicy.OVERWRITE)
        print(f"✅ DB'ye {written} chunk yazıldı")
    else:
        print("⚠️ Yüklenecek belge yok")
        written = 0

    # Summary JSON
    summary = {
        "task": "3.3-A", "description": "Lisansustu Ek Yonetmelik Scrape",
        "birim_id": BIRIM_ID, "total_valid": valid, "total_failed": failed,
        "total_skipped": skipped, "total_documents": len(all_docs),
        "total_written": written, "pdf_count": len(unique_pdfs),
        "urls_visited": len(visited),
    }
    out = Path(__file__).parent / "scrapers" / "lisansustu_summary.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"📄 Özet: {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
