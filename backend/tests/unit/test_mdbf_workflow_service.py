"""MDBF workflow/form DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.rag_service import RagService  # noqa: E402
from app.services.workflow_service import WorkflowService  # noqa: E402


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.forms = [
            self._form("Ders Muafiyet Başvuru Formu", "course_exemption", "muafiyet-basvuru.pdf"),
            self._form("Ders Muafiyet Değerlendirme Formu", "course_exemption", "muafiyet-degerlendirme.pdf"),
            self._form("Mazeret Ders Kayıt Formu", "late_registration", "mazeret-ders-kayit.pdf"),
            self._form("Kayıt Dondurma Başvuru Formu", "freeze_registration", "kayit-dondurma.pdf"),
            self._form("Sınav Kağıdına İtiraz ( Maddi Hata ) Formu", "exam_appeal", "sinav-itiraz.pdf"),
        ]
        self.workflows = {
            "course_registration": self._workflow(
                "course_registration",
                "Ders Kayıt İş Akış Şeması",
                [],
            ),
            "course_exemption": self._workflow(
                "course_exemption",
                "Ders Muafiyet İş Akış Şeması",
                [self.forms[0], self.forms[1]],
            ),
            "late_registration": self._workflow(
                "late_registration",
                "Mazeretli Kayıt Yenileme İş Akış Şeması",
                [self.forms[2]],
            ),
            "exam_appeal": self._workflow(
                "exam_appeal",
                "Sınavlara İtiraz İşlemleri İş Akış Şeması",
                [self.forms[4]],
            ),
            "freeze_registration": self._workflow(
                "freeze_registration",
                "Öğrenci Kayıt Dondurma İşlemleri İş Akış Şeması",
                [self.forms[3]],
            ),
            "excuse_exam": self._workflow(
                "excuse_exam",
                "Mazeret Sınavı İş Akış Şeması",
                [],
            ),
            "quota_determination": self._workflow(
                "quota_determination",
                "Öğrenci Kontenjanları Belirleme İşlemleri İş Akış Şeması",
                [],
            ),
        }

    @staticmethod
    def _form(name: str, process_key: str, filename: str) -> dict:
        return {
            "form_name": name,
            "process_key": process_key,
            "download_url": f"https://www.gibtu.edu.tr/Medya/Birim/Dosya/{filename}",
        }

    @staticmethod
    def _workflow(process_key: str, title: str, forms: list[dict]) -> dict:
        return {
            "id": process_key,
            "unit_code": "MDBF",
            "process_key": process_key,
            "title": title,
            "workflow_summary": f"{title} özeti.",
            "first_action_for_student": "Öğrenci başvuru belgelerini hazırlar.",
            "final_outcome": "Belgeler arşivlenir.",
            "pdf_url": f"https://www.gibtu.edu.tr/Medya/Birim/Dosya/{process_key}.pdf",
            "steps": [
                {"step_order": 1, "actor": "Öğrenci", "action_text": "Öğrenci başvuru belgelerini hazırlar."},
                {"step_order": 2, "actor": "MDBF Sekreterliği", "action_text": "Dilekçe kayıt altına alınır."},
            ],
            "forms": forms,
        }

    def get_workflow_by_process(self, process_key: str, unit_code: str = "MDBF") -> dict | None:
        return self.workflows.get(process_key)

    def list_forms(self, unit_code: str = "MDBF") -> list[dict]:
        return list(self.forms)


class MdbfWorkflowServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WorkflowService(FakeWorkflowRepository())

    def test_mazeret_sinavi_formu_yoksa_form_uydurmaz(self) -> None:
        result = self.service.answer_chat_query("MDBF mazeret sınavı formu nerede?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "excuse_exam")
        self.assertIn("doğrudan bir form bağlantısı bulunmuyor", result["response"])
        self.assertIn("MDBF İş Akış Şeması", result["response"])

    def test_ders_kaydini_kacirma_late_registration_doner(self) -> None:
        result = self.service.answer_chat_query("Mühendislik fakültesinde ders kaydını kaçırdım ne yapmalıyım?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "late_registration")
        self.assertIn("Mazeretli Kayıt Yenileme", result["response"])
        self.assertIn("Mazeret Ders Kayıt Formu", result["response"])

    def test_ders_kayit_sureci_takvim_degil_workflow_doner(self) -> None:
        result = self.service.answer_chat_query("ders kayıt sürecini adım adım anlatır mısın?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "course_registration")
        self.assertIn("Ders Kayıt İş Akış Şeması", result["response"])
        self.assertIn("Süreç adımları", result["response"])
        self.assertIn("İlk işlem:", result["response"])

    def test_mdbf_ders_kayit_sureci_takvime_birakilmaz(self) -> None:
        self.assertTrue(self.service.should_preempt_calendar("MDBF öğrencisiyim, ders kayıt sürecini adım adım anlatır mısın?"))

    def test_muafiyet_dilekcesi_surec_ve_form_doner(self) -> None:
        result = self.service.answer_chat_query("Daha önce aldığım dersten muaf olmak için dilekçe örneği var mı?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "course_exemption")
        self.assertIn("Ders Muafiyet İş Akış Şeması", result["response"])
        self.assertIn("Ders Muafiyet Başvuru Formu", result["response"])

    def test_sinav_notu_itiraz_sureci_exam_appeal_doner(self) -> None:
        result = self.service.answer_chat_query("Sınav notuma itiraz süreci nasıl işler?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "exam_appeal")
        self.assertIn("Sınavlara İtiraz", result["response"])
        self.assertIn("Sınav Kağıdına İtiraz", result["response"])

    def test_final_sinavi_itiraz_formu_takvim_degil_workflow_doner(self) -> None:
        result = self.service.answer_chat_query("final sınavına itiraz etmek istiyorum itiraz formu var mı")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "exam_appeal")
        self.assertIn("Sınav Kağıdına İtiraz", result["response"])
        self.assertTrue(self.service.should_preempt_calendar("final sınavına itiraz etmek istiyorum itiraz formu var mı"))

    def test_direct_form_only_kayit_dondurma_sadece_link_doner(self) -> None:
        result = self.service.answer_chat_query(
            "Kayıt dondurmak için doldurmam gereken MDBF formu nerede, sadece linkini verebilir misin"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "freeze_registration")
        self.assertIn("Kayıt Dondurma Başvuru Formu", result["response"])
        self.assertNotIn("Süreç adımları", result["response"])

    def test_direct_form_only_mazeret_formu_yoksa_adim_listesi_donmez(self) -> None:
        result = self.service.answer_chat_query("MDBF mazeret sınavı başvuru formunun linkini doğrudan atabilir misin?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "excuse_exam")
        self.assertIn("doğrudan bir form bağlantısı bulunmuyor", result["response"])
        self.assertNotIn("Süreç adımları", result["response"])

    def test_saf_ders_kaydi_tarih_sorusu_takvime_birakilir(self) -> None:
        self.assertFalse(self.service.should_preempt_calendar("Ders kayıtları ne zaman?"))
        self.assertIsNone(self.service.answer_chat_query("Ders kayıtları ne zaman?"))

    def test_kontenjan_metrik_sorusu_yokatlasa_birakilir(self) -> None:
        self.assertIsNone(self.service.answer_chat_query("Bilgisayar Mühendisliği kontenjanı kaç?"))
        self.assertIsNone(self.service.answer_chat_query("eem kontenjan"))

    def test_kontenjan_belirleme_sureci_workflow_doner(self) -> None:
        result = self.service.answer_chat_query(
            "Bölümlerin öğrenci kontenjanları belirlenirken süreç nasıl işliyor, üniversite içindeki adımlar neler?"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["process_key"], "quota_determination")
        self.assertIn("Öğrenci Kontenjanları Belirleme", result["response"])

    def test_baska_birim_sorusu_rag_akisina_birakilir(self) -> None:
        result = self.service.answer_chat_query("İlahiyat fakültesinde kayıt dondurma formu nerede?")

        self.assertIsNone(result)

    def test_rag_service_workflow_servisini_pipeline_oncesi_kullanir(self) -> None:
        expected = {"response": "workflow yanıtı", "sources": []}
        with patch("app.services.rag_service.get_food_menu_service") as food, \
            patch("app.services.rag_service.get_academic_calendar_service") as calendar, \
            patch("app.services.rag_service.get_workflow_service") as workflow:
            food.return_value.answer_chat_query.return_value = None
            calendar.return_value.answer_chat_query.return_value = None
            workflow.return_value.answer_chat_query.return_value = expected

            result = RagService().query("MDBF mazeret sınavı formu nerede?")

        self.assertEqual(result, expected)

    def test_rag_service_workflow_takvimden_once_preempt_eder(self) -> None:
        expected = {"response": "workflow yanıtı", "sources": [], "metadata": {"service": "workflow_service"}}

        class WorkflowRouteService:
            def should_preempt_calendar(self, question):
                return True

            def answer_chat_query(self, question):
                return expected

        class RaisingCalendarService:
            def answer_chat_query(self, question):
                raise AssertionError("Workflow preempt eden sorgu akademik takvime gitmemeli")

        with patch("app.services.rag_service.get_food_menu_service") as food, \
            patch("app.services.rag_service.get_academic_calendar_service", return_value=RaisingCalendarService()), \
            patch("app.services.rag_service.get_workflow_service", return_value=WorkflowRouteService()):
            food.return_value.answer_chat_query.return_value = None

            result = RagService().query("MDBF öğrencisiyim, ders kayıt sürecini adım adım anlatır mısın?")

        self.assertEqual(result, expected)

    def test_rag_service_saf_takvim_sorusu_akademik_takvimde_kalir(self) -> None:
        expected = {"response": "takvim yanıtı", "sources": [], "metadata": {"service": "academic_calendar"}}

        class WorkflowRouteService:
            def should_preempt_calendar(self, question):
                return False

            def answer_chat_query(self, question):
                raise AssertionError("Takvim yanıtı üretildikten sonra workflow denenmemeli")

        class CalendarService:
            def answer_chat_query(self, question):
                return expected

        with patch("app.services.rag_service.get_food_menu_service") as food, \
            patch("app.services.rag_service.get_academic_calendar_service", return_value=CalendarService()), \
            patch("app.services.rag_service.get_workflow_service", return_value=WorkflowRouteService()):
            food.return_value.answer_chat_query.return_value = None

            result = RagService().query("Final sınavları ne zaman?")

        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
