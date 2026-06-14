"""Birim yönetim scraper birim testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers import scheduler  # noqa: E402
from scrapers.unit_management_scraper import (  # noqa: E402
    TARGET_BY_ID,
    UnitManagementScrapeReport,
    build_validation_report,
    is_allowed_management_url,
    parse_management_page,
)


SAMPLE_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Dekanlık</div>
      <div class="row"></div>
      <div class="row">
        <div class="card">
          <div class="card-action">
            <ul>
              <li class="adsoyad truncate">Prof. Dr. Mahsum AYTEPE</li>
              <li class="unvan">Dekan</li>
              <li class="dahili"><i class="material-icons">ring_volume</i>2100</li>
              <li class="mail truncate"><i class="material-icons">mail</i>mahsum.aytepe@gibtu.edu.tr</li>
              <li class="blog"><a href="http://pbs.gibtu.edu.tr/mahsum.aytepe">Blog Sayfam</a></li>
            </ul>
          </div>
        </div>
      </div>
      <div class="birim_modul_baslik">Dekan Yardımcıları</div>
      <div class="row"></div>
      <div class="row">
        <div class="card">
          <div class="card-action">
            <ul>
              <li class="adsoyad truncate">Dr. Öğr. Üyesi Sıbğatullah İĞDE</li>
              <li class="unvan">Dekan Yrd.</li>
              <li class="dahili"><i class="material-icons">ring_volume</i>0000</li>
              <li class="mail truncate"><i class="material-icons">mail</i>sibgatullah.igde@gibtu.edu.tr</li>
              <li class="blog"><a href="http://pbs.gibtu.edu.tr/sibgatullah.igde">Blog Sayfam</a></li>
            </ul>
          </div>
        </div>
        <div class="card">
          <div class="card-action">
            <ul>
              <li class="adsoyad truncate">Kamil VURMAN</li>
              <li class="unvan">Fakülte Sekreteri</li>
              <li class="dahili"><i class="material-icons">ring_volume</i>2106</li>
              <li class="mail truncate"><i class="material-icons">mail</i>kamil.vurman@gibtu.edu.tr</li>
              <li class="blog"><a href="/personel/kamil">Blog Sayfam</a></li>
            </ul>
          </div>
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
      <div class="birim_modul_baslik">Yönetim Kurulu</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Ayşe ELKOCA</li>
            <li class="dahili"><i class="material-icons">ring_volume</i>2404</li>
            <li class="mail truncate"><i class="material-icons">mail</i>ayse.elkoca@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


DUPLICATE_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Fakülte Kurulu</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Prof. Dr. Osman BİLGİN</li>
            <li class="unvan">Başkan</li>
            <li class="dahili">2201</li>
            <li class="mail truncate">osman.bilgin@gibtu.edu.tr</li>
          </ul>
        </div>
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Prof. Dr. Osman BİLGİN</li>
            <li class="unvan">Başkan</li>
            <li class="dahili">2201</li>
            <li class="mail truncate">osman.bilgin@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


class UnitManagementScraperTests(unittest.TestCase):
    def test_allowlist_sadece_birim_yonetim_hedeflerini_kabul_eder(self):
        self.assertTrue(is_allowed_management_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15"))
        self.assertTrue(is_allowed_management_url("https://www.gibtu.edu.tr/birimyonetim.aspx?id=31"))
        self.assertFalse(is_allowed_management_url("http://www.gibtu.edu.tr/BirimYonetim.aspx?id=15"))
        self.assertFalse(is_allowed_management_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15&foo=bar"))
        self.assertFalse(is_allowed_management_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=12"))
        self.assertFalse(is_allowed_management_url("https://www.gibtu.edu.tr/duyuru.pdf"))
        self.assertFalse(is_allowed_management_url("https://example.com/BirimYonetim.aspx?id=15"))

    def test_grup_ve_kart_sirasi_turkce_karakterlerle_parse_edilir(self):
        target = TARGET_BY_ID[11]
        snapshot, groups, members = parse_management_page(
            SAMPLE_HTML,
            target,
            target.source_url,
            "run-1",
        )

        self.assertEqual(snapshot.parse_status, "ok")
        self.assertEqual([group.group_title for group in groups], ["Dekanlık", "Dekan Yardımcıları"])
        self.assertEqual(len(members), 3)
        self.assertEqual(members[0].full_name, "Mahsum AYTEPE")
        self.assertEqual(members[0].academic_title, "Prof. Dr.")
        self.assertEqual(members[0].role, "Dekan")
        self.assertEqual(members[0].phone_extension, "2100")
        self.assertEqual(members[0].email, "mahsum.aytepe@gibtu.edu.tr")
        self.assertEqual(members[1].full_name, "Sıbğatullah İĞDE")
        self.assertEqual(members[1].parse_status, "partial")
        self.assertEqual(members[2].profile_url, "https://www.gibtu.edu.tr/personel/kamil")
        self.assertEqual([member.page_order for member in members], [1, 2, 3])

    def test_eksik_gorev_needs_review_olarak_raporlanir(self):
        target = TARGET_BY_ID[21]
        snapshot, groups, members = parse_management_page(
            MISSING_ROLE_HTML,
            target,
            target.source_url,
            "run-2",
        )

        self.assertEqual(snapshot.parse_status, "partial")
        self.assertEqual(members[0].parse_status, "needs_review")
        report = UnitManagementScrapeReport(
            scrape_run_id="run-2",
            target_url_count=1,
            snapshots=[snapshot],
            groups=groups,
            members=members,
        )
        validation = build_validation_report(report)
        self.assertEqual(len(validation["missing_role_records"]), 1)
        self.assertEqual(len(validation["needs_review_records"]), 1)

    def test_duplicate_kayit_validation_raporuna_duser(self):
        target = TARGET_BY_ID[15]
        snapshot, groups, members = parse_management_page(
            DUPLICATE_HTML,
            target,
            target.source_url,
            "run-3",
        )
        report = UnitManagementScrapeReport(
            scrape_run_id="run-3",
            target_url_count=1,
            snapshots=[snapshot],
            groups=groups,
            members=members,
        )

        validation = build_validation_report(report)

        self.assertEqual(len(validation["duplicate_records"]), 1)

    def test_scheduler_yonetim_manual_job_anahtarini_tanimlar(self):
        self.assertIn("yonetim", scheduler.JOB_RUNNERS)
        self.assertEqual(scheduler.UNIT_MANAGEMENT_UPDATE_HOUR, 2)
        self.assertEqual(scheduler.UNIT_MANAGEMENT_UPDATE_MINUTE, 30)


if __name__ == "__main__":
    unittest.main()
