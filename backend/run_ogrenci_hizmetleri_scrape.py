"""
Gorev 3.2.15 — Ogrenci Hizmetleri: Harita Gudumlu Deep Scrape

3 blueprint:
  - Egitim Katalogu (UBYS Bologna) -> JS-rendered, extract tree structure from local HTML
  - Yemek Listesi -> Rich static menu cards (date + meals), parse from local HTML + live scrape
  - Aday Ogrenciler -> Tiny, links to already-scraped pages + adayogrenci portal scrape
"""
import sys
import json
import hashlib
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


# ─── FAZ 1: Egitim Katalogu — UBYS tree structure extraction ───
def phase1_egitim_katalogu():
    print("=" * 65)
    print("FAZ 1: Egitim Katalogu — Birim/Program Agaci")
    print("=" * 65)

    html_path = GIBTU / "Eğitim_Kataloğu.html"
    if not html_path.exists():
        print("  [SKIP] Dosya bulunamadi")
        return []

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    documents = []

    # 1) Extract the faculty/program tree from jstree
    tree_items = []
    for node in soup.select("li[role='none'] a.jstree-anchor"):
        name = node.get_text(strip=True)
        level = int(node.get("aria-level", 1))
        indent = "  " * (level - 1)
        tree_items.append(f"{indent}- {name}")

    tree_text = "GIBTU Egitim Katalogu - Birim ve Program Agaci\n\n" + "\n".join(tree_items)
    print(f"  Birim/Program agaci: {len(tree_items)} dugum, {len(tree_text)} karakter")

    doc1 = Document(
        id=_doc_id("gibtu_egitim_katalogu_agac"),
        content=tree_text,
        meta={
            "category": "egitim",
            "source_url": "https://ubys.gibtu.edu.tr/ais/outcomebasedlearning/home/index",
            "source_type": "web",
            "source_id": "egitim_katalogu_agac",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Egitim Katalogu - Birim ve Program Agaci",
            "doc_kind": "genel",
            "department": "GIBTU Genel",
            "contact_unit": "Ogrenci Isleri Daire Baskanligi",
            "contact_info": "ogrenciisleri@gibtu.edu.tr",
        },
    )
    documents.append(doc1)

    # 2) Extract sidebar menu items (UBYS portal structure)
    sidebar_items = []
    for a in soup.select("#sidebar-menu a[href]"):
        href = a.get("href", "").strip()
        name = a.get_text(strip=True).lstrip("- ")
        if href and href != "#" and name:
            sidebar_items.append(f"- {name}: {href}")

    sidebar_text = "GIBTU UBYS Portal Yapisi\n\n" + "\n".join(sidebar_items)
    print(f"  UBYS portal: {len(sidebar_items)} menu oge, {len(sidebar_text)} karakter")

    doc2 = Document(
        id=_doc_id("gibtu_ubys_portal"),
        content=sidebar_text,
        meta={
            "category": "dijital_hizmetler",
            "source_url": "https://ubys.gibtu.edu.tr",
            "source_type": "web",
            "source_id": "ubys_portal_yapisi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU UBYS Portal Yapisi ve Dijital Hizmetler",
            "doc_kind": "yonlendirme",
            "department": "GIBTU Genel",
            "contact_unit": "Bilgi Islem Daire Baskanligi",
            "contact_info": "bilgiislem@gibtu.edu.tr",
        },
    )
    documents.append(doc2)

    # 3) Extract education degree info & tab structure
    egitim_info = (
        "GIBTU Egitim Katalogu\n\n"
        "Egitim Katalogu, GIBTU bunyesindeki tum akademik programlarin Bologna surecine uygun "
        "bilgilerini icerir. Her program icin su bilgilere ulasilabilir:\n\n"
        "1. Program Tanimi - Programin genel aciklamasi ve akademik kadro bilgisi\n"
        "2. Program Ciktilari - Siniflandirilmis, sirali ve duzey/alan/program bazinda program ciktilari\n"
        "3. Programin Ogretim Plani - Mufredattaki dersler (Ders Kodu, Ders Adi, Ders Tipi, Dil, "
        "Teorik, Uygulama, Laboratuvar, Yerel Kredi, AKTS), secmeli dersler ve entegre dersler\n\n"
        "Egitim Duzeyleri: Onlisans, Lisans, Yuksek Lisans, Doktora\n\n"
        "Erisim: https://ubys.gibtu.edu.tr/ais/outcomebasedlearning/home/index\n\n"
        "Basvuru Islemleri:\n"
        "- OSYM Onkayit\n- Enstitu Basvurusu\n- Uluslararasi Ogrenci Basvurusu\n"
        "- Yatay Gecis Basvuru Islemleri\n- Yaz Okulu Misafir Ogrenci Basvurusu\n"
        "- Tezsiz Lisansustunden Tezliye Yatay Gecis\n- Akademik Kadro Ilan Basvuru\n"
        "- YOS Yabanci Dil Sinavi Basvurusu\n- Enstitu Icin Uluslararasi Ogrenci Basvurusu\n"
        "- Tezsiz Yuksek Lisans Basvurusu\n- TOMER Basvurusu\n- Ek Madde 2 Basvurusu\n"
        "- Lisans Ustu Af Basvurusu\n- Doktora Yeterlilik Basvurusu\n"
        "- Lisans Derecesi ile Doktora Basvurusu"
    )

    doc3 = Document(
        id=_doc_id("gibtu_egitim_katalogu_bilgi"),
        content=egitim_info,
        meta={
            "category": "egitim",
            "source_url": "https://ubys.gibtu.edu.tr/ais/outcomebasedlearning/home/index",
            "source_type": "web",
            "source_id": "egitim_katalogu_bilgi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Egitim Katalogu Hakkinda",
            "doc_kind": "genel",
            "department": "GIBTU Genel",
            "contact_unit": "Ogrenci Isleri Daire Baskanligi",
            "contact_info": "ogrenciisleri@gibtu.edu.tr",
        },
    )
    documents.append(doc3)

    return documents


# ─── FAZ 2: Yemek Listesi — local HTML parse + live scrape ───
def phase2_yemek_listesi():
    print("\n" + "=" * 65)
    print("FAZ 2: Yemek Listesi")
    print("=" * 65)

    documents = []

    # Parse local HTML for menu data
    html_path = GIBTU / "Yemek_Listesi.html"
    if html_path.exists():
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

        menu_entries = []
        for card in soup.select("div.card"):
            date_el = card.select_one("div.card-title")
            if not date_el:
                continue
            date_str = date_el.get_text(strip=True)

            items = []
            for col in card.select("div.card-content div.col"):
                text = col.get_text(strip=True)
                if text:
                    items.append(text)

            if items:
                menu_entries.append(f"{date_str}: {', '.join(items)}")

        menu_text = "GIBTU Yemekhane Menu Listesi\n\n" + "\n".join(menu_entries)
        print(f"  Lokal HTML: {len(menu_entries)} gunluk menu, {len(menu_text)} karakter")

        doc1 = Document(
            id=_doc_id("gibtu_yemek_listesi_lokal"),
            content=menu_text,
            meta={
                "category": "yemekhane",
                "source_url": "https://www.gibtu.edu.tr/yemek",
                "source_type": "web",
                "source_id": "yemek_listesi",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": "GIBTU Yemekhane Gunluk Menu Listesi",
                "doc_kind": "genel",
                "department": "Saglik Kultur ve Spor Daire Baskanligi",
                "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
                "contact_info": "sks@gibtu.edu.tr",
            },
        )
        documents.append(doc1)

    # Also scrape live page
    try:
        resp = requests.get(f"{BASE_URL}/yemek", timeout=15, headers={"User-Agent": "UniChat/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        body = soup.find("div", class_="page_body") or soup.find("div", class_="container")
        if body:
            text = body.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
            live_text = "GIBTU Yemek Sayfasi (Canli)\n\n" + "\n".join(lines)
            if len(live_text) > 80:
                doc2 = Document(
                    id=_doc_id("gibtu_yemek_canli"),
                    content=live_text[:50000],
                    meta={
                        "category": "yemekhane",
                        "source_url": "https://www.gibtu.edu.tr/yemek",
                        "source_type": "web",
                        "source_id": "yemek_canli",
                        "last_updated": datetime.now().strftime("%Y-%m-%d"),
                        "title": "GIBTU Yemek Sayfasi (Canli Veri)",
                        "doc_kind": "genel",
                        "department": "Saglik Kultur ve Spor Daire Baskanligi",
                        "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
                        "contact_info": "sks@gibtu.edu.tr",
                    },
                )
                documents.append(doc2)
                print(f"  Canli scrape: {len(live_text)} karakter")
    except Exception as e:
        print(f"  [ERR] Canli yemek scrape: {e}")

    # Yemekhane info doc
    yemek_info = (
        "GIBTU Yemekhane Bilgileri\n\n"
        "Yemekhane rezervasyon sistemi: https://gibtukart.gibtu.edu.tr\n"
        "Yemek listesi sayfasi: https://www.gibtu.edu.tr/yemek\n\n"
        "Gunluk menu icerigi: Genellikle 4 kalem yemek sunulmaktadir "
        "(ana yemek, pilav/makarna, corba, icecek/tatli).\n"
        "Hafta ici (Pazartesi-Cuma) yemek servisi yapilmaktadir."
    )
    doc_info = Document(
        id=_doc_id("gibtu_yemekhane_bilgi"),
        content=yemek_info,
        meta={
            "category": "yemekhane",
            "source_url": "https://www.gibtu.edu.tr/yemek",
            "source_type": "web",
            "source_id": "yemekhane_bilgi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GIBTU Yemekhane Genel Bilgi",
            "doc_kind": "genel",
            "department": "Saglik Kultur ve Spor Daire Baskanligi",
            "contact_unit": "Saglik Kultur ve Spor Daire Baskanligi",
            "contact_info": "sks@gibtu.edu.tr",
        },
    )
    documents.append(doc_info)

    return documents


# ─── FAZ 3: Aday Ogrenciler — live scrape ───
def phase3_aday_ogrenciler():
    print("\n" + "=" * 65)
    print("FAZ 3: Aday Ogrenciler")
    print("=" * 65)

    documents = []

    # Scrape adayogrenci portal
    try:
        resp = requests.get("https://adayogrenci.gibtu.edu.tr/", timeout=15,
                            headers={"User-Agent": "UniChat/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        body = soup.find("div", class_="container") or soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
            portal_text = "GIBTU Aday Ogrenci Portali\n\n" + "\n".join(lines)
            if len(portal_text) > 80:
                doc1 = Document(
                    id=_doc_id("gibtu_aday_ogrenci_portal"),
                    content=portal_text[:50000],
                    meta={
                        "category": "aday_ogrenci",
                        "source_url": "https://adayogrenci.gibtu.edu.tr/",
                        "source_type": "web",
                        "source_id": "aday_ogrenci_portal",
                        "last_updated": datetime.now().strftime("%Y-%m-%d"),
                        "title": "GIBTU Aday Ogrenci Portali",
                        "doc_kind": "genel",
                        "department": "GIBTU Genel",
                        "contact_unit": "Ogrenci Isleri Daire Baskanligi",
                        "contact_info": "ogrenciisleri@gibtu.edu.tr",
                    },
                )
                documents.append(doc1)
                print(f"  Aday portal: {len(portal_text)} karakter")
    except Exception as e:
        print(f"  [ERR] Aday portal scrape: {e}")

    # Aday Ogrenciler info from local HTML
    html_path = GIBTU / "Aday_Öğrenciler.html"
    if html_path.exists():
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            name = a.get_text(strip=True)
            href = a["href"]
            if name and href != "#":
                links.append(f"- {name}: {href}")

        info_text = (
            "GIBTU Aday Ogrenciler Rehberi\n\n"
            "Aday ogrenciler icin onemli linkler:\n\n" +
            "\n".join(links) +
            "\n\nNot: Aday ogrenci portali uzerinden kayit, puanlar, bolumler "
            "ve kampus bilgilerine ulasilabilir."
        )
        doc2 = Document(
            id=_doc_id("gibtu_aday_ogrenciler_rehber"),
            content=info_text,
            meta={
                "category": "aday_ogrenci",
                "source_url": "https://www.gibtu.edu.tr/adayogrenci",
                "source_type": "web",
                "source_id": "aday_ogrenciler_rehber",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": "GIBTU Aday Ogrenciler Rehberi",
                "doc_kind": "yonlendirme",
                "department": "GIBTU Genel",
                "contact_unit": "Ogrenci Isleri Daire Baskanligi",
                "contact_info": "ogrenciisleri@gibtu.edu.tr",
            },
        )
        documents.append(doc2)
        print(f"  Aday rehber: {len(info_text)} karakter ({len(links)} link)")

    return documents


# ─── FAZ 4: DB Ingest ───
def phase4_ingest(all_documents):
    print("\n" + "=" * 65)
    print("FAZ 4: DB Yukleme")
    print("=" * 65)
    print(f"  Toplam Document: {len(all_documents)}")
    if not all_documents:
        print("  [WARN] Yuklenecek document yok!")
        return 0
    result = ingest_documents(all_documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)
    print(f"  Yazilan chunk: {result}")
    return result


# ─── FAZ 5: Dogrulama ───
def phase5_validation(all_documents, chunks_written):
    print("\n" + "=" * 65)
    print("FAZ 5: Dogrulama")
    print("=" * 65)
    checks = []

    def check(label, cond, detail=""):
        checks.append(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" +
              (f" -- {detail}" if not cond and detail else ""))

    check("docs >= 5", len(all_documents) >= 5, f"got {len(all_documents)}")
    check("chunks > 0", chunks_written > 0, f"got {chunks_written}")

    cats = set(d.meta.get("category") for d in all_documents)
    check("3+ category", len(cats) >= 3, f"got {cats}")

    # metadata completeness
    required = ["category", "source_url", "source_type", "title", "doc_kind",
                "department", "contact_unit", "contact_info"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents)
    check("metadata 100%", all_ok)

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    print(f"\n  SONUC: {passed} PASS / {failed} FAIL")
    return failed == 0


def main():
    docs_egitim = phase1_egitim_katalogu()
    docs_yemek = phase2_yemek_listesi()
    docs_aday = phase3_aday_ogrenciler()
    all_documents = docs_egitim + docs_yemek + docs_aday
    chunks = phase4_ingest(all_documents)
    success = phase5_validation(all_documents, chunks)

    print("\n" + "=" * 65)
    status = "TAMAMLANDI" if success else "BASARISIZ"
    print(f"GOREV 3.2.15 -- Ogrenci Hizmetleri Deep Scrape {status}!")
    print("=" * 65)

    summary = {
        "task": "3.2.15",
        "description": "Ogrenci Hizmetleri Deep Scrape",
        "egitim_docs": len(docs_egitim),
        "yemek_docs": len(docs_yemek),
        "aday_docs": len(docs_aday),
        "total_documents": len(all_documents),
        "chunks_written": chunks,
    }
    summary_path = OUTPUT_DIR / "ogrenci_hizmetleri_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
