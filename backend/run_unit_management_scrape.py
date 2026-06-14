"""
GİBTÜ BirimYonetim DB-first scraper çalıştırıcısı.

Güvenli varsayılan: canlı resmi allowlist sayfalarını çekip rapor üretir,
ancak --write-db verilmedikçe veritabanına yazmaz.

Örnekler:
  python run_unit_management_scrape.py --dry-run
  python run_unit_management_scrape.py --write-db
  python run_unit_management_scrape.py --write-db --output-dir data/unit_management
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401
from scrapers.unit_management_scraper import UnitManagementScraper


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "unit_management"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GİBTÜ BirimYonetim DB-first scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret.")
    parser.add_argument("--write-db", action="store_true", help="Normalize yönetim tablolarına yaz.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Rapor dosyalarının yazılacağı klasör.")
    parser.add_argument("--verbose", action="store_true", help="Ayrıntılı log yaz.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.write_db and args.dry_run:
        raise SystemExit("--write-db ile --dry-run birlikte kullanılamaz.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "unit_management_report.json"
    validation_path = output_dir / "validation_report.json"
    import_summary_path = output_dir / "import_summary.json"
    dry_run = bool(args.dry_run or not args.write_db)

    print("=" * 72)
    print("GİBTÜ Birim Yönetim Scrape Başlıyor")
    print("=" * 72)
    print(f"DB yazma: {'açık' if args.write_db else 'kapalı'}")
    print(f"Dry-run: {dry_run}")
    print(f"Rapor klasörü: {output_dir}")

    scraper = UnitManagementScraper()
    report = scraper.scrape(
        dry_run=dry_run,
        write_db=args.write_db,
        report_json=report_path,
        validation_report_json=validation_path,
        import_summary_json=import_summary_path,
    )

    print("\n" + "=" * 72)
    print("GİBTÜ Birim Yönetim Scrape Özeti")
    print("=" * 72)
    print(f"Başarılı: {report.success}")
    print(f"Run ID: {report.scrape_run_id}")
    print(f"İşlenen URL: {report.validation_report.get('processed_url_count')}/{report.target_url_count}")
    print(f"Yönetim grubu: {report.validation_report.get('group_count')}")
    print(f"Kişi kaydı: {report.validation_report.get('member_count')}")
    print(f"Boş/problemli URL: {len(report.validation_report.get('empty_urls') or [])}")
    print(f"Duplicate kayıt: {len(report.validation_report.get('duplicate_records') or [])}")
    print(f"Needs review: {len(report.validation_report.get('needs_review_records') or [])}")
    print(f"Import summary: {json.dumps(report.import_summary, ensure_ascii=False)}")
    print(f"Tam rapor: {report_path}")
    print(f"Validation report: {validation_path}")
    print(f"Import summary dosyası: {import_summary_path}")

    if report.errors:
        print("Hatalar:")
        for error in report.errors:
            print(f"  - {error}")

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
