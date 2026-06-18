"""Alt birim yönetim scraper testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers.subunit_management_scraper import (  # noqa: E402
    DEFAULT_TARGETS,
    SubunitManagementScrapeReport,
    build_validation_report,
    is_allowed_subunit_management_url,
    parse_subunit_management_page,
)


def _target(birim_id: int):
    return next(target for target in DEFAULT_TARGETS if target.birim_id == birim_id)


MANAGEMENT_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Bölüm Başkanı</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Cemal AKTÜRK</li>
            <li class="unvan">Doç. Dr.</li>
            <li class="dahili"><i class="material-icons">ring_volume</i>2231</li>
            <li class="mail truncate"><i class="material-icons">mail</i>cemal.akturk@gibtu.edu.tr</li>
            <li class="blog"><a href="http://pbs.gibtu.edu.tr/cemal.akturk">Blog Sayfam</a></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


PARTIAL_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Bölüm Başkanlığı</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Prof. Dr. Mehmet Ali ÖZÇELİK</li>
            <li class="unvan">Bölüm Başkanı</li>
            <li class="dahili"><i class="material-icons">ring_volume</i>0000</li>
            <li class="mail truncate"><i class="material-icons">mail</i>mehmet.ozcelik@gibtu.edu.tr</li>
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
      <div class="birim_modul_baslik">Bölüm Başkanı</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Cemal AKTÜRK</li>
            <li class="unvan">Doç. Dr.</li>
            <li class="dahili">2231</li>
            <li class="mail truncate">cemal.akturk@gibtu.edu.tr</li>
          </ul>
        </div>
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Cemal AKTÜRK</li>
            <li class="unvan">Doç. Dr.</li>
            <li class="dahili">2231</li>
            <li class="mail truncate">cemal.akturk@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


NEEDS_REVIEW_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Yönetim</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Dr. Öğr. Üyesi Ayşe DEMİR</li>
            <li class="dahili">3001</li>
            <li class="mail truncate">ayse.demir@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


ACADEMIC_PERSONNEL_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Akademik</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Öğr. Gör. Aysun SÖYLEMEZ</li>
            <li class="unvan">Bölüm Başkan V.</li>
            <li class="dahili">3020</li>
            <li class="mail truncate">aysun.soylemez@gibtu.edu.tr</li>
          </ul>
        </div>
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Dr. Öğr. Üyesi Bengisu TÜFEKÇİ</li>
            <li class="unvan">Dr. Öğr. Üyesi</li>
            <li class="dahili">3022</li>
            <li class="mail truncate">bengisu.tufekci@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


OUT_OF_SCOPE_ROLE_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Dekan</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Prof. Dr. Şehmus DEMİR</li>
            <li class="unvan">Prof. Dr.</li>
            <li class="dahili">0000</li>
            <li class="mail truncate">sehmus.demir@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
      <div class="birim_modul_baslik">Bölüm Başkanı</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Cemal AKTÜRK</li>
            <li class="unvan">Doç. Dr.</li>
            <li class="dahili">2231</li>
            <li class="mail truncate">cemal.akturk@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


BASKAN_CONTEXT_HTML = """
<html><body>
  <div class="birim_safya_body_detay">
    <div class="personel_listesi">
      <div class="birim_modul_baslik">Başkan</div>
      <div class="row">
        <div class="card">
          <ul>
            <li class="adsoyad truncate">Doç. Dr. Eyyüp TUNCER</li>
            <li class="unvan">Doç. Dr.</li>
            <li class="dahili">2211</li>
            <li class="mail truncate">eyyup.tuncer@gibtu.edu.tr</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


class SubunitManagementScraperTests(unittest.TestCase):
    def test_allowlist_sadece_hedef_sayfalari_kabul_eder(self):
        self.assertTrue(is_allowed_subunit_management_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18"))
        self.assertTrue(is_allowed_subunit_management_url("https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id=96"))
        self.assertFalse(is_allowed_subunit_management_url("https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id=18"))
        self.assertFalse(is_allowed_subunit_management_url("http://www.gibtu.edu.tr/BirimYonetim.aspx?id=18"))
        self.assertFalse(is_allowed_subunit_management_url("https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18&foo=bar"))
        self.assertFalse(is_allowed_subunit_management_url("https://www.gibtu.edu.tr/Duyuru.aspx?id=18"))

    def test_grup_rolu_akademik_unvandan_ayrilir(self):
        target = _target(18)
        page, records, ignored, duplicates = parse_subunit_management_page(
            MANAGEMENT_HTML,
            target,
            target.source_url,
            "run-1",
        )

        self.assertEqual(page.parse_status, "valid")
        self.assertEqual(len(records), 1)
        self.assertEqual(len(ignored), 0)
        self.assertEqual(len(duplicates), 0)
        self.assertEqual(records[0].management_role, "Bölüm Başkanı")
        self.assertEqual(records[0].academic_title, "Doç. Dr.")
        self.assertEqual(records[0].person_name, "Cemal AKTÜRK")
        self.assertEqual(records[0].parse_status, "valid")

    def test_eksik_veya_0000_telefon_partial_warningdir(self):
        target = _target(16)
        page, records, _, _ = parse_subunit_management_page(
            PARTIAL_HTML,
            target,
            target.source_url,
            "run-2",
        )

        self.assertEqual(page.parse_status, "partial")
        self.assertEqual(records[0].parse_status, "partial")
        self.assertIn("placeholder_phone_0000", records[0].validation_issues)
        report = SubunitManagementScrapeReport(
            scrape_run_id="run-2",
            target_url_count=1,
            pages=[page],
            records=records,
        )
        validation = build_validation_report(report)
        self.assertTrue(validation["db_write_ready"])
        self.assertEqual(validation["partial_count"], 1)
        self.assertEqual(validation["db_candidate_count"], 1)
        self.assertEqual(validation["partial_db_candidate_count"], 1)
        self.assertEqual(validation["needs_review_count"], 0)

    def test_ayni_kisi_ayni_rol_ayni_url_duplicate_bastirilir(self):
        target = _target(18)
        page, records, ignored, duplicates = parse_subunit_management_page(
            DUPLICATE_HTML,
            target,
            target.source_url,
            "run-duplicate",
        )

        self.assertEqual(page.parse_status, "valid")
        self.assertEqual(len(records), 1)
        self.assertEqual(len(ignored), 0)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].kept_record_order, 1)
        self.assertEqual(duplicates[0].duplicate_record_order, 2)

        report = SubunitManagementScrapeReport(
            scrape_run_id="run-duplicate",
            target_url_count=1,
            pages=[page],
            records=records,
            duplicate_suppressed_records=duplicates,
        )
        validation = build_validation_report(report)
        self.assertTrue(validation["db_write_ready"])
        self.assertEqual(validation["duplicate_suppressed_count"], 1)
        self.assertEqual(validation["duplicate_records"], [])

    def test_kapsam_disi_roller_db_adayi_olmaz(self):
        target = _target(105)
        page, records, _, _ = parse_subunit_management_page(
            OUT_OF_SCOPE_ROLE_HTML,
            target,
            target.source_url,
            "run-out-of-scope",
        )

        report = SubunitManagementScrapeReport(
            scrape_run_id="run-out-of-scope",
            target_url_count=1,
            pages=[page],
            records=records,
        )
        validation = build_validation_report(report)

        self.assertEqual(validation["total_found"], 2)
        self.assertEqual(validation["db_candidate_count"], 1)
        self.assertEqual(validation["excluded_out_of_scope_count"], 1)
        self.assertEqual(validation["db_candidate_records"][0]["management_role"], "Bölüm Başkanı")
        self.assertEqual(validation["excluded_out_of_scope_records"][0]["management_role"], "Dekan")

    def test_baskan_rolu_bolum_baglaminda_db_adayidir(self):
        target = _target(34)
        page, records, _, _ = parse_subunit_management_page(
            BASKAN_CONTEXT_HTML,
            target,
            target.source_url,
            "run-baskan-context",
        )

        report = SubunitManagementScrapeReport(
            scrape_run_id="run-baskan-context",
            target_url_count=1,
            pages=[page],
            records=records,
        )
        validation = build_validation_report(report)

        self.assertEqual(validation["db_candidate_count"], 1)
        self.assertEqual(validation["excluded_out_of_scope_count"], 0)

    def test_belirsiz_rol_needs_review_raporlanir(self):
        target = _target(99)
        page, records, _, _ = parse_subunit_management_page(
            NEEDS_REVIEW_HTML,
            target,
            target.source_url,
            "run-3",
        )

        self.assertEqual(page.parse_status, "needs_review")
        self.assertEqual(records[0].parse_status, "needs_review")
        self.assertIn("missing_management_role", records[0].validation_issues)

    def test_needs_review_valid_kayitlarin_write_hazirligini_bloklamaz(self):
        valid_target = _target(18)
        valid_page, valid_records, _, _ = parse_subunit_management_page(
            MANAGEMENT_HTML,
            valid_target,
            valid_target.source_url,
            "run-mixed",
        )
        review_target = _target(99)
        review_page, review_records, _, _ = parse_subunit_management_page(
            NEEDS_REVIEW_HTML,
            review_target,
            review_target.source_url,
            "run-mixed",
        )

        report = SubunitManagementScrapeReport(
            scrape_run_id="run-mixed",
            target_url_count=2,
            pages=[valid_page, review_page],
            records=[*valid_records, *review_records],
        )
        validation = build_validation_report(report)

        self.assertEqual(validation["valid_count"], 1)
        self.assertEqual(validation["needs_review_count"], 1)
        self.assertTrue(validation["db_write_ready"])
        self.assertEqual(validation["db_write_blockers"], [])

    def test_birim_akademik_personel_sadece_yonetim_sinyalini_alir(self):
        target = _target(96)
        page, records, ignored, duplicates = parse_subunit_management_page(
            ACADEMIC_PERSONNEL_HTML,
            target,
            target.source_url,
            "run-4",
        )

        self.assertEqual(page.parse_status, "valid")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].management_role, "Bölüm Başkan V.")
        self.assertEqual(records[0].person_name, "Aysun SÖYLEMEZ")
        self.assertEqual(len(ignored), 1)
        self.assertEqual(len(duplicates), 0)
        self.assertEqual(ignored[0].reason, "BirimAkademikPersonel kartında açık yönetim rolü sinyali yok.")


if __name__ == "__main__":
    unittest.main()
