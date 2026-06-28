"""Derslik konum DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.classroom_location_intent import normalize_for_match, normalize_room_code  # noqa: E402
from app.services.classroom_location_service import ClassroomLocationService  # noqa: E402


class FakeClassroomRepository:
    def __init__(self, records: list[dict] | None = None, spaces: list[dict] | None = None):
        self.records = records or []
        self.spaces = spaces or []
        self.buildings = [
            {
                "building_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "normalized_building_name": "muhendislik ve doga bilimleri fakultesi",
                "aliases": [
                    "MDBF",
                    "Mühendislik",
                    "Mühendislik Fakültesi",
                    "Mühendislik Binası",
                    "Mühendislik ve Doğa Bilimleri Fakültesi",
                ],
                "normalized_aliases": [
                    "mdbf",
                    "muhendislik",
                    "muhendislik fakultesi",
                    "muhendislik binasi",
                    "muhendislik ve doga bilimleri fakultesi",
                ],
            }
        ]

    def list_buildings(self):
        return self.buildings

    def find_by_room_code(self, normalized_room_code):
        return [record for record in self.records if record["normalized_room_code"] == normalized_room_code]

    def find_by_room_and_building(self, normalized_room_code, normalized_building_name):
        return [
            record
            for record in self.records
            if record["normalized_room_code"] == normalized_room_code
            and record["normalized_building_name"] == normalized_building_name
        ]

    def find_by_department_and_room(self, department_code, normalized_room_code):
        return [
            record
            for record in self.records
            if record["normalized_room_code"] == normalized_room_code
            and record.get("department_code") == department_code.upper()
        ]

    def list_by_department(self, department_code):
        return [record for record in self.records if record.get("department_code") == department_code.upper()]

    def list_spaces(self):
        return self.spaces

    def find_spaces_by_building(self, normalized_building_name):
        return [
            record
            for record in self.spaces
            if record["normalized_building_name"] == normalized_building_name
        ]

    def find_spaces_by_department(self, department_code):
        return [record for record in self.spaces if record.get("department_code") == department_code.upper()]


def _record(
    room_code: str,
    floor_label: str,
    room_type: str,
    capacity: int | None,
    department_name: str | None = None,
    department_code: str | None = None,
    is_shared: bool = False,
) -> dict:
    building_name = "Mühendislik ve Doğa Bilimleri Fakültesi"
    return {
        "id": room_code,
        "building_name": building_name,
        "floor_label": floor_label,
        "room_code": room_code,
        "room_type": room_type,
        "capacity": capacity,
        "department_name": department_name,
        "department_code": department_code,
        "is_shared": is_shared,
        "normalized_room_code": normalize_room_code(room_code),
        "normalized_building_name": normalize_for_match(building_name),
        "source_file": "Derslikler.xlsx",
    }


def _space_record(
    space_name: str,
    floor_label: str,
    aliases: list[str],
    department_code: str | None = None,
) -> dict:
    building_name = "Mühendislik ve Doğa Bilimleri Fakültesi"
    normalized_aliases = [normalize_for_match(alias) for alias in aliases]
    return {
        "id": space_name,
        "building_name": building_name,
        "floor_label": floor_label,
        "space_name": space_name,
        "space_type": "İdari Ofis",
        "department_name": space_name,
        "department_code": department_code,
        "aliases": aliases,
        "normalized_space_name": normalize_for_match(space_name),
        "normalized_aliases": normalized_aliases,
        "normalized_building_name": normalize_for_match(building_name),
        "source_file": "Derslikler.xlsx",
    }


def _service(records: list[dict] | None = None, spaces: list[dict] | None = None) -> ClassroomLocationService:
    return ClassroomLocationService(
        FakeClassroomRepository(
            records if records is not None else _sample_records(),
            spaces if spaces is not None else _sample_spaces(),
        )
    )


def _sample_records() -> list[dict]:
    return [
        _record("113", "1", "Amfi", 104, "Ortak Kullanım", "ORTAK", True),
        _record("z-114", "Zemin", "Laboratuvar", 32, "Bilgisayar Mühendisliği", "BM"),
        _record("202", "2", "Derslik", 48, "Bilgisayar Mühendisliği", "BM"),
        _record("202", "3", "Derslik", 45, "Elektrik-Elektronik Mühendisliği", "EEM"),
        _record("209", "2", "Laboratuvar", 30, "Elektrik-Elektronik Mühendisliği", "EEM"),
        _record("206", "2", "Konferans Salonu", 80, "Ortak Kullanım", "ORTAK", True),
    ]


def _sample_spaces() -> list[dict]:
    return [
        _space_record(
            "Akademik personel odaları, Fakülte Sekreterliği",
            "4",
            ["Akademik personel odaları, Fakülte Sekreterliği", "Akademik Personel Odaları", "Fakülte Sekreterliği", "Sekreterlik"],
        ),
        _space_record("Öğrenci İşleri", "3", ["Öğrenci İşleri", "Öğrenci İşleri Ofisi"]),
        _space_record("Dekan, Dekan Yardımcısı", "4", ["Dekan, Dekan Yardımcısı", "Dekanlık", "Dekan", "Dekan Yardımcılığı", "Dekan Yardımcısı"]),
        _space_record("Bilgisayar Mühendisliği Bölüm Başkanlığı", "4", ["Bilgisayar Mühendisliği Bölüm Başkanlığı", "Bölüm Başkanlığı", "BM", "BM Bölüm Başkanlığı"], "BM"),
        _space_record("Elektrik-Elektronik Mühendisliği Bölüm Başkanlığı", "4", ["Elektrik-Elektronik Mühendisliği Bölüm Başkanlığı", "Bölüm Başkanlığı", "EEM", "EEM Bölüm Başkanlığı"], "EEM"),
    ]


class ClassroomLocationServiceTests(unittest.TestCase):
    def test_muhendislik_fakultesi_113_nerede(self):
        result = _service().answer_chat_query("mühendislik fakültesi 113 nerede")

        self.assertIsNotNone(result)
        self.assertIn("Mühendislik ve Doğa Bilimleri Fakültesi", result["response"])
        self.assertIn("113", result["response"])
        self.assertIn("1. kat", result["response"])
        self.assertIn("Amfi", result["response"])
        self.assertIn("104", result["response"])
        self.assertFalse(result["metadata"]["rag_fallback_used"])

    def test_mdbf_alias_113(self):
        result = _service().answer_chat_query("mdbf 113")

        self.assertIsNotNone(result)
        self.assertIn("113", result["response"])
        self.assertIn("1. kat", result["response"])

    def test_113_nolu_amfi_tekilse_dogrudan_doner(self):
        result = _service().answer_chat_query("113 nolu amfi nerede")

        self.assertIsNotNone(result)
        self.assertIn("amfiyi", result["response"])

    def test_z_114_ve_z114_normalize_edilir(self):
        service = _service()

        dashed = service.answer_chat_query("z-114 nerede")
        compact = service.answer_chat_query("z114 nerede")

        self.assertIsNotNone(dashed)
        self.assertIsNotNone(compact)
        self.assertIn("zemin kat", dashed["response"])
        self.assertIn("z-114", compact["response"])

    def test_bm_202_hangi_katta_department_ile_ayrisir(self):
        result = _service().answer_chat_query("BM 202 hangi katta")

        self.assertIsNotNone(result)
        self.assertIn("2. kat", result["response"])
        self.assertIn("Bilgisayar Mühendisliği", result["response"])

    def test_eem_209_nerede(self):
        result = _service().answer_chat_query("EEM 209 nerede")

        self.assertIsNotNone(result)
        self.assertIn("209", result["response"])
        self.assertIn("2. kat", result["response"])
        self.assertIn("Elektrik-Elektronik Mühendisliği", result["response"])

    def test_bilgisayar_muhendisligi_derslikleri_listelenir(self):
        result = _service().answer_chat_query("bilgisayar mühendisliği derslikleri")

        self.assertIsNotNone(result)
        self.assertIn("Bilgisayar Mühendisliği", result["response"])
        self.assertIn("202", result["response"])
        self.assertIn("z-114", result["response"])

    def test_program_hangi_fakultede_sorusu_classroom_tarafindan_sahiplenilmez(self):
        result = _service().answer_chat_query("Bilgisayar Mühendisliği hangi fakültede?")

        self.assertIsNone(result)

    def test_olmayan_derslik_rage_dusmeden_guvenli_yanit_doner(self):
        result = _service().answer_chat_query("olmayan derslik 999 nerede")

        self.assertIsNotNone(result)
        self.assertEqual(result["response"], "Bu derslik veritabanında bulunamadı.")
        self.assertFalse(result["metadata"]["rag_fallback_used"])

    def test_muhendislik_206_konferans_salonu_nerede(self):
        result = _service().answer_chat_query("mühendislik 206 konferans salonu nerede")

        self.assertIsNotNone(result)
        self.assertIn("206", result["response"])
        self.assertIn("Konferans Salonu", result["response"])
        self.assertIn("2. kat", result["response"])

    def test_ogrenci_isleri_nerede_idari_alan_doner(self):
        result = _service().answer_chat_query("öğrenci işleri nerede")

        self.assertIsNotNone(result)
        self.assertIn("Öğrenci İşleri", result["response"])
        self.assertIn("3. kat", result["response"])
        self.assertIn("İdari Ofis", result["response"])
        self.assertFalse(result["metadata"]["rag_fallback_used"])

    def test_dekanlik_nerede_idari_alan_doner(self):
        result = _service().answer_chat_query("dekanlık nerede")

        self.assertIsNotNone(result)
        self.assertIn("Dekanlık", result["response"])
        self.assertIn("4. kat", result["response"])

    def test_fakulte_sekreterligi_hangi_katta_idari_alan_doner(self):
        result = _service().answer_chat_query("fakülte sekreterliği hangi katta")

        self.assertIsNotNone(result)
        self.assertIn("Fakülte Sekreterliği", result["response"])
        self.assertIn("4. kat", result["response"])

    def test_bm_bolum_baskanligi_nerede_department_ile_eslesir(self):
        result = _service().answer_chat_query("BM bölüm başkanlığı nerede")

        self.assertIsNotNone(result)
        self.assertIn("BM Bölüm Başkanlığı", result["response"])
        self.assertIn("4. kat", result["response"])

    def test_dekan_kim_classroom_servisi_tarafindan_sahiplenilmez(self):
        result = _service().answer_chat_query("dekan kim")

        self.assertIsNone(result)

    def test_sekreterlik_telefonu_classroom_servisi_tarafindan_sahiplenilmez(self):
        result = _service().answer_chat_query("sekreterlik telefonu nedir")

        self.assertIsNone(result)

    def test_idari_ofis_nerede_cokluysa_secenek_ister(self):
        result = _service().answer_chat_query("idari ofis nerede")

        self.assertIsNotNone(result)
        self.assertIn("birden fazla idari alanla eşleşiyor", result["response"])

    def test_oda_kodu_fuzzy_eslesmez_113_114_getirmez(self):
        service = _service([_record("114", "1", "Derslik", 40)])

        result = service.answer_chat_query("113 nolu derslik nerede")

        self.assertIsNotNone(result)
        self.assertEqual(result["response"], "Bu derslik veritabanında bulunamadı.")

    def test_ayni_oda_kodu_cokluysa_secenek_ister(self):
        service = _service([
            _record("202", "2", "Derslik", 48, "Bilgisayar Mühendisliği", "BM"),
            _record("202", "3", "Derslik", 45, "Elektrik-Elektronik Mühendisliği", "EEM"),
        ])

        result = service.answer_chat_query("202 nolu derslik nerede")

        self.assertIsNotNone(result)
        self.assertIn("birden fazla derslikle eşleşiyor", result["response"])

    def test_rag_pipeline_derslik_sorusunda_llm_oncesi_fast_path_kullanir(self):
        from app.services.rag_service import RagService

        class FakeClassroomService:
            def answer_chat_query(self, question):
                return {"response": "Derslik cevabı", "sources": [], "metadata": {"service": "classroom"}}

        with patch("app.services.rag_service.get_classroom_location_service", return_value=FakeClassroomService()):
            result = RagService().query("mühendislik fakültesi 113 nerede")

        self.assertEqual(result["response"], "Derslik cevabı")


if __name__ == "__main__":
    unittest.main()
