"""YÖK Atlas DB-first chatbot servis testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.rag_service import RagService  # noqa: E402
from app.services.yokatlas_query_service import YokatlasQueryService  # noqa: E402


def _program(
    code: str,
    name: str,
    unit: str,
    level: str,
    score_type: str,
    language: str,
    quota: int,
    placed: int,
    base_score: float,
    base_rank: int,
    conditions: int = 0,
    school_first_quota: int | None = None,
    school_first_placed: int | None = None,
    earthquake_quota: int | None = None,
    women_34_plus_quota: int | None = None,
    martyr_veteran_quota: int | None = None,
) -> dict:
    return {
        "program_id": f"p-{code}",
        "program_year_id": f"py-{code}",
        "program_code": code,
        "program_name_raw": name,
        "program_name_clean": name.split(" (", 1)[0],
        "program_variant": None,
        "program_level": level,
        "duration_years": 4,
        "academic_unit_name": unit,
        "university_name": "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ",
        "city": "GAZİANTEP",
        "program_source_url": f"https://yokatlas.yok.gov.tr/lisans.php?y={code}",
        "program_year_source_url": f"https://yokatlas.yok.gov.tr/lisans.php?y={code}",
        "data_year": 2025,
        "score_type": score_type,
        "education_mode": "Örgün Öğretim",
        "language": language,
        "funding_type": "Ücretsiz",
        "general_quota": quota,
        "general_placed": placed,
        "school_first_quota": school_first_quota,
        "school_first_placed": school_first_placed,
        "earthquake_quota": earthquake_quota,
        "earthquake_placed": None,
        "women_34_plus_quota": women_34_plus_quota,
        "women_34_plus_placed": None,
        "martyr_veteran_quota": martyr_veteran_quota,
        "martyr_veteran_placed": None,
        "total_quota_known": quota,
        "total_placed_known": placed,
        "base_score": base_score,
        "base_rank": base_rank,
        "min_rank_condition": None,
        "fill_status": "filled",
        "condition_count": conditions,
    }


class FakeYokatlasQueryRepository:
    def __init__(self) -> None:
        self.programs = [
            _program("111210046", "Tıp", "Tıp Fakültesi", "lisans", "SAY", "Türkçe", 75, 75, 478.68376, 23162, 1),
            _program("111210012", "Bilgisayar Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "lisans", "SAY", "Türkçe", 75, 77, 333.23603, 210078, 1, school_first_quota=2, school_first_placed=2),
            _program("111210011", "Elektrik-Elektronik Mühendisliği", "Mühendislik ve Doğa Bilimleri Fakültesi", "lisans", "SAY", "Türkçe", 40, 41, 319.40685, 245901, 1),
            _program("111210102", "Endüstri Mühendisliği (İngilizce)", "Mühendislik ve Doğa Bilimleri Fakültesi", "lisans", "SAY", "İngilizce", 55, 57, 317.76857, 250517, 4),
            _program("111210016", "Ebelik", "Sağlık Bilimleri Fakültesi", "lisans", "SAY", "Türkçe", 60, 60, 336.27693, 203028, 1),
            _program("111210032", "Fizyoterapi ve Rehabilitasyon", "Sağlık Bilimleri Fakültesi", "lisans", "SAY", "Türkçe", 44, 44, 306.16679, 286938, 0),
            _program("111210017", "Hemşirelik", "Sağlık Bilimleri Fakültesi", "lisans", "SAY", "Türkçe", 70, 70, 370.90367, 138188, 0),
            _program("111210039", "Gastronomi ve Mutfak Sanatları", "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "lisans", "SÖZ", "Türkçe", 45, 45, 337.79175, 86122, 0),
            _program("111210123", "İlahiyat", "İlahiyat Fakültesi", "lisans", "SÖZ", "Arapça (%30)", 81, 84, 269.5113, 473265, 4),
            _program("111210130", "İlahiyat (M.T.O.K.)", "İlahiyat Fakültesi", "lisans", "SÖZ", "Arapça (%30)", 9, 9, 265.28168, 511978, 5),
            _program("111210109", "İlahiyat (Arapça)", "İlahiyat Fakültesi", "lisans", "SÖZ", "Arapça", 31, 31, 259.512, 566326, 4),
            _program("111210116", "İlahiyat (Arapça) (M.T.O.K.)", "İlahiyat Fakültesi", "lisans", "SÖZ", "Arapça", 4, 4, 250.62776, 652863, 5),
            _program("111210074", "Arapça Mütercim ve Tercümanlık", "İktisadi, İdari ve Sosyal Bilimler Fakültesi", "lisans", "DİL", "Arapça", 35, 36, 260.18402, 88728, 4),
            _program("111210081", "İngilizce Mütercim ve Tercümanlık", "İktisadi, İdari ve Sosyal Bilimler Fakültesi", "lisans", "DİL", "İngilizce", 30, 31, 372.13859, 33208, 3),
            _program("111210053", "Ameliyathane Hizmetleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "onlisans", "TYT", "Türkçe", 40, 40, 333.96671, 512625, 0),
            _program("111210022", "Tıbbi Laboratuvar Teknikleri", "Sağlık Hizmetleri Meslek Yüksekokulu", "onlisans", "TYT", "Türkçe", 40, 40, 339.55729, 469844, 0),
            _program("111210021", "İlk ve Acil Yardım", "Sağlık Hizmetleri Meslek Yüksekokulu", "onlisans", "TYT", "Türkçe", 40, 40, 356.23154, 359865, 0),
            _program("111210023", "Bilgisayar Programcılığı", "Teknik Bilimler Meslek Yüksekokulu", "onlisans", "TYT", "Türkçe", 50, 52, 318.22459, 652256, 0),
            _program("111210024", "Makine", "Teknik Bilimler Meslek Yüksekokulu", "onlisans", "TYT", "Türkçe", 40, 41, 285.28566, 1038265, 0),
        ]

    def list_latest_programs(self) -> list[dict]:
        return self.programs

    def get_conditions_for_program_year(self, program_year_id: str) -> list[dict]:
        program = next(item for item in self.programs if item["program_year_id"] == program_year_id)
        return [
            {
                "condition_code": str(index + 1),
                "condition_text": f"{program['program_name_raw']} özel koşul {index + 1}",
                "source_url": program["program_year_source_url"],
                "data_year": 2025,
            }
            for index in range(program["condition_count"])
        ]


class YokatlasQueryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = YokatlasQueryService(FakeYokatlasQueryRepository())

    def test_yirmi_soruluk_smoke_seti_db_first_yanitlanir(self) -> None:
        cases = [
            ("GİBTÜ Tıp taban puanı kaç?", "base_score", "111210046", "alias"),
            ("Bilgisayar Mühendisliği kontenjanı kaç?", "quota", "111210012", "alias"),
            ("İlahiyat başarı sırası nedir?", "success_rank", "111210123", "alias"),
            ("Bilgisayar Programcılığı kaç kişi alıyor?", "quota", "111210023", "alias"),
            ("GİBTÜ’deki lisans programları neler?", "list_lisans", None, "list"),
            ("GİBTÜ’deki ön lisans programları neler?", "list_onlisans", None, "list"),
            ("Elektrik-Elektronik Mühendisliği puan türü nedir?", "score_type", "111210011", "alias"),
            ("Endüstri Mühendisliği İngilizce mi?", "language", "111210102", "alias"),
            ("ÖSYM kodu 111210012 hangi programa ait?", "osym_code", "111210012", "osym_code"),
            ("Özel koşul bulunan programlar hangileri?", "conditions", None, "list"),
            ("bilg müh taban puanı kaç", "base_score", "111210012", "alias"),
            ("bilgisayar kaç puan", "base_score", None, "clarification_required"),
            ("eem kontenjan", "quota", "111210011", "alias"),
            ("elektirik elektronik başarı sırası", "success_rank", "111210011", "alias"),
            ("ftr kaçla alıyor", "base_score", "111210032", "alias"),
            ("ilahiyat mtok puanı", "base_score", "111210130", "alias"),
            ("arapça tercümanlık kontenjan", "quota", "111210074", "alias"),
            ("ing mütercim başarı sırası", "success_rank", "111210081", "alias"),
            ("tıbbi lab kaç kişi alıyor", "quota", "111210022", "alias"),
            ("hemsirelik taban puanı", "base_score", "111210017", "alias"),
        ]

        for question, intent, code, method in cases:
            with self.subTest(question=question):
                result = self.service.answer_chat_query(question)
                self.assertIsNotNone(result)
                metadata = result["metadata"]
                self.assertTrue(metadata["db_first"])
                self.assertFalse(metadata["rag_fallback_used"])
                self.assertEqual(metadata["intent"], intent)
                self.assertEqual(metadata["match_method"], method)
                self.assertEqual(metadata["matched_program_code"], code)
                self.assertTrue(result["response"])

    def test_yazim_hatasi_alias_ve_alt_kontenjan_varyasyonlari_db_first_yanitlanir(self) -> None:
        cases = [
            (
                "bilgisayar mühendisliği birincilik kontejanı",
                "bilgisayar muhendisligi birincilik kontenjan",
                "quota",
                "111210012",
                "alias",
                "school_first",
                "Okul birincisi kontenjanı: 2",
            ),
            (
                "bilgisayar müh birinci kontenjanı",
                "bilgisayar muhendisligi birinci kontenjan",
                "quota",
                "111210012",
                "alias",
                "school_first",
                "Okul birincisi kontenjanı: 2",
            ),
            (
                "bilgisayar müh okul birincisi kontenjanı",
                "bilgisayar muhendisligi okul birincisi kontenjan",
                "quota",
                "111210012",
                "alias",
                "school_first",
                "Okul birincisi kontenjanı: 2",
            ),
            (
                "bilgisayar müh öğretim dili",
                "bilgisayar muhendisligi ogretim dili",
                "language",
                "111210012",
                "alias",
                None,
                "Öğretim dili: Türkçe",
            ),
            (
                "bilgisayar müh öğrenim dili",
                "bilgisayar muhendisligi ogretim dili",
                "language",
                "111210012",
                "alias",
                None,
                "Öğretim dili: Türkçe",
            ),
            (
                "bilgisayar müh öğrenim dili?",
                "bilgisayar muhendisligi ogretim dili",
                "language",
                "111210012",
                "alias",
                None,
                "Öğretim dili: Türkçe",
            ),
            (
                "Arapça Mütercim ve Tercümanlık 2025 kontejanı",
                "arapca mutercim ve tercumanlik 2025 kontenjan",
                "quota",
                "111210074",
                "alias",
                "general",
                "Genel kontenjan: 35",
            ),
            (
                "tip bölümü genel kontejan nedir",
                "tip bolumu genel kontenjan nedir",
                "quota",
                "111210046",
                "alias",
                "general",
                "Genel kontenjan: 75",
            ),
            (
                "eee başarı sıralaması",
                "eee basari siralamasi",
                "success_rank",
                "111210011",
                "alias",
                None,
                "Başarı sırası: 245.901",
            ),
            (
                "em başarı sıralaması kaç",
                "em basari siralamasi kac",
                "success_rank",
                "111210102",
                "alias",
                None,
                "Başarı sırası: 250.517",
            ),
            (
                "bilgisayar programclığı öğrenim dili",
                "bilgisayar programciligi ogretim dili",
                "language",
                "111210023",
                "alias",
                None,
                "Öğretim dili: Türkçe",
            ),
            (
                "bilgisayar kaç puan",
                "bilgisayar kac puan",
                "base_score",
                None,
                "clarification_required",
                None,
                "birden fazla YÖK Atlas programıyla eşleşiyor",
            ),
        ]

        for question, normalized, intent, code, method, quota_subtype, expected_response in cases:
            with self.subTest(question=question):
                result = self.service.answer_chat_query(question)
                self.assertIsNotNone(result)
                metadata = result["metadata"]
                self.assertTrue(metadata["db_first"])
                self.assertFalse(metadata["rag_fallback_used"])
                self.assertEqual(metadata["normalized_query"], normalized)
                self.assertEqual(metadata["intent"], intent)
                self.assertEqual(metadata["matched_program_code"], code)
                self.assertEqual(metadata["match_method"], method)
                self.assertEqual(metadata["quota_subtype"], quota_subtype)
                self.assertIn(expected_response, result["response"])

                if method != "clarification_required":
                    self.assertIn("- ", result["response"])
                    self.assertIn("Kaynak: YÖK Atlas", result["response"])
                    self.assertTrue(result["sources"])
                    self.assertEqual(result["sources"][0]["category"], "YÖK Atlas")

    def test_son_yerlesen_netleri_kapsam_disi_yanitlanir(self) -> None:
        result = self.service.answer_chat_query("Tıp son yerleşen netleri nedir?")
        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "last_admitted_nets")
        self.assertEqual(result["metadata"]["match_method"], "out_of_scope")
        self.assertIn("tercih/yerleşme veri kapsamına alınmamıştır", result["response"])

    def test_yanit_sablonu_kullanici_dostu_sayi_formatlari_kullanir(self) -> None:
        result = self.service.answer_chat_query("Bilgisayar Mühendisliği başarı sırası nedir?")
        self.assertIsNotNone(result)
        response = result["response"]
        self.assertNotIn("`", response)
        self.assertIn("2025 YÖK Atlas verilerine göre", response)
        self.assertIn("Başarı sırası: 210.078", response)
        self.assertIn("Taban puan: 333,23603", response)
        self.assertIn("Puan türü: SAY", response)
        self.assertIn("Öğretim dili: Türkçe", response)
        self.assertIn("Özel koşul notu: Bu programda 1 özel koşul kaydı bulunuyor.", response)
        self.assertGreaterEqual(response.count("\n"), 5)

    def test_kontenjan_yaniti_teknik_backtick_kullanmaz(self) -> None:
        result = self.service.answer_chat_query("Bilgisayar Mühendisliği kontenjanı kaç?")
        self.assertIsNotNone(result)
        response = result["response"]
        self.assertNotIn("`", response)
        self.assertIn("Genel kontenjan: 75", response)
        self.assertIn("Genel yerleşen: 77", response)
        self.assertIn("Toplam bilinen kontenjan: 75", response)
        self.assertIn("Özel koşul notu:", response)

    def test_liste_yanitlari_kod_agirlikli_gorunmez(self) -> None:
        result = self.service.answer_chat_query("GİBTÜ’deki ön lisans programları neler?")
        self.assertIsNotNone(result)
        response = result["response"]
        self.assertNotIn("`", response)
        self.assertIn("2025 YÖK Atlas verilerine göre ön lisans programları", response)
        self.assertIn("Bilgisayar Programcılığı - TYT", response)

    def test_rag_service_yokatlas_sorusunu_pipeline_kurmadan_yanitlar(self) -> None:
        fake_service = YokatlasQueryService(FakeYokatlasQueryRepository())
        rag = RagService()
        with patch("app.services.rag_service.get_yokatlas_query_service", return_value=fake_service):
            result = rag.query("eem kontenjan")
        self.assertEqual(result["metadata"]["intent"], "quota")
        self.assertEqual(result["metadata"]["matched_program_code"], "111210011")
        self.assertIn("kontenjan", result["response"])

    def test_rag_service_yokatlas_metric_sorusunu_birim_servisinden_once_yanitlar(self) -> None:
        class FailingService:
            def answer_chat_query(self, question):
                raise AssertionError("YÖK Atlas metriği birim servisine düşmemeli")

        fake_service = YokatlasQueryService(FakeYokatlasQueryRepository())
        rag = RagService()
        with (
            patch("app.services.rag_service.get_yokatlas_query_service", return_value=fake_service),
            patch("app.services.rag_service.get_unit_management_service", return_value=FailingService()),
        ):
            result = rag.query("bilgisayar mühendisliği birincilik kontejanı")

        self.assertEqual(result["metadata"]["intent"], "quota")
        self.assertEqual(result["metadata"]["quota_subtype"], "school_first")
        self.assertEqual(result["metadata"]["matched_program_code"], "111210012")

    def test_yokatlas_disi_soru_rag_akisine_birakilir(self) -> None:
        self.assertIsNone(self.service.answer_chat_query("GİBTÜ yemekhane menüsü nedir?"))


if __name__ == "__main__":
    unittest.main()
