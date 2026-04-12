"""
Gorev 3.2.14 — Genel Yapi ve Iletisim: Harita Gudumlu Deep Scrape

GİBTU_genel_üniversite_yapısı.html -> navigasyon menusunden slug URL'leri cikar
Iletisim.html -> statik iletisim bilgileri + birim dropdown listesini cikar

Bu dosyalar standard birim-menu sidebar formatinda degil,
dolayisiyla blueprint_parser yerine dogrudan BS4 parse + canli scrape yapilir.
"""
import sys
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.map_guided_scraper import MapGuidedScraper
from app.ingestion.loader import ingest_documents, DuplicatePolicy
from haystack import Document

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"

BASE_URL = "https://www.gibtu.edu.tr"


def _generate_doc_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ─── Genel Yapi: Kurumsal Kimlik slug sayfalarini scrape et ───
def extract_slug_urls_from_genel():
    """GİBTU_genel HTML'sinden scrape edilebilir slug URL'lerini cikar."""
    html_path = GIBTU / "GİBTU_genel_üniversite_yapısı.html"
    if not html_path.exists():
        print(f"[SKIP] {html_path.name} bulunamadi")
        return []

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = a.get_text(strip=True)

        # Full gibtu.edu.tr URLs
        if href.startswith("https://www.gibtu.edu.tr/") or href.startswith("http://www.gibtu.edu.tr/"):
            url = href
        elif href.startswith("Birim.aspx"):
            # These are birim pages already scraped in other tasks
            continue
        elif href.startswith("Default.aspx") or href.startswith("#"):
            continue
        else:
            continue

        # Skip subdomain URLs (ubys, adayogrenci, etc.)
        if "ubys." in url or "adayogrenci." in url:
            continue

        # Skip already-scraped birim pages
        if "/Birim.aspx" in url or "/BirimIcerik.aspx" in url or "/BirimYonetim.aspx" in url:
            continue

        # Skip PDF/media links
        if any(url.lower().endswith(ext) for ext in [".pdf", ".docx", ".xlsx", ".png", ".jpg"]):
            continue

        # Normalize
        url_norm = url.split("#")[0].split("?")[0].rstrip("/").lower()
        if url_norm not in seen:
            seen.add(url_norm)
            urls.append({"url": url, "label": label})

    return urls


def phase1_scrape_genel_slug_pages():
    """Genel yapidaki slug sayfalarini canli scrape et."""
    print("=" * 65)
    print("FAZ 1: Genel Yapi — Slug Sayfa Scrape")
    print("=" * 65)

    slug_urls = extract_slug_urls_from_genel()
    print(f"  Tespit edilen slug URL: {len(slug_urls)}")
    for u in slug_urls:
        print(f"    {u['label'][:40]:40s} -> {u['url'][:60]}")

    import requests

    documents = []
    for entry in slug_urls:
        url = entry["url"]
        label = entry["label"]
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "UniChat/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try to get main content
            body = soup.find("div", class_="page_body") or soup.find("section", class_="birim_safya_body") or soup.find("div", class_="container")
            if body:
                text = body.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            # Clean boilerplate
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            # Remove very short boilerplate
            cleaned = "\n".join(l for l in lines if len(l) > 3)
            if len(cleaned) < 30:
                print(f"    [SKIP] {label} — cok kisa ({len(cleaned)} kar)")
                continue

            doc = Document(
                id=_generate_doc_id(url),
                content=cleaned[:50000],  # Cap at 50K
                meta={
                    "category": "genel_bilgi",
                    "source_url": url,
                    "source_type": "web",
                    "source_id": f"genel_{label.lower().replace(' ', '_')[:30]}",
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "title": label,
                    "doc_kind": "genel",
                    "department": "GIBTU Genel",
                    "contact_unit": "Rektorluk",
                    "contact_info": "info@gibtu.edu.tr",
                },
            )
            documents.append(doc)
            print(f"    [OK] {label} — {len(cleaned):,} kar")
        except Exception as e:
            print(f"    [ERR] {label} — {e}")

    return documents


def phase2_iletisim_content():
    """Iletisim HTML'sinden statik bilgileri Document olarak olustur."""
    print("\n" + "=" * 65)
    print("FAZ 2: Iletisim Bilgileri")
    print("=" * 65)

    html_path = GIBTU / "İletişim.html"
    if not html_path.exists():
        print(f"  [SKIP] {html_path.name} bulunamadi")
        return []

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    # Extract contact info
    iletisim_items = []
    for li in soup.select("ul.iletisim-bilgileri li"):
        text = li.get_text(strip=True)
        if text:
            iletisim_items.append(text)

    iletisim_text = "GİBTÜ İletişim Bilgileri\n\n" + "\n".join(iletisim_items)
    print(f"  İletişim metin: {len(iletisim_text)} karakter")

    # Extract birim list from dropdown (comprehensive birim directory)
    birim_list = []
    for option in soup.select("select#ddl_birim option"):
        val = option.get("value", "")
        name = option.get_text(strip=True)
        if val and val != "-1" and val != "0" and name:
            birim_list.append(f"BirimID={val}: {name}")

    birim_text = "GİBTÜ Birim Rehberi (Tüm Birimler)\n\n" + "\n".join(birim_list)
    print(f"  Birim rehberi: {len(birim_list)} birim, {len(birim_text)} karakter")

    documents = []

    # İletişim document
    doc1 = Document(
        id=_generate_doc_id("gibtu_iletisim_genel"),
        content=iletisim_text,
        meta={
            "category": "genel_bilgi",
            "source_url": "https://www.gibtu.edu.tr/iletisim",
            "source_type": "web",
            "source_id": "gibtu_iletisim",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Iletisim Bilgileri",
            "doc_kind": "iletisim",
            "department": "GIBTU Genel",
            "contact_unit": "Rektorluk",
            "contact_info": "info@gibtu.edu.tr",
        },
    )
    documents.append(doc1)

    # Birim Rehberi document
    doc2 = Document(
        id=_generate_doc_id("gibtu_birim_rehberi"),
        content=birim_text,
        meta={
            "category": "genel_bilgi",
            "source_url": "https://www.gibtu.edu.tr/iletisim",
            "source_type": "web",
            "source_id": "gibtu_birim_rehberi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Birim Rehberi",
            "doc_kind": "yonlendirme",
            "department": "GIBTU Genel",
            "contact_unit": "Rektorluk",
            "contact_info": "info@gibtu.edu.tr",
        },
    )
    documents.append(doc2)

    # RİMER info
    rimer_text = (
        "RİMER - Rektörlük İletişim Merkezi\n\n"
        "RİMER'e gönderilen iletiler 6698 sayılı KVKK - Kişisel Verilerin Korunması "
        "Kanunu gereğince 3. şahıslarla paylaşılmaz.\n\n"
        "Konu seçenekleri: Bilgi Edinme, Diğer, İstek, Öneri, Şikayet\n\n"
        "İletişim web adresi: https://www.gibtu.edu.tr/iletisim"
    )
    doc3 = Document(
        id=_generate_doc_id("gibtu_rimer"),
        content=rimer_text,
        meta={
            "category": "genel_bilgi",
            "source_url": "https://www.gibtu.edu.tr/iletisim",
            "source_type": "web",
            "source_id": "gibtu_rimer",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "RIMER - Rektorluk Iletisim Merkezi",
            "doc_kind": "iletisim",
            "department": "GIBTU Genel",
            "contact_unit": "Rektorluk",
            "contact_info": "info@gibtu.edu.tr",
        },
    )
    documents.append(doc3)

    return documents


def phase3_ingest(all_documents):
    """DB'ye yukle."""
    print("\n" + "=" * 65)
    print("FAZ 3: DB Yukleme")
    print("=" * 65)
    print(f"  Toplam Document: {len(all_documents)}")
    if not all_documents:
        print("  [WARN] Yuklenecek document yok!")
        return 0

    result = ingest_documents(all_documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)
    print(f"  Yazilan chunk: {result}")
    return result


def phase4_validation(all_documents, chunks_written):
    """Dogrulama."""
    print("\n" + "=" * 65)
    print("FAZ 4: Dogrulama")
    print("=" * 65)
    checks = []

    def check(label, cond, detail=""):
        checks.append(cond)
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label}" + (f" -- {detail}" if not cond and detail else ""))

    check("docs >= 5", len(all_documents) >= 5, f"got {len(all_documents)}")
    check("chunks > 0", chunks_written > 0, f"got {chunks_written}")

    # Check metadata completeness
    required_fields = ["category", "source_url", "source_type", "title", "doc_kind",
                       "department", "contact_unit", "contact_info"]
    all_ok = True
    for doc in all_documents:
        for f in required_fields:
            if not doc.meta.get(f):
                all_ok = False
                break
    check("metadata 100%", all_ok)

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    print(f"\n  SONUC: {passed} PASS / {failed} FAIL")
    return failed == 0


def main():
    genel_docs = phase1_scrape_genel_slug_pages()
    iletisim_docs = phase2_iletisim_content()
    all_documents = genel_docs + iletisim_docs
    chunks = phase3_ingest(all_documents)
    success = phase4_validation(all_documents, chunks)

    print("\n" + "=" * 65)
    print(f"GOREV 3.2.14 — Genel Yapi ve Iletisim {'TAMAMLANDI' if success else 'BASARISIZ'}!")
    print("=" * 65)

    summary = {
        "task": "3.2.14",
        "description": "Genel Yapi ve Iletisim Deep Scrape",
        "genel_slug_docs": len(genel_docs),
        "iletisim_docs": len(iletisim_docs),
        "total_documents": len(all_documents),
        "chunks_written": chunks,
    }
    summary_path = OUTPUT_DIR / "genel_iletisim_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
