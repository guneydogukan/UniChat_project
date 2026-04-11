"""
Gorev 3.2.8.2 — Muhendislik ve Doga Bilimleri Fakultesi: Harita Gudumlu Deep Scrape

Bu script, MDBF'nin tum blueprint'lerini kullanarak tam canli deep scrape yapar.
Fakülte genel (BirimID=15) + Bilgisayar Müh. (18) + E-E Müh. (16) + Endüstri Müh. (19)
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint
from scrapers.map_guided_scraper import MapGuidedScraper

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
MDBF_DIR = GIBTU / "FAKÜLTELER" / "Mühendislik ve Doğa Bilimleri Fakültesi"

# Blueprint dosyalari — her biri ayri birim
BLUEPRINTS = [
    {
        "file": MDBF_DIR / "Mühendislik_ve_Doğa_Bilimleri _Fakültesi.html",
        "department": "Muhendislik ve Doga Bilimleri Fakultesi",
        "contact_unit": "MDBF Dekanligi",
        "contact_info": "mdbf@gibtu.edu.tr",
    },
    {
        "file": MDBF_DIR / "Bilgisayar_Mühendisliği_Bölümü.html",
        "department": "Bilgisayar Muhendisligi Bolumu",
        "contact_unit": "Bilgisayar Muhendisligi Bolumu",
        "contact_info": "bilgisayar@gibtu.edu.tr",
    },
    {
        "file": MDBF_DIR / "Elektrik_Elektronik_Mühendisliği_Bölümü.html",
        "department": "Elektrik Elektronik Muhendisligi Bolumu",
        "contact_unit": "Elektrik Elektronik Muhendisligi Bolumu",
        "contact_info": "eee@gibtu.edu.tr",
    },
    {
        "file": MDBF_DIR / "Endüstri_Mühendisliği_Bölümü.html",
        "department": "Endustri Muhendisligi Bolumu",
        "contact_unit": "Endustri Muhendisligi Bolumu",
        "contact_info": "endustri@gibtu.edu.tr",
    },
]

OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"


def phase1_blueprint_check():
    """Her blueprint'i parse et, istatistikleri goster."""
    print("=" * 65)
    print("FAZ 1: Blueprint Parse — MDBF Tum Birimler")
    print("=" * 65)

    total_urls = 0
    for bp_info in BLUEPRINTS:
        bp_file = bp_info["file"]
        if not bp_file.exists():
            print(f"\n  [SKIP] Dosya bulunamadi: {bp_file.name}")
            continue

        tree = parse_blueprint(bp_file)
        s = tree.stats
        urls = tree.to_url_list()
        total_urls += len(urls)

        print(f"\n  --- {bp_info['department']} ---")
        print(f"  BirimID:        {s['birim_id']}")
        print(f"  Menu items:     {s['menu_item_count']}")
        print(f"  Total links:    {s['total_link_count']}")
        print(f"  Scrapable URLs: {s['scrapable_url_count']}")
        print(f"  PDF links:      {s['pdf_count']}")
        print(f"  External links: {len(tree.get_external_links())}")
        print(f"  URL list:       {len(urls)}")

    print(f"\n  TOPLAM SCRAPE HEDEF: {total_urls} URL")
    return total_urls


def phase2_full_scrape():
    """Her blueprint icin ayri scrape calistir, sonra birlestir."""
    print("\n" + "=" * 65)
    print("FAZ 2: Canli Deep Scrape — MDBF Tum Birimler")
    print("=" * 65)

    all_reports = []

    for bp_info in BLUEPRINTS:
        bp_file = bp_info["file"]
        dept = bp_info["department"]

        if not bp_file.exists():
            print(f"\n  [SKIP] {dept} — blueprint yok")
            continue

        print(f"\n  >>> {dept} scrape basliyor...")

        scraper = MapGuidedScraper(
            blueprint_path=bp_file,
            category="bolumler",
            department=dept,
            doc_kind="genel",
            contact_unit=bp_info["contact_unit"],
            contact_info=bp_info["contact_info"],
        )

        report = scraper.scrape_all(dry_run=False)

        # Her birim icin ayri JSON kaydet
        safe_name = dept.lower().replace(" ", "_").replace(".", "")
        json_path = OUTPUT_DIR / f"mdbf_{safe_name}_output.json"
        scraper.save_report_json(report, str(json_path))

        all_reports.append({
            "department": dept,
            "report": report,
            "json_path": str(json_path),
        })

        print(f"  <<< {dept}: {report.total_documents} Document, "
              f"{report.total_valid} valid, {report.total_failed} failed")

    return all_reports


def phase3_validation(all_reports):
    """Toplam sonuclari dogrula."""
    print("\n" + "=" * 65)
    print("FAZ 3: Dogrulama — MDBF Toplam")
    print("=" * 65)

    checks = []
    total_docs = 0
    total_valid = 0
    total_failed = 0
    total_chars = 0

    for entry in all_reports:
        r = entry["report"]
        dept = entry["department"]
        total_docs += r.total_documents
        total_valid += r.total_valid
        total_failed += r.total_failed
        total_chars += r.total_chars

        print(f"\n  {dept}:")
        print(f"    Documents: {r.total_documents}")
        print(f"    Valid:     {r.total_valid}")
        print(f"    Failed:    {r.total_failed}")
        print(f"    Chars:     {r.total_chars:,}")
        print(f"    PDFs:      {len(r.discovered_pdfs)}")
        print(f"    doc_kinds: {r.doc_kind_distribution}")

    def check(label, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        checks.append(cond)
        print(f"  [{status}] {label}" + (f" -- {detail}" if not cond and detail else ""))

    print(f"\n  TOPLAM:")
    print(f"    Documents: {total_docs}")
    print(f"    Valid:     {total_valid}")
    print(f"    Failed:    {total_failed}")
    print(f"    Chars:     {total_chars:,}")

    check("Toplam valid >= 20", total_valid >= 20, f"got {total_valid}")
    check("Toplam documents >= 20", total_docs >= 20, f"got {total_docs}")
    check("Toplam failed <= 10", total_failed <= 10, f"got {total_failed}")
    check("Toplam chars > 10000", total_chars > 10000, f"got {total_chars}")
    check("En az 3 birim scrape edildi", len(all_reports) >= 3, f"got {len(all_reports)}")

    # Her birimde en az 5 document olmali
    for entry in all_reports:
        r = entry["report"]
        check(
            f"{entry['department'][:30]} docs >= 5",
            r.total_documents >= 5,
            f"got {r.total_documents}",
        )

    passed = sum(1 for c in checks if c)
    failed_count = sum(1 for c in checks if not c)

    print(f"\n  SONUC: {passed} PASS / {failed_count} FAIL")
    return failed_count == 0


def main():
    phase1_blueprint_check()
    all_reports = phase2_full_scrape()
    success = phase3_validation(all_reports)

    print("\n" + "=" * 65)
    if success:
        print("GOREV 3.2.8.2 — MDBF Deep Scrape TAMAMLANDI!")
    else:
        print("GOREV 3.2.8.2 — Bazi testler basarisiz!")
    print("=" * 65)

    # Ozet JSON
    summary = {
        "task": "3.2.8.2",
        "description": "MDBF Harita Gudumlu Deep Scrape",
        "birimler": [],
    }
    for entry in all_reports:
        r = entry["report"]
        summary["birimler"].append({
            "department": entry["department"],
            "json_path": entry["json_path"],
            "total_documents": r.total_documents,
            "total_valid": r.total_valid,
            "total_failed": r.total_failed,
            "total_chars": r.total_chars,
            "pdf_count": len(r.discovered_pdfs),
            "doc_kind_distribution": r.doc_kind_distribution,
        })

    summary_path = OUTPUT_DIR / "mdbf_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
