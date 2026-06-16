"""
GİBTÜ idari birim/personel DB-first scraper çalıştırıcısı.

Güvenli varsayılan: canlı resmi allowlist sayfalarını çekip rapor üretir,
ancak --write-db verilmedikçe veritabanına yazmaz.

Örnekler:
  python run_administrative_staff_scrape.py --dry-run
  python run_administrative_staff_scrape.py --write-db
  python run_administrative_staff_scrape.py --write-db --output-dir data/administrative_staff
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401
from scrapers.administrative_staff_scraper import AdministrativeStaffScraper


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "administrative_staff"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GİBTÜ idari birim/personel DB-first scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret.")
    parser.add_argument("--write-db", action="store_true", help="Normalize idari tablolara yaz.")
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
    report_path = output_dir / "administrative_staff_report.json"
    validation_path = output_dir / "validation_report.json"
    import_summary_path = output_dir / "import_summary.json"
    diff_summary_path = output_dir / "diff_summary.json"
    dry_run = bool(args.dry_run or not args.write_db)

    print("=" * 72)
    print("GİBTÜ İdari Birim/Personel Scrape Başlıyor")
    print("=" * 72)
    print(f"DB yazma: {'açık' if args.write_db else 'kapalı'}")
    print(f"Dry-run: {dry_run}")
    print(f"Rapor klasörü: {output_dir}")

    scraper = AdministrativeStaffScraper()
    report = scraper.scrape(
        dry_run=dry_run,
        write_db=args.write_db,
        report_json=report_path,
        validation_report_json=validation_path,
        import_summary_json=import_summary_path,
        diff_summary_json=diff_summary_path,
    )

    print("\n" + "=" * 72)
    print("GİBTÜ İdari Birim/Personel Scrape Özeti")
    print("=" * 72)
    print(f"Başarılı: {report.success}")
    print(f"Run ID: {report.scrape_run_id}")
    print(f"İşlenen URL: {report.validation_report.get('processed_url_count')}/{report.target_url_count}")
    print(f"İdari birim: {report.validation_report.get('administrative_unit_count')}")
    print(f"Personel kaydı: {report.validation_report.get('staff_count')}")
    print(f"Tekil e-posta: {report.validation_report.get('unique_email_count')}")
    print(f"Warning: {report.validation_report.get('warning_count')}")
    print(f"Critical: {report.validation_report.get('critical_count')}")

    print("\nURL bazlı dağılım:")
    for item in report.validation_report.get("url_summaries") or []:
        print(
            f"  - {item['parent_unit_name']}: "
            f"birim={item['administrative_unit_count']}, "
            f"personel={item['staff_count']}, "
            f"status={item['parse_status']}, "
            f"warning={item['warning_count']}"
        )

    print("\nManuel kontrol örnekleri:")
    for sample in report.manual_check_samples[:5]:
        print(
            "  - "
            f"{sample.get('parent_unit_name')} / {sample.get('administrative_unit_name')} / "
            f"{sample.get('person_name')} / {sample.get('title_or_role')} / "
            f"{sample.get('internal_extension')} / {sample.get('email')}"
        )

    print(f"\nImport summary: {json.dumps(report.import_summary, ensure_ascii=False)}")
    print(f"Diff summary: {json.dumps(report.diff_summary, ensure_ascii=False)}")
    print(f"Tam rapor: {report_path}")
    print(f"Validation report: {validation_path}")
    print(f"Import summary dosyası: {import_summary_path}")
    print(f"Diff summary dosyası: {diff_summary_path}")

    if report.errors:
        print("Hatalar:")
        for error in report.errors:
            print(f"  - {error}")

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
