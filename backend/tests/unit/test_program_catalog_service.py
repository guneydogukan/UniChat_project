"""Program catalog DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from haystack import Document  # noqa: E402

from app.services.program_catalog_service import ProgramCatalogService  # noqa: E402
from app.services.rag_service import RagService  # noqa: E402


class FakeProgramCatalogRepository:
    def __init__(self) -> None:
        self.units = [
            self._unit("Mühendislik ve Doğa Bilimleri Fakültesi", "faculty", ["MDBF", "Mühendislik"]),
            self._unit("İlahiyat Fakültesi", "faculty", ["İlahiyat"]),
            self._unit("Sağlık Bilimleri Fakültesi", "faculty", ["SBF", "Sağlık Bilimleri"]),
            self._unit("İktisadi, İdari ve Sosyal Bilimler Fakültesi", "faculty", ["İİSBF", "IISBF"]),
            self._unit("Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "faculty", ["GSMF", "Güzel Sanatlar"]),
            self._unit("Yabancı Diller Yüksekokulu", "school", ["YDYO", "Yabancı Diller"]),
            self._unit("Sağlık Hizmetleri Meslek Yüksekokulu", "vocational_school", ["SHMYO", "Sağlık Hizmetleri MYO"]),
            self._unit("Teknik Bilimler Meslek Yüksekokulu", "vocational_school", ["TBMYO", "Teknik Bilimler MYO"]),
            self._unit("Lisansüstü Eğitim Enstitüsü", "institute", ["Lisansüstü"]),
        ]
        self.entries = [
            self._entry("Bilgisayar Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["BM", "bilgisayar müh", "bilgisayar muh"]),
            self._entry("Elektrik-Elektronik Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["EEM", "EEE", "elektrik elektronik"]),
            self._entry("Endüstri Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["EM", "endüstri"]),
            self._entry("İlahiyat", "İlahiyat Fakültesi", "undergraduate", ["ilahiyat"]),
            self._entry("Ebelik", "Sağlık Bilimleri Fakültesi", "undergraduate", ["ebelik"]),
            self._entry("Hemşirelik", "Sağlık Bilimleri Fakültesi", "undergraduate", ["hemşirelik", "hemsirelik"]),
            self._entry("Fizyoterapi ve Rehabilitasyon", "Sağlık Bilimleri Fakültesi", "undergraduate", ["FTR", "fizyoterapi"]),
            self._entry("Ameliyathane Hizmetleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["ameliyathane"]),
            self._entry("Tıbbi Laboratuvar Teknikleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["tıbbi lab", "tibbi lab"]),
            self._entry("İlk ve Acil Yardım", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["paramedik", "ilk acil"]),
            self._entry("Bilgisayar Programcılığı", "Teknik Bilimler Meslek Yüksekokulu", "associate", ["BP", "bilgisayar program"]),
            self._entry("Makine", "Teknik Bilimler Meslek Yüksekokulu", "associate", ["makine"]),
        ]

    def _unit(self, name, unit_type, aliases):
        normalized = self._normalize(name)
        return {
            "id": normalized,
            "unit_name": name,
            "normalized_unit_name": normalized,
            "unit_type": unit_type,
            "source_url": f"https://www.gibtu.edu.tr/{normalized.replace(' ', '-')}",
            "official_gibtu_url": f"https://www.gibtu.edu.tr/{normalized.replace(' ', '-')}",
            "match_status": "matched",
            "needs_review": False,
            "missing_in_current_run": False,
            "aliases": aliases,
        }

    def _entry(self, name, unit_name, level, aliases):
        normalized = self._normalize(name)
        unit_normalized = self._normalize(unit_name)
        return {
            "id": f"{unit_normalized}:{normalized}",
            "item_kind": "program" if level == "associate" else "department",
            "program_name": name,
            "normalized_program_name": normalized,
            "education_level": level,
            "source_url": f"https://www.gibtu.edu.tr/{normalized.replace(' ', '-')}",
            "official_gibtu_url": f"https://www.gibtu.edu.tr/{normalized.replace(' ', '-')}",
            "yokatlas_url": f"https://yokatlas.yok.gov.tr/detay/{abs(hash(name)) % 100000}",
            "program_code": None,
            "match_status": "matched",
            "needs_review": False,
            "missing_in_current_run": False,
            "unit_id": unit_normalized,
            "unit_name": unit_name,
            "normalized_unit_name": unit_normalized,
            "unit_type": "vocational_school" if level == "associate" else "faculty",
            "aliases": aliases,
        }

    @staticmethod
    def _normalize(value):
        from scrapers.program_catalog_scraper import normalize_for_match

        return normalize_for_match(value)

    def list_units(self):
        return list(self.units)

    def list_catalog_entries(self):
        return list(self.entries)


class CandidateMixedProgramCatalogRepository(FakeProgramCatalogRepository):
    def __init__(self) -> None:
        super().__init__()
        self.units.extend([
            self._candidate_unit("SAĞLIK BİLİMLERİ FAKÜLTESİ", "faculty", ["SBF"]),
            self._candidate_unit("Sağlık Hizmetleri Meslek Yüksekokulu", "vocational_school", ["SHMYO", "Sağlık Hizmetleri MYO"]),
            self._candidate_unit("Teknik Bilimler Meslek Yüksekokulu", "vocational_school", ["TBMYO", "Teknik Bilimler MYO"]),
            self._candidate_unit("Yabancı Diller Yüksekokulu", "school", ["YDYO"]),
            self._candidate_unit("İSLAMİ İLİMLER FAKÜLTESİ", "faculty", []),
        ])
        self.entries.extend([
            self._candidate_entry("Bilgisayar Mühendisliği", "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ", "undergraduate", ["BM", "bilgisayar müh", "bilgisayar muh"]),
            self._candidate_entry("Fizyoterapi", "SAĞLIK BİLİMLERİ FAKÜLTESİ", "undergraduate", ["fizyoterapi"]),
            self._candidate_entry("Fizyoterapi", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["fizyoterapi"]),
            self._candidate_entry("Mütercim Tercümanlık (İngilizce)", "Yabancı Diller Yüksekokulu", "undergraduate", ["ingilizce mütercim tercümanlık"]),
            self._candidate_entry("İslami İlimler (Türkçe)", "İSLAMİ İLİMLER FAKÜLTESİ", "undergraduate", ["islami ilimler türkçe"]),
        ])

    def _candidate_unit(self, name, unit_type, aliases):
        normalized = self._normalize(name)
        return {
            "id": f"candidate:{normalized}",
            "unit_name": name,
            "normalized_unit_name": normalized,
            "unit_type": unit_type,
            "source_url": "https://adayogrenci.gibtu.edu.tr/#ogrenim",
            "official_gibtu_url": None,
            "match_status": "candidate_support",
            "needs_review": False,
            "missing_in_current_run": False,
            "source_type": "candidate_page_ogrenim",
            "source_confidence": "candidate_support",
            "answer_scope": "candidate_page_only",
            "is_authoritative": False,
            "is_active_verified": False,
            "db_first_answerable": True,
            "aliases": aliases,
        }

    def _candidate_entry(self, name, unit_name, level, aliases):
        normalized = self._normalize(name)
        unit_normalized = self._normalize(unit_name)
        return {
            "id": f"candidate:{unit_normalized}:{normalized}:{level}",
            "item_kind": "candidate_listed_associate_program" if level == "associate" else "candidate_listed_undergraduate_program",
            "program_name": name,
            "normalized_program_name": normalized,
            "education_level": level,
            "source_url": "https://adayogrenci.gibtu.edu.tr/#ogrenim",
            "official_gibtu_url": None,
            "yokatlas_url": None,
            "program_code": None,
            "match_status": "candidate_support",
            "needs_review": False,
            "missing_in_current_run": False,
            "unit_id": f"candidate:{unit_normalized}",
            "unit_name": unit_name,
            "normalized_unit_name": unit_normalized,
            "unit_type": "vocational_school" if level == "associate" else "faculty",
            "source_type": "candidate_page_ogrenim",
            "source_confidence": "candidate_support",
            "answer_scope": "candidate_page_only",
            "is_authoritative": False,
            "is_active_verified": False,
            "db_first_answerable": True,
            "aliases": aliases,
        }


class ProgramCatalogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProgramCatalogService(FakeProgramCatalogRepository())

    def test_katalog_soru_seti_db_first_yanitlanir(self) -> None:
        cases = [
            ("GİBTÜ’de hangi fakülteler var?", "faculty_list_query", "Mühendislik ve Doğa Bilimleri Fakültesi"),
            ("GİBTÜ’de hangi meslek yüksekokulları var?", "vocational_school_list_query", "Teknik Bilimler Meslek Yüksekokulu"),
            ("GİBTÜ’de hangi yüksekokullar var?", "school_list_query", "Yabancı Diller Yüksekokulu"),
            ("GİBTÜ’de hangi bölümler var?", "department_list_query", "Bilgisayar Mühendisliği"),
            ("MDBF bölümleri neler?", "faculty_departments_query", "Elektrik-Elektronik Mühendisliği"),
            ("İlahiyat Fakültesinde hangi bölümler var?", "faculty_departments_query", "İlahiyat"),
            ("Sağlık Bilimleri Fakültesinde hangi bölümler var?", "faculty_departments_query", "Fizyoterapi ve Rehabilitasyon"),
            ("SHMYO programları neler?", "vocational_school_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("TBMYO programları neler?", "vocational_school_programs_query", "Bilgisayar Programcılığı"),
            ("Bilgisayar Mühendisliği var mı?", "program_exists_query", "Evet"),
            ("bilgisayar müh var mı?", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("FTR hangi fakültede?", "program_faculty_query", "Sağlık Bilimleri Fakültesi"),
            ("Ebelik var mı?", "program_exists_query", "Ebelik"),
            ("GİBTÜ’de hukuk var mı?", "program_exists_query", "bulunmuyor"),
            ("GİBTÜ’de diş hekimliği var mı?", "program_exists_query", "bulunmuyor"),
            ("Yabancı Diller Yüksekokulu bölüm mü?", "academic_unit_list_query", "bölüm/program değil"),
            ("Ön lisans programları neler?", "associate_degree_programs_query", "Makine"),
            ("Lisans programları neler?", "undergraduate_programs_query", "Hemşirelik"),
        ]

        for question, expected_intent, expected_text in cases:
            with self.subTest(question=question):
                result = self.service.answer_chat_query(question)
                self.assertIsNotNone(result)
                self.assertTrue(result["metadata"]["db_first"])
                self.assertFalse(result["metadata"]["rag_fallback_used"])
                self.assertEqual(result["metadata"]["intent"], expected_intent)
                self.assertIn(expected_text, result["response"])

    def test_saglik_genel_sorgusu_netlestirme_ister(self) -> None:
        result = self.service.answer_chat_query("Sağlık bölümleri neler?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "ambiguous_program_query")
        self.assertIn("Sağlık Bilimleri Fakültesi", result["response"])
        self.assertIn("Sağlık Hizmetleri Meslek Yüksekokulu", result["response"])

    def test_yokatlas_metrik_sorusuna_karismaz(self) -> None:
        self.assertIsNone(self.service.answer_chat_query("Bilgisayar Mühendisliği kontenjanı kaç?"))


class CandidateOgrenimRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProgramCatalogService(CandidateMixedProgramCatalogRepository())

    def test_hard_blocker_sorularinda_candidate_calismaz(self) -> None:
        blocked_questions = [
            "bilgisayar muh bölüm başkanı",
            "eem bölüm başkanı",
            "bilgisayar mühendisliği akademik kadrosu",
            "elektrik mühendisliği akademik kadrosu",
            "Bilgisayar Mühendisliği kontenjanı kaç?",
            "Tıp kadrosu",
        ]

        for question in blocked_questions:
            with self.subTest(question=question):
                self.assertIsNone(self.service.answer_chat_query(question))

    def test_genel_program_sorgusu_candidate_kaynakla_cevaplanmaz(self) -> None:
        result = self.service.answer_chat_query("Bilgisayar Mühendisliği var mı?")

        self.assertIsNotNone(result)
        self.assertNotIn("Aday öğrenci Öğrenim", result["response"])
        self.assertEqual(result["metadata"]["matched_program_name"], "Bilgisayar Mühendisliği")

    def test_explicit_aday_ogrenim_sorgusu_candidate_kaynakla_cevaplanir(self) -> None:
        result = self.service.answer_chat_query("Aday öğrenci öğrenim sayfasında Bilgisayar Mühendisliği var mı?")

        self.assertIsNotNone(result)
        self.assertIn("Aday öğrenci Öğrenim bölümünde", result["response"])
        self.assertIn("Kaynak: aday öğrenci öğrenim verisi", result["response"])
        self.assertEqual(result["sources"][0]["doc_kind"], "candidate_ogrenim_entry")

    def test_aday_portalindaki_lisans_programlari_candidate_ogrenimdir(self) -> None:
        result = self.service.answer_chat_query("Aday portalındaki lisans programları neler?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "undergraduate_programs_query")
        self.assertIn("Aday öğrenci Öğrenim bölümünde", result["response"])

    def test_eski_aday_sorularini_candidate_ogrenim_yanıtlamaz(self) -> None:
        for question in [
            "Aday öğrenci sık sorulan sorular neler?",
            "Aday öğrenci olanakları neler?",
            "Aday öğrenci burs imkanları neler?",
            "Aday öğrenci yurt bilgisi var mı?",
            "Aday öğrenci kayıt hakkında bilgi ver",
        ]:
            with self.subTest(question=question):
                self.assertIsNone(self.service.answer_chat_query(question))

    def test_fizyoterapi_genel_ve_aday_baglaminda_ayri_davranir(self) -> None:
        general = self.service.answer_chat_query("Fizyoterapi var mı?")
        candidate = self.service.answer_chat_query("Aday öğrenci öğrenim sayfasında Fizyoterapi var mı?")

        self.assertIsNotNone(general)
        self.assertIn("Fizyoterapi ve Rehabilitasyon", general["response"])
        self.assertNotIn("Aday öğrenci Öğrenim", general["response"])
        self.assertIsNotNone(candidate)
        self.assertIn("birden fazla bağlamda", candidate["response"])
        self.assertIn("Sağlık Hizmetleri Meslek Yüksekokulu", candidate["response"])

    def test_negatif_cevaplar_candidate_kapsamina_gore_ayrilir(self) -> None:
        general = self.service.answer_chat_query("Hukuk var mı?")
        general_yapay_zeka = self.service.answer_chat_query("Üniversitede yapay zeka bölümü var mı?")
        candidate = self.service.answer_chat_query("Aday öğrenci öğrenim sayfasında Hukuk var mı?")
        candidate_yapay_zeka = self.service.answer_chat_query("Yapay zeka aday öğrenci öğrenim sayfasında var mı?")

        self.assertIsNotNone(general)
        self.assertIn("Mevcut GİBTÜ bölüm/program envanterinde", general["response"])
        self.assertNotIn("Aday öğrenci Öğrenim", general["response"])
        self.assertIsNotNone(general_yapay_zeka)
        self.assertIn("Yapay Zeka kaydı bulunmuyor", general_yapay_zeka["response"])
        self.assertNotIn("Üniversitede Yapay", general_yapay_zeka["response"])
        self.assertIsNotNone(candidate)
        self.assertIn("kesin yoktur anlamına gelmez", candidate["response"])
        self.assertIsNotNone(candidate_yapay_zeka)
        self.assertIn("Yapay Zeka kaydı bulunamadı", candidate_yapay_zeka["response"])
        self.assertNotIn("Yapay Zeka Aday", candidate_yapay_zeka["response"])


class NullService:
    def answer_chat_query(self, question):
        return None


class FakeYokatlasMetricService:
    def answer_chat_query(self, question):
        return {
            "response": "Bilgisayar Mühendisliği kontenjanı YÖK Atlas servisinden yanıtlandı.",
            "sources": [],
            "metadata": {
                "db_first": True,
                "service": "yokatlas_query_service",
                "intent": "quota",
                "rag_fallback_used": False,
            },
        }


class FakeRouteService:
    def __init__(self, service_name):
        self.service_name = service_name

    def answer_chat_query(self, question):
        return {
            "response": f"{self.service_name} yanıtı",
            "sources": [],
            "metadata": {
                "db_first": True,
                "service": self.service_name,
                "intent": "test_route",
                "rag_fallback_used": False,
            },
        }


class RaisingService:
    def __init__(self, service_name):
        self.service_name = service_name

    def answer_chat_query(self, question):
        raise AssertionError(f"{self.service_name} çağrılmamalıydı")


class FakeCandidateFaqPipeline:
    def run(self, data, include_outputs_from=None):
        return {
            "llm": {"replies": ["Aday öğrenci SSS yanıtı."]},
            "candidate_source_prioritizer": {
                "documents": [
                    Document(
                        content="Aday öğrenci sık sorulan sorular içeriği.",
                        meta={
                            "category": "aday_ogrenci",
                            "title": "Aday Öğrenci SSS",
                            "doc_kind": "candidate_faq",
                            "source_url": "https://adayogrenci.gibtu.edu.tr/#sss",
                            "source_public_url": "https://adayogrenci.gibtu.edu.tr/#sss",
                        },
                    )
                ]
            },
        }


class RagServiceProgramCatalogRoutingTests(unittest.TestCase):
    def test_yokatlas_metrik_sorusu_mevcut_servise_gider(self) -> None:
        catalog_service = ProgramCatalogService(FakeProgramCatalogRepository())
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_program_catalog_service", return_value=catalog_service),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=FakeYokatlasMetricService()),
        ):
            result = rag.query("Bilgisayar Mühendisliği kontenjanı kaç?")

        self.assertEqual(result["metadata"]["service"], "yokatlas_query_service")
        self.assertEqual(result["metadata"]["intent"], "quota")
        self.assertIn("YÖK Atlas servisinden", result["response"])

    def test_bolum_baskani_sorusu_program_cataloga_gitmez(self) -> None:
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=FakeRouteService("subunit_management_service")),
            patch("app.services.rag_service.get_unit_management_service", return_value=RaisingService("unit_management_service")),
            patch("app.services.rag_service.get_academic_staff_service", return_value=RaisingService("academic_staff_service")),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=RaisingService("yokatlas_query_service")),
            patch("app.services.rag_service.get_program_catalog_service", return_value=RaisingService("program_catalog_service")),
        ):
            result = rag.query("bilgisayar muh bölüm başkanı")

        self.assertEqual(result["metadata"]["service"], "subunit_management_service")

    def test_akademik_kadro_sorusu_program_cataloga_gitmez(self) -> None:
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_staff_service", return_value=FakeRouteService("academic_staff_service")),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=RaisingService("yokatlas_query_service")),
            patch("app.services.rag_service.get_program_catalog_service", return_value=RaisingService("program_catalog_service")),
        ):
            result = rag.query("bilgisayar mühendisliği akademik kadrosu")

        self.assertEqual(result["metadata"]["service"], "academic_staff_service")

    def test_explicit_aday_ogrenim_sorusu_program_cataloga_gider(self) -> None:
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=NullService()),
            patch("app.services.rag_service.get_program_catalog_service", return_value=FakeRouteService("program_catalog_service")),
        ):
            result = rag.query("Aday öğrenci öğrenim sayfasında Bilgisayar Mühendisliği var mı?")

        self.assertEqual(result["metadata"]["service"], "program_catalog_service")

    def test_eski_aday_faq_sorusu_rag_candidate_faq_kaynagina_duser(self) -> None:
        rag = RagService()
        rag._pipeline = FakeCandidateFaqPipeline()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_subunit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=NullService()),
            patch("app.services.rag_service.get_program_catalog_service", return_value=NullService()),
        ):
            result = rag.query("Aday öğrenci sık sorulan sorular neler?")

        self.assertEqual(result["sources"][0]["doc_kind"], "candidate_faq")


if __name__ == "__main__":
    unittest.main()
