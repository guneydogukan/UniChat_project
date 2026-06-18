"""
GİBTÜ bölüm/program katalog dry-run çalıştırıcısı.

Güvenli varsayılan: canlı resmi seed kaynaklarını ve cached YÖK Atlas raporunu
kullanarak kalite raporu üretir; --write-db verilmedikçe DB'ye yazmaz.
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
from app.repositories.program_catalog_repository import ProgramCatalogRepository
from app.services.program_catalog_service import (
    ProgramCatalogInMemoryRepository,
    ProgramCatalogService,
)
from scrapers.program_catalog_scraper import ProgramCatalogScraper, build_markdown_report


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "reports" / "program_catalog"

SMOKE_CASES: tuple[tuple[str, str], ...] = (
    ("GİBTÜ’de hangi fakülteler var?", "faculty_list_query"),
    ("GİBTÜ’de hangi meslek yüksekokulları var?", "vocational_school_list_query"),
    ("GİBTÜ’de hangi yüksekokullar var?", "school_list_query"),
    ("GİBTÜ’de hangi bölümler var?", "department_list_query"),
    ("MDBF bölümleri neler?", "faculty_departments_query"),
    ("İlahiyat Fakültesinde hangi bölümler var?", "faculty_departments_query"),
    ("Sağlık Bilimleri Fakültesinde hangi bölümler var?", "faculty_departments_query"),
    ("SHMYO programları neler?", "vocational_school_programs_query"),
    ("TBMYO programları neler?", "vocational_school_programs_query"),
    ("Bilgisayar Mühendisliği var mı?", "program_exists_query"),
    ("bilgisayar müh var mı?", "program_exists_query"),
    ("FTR hangi fakültede?", "program_faculty_query"),
    ("Ebelik var mı?", "program_exists_query"),
    ("GİBTÜ’de hukuk var mı?", "program_exists_query"),
    ("GİBTÜ’de diş hekimliği var mı?", "program_exists_query"),
    ("Yabancı Diller Yüksekokulu bölüm mü?", "academic_unit_list_query"),
    ("Ön lisans programları neler?", "associate_degree_programs_query"),
    ("Lisans programları neler?", "undergraduate_programs_query"),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GİBTÜ bölüm/program katalog scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret.")
    parser.add_argument("--write-db", action="store_true", help="Ayrı program_catalog tablolarına yaz.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Rapor klasörü.")
    parser.add_argument("--live-yokatlas", action="store_true", help="Cached YÖK Atlas yerine canlı YÖK Atlas scrape dene.")
    parser.add_argument("--max-pages", type=int, default=35, help="Bu dry-run için işlenecek GİBTÜ sayfa üst sınırı (sert limit 150).")
    parser.add_argument("--max-candidate-pool", type=int, default=120, help="Bu dry-run için aday link havuzu üst sınırı (sert limit 300).")
    parser.add_argument("--timeout", type=int, default=8, help="URL başına timeout saniyesi (sert üst sınır 15).")
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
    report_path = output_dir / "program_catalog_report.json"
    validation_path = output_dir / "validation_report.json"
    markdown_path = output_dir / "program_catalog_report.md"
    import_summary_path = output_dir / "import_summary.json"
    smoke_path = output_dir / "chatbot_db_first_smoke.json"

    dry_run = bool(args.dry_run or not args.write_db)

    print("=" * 72)
    print("GİBTÜ Bölüm/Program Katalog Scrape Başlıyor")
    print("=" * 72)
    print(f"DB yazma: {'açık' if args.write_db else 'kapalı'}")
    print(f"Dry-run: {dry_run}")
    print(f"YÖK Atlas modu: {'live' if args.live_yokatlas else 'cached'}")
    print(f"Rapor klasörü: {output_dir}")

    max_pages = min(max(args.max_pages, 1), 150)
    max_candidate_pool = min(max(args.max_candidate_pool, 1), 300)
    timeout = min(max(args.timeout, 1), 15)
    scraper = ProgramCatalogScraper(
        use_live_yokatlas=args.live_yokatlas,
        max_gibtu_pages=max_pages,
        max_candidate_pool=max_candidate_pool,
        timeout=timeout,
        rate_limit_seconds=0.2,
    )
    report = scraper.scrape(
        dry_run=True,
        write_db=False,
        output_dir=output_dir,
    )
    report_dict = report.to_dict()
    smoke = run_chatbot_smoke_tests(report_dict)
    report_dict["validation_report"]["chatbot_db_first_smoke"] = smoke
    report_dict["validation_report"]["db_write_ready"] = _db_write_ready(report_dict["validation_report"])
    report_dict["validation_report"]["db_write_blockers"] = _db_write_blockers(report_dict["validation_report"])
    report.validation_report = report_dict["validation_report"]
    report_dict["import_summary"] = {
        "dry_run": dry_run,
        "write_db_requested": bool(args.write_db),
        "write_db_executed": False,
        "production_db_write_attempted": False,
        "note": "DB yazımı yapılmadı.",
    }

    if args.write_db:
        if not report_dict["validation_report"]["db_write_ready"]:
            raise SystemExit("DB write_ready=false; yazım durduruldu.")
        repo = ProgramCatalogRepository()
        report_dict["import_summary"] = repo.import_report(report_dict)

    _write_json(report_path, report_dict)
    _write_json(validation_path, report_dict["validation_report"])
    _write_json(import_summary_path, report_dict["import_summary"])
    _write_json(smoke_path, smoke)
    markdown_path.write_text(build_markdown_report(report), encoding="utf-8")

    validation = report_dict["validation_report"]
    print("\n" + "=" * 72)
    print("GİBTÜ Bölüm/Program Katalog Scrape Özeti")
    print("=" * 72)
    print(f"Başarılı: {report_dict.get('success')}")
    print(f"Run ID: {report_dict.get('scrape_run_id')}")
    print(f"İşlenen URL: {validation.get('processed_url_count')}")
    print(f"Atlanan URL: {validation.get('skipped_url_count')}")
    print(f"Başarılı URL: {validation.get('successful_url_count')}")
    print(f"Boş/erişilemeyen URL: {validation.get('failed_url_count')}")
    print(f"Limit nedeniyle işlenmeyen URL: {validation.get('not_processed_due_to_limit_count')}")
    print(f"Akademik birim: {validation.get('academic_unit_count')}")
    print(f"Fakülte/Yüksekokul/MYO/Enstitü: {validation.get('faculty_count')}/{validation.get('school_count')}/{validation.get('vocational_school_count')}/{validation.get('institute_count')}")
    print(f"Bölüm/Program: {validation.get('department_count')}/{validation.get('program_count')}")
    print(f"Match status: {json.dumps(validation.get('match_status_counts') or {}, ensure_ascii=False)}")
    print(f"Needs review: {len(validation.get('needs_review_records') or [])}")
    print(f"Duplicate: {validation.get('duplicate_count')}")
    print(f"Alias: {validation.get('alias_count')}")
    print(f"Critical error: {validation.get('critical_error_count')}")
    print(f"Chatbot smoke: {smoke['success_count']}/{smoke['total']}")
    print(f"DB write ready: {'evet' if validation.get('db_write_ready') else 'hayır'}")
    print(f"DB write blockers: {json.dumps(validation.get('db_write_blockers') or [], ensure_ascii=False)}")
    print(f"Production DB write attempted: {report_dict['import_summary'].get('production_db_write_attempted')}")
    print(f"Tam rapor: {report_path}")
    print(f"Validation report: {validation_path}")
    print(f"Markdown rapor: {markdown_path}")
    print(f"Smoke test raporu: {smoke_path}")
    print(f"Import summary: {import_summary_path}")

    return 0 if report_dict.get("success") else 1


def run_chatbot_smoke_tests(report: dict[str, Any]) -> dict[str, Any]:
    service = ProgramCatalogService(ProgramCatalogInMemoryRepository.from_report(report))
    results = []
    success_count = 0
    for question, expected_intent in SMOKE_CASES:
        answer = service.answer_chat_query(question)
        passed = bool(
            answer
            and answer.get("metadata", {}).get("db_first") is True
            and answer.get("metadata", {}).get("rag_fallback_used") is False
            and answer.get("metadata", {}).get("intent") == expected_intent
            and answer.get("response")
        )
        if passed:
            success_count += 1
        results.append({
            "question": question,
            "expected_intent": expected_intent,
            "passed": passed,
            "actual_intent": answer.get("metadata", {}).get("intent") if answer else None,
            "response_preview": (answer.get("response", "")[:220] if answer else None),
        })
    return {
        "success": success_count >= 10,
        "success_count": success_count,
        "total": len(SMOKE_CASES),
        "results": results,
    }


def _db_write_ready(validation: dict[str, Any]) -> bool:
    smoke = validation.get("chatbot_db_first_smoke") or {}
    return bool(
        validation.get("critical_error_count") == 0
        and validation.get("duplicate_count") == 0
        and validation.get("schema_validation_success") is True
        and validation.get("dry_run_report_complete") is True
        and int(smoke.get("success_count") or 0) >= 10
    )


def _db_write_blockers(validation: dict[str, Any]) -> list[str]:
    blockers = []
    smoke = validation.get("chatbot_db_first_smoke") or {}
    if validation.get("critical_error_count") != 0:
        blockers.append("critical_error_count_not_zero")
    if validation.get("duplicate_count") != 0:
        blockers.append("duplicate_count_not_zero")
    if validation.get("schema_validation_success") is not True:
        blockers.append("schema_validation_failed")
    if validation.get("dry_run_report_complete") is not True:
        blockers.append("dry_run_report_incomplete")
    if int(smoke.get("success_count") or 0) < 10:
        blockers.append("chatbot_db_first_smoke_less_than_10")
    return blockers


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
