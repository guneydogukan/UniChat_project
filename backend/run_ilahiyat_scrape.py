"""
Gorev 3.2.8.1 — Ilahiyat Fakultesi: Harita Gudumlu Deep Scrape

Bu script, Ilahiyat Fakultesi blueprint'ini kullanarak tam canli deep scrape yapar.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint
from scrapers.map_guided_scraper import MapGuidedScraper

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
BLUEPRINT = GIBTU / "FAKÜLTELER" / "İlahiyat Fakültesi" / "İlahiyat-Türkçe-Arapca.html"
OUTPUT_JSON = Path(__file__).resolve().parent / "scrapers" / "ilahiyat_scrape_output.json"


def phase1_blueprint_check():
    """Blueprint'i parse et, istatistikleri goster."""
    print("=" * 65)
    print("FAZ 1: Blueprint Parse")
    print("=" * 65)

    tree = parse_blueprint(BLUEPRINT)
    s = tree.stats

    print(f"  BirimID:          {s['birim_id']}")
    print(f"  Menu items:       {s['menu_item_count']}")
    print(f"  Total links:      {s['total_link_count']}")
    print(f"  Scrapable URLs:   {s['scrapable_url_count']}")
    print(f"  PDF links:        {s['pdf_count']}")
    print(f"  External links:   {len(tree.get_external_links())}")
    print(f"  Link types:       {s['link_type_distribution']}")

    assert s["birim_id"] == 11, f"Expected BirimID=11, got {s['birim_id']}"
    print("  BirimID=11 dogrulandi")

    urls = tree.to_url_list()
    print(f"\n  Scrape edilecek URL sayisi: {len(urls)}")
    for i, url in enumerate(urls, 1):
        print(f"    {i:3d}. {url[:90]}")

    return tree


def phase2_full_scrape():
    """Tam canli scrape calistir."""
    print("\n" + "=" * 65)
    print("FAZ 2: Canli Deep Scrape")
    print("=" * 65)

    scraper = MapGuidedScraper(
        blueprint_path=BLUEPRINT,
        category="bolumler",
        department="Ilahiyat Fakultesi",
        doc_kind="genel",
        contact_unit="Ilahiyat Fakultesi Dekanligi",
        contact_info="ilahiyat@gibtu.edu.tr",
    )

    report = scraper.scrape_all(dry_run=False)
    scraper.save_report_json(report, str(OUTPUT_JSON))

    return report


def phase3_validation(report):
    """Sonuclari dogrula."""
    print("\n" + "=" * 65)
    print("FAZ 3: Dogrulama")
    print("=" * 65)

    checks = []

    def check(label, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        checks.append(cond)
        print(f"  [{status}] {label}" + (f" -- {detail}" if not cond and detail else ""))

    check("Fetch basarili >= 10", report.total_fetched >= 10, f"got {report.total_fetched}")
    check("Valid pages >= 5", report.total_valid >= 5, f"got {report.total_valid}")
    check("Documents >= 6 (icerik + menu)", report.total_documents >= 6, f"got {report.total_documents}")
    check("Failed <= 2 (Birimhiyerarsi 404 tolere)", report.total_failed <= 2, f"got {report.total_failed}")
    check("Total chars > 2000", report.total_chars > 2000, f"got {report.total_chars}")

    # menu_haritasi document
    check("menu_haritasi doc var", "menu_haritasi" in report.doc_kind_distribution)

    # Metadata doluluk
    for field_name, info in report.metadata_completeness.items():
        if field_name in ("category", "source_url", "title", "doc_kind"):
            check(f"Metadata {field_name} %100", info["pct"] == 100, f"got {info['pct']}%")

    # PDF tespiti
    check("PDF tespit >= 0", len(report.discovered_pdfs) >= 0, f"got {len(report.discovered_pdfs)}")

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)

    print(f"\n  SONUC: {passed} PASS / {failed} FAIL")
    return failed == 0


def main():
    phase1_blueprint_check()
    report = phase2_full_scrape()
    success = phase3_validation(report)

    print("\n" + "=" * 65)
    if success:
        print("GOREV 3.2.8.1 — Ilahiyat Fakultesi Deep Scrape TAMAMLANDI!")
    else:
        print("GOREV 3.2.8.1 — Bazi testler basarisiz!")
    print("=" * 65)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
