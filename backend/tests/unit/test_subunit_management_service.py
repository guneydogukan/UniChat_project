"""Alt birim yönetim DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.subunit_management_service import SubunitManagementService  # noqa: E402


class FakeSubunitManagementRepository:
    def __init__(self) -> None:
        self.targets = [
            {
                "id": "bm",
                "target_unit_name": "Bilgisayar Mühendisliği Bölümü",
                "target_unit_name_normalized": "bilgisayar muhendisligi bolumu",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "department_or_program_name": "Bilgisayar Mühendisliği Bölümü",
                "department_or_program_name_normalized": "bilgisayar muhendisligi bolumu",
                "unit_type": "department",
                "scope_type": "department_program_management",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18",
                "source_page_type": "BirimYonetim",
                "source_birim_id": 18,
                "aliases": ["bm", "bilgisayar muhendisligi"],
            },
            {
                "id": "ftr-program",
                "target_unit_name": "Fizyoterapi Programı / Fizyoterapi ve Rehabilitasyon Bölümü",
                "target_unit_name_normalized": "fizyoterapi programi fizyoterapi ve rehabilitasyon bolumu",
                "parent_unit_name": None,
                "department_or_program_name": "Fizyoterapi Programı / Fizyoterapi ve Rehabilitasyon Bölümü",
                "department_or_program_name_normalized": "fizyoterapi programi fizyoterapi ve rehabilitasyon bolumu",
                "unit_type": "program",
                "scope_type": "department_program_management",
                "source_url": "https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id=96",
                "source_page_type": "BirimAkademikPersonel",
                "source_birim_id": 96,
                "aliases": ["ftr", "fizyoterapi"],
            },
            {
                "id": "ftr-bolum",
                "target_unit_name": "Sağlık Bilimleri Fakültesi / Fizyoterapi ve Rehabilitasyon Bölümü",
                "target_unit_name_normalized": "saglik bilimleri fakultesi fizyoterapi ve rehabilitasyon bolumu",
                "parent_unit_name": "Sağlık Bilimleri Fakültesi",
                "department_or_program_name": "Fizyoterapi ve Rehabilitasyon Bölümü",
                "department_or_program_name_normalized": "fizyoterapi ve rehabilitasyon bolumu",
                "unit_type": "department",
                "scope_type": "department_program_management",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=32",
                "source_page_type": "BirimYonetim",
                "source_birim_id": 32,
                "aliases": ["ftr bolum", "fizyoterapi"],
            },
        ]
        self.records = {
            "bm": [
                {
                    "record_id": "r1",
                    "target_id": "bm",
                    "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18",
                    "source_page_type": "BirimYonetim",
                    "target_unit_name": "Bilgisayar Mühendisliği Bölümü",
                    "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                    "department_or_program_name": "Bilgisayar Mühendisliği Bölümü",
                    "scope_type": "department_program_management",
                    "management_role": "Bölüm Başkanı",
                    "management_role_key": "bolum baskani",
                    "academic_title": "Doç. Dr.",
                    "person_name": "Cemal AKTÜRK",
                    "full_display_name": "Doç. Dr. Cemal AKTÜRK",
                    "email": "cemal.akturk@gibtu.edu.tr",
                    "phone": "2231",
                    "profile_url": "http://pbs.gibtu.edu.tr/cemal.akturk",
                    "scraped_at": "2026-06-17T10:00:00Z",
                    "parse_status": "valid",
                    "group_title": "Bölüm Başkanı",
                    "group_order": 1,
                    "record_order": 1,
                },
                {
                    "record_id": "r2",
                    "target_id": "bm",
                    "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18",
                    "source_page_type": "BirimYonetim",
                    "target_unit_name": "Bilgisayar Mühendisliği Bölümü",
                    "department_or_program_name": "Bilgisayar Mühendisliği Bölümü",
                    "scope_type": "department_program_management",
                    "management_role": "Bölüm Başkan Yardımcısı",
                    "management_role_key": "bolum baskan yardimcisi",
                    "academic_title": "Dr. Öğr. Üyesi",
                    "person_name": "Muhammet Yasin PAK",
                    "full_display_name": "Dr. Öğr. Üyesi Muhammet Yasin PAK",
                    "email": "muhammetyasin.pak@gibtu.edu.tr",
                    "phone": "2221",
                    "scraped_at": "2026-06-17T10:00:00Z",
                    "parse_status": "valid",
                    "group_title": "Bölüm Başkan Yardımcısı",
                    "group_order": 2,
                    "record_order": 2,
                },
            ],
            "ftr-program": [],
            "ftr-bolum": [],
        }

    def list_targets(self):
        return list(self.targets)

    def get_management_records(self, target_id, role_keys=None):
        return list(self.records.get(target_id, []))


class SubunitManagementServiceTests(unittest.TestCase):
    def test_bm_aliasi_bolum_baskanini_dbden_yanitlar(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("bm bölüm başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("Bilgisayar Mühendisliği Bölümü", result["response"])
        self.assertIn("Bölüm Başkanı", result["response"])
        self.assertIn("Cemal AKTÜRK", result["response"])
        self.assertIn("cemal.akturk@gibtu.edu.tr", result["response"])
        self.assertNotIn("Muhammet Yasin PAK", result["response"])

    def test_baskan_yardimcisi_filtrelenir(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("Bilgisayar Mühendisliği bölüm başkan yardımcısı kim?")

        self.assertIsNotNone(result)
        self.assertIn("Muhammet Yasin PAK", result["response"])
        self.assertNotIn("Cemal AKTÜRK", result["response"])

    def test_fizyoterapi_belirsizse_netlestirme_ister(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("Fizyoterapi başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("birden fazla bölüm/program", result["response"])
        self.assertIn("Fizyoterapi Programı", result["response"])
        self.assertIn("Fizyoterapi ve Rehabilitasyon Bölümü", result["response"])

    def test_program_contexti_fizyoterapi_programini_secer(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("Fizyoterapi program başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("veritabanında bulunamadı", result["response"])
        self.assertIn("BirimAkademikPersonel.aspx?id=96", result["response"])

    def test_fakulte_dekani_sorgusuna_karismaz(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("Mühendislik fakültesi dekanı kim?")

        self.assertIsNone(result)

    def test_eski_genel_yonetim_ve_idari_sorgularina_karismaz(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        queries = [
            "fakülte dekanı kim?",
            "Yabancı Diller yüksekokul müdürü kim?",
            "fakülte sekreteri kim?",
            "idari personel kimler?",
            "fakülte yönetim kurulu kimlerden oluşuyor?",
            "yüksekokul yönetim bilgileri nelerdir?",
        ]

        for query in queries:
            with self.subTest(query=query):
                self.assertIsNone(service.answer_chat_query(query))

    def test_bolum_belirsizse_rag_fallback_yapmadan_birim_ister(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("Bölüm başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("hangi bölüm veya program", result["response"].lower())


if __name__ == "__main__":
    unittest.main()
