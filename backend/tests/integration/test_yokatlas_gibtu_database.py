"""YÖK Atlas fake API → import service integration testleri.

Bu testler canlı internete veya gerçek PostgreSQL'e bağlanmaz. Import service'in
DB yazma politikasını ve idempotent davranışı in-memory repository ile sınar.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.yokatlas_import_service import YokatlasImportService  # noqa: E402
from scrapers.yokatlas_gibtu_scraper import YokatlasGibtuScraper  # noqa: E402
from tests.unit.test_yokatlas_gibtu_scraper import (  # noqa: E402
    FakeYokatlasClient,
    _allowlist_rows,
)


class InMemoryYokatlasRepository:
    def __init__(self, fail_after_snapshots: bool = False):
        self.fail_after_snapshots = fail_after_snapshots
        self.runs = {}
        self.snapshots = {}
        self.programs = {}
        self.program_years = {}
        self.conditions = {}
        self.validations = {}
        self.ensure_schema_calls = 0

    def ensure_schema(self):
        self.ensure_schema_calls += 1

    def import_report(self, report, allow_program_write, validation_status, config=None):
        staged = {
            "runs": copy.deepcopy(self.runs),
            "snapshots": copy.deepcopy(self.snapshots),
            "programs": copy.deepcopy(self.programs),
            "program_years": copy.deepcopy(self.program_years),
            "conditions": copy.deepcopy(self.conditions),
            "validations": copy.deepcopy(self.validations),
        }
        counts = {
            "snapshots_inserted": 0,
            "snapshots_updated": 0,
            "programs_inserted": 0,
            "programs_updated": 0,
            "program_years_inserted": 0,
            "program_years_updated": 0,
            "quota_statistics_upserted": 0,
            "score_statistics_upserted": 0,
            "conditions_inserted": 0,
            "validation_results_inserted": 0,
            "skipped_programs": 0,
        }
        staged["runs"][report["run_id"]] = {
            "validation_status": validation_status,
            "config": config or {},
        }
        for snapshot in report.get("snapshots") or []:
            key = snapshot["snapshot_id"]
            if key in staged["snapshots"]:
                counts["snapshots_updated"] += 1
            else:
                counts["snapshots_inserted"] += 1
            staged["snapshots"][key] = snapshot

        if self.fail_after_snapshots:
            raise RuntimeError("rollback test hatası")

        if allow_program_write:
            for program in report.get("programs") or []:
                code = program["program"]["program_code"]
                year = program["program_year"]["data_year"]
                py_key = (code, year)
                if code in staged["programs"]:
                    counts["programs_updated"] += 1
                else:
                    counts["programs_inserted"] += 1
                staged["programs"][code] = program
                if py_key in staged["program_years"]:
                    counts["program_years_updated"] += 1
                else:
                    counts["program_years_inserted"] += 1
                staged["program_years"][py_key] = program
                counts["quota_statistics_upserted"] += 1
                counts["score_statistics_upserted"] += 1
                staged["conditions"][py_key] = {
                    condition["condition_code"]: condition
                    for condition in program.get("conditions") or []
                }
                counts["conditions_inserted"] += len(staged["conditions"][py_key])
        else:
            counts["skipped_programs"] = len(report.get("programs") or [])

        staged["validations"][report["run_id"]] = list(report.get("validation_results") or [])
        counts["validation_results_inserted"] = len(staged["validations"][report["run_id"]])

        self.runs = staged["runs"]
        self.snapshots = staged["snapshots"]
        self.programs = staged["programs"]
        self.program_years = staged["program_years"]
        self.conditions = staged["conditions"]
        self.validations = staged["validations"]
        return counts

    def fetch_counts(self, scrape_run_id):
        return {
            "yokatlas_scrape_runs": len(self.runs),
            "yokatlas_raw_snapshots": len(self.snapshots),
            "yokatlas_programs": len(self.programs),
            "yokatlas_program_years": len(self.program_years),
            "yokatlas_quota_statistics": len(self.program_years),
            "yokatlas_score_statistics": len(self.program_years),
            "yokatlas_program_conditions": sum(len(items) for items in self.conditions.values()),
            "yokatlas_validation_results": len(self.validations.get(scrape_run_id, [])),
        }


def _scrape_report(rows=None):
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = YokatlasGibtuScraper(
            client=FakeYokatlasClient(rows or _allowlist_rows()),
            output_dir=Path(tmpdir),
            rate_limit_seconds=0,
        )
        return scraper.scrape(dry_run=True).to_dict()


class YokatlasDatabaseIntegrationTests(unittest.TestCase):
    def test_fake_api_scraper_validation_database_write_query(self):
        report = _scrape_report()
        repository = InMemoryYokatlasRepository()
        service = YokatlasImportService(repository)

        db_report = service.import_report(report, write_db=True, ensure_schema=True)

        self.assertTrue(db_report.success)
        self.assertTrue(db_report.program_write_allowed)
        self.assertEqual(repository.ensure_schema_calls, 1)
        self.assertEqual(db_report.db_counts["yokatlas_programs"], 19)
        self.assertEqual(db_report.db_counts["yokatlas_program_years"], 19)
        self.assertGreater(db_report.db_counts["yokatlas_program_conditions"], 0)
        self.assertEqual(db_report.db_counts["yokatlas_raw_snapshots"], report["snapshot_count"])

    def test_ayni_veri_ikinci_importta_duplicate_olusturmaz(self):
        report = _scrape_report()
        repository = InMemoryYokatlasRepository()
        service = YokatlasImportService(repository)

        first = service.import_report(report, write_db=True, ensure_schema=False)
        second = service.import_report(report, write_db=True, ensure_schema=False)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(second.db_counts["yokatlas_programs"], 19)
        self.assertEqual(second.db_counts["yokatlas_program_years"], 19)
        self.assertGreater(second.updated["programs"], 0)
        self.assertGreater(second.updated["program_years"], 0)

    def test_critical_validation_varken_program_verisi_yazilmaz(self):
        rows = _allowlist_rows()[:-1]
        report = _scrape_report(rows)
        repository = InMemoryYokatlasRepository()
        service = YokatlasImportService(repository)

        db_report = service.import_report(report, write_db=True, ensure_schema=False)

        self.assertTrue(db_report.success)
        self.assertEqual(db_report.validation_status, "invalid")
        self.assertFalse(db_report.program_write_allowed)
        self.assertEqual(db_report.db_counts["yokatlas_programs"], 0)
        self.assertGreater(db_report.skipped["programs"], 0)
        self.assertGreater(db_report.critical_count, 0)

    def test_transaction_rollback_hata_halinde_staged_veriyi_saklamaz(self):
        report = _scrape_report()
        repository = InMemoryYokatlasRepository(fail_after_snapshots=True)
        service = YokatlasImportService(repository)

        db_report = service.import_report(report, write_db=True, ensure_schema=False)

        self.assertFalse(db_report.success)
        self.assertEqual(repository.fetch_counts(report["run_id"])["yokatlas_raw_snapshots"], 0)
        self.assertEqual(repository.fetch_counts(report["run_id"])["yokatlas_programs"], 0)

    def test_write_db_kapaliyken_database_yazilmaz(self):
        report = _scrape_report()
        repository = InMemoryYokatlasRepository()
        service = YokatlasImportService(repository)

        db_report = service.import_report(report, write_db=False, ensure_schema=False)

        self.assertTrue(db_report.success)
        self.assertFalse(db_report.program_write_allowed)
        self.assertEqual(repository.fetch_counts(report["run_id"])["yokatlas_scrape_runs"], 0)
        self.assertEqual(db_report.skipped["programs"], 19)


if __name__ == "__main__":
    unittest.main()
