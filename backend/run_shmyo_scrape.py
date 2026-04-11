"""
Gorev 3.2.10.1 — Saglik Hizmetleri MYO: Harita Gudumlu Deep Scrape

MYO genel (BirimID=31) + 5 program:
  - Ameliyathane Hizmetleri (BirimID=100)
  - Fizyoterapi ve Rehabilitasyon (BirimID=96)
  - Tibbi Laboratuvar Teknikleri (BirimID=99)
  - Yasli Bakimi (BirimID=97)
  - Ilk ve Acil Yardim (BirimID=98)

scrape_all(dry_run=False) hem scrape eder hem DB'ye yazar.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint
from scrapers.map_guided_scraper import MapGuidedScraper

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
MYO_ROOT = GIBTU / "MESLEK YÜKSEKOKULLARI"
SHMYO_DIR = MYO_ROOT / "Sağlık Hizmetleri Meslek Yüksekokulu"

BLUEPRINTS = [
    {
        "file": MYO_ROOT / "Sağlık_Hizmetleri_Meslek_Yüksekokulu_Genel_Yapısı.html",
        "department": "Saglik Hizmetleri MYO",
        "contact_unit": "SHMYO Mudurlugu",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
    {
        "file": SHMYO_DIR / "Ameliyathane_Hizmetleri_Bölümü.html",
        "department": "Ameliyathane Hizmetleri Programi",
        "contact_unit": "Ameliyathane Hizmetleri Programi",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
    {
        "file": SHMYO_DIR / "Fizyoterapi ve Rehabilitasyon Bölümü.html",
        "department": "Fizyoterapi Programi",
        "contact_unit": "Fizyoterapi Programi",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
    {
        "file": SHMYO_DIR / "Tıbbi_Laboratuvar_Teknikleri_Bölümü.html",
        "department": "Tibbi Laboratuvar Teknikleri Programi",
        "contact_unit": "Tibbi Laboratuvar Teknikleri Programi",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
    {
        "file": SHMYO_DIR / "Yaşlı_Bakımı_Bölümü.html",
        "department": "Yasli Bakim Programi",
        "contact_unit": "Yasli Bakim Programi",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
    {
        "file": SHMYO_DIR / "İlk_ve_Acil_Yardım_Bölümü.html",
        "department": "Ilk ve Acil Yardim Programi",
        "contact_unit": "Ilk ve Acil Yardim Programi",
        "contact_info": "shmyo@gibtu.edu.tr",
    },
]

OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"


def phase1_blueprint_check():
    print("=" * 65)
    print("FAZ 1: Blueprint Parse — SHMYO Tum Birimler")
    print("=" * 65)
    total_urls = 0
    found = 0
    for bp_info in BLUEPRINTS:
        bp_file = bp_info["file"]
        if not bp_file.exists():
            print(f"\n  [SKIP] {bp_file.name} — dosya bulunamadi")
            continue
        found += 1
        tree = parse_blueprint(bp_file)
        s = tree.stats
        urls = tree.to_url_list()
        total_urls += len(urls)
        print(f"\n  --- {bp_info['department']} ---")
        print(f"  BirimID:        {s['birim_id']}")
        print(f"  Menu items:     {s['menu_item_count']}")
        print(f"  Scrapable URLs: {s['scrapable_url_count']}")
        print(f"  PDF links:      {s['pdf_count']}")
        print(f"  URL list:       {len(urls)}")
    print(f"\n  BULUNAN BLUEPRINT: {found}/{len(BLUEPRINTS)}")
    print(f"  TOPLAM SCRAPE HEDEF: {total_urls} URL")
    return total_urls


def phase2_full_scrape():
    """Canli deep scrape + otomatik DB yukleme (scrape_all dry_run=False)."""
    print("\n" + "=" * 65)
    print("FAZ 2: Canli Deep Scrape + DB Yukleme — SHMYO Tum Birimler")
    print("=" * 65)
    all_reports = []
    for bp_info in BLUEPRINTS:
        bp_file = bp_info["file"]
        dept = bp_info["department"]
        if not bp_file.exists():
            print(f"\n  [SKIP] {dept} — blueprint bulunamadi")
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
        # dry_run=False => scrape + DB ingest bir arada
        report = scraper.scrape_all(dry_run=False)
        safe_name = dept.lower().replace(" ", "_").replace(".", "")
        json_path = OUTPUT_DIR / f"shmyo_{safe_name}_output.json"
        scraper.save_report_json(report, str(json_path))
        all_reports.append({
            "department": dept,
            "report": report,
            "json_path": str(json_path),
        })
        print(f"  <<< {dept}: {report.total_documents} Doc, "
              f"{report.total_valid} valid, {report.total_failed} failed")
    return all_reports


def phase3_validation(all_reports):
    print("\n" + "=" * 65)
    print("FAZ 3: Dogrulama — SHMYO Toplam")
    print("=" * 65)
    checks = []
    total_docs = total_valid = total_failed = total_chars = 0
    total_pdfs = 0
    for entry in all_reports:
        r = entry["report"]
        total_docs += r.total_documents
        total_valid += r.total_valid
        total_failed += r.total_failed
        total_chars += r.total_chars
        total_pdfs += len(r.discovered_pdfs)
        print(f"\n  {entry['department']}:")
        print(f"    Documents: {r.total_documents}, Valid: {r.total_valid}, "
              f"Failed: {r.total_failed}, Chars: {r.total_chars:,}, "
              f"PDFs: {len(r.discovered_pdfs)}")
        print(f"    doc_kinds: {r.doc_kind_distribution}")

    def check(label, cond, detail=""):
        checks.append(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" +
              (f" -- {detail}" if not cond and detail else ""))

    print(f"\n  TOPLAM: {total_docs} doc, {total_valid} valid, "
          f"{total_failed} failed, {total_chars:,} chars, {total_pdfs} PDF")
    check("valid >= 20", total_valid >= 20, f"got {total_valid}")
    check("docs >= 20", total_docs >= 20, f"got {total_docs}")
    check("failed <= 10", total_failed <= 10, f"got {total_failed}")
    check("chars > 5000", total_chars > 5000, f"got {total_chars}")
    check(">= 3 birim", len(all_reports) >= 3, f"got {len(all_reports)}")
    for e in all_reports:
        check(f"{e['department'][:30]} docs>=3", e["report"].total_documents >= 3,
              f"got {e['report'].total_documents}")

    passed = sum(1 for c in checks if c)
    failed_c = sum(1 for c in checks if not c)
    print(f"\n  SONUC: {passed} PASS / {failed_c} FAIL")
    return failed_c == 0


def main():
    phase1_blueprint_check()
    all_reports = phase2_full_scrape()
    success = phase3_validation(all_reports)

    print("\n" + "=" * 65)
    print(f"GOREV 3.2.10.1 — SHMYO Deep Scrape {'TAMAMLANDI' if success else 'BASARISIZ'}!")
    print("=" * 65)

    summary = {"task": "3.2.10.1", "description": "SHMYO Harita Gudumlu Deep Scrape", "birimler": []}
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
    summary_path = OUTPUT_DIR / "shmyo_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
