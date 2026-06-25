"""Program catalog DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import json
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
            self._unit("Tıp Fakültesi", "faculty", ["Tıp"]),
            self._unit("Yabancı Diller Yüksekokulu", "school", ["YDYO", "Yabancı Diller"]),
            self._unit("Sağlık Hizmetleri Meslek Yüksekokulu", "vocational_school", ["SHMYO", "Sağlık Hizmetleri MYO"]),
            self._unit("Teknik Bilimler Meslek Yüksekokulu", "vocational_school", ["TBMYO", "Teknik Bilimler MYO"]),
            self._unit("Lisansüstü Eğitim Enstitüsü", "institute", ["Lisansüstü"]),
        ]
        self.entries = [
            self._entry("Bilgisayar Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["BM", "bilgisayar müh", "bilgisayar muh"]),
            self._entry("Elektrik-Elektronik Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["EEM", "EEE", "elektrik elektronik"]),
            self._entry("Endüstri Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["EM", "endüstri"]),
            self._entry("İnşaat Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "undergraduate", ["inşaat", "insaat"]),
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


class NoAliasProgramCatalogRepository(FakeProgramCatalogRepository):
    def __init__(self) -> None:
        super().__init__()
        for unit in self.units:
            unit["aliases"] = []
        for entry in self.entries:
            entry["aliases"] = []


class CandidateMixedProgramCatalogRepository(FakeProgramCatalogRepository):
    def __init__(self) -> None:
        super().__init__()
        self.units.extend([
            self._candidate_unit("MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ", "faculty", ["MDBF", "Mühendislik"]),
            self._candidate_unit("SAĞLIK BİLİMLERİ FAKÜLTESİ", "faculty", ["SBF"]),
            self._candidate_unit("Sağlık Hizmetleri Meslek Yüksekokulu", "vocational_school", ["SHMYO", "Sağlık Hizmetleri MYO"]),
            self._candidate_unit("Teknik Bilimler Meslek Yüksekokulu", "vocational_school", ["TBMYO", "Teknik Bilimler MYO"]),
            self._candidate_unit("Yabancı Diller Yüksekokulu", "school", ["YDYO"]),
            self._candidate_unit("İSLAMİ İLİMLER FAKÜLTESİ", "faculty", []),
        ])
        self.entries.extend([
            self._candidate_entry("Bilgisayar Mühendisliği", "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ", "undergraduate", ["BM", "bilgisayar müh", "bilgisayar muh"]),
            self._candidate_entry("İnşaat Mühendisliği", "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ", "undergraduate", ["inşaat", "insaat"]),
            self._candidate_entry("Fizyoterapi", "SAĞLIK BİLİMLERİ FAKÜLTESİ", "undergraduate", ["fizyoterapi"]),
            self._candidate_entry("Fizyoterapi", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["fizyoterapi"]),
            self._candidate_entry("Ameliyathane Hizmetleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["ameliyathane"]),
            self._candidate_entry("Tıbbi Laboratuvar Teknikleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["tıbbi lab", "tibbi lab"]),
            self._candidate_entry("İlk ve Acil Yardım", "Sağlık Hizmetleri Meslek Yüksekokulu", "associate", ["ilk acil", "paramedik"]),
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


class CandidateOnlyProgramCatalogRepository(CandidateMixedProgramCatalogRepository):
    def __init__(self) -> None:
        super().__init__()
        self.units = [unit for unit in self.units if unit.get("source_type") == "candidate_page_ogrenim"]
        self.entries = [entry for entry in self.entries if entry.get("source_type") == "candidate_page_ogrenim"]


class ProgramCatalogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProgramCatalogService(FakeProgramCatalogRepository())

    def test_katalog_soru_seti_db_first_yanitlanir(self) -> None:
        cases = [
            ("GİBTÜ’de hangi fakülteler var?", "faculty_list_query", "Mühendislik ve Doğa Bilimleri Fakültesi"),
            ("GİBTÜ’de hangi meslek yüksekokulları var?", "vocational_school_list_query", "Teknik Bilimler Meslek Yüksekokulu"),
            ("GİBTÜ’de hangi yüksekokullar var?", "school_list_query", "Yabancı Diller Yüksekokulu"),
            ("GİBTÜ’de hangi bölümler var?", "department_list_query", "Bilgisayar Mühendisliği"),
            ("üniversitede hangi bölümler var", "department_list_query", "Bilgisayar Mühendisliği"),
            ("üniversite de hangi fakülteler var?", "faculty_list_query", "Mühendislik ve Doğa Bilimleri Fakültesi"),
            ("MDBF bölümleri neler?", "faculty_departments_query", "Elektrik-Elektronik Mühendisliği"),
            ("mühendislikte hangi bölümler var", "faculty_departments_query", "Endüstri Mühendisliği"),
            ("İlahiyat Fakültesinde hangi bölümler var?", "faculty_departments_query", "İlahiyat"),
            ("Sağlık Bilimleri Fakültesinde hangi bölümler var?", "faculty_departments_query", "Fizyoterapi ve Rehabilitasyon"),
            ("sağlık bilimlerinde hangi bölümler var", "faculty_departments_query", "Fizyoterapi ve Rehabilitasyon"),
            ("SHMYO programları neler?", "vocational_school_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("sağlık meslek yüksekokulunda hangi bölümler var", "vocational_school_programs_query", "İlk ve Acil Yardım"),
            ("sağlık meslek yüksekokulunda hangi programlar var", "vocational_school_programs_query", "Ameliyathane Hizmetleri"),
            ("TBMYO programları neler?", "vocational_school_programs_query", "Bilgisayar Programcılığı"),
            ("Bilgisayar Mühendisliği var mı?", "program_exists_query", "Evet"),
            ("Bilgisayar Mühendisliği mevcut mu?", "program_exists_query", "Evet"),
            ("bilgisayar müh var mı?", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("bilgisayar müh varmi", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("bilgiyasar mühendsligi varmı?", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("Fizyoterapi mevcutmu", "program_exists_query", "Fizyoterapi ve Rehabilitasyon"),
            ("FTR var mı?", "program_exists_query", "Fizyoterapi ve Rehabilitasyon"),
            ("Bilgisayar Mühendisliği hangi fakültede?", "program_faculty_query", "Mühendislik ve Doğa Bilimleri Fakültesi"),
            ("FTR hangi fakültede?", "program_faculty_query", "Sağlık Bilimleri Fakültesi"),
            ("Tıp hangi fakültede?", "academic_unit_list_query", "Tıp Fakültesi"),
            ("Tıp Fakültesinde hangi bölümler bulunuyor?", "faculty_departments_query", "bölümler bulunamadı"),
            ("Hemşirelik hangi birimde?", "program_faculty_query", "Sağlık Bilimleri Fakültesi"),
            ("Bilgisayar Programcılığı hangi MYO'da?", "program_faculty_query", "Teknik Bilimler Meslek Yüksekokulu"),
            ("Makine programı hangi okulda?", "program_faculty_query", "Teknik Bilimler Meslek Yüksekokulu"),
            ("İlk ve Acil Yardım hangi birime bağlı?", "program_faculty_query", "Sağlık Hizmetleri Meslek Yüksekokulu"),
            ("Ebelik var mı?", "program_exists_query", "Ebelik"),
            ("Ebelik GİBTÜ’de var mı?", "program_exists_query", "Ebelik"),
            ("Yapay Zeka ve Veri Mühendisliği var mı?", "program_exists_query", "bulunmuyor"),
            ("Yazılım Mühendisliği var mı?", "program_exists_query", "bulunmuyor"),
            ("GİBTÜ’de hukuk var mı?", "program_exists_query", "bulunmuyor"),
            ("Hukuk bölümü açıldı mı?", "program_exists_query", "bulunmuyor"),
            ("Üniversitede hukuk bölümü var mı", "program_exists_query", "bulunmuyor"),
            ("GİBTÜ’de diş hekimliği var mı?", "program_exists_query", "bulunmuyor"),
            ("gibtu da diş hekimliği var mı", "program_exists_query", "bulunmuyor"),
            ("Makine Mühendisliği var mı?", "program_exists_query", "bulunmuyor"),
            ("Yabancı Diller Yüksekokulu bölüm mü?", "academic_unit_list_query", "bölüm/program değil"),
            ("Ön lisans programları neler?", "associate_degree_programs_query", "Makine"),
            ("Ön lisans programları hangileri?", "associate_degree_programs_query", "Makine"),
            ("Ön lisans bölümleri neler", "associate_degree_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("Lisans programları neler?", "undergraduate_programs_query", "Hemşirelik"),
            ("Lisans bölümlerini listele.", "undergraduate_programs_query", "Hemşirelik"),
            ("Ön lisans bölümlerini listele.", "associate_degree_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("4 yıllık programlar hangileri?", "undergraduate_programs_query", "Bilgisayar Mühendisliği"),
            ("2 yıllık programlar hangileri?", "associate_degree_programs_query", "Bilgisayar Programcılığı"),
        ]

        for question, expected_intent, expected_text in cases:
            with self.subTest(question=question):
                result = self.service.answer_chat_query(question)
                self.assertIsNotNone(result)
                self.assertTrue(result["metadata"]["db_first"])
                self.assertFalse(result["metadata"]["rag_fallback_used"])
                self.assertEqual(result["metadata"]["intent"], expected_intent)
                self.assertIn(expected_text, result["response"])
                self.assertNotIn("Bu akademisyen için", result["response"])
                self.assertNotIn("elimdeki belgelerden", result["response"])
                self.assertNotIn("Türkçe ve güvenilir bir cevap oluşturamadım", result["response"])
                self.assertNotIn("Yanıt süresi çok uzun sürdü", result["response"])

    def test_jenerik_alias_ve_kisaltmalar_db_alias_olmadan_calısır(self) -> None:
        service = ProgramCatalogService(NoAliasProgramCatalogRepository())
        cases = [
            ("MDBF bölümleri neler?", "faculty_departments_query", "Bilgisayar Mühendisliği"),
            ("SHMYO’da hangi programlar var", "vocational_school_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("mühendislikte hangi bölümler var", "faculty_departments_query", "Endüstri Mühendisliği"),
            ("sağlık bilimlerinde hangi bölümler var", "faculty_departments_query", "Fizyoterapi ve Rehabilitasyon"),
            ("sağlık meslek yüksekokulunda hangi programlar var", "vocational_school_programs_query", "İlk ve Acil Yardım"),
            ("bilgisayar muh varmi", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("fizyoterapi mevcut mu", "program_exists_query", "Fizyoterapi ve Rehabilitasyon"),
        ]

        for question, expected_intent, expected_text in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)
                self.assertIsNotNone(result)
                self.assertTrue(result["metadata"]["db_first"])
                self.assertFalse(result["metadata"]["rag_fallback_used"])
                self.assertEqual(result["metadata"]["intent"], expected_intent)
                self.assertIn(expected_text, result["response"])
                self.assertNotIn("Bu akademisyen için", result["response"])
                self.assertNotIn("elimdeki belgelerden", result["response"])

    def test_saglik_genel_sorgusu_netlestirme_ister(self) -> None:
        result = self.service.answer_chat_query("Sağlık bölümleri neler?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "ambiguous_program_query")
        self.assertIn("Sağlık Bilimleri Fakültesi", result["response"])
        self.assertIn("Sağlık Hizmetleri Meslek Yüksekokulu", result["response"])

    def test_yokatlas_metrik_sorusuna_karismaz(self) -> None:
        self.assertIsNone(self.service.answer_chat_query("Bilgisayar Mühendisliği kontenjanı kaç?"))

    def test_program_olmayan_var_mi_sorusu_katalog_negatifine_donusmez(self) -> None:
        self.assertIsNone(self.service.answer_chat_query("Erasmus imkanı var mı?"))


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

    def test_candidate_only_db_first_kayitlari_genel_katalog_fallback_olarak_kullanilir(self) -> None:
        service = ProgramCatalogService(CandidateOnlyProgramCatalogRepository())
        cases = [
            ("Bilgisayar Mühendisliği var mı?", "program_exists_query", "Bilgisayar Mühendisliği"),
            ("GİBTÜ'de hangi bölümler var?", "department_list_query", "Bilgisayar Mühendisliği"),
            ("GİBTÜ'de hangi fakülteler var?", "faculty_list_query", "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ"),
            ("SHMYO'da hangi programlar var?", "vocational_school_programs_query", "İlk ve Acil Yardım"),
            ("Ön lisans programları neler?", "associate_degree_programs_query", "Tıbbi Laboratuvar Teknikleri"),
            ("İslami İlimler Fakültesindeki bölümler neler?", "faculty_departments_query", "İslami İlimler (Türkçe)"),
        ]

        for question, expected_intent, expected_text in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                self.assertEqual(result["metadata"]["intent"], expected_intent)
                self.assertTrue(result["metadata"]["db_first"])
                self.assertFalse(result["metadata"]["rag_fallback_used"])
                self.assertIn(expected_text, result["response"])
                self.assertNotIn("Aday öğrenci Öğrenim", result["response"])
                self.assertNotIn("Kaynak: aday öğrenci öğrenim verisi", result["response"])
                self.assertNotIn("Bu akademisyen için", result["response"])
                self.assertNotIn("elimdeki belgelerden", result["response"])
                self.assertNotIn("birden fazla bölüm/programla eşleşiyor", result["response"])

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


class ConditionalRouteService:
    def __init__(self, service_name, predicate):
        self.service_name = service_name
        self.predicate = predicate

    def answer_chat_query(self, question):
        if not self.predicate(question):
            return None
        return {
            "response": f"{self.service_name} yanıtı",
            "sources": [],
            "metadata": {
                "db_first": True,
                "service": self.service_name,
                "intent": "smoke_route",
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


class SmokeRagPipeline:
    def run(self, data, include_outputs_from=None):
        question = data["candidate_source_prioritizer"]["question"]
        if "Kütüphane" in question:
            return {
                "llm": {
                    "replies": [
                        (
                            "Kütüphane hafta sonu çalışma saatleri için kaynakta yer alan güncel duyurular takip edilmelidir.\n\n"
                            "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için Sağlık Bilimleri Fakültesi birimine başvurmanızı öneriyorum. "
                            "E-posta: sbf@gibtu.edu.tr"
                        )
                    ]
                },
                "candidate_source_prioritizer": {
                    "documents": [
                        Document(
                            content="Kütüphane ve Dokümantasyon Daire Başkanlığı çalışma saatleri duyurularını yayımlar.",
                            meta={
                                "category": "kutuphane",
                                "title": "Kütüphane",
                                "doc_kind": "library_info",
                                "source_url": "https://www.gibtu.edu.tr/kutuphane",
                                "source_public_url": "https://www.gibtu.edu.tr/kutuphane",
                                "contact_unit": "Kütüphane ve Dokümantasyon Daire Başkanlığı",
                            },
                        ),
                        Document(
                            content="Sağlık Bilimleri Fakültesi iletişim: sbf@gibtu.edu.tr",
                            meta={
                                "category": "bolumler",
                                "title": "Sağlık Bilimleri Fakültesi",
                                "doc_kind": "faculty_info",
                                "source_url": "https://www.gibtu.edu.tr/sbf",
                                "source_public_url": "https://www.gibtu.edu.tr/sbf",
                                "contact_unit": "Sağlık Bilimleri Fakültesi",
                                "contact_info": "sbf@gibtu.edu.tr",
                            },
                        ),
                    ]
                },
            }
        return {
            "llm": {
                "replies": [
                    (
                        "Ders kaydı işlemleri akademik takvimde belirtilen tarihlerde öğrenci bilgi sistemi üzerinden yapılır.\n\n"
                        "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için Öğrenci İşleri birimine başvurmanızı öneriyorum."
                    )
                ]
            },
            "candidate_source_prioritizer": {
                "documents": [
                    Document(
                        content="Ders kaydı işlemleri akademik takvimde belirtilen tarihlerde öğrenci bilgi sistemi üzerinden yapılır.",
                        meta={
                            "category": "egitim",
                            "title": "Ders Kaydı",
                            "doc_kind": "registration_info",
                            "source_url": "https://www.gibtu.edu.tr/akademiktakvim",
                            "source_public_url": "https://www.gibtu.edu.tr/akademiktakvim",
                            "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
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

    def test_basit_program_varlik_sorusu_once_program_cataloga_gider(self) -> None:
        catalog_service = ProgramCatalogService(FakeProgramCatalogRepository())
        rag = RagService()
        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_program_catalog_service", return_value=catalog_service),
            patch("app.services.rag_service.get_subunit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=RaisingService("unit_management_service")),
            patch("app.services.rag_service.get_academic_staff_service", return_value=RaisingService("academic_staff_service")),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=RaisingService("yokatlas_query_service")),
        ):
            result = rag.query("Fizyoterapi var mı?")

        self.assertEqual(result["metadata"]["service"], "program_catalog_service")
        self.assertEqual(result["metadata"]["intent"], "program_exists_query")
        self.assertIn("Fizyoterapi ve Rehabilitasyon", result["response"])

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

    def test_mevcut_mu_ve_acildi_mi_sorulari_akademik_kadroya_sizmaz(self) -> None:
        catalog_service = ProgramCatalogService(FakeProgramCatalogRepository())
        rag = RagService()
        for question in ("Fizyoterapi mevcut mu?", "Hukuk bölümü açıldı mı?", "bilgisayar muh varmi"):
            with self.subTest(question=question):
                with (
                    patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
                    patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
                    patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
                    patch("app.services.rag_service.get_program_catalog_service", return_value=catalog_service),
                    patch("app.services.rag_service.get_subunit_management_service", return_value=RaisingService("subunit_management_service")),
                    patch("app.services.rag_service.get_unit_management_service", return_value=RaisingService("unit_management_service")),
                    patch("app.services.rag_service.get_academic_staff_service", return_value=RaisingService("academic_staff_service")),
                    patch("app.services.rag_service.get_yokatlas_query_service", return_value=RaisingService("yokatlas_query_service")),
                ):
                    result = rag.query(question)

                self.assertEqual(result["metadata"]["service"], "program_catalog_service")
                self.assertEqual(result["metadata"]["intent"], "program_exists_query")

    def test_fakulte_bolum_ve_birim_sorulari_akademik_kadroya_sizmaz(self) -> None:
        catalog_service = ProgramCatalogService(FakeProgramCatalogRepository())
        rag = RagService()
        cases = [
            ("Mühendislik ve Doğa Bilimleri Fakültesinde hangi bölümler var?", "faculty_departments_query"),
            ("Sağlık Bilimleri Fakültesinde hangi bölümler bulunuyor?", "faculty_departments_query"),
            ("Hemşirelik hangi birimde?", "program_faculty_query"),
            ("Bilgisayar Mühendisliği hangi fakültede?", "program_faculty_query"),
        ]

        for question, expected_intent in cases:
            with self.subTest(question=question):
                with (
                    patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
                    patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
                    patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
                    patch("app.services.rag_service.get_program_catalog_service", return_value=catalog_service),
                    patch("app.services.rag_service.get_subunit_management_service", return_value=RaisingService("subunit_management_service")),
                    patch("app.services.rag_service.get_unit_management_service", return_value=RaisingService("unit_management_service")),
                    patch("app.services.rag_service.get_academic_staff_service", return_value=RaisingService("academic_staff_service")),
                    patch("app.services.rag_service.get_yokatlas_query_service", return_value=RaisingService("yokatlas_query_service")),
                ):
                    result = rag.query(question)

                self.assertEqual(result["metadata"]["service"], "program_catalog_service")
                self.assertEqual(result["metadata"]["intent"], expected_intent)
                self.assertNotIn("Bu akademisyen için", result["response"])

    def test_mock_routing_smoke_report(self) -> None:
        rag = RagService()
        rag._pipeline = SmokeRagPipeline()
        questions = [
            ("Bilgisayar Mühendisliği kontenjanı kaç?", "yokatlas_query_service"),
            ("Tıp Fakültesi Dekanı kim?", "unit_management_service"),
            ("Ahmet Yılmaz hangi bölümde?", "academic_staff_service"),
            ("Kütüphane hafta sonu açık mı?", "rag_service"),
            ("Ders kaydı nasıl yapılır?", "workflow_service"),
        ]
        report = []

        with (
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=NullService()),
            patch("app.services.rag_service.get_administrative_staff_service", return_value=NullService()),
            patch("app.services.rag_service.get_program_catalog_service", return_value=RaisingService("program_catalog_service")),
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=ConditionalRouteService(
                "yokatlas_query_service",
                lambda question: "kontenjan" in question.lower(),
            )),
            patch("app.services.rag_service.get_subunit_management_service", return_value=NullService()),
            patch("app.services.rag_service.get_unit_management_service", return_value=ConditionalRouteService(
                "unit_management_service",
                lambda question: "Dekan" in question or "dekan" in question,
            )),
            patch("app.services.rag_service.get_academic_staff_service", return_value=ConditionalRouteService(
                "academic_staff_service",
                lambda question: "Ahmet Yılmaz" in question,
            )),
        ):
            for question, expected_service in questions:
                error = None
                routed_service = None
                response = ""
                try:
                    result = rag.query(question)
                    response = result.get("response") or ""
                    routed_service = result.get("metadata", {}).get("service") or "rag_service"
                except Exception as exc:  # pragma: no cover - raporda görünmesi için yakalanır
                    error = str(exc)

                lower_response = response.lower()
                smoke_row = {
                    "question": question,
                    "routed_service": routed_service,
                    "expected_service": expected_service,
                    "error": error,
                    "has_frankenstein_fallback": (
                        "yeterli bilgi bulunmuyor" in lower_response
                        and any(marker in lower_response for marker in ("kütüphane", "ders kaydı", "kontenjan"))
                    ),
                    "has_irrelevant_contact": any(
                        marker in lower_response
                        for marker in ("sbf@gibtu.edu.tr", "disiliskiler", "dış ilişkiler")
                    ),
                }
                report.append(smoke_row)

                self.assertIsNone(error, smoke_row)
                self.assertEqual(routed_service, expected_service, smoke_row)
                self.assertFalse(smoke_row["has_frankenstein_fallback"], smoke_row)
                self.assertFalse(smoke_row["has_irrelevant_contact"], smoke_row)

        print("SMOKE_ROUTING_REPORT=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
