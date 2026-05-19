import unittest

from migrate_academic_year_source_metadata import (
    SourceLookup,
    build_updated_meta,
    infer_year_metadata,
    normalize_academic_year,
)


class MetadataMigrationTests(unittest.TestCase):
    def test_normalize_academic_year_variants(self):
        self.assertEqual(normalize_academic_year("2025 / 2026"), "2025-2026")
        self.assertEqual(normalize_academic_year("2025-2026"), "2025-2026")
        self.assertEqual(normalize_academic_year("2025–2026"), "2025-2026")

    def test_strategic_plan_range_is_not_academic_year_without_context(self):
        meta = {"title": "Stratejik Plan 2022 - 2026", "doc_kind": "rapor"}

        academic_year, document_year = infer_year_metadata(meta, "")

        self.assertIsNone(academic_year)
        self.assertIsNone(document_year)

    def test_strategic_plan_title_without_separator_is_not_document_year(self):
        meta = {"title": "Stratejik Plan 2022 2026", "doc_kind": "rapor"}

        academic_year, document_year = infer_year_metadata(meta, "")

        self.assertIsNone(academic_year)
        self.assertIsNone(document_year)

    def test_report_single_year_sets_document_year_only(self):
        meta = {"title": "2024 Yılı Faaliyet Raporu", "doc_kind": "rapor"}

        academic_year, document_year = infer_year_metadata(meta, "")

        self.assertIsNone(academic_year)
        self.assertEqual(document_year, "2024")

    def test_academic_context_sets_academic_year(self):
        meta = {
            "title": "2025 / 2026 Eğitim Öğretim Yılı Önlisans-Lisans Akademik Takvimi",
            "doc_kind": "takvim",
        }

        academic_year, document_year = infer_year_metadata(meta, "")

        self.assertEqual(academic_year, "2025-2026")
        self.assertIsNone(document_year)

    def test_local_pdf_public_url_is_added_without_overwriting_source_url(self):
        lookup = SourceLookup(by_key={"2024 yili faaliyet raporu": "https://www.gibtu.edu.tr/rapor.pdf"})
        meta = {
            "source_url": r"C:\data\pdfs\raporlar_web\2024 Yılı Faaliyet Raporu.pdf",
            "title": "2024 Yılı Faaliyet Raporu",
            "doc_kind": "rapor",
        }

        updated = build_updated_meta(meta, "", lookup)

        self.assertEqual(updated["source_url"], meta["source_url"])
        self.assertEqual(updated["source_file_path"], meta["source_url"])
        self.assertEqual(updated["source_public_url"], "https://www.gibtu.edu.tr/rapor.pdf")
        self.assertEqual(updated["source_public_url_status"], "resolved")
        self.assertEqual(updated["document_year"], "2024")
        self.assertIsNone(updated["academic_year"])


if __name__ == "__main__":
    unittest.main()
