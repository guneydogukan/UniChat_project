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
                "id": "ilahiyat",
                "unit_name": "İlahiyat Fakültesi",
                "unit_name_normalized": "ilahiyat fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=11",
                "aliases": ["if"],
            },
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
                "id": "sbf",
                "unit_name": "Sağlık Bilimleri Fakültesi",
                "unit_name_normalized": "saglik bilimleri fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=21",
                "aliases": ["sbf"],
            },
            {
                "id": "iisbf",
                "unit_name": "İktisadi İdari ve Sosyal Bilimler Fakültesi",
                "unit_name_normalized": "iktisadi idari ve sosyal bilimler fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=22",
                "aliases": ["iisbf"],
            },
            {
                "id": "gstm",
                "unit_name": "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
                "unit_name_normalized": "guzel sanatlar tasarim ve mimarlik fakultesi",
                "unit_type": "faculty",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=24",
                "aliases": ["gstm"],
            },
            {
                "id": "shmyo",
                "unit_name": "Sağlık Hizmetleri Meslek Yüksekokulu",
                "unit_name_normalized": "saglik hizmetleri meslek yuksekokulu",
                "unit_type": "vocational_school",
                "source_url": "https://www.gibtu.edu.tr/birimyonetim.aspx?id=31",
                "aliases": ["shmyo"],
            },
            {
                "id": "tbmyo",
                "unit_name": "Teknik Bilimler Meslek Yüksekokulu",
                "unit_name_normalized": "teknik bilimler meslek yuksekokulu",
                "unit_type": "vocational_school",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=36",
                "aliases": ["tbmyo", "teknik bilimler myo"],
            },
            {
                "id": "ydyo",
                "unit_name": "Yabancı Diller Yüksekokulu",
                "unit_name_normalized": "yabanci diller yuksekokulu",
                "unit_type": "school",
                "source_url": "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=34",
                "aliases": ["ydyo"],
            },
        ]
        self.members = {
            "ilahiyat": [
                self._member(
                    "if1",
                    "ilahiyat",
                    "Dekanlık",
                    "dekanlik",
                    "Mahsum AYTEPE",
                    "Prof. Dr.",
                    "Dekan",
                    "2100",
                    "mahsum.aytepe@gibtu.edu.tr",
                    1,
                ),
            ],
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
            "sbf": [
                self._member(
                    "sbf1",
                    "sbf",
                    "Dekan",
                    "dekan",
                    "Reşit YILDIZ",
                    "Prof. Dr.",
                    "Dekan V.",
                    "2401",
                    "resit.yildiz@gibtu.edu.tr",
                    1,
                ),
            ],
            "iisbf": [
                self._member(
                    "iisbf1",
                    "iisbf",
                    "Dekan",
                    "dekan",
                    "Feridun BİLGİN",
                    "Prof. Dr.",
                    "Dekan V.",
                    "0000",
                    "fbilgin@gibtu.edu.tr",
                    1,
                    parse_status="partial",
                ),
            ],
            "gstm": [
                self._member(
                    "gstm1",
                    "gstm",
                    "Dekanlık",
                    "dekanlik",
                    "Şehmus DEMİR",
                    "Prof. Dr.",
                    "Prof. Dr.",
                    "0000",
                    "sehmus.demir@gibtu.edu.tr",
                    1,
                    parse_status="partial",
                ),
            ],
            "shmyo": [
                self._member(
                    "shmyo1",
                    "shmyo",
                    "Müdür",
                    "mudur",
                    "Hikmet DİNÇ",
                    "Doç. Dr.",
                    "Meslek Yüksekokul Müdürü",
                    "3001",
                    "hikmet.dinc@gibtu.edu.tr",
                    1,
                ),
            ],
            "tbmyo": [
                self._member(
                    "tbmyo1",
                    "tbmyo",
                    "Yüksekokul Müdürü",
                    "yuksekokul muduru",
                    "İpek ATİK",
                    "Doç. Dr.",
                    "Meslek Yüksekokul Müdürü",
                    "3101",
                    "ipek.atik@gibtu.edu.tr",
                    1,
                ),
                self._member(
                    "tbmyo2",
                    "tbmyo",
                    "Müdür Yardımcıları",
                    "mudur yardimcilari",
                    "Ayşe TOPRAK",
                    "Dr. Öğr. Üyesi",
                    "Müdür Yardımcısı",
                    "3102",
                    "ayse.toprak@gibtu.edu.tr",
                    2,
                ),
                self._member(
                    "tbmyo3",
                    "tbmyo",
                    "Yüksekokul Sekreteri",
                    "yuksekokul sekreteri",
                    "Ahmet DEMİR",
                    None,
                    "Meslek Yüksekokulu Sekreteri",
                    "3106",
                    "ahmet.demir@gibtu.edu.tr",
                    3,
                ),
                self._member(
                    "tbmyo4",
                    "tbmyo",
                    "Meslek Yüksekokulu Kurulu",
                    "meslek yuksekokulu kurulu",
                    "İpek ATİK",
                    "Doç. Dr.",
                    "Başkan",
                    "3101",
                    "ipek.atik@gibtu.edu.tr",
                    4,
                ),
            ],
            "ydyo": [
                self._member(
                    "ydyo1",
                    "ydyo",
                    "Yüksekokul Müdürü",
                    "yuksekokul muduru",
                    "Eyyüp TUNCER",
                    "Doç. Dr.",
                    "Yüksekokul Müdürü",
                    "1052",
                    "eyyup.tuncer@gibtu.edu.tr",
                    1,
                ),
            ],
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
        source_ids = {
            "ilahiyat": 11,
            "mdbf": 15,
            "tip": 20,
            "sbf": 21,
            "iisbf": 22,
            "gstm": 24,
            "shmyo": 31,
            "tbmyo": 36,
            "ydyo": 34,
        }
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
            "source_url": f"https://www.gibtu.edu.tr/BirimYonetim.aspx?id={source_ids[unit_id]}",
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

    def test_yaygin_kisaltma_ve_kisa_adlar_yanitlanir(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        cases = [
            ("İ.F. dekanı kim?", "Mahsum AYTEPE"),
            ("M.D.B.F. fakülte sekreteri kim?", "Ergün ÖZUSLU"),
            ("SBF dekanı kim?", "Reşit YILDIZ"),
            ("Sağlık bilimleri fak dekanı kim?", "Reşit YILDIZ"),
            ("T.F. dekanı kim?", "İbrahim Halil TÜRKBEYLER"),
            ("İİBF dekanı kim?", "Feridun BİLGİN"),
            ("İ.İ.S.B.F. dekanı kim?", "Feridun BİLGİN"),
            ("G.S.T.M.F. dekanı kim?", "Şehmus DEMİR"),
            ("Güzel sanatlar dekanı kim?", "Şehmus DEMİR"),
            ("Mimarlık dekanı kim?", "Şehmus DEMİR"),
            ("SH MYO müdürü kim?", "Hikmet DİNÇ"),
            ("S.H.M.Y.O. müdürü kim?", "Hikmet DİNÇ"),
            ("Sağlık MYO müdürü kim?", "Hikmet DİNÇ"),
            ("TB MYO müdürü kim?", "İpek ATİK"),
            ("T.B.M.Y.O. müdürü kim?", "İpek ATİK"),
            ("Teknik MYO müdürü kim?", "İpek ATİK"),
            ("YD YO müdürü kim?", "Eyyüp TUNCER"),
            ("Y.D.Y.O. müdürü kim?", "Eyyüp TUNCER"),
            ("Yabancı dil müdürü kim?", "Eyyüp TUNCER"),
        ]
        for question, expected_name in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)
                self.assertIsNotNone(result)
                self.assertIn(expected_name, result["response"])

    def test_belirsiz_saglik_kisa_adi_birim_ister(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Sağlık dekanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi birimin", result["response"])

    def test_yonetim_kurulu_sorusu_kurul_uyelerini_listeler(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Tıp Fakültesi yönetim kurulunda kimler var?")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("fakülte yönetim kurulu", response)
        self.assertIn("İbrahim Halil TÜRKBEYLER", response)
        self.assertIn("Aliye BULUT", response)
        self.assertNotIn("Dahili: 0000", response)

    def test_birim_turune_gore_ust_yonetici_unvani_yorumlanir(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        myo_result = service.answer_chat_query("Teknik Bilimler MYO dekanı kim?")
        school_result = service.answer_chat_query("Yabancı Diller Yüksekokulu dekanı kim?")
        faculty_result = service.answer_chat_query("Mühendislik müdürü kim?")

        self.assertIsNotNone(myo_result)
        self.assertIn("Teknik Bilimler Meslek Yüksekokulu müdürü", myo_result["response"])
        self.assertIn("İpek ATİK", myo_result["response"])
        self.assertNotIn("dekanı", myo_result["response"].splitlines()[0])
        self.assertIsNotNone(school_result)
        self.assertIn("Yabancı Diller Yüksekokulu müdürü", school_result["response"])
        self.assertIn("Eyyüp TUNCER", school_result["response"])
        self.assertIsNotNone(faculty_result)
        self.assertIn("Mühendislik ve Doğa Bilimleri Fakültesi dekanı", faculty_result["response"])
        self.assertIn("Osman BİLGİN", faculty_result["response"])

    def test_birim_turune_gore_yardimci_ve_sekreter_unvanlari_yorumlanir(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        assistant_result = service.answer_chat_query("Teknik Bilimler MYO dekan yardımcısı kim?")
        secretary_result = service.answer_chat_query("TBMYO fakülte sekreteri kim?")
        faculty_assistant_result = service.answer_chat_query("Mühendislik müdür yardımcısı kim?")

        self.assertIsNotNone(assistant_result)
        self.assertIn("Teknik Bilimler Meslek Yüksekokulu müdür yardımcıları", assistant_result["response"])
        self.assertIn("Ayşe TOPRAK", assistant_result["response"])
        self.assertIsNotNone(secretary_result)
        self.assertIn("Teknik Bilimler Meslek Yüksekokulu sekreteri", secretary_result["response"])
        self.assertIn("Ahmet DEMİR", secretary_result["response"])
        self.assertIsNotNone(faculty_assistant_result)
        self.assertIn(
            "Mühendislik ve Doğa Bilimleri Fakültesi dekan yardımcıları",
            faculty_assistant_result["response"],
        )
        self.assertIn("Ali AYTEK", faculty_assistant_result["response"])

    def test_myo_kurul_unvani_birim_turune_gore_yorumlanir(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Teknik Bilimler MYO yüksekokul kurulu kimlerden oluşur?")

        self.assertIsNotNone(result)
        self.assertIn("Teknik Bilimler Meslek Yüksekokulu MYO kurulu", result["response"])
        self.assertIn("İpek ATİK", result["response"])

    def test_veri_yoksa_tahminsiz_not_found_doner(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Mühendislik bölüm başkanı kim?")

        self.assertIsNotNone(result)
        self.assertIn("mevcut kaynakta bulunamadı", result["response"])

    def test_birim_belirsizse_rag_fallback_yapmadan_birim_ister(self):
        service = UnitManagementService(FakeUnitManagementRepository())

        result = service.answer_chat_query("Dekan kim?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi birimin", result["response"])


if __name__ == "__main__":
    unittest.main()
