"""Derslik Excel ingestion/seed üretim testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from tools.generate_classroom_seed_sql import (  # noqa: E402
    extract_department,
    generate_seed_sql,
    infer_space_department_code,
    normalize_for_match,
    normalize_room_code,
    parse_seed_data_from_rows,
    records_from_rows,
    space_records_from_rows,
)


class ClassroomIngestionTests(unittest.TestCase):
    def test_room_code_normalizasyonu_z_varyasyonlarini_standartlastirir(self):
        self.assertEqual(normalize_room_code("113"), "113")
        self.assertEqual(normalize_room_code("Z-114"), "z-114")
        self.assertEqual(normalize_room_code("z114"), "z-114")
        self.assertEqual(normalize_room_code("z 114"), "z-114")

    def test_bolum_kodu_regex_ile_parantezden_cikarilir(self):
        name, code, is_shared = extract_department("Bilgisayar Mühendisliği (BM)")

        self.assertEqual(name, "Bilgisayar Mühendisliği")
        self.assertEqual(code, "BM")
        self.assertFalse(is_shared)

    def test_ortak_kullanim_shared_olarak_isaretlenir(self):
        name, code, is_shared = extract_department("Ortak Kullanım (Ortak)")

        self.assertEqual(name, "Ortak Kullanım")
        self.assertEqual(code, "ORTAK")
        self.assertTrue(is_shared)

    def test_rows_to_records_kolonlari_normalize_eder(self):
        rows = [
            ["Bina Adı", "Kat", "Derslik No", "Derslik Türü", "Kapasite", "Bölüm"],
            [
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "Zemin",
                "z114",
                "Laboratuvar",
                "32",
                "Bilgisayar Mühendisliği (BM)",
            ],
        ]

        records = records_from_rows(rows, "Derslikler.xlsx")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].floor_label, "Zemin")
        self.assertEqual(records[0].normalized_room_code, "z-114")
        self.assertEqual(records[0].department_code, "BM")
        self.assertEqual(records[0].capacity, 32)
        self.assertEqual(
            records[0].normalized_building_name,
            normalize_for_match("Mühendislik ve Doğa Bilimleri Fakültesi"),
        )

    def test_derslik_adi_bos_idari_ofis_satirlari_space_olarak_alinir(self):
        rows = [
            ["KAT BİLGİSİ", "DERSLİK ADI", "BİNA ADI", "KAPASİTE", "TİP", "BİRİM / KULLANIM"],
            [
                "4",
                "",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "",
                "İdari Ofis",
                "Akademik personel odaları, Fakülte Sekreterliği",
            ],
            [
                "3",
                "",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "",
                "İdari Ofis",
                "Öğrenci İşleri",
            ],
            [
                "4",
                "",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "",
                "İdari Ofis",
                "Dekan, Dekan Yardımcısı",
            ],
            [
                "1",
                "113",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "104",
                "Amfi",
                "Ortak Kullanım (Ortak)",
            ],
        ]

        seed_data = parse_seed_data_from_rows(rows, "Derslikler.xlsx")

        self.assertEqual(len(seed_data.classrooms), 1)
        self.assertEqual(seed_data.classrooms[0].room_code, "113")
        self.assertNotIn("İdari Ofis", seed_data.classrooms[0].search_text)
        self.assertEqual(len(seed_data.spaces), 3)
        self.assertEqual(seed_data.spaces[1].space_name, "Öğrenci İşleri")
        self.assertEqual(seed_data.spaces[1].space_type, "İdari Ofis")
        self.assertIn("Fakülte Sekreterliği", seed_data.spaces[0].aliases)
        self.assertIn("Dekanlık", seed_data.spaces[2].aliases)

    def test_idari_bolum_baskanligi_kodu_parantezsiz_ise_sinirli_hint_ile_cikarilir(self):
        rows = [
            ["KAT BİLGİSİ", "DERSLİK ADI", "BİNA ADI", "KAPASİTE", "TİP", "BİRİM / KULLANIM"],
            [
                "4",
                "",
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "",
                "İdari Ofis",
                "Bilgisayar Mühendisliği Bölüm Başkanlığı",
            ],
        ]

        spaces = space_records_from_rows(rows, "Derslikler.xlsx")

        self.assertEqual(len(spaces), 1)
        self.assertEqual(spaces[0].department_code, "BM")
        self.assertIn("BM Bölüm Başkanlığı", spaces[0].aliases)
        self.assertEqual(infer_space_department_code("Elektrik-Elektronik Mühendisliği Bölüm Başkanlığı"), "EEM")

    def test_seed_sql_transaction_ve_alias_insert_uretimi(self):
        rows = [
            ["Bina", "Kat", "Oda", "Tür", "Kapasite", "Bölüm"],
            [
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "1. Kat",
                "113",
                "Amfi",
                "104 kişi",
                "Ortak Kullanım (Ortak)",
            ],
            [
                "Mühendislik ve Doğa Bilimleri Fakültesi",
                "3",
                "",
                "İdari Ofis",
                "",
                "Öğrenci İşleri",
            ],
        ]
        seed_data = parse_seed_data_from_rows(rows)

        sql = generate_seed_sql(seed_data.classrooms, spaces=seed_data.spaces)

        self.assertIn("BEGIN;", sql)
        self.assertIn("DELETE FROM campus_spaces WHERE source_file = 'Derslikler.xlsx';", sql)
        self.assertIn("DELETE FROM classrooms WHERE source_file = 'Derslikler.xlsx';", sql)
        self.assertIn("INSERT INTO campus_buildings", sql)
        self.assertIn("INSERT INTO campus_spaces", sql)
        self.assertIn("mdbf", sql)
        self.assertIn("'113'", sql)
        self.assertIn("Öğrenci İşleri", sql)
        self.assertIn("TRUE", sql)
        self.assertIn("COMMIT;", sql)

    def test_zorunlu_kolon_yoksa_acik_hata_verir(self):
        with self.assertRaisesRegex(ValueError, "Zorunlu derslik kolonları"):
            records_from_rows([["Bina", "Kat"], ["MDBF", "1"]])


if __name__ == "__main__":
    unittest.main()
