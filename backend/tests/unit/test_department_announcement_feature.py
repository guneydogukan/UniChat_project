"""Mühendislik bölüm duyuruları DB-first modülü testleri."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from psycopg2 import OperationalError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.repositories.department_announcement_repository import (  # noqa: E402
    DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL,
    REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES,
    ensure_department_announcement_schema,
)
from app.services.department_announcement_intent import extract_department_announcement_request
from app.services.department_announcement_service import DepartmentAnnouncementService
from scrapers.department_announcement_scraper import (
    DepartmentAnnouncementScrapeResult,
    DepartmentAnnouncementScraper,
    DepartmentAnnouncementSource,
    ScrapedDepartmentAnnouncement,
)


SOURCE = DepartmentAnnouncementSource(
    unit_id=18,
    department_code="bilgisayar_muhendisligi",
    department_name="Bilgisayar Mühendisliği",
    source_url="https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=18",
    source_id="11111111-1111-1111-1111-111111111111",
)


LISTING_HTML = """
<html><body>
  <table class="duyuru_listele">
    <tr><th>Başlık</th><th>Yayın Tarihi</th></tr>
    <tr>
      <td class="left-align">
        <a href="BirimIcerik.aspx?id=18&amp;icid=33616" target="_blank">
          <span>2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi</span>
        </a>
      </td>
      <td>04.06.2026</td>
    </tr>
    <tr>
      <td><a href="BirimIcerik.aspx?id=16&amp;icid=999">Yanlış bölüm</a></td>
      <td>05.06.2026</td>
    </tr>
    <tr>
      <td><a href="BirimDuyuruArsivi.aspx?id=18">Arşiv</a></td>
      <td>05.06.2026</td>
    </tr>
  </table>
</body></html>
"""


DETAIL_HTML = """
<html><body>
  <span class="icerik_baslik">
    <span id="ctl00_CPH_Sayfa_Body_lbl_baslik">2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi</span>
  </span>
  <span class="icerik_tarih left">
    <span id="ctl00_CPH_Sayfa_Body_lbl_tarih">04.06.2026 16:37</span>
  </span>
  <span class="icerik_detay">
    Revize edilmiş final sınav takvimine erişmek için
    <a href="https://www.gibtu.edu.tr/Medya/Birim/Dosya/final.pdf">tıklayınız.</a>
    <script>ignored()</script>
  </span>
</body></html>
"""


class DepartmentAnnouncementScraperTests(unittest.TestCase):
    def test_liste_sadece_hedef_bolum_duyuru_detay_linklerini_alir(self):
        scraper = DepartmentAnnouncementScraper(sources=[SOURCE], retry_delay_seconds=0)

        listed = scraper.parse_listing_html(LISTING_HTML, SOURCE)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].title, "2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi")
        self.assertEqual(listed[0].list_date_text, "04.06.2026")
        self.assertEqual(
            listed[0].detail_url,
            "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=33616",
        )

    def test_detay_baslik_tarih_icerik_ve_pdf_ekini_cikarir(self):
        scraper = DepartmentAnnouncementScraper(sources=[SOURCE], retry_delay_seconds=0)
        listed = scraper.parse_listing_html(LISTING_HTML, SOURCE)[0]

        announcement = scraper.parse_detail_html(DETAIL_HTML, listed)

        self.assertEqual(announcement.title, "2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi")
        self.assertEqual(announcement.announcement_date, date(2026, 6, 4))
        self.assertIn("Revize edilmiş final sınav takvimine", announcement.content)
        self.assertEqual(announcement.attachments[0]["file_extension"], "pdf")
        self.assertEqual(announcement.attachments[0]["text"], "tıklayınız.")

    def test_iso_8859_9_encoding_onceliklidir(self):
        class FakeResponse:
            headers = {"content-type": "text/html; charset=iso-8859-9"}
            url = "https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=18"
            encoding = "windows-1250"
            apparent_encoding = "windows-1250"

        response = FakeResponse()
        DepartmentAnnouncementScraper._apply_response_encoding(response)

        self.assertEqual(response.encoding, "iso-8859-9")


class DepartmentAnnouncementIntentTests(unittest.TestCase):
    def test_bolum_ve_konu_aliaslarini_yakalar(self):
        cases = [
            ("bilgisayar müh. final programı", "bilgisayar_muhendisligi", "final_exam"),
            ("Bilgisayar mühendisliği final programı açıklandı mı?", "bilgisayar_muhendisligi", "final_exam"),
            ("BMB bütünleme takvimi var mı?", "bilgisayar_muhendisligi", "makeup_exam"),
            ("bütler açıklandı mı", None, "makeup_exam"),
            ("ara sınav tarihleri açıklandı mı", None, "midterm_exam"),
            ("eem yaz okulu duyurusu", "elektrik_elektronik_muhendisligi", "summer_school"),
            ("Elektrik elektronik müh yaz okulu duyurusu", "elektrik_elektronik_muhendisligi", "summer_school"),
            ("eem yaz stajı işlemleri açıklandı mı", "elektrik_elektronik_muhendisligi", "internship"),
            ("endüstri proje sergisi", "endustri_muhendisligi", "project_exhibition"),
            ("Endüstri müh. mazeret sınav takvimi açıklandı mı?", "endustri_muhendisligi", "excuse_exam"),
        ]

        for query, department, topic in cases:
            with self.subTest(query=query):
                request = extract_department_announcement_request(query)
                self.assertTrue(request.is_announcement_query)
                if department:
                    self.assertIn(department, request.department_codes)
                self.assertIn(topic, request.topic_tags)

    def test_genel_vize_ne_zaman_takvim_fallback_icin_duyuru_sayilmaz(self):
        request = extract_department_announcement_request("vize ne zaman")

        self.assertFalse(request.is_announcement_query)
        self.assertTrue(request.calendar_fallback_preferred)

    def test_surec_ve_form_sorulari_duyuru_intenti_sayilmaz(self):
        non_announcement_queries = [
            "ders programı iş akışı",
            "ders programı nasıl hazırlanır?",
            "mazeret sınavı formu",
            "final notuma itiraz nasıl yapılır?",
        ]

        for query in non_announcement_queries:
            with self.subTest(query=query):
                request = extract_department_announcement_request(query)
                self.assertFalse(request.is_announcement_query)


class FakeRepository:
    def __init__(self, search_records=None, production_by_url=None):
        self.sources = [
            {
                "id": SOURCE.source_id,
                "unit_id": SOURCE.unit_id,
                "department_code": SOURCE.department_code,
                "department_name": SOURCE.department_name,
                "source_url": SOURCE.source_url,
            }
        ]
        self.production_by_url = production_by_url or {}
        self.search_records = search_records or []
        self.staged = []
        self.runs = {}
        self.approved = []
        self.rejected = []

    def get_active_sources(self):
        return self.sources

    def create_scrape_run(self, scrape_run_id, source_count, config=None):
        self.runs[scrape_run_id] = {"scrape_run_id": scrape_run_id, "source_count": source_count}
        return self.runs[scrape_run_id]

    def update_scrape_run(self, scrape_run_id, **kwargs):
        self.runs[scrape_run_id].update(kwargs)
        return self.runs[scrape_run_id]

    def find_production_by_detail_url(self, detail_url):
        return self.production_by_url.get(detail_url)

    def stage_announcement(self, **kwargs):
        row = {
            "id": f"stage-{len(self.staged) + 1}",
            "scrape_run_id": kwargs["scrape_run_id"],
            **kwargs["announcement"],
            "validation_status": kwargs["validation_status"],
            "validation_issues": kwargs["validation_issues"],
            "intent_tags": kwargs["intent_tags"],
            "status": "pending",
        }
        self.staged.append(row)
        return row

    def list_staging(self, status=None, scrape_run_id=None, limit=100):
        rows = self.staged
        if status:
            rows = [row for row in rows if row["status"] == status]
        if scrape_run_id:
            rows = [row for row in rows if row["scrape_run_id"] == scrape_run_id]
        return rows[:limit]

    def approve_staging(self, staging_id, reviewed_by=None, review_note=None):
        row = next(item for item in self.staged if item["id"] == staging_id)
        row["status"] = "approved"
        self.approved.append(row)
        return {"staging": row, "production": {"id": f"prod-{staging_id}"}}

    def reject_staging(self, staging_id, reviewed_by=None, review_note=None):
        row = next(item for item in self.staged if item["id"] == staging_id)
        row["status"] = "rejected"
        self.rejected.append(row)
        return row

    def search_announcements(self, department_codes=None, limit=150):
        if not department_codes:
            return self.search_records[:limit]
        return [row for row in self.search_records if row["department_code"] in department_codes][:limit]

    def get_status(self):
        return {
            "schema_ready": True,
            "missing_tables": [],
            "active_source_count": len(self.sources),
            "production_count": len(self.search_records),
            "pending_staging_count": len([row for row in self.staged if row["status"] == "pending"]),
            "last_scrape_run": list(self.runs.values())[-1] if self.runs else None,
        }


class RaisingSearchRepository(FakeRepository):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def search_announcements(self, department_codes=None, limit=150):
        raise self.exc


class FakePgError(Exception):
    def __init__(self, pgcode):
        super().__init__(pgcode)
        self.pgcode = pgcode


class FakeScraper:
    announcements = []

    def __init__(self, sources):
        self.sources = sources

    def scrape(self):
        return DepartmentAnnouncementScrapeResult(
            success=True,
            announcements=list(self.announcements),
            source_count=len(self.sources),
            listing_count=len(self.announcements),
            detail_count=len(self.announcements),
        )


def _announcement(**overrides):
    data = {
        "unit_id": 18,
        "department_code": "bilgisayar_muhendisligi",
        "department_name": "Bilgisayar Mühendisliği",
        "title": "2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi",
        "announcement_date": date(2026, 6, 4),
        "published_at": None,
        "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=33616",
        "content": "Final sınav takvimine erişmek için tıklayınız.",
        "attachments": [],
        "content_hash": "hash-final",
    }
    data.update(overrides)
    return ScrapedDepartmentAnnouncement(**data)


class DepartmentAnnouncementServiceTests(unittest.TestCase):
    def test_scrape_sadece_staginge_yazar_ve_duplicate_production_kaydini_atlar(self):
        announcement = _announcement()
        FakeScraper.announcements = [announcement]
        repo = FakeRepository(production_by_url={announcement.detail_url: {"content_hash": announcement.content_hash}})
        service = DepartmentAnnouncementService(repo, scraper_factory=FakeScraper)

        result = service.scrape_to_staging()

        self.assertTrue(result["success"])
        self.assertEqual(result["staged"], 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(repo.staged, [])

    def test_validation_hatasi_staging_kaydinda_gorunur(self):
        FakeScraper.announcements = [
            _announcement(content="", announcement_date=None, content_hash="hash-invalid")
        ]
        repo = FakeRepository()
        service = DepartmentAnnouncementService(repo, scraper_factory=FakeScraper)

        result = service.scrape_to_staging()

        self.assertEqual(result["staged"], 1)
        self.assertEqual(repo.staged[0]["validation_status"], "invalid")
        self.assertIn("content_too_short", repo.staged[0]["validation_issues"])
        self.assertIn("missing_or_unparsed_date", repo.staged[0]["validation_issues"])

    def test_run_onayi_sadece_valid_pending_kayitlari_onaylar(self):
        FakeScraper.announcements = [
            _announcement(),
            _announcement(
                detail_url="https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=2",
                content="",
                announcement_date=None,
                content_hash="hash-invalid",
            ),
        ]
        repo = FakeRepository()
        service = DepartmentAnnouncementService(repo, scraper_factory=FakeScraper)
        scrape_result = service.scrape_to_staging()

        approve_result = service.approve_run(scrape_result["scrape_run_id"])

        self.assertEqual(approve_result["approved_count"], 1)
        self.assertEqual(approve_result["skipped_count"], 1)

    def test_chat_sorgusu_db_first_yanit_doner(self):
        repo = FakeRepository(
            search_records=[
                {
                    "department_code": "bilgisayar_muhendisligi",
                    "department_name": "Bilgisayar Mühendisliği",
                    "title": "2025-2026 Bahar Dönemi Lisans Final Sınav Takvimi",
                    "announcement_date": "2026-06-04",
                    "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=33616",
                    "content": "Final sınav takvimine erişmek için tıklayınız.",
                    "intent_tags": ["final_exam"],
                    "search_text": "bilgisayar muhendisligi final sinav takvimi",
                }
            ]
        )
        service = DepartmentAnnouncementService(repo, scraper_factory=FakeScraper)

        answer = service.answer_chat_query("bilgisayar müh. final programı")

        self.assertIsNotNone(answer)
        self.assertIn("Final Sınav Takvimi", answer["response"])
        self.assertEqual(answer["sources"][0]["doc_kind"], "department_announcement")

    def test_explicit_duyuru_eslesme_yoksa_kontrollu_not_found_doner(self):
        service = DepartmentAnnouncementService(FakeRepository(), scraper_factory=FakeScraper)

        result = service.answer_chat_query("bilgisayar müh. final programı")

        self.assertIsNotNone(result)
        self.assertIn("onaylı bölüm duyurusu bulunamadı", result["response"])
        self.assertFalse(result["metadata"]["rag_fallback_used"])
        self.assertIsNone(service.answer_chat_query("vize ne zaman"))

    def test_tablo_eksikse_schema_missing_metadata_ile_kontrollu_yanit_doner(self):
        service = DepartmentAnnouncementService(RaisingSearchRepository(FakePgError("42P01")), scraper_factory=FakeScraper)

        result = service.answer_chat_query("bilgisayar mühendisliği final programı açıklandı mı?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["error_type"], "schema_missing")
        self.assertEqual(result["metadata"]["intent"], "schema_missing")
        self.assertIn("duyuru veritabanı şeması henüz hazır değil", result["response"])
        self.assertFalse(result["metadata"]["rag_fallback_used"])

    def test_db_baglanti_hatasi_db_connection_error_metadata_ile_doner(self):
        service = DepartmentAnnouncementService(RaisingSearchRepository(OperationalError("connection refused")), scraper_factory=FakeScraper)

        result = service.answer_chat_query("EEM ara sınav tarihleri açıklandı mı?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["error_type"], "db_connection_error")
        self.assertIn("duyuru veritabanına şu anda bağlanılamıyor", result["response"])

    def test_sorgu_hatasi_query_failed_metadata_ile_doner(self):
        service = DepartmentAnnouncementService(RaisingSearchRepository(FakePgError("99999")), scraper_factory=FakeScraper)

        result = service.answer_chat_query("endüstri bütünleme programı yayınlandı mı?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["error_type"], "query_failed")
        self.assertIn("duyuru veritabanı şu anda okunamadı", result["response"])

    def test_schema_hazir_ama_production_bossa_db_unavailable_donmez(self):
        service = DepartmentAnnouncementService(FakeRepository(), scraper_factory=FakeScraper)

        result = service.answer_chat_query("BMB duyurularını listele")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "department_announcement_not_found")
        self.assertNotIn("error_type", result["metadata"])
        self.assertIn("onaylı bölüm duyurusu kaydı bulunamadı", result["response"])

    def test_son_duyurular_en_guncel_kayitlari_listeler(self):
        records = [
            {
                "department_code": "bilgisayar_muhendisligi",
                "department_name": "Bilgisayar Mühendisliği",
                "title": f"Duyuru {index}",
                "announcement_date": f"2026-06-{index:02d}",
                "detail_url": f"https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid={index}",
                "content": f"Duyuru {index} içeriği",
                "intent_tags": [],
                "search_text": "bilgisayar muhendisligi duyuru",
            }
            for index in range(1, 7)
        ]
        service = DepartmentAnnouncementService(FakeRepository(search_records=records), scraper_factory=FakeScraper)

        result = service.answer_chat_query("son bilgisayar mühendisliği duyuruları neler?")

        self.assertIsNotNone(result)
        self.assertEqual(len(result["sources"]), 5)
        self.assertIn("Duyuru 6", result["response"])
        self.assertNotIn("Duyuru 1", result["response"])

    def test_bolum_filtresi_kati_kalir_baska_bolumden_yanit_donmez(self):
        records = [
            {
                "department_code": "elektrik_elektronik_muhendisligi",
                "department_name": "Elektrik-Elektronik Mühendisliği",
                "title": "Elektrik Elektronik Proje Sergisi",
                "announcement_date": "2026-05-23",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=16&icid=1",
                "content": "Proje sergisi duyurusu",
                "intent_tags": ["project_exhibition"],
                "search_text": "elektrik elektronik proje sergisi",
            }
        ]
        service = DepartmentAnnouncementService(FakeRepository(search_records=records), scraper_factory=FakeScraper)

        result = service.answer_chat_query("endüstri proje sergisi duyurusu")

        self.assertIsNotNone(result)
        self.assertIn("Endüstri Mühendisliği proje sergisi duyurusu için onaylı bölüm duyurusu bulunamadı", result["response"])
        self.assertEqual(result["sources"], [])

    def test_konu_filtresi_kati_kalir_alakasiz_ayni_bolum_kaydi_donmez(self):
        records = [
            {
                "department_code": "endustri_muhendisligi",
                "department_name": "Endüstri Mühendisliği",
                "title": "Endüstri Mühendisi Stajyeri İlanı",
                "announcement_date": "2026-04-07",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=19&icid=33239",
                "content": "Stajyer ilanı ve başvuru bilgileri.",
                "intent_tags": ["internship"],
                "search_text": "endustri muhendisligi staj ilan internship",
            }
        ]
        service = DepartmentAnnouncementService(FakeRepository(search_records=records), scraper_factory=FakeScraper)

        result = service.answer_chat_query("endüstri ders programı açıklandı mı?")

        self.assertIsNotNone(result)
        self.assertEqual(result["metadata"]["intent"], "department_announcement_not_found")
        self.assertEqual(result["sources"], [])

    def test_son_duyurular_tarihe_gore_siralanir(self):
        records = [
            {
                "department_code": "bilgisayar_muhendisligi",
                "department_name": "Bilgisayar Mühendisliği",
                "title": "Eski Çok Alakalı Duyuru",
                "announcement_date": "2026-01-01",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=1",
                "content": "bilgisayar duyuru güncel son duyuru",
                "intent_tags": [],
                "search_text": "bilgisayar muhendisligi duyuru guncel son",
            },
            {
                "department_code": "bilgisayar_muhendisligi",
                "department_name": "Bilgisayar Mühendisliği",
                "title": "Yeni Duyuru",
                "announcement_date": "2026-06-20",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=18&icid=2",
                "content": "Yeni kayıt.",
                "intent_tags": [],
                "search_text": "bilgisayar muhendisligi duyuru",
            },
        ]
        service = DepartmentAnnouncementService(FakeRepository(search_records=records), scraper_factory=FakeScraper)

        result = service.answer_chat_query("son bilgisayar mühendisliği duyuruları neler?")

        self.assertIsNotNone(result)
        self.assertLess(result["response"].find("Yeni Duyuru"), result["response"].find("Eski Çok Alakalı Duyuru"))

    def test_konulu_son_duyurular_tarihe_gore_siralanir(self):
        records = [
            {
                "department_code": "endustri_muhendisligi",
                "department_name": "Endüstri Mühendisliği",
                "title": "Eski Staj İlanı",
                "announcement_date": "2026-04-07",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=19&icid=1",
                "content": "Staj ilanı.",
                "intent_tags": ["internship"],
                "search_text": "endustri muhendisligi staj internship",
            },
            {
                "department_code": "endustri_muhendisligi",
                "department_name": "Endüstri Mühendisliği",
                "title": "Yeni Yaz Stajı Duyurusu",
                "announcement_date": "2026-06-15",
                "detail_url": "https://www.gibtu.edu.tr/BirimIcerik.aspx?id=19&icid=2",
                "content": "Yaz stajı duyurusu.",
                "intent_tags": ["internship"],
                "search_text": "endustri muhendisligi yaz staji internship",
            },
        ]
        service = DepartmentAnnouncementService(FakeRepository(search_records=records), scraper_factory=FakeScraper)

        result = service.answer_chat_query("endüstri staj duyuruları neler?")

        self.assertIsNotNone(result)
        self.assertLess(result["response"].find("Yeni Yaz Stajı Duyurusu"), result["response"].find("Eski Staj İlanı"))

    def test_status_production_pending_ve_bos_veri_durumlarini_ayirir(self):
        ready_repo = FakeRepository(search_records=[{"department_code": "bilgisayar_muhendisligi"}])
        ready = DepartmentAnnouncementService(ready_repo, scraper_factory=FakeScraper).get_status()
        self.assertTrue(ready["schema_ready"])
        self.assertEqual(ready["data_state"], "ready")
        self.assertIsNone(ready["last_error_type"])

        pending_repo = FakeRepository()
        pending_repo.staged.append({"id": "stage-1", "status": "pending"})
        pending = DepartmentAnnouncementService(pending_repo, scraper_factory=FakeScraper).get_status()
        self.assertEqual(pending["data_state"], "approval_pending")
        self.assertEqual(pending["last_error_type"], "no_approved_data")

        empty = DepartmentAnnouncementService(FakeRepository(), scraper_factory=FakeScraper).get_status()
        self.assertEqual(empty["data_state"], "no_approved_data")

    def test_status_db_hatasini_kontrollu_ozete_cevirir(self):
        class RaisingStatusRepository(FakeRepository):
            def get_status(self):
                raise FakePgError("42P01")

        status = DepartmentAnnouncementService(RaisingStatusRepository(), scraper_factory=FakeScraper).get_status()

        self.assertFalse(status["schema_ready"])
        self.assertEqual(status["last_error_type"], "schema_missing")
        self.assertEqual(status["data_state"], "unavailable")
        self.assertEqual(status["missing_tables"], list(REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES))


class DepartmentAnnouncementIntegrationShapeTests(unittest.TestCase):
    def test_sql_semasi_ve_seedler_mevcut(self):
        root_init = Path(__file__).resolve().parents[3] / "database" / "init.sql"
        backend_init = Path(__file__).resolve().parent.parent.parent / "database" / "init_db.py"

        root_sql = root_init.read_text(encoding="utf-8")
        backend_sql = backend_init.read_text(encoding="utf-8")

        for sql_text in (root_sql, backend_sql):
            self.assertIn("CREATE TABLE IF NOT EXISTS department_announcement_sources", sql_text)
            self.assertIn("CREATE TABLE IF NOT EXISTS department_announcement_staging", sql_text)
            self.assertIn("CREATE TABLE IF NOT EXISTS department_announcements", sql_text)
            self.assertIn("https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=18", sql_text)
            self.assertIn("https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=16", sql_text)
            self.assertIn("https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=19", sql_text)

    def test_startup_bootstrap_sql_sadece_duyuru_tablolarini_kapsar(self):
        for table in REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL)

        self.assertIn("ON CONFLICT (unit_id) DO UPDATE", DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_department_announcements_search", DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL)
        forbidden_fragments = [
            "CREATE TABLE IF NOT EXISTS food_menus",
            "CREATE TABLE IF NOT EXISTS chat_logs",
            "CREATE TABLE IF NOT EXISTS classrooms",
            "CREATE TABLE IF NOT EXISTS yokatlas_",
            "CREATE TABLE IF NOT EXISTS academic_",
            "CREATE TABLE IF NOT EXISTS program_catalog_",
            "CREATE TABLE IF NOT EXISTS workflows",
        ]
        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL)

    def test_ensure_schema_connect_timeout_ve_idempotent_sql_kullanir(self):
        calls = []

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                calls.append((sql, params))

        class FakeConnection:
            def __init__(self):
                self.committed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return FakeCursor()

            def commit(self):
                self.committed = True

        with patch("app.repositories.department_announcement_repository.psycopg2.connect", return_value=FakeConnection()) as connect:
            result = ensure_department_announcement_schema("postgresql://example/db", connect_timeout=2)

        connect.assert_called_once_with("postgresql://example/db", connect_timeout=2)
        executed_sql = "\n".join(sql for sql, _ in calls)
        self.assertTrue(result["schema_ready"])
        self.assertIn("CREATE TABLE IF NOT EXISTS department_announcements", executed_sql)
        self.assertIn("ON CONFLICT (unit_id) DO UPDATE", executed_sql)
        self.assertIn("SET statement_timeout", executed_sql)

    def test_main_startup_duyuru_bootstrap_cagrisini_icerir(self):
        main_py = Path(__file__).resolve().parents[2] / "main.py"
        main_text = main_py.read_text(encoding="utf-8")

        self.assertIn("ensure_department_announcement_schema", main_text)
        self.assertIn("connect_timeout=3", main_text)
        self.assertIn("Duyuru tabloları doğrulanamadı/oluşturulamadı", main_text)

    def test_status_endpoint_service_ozetini_doner(self):
        from app.routers.department_announcements import get_department_announcement_status

        class FakeStatusService:
            def get_status(self):
                return {
                    "schema_ready": True,
                    "active_source_count": 3,
                    "production_count": 7,
                    "pending_staging_count": 2,
                    "last_scrape_run": {"scrape_run_id": "run-1"},
                    "last_error_type": None,
                }

        with patch(
            "app.routers.department_announcements.get_department_announcement_service",
            return_value=FakeStatusService(),
        ):
            result = asyncio.run(get_department_announcement_status())

        self.assertTrue(result["schema_ready"])
        self.assertEqual(result["active_source_count"], 3)
        self.assertEqual(result["production_count"], 7)

    def test_rag_pipeline_duyuru_fast_path_kullanir(self):
        from app.services.rag_service import RagService

        class FakeDepartmentAnnouncementService:
            def answer_chat_query(self, question):
                return {"response": "DB duyuru yanıtı", "sources": []}

        with patch(
            "app.services.rag_service.get_department_announcement_service",
            return_value=FakeDepartmentAnnouncementService(),
        ):
            service = RagService()
            result = service.query("bilgisayar final programı açıklandı mı?")

        self.assertEqual(result["response"], "DB duyuru yanıtı")

    def test_rag_pipeline_duyuru_not_found_ile_fallbacki_keser(self):
        from app.services.rag_service import RagService

        class NullService:
            def answer_chat_query(self, question):
                return None

        class RaisingWorkflowService:
            def should_preempt_calendar(self, question):
                raise AssertionError("Duyuru sorgusu workflow preempt'e gitmemeli")

            def answer_chat_query(self, question):
                raise AssertionError("Duyuru sorgusu workflow'a gitmemeli")

        class RaisingCalendarService:
            def answer_chat_query(self, question):
                raise AssertionError("Duyuru sorgusu akademik takvime gitmemeli")

        department_service = DepartmentAnnouncementService(FakeRepository(), scraper_factory=FakeScraper)

        with (
            patch("app.services.rag_service.get_classroom_location_service", return_value=NullService()),
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_department_announcement_service", return_value=department_service),
            patch("app.services.rag_service.get_workflow_service", return_value=RaisingWorkflowService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=RaisingCalendarService()),
        ):
            result = RagService().query("Endüstri mühendisliği final programı")

        self.assertEqual(result["metadata"]["service"], "department_announcement_service")
        self.assertEqual(result["metadata"]["intent"], "department_announcement_not_found")

    def test_genel_tarih_sorusu_akademik_takvimde_kalir(self):
        from app.services.rag_service import RagService

        class NullService:
            def answer_chat_query(self, question):
                return None

        class WorkflowService:
            def should_preempt_calendar(self, question):
                return False

            def answer_chat_query(self, question):
                return None

        class CalendarService:
            def answer_chat_query(self, question):
                return {"response": "takvim yanıtı", "sources": [], "metadata": {"service": "academic_calendar"}}

        with (
            patch("app.services.rag_service.get_classroom_location_service", return_value=NullService()),
            patch("app.services.rag_service.get_food_menu_service", return_value=NullService()),
            patch("app.services.rag_service.get_department_announcement_service", return_value=DepartmentAnnouncementService(FakeRepository(), scraper_factory=FakeScraper)),
            patch("app.services.rag_service.get_workflow_service", return_value=WorkflowService()),
            patch("app.services.rag_service.get_academic_calendar_service", return_value=CalendarService()),
        ):
            result = RagService().query("vize ne zaman?")

        self.assertEqual(result["metadata"]["service"], "academic_calendar")


if __name__ == "__main__":
    unittest.main()
