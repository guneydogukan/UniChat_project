"""YÖK Akademik akademik kadro scraper birim testleri."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers.yok_academic_staff_scraper import (  # noqa: E402
    YokAcademicStaffScrapeReport,
    YokAcademicStaffScraper,
    YokAcademicTarget,
    YokPersonRecord,
    YokUnitSnapshot,
    build_scrape_quality_report,
    classify_yok_record_against_targets,
    normalize_for_match,
    parse_filtered_result_context,
    parse_kadro_veri_profile,
    parse_yok_filtered_targets,
    parse_yok_pagination_links,
    parse_yok_upper_unit_links,
    parse_yok_university_list,
    parse_yok_university_staff_page,
    utc_now_iso,
)


UNIVERSITY_LIST_HTML = """
<html><body>
  <a href="/AkademikArama/view/universityView.jsp?universityId=123">
    Gaziantep İslam Bilim ve Teknoloji Üniversitesi
  </a>
</body></html>
"""

FILTERED_PAGE_HTML = """
<html><head><title>YÖK Akademik</title></head><body>
  <h2>
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
    MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ /
    BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ
    Arama Sonucu: 2
  </h2>
  <div class="result-card">
    <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1">Doç. Dr. Ayşe YILMAZ</a>
  </div>
  <a href="/AkademikArama/AkademisyenArama?page=2&unit=bilgisayar">2</a>
</body></html>
"""

UNIVERSITY_HOME_HTML = """
<html><body>
  <h1>Gaziantep İslam Bilim ve Teknoloji Üniversitesi</h1>
  <h3>Mühendislik ve Doğa Bilimleri Fakültesi</h3>
  <ul>
    <li>
      <a href="/AkademikArama/AkademisyenArama?birim=bilgisayar">
        Bilgisayar Mühendisliği Bölümü (2)
      </a>
    </li>
    <li>
      <a href="/AkademikArama/AkademisyenArama?birim=fakulte">
        Mühendislik ve Doğa Bilimleri Fakültesi
      </a>
    </li>
  </ul>
  <h3>Teknik Bilimler Meslek Yüksekokulu</h3>
  <a href="/AkademikArama/AkademisyenArama?birim=bilgisayar-programciligi">
    Bilgisayar Programcılığı Programı (4)
  </a>
</body></html>
"""

LIVE_GIBTU_HOME_HTML = """
<html><body>
  <div class="alert alert-info">
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ için arama sonuçları
    <span class="badge">Arama sonucu: 251 sonuç bulundu</span>
  </div>
  <div class="sidebar-nav">
    <a class="list-group-item listMinimal list-group-item-info active"
       href="/AkademikArama/AkademisyenArama?islem=uni">
      GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ
    </a>
    <a class="list-group-item listMinimal list-group-item-info"
       href="/AkademikArama/AkademisyenArama?birim=eng">
      MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİMÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ
      FACULTY OF ENGINEERING AND NATURAL SCIENCES
    </a>
    <a class="list-group-item listMinimal list-group-item-info"
       href="/AkademikArama/AkademisyenArama?birim=rector">
      REKTÖRLÜKREKTÖRLÜK REKTÖRLÜK
    </a>
  </div>
</body></html>
"""

LIVE_ENGINEERING_PAGE_HTML = """
<html><body>
  <div class="alert alert-info">
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
    MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ için arama sonuçları
    <span class="badge">Arama sonucu: 36 sonuç bulundu</span>
  </div>
  <div class="sidebar-nav">
    <a class="list-group-item listMinimal list-group-item-info active"
       href="/AkademikArama/AkademisyenArama?birim=eng">
      MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİMÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ
    </a>
    <a class="list-group-item listMinimal list-group-item-info"
       href="/AkademikArama/AkademisyenArama?islem=comp">
      BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜBİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ
      DEPARTMENT OF COMPUTER ENGINEERING
    </a>
    <a class="list-group-item listMinimal list-group-item-info"
       href="/AkademikArama/AkademisyenArama?islem=ee">
      ELEKTRİK-ELEKTRONİK MÜHENDİSLİĞİ BÖLÜMÜELEKTRİK-ELEKTRONİK MÜHENDİSLİĞİ BÖLÜMÜ
      DEPARTMENT OF ELECTRICAL-ELECTRONICS ENGINEERING
    </a>
  </div>
  <table id="authorlistTb">
    <tr id="authorInfo_219472">
      <td>
        <h4>
          <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=6275CE07D6A73969">
            ALİ AYTEK
          </a>
        </h4>
        <span class="label label-success">
          <a class="anahtarKelime" href="/AkademikArama/AkademisyenArama?islem=temel">
            Mühendislik Temel Alanı
          </a>
        </span>
      </td>
    </tr>
  </table>
</body></html>
"""

LIVE_COMPUTER_DEPARTMENT_HTML = """
<html><body>
  <div class="alert alert-info">
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
    MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ /
    BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ için arama sonuçları
    <span class="badge">Arama sonucu: 8 sonuç bulundu</span>
  </div>
  <table id="authorlistTb" class="table table-striped">
    <tbody>
      <tr id="authorInfo_49740">
        <td><span id="spid" style="visibility: hidden;font-size: 0pt">49740</span></td>
        <td width="110px">
          <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?islem=direct&amp;sira=X&amp;authorId=6A8A18D6CFB895E5">
            <img alt="CEMAL AKTÜRK" />
          </a>
        </td>
        <td>
          <h6>DOÇENT</h6>
          <h4>
            <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?islem=direct&amp;sira=X&amp;authorId=6A8A18D6CFB895E5">
              CEMAL AKTÜRK
            </a>
          </h4>
          <h6>
            GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ/
            MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ/
            BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ/
            BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI/
          </h6>
          <span class="label label-success">
            <a class="anahtarKelime" href="/AkademikArama/AkademisyenArama?islem=temel">
              Mühendislik Temel Alanı
            </a>
          </span>
          <span class="label label-primary">
            <a class="anahtarKelime" href="/AkademikArama/AkademisyenArama?islem=bilim">
              Bilgisayar Bilimleri ve Mühendisliği
            </a>
          </span>
          <a href="/AkademikArama/AkademisyenArama?islem=keyword">Makine Öğrenmesi</a>
        </td>
      </tr>
    </tbody>
  </table>
  <ul class="pagination">
    <li><a href="/AkademikArama/AramaFiltrele?islem=page1-again">1</a></li>
    <li class="active"><a href="/AkademikArama/AramaFiltrele?islem=page2-active">2</a></li>
  </ul>
</body></html>
"""

LIVE_COMPUTER_DEPARTMENT_PAGE_2_HTML = """
<html><body>
  <div class="alert alert-info">
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
    MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ /
    BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ için arama sonuçları
    <span class="badge">Arama sonucu: 2 sonuç bulundu</span>
  </div>
  <table id="authorlistTb">
    <tbody>
      <tr id="authorInfo_49741">
        <td><span id="spid" style="visibility: hidden;font-size: 0pt">49741</span></td>
        <td>
          <h6>DOÇENT</h6>
          <h4>
            <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?islem=direct&amp;sira=Y&amp;authorId=PAGE2A">
              TARIK TALAN
            </a>
          </h4>
          <h6>
            GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ/
            MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ/
            BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ/
            BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI/
          </h6>
        </td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

LIVE_PAGINATED_DEPARTMENT_PAGE_1_HTML = """
<html><body>
  <div class="alert alert-info">
    GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
    MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ /
    BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ için arama sonuçları
    <span class="badge">Arama sonucu: 2 sonuç bulundu</span>
  </div>
  <table id="authorlistTb">
    <tbody>
      <tr id="authorInfo_49740">
        <td><span id="spid" style="visibility: hidden;font-size: 0pt">49740</span></td>
        <td>
          <h6>DOÇENT</h6>
          <h4>
            <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?islem=direct&amp;sira=X&amp;authorId=PAGE1A">
              CEMAL AKTÜRK
            </a>
          </h4>
          <h6>
            GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ/
            MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ/
            BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ/
            BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI/
          </h6>
        </td>
      </tr>
    </tbody>
  </table>
  <ul class="pagination">
    <li class="active"><a href="/AkademikArama/AramaFiltrele?islem=active-bad">1</a></li>
    <li><a href="/AkademikArama/AramaFiltrele?islem=page2">2</a></li>
  </ul>
  <a class="anahtarKelime" href="/AkademikArama/AkademisyenArama?islem=keyword">Makine Öğrenmesi</a>
</body></html>
"""

INVALID_TARGET_CONTEXT_HTML = """
<html><body>
  <h1>YÜKSEKÖĞRETİM KURULU</h1>
  <div class="alert alert-info">Unvan(lar) Araştırmacı Listem</div>
</body></html>
"""

PROFILE_HTML = """
<html><body>
  <h1>Doç. Dr. Ayşe YILMAZ</h1>
  <section>
    <h3>Kadro Veri</h3>
    <p>
      GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ /
      MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ /
      BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ /
      BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI
    </p>
  </section>
  <section>
    <h3>Anahtar Kelime</h3>
    <p>Makine Öğrenmesi</p>
  </section>
</body></html>
"""

LIVE_LIKE_MIXED_RESULT_HTML = """
<html><body>
  <table>
    <tbody>
      <tr id="authorInfo_51833">
        <td>51833</td>
        <td>
          DOÇENT
          <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=B2">
            EMRE AYINTAP
          </a>
          SAĞLIK BİLİMLERİ ÜNİVERSİTESİ/İZMİR TEPECİK SAĞLIK UYGULAMA VE ARAŞTIRMA MERKEZİ/
          CERRAHİ TIP BİLİMLERİ BÖLÜMÜ/GÖZ HASTALIKLARI ANABİLİM DALI/
          <a class="anahtarKelime" href="/AkademikArama/AkademisyenArama?islem=temel">
            Sağlık Bilimleri Temel Alanı
          </a>
        </td>
      </tr>
      <tr id="authorInfo_12345">
        <td>12345</td>
        <td>
          DOÇENT
          <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1">
            AYŞE YILMAZ
          </a>
          GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ/
          MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ/
          BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ/
          BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI/
        </td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

UNBOUNDED_BULK_PROFILE_HTML = """
<html><body>
  <table>
    <tr>
      <td>
        DOÇENT
        <a href="/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=BULK1">
          EMRE AYINTAP
        </a>
        SAĞLIK BİLİMLERİ ÜNİVERSİTESİ CERRAHİ TIP BİLİMLERİ BÖLÜMÜ
      </td>
    </tr>
  </table>
</body></html>
"""


def _record(**overrides) -> YokPersonRecord:
    payload = {
        "full_name": "Ayşe YILMAZ",
        "normalized_name": normalize_for_match("Ayşe YILMAZ"),
        "title": "Doç. Dr.",
        "yok_profile_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=A1",
        "yok_researcher_id": "A1",
        "university_from_yok": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
        "faculty_from_yok": None,
        "department_from_yok": None,
        "unit_text_from_yok": "Anahtar Kelime: Makine Öğrenmesi",
        "source_url": "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
        "source_status": "unmatched_program",
        "confidence_status": "unmatched_program",
        "confidence_score": 0.0,
        "needs_manual_review": True,
        "last_checked_at": utc_now_iso(),
    }
    payload.update(overrides)
    return YokPersonRecord(**payload)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.requests: list[dict[str, str | None]] = []

    def get(self, url: str, timeout: int, headers: dict[str, str | None]):
        self.requests.append({"url": url, "referer": headers.get("Referer")})
        return FakeResponse(self.responses.get(url, INVALID_TARGET_CONTEXT_HTML))


class YokAcademicParserTests(unittest.TestCase):
    def test_university_list_gibtu_linkini_bulur(self):
        url = parse_yok_university_list(UNIVERSITY_LIST_HTML)

        self.assertEqual(
            url,
            "https://akademik.yok.gov.tr/AkademikArama/view/universityView.jsp?universityId=123",
        )

    def test_filtered_context_basliktan_birim_ve_sonuc_sayisi_parse_eder(self):
        context = parse_filtered_result_context(
            FILTERED_PAGE_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
        )

        self.assertEqual(context["parent_unit_name"], "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ")
        self.assertEqual(context["unit_name"], "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ")
        self.assertEqual(context["result_count"], 2)

    def test_canli_alert_context_bolum_ve_sonuc_sayisi_parse_eder(self):
        context = parse_filtered_result_context(
            LIVE_COMPUTER_DEPARTMENT_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=comp",
        )

        self.assertEqual(context["parent_unit_name"], "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ")
        self.assertEqual(context["unit_name"], "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ")
        self.assertEqual(context["result_count"], 8)
        self.assertNotIn("CEMAL AKTÜRK", context["raw_title"])

    def test_universite_sayfasindan_sadece_bolum_program_hedefleri_cikarilir(self):
        targets = parse_yok_filtered_targets(
            UNIVERSITY_HOME_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/view/universityView.jsp?universityId=123",
        )

        names = {target.unit_name for target in targets}
        self.assertIn("Bilgisayar Mühendisliği Bölümü", names)
        self.assertIn("Bilgisayar Programcılığı Programı", names)
        self.assertNotIn("Mühendislik ve Doğa Bilimleri Fakültesi", names)

    def test_gibtu_sayfasindan_ust_birim_linkleri_cikarilir(self):
        links = parse_yok_upper_unit_links(
            LIVE_GIBTU_HOME_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=uni",
        )

        names = {link["parent_unit_name"] for link in links}
        self.assertIn("MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ", names)
        self.assertNotIn("REKTÖRLÜK", names)

    def test_ust_birim_sayfasindan_canli_sidebar_bolum_hedefleri_cikarilir(self):
        targets = parse_yok_filtered_targets(
            LIVE_ENGINEERING_PAGE_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=eng",
        )

        names = {target.unit_name for target in targets}
        by_name = {target.unit_name: target for target in targets}
        self.assertIn("BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ", names)
        self.assertIn("ELEKTRİK-ELEKTRONİK MÜHENDİSLİĞİ BÖLÜMÜ", names)
        self.assertNotIn(
            "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜBİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ",
            names,
        )
        self.assertEqual(
            by_name["BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ"].filtered_context["raw_title"],
            "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ / MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ / BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ",
        )

    def test_filtered_sayfadan_gercek_profil_url_cikarilir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_result_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
            filtered_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
        )

        records = parse_yok_university_staff_page(
            FILTERED_PAGE_HTML,
            target.filtered_result_url or "",
            target=target,
        )

        self.assertEqual(len(records), 1)
        self.assertIn("authorId=A1", records[0].yok_profile_url or "")
        self.assertEqual(records[0].matched_target_key, target.unit_key)

    def test_canli_authorlistTb_satirindan_kisi_ve_birim_yolu_parse_edilir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
        )

        records = parse_yok_university_staff_page(
            LIVE_COMPUTER_DEPARTMENT_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=comp",
            target=target,
            filtered_context=target.filtered_context,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].full_name, "CEMAL AKTÜRK")
        self.assertEqual(records[0].title, "Doç. Dr.")
        self.assertEqual(records[0].university_from_yok, "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ")
        self.assertEqual(records[0].department_from_yok, "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ")

    def test_pagination_sadece_aktif_olmayan_pager_linklerini_dondurur(self):
        links = parse_yok_pagination_links(
            LIVE_PAGINATED_DEPARTMENT_PAGE_1_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=comp",
        )

        self.assertEqual(
            links,
            ["https://akademik.yok.gov.tr/AkademikArama/AramaFiltrele?islem=page2"],
        )

    def test_toplu_sayfa_metninden_target_uretilmez(self):
        targets = parse_yok_filtered_targets(
            LIVE_LIKE_MIXED_RESULT_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=karisik",
        )

        self.assertEqual(targets, ())

    def test_kisi_karti_sinirinda_temiz_isim_parse_edilir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
        )

        records = parse_yok_university_staff_page(
            LIVE_LIKE_MIXED_RESULT_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=karisik",
            target=target,
        )

        names = {record.full_name for record in records}
        self.assertIn("EMRE AYINTAP", names)
        self.assertNotIn("EMRE AYINTAP SAĞLIK BİLİMLERİ", names)

    def test_siniri_belirsiz_toplu_satirdan_kisi_parse_edilmez(self):
        records = parse_yok_university_staff_page(
            UNBOUNDED_BULK_PROFILE_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=bulk",
        )

        self.assertEqual(records, [])

    def test_target_context_yoksa_sayfa_context_uretilmez(self):
        context = parse_filtered_result_context(
            LIVE_LIKE_MIXED_RESULT_HTML,
            "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=karisik",
        )

        self.assertIsNone(context.get("unit_name"))

    def test_context_dogrulanmayan_candidate_target_uretilmez(self):
        candidate_url = "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=invalid"
        candidate = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_result_url=candidate_url,
            filtered_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
        )
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id="run",
            started_at=utc_now_iso(),
            dry_run=True,
        )
        scraper = YokAcademicStaffScraper(
            session=FakeSession({candidate_url: INVALID_TARGET_CONTEXT_HTML}),
            rate_limit_seconds=0,
            max_rate_limit_seconds=0,
            checkpoint_dir=None,
            target_limit=1,
        )

        target = scraper._validate_target_candidate(report, candidate, "https://akademik.yok.gov.tr/AkademikArama/")

        self.assertIsNone(target)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.validation_results[-1]["code"], "rejected_target_candidate")

    def test_pagination_ikinci_sayfadaki_kisileri_ekler(self):
        start_url = "https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?islem=comp"
        page2_url = "https://akademik.yok.gov.tr/AkademikArama/AramaFiltrele?islem=page2"
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_result_url=start_url,
            filtered_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
            expected_result_count=2,
        )
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id="run",
            started_at=utc_now_iso(),
            dry_run=True,
        )
        session = FakeSession({
                start_url: LIVE_PAGINATED_DEPARTMENT_PAGE_1_HTML,
                page2_url: LIVE_COMPUTER_DEPARTMENT_PAGE_2_HTML,
            })
        scraper = YokAcademicStaffScraper(
            session=session,
            rate_limit_seconds=0,
            max_rate_limit_seconds=0,
            checkpoint_dir=None,
            resume=False,
            max_pages=5,
        )

        records, metric = scraper._crawl_filtered_target(report, target, "https://akademik.yok.gov.tr/AkademikArama/")

        self.assertEqual({record.full_name for record in records}, {"CEMAL AKTÜRK", "TARIK TALAN"})
        self.assertEqual(metric["parsed_person_count"], 2)
        self.assertEqual(metric["pagination_page_count"], 2)
        self.assertEqual([request["url"] for request in session.requests], [start_url, page2_url])
        self.assertEqual(session.requests[1]["referer"], start_url)
        self.assertEqual(report.errors, [])

    def test_kadro_veri_label_aware_parse_edilir(self):
        parsed = parse_kadro_veri_profile(PROFILE_HTML)

        self.assertEqual(parsed["parse_status"], "parsed")
        self.assertEqual(parsed["parent_unit"], "MÜHENDİSLİK VE DOĞA BİLİMLERİ FAKÜLTESİ")
        self.assertEqual(parsed["department"], "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ")
        self.assertEqual(parsed["subunit"], "BİLGİSAYAR MÜHENDİSLİĞİ ANABİLİM DALI")


class YokAcademicMatcherTests(unittest.TestCase):
    def test_kadro_veri_guclu_kanit_olarak_eslestirir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
        )
        record = _record(
            kadro_university="Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
            kadro_parent_unit="Mühendislik ve Doğa Bilimleri Fakültesi",
            kadro_department="Bilgisayar Mühendisliği Bölümü",
            kadro_subunit="Bilgisayar Mühendisliği Anabilim Dalı",
            kadro_parse_status="parsed",
        )

        classified, matched = classify_yok_record_against_targets(record, (target,))

        self.assertEqual(matched, target)
        self.assertEqual(classified.source_status, "verified_from_kadro_veri")
        self.assertIn("kadro_veri", classified.match_evidence)

    def test_anahtar_kelime_makine_programina_eslestirmez(self):
        target = YokAcademicTarget(
            "Teknik Bilimler Meslek Yüksekokulu",
            "Makine Programı",
        )
        record = _record(
            kadro_university="Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
            kadro_parent_unit="Mühendislik ve Doğa Bilimleri Fakültesi",
            kadro_department="Bilgisayar Mühendisliği Bölümü",
            kadro_parse_status="parsed",
            unit_text_from_yok="Anahtar Kelime: Makine Öğrenmesi; Temel Alan: Fen ve Mühendislik",
        )

        classified, matched = classify_yok_record_against_targets(record, (target,))

        self.assertIsNone(matched)
        self.assertNotIn(classified.source_status, {"verified_from_kadro_veri", "verified_from_filtered_context"})

    def test_filtered_context_kadro_yokken_guvenli_kanit_olabilir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
        )
        record = _record(
            matched_target_key=target.unit_key,
            kadro_parse_status="not_found",
            listing_context={
                "university": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi",
                "parent_unit_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                "unit_name": "Bilgisayar Mühendisliği Bölümü",
            },
        )

        classified, matched = classify_yok_record_against_targets(record, (target,))

        self.assertEqual(matched, target)
        self.assertEqual(classified.source_status, "verified_from_filtered_context")

    def test_kadro_veri_yokken_kadro_verified_verilmez(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
        )
        record = _record(
            kadro_parse_status="not_found",
            department_from_yok="Bilgisayar Mühendisliği Bölümü",
        )

        classified, matched = classify_yok_record_against_targets(record, (target,))

        self.assertEqual(matched, target)
        self.assertEqual(classified.source_status, "missing_kadro_veri")
        self.assertNotEqual(classified.source_status, "verified_from_kadro_veri")

    def test_farkli_universite_sonucu_conflict_olur(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
        )
        record = _record(
            university_from_yok="Sağlık Bilimleri Üniversitesi",
            department_from_yok="Bilgisayar Mühendisliği Bölümü",
            kadro_parse_status="not_found",
        )

        classified, matched = classify_yok_record_against_targets(record, (target,))

        self.assertIsNone(matched)
        self.assertEqual(classified.source_status, "conflict_institution")

    def test_quality_report_fakulte_snapshot_varsa_basarisizdir(self):
        target = YokAcademicTarget("Mühendislik ve Doğa Bilimleri Fakültesi", "Mühendislik ve Doğa Bilimleri Fakültesi", "faculty")
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id="run",
            started_at=utc_now_iso(),
            staff_snapshots=[
                YokUnitSnapshot(
                    target=target,
                    source_urls=["https://akademik.yok.gov.tr/AkademikArama/"],
                    person_keys=[],
                    missing_fields=[],
                    validation_status="valid",
                    last_checked_at=utc_now_iso(),
                )
            ],
        )

        quality = build_scrape_quality_report(report, expected_target_count=0)

        self.assertFalse(quality["kontroller"]["no_faculty_staff_snapshot"])
        self.assertTrue(quality["fakulte_snapshot_var_mi"])


class FakeAcademicRepository:
    def __init__(self) -> None:
        self.scrape_runs: list[dict] = []
        self.units: dict[str, str] = {}
        self.people: dict[str, str] = {}
        self.profiles: dict[str, dict] = {}
        self.affiliations: set[tuple[str, str, str]] = set()
        self.staff_snapshots: list[dict] = []
        self.program_metadata_calls = 0
        self.management_role_calls = 0

    def ensure_schema(self):
        return None

    def upsert_university(self, **kwargs):
        return "university-1"

    def upsert_scrape_run(self, run):
        self.scrape_runs.append(run)

    def upsert_unit(self, unit, university_id, parent_unit_id=None):
        key = (parent_unit_id, unit["unit_name_normalized"])
        self.units.setdefault(key, f"unit-{len(self.units) + 1}")
        return self.units[key]

    def upsert_program_metadata(self, *args, **kwargs):
        self.program_metadata_calls += 1
        raise AssertionError("YÖK Akademik kadro akışı program metadata yazmamalı")

    def upsert_yok_person(self, person):
        key = person.get("yok_profile_url") or person.get("yok_researcher_id") or person["normalized_name"]
        self.people.setdefault(key, f"person-{len(self.people) + 1}")
        return self.people[key]

    def upsert_external_profile(self, profile):
        key = profile.get("profile_url") or profile.get("external_id")
        self.profiles[key] = profile
        return f"profile-{len(self.profiles)}"

    def insert_evidence(self, evidence, unit_id=None, person_id=None):
        return "evidence-1"

    def deactivate_yok_staff_affiliations_for_units(self, unit_ids, last_checked_at=None):
        return 0

    def upsert_affiliation(self, affiliation):
        self.affiliations.add((
            affiliation["person_id"],
            affiliation["unit_id"],
            affiliation["source_url"],
        ))
        return "affiliation-1"

    def insert_raw_snapshot(self, snapshot, unit_id=None):
        return None

    def upsert_unit_staff_snapshot(self, snapshot, unit_id):
        self.staff_snapshots.append({"unit_id": unit_id, **snapshot})


class YokAcademicDatabaseWriteTests(unittest.TestCase):
    def test_db_yazimi_yok_only_idempotent_ve_yonetimsizdir(self):
        target = YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            filtered_result_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=bilgisayar",
            filtered_context={"unit_name": "Bilgisayar Mühendisliği Bölümü"},
        )
        person = _record(
            source_status="verified_from_kadro_veri",
            confidence_status="verified_from_kadro_veri",
            confidence_score=0.99,
            needs_manual_review=False,
            matched_target_key=target.unit_key,
            kadro_department="Bilgisayar Mühendisliği Bölümü",
        )
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id="run-1",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            targets=[target],
            persons=[person],
            staff_snapshots=[
                YokUnitSnapshot(
                    target=target,
                    source_urls=[target.filtered_result_url or ""],
                    person_keys=[person.person_key],
                    missing_fields=[],
                    validation_status="valid",
                    last_checked_at=utc_now_iso(),
                )
            ],
        )
        fake_repo = FakeAcademicRepository()

        with patch("app.repositories.academic_repository.AcademicRepository", return_value=fake_repo):
            scraper = YokAcademicStaffScraper(targets=(target,))
            first = scraper.write_report_to_database(report)
            second = scraper.write_report_to_database(report)

        self.assertEqual(first["affiliations"], 1)
        self.assertEqual(second["affiliations"], 1)
        self.assertEqual(len(fake_repo.affiliations), 1)
        self.assertEqual(fake_repo.program_metadata_calls, 0)
        self.assertEqual(fake_repo.management_role_calls, 0)
        self.assertEqual(fake_repo.scrape_runs[-1]["config"]["sources"], ["yok_akademik"])

    def test_ayni_bolum_adi_farkli_ust_birimlerde_ayri_unit_olur(self):
        faculty_target = YokAcademicTarget(
            "Sağlık Bilimleri Fakültesi",
            "Fizyoterapi ve Rehabilitasyon Bölümü",
            unit_type="department",
            filtered_result_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=sbf-ftr",
            filtered_context={"parent_unit_name": "Sağlık Bilimleri Fakültesi"},
        )
        vocational_target = YokAcademicTarget(
            "Sağlık Hizmetleri Meslek Yüksekokulu",
            "Fizyoterapi ve Rehabilitasyon Bölümü",
            unit_type="program",
            filtered_result_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenArama?birim=shmyo-ftr",
            filtered_context={"parent_unit_name": "Sağlık Hizmetleri Meslek Yüksekokulu"},
        )
        faculty_person = _record(
            full_name="Ayşe FAKÜLTE",
            normalized_name=normalize_for_match("Ayşe FAKÜLTE"),
            yok_profile_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=F1",
            yok_researcher_id="F1",
            source_status="verified_from_filtered_context",
            confidence_status="verified_from_filtered_context",
            confidence_score=0.94,
            needs_manual_review=False,
            matched_target_key=faculty_target.unit_key,
            faculty_from_yok=faculty_target.parent_unit_name,
            department_from_yok=faculty_target.unit_name,
        )
        vocational_person = _record(
            full_name="Mehmet MYO",
            normalized_name=normalize_for_match("Mehmet MYO"),
            yok_profile_url="https://akademik.yok.gov.tr/AkademikArama/AkademisyenGorevOgrenimBilgileri?authorId=M1",
            yok_researcher_id="M1",
            source_status="verified_from_filtered_context",
            confidence_status="verified_from_filtered_context",
            confidence_score=0.94,
            needs_manual_review=False,
            matched_target_key=vocational_target.unit_key,
            faculty_from_yok=vocational_target.parent_unit_name,
            department_from_yok=vocational_target.unit_name,
        )
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id="run-duplicate-unit-name",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            targets=[faculty_target, vocational_target],
            persons=[faculty_person, vocational_person],
            staff_snapshots=[
                YokUnitSnapshot(
                    target=faculty_target,
                    source_urls=[faculty_target.filtered_result_url or ""],
                    person_keys=[faculty_person.person_key],
                    missing_fields=[],
                    validation_status="valid",
                    last_checked_at=utc_now_iso(),
                ),
                YokUnitSnapshot(
                    target=vocational_target,
                    source_urls=[vocational_target.filtered_result_url or ""],
                    person_keys=[vocational_person.person_key],
                    missing_fields=[],
                    validation_status="valid",
                    last_checked_at=utc_now_iso(),
                ),
            ],
        )
        fake_repo = FakeAcademicRepository()

        with patch("app.repositories.academic_repository.AcademicRepository", return_value=fake_repo):
            scraper = YokAcademicStaffScraper(targets=(faculty_target, vocational_target))
            counts = scraper.write_report_to_database(report)

        snapshot_unit_ids = {snapshot["unit_id"] for snapshot in fake_repo.staff_snapshots}
        self.assertEqual(counts["staff_snapshots"], 2)
        self.assertEqual(len(fake_repo.staff_snapshots), 2)
        self.assertEqual(len(snapshot_unit_ids), 2)
        self.assertEqual(len(fake_repo.affiliations), 2)


if __name__ == "__main__":
    unittest.main()
