"""
GİBTÜ YÖK Atlas veri scraper çalıştırıcısı.

Güvenli varsayılan: canlı API'den veri çekip snapshot/rapor üretir, ancak
--write-db verilmedikçe veritabanına yazmaz.

Örnekler:
  python run_yokatlas_gibtu_scrape.py --dry-run
  python run_yokatlas_gibtu_scrape.py --live --dry-run --limit 2
  python run_yokatlas_gibtu_scrape.py --live --dry-run
  python run_yokatlas_gibtu_scrape.py --live --write-db --export-report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401
from app.services.yokatlas_import_service import YokatlasImportService
from scrapers.yokatlas_gibtu_scraper import (
    PROGRAM_ALLOWLIST,
    YokatlasGibtuScraper,
    select_allowlist,
)


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "yokatlas"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "gibtu_yokatlas_report.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GİBTÜ YÖK Atlas allowlist tabanlı yapılandırılmış veri scraper'ı",
    )
    parser.add_argument("--live", action="store_true", help="Canlı YÖK Atlas API ile çalıştır.")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan canlı veri çek ve rapor üret.")
    parser.add_argument("--write-db", action="store_true", help="Validation politikasına göre DB import yap.")
    parser.add_argument("--limit", type=int, default=None, help="Smoke test için allowlist program sayısını sınırla.")
    parser.add_argument("--catalog-only", action="store_true", help="Detay sorgularını atlayıp yalnız katalog çek.")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="İstekler arası bekleme süresi.")
    parser.add_argument("--snapshot-dir", default=None, help="Snapshot ana klasörü.")
    parser.add_argument("--report-dir", default=None, help="Rapor dosyalarının yazılacağı klasör.")
    parser.add_argument("--export-report", action="store_true", help="Detaylı rapor paketini üret; temel raporlar zaten yazılır.")
    parser.add_argument("--output", default=str(DEFAULT_REPORT_PATH), help="Birleşik JSON rapor çıktı yolu.")
    parser.add_argument("--output-dir", default=None, help="Geriye dönük alias: snapshot ve rapor ana klasörü.")
    parser.add_argument("--verbose", action="store_true", help="Ayrıntılı log yaz.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.write_db and args.dry_run:
        raise SystemExit("--write-db ile --dry-run birlikte kullanılamaz.")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit pozitif olmalıdır.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    base_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else base_dir
    report_dir = Path(args.report_dir) if args.report_dir else base_dir
    output_path = Path(args.output)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    allowlist = select_allowlist(args.limit)
    dry_run = bool(args.dry_run or not args.write_db)

    print("=" * 72)
    print("GİBTÜ YÖK Atlas Scrape Başlıyor")
    print("=" * 72)
    print("Canlı API modu: açık (YÖK Atlas API)")
    print(f"DB yazma: {'açık' if args.write_db else 'kapalı'}")
    print(f"Dry-run: {dry_run}")
    print(f"Baz program sayısı: {len(allowlist)}/{len(PROGRAM_ALLOWLIST)}")
    print(f"Snapshot klasörü: {snapshot_dir / 'snapshots'}")
    print(f"Rapor klasörü: {report_dir}")
    print(f"Detay sorguları: {'kapalı' if args.catalog_only else 'açık'}")

    scraper = YokatlasGibtuScraper(
        output_dir=snapshot_dir,
        allowlist=allowlist,
        rate_limit_seconds=args.rate_limit,
    )
    report = scraper.scrape(
        report_json=output_path,
        fetch_details=not args.catalog_only,
        dry_run=dry_run,
        allowlist_limit=args.limit,
    )
    report_dict = report.to_dict()

    import_service = YokatlasImportService()
    db_report = import_service.import_report(
        report_dict,
        write_db=args.write_db,
        ensure_schema=True,
        config={
            "live": bool(args.live),
            "dry_run": dry_run,
            "write_db": bool(args.write_db),
            "limit": args.limit,
            "catalog_only": bool(args.catalog_only),
            "rate_limit_seconds": args.rate_limit,
        },
    )

    write_report_bundle(report_dict, db_report.to_dict(), report_dir)

    severity_counts = _severity_counts(report_dict)
    print("\n" + "=" * 72)
    print("GİBTÜ YÖK Atlas Scrape Özeti")
    print("=" * 72)
    print(f"Scrape başarılı: {report.success}")
    print(f"DB import başarılı: {db_report.success}")
    print(f"Üniversite ID: {report.university_id}")
    print(f"Veri yılı: {report.data_year}")
    print(f"Katalog sayıları: {json.dumps(report.catalog_counts, ensure_ascii=False)}")
    print(f"Eşleşen program: {report.matched_program_count}/{report.expected_program_count}")
    print(f"Eksik program: {len(report.missing_programs)}")
    print(f"Beklenmeyen program: {len(report.unexpected_programs)}")
    print(f"Normalize program: {report.normalized_program_count}")
    print(f"Snapshot: {report.snapshot_count}")
    print(f"Critical/Warning/Info: {severity_counts['critical']}/{severity_counts['warning']}/{severity_counts['info']}")
    print(f"Program DB yazımı: {'açık' if db_report.program_write_allowed else 'kapalı'}")
    print(f"DB kayıt sayıları: {json.dumps(db_report.db_counts, ensure_ascii=False)}")
    print(f"Birleşik rapor: {output_path}")
    print(f"Rapor paketi: {report_dir}")

    if report.errors or db_report.errors:
        print("Hatalar:")
        for error in [*report.errors, *db_report.errors]:
            print(f"  - {error}")

    return 0 if report.success and db_report.success else 1


def write_report_bundle(report: dict[str, Any], db_report: dict[str, Any], report_dir: Path) -> None:
    severity_counts = _severity_counts(report)
    runtime = {
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "rate_limit_seconds": report.get("rate_limit_seconds"),
    }
    scrape_summary = {
        "success": report.get("success"),
        "run_id": report.get("run_id"),
        "runtime": runtime,
        "data_year": report.get("data_year"),
        "expected_program_count": report.get("expected_program_count"),
        "matched_program_count": report.get("matched_program_count"),
        "normalized_program_count": report.get("normalized_program_count"),
        "missing_program_count": len(report.get("missing_programs") or []),
        "unexpected_program_count": len(report.get("unexpected_programs") or []),
        "critical_count": severity_counts["critical"],
        "warning_count": severity_counts["warning"],
        "info_count": severity_counts["info"],
        "snapshot_count": report.get("snapshot_count"),
        "database": db_report,
        "manual_check_samples": report.get("manual_check_samples") or [],
    }
    validation_report = {
        "run_id": report.get("run_id"),
        "summary": severity_counts,
        "results": report.get("validation_results") or [],
    }
    snapshot_manifest = {
        "run_id": report.get("run_id"),
        "snapshot_count": report.get("snapshot_count"),
        "snapshots": [
            {key: value for key, value in snapshot.items() if key != "response_payload"}
            for snapshot in report.get("snapshots") or []
        ],
    }
    _write_json(report_dir / "scrape_summary.json", scrape_summary)
    _write_json(report_dir / "validation_report.json", validation_report)
    _write_json(report_dir / "database_import_report.json", db_report)
    _write_json(report_dir / "unmatched_programs.json", report.get("missing_programs") or [])
    _write_json(report_dir / "unexpected_programs.json", report.get("unexpected_programs") or [])
    _write_json(report_dir / "snapshot_manifest.json", snapshot_manifest)


def _severity_counts(report: dict[str, Any]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in report.get("validation_results") or []:
        severity = str(issue.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
