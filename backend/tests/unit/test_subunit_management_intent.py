"""Alt birim yönetim intent ve RAG sırası testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.rag_service import RagService  # noqa: E402
from app.services.subunit_management_service import SubunitManagementService  # noqa: E402
from tests.unit.test_subunit_management_service import FakeSubunitManagementRepository  # noqa: E402


class NoneService:
    def answer_chat_query(self, question):
        return None


class SubunitAnswerService:
    def answer_chat_query(self, question):
        return {"response": "* **Birim:** Bilgisayar Mühendisliği Bölümü", "sources": []}


class UnitManagementAnswerService:
    def answer_chat_query(self, question):
        return {"response": "* **Birim Yönetimi:** Eski unit management cevabı", "sources": []}


class AdministrativeAnswerService:
    def answer_chat_query(self, question):
        return {"response": "* **İdari Personel:** Eski administrative cevabı", "sources": []}


class FailingUnitManagementService:
    def answer_chat_query(self, question):
        raise AssertionError("unit_management_service subunit cevabından sonra çağrılmamalı")


class FailingSubunitManagementService:
    def answer_chat_query(self, question):
        raise AssertionError("subunit_management_service bu sorguda çağrılmamalı")


class SubunitManagementIntentTests(unittest.TestCase):
    def test_yazim_hatasi_fuzzy_eslesir(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("bilgisayar muhendisligi bolum baskani kim")

        self.assertIsNotNone(result)
        self.assertIn("Cemal AKTÜRK", result["response"])

    def test_eksik_bilgisayar_adi_belirsizlik_ister(self):
        service = SubunitManagementService(FakeSubunitManagementRepository())

        result = service.answer_chat_query("bilgisayar bölümü başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("birden fazla bölüm/program", result["response"])

    def test_rag_pipeline_subunit_servisini_unit_managementten_once_kullanir(self):
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NoneService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NoneService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NoneService()),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=NoneService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=SubunitAnswerService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=FailingUnitManagementService()),
        ):
            result = rag.query("bm bölüm başkanı kim?")

        self.assertEqual(result["response"], "* **Birim:** Bilgisayar Mühendisliği Bölümü")

    def test_rag_idari_personel_sorgusunu_eski_administrative_serviste_birakir(self):
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NoneService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NoneService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=AdministrativeAnswerService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=FailingSubunitManagementService()),
        ):
            result = rag.query("idari personel kimler?")

        self.assertEqual(result["response"], "* **İdari Personel:** Eski administrative cevabı")

    def test_rag_yuksekokul_mudur_sorgusunu_eski_unit_management_servisine_birakir(self):
        rag = RagService()
        subunit_service = SubunitManagementService(FakeSubunitManagementRepository())
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NoneService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NoneService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NoneService()),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=NoneService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=subunit_service),
            patch("app.services.rag_service.get_unit_management_service", return_value=UnitManagementAnswerService()),
        ):
            result = rag.query("Yabancı Diller yüksekokul müdürü kim?")

        self.assertEqual(result["response"], "* **Birim Yönetimi:** Eski unit management cevabı")


if __name__ == "__main__":
    unittest.main()
