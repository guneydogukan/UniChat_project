"""Intent classifier kapsam ve SSS guard testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.intent_classifier import classify_intent  # noqa: E402


class IntentClassifierTests(unittest.TestCase):
    def test_genel_sss_sorusu_universite_kapsaminda_kalir(self) -> None:
        self.assertEqual(classify_intent("Sık sorulan sorular neler?"), "IN_SCOPE")

    def test_siyaset_sorusu_rag_pipelinea_gitmeden_reddedilir(self) -> None:
        self.assertEqual(classify_intent("İsrail ve Birleşmiş Milletler kararı nedir?"), "OUT_OF_SCOPE")

    def test_derslik_sorusu_universite_kapsaminda_kalir(self) -> None:
        self.assertEqual(classify_intent("mühendislik fakültesi 113 nerede"), "IN_SCOPE")

    def test_idari_alan_konum_sorusu_universite_kapsaminda_kalir(self) -> None:
        self.assertEqual(classify_intent("öğrenci işleri nerede"), "IN_SCOPE")


if __name__ == "__main__":
    unittest.main()
