"""Aday öğrenci kaynak önceliği birim testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from haystack import Document  # noqa: E402

from app.services.rag_service import (  # noqa: E402
    CandidateSourcePrioritizer,
    _candidate_priority_query_suffix,
    prioritize_candidate_documents,
)


def _doc(title: str, category: str, doc_kind: str, source_anchor: str | None = None) -> Document:
    meta = {
        "title": title,
        "category": category,
        "doc_kind": doc_kind,
        "source_url": f"https://www.gibtu.edu.tr/{title.lower().replace(' ', '-')}",
    }
    if category == "aday_ogrenci":
        anchor = source_anchor or "olanaklar"
        meta.update(
            {
                "source_url": f"https://adayogrenci.gibtu.edu.tr/#{anchor}",
                "source_public_url": f"https://adayogrenci.gibtu.edu.tr/#{anchor}",
                "source_anchor": anchor,
                "metadata_version": "candidate.v1",
                "scraper_name": "candidate_portal_scraper",
                "is_official": True,
            }
        )
    elif source_anchor:
        meta["source_anchor"] = source_anchor

    return Document(content=f"{title} içeriği", meta=meta)


class CandidateSourcePriorityTests(unittest.TestCase):
    def test_iletisim_sorgusunda_aday_iletisim_kaynagi_once_gelir(self):
        documents = [
            _doc("Genel İletişim", "iletisim", "birim_iletisim"),
            _doc("Aday Portalı İletişim", "aday_ogrenci", "candidate_contact", "iletisim-bilgileri"),
            _doc("Aday Portalı Olanaklar", "aday_ogrenci", "candidate_opportunity", "olanaklar"),
        ]

        prioritized = prioritize_candidate_documents("Aday öğrenciler için iletişim bilgileri nedir?", documents)

        self.assertEqual(prioritized[0].meta["title"], "Aday Portalı İletişim")
        self.assertEqual(prioritized[0].meta["source_anchor"], "iletisim-bilgileri")

    def test_erasmus_sorgusunda_aday_erasmus_kaynagi_once_gelir(self):
        documents = [
            _doc("Erasmus Koordinatörlüğü", "erasmus", "rehber"),
            _doc("Aday Portalı Erasmus", "aday_ogrenci", "candidate_exchange", "erasmus"),
        ]

        prioritized = prioritize_candidate_documents("Erasmus imkanı var mı?", documents)

        self.assertEqual(prioritized[0].meta["title"], "Aday Portalı Erasmus")

    def test_alakasiz_sorguda_mevcut_siralama_korunur(self):
        documents = [
            _doc("Öğrenci İşleri Transkript", "ogrenci_isleri", "rehber"),
            _doc("Aday Portalı Olanaklar", "aday_ogrenci", "candidate_opportunity", "olanaklar"),
        ]

        prioritized = prioritize_candidate_documents("Transkript nasıl alınır?", documents)

        self.assertEqual(prioritized, documents)

    def test_retriever_sorgu_eki_sadece_aday_kritik_sinyalde_uretilir(self):
        self.assertIn("aday öğrenci", _candidate_priority_query_suffix("Yurt ve konaklama imkanı var mı?"))
        self.assertIn("kayıt", _candidate_priority_query_suffix("Kayıt ve tercih süreci nasıl ilerliyor?"))
        self.assertEqual(_candidate_priority_query_suffix("Transkript nasıl alınır?"), "")

    def test_haystack_bileseni_oncelikli_siralama_dondurur(self):
        documents = [
            _doc("Genel Kulüpler", "topluluklar", "rehber"),
            _doc("Aday Portalı Kulüpler", "aday_ogrenci", "candidate_opportunity", "olanaklar"),
        ]

        result = CandidateSourcePrioritizer().run(
            documents=documents,
            question="Öğrenci kulüpleri var mı?",
        )

        self.assertEqual(result["documents"][0].meta["title"], "Aday Portalı Kulüpler")


if __name__ == "__main__":
    unittest.main()
