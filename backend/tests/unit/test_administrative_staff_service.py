"""İdari birim/personel DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.administrative_staff_service import AdministrativeStaffService  # noqa: E402


class FakeAdministrativeRepository:
    def __init__(self) -> None:
        self.units = [
            self._parent(11, "İlahiyat Fakültesi", "faculty", "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=11", ["ilahiyat"]),
            self._parent(15, "Mühendislik ve Doğa Bilimleri Fakültesi", "faculty", "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15", ["mdbf", "mühendislik"]),
            self._parent(20, "Tıp Fakültesi", "faculty", "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=20", ["tip", "tıp"]),
            self._parent(21, "Sağlık Bilimleri Fakültesi", "faculty", "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=21", ["sbf", "sağlık bilimleri"]),
            self._parent(22, "İktisadi İdari ve Sosyal Bilimler Fakültesi", "faculty", "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=22", ["iibf", "iisbf", "iktisadi idari"]),
            self._parent(24, "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "faculty", "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=24", ["gsmf", "güzel sanatlar"]),
            self._parent(31, "Sağlık Hizmetleri Meslek Yüksekokulu", "vocational_school", "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=31", ["shmyo", "sağlık hizmetleri myo"]),
            self._parent(36, "Teknik Bilimler Meslek Yüksekokulu", "vocational_school", "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=36", ["tbmyo", "teknik bilimler myo"]),
            self._parent(34, "Yabancı Diller Yüksekokulu", "school", "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=34", ["ydyo", "yabancı diller"]),
        ]
        self.admin_units = {
            11: [
                self._unit(11, "Fakülte Sekreteri", 1),
                self._unit(11, "Öğrenci İşleri", 2),
            ],
            15: [
                self._unit(15, "Fakülte Sekreterliği", 1),
                self._unit(15, "Destek Hizmetler", 2),
            ],
            20: [
                self._unit(20, "Fakülte Sekreteri", 1),
                self._unit(20, "Öğrenci İşleri", 2),
            ],
            21: [self._unit(21, "Fakülte Sekreteri", 1)],
            22: [
                self._unit(22, "Fakülte Sekreterliği", 1),
                self._unit(22, "Memur", 2),
            ],
            24: [
                self._unit(24, "Fakülte Sekreteri", 1),
                self._unit(24, "Bilgisayar İşletmeni", 2),
            ],
            31: [
                self._unit(31, "Yüksekokul Sekreteri", 1),
                self._unit(31, "Öğrenci İşleri", 2),
            ],
            36: [
                self._unit(36, "Yüksekokul Sekreteri", 1),
                self._unit(36, "İdari", 2),
            ],
            34: [
                self._unit(34, "Yüksekokul Sekreterliği", 1),
                self._unit(34, "İdari", 2),
            ],
        }
        self.staff = {
            11: [
                self._staff(11, "Fakülte Sekreteri", "Kamil VURMAN", "Fakülte Sekreteri", "2106", "kamil.vurman@gibtu.edu.tr", 1),
                self._staff(11, "Öğrenci İşleri", "Hüseyin ALP", "Bilgisayar İşletmeni", "2143", "huseyin.alp@gibtu.edu.tr", 2),
            ],
            15: [
                self._staff(15, "Fakülte Sekreterliği", "Ergün ÖZUSLU", "Fakülte Sekreteri", "2206", "ergun.ozuslu@gibtu.edu.tr", 1),
                self._staff(15, "Fakülte Sekreterliği", "Faruk DURMUŞ", "Şef", "2260", "faruk.durmus@gibtu.edu.tr", 2),
                self._staff(15, "Fakülte Sekreterliği", "Kerim KALKAN", "Bilgisayar İşletmeni", "2261", "kerim.kalkan@gibtu.edu.tr", 3),
            ],
            20: [
                self._staff(20, "Fakülte Sekreteri", "Fevzi ALTUNTAŞ", "Fakülte Sekreteri", "2302", "fevzi.altuntas@gibtu.edu.tr", 1),
                self._staff(20, "Öğrenci İşleri", "Sevgi KAYABAŞI", "Memur", "2332", "sevgi.topal@gibtu.edu.tr", 2),
            ],
            21: [
                self._staff(21, "Fakülte Sekreteri", "Abdulvahap ASLAN", "Fakülte Sekreteri", "2402", "abdulvehap.aslan@gibtu.edu.tr", 1),
            ],
            22: [
                self._staff(22, "Fakülte Sekreterliği", "Ümmügülsüm ÇELİK", "Fakülte Sekreteri", "1062", "ummugulsum.celik@gibtu.edu.tr", 1),
                self._staff(22, "Memur", "Fatma Nur ÖZTEKİN", "Memur", "1063", "fatmanur.oztekin@gibtu.edu.tr", 2),
            ],
            24: [
                self._staff(24, "Fakülte Sekreteri", "Abdullah KESKİN", "Fakülte Sekreteri", "2605", "abdullah.keskin@gibtu.edu.tr", 1),
                self._staff(24, "Bilgisayar İşletmeni", "Hakkı ŞAHİNALP", "Bilgisayar İşletmeni", "2606", "hakki.sahinalp@gibtu.edu.tr", 2),
            ],
            31: [
                self._staff(31, "Yüksekokul Sekreteri", "Mehmet Ali EKİNCİOĞLU", "Yüksekokul Sekreteri", "3033", "mehmetali.ekincioglu@gibtu.edu.tr", 1),
                self._staff(31, "Öğrenci İşleri", "Meryem YİĞİT", "Memur", "3034", "meryem.ekinci@gibtu.edu.tr", 2),
            ],
            36: [
                self._staff(36, "Yüksekokul Sekreteri", "Tuncay ŞAHAN", "Yüksekokul Sekreteri", "3102", "tuncay.sahan@gibtu.edu.tr", 1),
                self._staff(36, "İdari", "Mehmet DEMİROK", "Bilgisayar İşletmeni", "3105", "mehmet.demirok@gibtu.edu.tr", 2),
                self._staff(36, "İdari", "Mehmet Şerif YEŞİLMEN", "Tekniker", "3106", "mehmetserif.yesilmen@gibtu.edu.tr", 3),
            ],
            34: [
                self._staff(34, "Yüksekokul Sekreterliği", "Mehmet ÖZTÜRK", "Yüksekokul Sekreteri", "1051", "mehmet.ozturk@gibtu.edu.tr", 1),
                self._staff(34, "İdari", "İrem YILDIZOĞLU", "Memur", "1060", "irem.yildizoglu@gibtu.edu.tr", 2),
                self._staff(34, "İdari", "Mehmet GÖK", "Hizmetli", None, "mehmet.gok@gibtu.edu.tr", 3),
            ],
        }

    def list_parent_units(self):
        return list(self.units)

    def get_administrative_units(self, website_unit_id):
        return list(self.admin_units.get(website_unit_id, []))

    def get_administrative_staff(self, website_unit_id, administrative_unit_keys=None):
        rows = list(self.staff.get(website_unit_id, []))
        if administrative_unit_keys:
            keys = set(administrative_unit_keys)
            rows = [row for row in rows if row["administrative_unit_key"] in keys]
        return rows

    @staticmethod
    def _parent(website_unit_id, name, unit_type, source_url, aliases):
        return {
            "website_unit_id": website_unit_id,
            "parent_unit_name": name,
            "parent_unit_type": unit_type,
            "source_url": source_url,
            "last_seen_at": "2026-06-16T12:00:00Z",
            "aliases": aliases,
        }

    @staticmethod
    def _unit(website_unit_id, name, order_index):
        return {
            "id": f"unit-{website_unit_id}-{order_index}",
            "website_unit_id": website_unit_id,
            "administrative_unit_name": name,
            "administrative_unit_key": name.lower().replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ı", "i").replace("ö", "o").replace("ç", "c"),
            "order_index": order_index,
        }

    @staticmethod
    def _staff(website_unit_id, admin_unit, name, role, extension, email, order_index):
        source_urls = {
            11: "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=11",
            15: "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15",
            20: "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=20",
            21: "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=21",
            22: "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=22",
            24: "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=24",
            31: "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=31",
            36: "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=36",
            34: "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=34",
        }
        unit_key = admin_unit.lower().replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ı", "i").replace("ö", "o").replace("ç", "c")
        return {
            "staff_id": f"staff-{website_unit_id}-{order_index}",
            "administrative_unit_id": f"unit-{website_unit_id}-{unit_key}",
            "website_unit_id": website_unit_id,
            "source_url": source_urls[website_unit_id],
            "administrative_unit_name": admin_unit,
            "administrative_unit_key": unit_key,
            "stable_staff_key": f"email:{email}",
            "person_name": name,
            "person_name_normalized": name.lower(),
            "title_or_role": role,
            "email": email,
            "phone": None,
            "internal_extension": extension,
            "last_seen_at": "2026-06-16T12:00:00Z",
            "parse_status": "partial" if extension is None else "ok",
            "validation_issues": ["placeholder_internal_extension_0000"] if extension is None else [],
        }


class AdministrativeStaffServiceTests(unittest.TestCase):
    def test_ornek_sorgular_db_first_yanitlanir(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())
        cases = [
            ("MDBF idari personeli kim?", "Ergün ÖZUSLU"),
            ("muhendislik idari birimleri", "Fakülte Sekreterliği"),
            ("ilahiyat sekreterlik telefonu", "Dahili 2106"),
            ("tip fakultesi idari personel", "Fevzi ALTUNTAŞ"),
            ("SHMYO idari birimler", "Yüksekokul Sekreteri"),
            ("tbmyo idari personeli", "Tuncay ŞAHAN"),
            ("ydyo memur bilgileri", "İrem YILDIZOĞLU"),
            ("gsmf sekreterlik", "Abdullah KESKİN"),
            ("iktisadi idari sosyal bilimler idari personeli", "Ümmügülsüm ÇELİK"),
            ("öğrenci işleri kim mühendislik", "kaynak sayfada bulunamadı"),
            ("fakülte sekreteri kim ilahiyat", "Kamil VURMAN"),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)
                self.assertIsNotNone(result)
                self.assertIn(expected, result["response"])

    def test_saglik_kisa_sorgusu_netlestirme_ister(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("saglik idari personel")

        self.assertIsNotNone(result)
        self.assertIn("netleştirir misiniz", result["response"])
        self.assertIn("Sağlık Bilimleri Fakültesi", result["response"])
        self.assertIn("Sağlık Hizmetleri Meslek Yüksekokulu", result["response"])

    def test_bilinmeyen_birim_rag_fallback_yapmadan_birim_ister(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("idari personel kim?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi fakülte/yüksekokul", result["response"])

    def test_telefon_yoksa_kaynakta_yer_almiyor_der(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("ydyo idari personel telefonu")

        self.assertIsNotNone(result)
        self.assertIn("Mehmet GÖK", result["response"])
        self.assertIn("Telefon: Kaynakta dahili 0000 görünüyor; geçerli telefon belirtilmemiş.", result["response"])

    def test_idari_olmayan_yonetim_sorusu_none_doner(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Mühendislik fakültesi dekanı kim?")

        self.assertIsNone(result)

    def test_dis_hekimligi_allowlist_disina_yakin_birime_eslesmez(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Diş Hekimliği Fakültesi sekreterlik telefonu nedir?")

        self.assertIsNotNone(result)
        self.assertIn("veritabanında bulunamadı", result["response"])
        self.assertNotIn("İlahiyat Fakültesi", result["response"])

    def test_hukuk_fakultesi_kapsam_disi_veri_yok_der(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Hukuk Fakültesi idari personeli kim?")

        self.assertIsNotNone(result)
        self.assertIn("veritabanında bulunamadı", result["response"])
        self.assertNotIn("Hangi fakülte/yüksekokul", result["response"])

    def test_tip_yonetim_idari_personel_admin_intent_yanitlanir(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Tıp fakültesinin yönetim/idari personel bilgilerini göster.")

        self.assertIsNotNone(result)
        self.assertIn("Tıp Fakültesi idari personel", result["response"])
        self.assertIn("Fevzi ALTUNTAŞ", result["response"])

    def test_muhendislik_idari_islere_kim_bakiyor_admin_intent_yanitlanir(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Mühendislik fakültesinde idari işlere kim bakıyor?")

        self.assertIsNotNone(result)
        self.assertIn("Mühendislik ve Doğa Bilimleri Fakültesi", result["response"])
        self.assertIn("Ergün ÖZUSLU", result["response"])

    def test_guzel_sanatlar_memur_bilgileri_genel_idari_personel_doner(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("Güzel Sanatlar Fakültesi memur bilgileri var mı?")

        self.assertIsNotNone(result)
        self.assertIn("Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", result["response"])
        self.assertIn("Abdullah KESKİN", result["response"])
        self.assertIn("Hakkı ŞAHİNALP", result["response"])
        self.assertNotIn("bulunamadı", result["response"])

    def test_yanit_teknik_scrape_tarihi_gostermez(self):
        service = AdministrativeStaffService(FakeAdministrativeRepository())

        result = service.answer_chat_query("MDBF idari personeli kim?")

        self.assertIsNotNone(result)
        self.assertNotIn("Son scrape tarihi", result["response"])
        self.assertNotIn("snapshot", result["response"].casefold())
        self.assertNotIn("hash", result["response"].casefold())


if __name__ == "__main__":
    unittest.main()
