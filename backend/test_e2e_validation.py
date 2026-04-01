"""
Görev 3.2.7.3 — Altyapı Doğrulama: MDBF Uçtan Uca Test

Bu script, Harita Güdümlü Scraper altyapısının doğruluğunu
MDBF fakültesi üzerinde uçtan uca test eder.

Adımlar:
  1. Blueprint parse → MenuTree
  2. Haritadan URL listesi üret (doğrula)
  3. Canlı siteden 5 sayfa fetch + deep parse
  4. Menü haritası + içerik Document'ları doğrula
  5. PDF tespiti doğrula
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint, LinkType
from scrapers.map_guided_scraper import MapGuidedScraper

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
MDBF_PATH = (
    GIBTU / "FAKÜLTELER"
    / "Mühendislik ve Doğa Bilimleri Fakültesi"
    / "Mühendislik_ve_Doğa_Bilimleri _Fakültesi.html"
)

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} -- {detail}")


def step1_blueprint_parse():
    print("\n" + "=" * 65)
    print("ADIM 1: Blueprint Parse")
    print("=" * 65)

    tree = parse_blueprint(MDBF_PATH)
    stats = tree.stats

    print(f"  Kaynak: {MDBF_PATH.name}")
    print(f"  BirimID: {stats['birim_id']}")
    print(f"  Menu items: {stats['menu_item_count']}")
    print(f"  Total links: {stats['total_link_count']}")
    print(f"  Scrapable URLs: {stats['scrapable_url_count']}")
    print(f"  PDF links: {stats['pdf_count']}")
    print(f"  Link types: {stats['link_type_distribution']}")

    check("BirimID == 15", stats["birim_id"] == 15, f"got {stats['birim_id']}")
    check(">=14 menu items", stats["menu_item_count"] >= 14, f"got {stats['menu_item_count']}")
    check(">=50 total links", stats["total_link_count"] >= 50, f"got {stats['total_link_count']}")
    check(">=5 PDF links", stats["pdf_count"] >= 5, f"got {stats['pdf_count']}")

    return tree


def step2_url_generation(tree):
    print("\n" + "=" * 65)
    print("ADIM 2: URL Listesi Uretimi")
    print("=" * 65)

    urls = tree.to_url_list()
    print(f"  Toplam scrape URL: {len(urls)}")

    # Beklenen sayfa turleri
    expected_patterns = {
        "Anasayfa": "Birim.aspx?id=15",
        "Yonetim": "BirimYonetim.aspx?id=15",
        "Misyon": "BirimMisyon.aspx?id=15",
        "Vizyon": "BirimVizyon.aspx?id=15",
        "Tarihce": "BirimTarihce.aspx?id=15",
        "Formlar": "BirimForm.aspx?id=15",
        "Mevzuatlar": "BirimMevzuat.aspx?id=15",
        "Iletisim": "BirimIletisim.aspx?id=15",
        "Duyurular": "BirimDuyuru.aspx?id=15",
        "Galeri": "BirimGaleri.aspx?id=15",
    }

    for label, pattern in expected_patterns.items():
        found = any(pattern.lower() in u.lower() for u in urls)
        check(f"URL icerir: {label} ({pattern})", found)

    # Kalite alt sayfalari (mdbf/icerik/ kaliplari)
    kalite_urls = [u for u in urls if "mdbf/icerik" in u.lower() or "kalite" in u.lower()]
    check("Kalite alt sayfalari >= 5", len(kalite_urls) >= 5, f"got {len(kalite_urls)}")

    # Ogrenci alt sayfalari
    ogrenci_patterns = ["ders", "not-donusum", "danismanlik", "akademik-takvim", "topluluk"]
    ogrenci_found = sum(1 for u in urls if any(p in u.lower() for p in ogrenci_patterns))

    print(f"  Kalite alt sayfa: {len(kalite_urls)}")
    print(f"  Ogrenci ilgili: {ogrenci_found}")

    for i, url in enumerate(urls):
        print(f"  {i+1:3d}. {url[:90]}")

    return urls


def step3_live_fetch(tree):
    print("\n" + "=" * 65)
    print("ADIM 3: Canli Siteden 5 Sayfa Fetch + Deep Parse")
    print("=" * 65)

    scraper = MapGuidedScraper(
        blueprint_path=MDBF_PATH,
        category="bolumler",
        department="Muhendislik ve Doga Bilimleri Fakultesi",
        doc_kind="tanitim",
        contact_unit="MDBF Dekanligi",
        contact_info="mdbf@gibtu.edu.tr",
        url_limit=5,
    )

    report = scraper.scrape_all(dry_run=True)

    print(f"\n  Sonuc Ozeti:")
    print(f"    Blueprint URLs: {report.total_blueprint_urls}")
    print(f"    Fetched:        {report.total_fetched}")
    print(f"    Valid:          {report.total_valid}")
    print(f"    Failed:         {report.total_failed}")
    print(f"    Skipped:        {report.total_skipped}")
    print(f"    Documents:      {report.total_documents}")
    print(f"    Total chars:    {report.total_chars}")

    check("Fetch basarili >= 3", report.total_fetched >= 3, f"got {report.total_fetched}")
    check("Valid pages >= 1", report.total_valid >= 1, f"got {report.total_valid}")
    check("Documents >= 2 (en az 1 icerik + 1 menu)", report.total_documents >= 2, f"got {report.total_documents}")
    check("Total chars > 500", report.total_chars > 500, f"got {report.total_chars}")
    check("Failed == 0", report.total_failed == 0, f"got {report.total_failed}")

    return report


def step4_document_validation(report):
    print("\n" + "=" * 65)
    print("ADIM 4: Document ve Metadata Dogrulama")
    print("=" * 65)

    # doc_kind dagilimi
    print(f"  doc_kind dagilimi: {report.doc_kind_distribution}")
    check(
        "menu_haritasi document var",
        "menu_haritasi" in report.doc_kind_distribution,
        f"kinds: {list(report.doc_kind_distribution.keys())}",
    )

    icerik_count = sum(
        v for k, v in report.doc_kind_distribution.items()
        if k != "menu_haritasi"
    )
    check("Icerik document >= 1", icerik_count >= 1, f"got {icerik_count}")

    # Metadata doluluğu
    print(f"\n  Metadata doluluk:")
    required_fields = ["category", "source_url", "source_type", "source_id",
                       "last_updated", "title", "doc_kind"]
    all_complete = True
    for field_name, info in report.metadata_completeness.items():
        pct = info["pct"]
        status = "OK" if pct == 100 else "EKSIK"
        print(f"    {field_name}: {info['count']}/{info['total']} ({pct}%) [{status}]")
        if field_name in required_fields and pct < 100:
            all_complete = False

    check("Zorunlu metadata alanlari %100", all_complete)

    # Sayfa sonuclari
    print(f"\n  Sayfa sonuclari:")
    for pr in report.page_results:
        print(f"    {pr['title'][:40]:40s} | {pr['char_count']:6d} kar. | depth={pr['depth']} | valid={pr['is_valid']}")
        if pr.get("placeholder"):
            print(f"      !! Placeholder: {pr['placeholder']}")

    return True


def step5_pdf_validation(report):
    print("\n" + "=" * 65)
    print("ADIM 5: PDF Tespiti Dogrulama")
    print("=" * 65)

    pdfs = report.discovered_pdfs
    print(f"  Toplam PDF tespit: {len(pdfs)}")

    for pdf in pdfs:
        is_pdf_url = ".pdf" in pdf["url"].lower()
        print(f"    {'[PDF]' if is_pdf_url else '[???]'} {pdf['text'][:50]:50s} -> {pdf['url'][:70]}")

    check("PDF tespit >= 5", len(pdfs) >= 5, f"got {len(pdfs)}")

    # PDF URL'leri gecerli mi?
    pdf_urls_valid = all(".pdf" in p["url"].lower() or "dosya" in p["url"].lower() for p in pdfs)
    check("Tum PDF URL'leri gecerli", pdf_urls_valid)

    # External links
    externals = report.external_links
    print(f"\n  Harici linkler: {len(externals)}")
    for ext in externals:
        print(f"    [{ext['type']}] {ext['text'][:40]} -> {ext['url'][:60]}")

    check("Harici link tespit >= 1", len(externals) >= 1, f"got {len(externals)}")

    return True


def main():
    global PASS, FAIL

    print("=" * 65)
    print("GOREV 3.2.7.3 -- ALTYAPI DOGRULAMA")
    print("MDBF Fakultesi Uctan Uca Test")
    print("=" * 65)

    # Adim 1: Blueprint parse
    tree = step1_blueprint_parse()

    # Adim 2: URL listesi
    urls = step2_url_generation(tree)

    # Adim 3: Canli fetch (5 sayfa)
    report = step3_live_fetch(tree)

    # Adim 4: Document dogrulama
    step4_document_validation(report)

    # Adim 5: PDF dogrulama
    step5_pdf_validation(report)

    # Sonuc
    print("\n" + "=" * 65)
    print(f"SONUC: {PASS} PASS / {FAIL} FAIL")
    print("=" * 65)

    if FAIL == 0:
        print("\nTUM TESTLER GECTI!")
        return 0
    else:
        print(f"\n{FAIL} TEST BASARISIZ!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
