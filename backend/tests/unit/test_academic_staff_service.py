"""Akademik kadro DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.academic_staff_service import AcademicStaffService  # noqa: E402


class FakeAcademicRepository:
    def __init__(self) -> None:
        self.units = [
            {
                "id": "faculty-1",
                "unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name_normalized": "muhendislik ve doga bilimleri fakultesi",
                "unit_type": "faculty",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/view/universityView.jsp?id=1",
            },
            {
                "id": "dept-1",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
                "unit_name_normalized": "bilgisayar muhendisligi bolumu",
                "unit_type": "department",
                "parent_unit_id": "faculty-1",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
            },
        ]
        self.staff = [
            {
                "person_id": "person-1",
                "full_name": "Ayşe YILMAZ",
                "normalized_name": "ayse yilmaz",
                "title": "Doç. Dr.",
                "person_source_status": "verified_from_kadro_veri",
                "source_status": "verified_from_kadro_veri",
                "confidence_status": "verified_from_kadro_veri",
                "confidence_score": 0.99,
                "needs_manual_review": False,
                "unit_id": "dept-1",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
                "unit_type": "department",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1",
                "last_checked_at": "2026-06-10T00:00:00Z",
                "external_profiles": [
                    {
                        "profile_type": "yok_akademik",
                        "profile_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1",
                        "external_id": "A1",
                        "raw_data": {
                            "kadro_parent_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
                            "kadro_department": "Bilgisayar Mühendisliği Bölümü",
                            "kadro_subunit": "Bilgisayar Mühendisliği Anabilim Dalı",
                        },
                    }
                ],
            }
        ]

    def list_units(self):
        return list(self.units)

    def get_child_units(self, parent_unit_id):
        return [unit for unit in self.units if unit.get("parent_unit_id") == parent_unit_id]

    def get_staff_by_unit(self, unit_id):
        if unit_id == "dept-1":
            return list(self.staff)
        return []

    def search_persons(self, normalized_query):
        return []


class AcademicStaffServiceTests(unittest.TestCase):
    def test_bolum_kadrosu_dbden_yanitlanir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Bilgisayar mühendisliği akademik kadrosu kimlerden oluşuyor?")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("Ayşe YILMAZ", response)
        self.assertIn("kaynak: YÖK Akademik", response)
        self.assertNotIn("YÖK Atlas", response)

    def test_fakulte_sorusunda_bolum_program_secimi_istenir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Mühendislik ve Doğa Bilimleri Fakültesi akademik kadrosu")

        self.assertIsNotNone(result)
        self.assertIn("bölüm/program seçimi gerekli", result["response"].lower())
        self.assertIn("Bilgisayar Mühendisliği Bölümü", result["response"])

    def test_belirsiz_kadro_sorusu_rag_fallback_icin_none_donmez(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Akademik kadro listesini gösterir misin?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi bölüm veya program", result["response"])

    def test_yonetim_sorusu_rag_akisina_birakilir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Bilgisayar mühendisliği bölüm başkanı kim?")

        self.assertIsNone(result)

    def test_dekan_sorusu_rag_akisina_birakilir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Mühendislik fakültesi dekanı?")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
