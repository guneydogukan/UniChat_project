"""Aday öğrenci portalı scraper birim testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers.candidate_portal_scraper import (  # noqa: E402
    BASE_URL,
    SCRAPER_NAME,
    CandidatePortalScraper,
    _decode_bytes,
)


SAMPLE_HTML = """
<html>
  <body>
    <div id="ogrenim">
      <section class="yukseklisans_listesi">
        <div class="faculty-card">
          <div class="faculty-card-title"><h3>ELEKTRİK - ELEKTRONİK MÜHENDİSLİĞİ</h3></div>
          <div class="faculty-card-list"></div>
        </div>
      </section>
      <section class="lisans_listesi">
        <div class="faculty-card">
          <div class="faculty-card-title"><h3>MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ | 4 YIL</h3></div>
          <div class="faculty-card-list">
            <ul>
              <li><span>Bilgisayar Mühendisliği</span></li>
              <li><span>Endüstri Mühendisliği</span></li>
            </ul>
          </div>
        </div>
      </section>
      <section class="onlisans_listesi">
        <div class="faculty-card">
          <div class="faculty-card-title"><h3>TEKNİK BİLİMLER MYO | 2 YIL</h3></div>
          <div class="faculty-card-list">
            <ul>
              <li><span>Bilgisayar Programcılığı</span></li>
            </ul>
          </div>
        </div>
      </section>
    </div>

    <div id="olanaklar">
      <div class="slayt">
        <div class="slayt_baslik"><span>Ulaşım Olanakları</span></div>
        <div class="slayt_metin"><span>Şehir içi ulaşımda halk otobüsleri ve belediye otobüsleri kullanılmaktadır.</span></div>
      </div>
      <div class="slayt">
        <div class="slayt_baslik"><span>Sağlıkta Öncü</span></div>
        <div class="slayt_metin"><span>Öğrencilerimizin sağlığını ön planda tutan bir öğrenim ortamı sunulur.</span></div>
      </div>
      <div class="slayt-copy">
        <div class="slayt_baslik"><span>Sahte Kart</span></div>
        <div class="slayt_metin"><span>Bu kart exact class selector ile alınmamalıdır.</span></div>
      </div>
    </div>

    <div id="kutuphane">KÜTÜPHANE Öğrenciler için çalışma alanları ve araştırma kaynakları sunulur.</div>
    <div id="erasmus">Erasmus+ ve Uluslararası Değişim Programları öğrencilere küresel deneyim fırsatı sunar.</div>
    <div id="cbiko">CBİKO Kariyer Merkezi öğrenciler için kariyer hizmetleri ve eğitim fırsatları sunar.</div>
    <div id="konaklama">ÖĞRENCİ KONAKLAMA SEÇENEKLERİ Kampüs içinde KYK yurdu olanağı bulunmaktadır.</div>
    <div id="gibtu">Gaziantep İslam Bilim ve Teknoloji Üniversitesi aday öğrenciler için akademik fırsatlar sunar.</div>
    <div id="gaziantep">Gaziantep tarihi, kültürel ve gastronomi olanaklarıyla aday öğrenciler için önemli bir şehirdir.</div>
    <div id="ogrencibasarisi">Öğrencinin Akademik Başarısı not ve başarı değerlendirme süreçleriyle belirlenir.</div>
    <footer id="iletisim-bilgileri">
      Öğrenci İşleri Daire Başkanlığı ogrenciisleri@gibtu.edu.tr https://adayogrenci.gibtu.edu.tr/
    </footer>

    <div id="sss">
      <ul class="collapsible popout">
        <li>
          <div class="collapsible-header">Üniversitedeki Akademik Programlar Nelerdir?</div>
          <div class="collapsible-body">Lisansüstü, lisans ve önlisans programları aday öğrenci portalında listelenir.</div>
        </li>
        <li>
          <div class="collapsible-header">Yurtdışı Değişim Programları Var Mı?</div>
          <div class="collapsible-body">Erasmus+ ve uluslararası değişim programlarıyla öğrenciler desteklenir.</div>
        </li>
      </ul>
    </div>

    <a href="https://example.com/dis-link">Dış link</a>
  </body>
</html>
"""


class CandidatePortalParserTests(unittest.TestCase):
    def setUp(self):
        self.scraper = CandidatePortalScraper(rate_limit_seconds=0)
        self.documents, self.stats = self.scraper.parse_documents(
            SAMPLE_HTML,
            fetched_at="2026-05-29T20:00:00Z",
        )

    def test_sss_soru_cevap_tek_document_kalir(self):
        faq_docs = [doc for doc in self.documents if doc.meta["doc_kind"] == "candidate_faq"]

        self.assertEqual(len(faq_docs), 2)
        for doc in faq_docs:
            self.assertIn("Soru:", doc.content)
            self.assertIn("Cevap:", doc.content)
            self.assertEqual(doc.meta["source_anchor"], "sss")
            self.assertIn("question", doc.meta)

    def test_olanaklar_exact_class_selector_ile_ayrisir(self):
        opportunity_docs = [
            doc for doc in self.documents
            if doc.meta["source_anchor"] == "olanaklar"
        ]
        titles = [doc.meta["title"] for doc in opportunity_docs]

        self.assertEqual(len(opportunity_docs), 2)
        self.assertTrue(any(doc.meta["doc_kind"] == "candidate_transportation" for doc in opportunity_docs))
        self.assertFalse(any("Sahte Kart" in title for title in titles))

    def test_programlar_seviyeye_gore_ayri_document_olur(self):
        program_docs = [doc for doc in self.documents if doc.meta["doc_kind"] == "candidate_program"]

        self.assertEqual(len(program_docs), 3)
        self.assertEqual(self.stats["program_card_count"], 3)
        levels = {doc.meta["program_level"] for doc in program_docs}
        self.assertEqual(levels, {"lisansustu", "lisans", "onlisans"})
        self.assertTrue(any("Bilgisayar Mühendisliği" in doc.content for doc in program_docs))

    def test_metadata_zorunlu_candidate_alanlarini_icerir(self):
        required = {
            "source_anchor",
            "scraper_name",
            "content_hash",
            "last_fetched_at",
            "is_official",
            "university",
            "dedup_key",
        }

        self.assertGreater(len(self.documents), 0)
        for doc in self.documents:
            self.assertTrue(required.issubset(doc.meta.keys()))
            self.assertEqual(doc.meta["scraper_name"], SCRAPER_NAME)
            self.assertTrue(doc.meta["source_url"].startswith(BASE_URL))
            self.assertTrue(doc.meta["is_official"])

    def test_windows_1254_encoding_fallback_turkceyi_korur(self):
        raw = "GİBTÜ Öğrenci İşleri".encode("windows-1254")

        text, encoding = _decode_bytes(raw, "text/html; charset=utf-8")

        self.assertEqual(text, "GİBTÜ Öğrenci İşleri")
        self.assertIn(encoding, {"windows-1254", "iso-8859-9"})


class CandidatePortalFetchTests(unittest.TestCase):
    def test_scrape_dis_linkleri_takip_etmez(self):
        class FakeResponse:
            content = SAMPLE_HTML.encode("windows-1254")
            headers = {"content-type": "text/html; charset=utf-8"}

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, timeout):
                self.calls.append((url, timeout))
                return FakeResponse()

        session = FakeSession()
        scraper = CandidatePortalScraper(session=session, max_retries=1, rate_limit_seconds=0)

        report = scraper.scrape(dry_run=True, cleanup=False)

        self.assertTrue(report.success)
        self.assertEqual(session.calls, [(BASE_URL, 20)])
        self.assertEqual(report.faq_count, 2)


if __name__ == "__main__":
    unittest.main()
