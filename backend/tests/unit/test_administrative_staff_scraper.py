"""İdari birim/personel scraper birim testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers import scheduler  # noqa: E402
from scrapers.administrative_staff_scraper import (  # noqa: E402
    TARGET_BY_ID,
    AdministrativeScrapeReport,
    AdministrativeStaffScraper,
    build_validation_report,
    is_allowed_administrative_url,
    parse_administrative_page,
    _decode_response,
)


BIRIMLER_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <ul class="collapsible">
        <li>
          <div class="collapsible-header"> Fakülte Sekreterliği <i class="material-icons">keyboard_arrow_right</i></div>
          <div class="collapsible-body">
            <div class="row">
              <div class="card">
                <ul>
                  <li class="adsoyad truncate"> Ergün ÖZUSLU</li>
                  <li class="unvan truncate">Fakülte Sekreteri</li>
                  <li class="dahili"><i class="material-icons">ring_volume</i>2206</li>
                  <li class="mail truncate"><i class="material-icons">mail</i>ergun.ozuslu@gibtu.edu.tr</li>
                </ul>
              </div>
              <div class="card">
                <ul>
                  <li class="adsoyad truncate"> Faruk DURMUŞ</li>
                  <li class="unvan truncate">Şef</li>
                  <li class="dahili"><i class="material-icons">ring_volume</i>0000</li>
                  <li class="mail truncate"><i class="material-icons">mail</i>faruk.durmus@gibtu.edu.tr</li>
                </ul>
              </div>
            </div>
          </div>
        </li>
        <li>
          <div class="collapsible-header"> Destek Hizmetler <i class="material-icons">keyboard_arrow_right</i></div>
          <div class="collapsible-body"></div>
        </li>
      </ul>
    </div>
  </div>
</body></html>
"""


PERSONEL_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik"> Fakülte Sekreterliği </div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate"> Ümmügülsüm ÇELİK</li>
            <li class="unvan truncate">Fakülte Sekreteri</li>
            <li class="dahili"><i class="material-icons">ring_volume</i>1062</li>
            <li class="mail truncate"><i class="material-icons">mail</i>ummugulsum.celik@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
      <div class="birim_modul_baslik"> Memur </div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate"> Fatma Nur ÖZTEKİN</li>
            <li class="unvan truncate">Memur</li>
            <li class="dahili"><i class="material-icons">ring_volume</i>1063</li>
            <li class="mail truncate"><i class="material-icons">mail</i>fatmanur.oztekin@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


MISSING_ROLE_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <ul class="collapsible">
        <li>
          <div class="collapsible-header">İdari Personel</div>
          <div class="collapsible-body">
            <div class="card">
              <ul>
                <li class="adsoyad truncate"> Ayşe TEST</li>
                <li class="dahili">2400</li>
                <li class="mail truncate">ayse.test@gibtu.edu.tr</li>
              </ul>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </div>
</body></html>
"""


class FakeResponse:
    def __init__(self, content: bytes, encoding: str = "utf-8", apparent_encoding: str = "cp775") -> None:
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class FakeAdministrativeRepository:
    last_instance = None

    def __init__(self) -> None:
        FakeAdministrativeRepository.last_instance = self
        self.staff_ids = []
        self.deactivate_calls = []
        self.diff_summary = None

    def ensure_schema(self):
        self.schema_called = True

    def get_active_staff_keys(self):
        return {(15, "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=15"): {"fakulte sekreterligi|email:old@gibtu.edu.tr"}}

    def upsert_scrape_run(self, run):
        self.run = run

    def upsert_source_page(self, page):
        self.page = page

    def upsert_administrative_unit(self, unit):
        return "11111111-1111-1111-1111-111111111111"

    def upsert_administrative_staff(self, staff, administrative_unit_id):
        staff_id = f"22222222-2222-2222-2222-22222222222{len(self.staff_ids)}"
        self.staff_ids.append(staff_id)
        return staff_id

    def upsert_aliases(self, **kwargs):
        return len(kwargs.get("aliases") or [])

    def deactivate_staff_not_seen(self, website_unit_id, normalized_source_url, seen_staff_ids):
        self.deactivate_calls.append((website_unit_id, normalized_source_url, list(seen_staff_ids)))
        return 1

    def update_scrape_run_diff(self, scrape_run_id, diff_summary):
        self.diff_summary = diff_summary


class AdministrativeStaffScraperTests(unittest.TestCase):
    def test_allowlist_sadece_idari_hedefleri_kabul_eder(self):
        self.assertTrue(is_allowed_administrative_url("https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15"))
        self.assertTrue(is_allowed_administrative_url("https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=22"))
        self.assertFalse(is_allowed_administrative_url("http://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15"))
        self.assertFalse(is_allowed_administrative_url("https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15&foo=bar"))
        self.assertFalse(is_allowed_administrative_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15"))
        self.assertFalse(is_allowed_administrative_url("https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=11"))
        self.assertFalse(is_allowed_administrative_url("https://example.com/birimidaripersonel.aspx?id=22"))

    def test_birimler_sablonu_grup_personel_ve_bos_birim_parse_eder(self):
        target = TARGET_BY_ID[15]
        page, units, staff = parse_administrative_page(BIRIMLER_HTML, target, target.source_url, "run-1")

        self.assertEqual(page.parse_status, "partial")
        self.assertEqual([unit.administrative_unit_name for unit in units], ["Fakülte Sekreterliği", "Destek Hizmetler"])
        self.assertEqual(len(staff), 2)
        self.assertEqual(staff[0].person_name, "Ergün ÖZUSLU")
        self.assertEqual(staff[0].title_or_role, "Fakülte Sekreteri")
        self.assertEqual(staff[0].internal_extension, "2206")
        self.assertEqual(staff[0].email, "ergun.ozuslu@gibtu.edu.tr")
        self.assertEqual(staff[1].internal_extension, None)
        self.assertIn("placeholder_internal_extension_0000", staff[1].validation_issues)

    def test_personel_sablonu_birim_modul_baslik_ile_parse_edilir(self):
        target = TARGET_BY_ID[22]
        page, units, staff = parse_administrative_page(PERSONEL_HTML, target, target.source_url, "run-2")

        self.assertEqual(page.parse_status, "ok")
        self.assertEqual([unit.administrative_unit_name for unit in units], ["Fakülte Sekreterliği", "Memur"])
        self.assertEqual(len(staff), 2)
        self.assertEqual(staff[0].person_name, "Ümmügülsüm ÇELİK")
        self.assertEqual(staff[1].administrative_unit_name, "Memur")
        self.assertEqual(staff[1].email, "fatmanur.oztekin@gibtu.edu.tr")

    def test_iso_8859_9_decode_turkce_karakterleri_korur(self):
        response = FakeResponse("GİBTÜ - İlahiyat Fakültesi".encode("iso-8859-9"))

        text = _decode_response(response)

        self.assertIn("İlahiyat Fakültesi", text)
        self.assertNotIn("�", text)

    def test_validation_eksik_gorev_ve_duplicate_raporlar(self):
        target = TARGET_BY_ID[21]
        page, units, staff = parse_administrative_page(MISSING_ROLE_HTML, target, target.source_url, "run-3")
        staff.append(staff[0])
        report = AdministrativeScrapeReport(
            scrape_run_id="run-3",
            target_url_count=1,
            source_pages=[page],
            administrative_units=units,
            staff=staff,
        )

        validation = build_validation_report(report)

        self.assertEqual(len(validation["missing_role_records"]), 2)
        self.assertEqual(len(validation["needs_review_records"]), 2)
        self.assertEqual(len(validation["duplicate_records"]), 1)

    def test_db_import_diff_ve_deactivate_fake_repository_ile_calisir(self):
        target = TARGET_BY_ID[15]
        page, units, staff = parse_administrative_page(BIRIMLER_HTML, target, target.source_url, "run-4")
        report = AdministrativeScrapeReport(
            success=True,
            scrape_run_id="run-4",
            started_at="2026-06-16T12:00:00Z",
            finished_at="2026-06-16T12:01:00Z",
            target_url_count=1,
            source_pages=[page],
            administrative_units=units,
            staff=staff,
            validation_report={"warning_count": 1, "critical_count": 0},
        )
        scraper = AdministrativeStaffScraper(targets=(target,))

        with patch("app.repositories.administrative_repository.AdministrativeRepository", FakeAdministrativeRepository):
            summary = scraper.write_report_to_database(report)

        fake_repo = FakeAdministrativeRepository.last_instance
        self.assertEqual(summary["staff_upserted"], 2)
        self.assertEqual(summary["staff_deactivated"], 1)
        self.assertEqual(summary["diff_summary"]["new_count"], 2)
        self.assertEqual(summary["diff_summary"]["missing_count"], 1)
        self.assertTrue(fake_repo.deactivate_calls)

    def test_scheduler_idari_personel_manual_job_anahtarini_tanimlar(self):
        self.assertIn("idari_personel", scheduler.JOB_RUNNERS)
        self.assertEqual(scheduler.ADMINISTRATIVE_STAFF_UPDATE_HOUR, 2)
        self.assertEqual(scheduler.ADMINISTRATIVE_STAFF_UPDATE_MINUTE, 45)


if __name__ == "__main__":
    unittest.main()
