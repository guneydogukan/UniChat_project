"""
Gorev 3.2.8.4 — Tip Fakultesi: Harita Gudumlu Deep Scrape
Tek blueprint (BirimID=20) — 55KB, derin menu yapisi bekleniyor.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrapers.blueprint_parser import parse_blueprint
from scrapers.map_guided_scraper import MapGuidedScraper

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
BLUEPRINT = GIBTU / "FAKÜLTELER" / "Tıp Fakültesi" / "Tıp.html"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"


def main():
    # --- FAZ 1: Blueprint ---
    print("=" * 65)
    print("FAZ 1: Blueprint Parse — Tip Fakultesi")
    print("=" * 65)
    tree = parse_blueprint(BLUEPRINT)
    s = tree.stats
    urls = tree.to_url_list()
    print(f"  BirimID:        {s['birim_id']}")
    print(f"  Menu items:     {s['menu_item_count']}")
    print(f"  Scrapable URLs: {s['scrapable_url_count']}")
    print(f"  PDF links:      {s['pdf_count']}")
    print(f"  External links: {len(tree.get_external_links())}")
    print(f"  URL list:       {len(urls)}")

    # --- FAZ 2: Scrape ---
    print("\n" + "=" * 65)
    print("FAZ 2: Canli Deep Scrape — Tip Fakultesi")
    print("=" * 65)
    scraper = MapGuidedScraper(
        blueprint_path=BLUEPRINT,
        category="bolumler",
        department="Tip Fakultesi",
        doc_kind="genel",
        contact_unit="Tip Fakultesi Dekanligi",
        contact_info="tip@gibtu.edu.tr",
    )
    report = scraper.scrape_all(dry_run=False)
    json_path = OUTPUT_DIR / "tip_fakultesi_output.json"
    scraper.save_report_json(report, str(json_path))

    # --- FAZ 3: Dogrulama ---
    print("\n" + "=" * 65)
    print("FAZ 3: Dogrulama — Tip Fakultesi")
    print("=" * 65)
    checks = []

    def check(label, cond, detail=""):
        checks.append(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" +
              (f" -- {detail}" if not cond and detail else ""))

    print(f"  Documents:  {report.total_documents}")
    print(f"  Valid:      {report.total_valid}")
    print(f"  Failed:     {report.total_failed}")
    print(f"  Chars:      {report.total_chars:,}")
    print(f"  PDFs:       {len(report.discovered_pdfs)}")
    print(f"  doc_kinds:  {report.doc_kind_distribution}")

    check("valid >= 10", report.total_valid >= 10, f"got {report.total_valid}")
    check("docs >= 10", report.total_documents >= 10, f"got {report.total_documents}")
    check("failed <= 5", report.total_failed <= 5, f"got {report.total_failed}")
    check("chars > 5000", report.total_chars > 5000, f"got {report.total_chars}")

    passed = sum(1 for c in checks if c)
    failed_c = sum(1 for c in checks if not c)
    print(f"\n  SONUC: {passed} PASS / {failed_c} FAIL")

    success = failed_c == 0
    print("\n" + "=" * 65)
    print(f"GOREV 3.2.8.4 — Tip Fakultesi Deep Scrape {'TAMAMLANDI' if success else 'BASARISIZ'}!")
    print("=" * 65)

    summary = {
        "task": "3.2.8.4",
        "description": "Tip Fakultesi Harita Gudumlu Deep Scrape",
        "department": "Tip Fakultesi",
        "json_path": str(json_path),
        "total_documents": report.total_documents,
        "total_valid": report.total_valid,
        "total_failed": report.total_failed,
        "total_chars": report.total_chars,
        "pdf_count": len(report.discovered_pdfs),
        "doc_kind_distribution": report.doc_kind_distribution,
    }
    summary_path = OUTPUT_DIR / "tip_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nOzet rapor: {summary_path}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
