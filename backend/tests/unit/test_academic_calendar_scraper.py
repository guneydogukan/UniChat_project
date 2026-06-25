"""Akademik takvim hedefli scraper birim testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.ingestion.loader import _generate_doc_id  # noqa: E402
from app.services.query_preprocessor import preprocess_query  # noqa: E402
from app.services.response_validator import PLACEHOLDER_ACADEMIC_DATE, validate_response  # noqa: E402
from app.services.academic_calendar_service import AcademicCalendarService, CalendarEventRecord  # noqa: E402
from scrapers.academic_calendar_scraper import (  # noqa: E402
    ACADEMIC_CALENDAR_URL,
    CalendarSource,
    AcademicCalendarScraper,
    HolidaySectionContext,
    parse_date_range,
)


SAMPLE_HTML = """
<html>
  <body>
    <nav>
      <a href="/Medya/GibtuDosya/menu_raporu.pdf">Menü PDF</a>
    </nav>
    <div class="page_header"><span class="page_title">Akademik Takvim</span></div>
    <div class="page_body">
      <div class="card">
        <div class="card-content">
          <object data="/Medya/GibtuDosya/20250724151936_6843460a.pdf" type="application/pdf">
            Dosyayı görüntüleyemiyorsanız,
            <a href="/Medya/GibtuDosya/20250724151936_6843460a.pdf">buradan indirebilirsiniz</a>
            <a href="https://get.adobe.com/reader/">Adobe PDF Reader</a>
          </object>
          <iframe src="Medya/GibtuDosya/20250724151936_6843460a.pdf"></iframe>
        </div>
      </div>
    </div>
  </body>
</html>
"""


class AcademicCalendarDiscoveryTests(unittest.TestCase):
    def test_ana_sayfa_icerik_pdfini_deduplicate_eder_nav_pdfini_almaz(self):
        scraper = AcademicCalendarScraper()

        sources = scraper.discover_calendar_sources(SAMPLE_HTML)

        self.assertEqual(len(sources), 1)
        self.assertEqual(
            sources[0].source_url,
            "https://www.gibtu.edu.tr/Medya/GibtuDosya/20250724151936_6843460a.pdf",
        )
        self.assertEqual(sources[0].source_type, "pdf")


class AcademicCalendarDateParserTests(unittest.TestCase):
    def test_turkce_tarih_araliklarini_parse_eder(self):
        self.assertEqual(
            parse_date_range("15-19 Eylül 2025"),
            ("2025-09-15", "2025-09-19", "15-19 Eylül 2025"),
        )
        self.assertEqual(
            parse_date_range("15 Eylül - 19 Eylül 2025"),
            ("2025-09-15", "2025-09-19", "15 Eylül - 19 Eylül 2025"),
        )
        self.assertEqual(
            parse_date_range("29 Mart - 1 Nisan 2025"),
            ("2025-03-29", "2025-04-01", "29 Mart - 1 Nisan 2025"),
        )
        self.assertEqual(
            parse_date_range("01.10.2025"),
            ("2025-10-01", "2025-10-01", "01.10.2025"),
        )


class AcademicCalendarEventTests(unittest.TestCase):
    def test_guz_bahar_tarihleri_ayri_event_olur(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )

        events = scraper._events_from_row(
            cells=["Ders kayıtları", "15-19 Eylül 2025", "02-06 Şubat 2026"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=7,
            inherited_term=None,
            header_cells=["Faaliyet", "Güz Yarıyılı", "Bahar Yarıyılı"],
            parser_confidence=0.86,
        )

        self.assertEqual(len(events), 2)
        self.assertEqual({event.term for event in events}, {"güz yarıyılı", "bahar yarıyılı"})
        self.assertTrue(all(event.event_category == "course_registration" for event in events))

    def test_document_metadata_structured_event_alanlarini_korur(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        event = scraper._events_from_row(
            cells=["Final sınavları", "05-16 Ocak 2026"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=2,
            row_index=3,
            inherited_term="güz yarıyılı",
            header_cells=[],
            parser_confidence=0.86,
        )[0]

        doc = scraper.event_to_document(event)

        self.assertEqual(doc.meta["doc_kind"], "academic_calendar_event")
        self.assertEqual(doc.meta["category"], "academic_calendar")
        self.assertEqual(doc.meta["academic_year"], "2025-2026")
        self.assertEqual(doc.meta["event_category"], "final_exam")
        self.assertEqual(doc.meta["source_page_url"], ACADEMIC_CALENDAR_URL)
        self.assertEqual(doc.meta["official_source"], True)
        self.assertIn("2025-2026", doc.content)

    def test_benzer_baslikli_farkli_tarihlerde_source_id_benzersizdir(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )

        first = scraper._events_from_row(
            cells=["Modül Çıkış Sınavı (Yazma/Konuşma/Test)", "12-14 Kasım 2025"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=21,
            inherited_term="güz yarıyılı",
            header_cells=[],
            parser_confidence=0.86,
        )[0]
        second = scraper._events_from_row(
            cells=["Modül Çıkış Sınavı (Yazma/Konuşma/Test)", "19-21 Ocak 2026"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=30,
            inherited_term="güz yarıyılı",
            header_cells=[],
            parser_confidence=0.86,
        )[0]

        first_doc = scraper.event_to_document(first)
        second_doc = scraper.event_to_document(second)

        self.assertNotEqual(first_doc.meta["source_id"], second_doc.meta["source_id"])

    def test_ayni_icerikli_farkli_satirlar_rag_id_ile_birbirini_ezmez(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        context = HolidaySectionContext(
            active=True,
            section_title="2025-2026 EĞİTİM ÖĞRETİM YILI RESMİ TATİL GÜNLERİ",
        )

        first = scraper._events_from_row(
            cells=["19 Mayıs 2026", "Atatürk’ü Anma, Gençlik ve Spor Bayramı"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=44,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )[0]
        second = scraper._events_from_row(
            cells=["19 Mayıs 2026", "Atatürk’ü Anma, Gençlik ve Spor Bayramı"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=5,
            row_index=17,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )[0]

        first_doc = scraper.event_to_document(first)
        second_doc = scraper.event_to_document(second)
        first_loader_id = _generate_doc_id(first_doc.content + first_doc.meta["source_id"] + "0")
        second_loader_id = _generate_doc_id(second_doc.content + second_doc.meta["source_id"] + "0")

        self.assertEqual(first_doc.content, second_doc.content)
        self.assertNotEqual(first_doc.meta["source_id"], second_doc.meta["source_id"])
        self.assertNotEqual(first_loader_id, second_loader_id)

    def test_turkce_buyuk_i_final_kategorisini_bozmaz(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )

        event = scraper._events_from_row(
            cells=["YARIYIL SONU (FİNAL) SINAVLARI", "15 Haziran 2026", "26 Haziran 2026"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=30,
            inherited_term="bahar yarıyılı",
            header_cells=["Başlangıç", "Bitiş", "Faaliyet"],
            parser_confidence=0.86,
        )[0]

        self.assertEqual(event.event_category, "final_exam")

    def test_resmi_tatil_header_ve_not_satiri_event_uretmez(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        context = HolidaySectionContext()

        header_events = scraper._events_from_row(
            cells=["2025-2026 EĞİTİM ÖĞRETİM YILI RESMİ TATİL GÜNLERİ"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=35,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )
        note_events = scraper._events_from_row(
            cells=["Not: Arife günleri öğleden sonra tatildir"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=51,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )

        self.assertEqual(header_events, [])
        self.assertEqual(note_events, [])
        self.assertTrue(context.active)
        self.assertEqual(context.section_note, "Arife günleri öğleden sonra tatildir")
        self.assertEqual(len(scraper._holiday_parse_audit["skipped_rows"]), 2)

    def test_resmi_tatil_satirlari_structured_holiday_event_olur(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        context = HolidaySectionContext(
            active=True,
            section_title="2025-2026 EĞİTİM ÖĞRETİM YILI RESMİ TATİL GÜNLERİ",
            section_note="Arife günleri öğleden sonra tatildir",
        )

        rows = [
            ["29 Ekim 2025", "Cumhuriyet Bayramı"],
            ["1 Ocak 2026", "Yılbaşı"],
            ["19 Mart 2026", "Ramazan Bayramı Arifesi"],
            ["20 Mart 2026", "Ramazan Bayramı 1.gün"],
        ]
        events = [
            scraper._events_from_row(
                cells=row,
                source=source,
                file_hash="abc123",
                checked_at="2026-05-31T00:00:00Z",
                parsed_at="2026-05-31T00:00:00Z",
                page_number=1,
                row_index=index,
                inherited_term="güz yarıyılı",
                header_cells=[],
                parser_confidence=0.86,
                holiday_context=context,
            )[0]
            for index, row in enumerate(rows, start=40)
        ]

        self.assertEqual([event.event_title for event in events], [
            "Cumhuriyet Bayramı",
            "Yılbaşı",
            "Ramazan Bayramı Arifesi",
            "Ramazan Bayramı 1.gün",
        ])
        self.assertTrue(all(event.event_category == "holiday" for event in events))
        self.assertTrue(all(event.term is None for event in events))
        self.assertEqual(events[0].start_date, "2025-10-29")
        self.assertEqual(events[1].start_date, "2026-01-01")
        self.assertEqual(events[2].note, "Arife günleri öğleden sonra tatildir")

    def test_spor_bayrami_devam_satiri_onceki_tatil_eventine_baglanir(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        context = HolidaySectionContext(
            active=True,
            section_title="2025-2026 EĞİTİM ÖĞRETİM YILI RESMİ TATİL GÜNLERİ",
        )

        events = scraper._events_from_row(
            cells=["19 Mayıs 2026", "Atatürk’ü Anma, Gençlik ve"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=5,
            row_index=18,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )
        weekday_events = scraper._events_from_row(
            cells=["Salı"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=5,
            row_index=18,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )
        continuation_events = scraper._events_from_row(
            cells=["Spor Bayramı"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=5,
            row_index=19,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )

        self.assertEqual(weekday_events, [])
        self.assertEqual(continuation_events, [])
        self.assertEqual(events[0].event_title, "Atatürk’ü Anma, Gençlik ve Spor Bayramı")
        self.assertEqual(events[0].start_date, "2026-05-19")
        self.assertEqual(events[0].merged_from_rows[0]["text"], "Spor Bayramı")
        self.assertEqual(len(scraper._holiday_parse_audit["merged_rows"]), 1)

    def test_resmi_tatil_temsil_metni_notu_korur(self):
        scraper = AcademicCalendarScraper()
        source = CalendarSource(
            source_url="https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
            source_type="pdf",
            academic_year="2025-2026",
        )
        context = HolidaySectionContext(
            active=True,
            section_title="2025-2026 EĞİTİM ÖĞRETİM YILI RESMİ TATİL GÜNLERİ",
            section_note="Arife günleri öğleden sonra tatildir",
        )
        event = scraper._events_from_row(
            cells=["19 Mart 2026", "Ramazan Bayramı Arifesi"],
            source=source,
            file_hash="abc123",
            checked_at="2026-05-31T00:00:00Z",
            parsed_at="2026-05-31T00:00:00Z",
            page_number=1,
            row_index=42,
            inherited_term=None,
            header_cells=[],
            parser_confidence=0.86,
            holiday_context=context,
        )[0]

        doc = scraper.event_to_document(event)

        self.assertIn("2025-2026 akademik takviminde 19 Mart 2026 Ramazan Bayramı Arifesi resmî tatildir.", doc.content)
        self.assertIn("Not: Arife günleri öğleden sonra tatildir.", doc.content)
        self.assertEqual(doc.meta["section_type"], "resmi_tatil")


class AcademicCalendarServiceSelectionTests(unittest.TestCase):
    def test_mazeretli_kayit_yenileme_tarih_sorgusu_mazeret_muracaat_tarihini_doner(self):
        service = AcademicCalendarService()
        service._load_events = lambda: [  # type: ignore[method-assign]
            CalendarEventRecord(
                content="2025-2026 genel akademik takvim öğrenci ders kayıtları",
                meta={
                    "doc_kind": "academic_calendar_event",
                    "category": "academic_calendar",
                    "academic_year": "2025-2026",
                    "calendar_type": "genel/önlisans-lisans",
                    "event_category": "course_registration",
                    "event_title": "Öğrenci Ders Kayıtları",
                    "term": "güz yarıyılı",
                    "start_date": "2025-09-08",
                    "end_date": "2025-09-14",
                    "original_date_text": "8 Eylül 2025 - 14 Eylül 2025",
                    "source_file_url": "https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
                    "confidence_score": 1.0,
                },
            ),
            CalendarEventRecord(
                content="Mazeretleri Nedeniyle Ders Kaydı Yaptıramayan Öğrencilerin Birimlerine Müracaat Tarihleri",
                meta={
                    "doc_kind": "academic_calendar_event",
                    "category": "academic_calendar",
                    "academic_year": "2025-2026",
                    "calendar_type": "genel/önlisans-lisans",
                    "event_category": "course_registration",
                    "event_title": "Mazeretleri Nedeniyle Ders Kaydı Yaptıramayan Öğrencilerin Birimlerine Müracaat Tarihleri",
                    "term": "güz yarıyılı",
                    "start_date": "2025-09-15",
                    "end_date": "2025-09-17",
                    "original_date_text": "15 Eylül 2025 - 17 Eylül 2025",
                    "source_file_url": "https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
                    "confidence_score": 1.0,
                },
            )
        ]

        result = service.answer_chat_query("Mazeretli kayıt yenileme tarihleri hangi gün bitiyor?")

        self.assertIsNotNone(result)
        self.assertIn("Mazeretleri Nedeniyle Ders Kaydı Yaptıramayan", result["response"])
        self.assertIn("15 Eylül 2025 - 17 Eylül 2025", result["response"])
        self.assertIn("Son gün: 17 Eylül 2025", result["response"])
        self.assertEqual(result["sources"][0]["doc_kind"], "academic_calendar_event")

    def test_kayit_dondurma_son_basvuru_tarihi_application_eventini_doner(self):
        service = AcademicCalendarService()
        service._load_events = lambda: [  # type: ignore[method-assign]
            CalendarEventRecord(
                content="Erasmus başvuru tarihleri",
                meta={
                    "doc_kind": "academic_calendar_event",
                    "category": "academic_calendar",
                    "academic_year": "2025-2026",
                    "calendar_type": "genel/önlisans-lisans",
                    "event_category": "application",
                    "event_title": "Erasmus Başvuru Tarihleri",
                    "term": "güz yarıyılı",
                    "start_date": "2025-08-01",
                    "end_date": "2025-08-10",
                    "original_date_text": "1 Ağustos 2025 - 10 Ağustos 2025",
                    "source_file_url": "https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
                    "confidence_score": 1.0,
                },
            ),
            CalendarEventRecord(
                content="Kayıt Dondurma Tarihleri",
                meta={
                    "doc_kind": "academic_calendar_event",
                    "category": "academic_calendar",
                    "academic_year": "2025-2026",
                    "calendar_type": "genel/önlisans-lisans",
                    "event_category": "application",
                    "event_title": "Kayıt Dondurma Tarihleri (Müracaatlar İlgili MYO/YO/Fakülte’ye yapılacaktır.)",
                    "term": "bahar yarıyılı",
                    "start_date": "2026-02-16",
                    "end_date": "2026-03-02",
                    "original_date_text": "16 Şubat 2026 - 2 Mart 2026",
                    "source_file_url": "https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
                    "confidence_score": 1.0,
                },
            ),
        ]

        result = service.answer_chat_query("Kayıt dondurma işlemi için son başvuru tarihi nedir?")

        self.assertIsNotNone(result)
        self.assertIn("Kayıt Dondurma Tarihleri", result["response"])
        self.assertIn("16 Şubat 2026 - 2 Mart 2026", result["response"])
        self.assertIn("Son gün: 2 Mart 2026", result["response"])
        self.assertNotIn("Erasmus", result["response"])

    def test_genel_basvuru_tarihleri_takvim_servisine_cekilmez(self):
        service = AcademicCalendarService()

        self.assertIsNone(service.answer_chat_query("Erasmus başvuru tarihleri ne zaman bitiyor?"))

    def test_belirsiz_final_sorgusunda_sonuc_ilani_yerine_ana_sinavlari_secer(self):
        service = AcademicCalendarService()
        main_exam = CalendarEventRecord(
            content="Ana final sınavları",
            meta={
                "event_category": "final_exam",
                "event_title": "YARIYIL SONU (FİNAL) SINAVLARI",
                "term": "bahar yarıyılı",
                "start_date": "2026-06-15",
                "end_date": "2026-06-26",
            },
        )
        result_announcement = CalendarEventRecord(
            content="Final sonuç ilanı",
            meta={
                "event_category": "final_exam",
                "event_title": "Yarıyıl sonu sınav sonuçlarının öğrenci otomasyon sistemine girilip ilan edilmesi",
                "term": "bahar yarıyılı",
                "start_date": "2026-06-15",
                "end_date": "2026-07-06",
            },
        )

        selected = service._select_answer_events(
            ranked=[(120, result_announcement), (119, main_exam)],
            requested_category="final_exam",
            requested_term="bahar yarıyılı",
        )

        self.assertEqual(selected, [main_exam])


class AcademicCalendarGuardrailTests(unittest.TestCase):
    def test_response_validator_kaynak_disi_takvim_tarihini_temizler(self):
        sources = [
            {
                "content": "2025-2026 genel/önlisans-lisans akademik takvimine göre final sınavları 05-16 Ocak 2026 tarihleri arasındadır.",
                "source_url": "https://www.gibtu.edu.tr/Medya/GibtuDosya/takvim.pdf",
                "meta": {
                    "doc_kind": "academic_calendar_event",
                    "category": "academic_calendar",
                    "academic_year": "2025-2026",
                    "original_date_text": "05-16 Ocak 2026",
                    "start_date": "2026-01-05",
                    "end_date": "2026-01-16",
                },
            }
        ]

        result = validate_response(
            "Final sınavları 05-16 Ocak 2026 tarihlerindedir. Ayrıca 20 Şubat 2026 da sınav vardır.",
            sources,
        )

        self.assertIn("05-16 Ocak 2026", result)
        self.assertNotIn("20 Şubat 2026", result)
        self.assertIn(PLACEHOLDER_ACADEMIC_DATE, result)

    def test_query_preprocessor_akademik_takvim_sorgusunu_genisletir(self):
        result = preprocess_query("Final ne zaman?")

        self.assertIn("yarıyıl sonu sınavı", result.keyword_query)
        self.assertIn("academic_calendar_event", result.keyword_query)
        self.assertIsNotNone(result.system_note)


if __name__ == "__main__":
    unittest.main()
