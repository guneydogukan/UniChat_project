"""Birim yönetim DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.unit_management_service import UnitManagementService  # noqa: E402


class FakeUnitManagementRepository:
    def __init__(self) -> None:
        self.units = [
            {
                "id": "mdbf",
                "unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name_normalized": "muhendislik ve doga bilimleri fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15",
                "aliases": ["mdbf"],
            },
            {
                "id": "tip",
                "unit_name": "Tıp Fakültesi",
                "unit_name_normalized": "tip fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=20",
                "aliases": ["tip"],
            },
            {
                "id": "tbmyo",
                "unit_name": "Teknik Bilimler Meslek Yüksekokulu",
                "unit_name_normalized": "teknik bilimler meslek yuksekokulu",
                "unit_type": "vocational_school",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=36",
                "aliases": ["tbmyo", "teknik bilimler myo"],
            },
        ]
        self.members = {
            "mdbf": [
                self._member(
                    "m1",
                    "mdbf",
                    "Dekanlık",
                    "dekanlik",
                    "Osman BİLGİN",
                    "Prof. Dr.",
                    "Dekan V.",
                    "2201",
                    "osman.bilgin@gibtu.edu.tr",
                    1,
                ),
                self._member(
                    "m2",
                    "mdbf",
                    "Dekanlık",
                    "dekanlik",
                    "Ali AYTEK",
                    "Prof. Dr.",
                    "Dekan Yrd.",
                    "2203",
                    "ali.aytek@gibtu.edu.tr",
                    2,
                ),
                self._member(
                    "m3",
                    "mdbf",
                    "Fakülte Sekreterliği",
                    "fakulte sekreterligi",
                    "Ergün ÖZUSLU",
                    None,
                    "Fakülte Sekreteri",
                    "2206",
                    "ergun.ozuslu@gibtu.edu.tr",
                    3,
                ),
                self._member(
                    "m4",
                    "mdbf",
                    "Yönetim Kurulu",
                    "yonetim kurulu",
                    "Osman BİLGİN",
                    "Prof. Dr.",
                    "Başkan",
                    "2201",
                    "osman.bilgin@gibtu.edu.tr",
                    4,
                ),
                self._member(
                    "m5",
                    "mdbf",
                    "Yönetim Kurulu",
                    "yonetim kurulu",
                    "Cemal AKTÜRK",
                    "Doç. Dr.",
                    "Üye",
                    "2241",
                    "cemal.akturk@gibtu.edu.tr",
                    5,
                ),
            ],
            "tip": [
                self._member(
                    "t0",
                    "tip",
                    "Dekan",
                    "dekan",
                    "İbrahim Halil TÜRKBEYLER",
                    "Prof. Dr.",
                    "Dekan V.",
                    "2301",
                    "ihalil.turkbeyler@gibtu.edu.tr",
                    0,
                ),
                self._member(
                    "t1",
                    "tip",
                    "Fakülte Yönetim Kurulu",
                    "fakulte yonetim kurulu",
                    "İbrahim Halil TÜRKBEYLER",
                    "Prof. Dr.",
                    "Başkan",
                    "2301",
                    "ihalil.turkbeyler@gibtu.edu.tr",
                    1,
                ),
                self._member(
                    "t2",
                    "tip",
                    "Fakülte Yönetim Kurulu",
                    "fakulte yonetim kurulu",
                    "Aliye BULUT",
                    "Prof. Dr.",
                    "Üye",
                    "0000",
                    "aliye.bulut@gibtu.edu.tr",
                    2,
                    parse_status="partial",
                ),
            ],
            "tbmyo": [],
        }

    def list_units(self):
        return list(self.units)

    def get_management_members(self, unit_id, group_keys=None):
        return list(self.members.get(unit_id, []))

    @staticmethod
    def _member(
        member_id,
        unit_id,
        group_title,
        group_key,
        full_name,
        academic_title,
        role,
        phone,
        email,
        page_order,
        parse_status="ok",
    ):
        return {
            "member_id": member_id,
            "stable_member_key": f"email:{email}",
            "unit_id": unit_id,
            "group_id": f"group-{group_key}",
            "group_title": group_title,
            "group_key": group_key,
            "group_order": 1,
            "full_name": full_name,
            "full_name_normalized": full_name.lower(),
            "academic_title": academic_title,
            "role": role,
            "phone_extension": phone,
            "email": email,
            "profile_url": None,
            "source_url": f"https://www.gibtu.edu.tr/BirimYonetim.aspx?id={15 if unit_id == 'mdbf' else 20}",
            "page_order": page_order,
            "scrape_time": "2026-06-14T12:00:00Z",
            "parse_status": parse_status,
        }


class UnitManagementServiceTests(unittest.TestCase):
    def test_dekan_sorusu_dbden_yanitlanir_ve_yardimciyi_karistirmaz(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Mühendislik ve Doğa Bilimleri Fakültesi dekanı kim?")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("Osman BİLGİN", response)
        self.assertIn("Dekan V.", response)
        self.assertNotIn("Ali AYTEK", response)
        self.assertIn("Kaynak: https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15", response)

    def test_mdbf_aliasi_ile_fakulte_sekreteri_bulunur(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("MDBF fakülte sekreteri kim?")

        self.assertIsNotNone(result)
        self.assertIn("Ergün ÖZUSLU", result["response"])
        self.assertIn("Fakülte Sekreteri", result["response"])

    def test_kisa_fakulte_adi_ile_dekan_sorusu_yanitlanir(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        muhendislik = service.answer_chat_query("Mühendislik dekanı kim?")
        tip = service.answer_chat_query("Tıp dekanı kim?")

        self.assertIsNotNone(muhendislik)
        self.assertIn("Osman BİLGİN", muhendislik["response"])
        self.assertIsNotNone(tip)
        self.assertIn("İbrahim Halil TÜRKBEYLER", tip["response"])

    def test_yonetim_kurulu_sorusu_kurul_uyelerini_listeler(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Tıp Fakültesi yönetim kurulunda kimler var?")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("İbrahim Halil TÜRKBEYLER", response)
        self.assertIn("Aliye BULUT", response)
        self.assertNotIn("Dahili: 0000", response)

    def test_veri_yoksa_tahminsiz_not_found_doner(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Teknik Bilimler MYO müdürü kim?")

        self.assertIsNotNone(result)
        self.assertIn("mevcut kaynakta bulunamadı", result["response"])

    def test_birim_belirsizse_rag_fallback_yapmadan_birim_ister(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Dekan kim?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi birimin", result["response"])


if __name__ == "__main__":
    unittest.main()
