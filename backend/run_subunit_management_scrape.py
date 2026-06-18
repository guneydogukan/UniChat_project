"""
GİBTÜ bölüm/program alt birim yönetim dry-run çalıştırıcısı.

Güvenli varsayılan: canlı resmi allowlist sayfalarını çeker ve rapor üretir,
ancak --write-db verilmedikçe veritabanına yazmaz.

Örnekler:
  python run_subunit_management_scrape.py --dry-run
  python run_subunit_management_scrape.py --dry-run --output-dir reports/subunit_management
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401
from scrapers.subunit_management_scraper import SubunitManagementScraper, build_markdown_report


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "reports" / "subunit_management"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GİBTÜ bölüm/program alt birim yönetim scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret.")
    parser.add_argument("--write-db", action="store_true", help="Ayrı subunit management tablolarına yaz.")
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
    report_path = output_dir / "subunit_management_report.json"
    validation_path = output_dir / "validation_report.json"
    import_summary_path = output_dir / "import_summary.json"
    markdown_path = output_dir / "subunit_management_report.md"
    dry_run = bool(args.dry_run or not args.write_db)

    print("=" * 72)
    print("GİBTÜ Bölüm/Program Alt Birim Yönetim Scrape Başlıyor")
    print("=" * 72)
    print(f"DB yazma: {'açık' if args.write_db else 'kapalı'}")
    print(f"Dry-run: {dry_run}")
    print(f"Rapor klasörü: {output_dir}")

    scraper = SubunitManagementScraper()
    report = scraper.scrape(
        dry_run=dry_run,
        write_db=args.write_db,
        report_json=report_path,
        validation_report_json=validation_path,
        import_summary_json=import_summary_path,
    )
    markdown_path.write_text(build_markdown_report(report), encoding="utf-8")

    validation = report.validation_report
    print("\n" + "=" * 72)
    print("GİBTÜ Bölüm/Program Alt Birim Yönetim Scrape Özeti")
    print("=" * 72)
    print(f"Başarılı: {report.success}")
    print(f"Run ID: {report.scrape_run_id}")
    print(f"İşlenen URL: {validation.get('processed_url_count')}/{validation.get('target_url_count')}")
    print(f"Total found: {validation.get('total_found')}")
    print(f"DB candidate: {validation.get('db_candidate_count')}")
    print(f"Excluded out-of-scope: {validation.get('excluded_out_of_scope_count')}")
    print(f"Valid: {validation.get('valid_count')}")
    print(f"Partial: {validation.get('partial_count')}")
    print(f"Valid DB candidate: {validation.get('valid_db_candidate_count')}")
    print(f"Partial DB candidate: {validation.get('partial_db_candidate_count')}")
    print(f"Needs review: {validation.get('needs_review_count')}")
    print(f"Empty: {validation.get('empty_count')}")
    print(f"Failed: {validation.get('failed_count')}")
    print(f"Ignored non-management: {validation.get('ignored_non_management_count')}")
    print(f"Duplicate suppressed: {validation.get('duplicate_suppressed_count')}")
    print(f"Duplicate kayıt: {len(validation.get('duplicate_records') or [])}")
    print(f"Eksik e-posta warning: {len(validation.get('missing_email_records') or [])}")
    print(f"Eksik/0000 telefon warning: {len(validation.get('missing_phone_records') or [])}")
    print(f"Write ready: {'evet' if validation.get('write_ready') else 'hayır'}")
    print(f"DB write blockers: {json.dumps(validation.get('db_write_blockers') or [], ensure_ascii=False)}")
    print(f"Import summary: {json.dumps(report.import_summary, ensure_ascii=False)}")
    print(f"Tam rapor: {report_path}")
    print(f"Validation report: {validation_path}")
    print(f"Markdown rapor: {markdown_path}")
    print(f"Import summary dosyası: {import_summary_path}")

    if report.errors:
        print("Hatalar:")
        for error in report.errors:
            print(f"  - {error}")

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
