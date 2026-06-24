"""Response validator güçlendirme testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.response_validator import (  # noqa: E402
    ACADEMIC_STAFF_RAG_FALLBACK_RESPONSE,
    GENERAL_CONTACT_EMAIL,
    LANGUAGE_FALLBACK_RESPONSE,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PHONE,
    enforce_turkish_response,
    validate_response,
)
from app.services.rag_service import _append_general_contact_if_needed, _strip_contradictory_fallback  # noqa: E402


class ResponseValidatorWhitelistTests(unittest.TestCase):
    def test_metadata_contact_info_email_whitelist_olarak_kullanilir(self):
        sources = [
            {
                "content": "Aday öğrenci iletişim bilgileri.",
                "source_url": "https://adayogrenci.gibtu.edu.tr/#iletisim-bilgileri",
                "contact_info": "aday@gibtu.edu.tr",
            }
        ]

        result = validate_response("E-posta: aday@gibtu.edu.tr", sources)

        self.assertIn("aday@gibtu.edu.tr", result)

    def test_whitelist_disi_gibtu_email_kaldirilir(self):
        sources = [{"content": "İletişim: aday@gibtu.edu.tr"}]

        result = validate_response("E-posta: sahte@gibtu.edu.tr", sources)

        self.assertNotIn("sahte@gibtu.edu.tr", result)
        self.assertIn(PLACEHOLDER_EMAIL, result)

    def test_telefon_whitelist_format_farkini_tolere_eder(self):
        sources = [{"content": "Telefon: 0342 909 75 00"}]

        result = validate_response("Telefon: +90 342 909 75 00", sources)

        self.assertIn("+90 342 909 75 00", result)

    def test_whitelist_disi_telefon_kaldirilir(self):
        sources = [{"content": "Telefon: 0342 909 75 00"}]

        result = validate_response("Telefon: 0342 111 22 33", sources)

        self.assertNotIn("0342 111 22 33", result)
        self.assertIn(PLACEHOLDER_PHONE, result)

    def test_kaynakta_gecen_dis_email_korunur(self):
        sources = [{"content": "Başvuru e-postası: info@example.org"}]

        result = validate_response("Başvuru: info@example.org", sources)

        self.assertIn("info@example.org", result)

    def test_kutuphane_sorusunda_alakasiz_kaynak_maili_kaldirilir(self):
        sources = [
            {
                "content": "Kütüphane ve Dokümantasyon Daire Başkanlığı çalışma saatleri.",
                "meta": {"category": "kutuphane", "title": "Kütüphane"},
            },
            {
                "content": "Sağlık Bilimleri Fakültesi iletişim: sbf@gibtu.edu.tr",
                "meta": {"category": "bolumler", "title": "Sağlık Bilimleri Fakültesi"},
            },
        ]

        result = validate_response(
            "Kütüphane için e-posta: sbf@gibtu.edu.tr",
            sources,
            question="Kütüphane hafta sonu açık mı?",
        )

        self.assertNotIn("sbf@gibtu.edu.tr", result)
        self.assertIn(PLACEHOLDER_EMAIL, result)

    def test_konuya_ozel_mail_yoksa_genel_mail_whitelisttedir(self):
        sources = [
            {
                "content": "Kütüphane ve Dokümantasyon Daire Başkanlığı çalışma saatleri.",
                "meta": {"category": "kutuphane", "title": "Kütüphane"},
            }
        ]

        result = validate_response(
            f"Genel iletişim: {GENERAL_CONTACT_EMAIL}",
            sources,
            question="Kütüphane hafta sonu açık mı?",
        )

        self.assertIn(GENERAL_CONTACT_EMAIL, result)


class RagResponsePostProcessTests(unittest.TestCase):
    def test_context_varken_frankenstein_fallback_temizlenir(self):
        response = (
            "Ders kaydı işlemleri akademik takvimde belirtilen tarihlerde öğrenci bilgi sistemi üzerinden yapılır.\n\n"
            "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için Öğrenci İşleri birimine başvurmanızı öneriyorum."
        )
        sources = [{"content": "Ders kaydı işlemleri öğrenci bilgi sistemi üzerinden yapılır."}]

        result = _strip_contradictory_fallback(response, sources)

        self.assertIn("Ders kaydı işlemleri", result)
        self.assertNotIn("yeterli bilgi bulunmuyor", result.lower())

    def test_fallback_only_yanit_korunur(self):
        response = "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için ilgili birime başvurmanızı öneriyorum."

        result = _strip_contradictory_fallback(response, [{"content": "Kısa kaynak"}])

        self.assertEqual(result, response)

    def test_konuya_ozel_mail_yoksa_genel_mail_eklenir(self):
        response = "Kütüphane çalışma saatleri için güncel duyurular takip edilmelidir."
        sources = [{"content": "Kütüphane ve Dokümantasyon Daire Başkanlığı çalışma saatleri."}]

        result = _append_general_contact_if_needed(response, "Kütüphane hafta sonu açık mı?", sources)

        self.assertIn(GENERAL_CONTACT_EMAIL, result)


class ResponseLanguageConsistencyTests(unittest.TestCase):
    def test_ingilizce_kaliplar_turkcelestirilir(self):
        result = enforce_turkish_response(
            "Based on the provided documents: For more information, please contact the department."
        )

        self.assertIn("Belgelerdeki bilgilere göre", result)
        self.assertIn("Detaylı bilgi için", result)
        self.assertNotIn("Based on", result)

    def test_ingilizce_baskin_yanit_guvenli_turkce_fallback_doner(self):
        result = validate_response(
            (
                "The university has departments and students can apply for programs. "
                "The documents provide information about the campus and library."
            ),
            [],
        )

        self.assertEqual(result, LANGUAGE_FALLBACK_RESPONSE)

    def test_portekizce_baskin_yanit_guvenli_turkce_fallback_doner(self):
        result = validate_response(
            (
                "Os professores do departamento segundo os documentos da universidade "
                "fornecem informacoes sobre programas academicos."
            ),
            [],
        )

        self.assertEqual(result, LANGUAGE_FALLBACK_RESPONSE)

    def test_turkce_yanit_degisiklik_yapilmeden_kalir(self):
        response = "GİBTÜ aday öğrencileri için kampüs olanakları ve yurt bilgileri kaynaklarda yer almaktadır."

        result = enforce_turkish_response(response)

        self.assertEqual(result, response)


class AcademicStaffResponseValidatorTests(unittest.TestCase):
    def test_akademik_kadro_rag_yayin_tez_paragrafi_engellenir(self):
        sources = [
            {
                "content": "Bilgisayar Mühendisliği Bölümü akademik kadro kaynağı.",
                "category": "akademik_kadro",
                "doc_kind": "yok_akademik_staff",
            }
        ]

        result = validate_response(
            "Bilgisayar alanındaki yayınlar, tezler, makaleler ve DOI bilgileri şöyledir.",
            sources,
        )

        self.assertEqual(result, ACADEMIC_STAFF_RAG_FALLBACK_RESPONSE)

    def test_akademik_kadro_rag_yonetim_tahmini_engellenir(self):
        sources = [
            {
                "content": "Bilgisayar Mühendisliği Bölümü akademik kadro kaynağı.",
                "meta": {"category": "akademik_kadro", "doc_kind": "yok_akademik_staff"},
            }
        ]

        result = validate_response("Bu bölümün dekanı Ali Veli olarak görünmektedir.", sources)

        self.assertEqual(result, ACADEMIC_STAFF_RAG_FALLBACK_RESPONSE)


if __name__ == "__main__":
    unittest.main()
