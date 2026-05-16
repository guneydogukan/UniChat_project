"""
UniChat — Regression Bug Test Suite
====================================
Bu testler, QA denetiminde tespit edilen bilinen hataları belgeler.
Her test, sisteme bir sorgu gönderir ve HATALI davranışı doğrular.

Testler şu anda `xfail` (expected failure) olarak işaretlidir:
  - xfail testi BAŞARISIZ olursa → beklenen, hata hâlâ mevcut ✅
  - xfail testi GEÇERse (XPASS) → hata düzeltilmiş, xfail kaldırılmalı ⚠️

Kullanım:
    cd backend
    python -m pytest test_regression_bugs.py -v --tb=short

Bağımlılıklar:
    - PostgreSQL çalışıyor olmalı (DATABASE_URL)
    - Ollama çalışıyor olmalı (gemma3:4b-it-qat)
    - pip install pytest  (henüz yüklü değilse)
"""

import os
import re
import sys
import time
import pytest

# ── Path ve ortam ayarları ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:gizlisifre@localhost:5433/postgres")

from app.services.rag_service import RagService


# ── Fixtures ──

@pytest.fixture(scope="session")
def rag():
    """RAG pipeline'ını session boyunca bir kez oluşturur."""
    service = RagService()
    service.build_pipeline()
    # İlk sorgu ile cold-start'ı atla
    service.query("test")
    return service


def _query(rag: RagService, question: str) -> dict:
    """Yardımcı: sorgu çalıştır, süreyi ölç."""
    start = time.time()
    result = rag.query(question)
    result["_elapsed"] = round(time.time() - start, 2)
    return result


# ═══════════════════════════════════════════════════════════════════
# GRUP 1: GUARDRAIL / KAPSAM DIŞI HATALARI
# Beklenen: Sistem kapsam dışı sorulara cevap VERMEMELİ.
# Mevcut durum: Sistem cevap veriyor → bu testler hataları yakalar.
# ═══════════════════════════════════════════════════════════════════

class TestGuardrailBugs:
    """Kapsam dışı sorulara verilen yanıtlardaki guardrail hataları."""

    @pytest.mark.xfail(reason="BUG-G7-02: Sistem Python kodu yazıyor, guardrail çalışmıyor")
    def test_python_code_rejected(self, rag):
        """G7-02: 'Python kodu yaz' sorusuna kod yazmamalı, reddetmeli."""
        result = _query(rag, "Bana bir Python kodu yazar mısın?")
        response = result["response"] or ""
        response_lower = response.lower()

        # Yanıtta kod blokları veya programlama dili öğeleri OLMAMALI
        has_code_block = "```" in response
        has_python_keywords = any(kw in response_lower for kw in [
            "def ", "print(", "import ", "class ", "for ", "while ",
            "if __name__", "return ", "lambda ",
        ])
        has_code_lang = any(lang in response_lower for lang in [
            "python", "javascript", "java", "c++", "html",
        ])

        assert not has_code_block, (
            f"Yanıtta kod bloğu var (```) — guardrail bypass!\n"
            f"Yanıt ilk 300 kar: {response[:300]}"
        )
        assert not has_python_keywords, (
            f"Yanıtta Python anahtar kelimeleri var — kod yazmış!\n"
            f"Yanıt ilk 300 kar: {response[:300]}"
        )
        # Üniversite asistanı olduğunu belirten reddetme yanıtı olmalı
        has_rejection = any(phrase in response_lower for phrase in [
            "yardımcı olamam", "kapsamım dışında", "üniversite",
            "gibtu", "yalnızca", "ilgili değil",
        ])
        assert has_rejection, (
            f"Kapsam dışı reddetme ifadesi yok!\n"
            f"Yanıt ilk 300 kar: {response[:300]}"
        )

    @pytest.mark.xfail(reason="BUG-G7-01: Sistem başkent sorusuna 'Ankara' diyor")
    def test_capital_city_rejected(self, rag):
        """G7-01: Genel kültür sorusuna cevap vermemeli."""
        result = _query(rag, "Türkiye'nin başkenti neresidir?")
        response = result["response"] or ""
        response_lower = response.lower()

        # "Ankara" kelimesi yanıtta OLMAMALI (üniversite bağlamı dışında)
        has_ankara = "ankara" in response_lower

        # Üniversite ile ilgili bir bağlamda Ankara geçiyorsa kabul edilebilir
        gibtu_context = any(w in response_lower for w in ["gibtu", "gaziantep", "üniversite"])
        ankara_in_address = "adres" in response_lower and has_ankara

        if ankara_in_address and gibtu_context:
            # Ankara üniversite adresinde geçiyorsa tamam
            pass
        else:
            assert not has_ankara, (
                f"Genel kültür sorusuna cevap verildi: 'Ankara' yanıtta!\n"
                f"Yanıt ilk 300 kar: {response[:300]}"
            )

        # Kapsam dışı reddetme olmalı
        has_rejection = any(phrase in response_lower for phrase in [
            "kapsamım dışında", "üniversite konuları",
            "yalnızca", "yardımcı olamam",
        ])
        assert has_rejection, (
            f"Kapsam dışı reddetme ifadesi yok!\n"
            f"Yanıt ilk 300 kar: {response[:300]}"
        )


# ═══════════════════════════════════════════════════════════════════
# GRUP 2: HALÜSİNASYON — UYDURMA İLETİŞİM BİLGİSİ
# Beklenen: Belgede olmayan URL/telefon/e-posta üretmemeli.
# Mevcut durum: Uydurma bilgiler üretiliyor.
# ═══════════════════════════════════════════════════════════════════

class TestHallucinatedContactInfo:
    """Belgede bulunmayan URL, telefon, e-posta üretimi hataları."""

    # Bilinen geçerli domain'ler — yalnızca GİBTÜ resmi domain'leri
    VALID_DOMAINS = {
        "gibtu.edu.tr", "www.gibtu.edu.tr",
        "adayogrenci.gibtu.edu.tr",
        "mail.gibtu.edu.tr",
        "ubys.gibtu.edu.tr",
    }

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        """Yanıttan URL'leri çıkarır."""
        return re.findall(r'https?://[^\s\)\]>\"]+', text)

    @staticmethod
    def _extract_phones(text: str) -> list[str]:
        """Yanıttan telefon numaralarını çıkarır."""
        # +90, 0xxx, (0xx) formatlarını yakalar
        return re.findall(r'[\+]?[\d][\d\s\(\)\-]{8,}[\d]', text)

    def _is_valid_domain(self, url: str) -> bool:
        """URL domain'inin bilinen listede olup olmadığını kontrol eder."""
        try:
            # http://www.gibtu.edu.tr/path → www.gibtu.edu.tr
            domain = url.split("//")[1].split("/")[0].split(":")[0]
            # Subdomain kontrolü: x.gibtu.edu.tr → gibtu.edu.tr de kabul
            for valid in self.VALID_DOMAINS:
                if domain == valid or domain.endswith("." + valid):
                    return True
            return False
        except (IndexError, AttributeError):
            return False

    @pytest.mark.xfail(reason="BUG-G6-01: Uydurma URL üretiliyor (Muenfezlik.aspx)")
    def test_no_hallucinated_urls_uzay(self, rag):
        """G6-01: Uzay mühendisliği sorusunda uydurma URL olmamalı."""
        result = _query(rag, "GİBTÜ'nün uzay mühendisliği bölümü var mı?")
        response = result["response"] or ""

        urls = self._extract_urls(response)
        invalid_urls = [u for u in urls if not self._is_valid_domain(u)]

        assert not invalid_urls, (
            f"Uydurma URL tespit edildi: {invalid_urls}\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

    @pytest.mark.xfail(reason="BUG-G3-02: Uydurma telefon üretiliyor (032) 2523 4000")
    def test_no_hallucinated_phone_hemsirelik(self, rag):
        """G3-02: Hemşirelik sorusunda uydurma telefon olmamalı."""
        result = _query(rag, "Hemşirelik mi ebelik mi daha iyi? Hangisini seçmeliyim?")
        response = result["response"] or ""

        phones = self._extract_phones(response)
        # Bilinen doğru numara
        known_phone_fragments = ["342 909 75 00", "3429097500"]

        for phone in phones:
            clean = re.sub(r'[\s\(\)\-\+]', '', phone)
            is_known = any(k.replace(" ", "") in clean for k in known_phone_fragments)
            assert is_known, (
                f"Doğrulanamayan telefon numarası: '{phone}'\n"
                f"Bilinen numaralar: {known_phone_fragments}\n"
                f"Yanıt ilk 500 kar: {response[:500]}"
            )

    @pytest.mark.xfail(reason="BUG-G1-05: gantep.edu.tr (yanlış üniversite) domain'i üretiliyor")
    def test_no_wrong_domain_yemek(self, rag):
        """G1-05: Yemek sorusunda GİBTÜ dışı domain olmamalı.

        gantep.edu.tr GİBTÜ'ye ait değildir. sks.gantep.edu.tr dahil
        tüm gantep domain'leri validator tarafından kaldırılmalıdır.
        """
        result = _query(rag, "Bugün yemekhanede ne var?")
        response = result["response"] or ""

        urls = self._extract_urls(response)
        gantep_urls = [u for u in urls if "gantep.edu.tr" in u]
        assert not gantep_urls, (
            f"GİBTÜ dışı gantep.edu.tr URL'si bulundu: {gantep_urls}\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )


# ═══════════════════════════════════════════════════════════════════
# GRUP 3: GÜNCELLİK HATALARI
# Beklenen: Eski akademik yıl bilgisi güncel gibi sunulmamalı.
# Mevcut durum: 2023-2024 sınav tarihleri döndürülüyor.
# ═══════════════════════════════════════════════════════════════════

class TestStalenesseBugs:
    """Eski bilgiyi güncel gibi sunma hataları."""

    @pytest.mark.xfail(reason="BUG-G9-02: 2023-2024 sınav tarihleri güncel gibi sunuluyor")
    def test_exam_dates_not_outdated(self, rag):
        """G9-02: Sınav tarihleri sorgusu eski yıl tarihlerini döndürmemeli."""
        result = _query(rag, "Sınav tarihleri ne zaman açıklanacak?")
        response = result["response"] or ""

        # 2023 veya 2023-2024 gibi eski akademik yıl referansları
        outdated_patterns = [
            r'\b2023\s*[-–/]\s*2024\b',     # 2023-2024
            r'\b2022\s*[-–/]\s*2023\b',     # 2022-2023
            r'\bKasım 2023\b',              # Kasım 2023
            r'\bNisan 2024\b',              # Nisan 2024 (eski takvim)
            r'\bAralık 2023\b',             # Aralık 2023
            r'\bMayıs 2024\b',             # Mayıs 2024 (eski takvim)
        ]

        found_outdated = []
        for pat in outdated_patterns:
            matches = re.findall(pat, response)
            found_outdated.extend(matches)

        assert not found_outdated, (
            f"Eski akademik yıl tarihleri tespit edildi: {found_outdated}\n"
            f"Test tarihi: Mayıs 2026 — 2023-2024 tarihleri güncel değil!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )


# ═══════════════════════════════════════════════════════════════════
# GRUP 4: YANLIŞ YÖNLENDİRME
# Beklenen: Transkript → Öğrenci İşleri yönlendirmeli.
# Mevcut durum: Lisansüstü Enstitüsü'ne yönlendiriyor.
# ═══════════════════════════════════════════════════════════════════

class TestRoutingBugs:
    """Yanlış birime yönlendirme hataları."""

    @pytest.mark.xfail(reason="BUG-G5-01: Transkript Lisansüstü'ye yönlendiriliyor, Öğrenci İşleri olmalı")
    def test_transcript_routes_to_ogrenci_isleri(self, rag):
        """G5-01: Transkript sorusu Öğrenci İşleri'ne yönlendirmeli."""
        result = _query(rag, "Transkript almak istiyorum, nereye başvurmam lazım?")
        response = result["response"] or ""
        response_lower = response.lower()

        has_ogrenci_isleri = "öğrenci işleri" in response_lower
        has_enstitü = "lisansüstü" in response_lower and "enstitü" in response_lower

        # Öğrenci İşleri geçmeli
        assert has_ogrenci_isleri, (
            f"'Öğrenci İşleri' yönlendirmesi yok!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

        # Lisansüstü Enstitüsü tek başına yönlendirilmemeli
        # (eğer "lisansüstü öğrenci iseniz enstitüye" gibi koşullu ise kabul)
        if has_enstitü and not has_ogrenci_isleri:
            pytest.fail(
                f"Transkript için yanlış birime yönlendirme: Lisansüstü Enstitüsü\n"
                f"Doğru birim: Öğrenci İşleri Daire Başkanlığı\n"
                f"Yanıt ilk 500 kar: {response[:500]}"
            )


# ═══════════════════════════════════════════════════════════════════
# GRUP 5: RETRIEVAL HATALARI
# Beklenen: Yazım hatalı, kısaltmalı ve karşılaştırmalı sorgular
#           doğru belgeleri getirmeli.
# Mevcut durum: Bu sorgularda retrieval başarısız.
# ═══════════════════════════════════════════════════════════════════

class TestRetrievalBugs:
    """Retrieval başarısızlık hataları."""

    @pytest.mark.xfail(reason="BUG-G2-01: 'bilgiyasar mühendsligi' yazım hatası tolere edilemiyor")
    def test_typo_bilgisayar(self, rag):
        """G2-01: Yazım hatalı sorgu doğru bölümü bulmalı."""
        result = _query(rag, "gibtüde bilgiyasar mühendsligi var mı?")
        response = result["response"] or ""
        response_lower = response.lower()

        # Bilgisayar mühendisliği ile ilgili bilgi olmalı
        has_bilgisayar = any(kw in response_lower for kw in [
            "bilgisayar", "bilgisayar mühendisliği", "yazılım", "bmb",
        ])

        assert has_bilgisayar, (
            f"Yazım hatalı sorgu sonucu Bilgisayar Müh. bulunamadı!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

        # Yanlış birime yönlendirme olmamalı
        wrong_redirects = ["sbf dekanlığı", "ebelik", "sağlık bilimleri"]
        found_wrong = [w for w in wrong_redirects if w in response_lower]
        assert not found_wrong, (
            f"Yanlış birime yönlendirme: {found_wrong}\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

    @pytest.mark.xfail(reason="BUG-G4-03: MDBF kısaltması tanınmıyor, SBF/İlahiyat SWOT dönüyor")
    def test_abbreviation_mdbf(self, rag):
        """G4-03: MDBF kısaltması Mühendislik Fakültesi olarak çözülmeli."""
        result = _query(rag, "MDBF'nin kalite güvence süreçleri ve akreditasyon çalışmaları hakkında bilgi verin. SWOT analizi yapılmış mı?")
        response = result["response"] or ""
        response_lower = response.lower()

        # MDBF/Mühendislik ile ilgili bilgi olmalı
        has_mdbf_content = any(kw in response_lower for kw in [
            "mühendislik ve doğa bilimleri",
            "mühendislik fakültesi",
            "mdbf",
        ])

        assert has_mdbf_content, (
            f"MDBF ile ilgili bilgi yok! Kısaltma çözülemedi.\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

        # SBF veya İlahiyat SWOT'u dönmemeli (yanlış belge)
        wrong_docs = []
        if "sağlık bilimleri fakültesi" in response_lower and "swot" in response_lower:
            wrong_docs.append("SBF SWOT")
        if "ilahiyat" in response_lower and "swot" in response_lower:
            wrong_docs.append("İlahiyat SWOT")

        assert not wrong_docs, (
            f"Yanlış fakültenin SWOT analizi döndürüldü: {wrong_docs}\n"
            f"Beklenen: MDBF SWOT analizi\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

    @pytest.mark.xfail(reason="BUG-G3-02: Karşılaştırmalı sorguda her iki bölüm bilgisi gelmiyor")
    def test_comparison_hemsirelik_ebelik(self, rag):
        """G3-02: İki bölüm karşılaştırması her ikisi hakkında bilgi vermeli."""
        result = _query(rag, "Hemşirelik mi ebelik mi daha iyi? Hangisini seçmeliyim?")
        response = result["response"] or ""
        response_lower = response.lower()

        has_hemsirelik = "hemşirelik" in response_lower
        has_ebelik = "ebelik" in response_lower

        # Her iki bölüm de geçmeli
        assert has_hemsirelik, (
            f"'Hemşirelik' bilgisi yanıtta yok!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )
        assert has_ebelik, (
            f"'Ebelik' bilgisi yanıtta yok!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )

        # "Bilgi yok" dememeli — her iki bölüm de veritabanında mevcut
        has_no_info = "bilgi bulunmuyor" in response_lower or "bilgi yok" in response_lower
        assert not has_no_info, (
            f"Sistem 'bilgi yok' dedi — ama her iki bölüm de veritabanında mevcut!\n"
            f"Yanıt ilk 500 kar: {response[:500]}"
        )


# ═══════════════════════════════════════════════════════════════════
# GRUP 6: DUPLICATED SOURCES
# Beklenen: Aynı belge birden fazla kez kaynak olarak dönmemeli.
# Mevcut durum: Bazı sorgularda aynı belge 5 kez dönüyor.
# ═══════════════════════════════════════════════════════════════════

class TestDuplicateSourceBugs:
    """Kaynak belge tekrarı hataları."""

    @pytest.mark.xfail(reason="BUG: Aynı kaynak belge birden fazla kez dönüyor (RRF dedup sorunu)")
    def test_no_duplicate_sources(self, rag):
        """Kaynak listesinde aynı belge tekrar etmemeli."""
        # Bu sorgu E2E raporda 5 kez aynı belgeyi döndürmüştü (G8-02)
        result = _query(rag, "Sağlık Hizmetleri MYO'da hangi programlar var?")
        sources = result.get("sources", [])

        if not sources:
            pytest.skip("Kaynak belgesi döndürülmedi")

        # source_url bazlı tekrar kontrolü
        urls = [s.get("source_url") for s in sources if s.get("source_url")]
        unique_urls = set(urls)

        assert len(urls) == len(unique_urls), (
            f"Tekrarlı kaynak belgeler tespit edildi!\n"
            f"Toplam kaynak: {len(urls)}, Benzersiz: {len(unique_urls)}\n"
            f"URL'ler: {urls}"
        )


# ═══════════════════════════════════════════════════════════════════
# GRUP 7: GENEL YANIT KALİTESİ KONTROLLARI
# Bunlar xfail DEĞİL — her zaman geçmeli (regresyon koruması).
# ═══════════════════════════════════════════════════════════════════

class TestBaselineQuality:
    """Şu anda çalışan temel fonksiyonların regresyon koruması."""

    def test_erasmus_query_works(self, rag):
        """G2-02: Erasmus sorgusu başarılı dönmeli (baseline)."""
        result = _query(rag, "erasmus başvurusu nasıl yapılır nerden bilgi alabilirim")
        response = result["response"] or ""
        assert len(response) > 50, "Yanıt çok kısa"
        assert "erasmus" in response.lower(), "Yanıtta 'erasmus' geçmiyor"

    def test_fakulteler_query_works(self, rag):
        """G1-01: Fakülte listesi sorgusu başarılı dönmeli (baseline)."""
        result = _query(rag, "GİBTÜ'de hangi fakülteler var?")
        response = result["response"] or ""
        assert len(response) > 100, "Yanıt çok kısa"
        # En az 2 fakülte/birim geçmeli (LLM nondeterministik → eşik düşük)
        fakulte_keywords = [
            "mühendislik", "doğa bilimleri", "mdbf",
            "tıp", "sağlık", "ilahiyat",
            "iktisadi", "sosyal bilimler",
            "güzel sanatlar", "mimarlık",
            "fakülte", "yüksekokul", "enstitü",
        ]
        found = [kw for kw in fakulte_keywords if kw in response.lower()]
        assert len(found) >= 2, f"2'den az fakülte/birim bulundu: {found}"

    def test_devamsizlik_query_works(self, rag):
        """G10-02: Devamsızlık kuralı sorgusu başarılı dönmeli (baseline)."""
        result = _query(rag, "Devamsızlık sınırı nedir? Kaç ders kaçırırsam kalırım?")
        response = result["response"] or ""
        assert "devamsızlık" in response.lower(), "Yanıtta 'devamsızlık' geçmiyor"

    def test_nonexistent_department_rejected(self, rag):
        """G6-01: Olmayan bölüm sorusunda uydurma bilgi verilmemeli (baseline)."""
        result = _query(rag, "GİBTÜ'nün uzay mühendisliği bölümü var mı?")
        response = result["response"] or ""
        response_lower = response.lower()
        # "Uzay mühendisliği bölümü vardır" gibi onaylayıcı yanıt OLMAMALI
        false_positives = [
            "uzay mühendisliği bölümü bulunmaktadır",
            "uzay mühendisliği programı mevcuttur",
            "uzay mühendisliği bölümü açılmıştır",
        ]
        found = [fp for fp in false_positives if fp in response_lower]
        assert not found, f"Olmayan bölüm onaylandı: {found}"

    def test_response_is_turkish(self, rag):
        """G11-02: İngilizce soruya Türkçe yanıt vermeli (baseline)."""
        result = _query(rag, "What departments are available at this university?")
        response = result["response"] or ""
        turkish_chars = set("çğıöşüÇĞİÖŞÜ")
        has_turkish = any(c in response for c in turkish_chars)
        assert has_turkish, f"Yanıt Türkçe değil!\nYanıt ilk 200 kar: {response[:200]}"

    def test_response_not_empty(self, rag):
        """Herhangi bir sorguya boş yanıt dönmemeli."""
        result = _query(rag, "Bilgisayar mühendisliği bölümünün iletişim bilgileri nedir?")
        assert result["response"] is not None, "Yanıt None döndü"
        assert len(result["response"]) > 20, f"Yanıt çok kısa: {len(result['response'])} karakter"

    def test_sources_returned(self, rag):
        """Sorgulara kaynak belge döndürülmeli."""
        result = _query(rag, "Staj yapmam gerekiyor. Staj süreci nasıl işliyor?")
        assert len(result["sources"]) > 0, "Hiç kaynak belgesi döndürülmedi"


# ═══════════════════════════════════════════════════════════════════
# GRUP 8: VALIDATOR UNIT TESTLERİ
# Pipeline gerektirmeyen, doğrudan validate_response() fonksiyonunu
# test eden birim testleri.
# ═══════════════════════════════════════════════════════════════════

from app.services.response_validator import validate_response


class TestValidatorRules:
    """Response validator kurallarının birim testleri (pipeline gerektirmez)."""

    # ── Sabit kaynak belge örnekleri ──
    MOCK_SOURCES = [
        {
            "content": "Bilgisayar Mühendisliği bölümü hakkında bilgi. İletişim: bilgisayar@gibtu.edu.tr Telefon: 0342 909 75 00 Web: https://www.gibtu.edu.tr/bilgisayar",
            "source_url": "https://www.gibtu.edu.tr/bilgisayar",
        },
        {
            "content": "Erasmus başvuruları için https://erasmusbasvuru.ua.gov.tr adresini ziyaret ediniz.",
            "source_url": "https://www.gibtu.edu.tr/erasmus",
        },
    ]

    def test_gantep_url_removed(self):
        """gantep.edu.tr URL'si yanıttan kaldırılmalı."""
        response = "Yemekhane menüsü için https://www.gantep.edu.tr/yemekhane adresini ziyaret edin."
        result = validate_response(response, self.MOCK_SOURCES)
        assert "gantep.edu.tr" not in result
        assert "GİBTÜ dışı kaynak kaldırıldı" in result

    def test_sks_gantep_url_removed(self):
        """sks.gantep.edu.tr URL'si yanıttan kaldırılmalı."""
        response = "Yemek listesi: https://sks.gantep.edu.tr/yemek-listesi"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "sks.gantep.edu.tr" not in result
        assert "GİBTÜ dışı kaynak kaldırıldı" in result

    def test_fake_gibtu_url_removed(self):
        """Kaynakta olmayan gibtu.edu.tr URL'si kaldırılmalı."""
        response = "Detaylar: https://www.gibtu.edu.tr/sahte-sayfa-xyz"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "sahte-sayfa-xyz" not in result
        assert "www.gibtu.edu.tr" in result  # placeholder içinde geçmeli

    def test_real_gibtu_url_preserved(self):
        """Kaynakta birebir geçen gibtu.edu.tr URL'si korunmalı."""
        response = "Bölüm sayfası: https://www.gibtu.edu.tr/bilgisayar"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "https://www.gibtu.edu.tr/bilgisayar" in result

    def test_gibtu_email_not_in_source_removed(self):
        """Kaynakta geçmeyen gibtu.edu.tr e-postası kaldırılmalı."""
        response = "İletişim: sahte@gibtu.edu.tr"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "sahte@gibtu.edu.tr" not in result

    def test_gibtu_email_in_source_preserved(self):
        """Kaynakta geçen gibtu.edu.tr e-postası korunmalı."""
        response = "İletişim: bilgisayar@gibtu.edu.tr"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "bilgisayar@gibtu.edu.tr" in result

    def test_gantep_email_removed(self):
        """gantep.edu.tr e-postası her zaman kaldırılmalı."""
        response = "E-posta: info@gantep.edu.tr"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "gantep.edu.tr" not in result

    def test_source_verified_external_url_preserved(self):
        """Kaynakta geçen dış URL (erasmus) korunmalı."""
        response = "Başvuru: https://erasmusbasvuru.ua.gov.tr"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "erasmusbasvuru.ua.gov.tr" in result

    def test_hallucinated_phone_removed(self):
        """Kaynakta geçmeyen telefon kaldırılmalı."""
        response = "Telefon: (0322) 523 40 00"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "(0322) 523 40 00" not in result

    def test_source_verified_phone_preserved(self):
        """Kaynakta geçen telefon korunmalı."""
        response = "Telefon: 0342 909 75 00"
        result = validate_response(response, self.MOCK_SOURCES)
        assert "0342 909 75 00" in result
