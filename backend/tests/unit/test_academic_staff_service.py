"""Akademik kadro DB-first servis testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.academic_staff_service import AcademicStaffService  # noqa: E402


class FakeAcademicRepository:
    def __init__(self) -> None:
        self.units = [
            {
                "id": "faculty-1",
                "unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name_normalized": "muhendislik ve doga bilimleri fakultesi",
                "unit_type": "faculty",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/view/universityView.jsp?id=1",
            },
            {
                "id": "dept-1",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
                "unit_name_normalized": "bilgisayar muhendisligi bolumu",
                "unit_type": "department",
                "parent_unit_id": "faculty-1",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
            },
            {
                "id": "dept-eee",
                "unit_name": "Elektrik-Elektronik Mühendisliği Bölümü",
                "unit_name_normalized": "elektrik elektronik muhendisligi bolumu",
                "unit_type": "department",
                "parent_unit_id": "faculty-1",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=eee",
            },
            {
                "id": "dept-endustri",
                "unit_name": "Endüstri Mühendisliği Bölümü",
                "unit_name_normalized": "endustri muhendisligi bolumu",
                "unit_type": "department",
                "parent_unit_id": "faculty-1",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=endustri",
            },
            {
                "id": "dept-endustri-en",
                "unit_name": "Endüstri Mühendisliği (İngilizce) Bölümü",
                "unit_name_normalized": "endustri muhendisligi ingilizce bolumu",
                "unit_type": "department",
                "parent_unit_id": "faculty-1",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=endustri-en",
            },
        ]
        self.staff = [
            {
                "person_id": "person-1",
                "full_name": "Ayşe YILMAZ",
                "normalized_name": "ayse yilmaz",
                "title": "Doç. Dr.",
                "person_source_status": "verified_from_kadro_veri",
                "source_status": "verified_from_kadro_veri",
                "confidence_status": "verified_from_kadro_veri",
                "confidence_score": 0.99,
                "needs_manual_review": False,
                "unit_id": "dept-1",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
                "unit_type": "department",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1",
                "last_checked_at": "2026-06-10T00:00:00Z",
                "external_profiles": [
                    {
                        "profile_type": "yok_akademik",
                        "profile_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1",
                        "external_id": "A1",
                        "raw_data": {
                            "kadro_parent_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
                            "kadro_department": "Bilgisayar Mühendisliği Bölümü",
                            "kadro_subunit": "Bilgisayar Mühendisliği Anabilim Dalı",
                        },
                    }
                ],
            }
        ]
        self.staff.extend([
            self._staff_member("person-2", "Tarık TALAN", "tarik talan", "Doç. Dr.", "dept-1", "T1"),
            self._staff_member("person-3", "Cemal AKTÜRK", "cemal akturk", "Doç. Dr.", "dept-1", "C1"),
            self._staff_member("person-4", "Bahadır BOZKURT", "bahadir bozkurt", "Dr. Öğr. Üyesi", "dept-1", "B1"),
            self._staff_member("person-5", "Mehmet KAYA", "mehmet kaya", "Dr. Öğr. Üyesi", "dept-eee", "E1"),
            self._staff_member("person-6", "Elif DEMİR", "elif demir", "Doç. Dr.", "dept-endustri", "EN1"),
        ])

    def list_units(self):
        return list(self.units)

    def get_child_units(self, parent_unit_id):
        return [unit for unit in self.units if unit.get("parent_unit_id") == parent_unit_id]

    def get_staff_by_unit(self, unit_id):
        return [person for person in self.staff if person.get("unit_id") == unit_id]

    def search_persons(self, normalized_query):
        return [
            person for person in self.staff
            if normalized_query in person.get("normalized_name", "")
        ]

    def add_unit_with_staff(self, unit_id, unit_name, unit_name_normalized, unit_type, parent_unit_name, staff_name):
        self.units.append(
            {
                "id": unit_id,
                "unit_name": unit_name,
                "unit_name_normalized": unit_name_normalized,
                "unit_type": unit_type,
                "parent_unit_id": "faculty-1",
                "parent_unit_name": parent_unit_name,
                "source_url": f"https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim={unit_id}",
            }
        )
        self.staff.append(
            self._staff_member(
                f"person-{unit_id}",
                staff_name,
                staff_name.lower().replace("ı", "i"),
                "Dr. Öğr. Üyesi",
                unit_id,
                unit_id.upper(),
                parent_unit_name=parent_unit_name,
            )
        )

    def add_unit_without_staff(
        self,
        unit_id,
        unit_name,
        unit_name_normalized,
        unit_type,
        parent_unit_id="faculty-1",
        parent_unit_name="Mühendislik ve Doğa Bilimleri Fakültesi",
        source_url="https://yokatlas.yok.gov.tr/detay/test",
    ):
        self.units.append(
            {
                "id": unit_id,
                "unit_name": unit_name,
                "unit_name_normalized": unit_name_normalized,
                "unit_type": unit_type,
                "parent_unit_id": parent_unit_id,
                "parent_unit_name": parent_unit_name,
                "source_url": source_url,
            }
        )

    def _staff_member(
        self,
        person_id,
        full_name,
        normalized_name,
        title,
        unit_id,
        external_id,
        parent_unit_name="Mühendislik ve Doğa Bilimleri Fakültesi",
    ):
        unit = next(item for item in self.units if item["id"] == unit_id)
        return {
            "person_id": person_id,
            "full_name": full_name,
            "normalized_name": normalized_name,
            "title": title,
            "person_source_status": "verified_from_kadro_veri",
            "source_status": "verified_from_kadro_veri",
            "confidence_status": "verified_from_kadro_veri",
            "confidence_score": 0.99,
            "needs_manual_review": False,
            "unit_id": unit_id,
            "unit_name": unit["unit_name"],
            "unit_type": unit["unit_type"],
            "parent_unit_name": parent_unit_name,
            "source_url": f"https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId={external_id}",
            "last_checked_at": "2026-06-10T00:00:00Z",
            "external_profiles": [
                {
                    "profile_type": "yok_akademik",
                    "profile_url": f"https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId={external_id}",
                    "external_id": external_id,
                    "raw_data": {
                        "kadro_parent_unit": parent_unit_name,
                        "kadro_department": unit["unit_name"],
                    },
                }
            ],
        }


class AcademicStaffServiceTests(unittest.TestCase):
    def test_bolum_kadrosu_dbden_yanitlanir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Bilgisayar mühendisliği akademik kadrosu kimlerden oluşuyor?")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("Bilgisayar Mühendisliği Bölümü akademik kadrosu", response)
        self.assertIn("Ayşe YILMAZ", response)
        self.assertIn("Kaynak: YÖK Akademik", response)
        self.assertIn("Son kontrol tarihi: 2026-06-10", response)
        self.assertNotIn("YÖK Atlas", response)

    def test_yazim_hatali_ve_kisa_kadro_sorulari_bilgisayar_bolumune_yonlenir(self):
        service = AcademicStaffService(FakeAcademicRepository())
        questions = [
            "bilgisaar mühendisliği akademik kadrosu",
            "bilgisaar müh kadro",
            "bilgisayar müh kadro",
            "bilgisayar hocaları",
            "bm akademik kadro",
            "bilgisayar mühendisliği kadro",
        ]

        for question in questions:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                self.assertIn("Bilgisayar Mühendisliği Bölümü akademik kadrosu", result["response"])
                self.assertIn("Ayşe YILMAZ", result["response"])

    def test_kisaltmali_ve_aliasli_bolum_sorulari_dogru_bolume_yonlenir(self):
        service = AcademicStaffService(FakeAcademicRepository())
        cases = [
            ("eee kadro", "Elektrik-Elektronik Mühendisliği Bölümü akademik kadrosu", "Mehmet KAYA"),
            ("elektrik müh akademik kadro", "Elektrik-Elektronik Mühendisliği Bölümü akademik kadrosu", "Mehmet KAYA"),
            ("endüstri bölümü kadro", "Endüstri Mühendisliği Bölümü akademik kadrosu", "Elif DEMİR"),
            ("endüstri mühendisliği bölümü kadro", "Endüstri Mühendisliği Bölümü akademik kadrosu", "Elif DEMİR"),
            ("em kadro", "Endüstri Mühendisliği Bölümü akademik kadrosu", "Elif DEMİR"),
        ]

        for question, expected_heading, expected_name in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                self.assertIn(expected_heading, result["response"])
                self.assertIn(expected_name, result["response"])
                self.assertIn("Kaynak: YÖK Akademik", result["response"])

    def test_dil_varyanti_olmayan_sorgu_taban_bolumu_secer(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Endüstri Mühendisliği kadro")

        self.assertIsNotNone(result)
        self.assertIn("Endüstri Mühendisliği Bölümü akademik kadrosu", result["response"])
        self.assertIn("Elif DEMİR", result["response"])
        self.assertNotIn("Bölüm/program seçimi gerekli", result["response"])

    def test_dil_varyanti_acikca_yazilirsa_o_birim_secilir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Endüstri Mühendisliği İngilizce kadro")

        self.assertIsNotNone(result)
        self.assertIn("Endüstri Mühendisliği (İngilizce) Bölümü akademik kadrosu", result["response"])
        self.assertIn("henüz veritabanında bulunmuyor", result["response"])
        self.assertNotIn("Endüstri Mühendisliği Bölümü akademik kadrosu\n- Elif DEMİR", result["response"])

    def test_yok_atlas_duplicate_yerine_staff_backed_yok_birimi_secilir(self):
        repository = FakeAcademicRepository()
        repository.add_unit_without_staff(
            "prog-ftr-atlas",
            "Fizyoterapi ve Rehabilitasyon",
            "fizyoterapi ve rehabilitasyon",
            "program",
            parent_unit_name="Sağlık Bilimleri Fakültesi",
        )
        repository.add_unit_with_staff(
            "prog-ftr-yok",
            "Fizyoterapi ve Rehabilitasyon Bölümü",
            "fizyoterapi ve rehabilitasyon bolumu",
            "program",
            "Sağlık Hizmetleri Meslek Yüksekokulu",
            "FTR Staff TEST",
        )
        service = AcademicStaffService(repository)

        for question in [
            "Fizyoterapi ve Rehabilitasyon akademik kadro",
            "Fizyoterapi ve Rehabilitasyon kadro",
            "fizyoterapi kadro",
        ]:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                self.assertIn("Fizyoterapi ve Rehabilitasyon Bölümü akademik kadrosu", result["response"])
                self.assertIn("FTR Staff TEST", result["response"])
                self.assertNotIn("Bölüm/program seçimi gerekli", result["response"])

    def test_tam_tip_bolumu_adi_ortak_tip_bilimleri_parcasi_yuzunden_belirsizlesmez(self):
        repository = FakeAcademicRepository()
        repository.add_unit_with_staff(
            "dept-cerrahi-tip",
            "Cerrahi Tıp Bilimleri Bölümü",
            "cerrahi tip bilimleri bolumu",
            "department",
            "Tıp Fakültesi",
            "Cerrahi Staff TEST",
        )
        repository.add_unit_with_staff(
            "dept-dahili-tip",
            "Dahili Tıp Bilimleri Bölümü",
            "dahili tip bilimleri bolumu",
            "department",
            "Tıp Fakültesi",
            "Dahili Staff TEST",
        )
        repository.add_unit_with_staff(
            "dept-temel-tip",
            "Temel Tıp Bilimleri Bölümü",
            "temel tip bilimleri bolumu",
            "department",
            "Tıp Fakültesi",
            "Temel Tıp TEST",
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("Cerrahi Tıp Bilimleri Bölümü kadro")

        self.assertIsNotNone(result)
        self.assertIn("Cerrahi Tıp Bilimleri Bölümü akademik kadrosu", result["response"])
        self.assertIn("Cerrahi Staff TEST", result["response"])
        self.assertNotIn("Bölüm/program seçimi gerekli", result["response"])

    def test_fakulte_seciminde_yokatlas_only_program_secenek_olarak_gosterilmez(self):
        repository = FakeAcademicRepository()
        repository.units.append(
            {
                "id": "faculty-tip",
                "unit_name": "Tıp Fakültesi",
                "unit_name_normalized": "tip fakultesi",
                "unit_type": "faculty",
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=tip",
            }
        )
        repository.add_unit_with_staff(
            "dept-cerrahi-tip",
            "Cerrahi Tıp Bilimleri Bölümü",
            "cerrahi tip bilimleri bolumu",
            "department",
            "Tıp Fakültesi",
            "Cerrahi Staff TEST",
        )
        repository.units[-1]["parent_unit_id"] = "faculty-tip"
        repository.add_unit_without_staff(
            "prog-tip-atlas",
            "Tıp",
            "tip",
            "program",
            parent_unit_id="faculty-tip",
            parent_unit_name="Tıp Fakültesi",
            source_url="https://yokatlas.yok.gov.tr/detay/111210046",
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("Tıp akademik kadro")

        self.assertIsNotNone(result)
        self.assertIn("Tıp Fakültesi için bölüm/program seçimi gerekli", result["response"])
        self.assertIn("Cerrahi Tıp Bilimleri Bölümü", result["response"])
        self.assertNotIn("Bilinen seçenekler: Cerrahi Tıp Bilimleri Bölümü, Tıp.", result["response"])

    def test_otomatik_aliaslar_katalogdaki_bolum_program_orneklerini_kapsar(self):
        repository = FakeAcademicRepository()
        parent_units = {
            "saglik": "Sağlık Bilimleri Fakültesi",
            "shmyo": "Sağlık Hizmetleri Meslek Yüksekokulu",
            "gstm": "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
            "ilahiyat": "İlahiyat Fakültesi",
            "iisbf": "İktisadi, İdari ve Sosyal Bilimler Fakültesi",
            "tip": "Tıp Fakültesi",
        }
        repository.add_unit_with_staff(
            "dept-insaat",
            "İnşaat Mühendisliği Bölümü",
            "insaat muhendisligi bolumu",
            "department",
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "İnşaat TEST",
        )
        repository.add_unit_with_staff(
            "dept-gastro",
            "Gastronomi ve Mutfak Sanatları Bölümü",
            "gastronomi ve mutfak sanatlari bolumu",
            "department",
            parent_units["gstm"],
            "Gastro TEST",
        )
        repository.add_unit_with_staff(
            "dept-hemsire",
            "Hemşirelik Bölümü",
            "hemsirelik bolumu",
            "department",
            parent_units["saglik"],
            "Hemşire TEST",
        )
        repository.add_unit_with_staff(
            "prog-lab",
            "Tıbbi Laboratuvar Teknikleri Programı",
            "tibbi laboratuvar teknikleri programi",
            "program",
            parent_units["shmyo"],
            "Laboratuvar TEST",
        )
        repository.add_unit_with_staff(
            "prog-ilk-acil",
            "İlk ve Acil Yardım Programı",
            "ilk ve acil yardim programi",
            "program",
            parent_units["shmyo"],
            "İlk Acil TEST",
        )
        repository.add_unit_with_staff(
            "prog-arapca-mutercim",
            "Arapça Mütercim ve Tercümanlık",
            "arapca mutercim ve tercumanlik",
            "program",
            parent_units["iisbf"],
            "Arapça Mütercim TEST",
        )
        repository.add_unit_with_staff(
            "prog-ilahiyat-mtok",
            "İlahiyat (Arapça) (M.T.O.K.)",
            "ilahiyat arapca m t o k",
            "program",
            parent_units["ilahiyat"],
            "İlahiyat MTOK TEST",
        )
        repository.add_unit_with_staff(
            "dept-temel-islam",
            "Temel İslam Bilimleri Bölümü",
            "temel islam bilimleri bolumu",
            "department",
            parent_units["ilahiyat"],
            "Temel İslam TEST",
        )
        repository.add_unit_with_staff(
            "dept-temel-tip",
            "Temel Tıp Bilimleri Bölümü",
            "temel tip bilimleri bolumu",
            "department",
            parent_units["tip"],
            "Temel Tıp TEST",
        )
        service = AcademicStaffService(repository)
        cases = [
            ("inşaat müh kadro", "İnşaat Mühendisliği Bölümü akademik kadrosu", "İnşaat TEST"),
            ("gastronomi kadro", "Gastronomi ve Mutfak Sanatları Bölümü akademik kadrosu", "Gastro TEST"),
            ("hemşirelik hocaları", "Hemşirelik Bölümü akademik kadrosu", "Hemşire TEST"),
            ("tıbbi laboratuvar kadro", "Tıbbi Laboratuvar Teknikleri Programı akademik kadrosu", "Laboratuvar TEST"),
            ("ilk acil yardım akademik kadro", "İlk ve Acil Yardım Programı akademik kadrosu", "İlk Acil TEST"),
            ("arapça mütercim akademisyenleri", "Arapça Mütercim ve Tercümanlık akademik kadrosu", "Arapça Mütercim TEST"),
            ("ilahiyat arapça mtok kadro", "İlahiyat (Arapça) (M.T.O.K.) akademik kadrosu", "İlahiyat MTOK TEST"),
            ("temel islam kadro", "Temel İslam Bilimleri Bölümü akademik kadrosu", "Temel İslam TEST"),
            ("temel tıp kadro", "Temel Tıp Bilimleri Bölümü akademik kadrosu", "Temel Tıp TEST"),
        ]

        for question, expected_heading, expected_name in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                self.assertIn(expected_heading, result["response"])
                self.assertIn(expected_name, result["response"])

    def test_genel_tek_kelime_arastirma_alani_programa_kesin_eslesmez(self):
        repository = FakeAcademicRepository()
        repository.add_unit_with_staff(
            "prog-makine",
            "Makine Programı",
            "makine programi",
            "program",
            "Teknik Bilimler Meslek Yüksekokulu",
            "Makine TEST",
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("makine öğrenmesi hocaları")

        self.assertIsNotNone(result)
        self.assertIn("Hangi bölüm veya program", result["response"])
        self.assertNotIn("Makine Programı akademik kadrosu", result["response"])

    def test_ayni_kisa_alias_birden_fazla_unitteyse_secim_istenir(self):
        repository = FakeAcademicRepository()
        repository.add_unit_with_staff(
            "prog-ftr",
            "Fizyoterapi ve Rehabilitasyon",
            "fizyoterapi ve rehabilitasyon",
            "program",
            "Sağlık Bilimleri Fakültesi",
            "FTR Program TEST",
        )
        repository.add_unit_with_staff(
            "dept-ftr-shmyo",
            "Fizyoterapi ve Rehabilitasyon Bölümü",
            "fizyoterapi ve rehabilitasyon bolumu",
            "program",
            "Sağlık Hizmetleri Meslek Yüksekokulu",
            "FTR Bölüm TEST",
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("fizyoterapi kadro")

        self.assertIsNotNone(result)
        self.assertIn("Bölüm/program seçimi gerekli", result["response"])
        self.assertIn("Fizyoterapi ve Rehabilitasyon", result["response"])
        self.assertIn("Fizyoterapi ve Rehabilitasyon Bölümü", result["response"])

    def test_akademisyen_kisi_sorgulari_dbden_kisa_yanitlanir(self):
        service = AcademicStaffService(FakeAcademicRepository())
        cases = [
            ("Tarık Talan kimdir", "Doç. Dr. Tarık TALAN"),
            ("tarik taln kim", "Doç. Dr. Tarık TALAN"),
            ("Cemal Aktürk hangi bölümde", "Doç. Dr. Cemal AKTÜRK"),
            ("Bahadır Bozkurt hoca kim", "Dr. Öğr. Üyesi Bahadır BOZKURT"),
        ]

        for question, expected_person in cases:
            with self.subTest(question=question):
                result = service.answer_chat_query(question)

                self.assertIsNotNone(result)
                response = result["response"]
                self.assertIn(expected_person, response)
                self.assertIn("Mühendislik ve Doğa Bilimleri Fakültesi", response)
                self.assertIn("Bilgisayar Mühendisliği Bölümü", response)
                self.assertIn("Kaynak: YÖK Akademik", response)
                self.assertIn("Son kontrol: 2026-06-10", response)

    def test_fakulte_sorusunda_bolum_program_secimi_istenir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Mühendislik ve Doğa Bilimleri Fakültesi akademik kadrosu")

        self.assertIsNotNone(result)
        self.assertIn("bölüm/program seçimi gerekli", result["response"].lower())
        self.assertIn("Bilgisayar Mühendisliği Bölümü", result["response"])

    def test_belirsiz_kadro_sorusu_rag_fallback_icin_none_donmez(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Akademik kadro listesini gösterir misin?")

        self.assertIsNotNone(result)
        self.assertIn("Hangi bölüm veya program", result["response"])

    def test_yonetim_sorusu_rag_akisina_birakilir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Bilgisayar mühendisliği bölüm başkanı kim?")

        self.assertIsNone(result)

    def test_dekan_sorusu_rag_akisina_birakilir(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Mühendislik fakültesi dekanı?")

        self.assertIsNone(result)

    def test_yakin_bolum_program_eslesmesinde_secim_istenir(self):
        repository = FakeAcademicRepository()
        repository.units.append(
            {
                "id": "program-1",
                "unit_name": "Bilgisayar Programcılığı Programı",
                "unit_name_normalized": "bilgisayar programciligi programi",
                "unit_type": "program",
                "parent_unit_id": "faculty-1",
                "aliases": ["bilgisayar"],
                "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=program",
            }
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("bilgisayar kadro")

        self.assertIsNotNone(result)
        self.assertIn("Bölüm/program seçimi gerekli", result["response"])
        self.assertIn("Bilgisayar Mühendisliği Bölümü", result["response"])
        self.assertIn("Bilgisayar Programcılığı Programı", result["response"])

    def test_yakin_kisi_eslesmesinde_secim_istenir(self):
        repository = FakeAcademicRepository()
        repository.staff.append(
            repository._staff_member("person-7", "Tarık TALANLI", "tarik talanli", "Dr. Öğr. Üyesi", "dept-1", "T2")
        )
        service = AcademicStaffService(repository)

        result = service.answer_chat_query("tarik tal kim")

        self.assertIsNotNone(result)
        self.assertIn("Şunu mu kastettiniz", result["response"])
        self.assertIn("Tarık TALAN", result["response"])
        self.assertIn("Tarık TALANLI", result["response"])

    def test_kisi_sorgusunda_dbde_veri_yoksa_rag_fallback_yapilmaz(self):
        service = AcademicStaffService(FakeAcademicRepository())

        result = service.answer_chat_query("Mehmet Uçar kimdir")

        self.assertIsNotNone(result)
        self.assertIn("henüz veritabanında bulunmuyor", result["response"])
        self.assertIn("Canlı scrape veya RAG tahmini yapılmadı", result["response"])


if __name__ == "__main__":
    unittest.main()
