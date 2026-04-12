"""
Gorev 3.2.19 — Ogrenci Kulupleri: Toplu Harita Gudumlu Deep Scrape

Blueprint: Ogrenci_Topluluklari_Kulupleri.html (274 KB, 58 kulup)
Her kulup karti icindeki bilgiler:
  - Kulup adi + URL (kulup_url a)
  - Kulup baskani (kulup_baskani_adsoyad)
  - E-posta
  - Danisman bilgisi (danisman, danisman_yrd)
  - Sosyal medya linkleri

Strateji:
  1) Lokal HTML'den tum kulup kartlarini parse et -> her biri 1 Document
  2) Tum kuluplerin master listesini olustur -> 1 Document
  3) Her kulup URL'sini canli scrape et (ek icerik) -> N Document
"""
import sys
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ingestion.loader import ingest_documents, DuplicatePolicy
from haystack import Document

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"
BASE_URL = "https://www.gibtu.edu.tr"


def _doc_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def phase1_parse_blueprint():
    """Lokal HTML'den tum kulup kartlarini parse et."""
    print("=" * 65)
    print("FAZ 1: Blueprint Parse — Kulup Kartlari")
    print("=" * 65)

    html_path = GIBTU / "Öğrenci_Toplulukları_Kulüpleri.html"
    if not html_path.exists():
        print("  [SKIP] Blueprint bulunamadi")
        return [], []

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    clubs = []
    for li in soup.select("li[data-birimadi]"):
        card = li.select_one("div.card")
        if not card:
            continue

        # Club name + URL
        name_el = card.select_one("span.kulup_url a")
        if not name_el:
            continue
        club_name = name_el.get_text(strip=True)
        club_url = name_el.get("href", "")

        # President
        president_el = card.select_one("span.kulup_baskani_adsoyad")
        president = president_el.get_text(strip=True) if president_el else "---"

        # Email
        email = ""
        for span in card.select("div.card-content span"):
            text = span.get_text(strip=True)
            if "@" in text or ".ogrencikulubu" in text:
                email = text
                break

        # Advisor
        advisor_el = card.select_one("span.danisman")
        advisor = advisor_el.get_text(strip=True) if advisor_el else "---"
        advisor_yrd_el = card.select_one("span.danisman_yrd")
        advisor_yrd = advisor_yrd_el.get_text(strip=True) if advisor_yrd_el else "---"

        clubs.append({
            "name": club_name,
            "url": club_url,
            "president": president,
            "email": email,
            "advisor": advisor,
            "advisor_yrd": advisor_yrd,
        })

    print(f"  Tespit edilen kulup: {len(clubs)}")

    # Create individual club documents
    documents = []
    for c in clubs:
        content = (
            f"{c['name']}\n\n"
            f"Kulup Baskani: {c['president']}\n"
            f"E-posta: {c['email']}\n"
            f"Danisman: {c['advisor']}\n"
            f"Danisman Yardimcisi: {c['advisor_yrd']}\n"
            f"Web Sayfasi: {c['url']}\n"
        )
        safe_name = c['name'].replace(" ", "_")[:40].lower()
        doc = Document(
            id=_doc_id(f"kulup_{safe_name}"),
            content=content,
            meta={
                "category": "topluluklar",
                "source_url": c["url"] or f"{BASE_URL}/ogrencitopluluk",
                "source_type": "web",
                "source_id": f"kulup_{safe_name}",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": c["name"],
                "doc_kind": "tanitim",
                "department": "Saglik Kultur ve Spor Daire Baskanligi",
                "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
                "contact_info": c["email"] or "sks@gibtu.edu.tr",
            },
        )
        documents.append(doc)

    # Create master list document
    master_lines = [f"GIBTU Ogrenci Topluluklari Rehberi\n\nToplam: {len(clubs)} topluluk\n"]
    for i, c in enumerate(clubs, 1):
        line = f"{i}. {c['name']}"
        if c['president'] != '---':
            line += f" | Baskan: {c['president']}"
        if c['email']:
            line += f" | {c['email']}"
        master_lines.append(line)

    master_doc = Document(
        id=_doc_id("gibtu_kulup_master_list"),
        content="\n".join(master_lines),
        meta={
            "category": "topluluklar",
            "source_url": f"{BASE_URL}/ogrencitopluluk",
            "source_type": "web",
            "source_id": "kulup_master_list",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Ogrenci Topluluklari Tam Liste",
            "doc_kind": "rehber",
            "department": "Saglik Kultur ve Spor Daire Baskanligi",
            "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
            "contact_info": "sks@gibtu.edu.tr",
        },
    )
    documents.append(master_doc)

    print(f"  Document olusturuldu: {len(documents)} ({len(clubs)} kulup + 1 master liste)")
    return documents, clubs


def phase2_live_scrape(clubs):
    """Her kulubun canli sayfasini scrape et (ek icerik)."""
    print("\n" + "=" * 65)
    print("FAZ 2: Canli Kulup Sayfalari Scrape")
    print("=" * 65)

    documents = []
    ok_count = 0
    skip_count = 0
    err_count = 0

    for i, c in enumerate(clubs):
        url = c["url"]
        if not url or not url.startswith("http"):
            skip_count += 1
            continue

        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": "UniChat/1.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            body = (soup.find("div", class_="page_body") or
                    soup.find("section", class_="birim_safya_body") or
                    soup.find("div", class_="container"))

            if not body:
                skip_count += 1
                continue

            text = body.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
            cleaned = "\n".join(lines)

            if len(cleaned) < 50:
                skip_count += 1
                continue

            safe_name = c['name'].replace(" ", "_")[:40].lower()
            doc = Document(
                id=_doc_id(f"kulup_canli_{safe_name}"),
                content=cleaned[:30000],
                meta={
                    "category": "topluluklar",
                    "source_url": url,
                    "source_type": "web",
                    "source_id": f"kulup_canli_{safe_name}",
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "title": f"{c['name']} - Detay Sayfasi",
                    "doc_kind": "tanitim",
                    "department": "Saglik Kultur ve Spor Daire Baskanligi",
                    "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
                    "contact_info": c["email"] or "sks@gibtu.edu.tr",
                },
            )
            documents.append(doc)
            ok_count += 1

            # Rate limiting
            if (i + 1) % 10 == 0:
                time.sleep(0.5)

        except Exception:
            err_count += 1

    print(f"  Basarili: {ok_count}, Skip: {skip_count}, Hata: {err_count}")
    return documents


def phase3_ingest(all_documents):
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


def phase4_validation(all_documents, chunks_written, club_count):
    print("\n" + "=" * 65)
    print("FAZ 4: Dogrulama")
    print("=" * 65)
    checks = []

    def check(label, cond, detail=""):
        checks.append(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" +
              (f" -- {detail}" if not cond and detail else ""))

    check("docs >= 40", len(all_documents) >= 40, f"got {len(all_documents)}")
    check("chunks > 0", chunks_written > 0, f"got {chunks_written}")
    check("clubs >= 40", club_count >= 40, f"got {club_count}")

    # metadata check
    required = ["category", "source_url", "source_type", "title", "doc_kind",
                "department", "contact_unit", "contact_info"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents)
    check("metadata 100%", all_ok)

    # category check
    cats = set(d.meta.get("category") for d in all_documents)
    check("category=topluluklar", "topluluklar" in cats)

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    print(f"\n  SONUC: {passed} PASS / {failed} FAIL")
    return failed == 0


def main():
    blueprint_docs, clubs = phase1_parse_blueprint()
    live_docs = phase2_live_scrape(clubs)
    all_documents = blueprint_docs + live_docs
    chunks = phase3_ingest(all_documents)
    success = phase4_validation(all_documents, chunks, len(clubs))

    print("\n" + "=" * 65)
    status = "TAMAMLANDI" if success else "BASARISIZ"
    print(f"GOREV 3.2.19 -- Ogrenci Kulupleri Toplu Deep Scrape {status}!")
    print("=" * 65)

    summary = {
        "task": "3.2.19",
        "description": "Ogrenci Kulupleri Toplu Deep Scrape",
        "club_count": len(clubs),
        "blueprint_docs": len(blueprint_docs),
        "live_docs": len(live_docs),
        "total_documents": len(all_documents),
        "chunks_written": chunks,
    }
    summary_path = OUTPUT_DIR / "ogrenci_kulupleri_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
