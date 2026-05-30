"""Response validator güçlendirme testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.response_validator import (  # noqa: E402
    LANGUAGE_FALLBACK_RESPONSE,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_PHONE,
    enforce_turkish_response,
    validate_response,
)


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

    def test_turkce_yanit_degisiklik_yapilmeden_kalir(self):
        response = "GİBTÜ aday öğrencileri için kampüs olanakları ve yurt bilgileri kaynaklarda yer almaktadır."

        result = enforce_turkish_response(response)

        self.assertEqual(result, response)


if __name__ == "__main__":
    unittest.main()
