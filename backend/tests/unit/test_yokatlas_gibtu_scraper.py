"""GİBTÜ YÖK Atlas scraper birim testleri."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers.yokatlas_gibtu_scraper import (  # noqa: E402
    BIRIM_TURU_ID_BY_LEVEL,
    EXPECTED_UNIVERSITY_ID,
    LEVEL_LISANS,
    LEVEL_ONLISANS,
    PROGRAM_ALLOWLIST,
    RawSnapshotStore,
    SEARCH_PATH,
    UNIVERSITIES_PATH,
    DataNormalizer,
    ProgramAllowlistValidator,
    ValidationEngine,
    YokatlasGibtuScraper,
    _to_decimal,
    _to_int,
    select_allowlist,
)


def _row(
    unit: str,
    program: str,
    level: str,
    code: int,
    year: int = 2025,
    extra: dict | None = None,
) -> dict:
    birim_turu_id = BIRIM_TURU_ID_BY_LEVEL[level]
    payload = {
        "yil": year,
        "kilavuzKodu": code,
        "universiteId": EXPECTED_UNIVERSITY_ID,
        "universiteAdi": "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ",
        "universiteTuru": "DEVLET",
        "uniIlKodu": 27,
        "uniIlAdi": "GAZİANTEP",
        "fymkId": code + 1000,
        "fymkAdi": unit,
        "fymkIlAdi": "GAZİANTEP",
        "birimId": code + 2000,
        "birimAdi": program,
        "birimGrupId": code + 3000,
        "birimGrupAdi": program,
        "birimTuruId": birim_turu_id,
        "birimTuruAdi": "LISANS" if level == LEVEL_LISANS else "ÖNLISANS",
        "ogrenimTuruId": 86,
        "ogrenimTuruAdi": "Örgün Öğretim",
        "ogrenimSuresi": 4 if level == LEVEL_LISANS else 2,
        "puanTuru": "SAY" if level == LEVEL_LISANS else "TYT",
        "ogrenimDiliId": 181,
        "ogrenimDiliAdi": "Türkçe",
        "bursOraniId": 0,
        "kontenjan": 40,
        "kontenjanObs": 1,
        "gkY": 40,
        "obkY": 1,
        "minPuan": 333.23603,
        "basariSirasi": 210078,
        "kosul": "144",
        "kosulList": [{"144": "Mühendislik programları için başarı sırası koşulu uygulanır."}],
    }
    if extra:
        payload.update(extra)
    return payload


def _allowlist_rows() -> list[dict]:
    rows = []
    for index, entry in enumerate(PROGRAM_ALLOWLIST, start=1):
        rows.append(_row(entry.academic_unit, entry.program_name, entry.level, 111210000 + index))
    return rows


class FakeYokatlasClient:
    def __init__(self, catalog_rows: list[dict]) -> None:
        self.catalog_rows = catalog_rows
        self.calls: list[tuple[str, dict | None]] = []

    def get_json(self, path: str):
        self.calls.append((path, None))
        if path == UNIVERSITIES_PATH:
            return [
                {
                    "universiteAdi": "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ",
                    "universiteId": EXPECTED_UNIVERSITY_ID,
                }
            ]
        raise AssertionError(f"Beklenmeyen GET path: {path}")

    def post_json(self, path: str, payload: dict):
        self.calls.append((path, payload))
        if path != SEARCH_PATH:
            raise AssertionError(f"Beklenmeyen POST path: {path}")

        filters = payload.get("filters") or {}
        if "kilavuzKodu" in filters:
            code = filters["kilavuzKodu"]
            content = [row for row in self.catalog_rows if row["kilavuzKodu"] == code]
            return {
                "content": content,
                "totalElements": len(content),
                "yil": 2025,
                "source": "test",
            }

        birim_turu_id = filters.get("birimTuruId")
        content = [row for row in self.catalog_rows if row["birimTuruId"] == birim_turu_id]
        return {
            "content": content,
            "totalElements": len(content),
            "yil": 2025,
            "source": "test",
        }


class YokatlasAllowlistTests(unittest.TestCase):
    def test_allowlist_19_program_ve_duzey_dagilimi_icerir(self):
        lisans = [entry for entry in PROGRAM_ALLOWLIST if entry.level == LEVEL_LISANS]
        onlisans = [entry for entry in PROGRAM_ALLOWLIST if entry.level == LEVEL_ONLISANS]

        self.assertEqual(len(PROGRAM_ALLOWLIST), 19)
        self.assertEqual(len(lisans), 14)
        self.assertEqual(len(onlisans), 5)

    def test_allowlist_tam_katalog_ile_eslesir(self):
        result = ProgramAllowlistValidator().validate(_allowlist_rows())

        self.assertEqual(len(result.matched_rows), 19)
        self.assertEqual(result.missing_entries, [])
        self.assertEqual(result.unexpected_rows, [])
        self.assertFalse(any(issue.severity == "critical" for issue in result.issues))

    def test_eksik_ve_beklenmeyen_programlari_yakalar(self):
        rows = _allowlist_rows()[:-1]
        rows.append(_row("Başka Fakülte", "Beklenmeyen Program", LEVEL_LISANS, 999999999))

        result = ProgramAllowlistValidator().validate(rows)

        self.assertEqual(len(result.missing_entries), 1)
        self.assertEqual(len(result.unexpected_rows), 1)
        self.assertTrue(any(issue.code == "missing_allowlisted_program" for issue in result.issues))
        self.assertTrue(any(issue.code == "unexpected_program" for issue in result.issues))


class YokatlasNormalizerTests(unittest.TestCase):
    def test_turkce_decimal_ve_basari_sirasi_donusur(self):
        self.assertEqual(_to_decimal("502,97621"), "502.97621")
        self.assertEqual(_to_int("35.763"), 35763)

    def test_null_ve_ozel_durumlar_null_doner(self):
        for value in ("---", "", None, "Dolmadı", "Yeni açıldı"):
            with self.subTest(value=value):
                self.assertIsNone(_to_decimal(value))
                self.assertIsNone(_to_int(value))

    def test_parantezli_program_adi_dil_ve_varyanti_ayrir(self):
        normalizer = DataNormalizer()
        row = _row(
            "İlahiyat Fakültesi",
            "İlahiyat (Arapça) (M.T.O.K.)",
            LEVEL_LISANS,
            111210116,
            extra={
                "ogrenimDiliAdi": "Arapça",
                "birimEkTuru": "M.T.O.K.",
            },
        )

        normalized = normalizer.normalize_program(row, "catalog123", "detail123")

        self.assertEqual(normalized["program"]["program_name_raw"], "İlahiyat (Arapça) (M.T.O.K.)")
        self.assertEqual(normalized["program"]["program_name_clean"], "İlahiyat")
        self.assertEqual(normalized["program"]["program_language_from_name"], "Arapça")
        self.assertEqual(normalized["program"]["program_variant"], "M.T.O.K.")

    def test_ingilizce_program_adi_temizlenir_ama_raw_korunur(self):
        normalizer = DataNormalizer()
        row = _row(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Endüstri Mühendisliği (İngilizce)",
            LEVEL_LISANS,
            111210102,
            extra={"ogrenimDiliAdi": "İngilizce"},
        )

        normalized = normalizer.normalize_program(row, "catalog123", "detail123")

        self.assertEqual(normalized["program"]["program_name_raw"], "Endüstri Mühendisliği (İngilizce)")
        self.assertEqual(normalized["program"]["program_name_clean"], "Endüstri Mühendisliği")
        self.assertEqual(normalized["program"]["program_language_from_name"], "İngilizce")
        self.assertEqual(normalized["education"]["language"], "İngilizce")

    def test_burs_ve_indirim_sozlukten_ayrisir(self):
        normalizer = DataNormalizer()
        row = _row(
            "Örnek Fakülte",
            "Örnek Program (%50 İndirimli)",
            LEVEL_LISANS,
            123456789,
            extra={"bursOraniId": 156, "bursOraniAdi": "%50 İndirimli"},
        )

        normalized = normalizer.normalize_program(row, "catalog123", "detail123")

        self.assertEqual(normalized["education"]["funding_id"], 156)
        self.assertEqual(normalized["education"]["funding_type"], "%50 İndirimli")


class YokatlasSnapshotTests(unittest.TestCase):
    def test_snapshot_utf8_yazar_ve_hash_uretir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RawSnapshotStore(tmpdir, "run123")
            payload = {"program": "İlahiyat (Arapça)", "puan": "502,97621"}

            record = store.store_json("detail", "https://yokatlas.yok.gov.tr/api/test", "POST", {"x": 1}, payload)

            self.assertTrue(record.snapshot_id)
            self.assertTrue(record.response_hash)
            self.assertIsNotNone(record.path)
            text = Path(record.path).read_text(encoding="utf-8")
            self.assertIn("İlahiyat", text)

    def test_ayni_response_ayni_hashi_uretir(self):
        store = RawSnapshotStore(None, "run123")
        payload = {"b": 2, "a": "Türkçe"}

        first = store.store_json("detail", "https://yokatlas.yok.gov.tr/api/test", "POST", {"x": 1}, payload)
        second = store.store_json("detail", "https://yokatlas.yok.gov.tr/api/test", "POST", {"x": 1}, {"a": "Türkçe", "b": 2})

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.response_hash, second.response_hash)

    def test_snapshot_normalize_kayitla_iliskilenir(self):
        row = _row("Tıp Fakültesi", "Tıp", LEVEL_LISANS, 111210046)
        normalized = DataNormalizer().normalize_program(row, "catalog123", "detail123")

        self.assertEqual(normalized["program_year"]["catalog_snapshot_id"], "catalog123")
        self.assertEqual(normalized["program_year"]["detail_snapshot_id"], "detail123")
        self.assertEqual(normalized["source"]["detail_snapshot_id"], "detail123")


class YokatlasValidationTests(unittest.TestCase):
    def _valid_program(self):
        row = _row("Tıp Fakültesi", "Tıp", LEVEL_LISANS, 111210046)
        normalized = DataNormalizer().normalize_program(row, "catalog123", "detail123")
        normalized["_raw_condition_codes"] = "144"
        return normalized

    def test_duplicate_program_kodu_yakalanir(self):
        program = self._valid_program()
        issues = ValidationEngine()._validate_program_codes([program, program])

        self.assertTrue(any(issue.code == "duplicate_program_code_year" for issue in issues))

    def test_eksik_source_url_critical_verir(self):
        program = self._valid_program()
        program["program_year"]["source_url"] = ""

        issues = ValidationEngine()._validate_program_records(
            [program],
            {111210046: {"catalog_snapshot_id": "catalog123", "detail_snapshot_id": "detail123"}},
        )

        self.assertTrue(any(issue.code == "missing_source_url" and issue.severity == "critical" for issue in issues))

    def test_eksik_snapshot_critical_verir(self):
        program = self._valid_program()

        issues = ValidationEngine()._validate_program_records([program], {111210046: {}})

        self.assertTrue(any(issue.code == "missing_raw_snapshot" and issue.severity == "critical" for issue in issues))

    def test_gecersiz_puan_turu_warning_verir(self):
        program = self._valid_program()
        program["education"]["score_type"] = "XYZ"

        issues = ValidationEngine()._validate_program_records(
            [program],
            {111210046: {"catalog_snapshot_id": "catalog123", "detail_snapshot_id": "detail123"}},
        )

        self.assertTrue(any(issue.code == "unexpected_score_type" and issue.severity == "warning" for issue in issues))

    def test_eksik_kosul_aciklamasi_warning_verir(self):
        program = self._valid_program()
        program["conditions"] = []

        issues = ValidationEngine()._validate_program_records(
            [program],
            {111210046: {"catalog_snapshot_id": "catalog123", "detail_snapshot_id": "detail123"}},
        )

        self.assertTrue(any(issue.code == "condition_text_missing" and issue.severity == "warning" for issue in issues))


class YokatlasPipelineTests(unittest.TestCase):
    def test_limit_iki_programda_bir_lisans_bir_onlisans_secer(self):
        limited = select_allowlist(2)

        self.assertEqual(len(limited), 2)
        self.assertEqual({entry.level for entry in limited}, {LEVEL_LISANS, LEVEL_ONLISANS})

    def test_fake_api_ile_snapshot_ve_rapor_uretir(self):
        rows = _allowlist_rows()
        client = FakeYokatlasClient(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"
            scraper = YokatlasGibtuScraper(client=client, output_dir=tmpdir, rate_limit_seconds=0)

            report = scraper.scrape(report_json=report_path)

            self.assertTrue(report.success)
            self.assertEqual(report.university_id, EXPECTED_UNIVERSITY_ID)
            self.assertEqual(report.matched_program_count, 19)
            self.assertEqual(report.normalized_program_count, 19)
            self.assertEqual(report.catalog_counts, {"lisans": 14, "onlisans": 5})
            self.assertTrue(report_path.exists())
            self.assertGreaterEqual(report.snapshot_count, 22)
            snapshot_files = list((Path(tmpdir) / "snapshots").rglob("*.json"))
            self.assertEqual(len(snapshot_files), report.snapshot_count)

            validation_codes = {item["code"] for item in report.validation_results}
            self.assertIn("nets_not_available", validation_codes)
            self.assertFalse(any(item["severity"] == "critical" for item in report.validation_results))


if __name__ == "__main__":
    unittest.main()
