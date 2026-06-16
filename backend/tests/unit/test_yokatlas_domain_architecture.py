"""YÖK Atlas domain modülü raporlama ve diff testleri."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from run_yokatlas_gibtu_scrape import replay_report_bundle, write_report_bundle  # noqa: E402
from yokatlas.contracts import EXPECTED_API_UNIVERSITY_ID, PUBLIC_UNIVERSITY_CODE, SOURCE_SYSTEM  # noqa: E402
from yokatlas.discovery import ProgramAllowlistValidator  # noqa: E402
from yokatlas.extraction import RawSnapshotStore  # noqa: E402
from yokatlas.reporting import build_report_bundle  # noqa: E402
from yokatlas.validation import validate_program_payloads  # noqa: E402
from yokatlas.versioning import diff_reports  # noqa: E402


def _program(
    code: str,
    name: str,
    *,
    unit_name: str = "İlahiyat Fakültesi",
    language: str = "Türkçe",
    year: int = 2026,
) -> dict:
    return {
        "university": {
            "source_university_id": EXPECTED_API_UNIVERSITY_ID,
            "name": "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ",
            "type": "DEVLET",
            "city": "GAZİANTEP",
        },
        "academic_unit": {
            "source_unit_id": 111,
            "name": unit_name,
        },
        "program": {
            "program_code": code,
            "program_name_raw": name,
            "program_name_clean": name.replace(" (Arapça)", "").replace(" (M.T.O.K.)", ""),
            "program_language_from_name": "Arapça" if "Arapça" in name else None,
            "program_variant": "M.T.O.K." if "M.T.O.K." in name else None,
            "level": "lisans",
            "duration_years": 4,
            "is_active": True,
        },
        "program_year": {
            "data_year": year,
            "source_url": f"https://yokatlas.yok.gov.tr/lisans.php?y={code}",
            "catalog_snapshot_id": "catalog123",
            "detail_snapshot_id": "detail123",
        },
        "education": {
            "score_type": "SÖZ",
            "education_mode": "Örgün Öğretim",
            "language": language,
            "funding_type": "Ücretsiz",
        },
        "quota_statistics": {
            "general": {"quota": 40, "placed": 40},
        },
        "admission_statistics": {
            "base_score": "400.12345",
            "base_rank": 100000,
        },
        "last_admitted_nets": {
            "status": "not_available",
            "fields": {},
        },
        "conditions": [
            {
                "condition_code": "144",
                "condition_text": "Başarı sırası koşulu uygulanır.",
            }
        ],
        "source": {
            "source_url": f"https://yokatlas.yok.gov.tr/lisans.php?y={code}",
        },
    }


def _report(programs: list[dict], *, run_id: str = "run-2026", year: int = 2026) -> dict:
    return {
        "success": True,
        "run_id": run_id,
        "started_at": f"{year}-06-15T10:00:00+03:00",
        "finished_at": f"{year}-06-15T10:01:00+03:00",
        "dry_run": True,
        "university_id": EXPECTED_API_UNIVERSITY_ID,
        "university_name": "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ",
        "data_year": year,
        "expected_program_count": len(programs),
        "matched_program_count": len(programs),
        "normalized_program_count": len(programs),
        "snapshot_count": 0,
        "snapshots": [],
        "programs": programs,
        "missing_programs": [],
        "unexpected_programs": [],
        "validation_results": [],
        "errors": [],
    }


class YokatlasDomainArchitectureTests(unittest.TestCase):
    def test_moduler_import_yollari_eski_siniflari_disari_acar(self):
        self.assertEqual(PUBLIC_UNIVERSITY_CODE, "1112")
        self.assertEqual(SOURCE_SYSTEM, "YÖK Atlas")
        self.assertIsNotNone(ProgramAllowlistValidator)
        self.assertIsNotNone(RawSnapshotStore)

    def test_quality_rules_panel_eksigini_manual_review_uyarisi_yapar(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        issues = validate_program_payloads(report)

        self.assertTrue(any(issue["rule_code"] == "panel_not_discovered" for issue in issues))
        self.assertFalse(any(issue["severity"] == "critical" for issue in issues))

    def test_report_bundle_import_ready_ve_manual_review_uretir(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        bundle = build_report_bundle(
            report,
            {
                "success": True,
                "errors": [],
                "write_db_requested": True,
                "program_write_allowed": True,
            },
        )

        self.assertIn("crawl_run_manifest", bundle)
        self.assertIn("validation_report", bundle)
        self.assertIn("diff_report", bundle)
        self.assertIn("manual_review_items", bundle)
        self.assertIn("import_ready_report", bundle)
        self.assertTrue(bundle["import_ready_report"]["ready_for_db_write"])
        self.assertFalse(bundle["import_ready_report"]["manual_review_required"])
        self.assertEqual(bundle["import_ready_report"]["manual_review_decision"], "manual_review_passed")

    def test_netler_kapsam_disiyken_import_ready_bloke_olmaz(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        bundle = build_report_bundle(
            report,
            {
                "success": True,
                "errors": [],
                "write_db_requested": True,
                "program_write_allowed": True,
            },
        )

        core_results = bundle["validation_report"]["core_results"]
        self.assertTrue(any(item["status"] == "out_of_scope" for item in core_results))
        self.assertEqual(bundle["validation_report"]["summary"]["critical"], 0)
        self.assertFalse(bundle["import_ready_report"]["manual_review_required"])
        self.assertTrue(bundle["import_ready_report"]["ready_for_db_write"])

    def test_aciklanabilir_placed_gt_quota_expected_warning_olur(self):
        program = _program("111210012", "Bilgisayar Mühendisliği")
        program["quota_statistics"] = {
            "general": {"quota": 75, "placed": 77},
            "school_first": {"quota": 2, "placed": 0},
            "earthquake": {"quota": 8, "placed": 8},
            "women_34_plus": {"quota": 0, "placed": 0},
            "martyr_veteran": {"quota": 0, "placed": 0},
            "total_quota_known": 85,
            "total_placed_known": 85,
        }
        report = _report([program])
        report["validation_results"] = [
            {
                "severity": "warning",
                "code": "placed_gt_quota",
                "message": "Yerleşen sayısı genel kontenjandan büyük.",
                "program_code": 111210012,
            }
        ]

        bundle = build_report_bundle(report, {"success": True, "errors": []})

        expected = [
            item for item in bundle["validation_report"]["core_results"]
            if item["original_rule_code"] == "placed_gt_quota"
        ]
        self.assertEqual(expected[0]["status"], "expected_warning")
        self.assertEqual(expected[0]["rule_code"], "expected_warning")
        self.assertFalse(expected[0]["manual_review_required"])
        self.assertEqual(bundle["manual_review_items"], [])

    def test_core_import_ready_with_warnings_ama_db_write_istenmediyse_ready_false(self):
        program = _program("111210012", "Bilgisayar Mühendisliği")
        program["quota_statistics"] = {
            "general": {"quota": 75, "placed": 77},
            "school_first": {"quota": 2, "placed": 0},
            "earthquake": {"quota": 8, "placed": 8},
            "women_34_plus": {"quota": 0, "placed": 0},
            "martyr_veteran": {"quota": 0, "placed": 0},
            "total_quota_known": 85,
            "total_placed_known": 85,
        }
        report = _report([program])
        report["expected_program_count"] = 19
        report["matched_program_count"] = 19
        report["validation_results"] = [
            {
                "severity": "warning",
                "code": "placed_gt_quota",
                "message": "Yerleşen sayısı genel kontenjandan büyük.",
                "program_code": 111210012,
            }
        ]

        bundle = build_report_bundle(
            report,
            {
                "success": True,
                "errors": [],
                "write_db_requested": False,
                "program_write_allowed": False,
            },
        )

        import_ready = bundle["import_ready_report"]
        self.assertEqual(import_ready["manual_review_decision"], "manual_review_passed")
        self.assertEqual(import_ready["core_import_decision"], "import_ready_with_warnings")
        self.assertFalse(import_ready["ready_for_db_write"])
        self.assertIn("database_write_not_requested", import_ready["blocking_reasons"])

    def test_scrape_basarisizsa_import_ready_bloke_edilir(self):
        report = _report([])
        report["success"] = False
        report["errors"] = ["YÖK Atlas bağlantısı zaman aşımına uğradı."]

        bundle = build_report_bundle(report, {"success": True, "errors": []})

        self.assertFalse(bundle["import_ready_report"]["ready_for_db_write"])
        self.assertEqual(bundle["import_ready_report"]["status"], "import_blocked")
        self.assertIn("scrape_failed", bundle["import_ready_report"]["blocking_reasons"])

    def test_basarisiz_current_rapor_onceki_yili_pasif_saymaz(self):
        previous = _report([_program("111210046", "Tıp", unit_name="Tıp Fakültesi", year=2025)], year=2025)
        current = _report([], run_id="failed-run")
        current["success"] = False
        current["errors"] = ["YÖK Atlas bağlantısı zaman aşımına uğradı."]

        diff = diff_reports(current, previous)

        self.assertTrue(diff["summary"]["skipped"])
        self.assertEqual(diff["summary"]["skip_reason"], "current_scrape_failed")
        self.assertEqual(diff["summary"]["passive_program_count"], 0)
        self.assertEqual(diff["passive_programs"], [])

    def test_diff_onceki_rapor_verilince_yeni_pasif_ve_kimlik_degisimini_bulur(self):
        previous = _report(
            [
                _program("111210116", "İlahiyat (Arapça) (M.T.O.K.)", language="Arapça", year=2025),
                _program("111210046", "Tıp", unit_name="Tıp Fakültesi", year=2025),
            ],
            run_id="run-2025",
            year=2025,
        )
        current = _report(
            [
                _program("111210116", "İlahiyat", language="Türkçe"),
                _program("111210999", "Yeni Program"),
            ],
        )

        diff = diff_reports(current, previous)

        self.assertTrue(diff["summary"]["compared"])
        self.assertEqual(diff["summary"]["new_program_count"], 1)
        self.assertEqual(diff["summary"]["passive_program_count"], 1)
        statuses = {change["status"] for change in diff["changes"]}
        self.assertIn("new_program_candidate", statuses)
        self.assertIn("passive_candidate", statuses)
        self.assertIn("identity_field_changed", statuses)

    def test_write_report_bundle_eski_ve_yeni_raporlari_yazar(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            write_report_bundle(report, {"success": True, "errors": []}, report_dir)

            for filename in (
                "scrape_summary.json",
                "validation_report.json",
                "database_import_report.json",
                "snapshot_manifest.json",
                "crawl_run_manifest.json",
                "diff_report.json",
                "manual_review_items.json",
                "import_ready_report.json",
            ):
                with self.subTest(filename=filename):
                    self.assertTrue((report_dir / filename).exists())

            manifest = json.loads((report_dir / "crawl_run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["crawl_run_id"], "run-2026")

    def test_replay_report_bundle_ag_ve_db_kullanmadan_rapor_uretir(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source_report = base / "source_report.json"
            output_report = base / "replayed_report.json"
            report_dir = base / "reports"
            source_report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(StringIO()):
                exit_code = replay_report_bundle(source_report, output_report, report_dir)

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_report.exists())
            self.assertTrue((report_dir / "import_ready_report.json").exists())
            import_ready = json.loads((report_dir / "import_ready_report.json").read_text(encoding="utf-8"))
            self.assertFalse(import_ready["ready_for_db_write"])
            self.assertTrue(import_ready["data_quality_ready"])
            self.assertEqual(import_ready["status"], "import_blocked")
            self.assertFalse(import_ready["db_report"]["write_db_requested"])

    def test_replay_ayni_raporda_validation_sonuclarini_cogaltmaz(self):
        report = _report([_program("111210116", "İlahiyat (Arapça) (M.T.O.K.)")])

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report_path = base / "report.json"
            report_dir = base / "reports"
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(StringIO()):
                replay_report_bundle(report_path, report_path, report_dir)
                replay_report_bundle(report_path, report_path, report_dir)

            replayed = json.loads(report_path.read_text(encoding="utf-8"))
            validation_keys = [
                (item.get("code"), str(item.get("program_code")))
                for item in replayed.get("validation_results") or []
            ]
            self.assertEqual(len(validation_keys), len(set(validation_keys)))
            self.assertEqual(validation_keys.count(("panel_not_discovered", "111210116")), 1)


if __name__ == "__main__":
    unittest.main()
