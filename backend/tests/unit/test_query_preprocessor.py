"""Query preprocessor typo düzeltme sınır testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.query_preprocessor import preprocess_query  # noqa: E402


class QueryPreprocessorTests(unittest.TestCase):
    def test_aday_sss_kelimeleri_yanlis_fuzzy_duzeltmeye_ugramaz(self) -> None:
        result = preprocess_query("Aday öğrenci sık sorulan sorular neler?")

        self.assertEqual(result.corrected_query, "Aday öğrenci sık sorulan sorular neler?")
        self.assertNotIn("radyo", result.keyword_query)
        self.assertNotIn("spor", result.keyword_query)


if __name__ == "__main__":
    unittest.main()
