"""
UniChat — Kapsamlı Uçtan Uca Kullanıcı Deneyimi Testi
=====================================================
Bu script, sistemi gerçek bir son kullanıcı gibi test eder:
- Farklı kullanıcı profilleri (aday öğrenci, mevcut öğrenci, akademisyen, veli)
- Doğal dilde sorular, yazım hatalı, belirsiz, karşılaştırmalı, çok adımlı sorgular
- Cevap doğruluk kontrolü, kaynak tutarlılığı, halüsinasyon tespiti
- Retrieval kalitesi ve hybrid search başarısı
"""

import json
import time
import sys
import os
import re
import traceback
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ─────────────────────────────────────────────
# PHASE 1: Database Inspection
# ─────────────────────────────────────────────

def db_inspection():
    """Veritabanı durumunu kapsamlı inceler."""
    print("\n" + "="*80)
    print("PHASE 1: VERİTABANI İNCELEME")
    print("="*80)
    
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    
    results = {}
    
    # Total chunks
    cur.execute("SELECT COUNT(*) FROM haystack_docs")
    total = cur.fetchone()[0]
    results["total_chunks"] = total
    print(f"\n📊 Toplam chunk sayısı: {total}")
    
    # Category distribution
    cur.execute("""
        SELECT meta->>'category' as cat, COUNT(*) as cnt 
        FROM haystack_docs 
        WHERE meta->>'category' IS NOT NULL 
        GROUP BY cat 
        ORDER BY cnt DESC
    """)
    cat_rows = cur.fetchall()
    results["categories"] = {r[0]: r[1] for r in cat_rows}
    print(f"\n📂 Kategori Dağılımı ({len(cat_rows)} kategori):")
    for cat, cnt in cat_rows:
        print(f"   {cat}: {cnt} chunk")
    
    # doc_kind distribution
    cur.execute("""
        SELECT meta->>'doc_kind' as dk, COUNT(*) as cnt 
        FROM haystack_docs 
        WHERE meta->>'doc_kind' IS NOT NULL 
        GROUP BY dk 
        ORDER BY cnt DESC
    """)
    dk_rows = cur.fetchall()
    results["doc_kinds"] = {r[0]: r[1] for r in dk_rows}
    print(f"\n📑 doc_kind Dağılımı ({len(dk_rows)} tür):")
    for dk, cnt in dk_rows:
        print(f"   {dk}: {cnt} chunk")
    
    # Department distribution
    cur.execute("""
        SELECT meta->>'department' as dept, COUNT(*) as cnt 
        FROM haystack_docs 
        WHERE meta->>'department' IS NOT NULL 
        GROUP BY dept 
        ORDER BY cnt DESC
        LIMIT 20
    """)
    dept_rows = cur.fetchall()
    results["departments"] = {r[0]: r[1] for r in dept_rows}
    print(f"\n🏛️ Departman Dağılımı (top 20):")
    for dept, cnt in dept_rows:
        print(f"   {dept}: {cnt} chunk")
    
    # source_url coverage
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'source_url' IS NOT NULL AND meta->>'source_url' != ''")
    url_count = cur.fetchone()[0]
    results["source_url_coverage"] = f"{url_count}/{total} ({url_count/total*100:.1f}%)" if total > 0 else "0/0"
    print(f"\n🔗 source_url doluluk: {results['source_url_coverage']}")
    
    # title coverage
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'title' IS NOT NULL AND meta->>'title' != ''")
    title_count = cur.fetchone()[0]
    results["title_coverage"] = f"{title_count}/{total} ({title_count/total*100:.1f}%)" if total > 0 else "0/0"
    print(f"📝 title doluluk: {results['title_coverage']}")
    
    # Average content length
    cur.execute("SELECT AVG(LENGTH(content)), MIN(LENGTH(content)), MAX(LENGTH(content)) FROM haystack_docs")
    avg_len, min_len, max_len = cur.fetchone()
    results["content_length"] = {"avg": round(avg_len, 0) if avg_len else 0, "min": min_len, "max": max_len}
    print(f"📏 İçerik uzunluğu: avg={avg_len:.0f}, min={min_len}, max={max_len}")
    
    # Embedding coverage
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE embedding IS NOT NULL")
    emb_count = cur.fetchone()[0]
    results["embedding_coverage"] = f"{emb_count}/{total} ({emb_count/total*100:.1f}%)" if total > 0 else "0/0"
    print(f"🧮 Embedding doluluk: {results['embedding_coverage']}")
    
    # Very short chunks (potential quality issues)
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE LENGTH(content) < 50")
    short_count = cur.fetchone()[0]
    results["very_short_chunks"] = short_count
    print(f"⚠️ Çok kısa chunk (<50 kar): {short_count}")
    
    # Duplicate content check
    cur.execute("""
        SELECT content, COUNT(*) as cnt
        FROM haystack_docs
        GROUP BY content
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 5
    """)
    dup_rows = cur.fetchall()
    results["duplicate_chunks"] = len(dup_rows)
    if dup_rows:
        print(f"\n⚠️ Tekrarlı içerik ({len(dup_rows)} unique, en çok tekrar eden):")
        for content, cnt in dup_rows[:3]:
            preview = content[:80].replace("\n", " ")
            print(f"   [{cnt}x] {preview}...")
    
    # Sample check: chunks missing key metadata
    cur.execute("""
        SELECT COUNT(*) FROM haystack_docs 
        WHERE meta->>'category' IS NULL 
           OR meta->>'title' IS NULL 
           OR meta->>'source_url' IS NULL
    """)
    missing_meta = cur.fetchone()[0]
    results["missing_metadata_chunks"] = missing_meta
    print(f"\n🔍 Eksik metadata (cat/title/url herhangi biri NULL): {missing_meta} chunk")
    
    cur.close()
    conn.close()
    
    return results


# ─────────────────────────────────────────────
# PHASE 2: RAG Pipeline Test
# ─────────────────────────────────────────────

def build_test_pipeline():
    """RAG pipeline'ını test için oluşturur."""
    print("\n" + "="*80)
    print("PHASE 2: RAG PIPELINE OLUŞTURMA")
    print("="*80)
    
    from app.services.rag_service import RagService
    
    service = RagService()
    service.build_pipeline()
    print("✅ RAG pipeline hazır.")
    return service


def run_query(service, question, test_id=""):
    """Tek bir sorguyu çalıştırıp sonucu döner."""
    start = time.time()
    try:
        result = service.query(question)
        elapsed = time.time() - start
        return {
            "test_id": test_id,
            "question": question,
            "response": result["response"],
            "sources": result["sources"],
            "elapsed_sec": round(elapsed, 2),
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "test_id": test_id,
            "question": question,
            "response": None,
            "sources": [],
            "elapsed_sec": round(elapsed, 2),
            "error": str(e),
        }


# ─────────────────────────────────────────────
# TEST SENARYOLARI
# ─────────────────────────────────────────────

TEST_SCENARIOS = [
    # ═══════════════════════════════════════════
    # GRUP 1: DOĞRUDAN BİLGİ SORGULARI (Kolay)
    # ═══════════════════════════════════════════
    {
        "id": "G1-01",
        "profile": "Aday Öğrenci",
        "category": "Doğrudan Bilgi",
        "question": "GİBTÜ'de hangi fakülteler var?",
        "expected_behavior": "Tüm fakülteleri listelemeli (İlahiyat, MDBF, SBF, Tıp, İİSBF, GSMF)",
        "check_keywords": ["ilahiyat", "mühendislik", "sağlık", "tıp", "iktisadi", "güzel sanatlar"],
        "severity": "P0",
    },
    {
        "id": "G1-02",
        "profile": "Mevcut Öğrenci",
        "category": "Doğrudan Bilgi",
        "question": "Bilgisayar mühendisliği bölümünün iletişim bilgileri nedir?",
        "expected_behavior": "Bilg. Müh. bölüm telefonu, e-posta veya web adresi verilmeli",
        "check_keywords": ["bilgisayar", "mühendisliğ"],
        "severity": "P0",
    },
    {
        "id": "G1-03",
        "profile": "Veli",
        "category": "Doğrudan Bilgi",
        "question": "Üniversitenin adresi ve kampüse nasıl ulaşılır?",
        "expected_behavior": "Adres bilgisi ve ulaşım yönergesi verilmeli",
        "check_keywords": ["gaziantep", "adres"],
        "severity": "P0",
    },
    {
        "id": "G1-04",
        "profile": "Mevcut Öğrenci",
        "category": "Doğrudan Bilgi",
        "question": "Akademik takvim ne zaman başlıyor?",
        "expected_behavior": "Akademik takvim bilgisi veya takvim kaynağı verilmeli",
        "check_keywords": ["akademik", "takvim"],
        "severity": "P0",
    },
    {
        "id": "G1-05",
        "profile": "Mevcut Öğrenci",
        "category": "Doğrudan Bilgi",
        "question": "Bugün yemekhanede ne var?",
        "expected_behavior": "Yemek listesi bilgisi veya yemekhane kaynağı verilmeli",
        "check_keywords": ["yemek"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 2: YAZIM HATALI VE BELİRSİZ SORGULAR
    # ═══════════════════════════════════════════
    {
        "id": "G2-01",
        "profile": "Aday Öğrenci",
        "category": "Yazım Hatalı",
        "question": "gibtüde bilgiyasar mühendsligi var mı?",
        "expected_behavior": "Yazım hatasına rağmen Bilgisayar Mühendisliği bölümünü bulmalı",
        "check_keywords": ["bilgisayar", "mühendisliğ"],
        "severity": "P1",
    },
    {
        "id": "G2-02",
        "profile": "Mevcut Öğrenci",
        "category": "Yazım Hatalı",
        "question": "erasmus başvurusu nasıl yapılır nerden bilgi alabilirim",
        "expected_behavior": "Erasmus koordinatörlüğü ve başvuru süreci hakkında bilgi vermeli",
        "check_keywords": ["erasmus"],
        "severity": "P0",
    },
    {
        "id": "G2-03",
        "profile": "Mevcut Öğrenci",
        "category": "Belirsiz",
        "question": "kayıt işlemleri",
        "expected_behavior": "Çok kısa ve belirsiz sorguya rağmen öğrenci işleri/kayıt bilgisi vermeli veya yönlendirmeli",
        "check_keywords": ["kayıt", "öğrenci"],
        "severity": "P1",
    },
    {
        "id": "G2-04",
        "profile": "Aday Öğrenci",
        "category": "Belirsiz",
        "question": "burs",
        "expected_behavior": "Tek kelimelik sorguya karşı burs bilgisi vermeli veya SKS/Öğrenci İşleri yönlendirmeli",
        "check_keywords": ["burs"],
        "severity": "P1",
    },
    {
        "id": "G2-05",
        "profile": "Mevcut Öğrenci",
        "category": "Yazım Hatalı",
        "question": "kütüpahne çalışma saatleri ne zaman",
        "expected_behavior": "'kütüpahne' yazım hatasına rağmen kütüphane bilgisi vermeli",
        "check_keywords": ["kütüphane"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 3: KARŞILAŞTIRMALI SORGULAR
    # ═══════════════════════════════════════════
    {
        "id": "G3-01",
        "profile": "Aday Öğrenci",
        "category": "Karşılaştırmalı",
        "question": "Bilgisayar mühendisliği ile endüstri mühendisliği arasındaki fark nedir?",
        "expected_behavior": "İki bölüm hakkında bilgi vermeli, müfredat/program farklarını belirtmeli",
        "check_keywords": ["bilgisayar", "endüstri"],
        "severity": "P1",
    },
    {
        "id": "G3-02",
        "profile": "Aday Öğrenci",
        "category": "Karşılaştırmalı",
        "question": "Hemşirelik mi ebelik mi daha iyi? Hangisini seçmeliyim?",
        "expected_behavior": "Her iki program hakkında bilgi vermeli, kişisel tavsiye vermekten kaçınmalı",
        "check_keywords": ["hemşirelik", "ebelik"],
        "severity": "P2",
    },

    # ═══════════════════════════════════════════
    # GRUP 4: ÇOK ADIMLI / DERİN SORGULAR
    # ═══════════════════════════════════════════
    {
        "id": "G4-01",
        "profile": "Mevcut Öğrenci",
        "category": "Çok Adımlı",
        "question": "Erasmus'a gitmek istiyorum. Başvuru şartları neler, hangi ülkelerle anlaşma var ve başvuru için kime ulaşmalıyım?",
        "expected_behavior": "Erasmus başvuru bilgisi, anlaşmalı üniversiteler ve koordinatörlük iletişim bilgisi",
        "check_keywords": ["erasmus", "başvuru"],
        "severity": "P0",
    },
    {
        "id": "G4-02",
        "profile": "Mevcut Öğrenci",
        "category": "Çok Adımlı",
        "question": "Staj yapmam gerekiyor. Staj süreci nasıl işliyor, kaç gün staj yapmalıyım ve formu nereden alacağım?",
        "expected_behavior": "Staj bilgisi veya ilgili birime yönlendirme",
        "check_keywords": ["staj"],
        "severity": "P1",
    },
    {
        "id": "G4-03",
        "profile": "Akademisyen",
        "category": "Çok Adımlı",
        "question": "MDBF'nin kalite güvence süreçleri ve akreditasyon çalışmaları hakkında bilgi verin. SWOT analizi yapılmış mı?",
        "expected_behavior": "Kalite raporları, akreditasyon bilgisi ve SWOT analizi hakkında bilgi vermeli",
        "check_keywords": ["kalite", "mdbf"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 5: YÖNLENDİRME KALİTESİ
    # ═══════════════════════════════════════════
    {
        "id": "G5-01",
        "profile": "Mevcut Öğrenci",
        "category": "Yönlendirme",
        "question": "Transkript almak istiyorum, nereye başvurmam lazım?",
        "expected_behavior": "Öğrenci İşleri Daire Başkanlığı yönlendirmesi yapmalı",
        "check_keywords": ["öğrenci işleri"],
        "severity": "P0",
    },
    {
        "id": "G5-02",
        "profile": "Mevcut Öğrenci",
        "category": "Yönlendirme",
        "question": "Mezuniyet törenine katılmak için ne yapmalıyım?",
        "expected_behavior": "İlgili birime yönlendirme veya mezuniyet bilgisi",
        "check_keywords": ["mezuniyet"],
        "severity": "P2",
    },
    {
        "id": "G5-03",
        "profile": "Mevcut Öğrenci",
        "category": "Yönlendirme",
        "question": "Öğrenci kulüplerine nasıl üye olabilirim? Hangi kulüpler var?",
        "expected_behavior": "Topluluk/kulüp listesi ve SKS yönlendirmesi",
        "check_keywords": ["kulüp", "topluluk"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 6: HALÜSİNASYON TESTİ
    # ═══════════════════════════════════════════
    {
        "id": "G6-01",
        "profile": "Aday Öğrenci",
        "category": "Halüsinasyon",
        "question": "GİBTÜ'nün uzay mühendisliği bölümü var mı?",
        "expected_behavior": "Hayır veya 'elimde bu konuda bilgi yok' demeli. Uydurma bölüm bilgisi VERMEMELI.",
        "check_keywords": [],
        "negative_keywords": ["uzay mühendisliği bölümü bulunmaktadır", "uzay mühendisliği programı mevcuttur"],
        "severity": "P0",
    },
    {
        "id": "G6-02",
        "profile": "Mevcut Öğrenci",
        "category": "Halüsinasyon",
        "question": "GİBTÜ rektörünün telefon numarası nedir?",
        "expected_behavior": "Belgede varsa doğru bilgiyi vermeli, yoksa uydurmamalı",
        "check_keywords": [],
        "severity": "P1",
    },
    {
        "id": "G6-03",
        "profile": "Farklı",
        "category": "Halüsinasyon",
        "question": "GİBTÜ'nün dünya sıralaması kaçıncı?",
        "expected_behavior": "Belgede yoksa bilmediğini belirtmeli, uydurma sıralama VERMEMELI",
        "check_keywords": [],
        "negative_keywords": ["dünya sıralamasında"],
        "severity": "P0",
    },

    # ═══════════════════════════════════════════
    # GRUP 7: GUARDRAILS / KAPSAM DIŞI
    # ═══════════════════════════════════════════
    {
        "id": "G7-01",
        "profile": "Farklı",
        "category": "Kapsam Dışı",
        "question": "Türkiye'nin başkenti neresidir?",
        "expected_behavior": "Üniversite dışı konu olduğunu belirtmeli, cevap vermemeli",
        "check_keywords": ["üniversite"],
        "severity": "P0",
    },
    {
        "id": "G7-02",
        "profile": "Farklı",
        "category": "Kapsam Dışı",
        "question": "Bana bir Python kodu yazar mısın?",
        "expected_behavior": "Üniversite dışı konu olduğunu belirtmeli",
        "check_keywords": [],
        "severity": "P1",
    },
    {
        "id": "G7-03",
        "profile": "Farklı",
        "category": "Kapsam Dışı",
        "question": "Sen hangi yapay zeka modelisin?",
        "expected_behavior": "UniChat asistanı olduğunu belirtmeli, model detaylarını paylaşmamalı",
        "check_keywords": ["unichat"],
        "severity": "P2",
    },

    # ═══════════════════════════════════════════
    # GRUP 8: SPESİFİK VERİ DOĞRULAMA
    # ═══════════════════════════════════════════
    {
        "id": "G8-01",
        "profile": "Mevcut Öğrenci",
        "category": "Spesifik Veri",
        "question": "Tıp fakültesinde hangi ana bilim dalları var?",
        "expected_behavior": "Tıp fakültesi yapısı/bölümleri/anabilim dalları hakkında bilgi",
        "check_keywords": ["tıp"],
        "severity": "P1",
    },
    {
        "id": "G8-02",
        "profile": "Mevcut Öğrenci",
        "category": "Spesifik Veri",
        "question": "Sağlık Hizmetleri MYO'da hangi programlar var?",
        "expected_behavior": "Ameliyathane, Fizyoterapi, Tıbbi Lab., Yaşlı Bakım, İlk ve Acil Yardım programlarını listelemelimi",
        "check_keywords": ["ameliyathane", "fizyoterapi", "tıbbi lab"],
        "severity": "P1",
    },
    {
        "id": "G8-03",
        "profile": "Mevcut Öğrenci",
        "category": "Spesifik Veri",
        "question": "Mütercim tercümanlık bölümünün müfredatı nasıl?",
        "expected_behavior": "Mütercim Tercümanlık bölümü müfredat bilgisi veya yönlendirme",
        "check_keywords": ["mütercim", "tercümanlık"],
        "severity": "P1",
    },
    {
        "id": "G8-04",
        "profile": "Aday Öğrenci",
        "category": "Spesifik Veri",
        "question": "Gastronomi bölümü hakkında bilgi verin",
        "expected_behavior": "Gastronomi ve Mutfak Sanatları bölümü bilgileri",
        "check_keywords": ["gastronomi"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 9: DUYURULAR VE GÜNCEL BİLGİ
    # ═══════════════════════════════════════════
    {
        "id": "G9-01",
        "profile": "Mevcut Öğrenci",
        "category": "Duyurular",
        "question": "Son duyurular neler?",
        "expected_behavior": "Duyuru bilgisi veya duyuru kaynağına yönlendirme",
        "check_keywords": ["duyuru"],
        "severity": "P1",
    },
    {
        "id": "G9-02",
        "profile": "Mevcut Öğrenci",
        "category": "Duyurular",
        "question": "Sınav tarihleri ne zaman açıklanacak?",
        "expected_behavior": "Sınav bilgisi veya akademik takvim/öğrenci işleri yönlendirme",
        "check_keywords": ["sınav"],
        "severity": "P1",
    },

    # ═══════════════════════════════════════════
    # GRUP 10: MEVZUAT VE YÖNETMELİK
    # ═══════════════════════════════════════════
    {
        "id": "G10-01",
        "profile": "Mevcut Öğrenci",
        "category": "Mevzuat",
        "question": "Sınav yönetmeliği ne diyor? Sınavdan kaç alırsam geçerim?",
        "expected_behavior": "Sınav yönetmeliği bilgisi, geçme notu/başarı kriteri",
        "check_keywords": ["sınav", "yönetmelik"],
        "severity": "P0",
    },
    {
        "id": "G10-02",
        "profile": "Mevcut Öğrenci",
        "category": "Mevzuat",
        "question": "Devamsızlık sınırı nedir? Kaç ders kaçırırsam kalırım?",
        "expected_behavior": "Devamsızlık kuralı hakkında yönetmelik bilgisi",
        "check_keywords": ["devamsızlık"],
        "severity": "P0",
    },

    # ═══════════════════════════════════════════
    # GRUP 11: İNGİLİZCE HAZIRLIK VE DİL
    # ═══════════════════════════════════════════
    {
        "id": "G11-01",
        "profile": "Aday Öğrenci",
        "category": "Dil",
        "question": "İngilizce hazırlık sınıfı zorunlu mu? Muafiyet sınavı var mı?",
        "expected_behavior": "YDYO/hazırlık bilgisi, muafiyet süreci",
        "check_keywords": ["hazırlık", "ingilizce"],
        "severity": "P1",
    },
    {
        "id": "G11-02",
        "profile": "Mevcut Öğrenci",
        "category": "Dil",
        "question": "What departments are available at this university?",
        "expected_behavior": "Türkçe cevap vermeli (guardrail kuralı). Fakülte/bölüm listesi verebilir.",
        "check_keywords": [],
        "severity": "P2",
    },
]


def evaluate_result(scenario, result):
    """Sonucu senaryoya göre değerlendirir."""
    evaluation = {
        "test_id": scenario["id"],
        "category": scenario["category"],
        "profile": scenario["profile"],
        "severity": scenario["severity"],
        "question": scenario["question"],
        "response_length": len(result["response"]) if result["response"] else 0,
        "elapsed_sec": result["elapsed_sec"],
        "source_count": len(result["sources"]),
        "issues": [],
        "score": 0,  # 0-10 scale
    }
    
    if result["error"]:
        evaluation["issues"].append(f"❌ HATA: {result['error']}")
        evaluation["score"] = 0
        return evaluation
    
    response = result["response"] or ""
    response_lower = response.lower()
    
    score = 5  # baseline
    
    # 1. Check keywords
    check_kw = scenario.get("check_keywords", [])
    found_kw = [kw for kw in check_kw if kw.lower() in response_lower]
    missing_kw = [kw for kw in check_kw if kw.lower() not in response_lower]
    
    if check_kw:
        kw_ratio = len(found_kw) / len(check_kw)
        if kw_ratio >= 0.8:
            score += 2
        elif kw_ratio >= 0.5:
            score += 1
        else:
            score -= 2
            evaluation["issues"].append(f"⚠️ Eksik anahtar kelimeler: {missing_kw}")
    
    # 2. Check negative keywords (hallucination markers)
    neg_kw = scenario.get("negative_keywords", [])
    found_neg = [kw for kw in neg_kw if kw.lower() in response_lower]
    if found_neg:
        score -= 3
        evaluation["issues"].append(f"🔴 HALÜSİNASYON ŞÜPHESİ: Belgede olmaması gereken ifadeler bulundu: {found_neg}")
    
    # 3. Response length check
    if len(response) < 30:
        score -= 2
        evaluation["issues"].append("⚠️ Yanıt çok kısa (<30 karakter)")
    elif len(response) > 5000:
        score -= 1
        evaluation["issues"].append("⚠️ Yanıt çok uzun (>5000 karakter)")
    
    # 4. Source quality check
    if result["sources"]:
        # Check if sources have valid URLs
        urls = [s.get("source_url") for s in result["sources"] if s.get("source_url")]
        if urls:
            score += 1
        else:
            evaluation["issues"].append("⚠️ Kaynak belgelerde URL yok")
        
        # Check if categories match expected context
        cats = [s.get("category") for s in result["sources"] if s.get("category")]
        if cats:
            evaluation["source_categories"] = list(set(cats))
    else:
        evaluation["issues"].append("⚠️ Hiç kaynak belge döndürülmedi")
    
    # 5. Turkish check
    if scenario.get("id") == "G11-02":
        # Should respond in Turkish even for English query
        turkish_chars = set("çğıöşüÇĞİÖŞÜ")
        if not any(c in response for c in turkish_chars):
            score -= 2
            evaluation["issues"].append("⚠️ İngilizce soruya Türkçe yanıt vermeli ama Türkçe karakterler yok")
    
    # 6. Markdown formatting check
    has_markdown = any(marker in response for marker in ["**", "##", "- ", "* ", "[", "]("])
    if has_markdown:
        score += 1
    else:
        evaluation["issues"].append("ℹ️ Markdown formatı kullanılmamış")
    
    # 7. Contact/directing info check
    has_contact_info = any(marker in response_lower for marker in ["telefon", "e-posta", "mail", "@", "web", "http", "başvur", "birim"])
    if has_contact_info:
        score += 1
    
    evaluation["score"] = max(0, min(10, score))
    
    # Determine verdict
    if evaluation["score"] >= 7:
        evaluation["verdict"] = "✅ BAŞARILI"
    elif evaluation["score"] >= 4:
        evaluation["verdict"] = "⚠️ KISMİ BAŞARILI"
    else:
        evaluation["verdict"] = "❌ BAŞARISIZ"
    
    return evaluation


def run_all_tests(service):
    """Tüm test senaryolarını çalıştırır."""
    print("\n" + "="*80)
    print("PHASE 3: KULLANICI DENEYİMİ TESTİ")
    print(f"Toplam: {len(TEST_SCENARIOS)} senaryo")
    print("="*80)
    
    all_results = []
    all_evaluations = []
    
    for i, scenario in enumerate(TEST_SCENARIOS):
        test_id = scenario["id"]
        print(f"\n{'─'*60}")
        print(f"[{i+1}/{len(TEST_SCENARIOS)}] {test_id} | {scenario['category']} | {scenario['profile']}")
        print(f"  Soru: {scenario['question']}")
        
        result = run_query(service, scenario["question"], test_id)
        evaluation = evaluate_result(scenario, result)
        
        all_results.append(result)
        all_evaluations.append(evaluation)
        
        # Print summary
        print(f"  {evaluation['verdict']} (Skor: {evaluation['score']}/10, {result['elapsed_sec']}s, {evaluation['source_count']} kaynak)")
        if result["response"]:
            preview = result["response"][:200].replace("\n", " ")
            print(f"  Yanıt: {preview}...")
        if evaluation["issues"]:
            for issue in evaluation["issues"]:
                print(f"  {issue}")
    
    return all_results, all_evaluations


# ─────────────────────────────────────────────
# PHASE 4: RAPOR OLUŞTURMA
# ─────────────────────────────────────────────

def generate_report(db_info, evaluations, results):
    """Kapsamlı markdown rapor oluşturur."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Category stats
    cat_stats = {}
    for ev in evaluations:
        cat = ev["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "pass": 0, "partial": 0, "fail": 0, "scores": []}
        cat_stats[cat]["total"] += 1
        cat_stats[cat]["scores"].append(ev["score"])
        if ev["score"] >= 7:
            cat_stats[cat]["pass"] += 1
        elif ev["score"] >= 4:
            cat_stats[cat]["partial"] += 1
        else:
            cat_stats[cat]["fail"] += 1
    
    # Overall stats
    total_tests = len(evaluations)
    pass_count = sum(1 for ev in evaluations if ev["score"] >= 7)
    partial_count = sum(1 for ev in evaluations if 4 <= ev["score"] < 7)
    fail_count = sum(1 for ev in evaluations if ev["score"] < 4)
    avg_score = sum(ev["score"] for ev in evaluations) / total_tests if total_tests else 0
    avg_time = sum(ev["elapsed_sec"] for ev in evaluations) / total_tests if total_tests else 0
    
    # Severity stats
    p0_evals = [ev for ev in evaluations if ev["severity"] == "P0"]
    p0_pass = sum(1 for ev in p0_evals if ev["score"] >= 7)
    
    report_lines = []
    report_lines.append(f"# UniChat — Uçtan Uca Kullanıcı Deneyimi Test Raporu")
    report_lines.append(f"")
    report_lines.append(f"> **Tarih:** {timestamp}")
    report_lines.append(f"> **Test Sayısı:** {total_tests} senaryo")
    report_lines.append(f"> **Model:** gemma3:4b-it-qat (Ollama)")
    report_lines.append(f"> **Embedding:** multilingual-e5-base")
    report_lines.append(f"> **Veritabanı:** {db_info['total_chunks']} chunk, {len(db_info.get('categories', {}))} kategori")
    report_lines.append(f"")
    
    # Executive Summary
    report_lines.append(f"---")
    report_lines.append(f"## Özet Puan Kartı")
    report_lines.append(f"")
    report_lines.append(f"| Metrik | Değer |")
    report_lines.append(f"|--------|-------|")
    report_lines.append(f"| Genel Başarı Oranı | **{pass_count}/{total_tests}** ({pass_count/total_tests*100:.0f}%) |")
    report_lines.append(f"| Ortalama Skor | **{avg_score:.1f}/10** |")
    report_lines.append(f"| ✅ Başarılı | {pass_count} |")
    report_lines.append(f"| ⚠️ Kısmi Başarılı | {partial_count} |")
    report_lines.append(f"| ❌ Başarısız | {fail_count} |")
    report_lines.append(f"| P0 Kritik Testler | {p0_pass}/{len(p0_evals)} başarılı |")
    report_lines.append(f"| Ortalama Yanıt Süresi | {avg_time:.1f}s |")
    report_lines.append(f"")
    
    # DB Summary
    report_lines.append(f"---")
    report_lines.append(f"## Veritabanı Durumu")
    report_lines.append(f"")
    report_lines.append(f"| Metrik | Değer |")
    report_lines.append(f"|--------|-------|")
    report_lines.append(f"| Toplam Chunk | {db_info['total_chunks']} |")
    report_lines.append(f"| Kategori Sayısı | {len(db_info.get('categories', {}))} |")
    report_lines.append(f"| source_url Doluluk | {db_info.get('source_url_coverage', 'N/A')} |")
    report_lines.append(f"| title Doluluk | {db_info.get('title_coverage', 'N/A')} |")
    report_lines.append(f"| Embedding Doluluk | {db_info.get('embedding_coverage', 'N/A')} |")
    report_lines.append(f"| Çok Kısa Chunk (<50 kar) | {db_info.get('very_short_chunks', 'N/A')} |")
    report_lines.append(f"| Tekrarlı İçerik | {db_info.get('duplicate_chunks', 'N/A')} kayıt |")
    report_lines.append(f"| Eksik Metadata | {db_info.get('missing_metadata_chunks', 'N/A')} chunk |")
    report_lines.append(f"")
    
    if db_info.get("categories"):
        report_lines.append(f"### Kategori Dağılımı")
        report_lines.append(f"")
        report_lines.append(f"| Kategori | Chunk Sayısı |")
        report_lines.append(f"|----------|-------------|")
        for cat, cnt in sorted(db_info["categories"].items(), key=lambda x: -x[1]):
            report_lines.append(f"| {cat} | {cnt} |")
        report_lines.append(f"")
    
    if db_info.get("doc_kinds"):
        report_lines.append(f"### doc_kind Dağılımı")
        report_lines.append(f"")
        report_lines.append(f"| doc_kind | Chunk Sayısı |")
        report_lines.append(f"|----------|-------------|")
        for dk, cnt in sorted(db_info["doc_kinds"].items(), key=lambda x: -x[1]):
            report_lines.append(f"| {dk} | {cnt} |")
        report_lines.append(f"")
    
    # Category-level results
    report_lines.append(f"---")
    report_lines.append(f"## Kategori Bazlı Sonuçlar")
    report_lines.append(f"")
    report_lines.append(f"| Kategori | Toplam | ✅ | ⚠️ | ❌ | Ort. Skor |")
    report_lines.append(f"|----------|--------|----|----|----|-----------:|")
    for cat, stats in sorted(cat_stats.items()):
        avg = sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0
        report_lines.append(f"| {cat} | {stats['total']} | {stats['pass']} | {stats['partial']} | {stats['fail']} | {avg:.1f}/10 |")
    report_lines.append(f"")
    
    # Detailed test results
    report_lines.append(f"---")
    report_lines.append(f"## Detaylı Test Sonuçları")
    report_lines.append(f"")
    
    for ev, res in zip(evaluations, results):
        report_lines.append(f"### {ev['test_id']} — {ev['category']} ({ev['severity']}) {ev['verdict']}")
        report_lines.append(f"")
        report_lines.append(f"- **Profil:** {ev['profile']}")
        report_lines.append(f"- **Soru:** {ev['question']}")
        
        # Find the scenario
        scenario = next((s for s in TEST_SCENARIOS if s["id"] == ev["test_id"]), None)
        if scenario:
            report_lines.append(f"- **Beklenen:** {scenario['expected_behavior']}")
        
        report_lines.append(f"- **Skor:** {ev['score']}/10 | **Süre:** {ev['elapsed_sec']}s | **Kaynak:** {ev['source_count']} belge")
        
        if ev.get("issues"):
            report_lines.append(f"- **Sorunlar:**")
            for issue in ev["issues"]:
                report_lines.append(f"  - {issue}")
        
        if res.get("response"):
            resp_preview = res["response"][:500].replace("\n", "\n  > ")
            report_lines.append(f"")
            report_lines.append(f"<details>")
            report_lines.append(f"<summary>Yanıt Önizleme (ilk 500 kar)</summary>")
            report_lines.append(f"")
            report_lines.append(f"  > {resp_preview}")
            report_lines.append(f"")
            report_lines.append(f"</details>")
        
        if res.get("sources"):
            report_lines.append(f"")
            report_lines.append(f"<details>")
            report_lines.append(f"<summary>Kaynaklar ({len(res['sources'])} belge)</summary>")
            report_lines.append(f"")
            for i, src in enumerate(res["sources"][:5]):
                title = src.get("title", "—")
                url = src.get("source_url", "—")
                cat = src.get("category", "—")
                dk = src.get("doc_kind", "—")
                report_lines.append(f"  {i+1}. **{title}** [{cat}/{dk}] — {url}")
            report_lines.append(f"")
            report_lines.append(f"</details>")
        
        report_lines.append(f"")
    
    # ─── CRITICAL FAILURES ───
    report_lines.append(f"---")
    report_lines.append(f"## 🔴 Kritik Hatalar ve Başarısız Testler")
    report_lines.append(f"")
    
    failures = [ev for ev in evaluations if ev["score"] < 4]
    if failures:
        for ev in failures:
            scenario = next((s for s in TEST_SCENARIOS if s["id"] == ev["test_id"]), None)
            report_lines.append(f"### {ev['test_id']} — {ev['category']} ({ev['severity']})")
            report_lines.append(f"- **Soru:** {ev['question']}")
            if scenario:
                report_lines.append(f"- **Beklenen:** {scenario['expected_behavior']}")
            report_lines.append(f"- **Skor:** {ev['score']}/10")
            report_lines.append(f"- **Sorunlar:** {'; '.join(ev.get('issues', ['Bilinmiyor']))}")
            report_lines.append(f"")
    else:
        report_lines.append(f"Kritik hata bulunmadı. ✅")
        report_lines.append(f"")
    
    # ─── STRENGTHS ───
    report_lines.append(f"---")
    report_lines.append(f"## 💪 Güçlü Yönler")
    report_lines.append(f"")
    
    strengths = []
    if avg_score >= 6:
        strengths.append("Genel yanıt kalitesi iyi seviyede")
    if p0_pass / max(len(p0_evals), 1) >= 0.7:
        strengths.append(f"P0 kritik testlerin {p0_pass}/{len(p0_evals)} kadarı başarılı")
    if db_info.get("total_chunks", 0) > 5000:
        strengths.append(f"Zengin veri tabanı: {db_info['total_chunks']} chunk, {len(db_info.get('categories', {}))} kategori")
    
    high_cats = [cat for cat, stats in cat_stats.items() if sum(stats["scores"])/len(stats["scores"]) >= 7]
    if high_cats:
        strengths.append(f"Yüksek performanslı kategoriler: {', '.join(high_cats)}")
    
    for s in strengths:
        report_lines.append(f"- {s}")
    if not strengths:
        report_lines.append(f"- (Belirgin güçlü yön tespit edilemedi)")
    report_lines.append(f"")
    
    # ─── IMPROVEMENT RECOMMENDATIONS ───
    report_lines.append(f"---")
    report_lines.append(f"## 📋 Önceliklendirilmiş İyileştirme Önerileri")
    report_lines.append(f"")
    
    recommendations = []
    
    # Based on test results
    low_cats = [(cat, stats) for cat, stats in cat_stats.items() if sum(stats["scores"])/len(stats["scores"]) < 5]
    if low_cats:
        for cat, stats in low_cats:
            avg = sum(stats["scores"])/len(stats["scores"])
            recommendations.append({
                "priority": "P0",
                "area": cat,
                "description": f"'{cat}' kategorisinde ortalama skor {avg:.1f}/10 — ciddi iyileştirme gerekli",
            })
    
    # Hallucination issues
    halluc_fails = [ev for ev in evaluations if ev["category"] == "Halüsinasyon" and ev["score"] < 7]
    if halluc_fails:
        recommendations.append({
            "priority": "P0",
            "area": "Halüsinasyon Kontrolü",
            "description": f"{len(halluc_fails)} halüsinasyon testinde sorun: Prompt'a daha güçlü guardrail kuralları eklenebilir",
        })
    
    # Missing metadata
    if db_info.get("missing_metadata_chunks", 0) > 50:
        recommendations.append({
            "priority": "P1",
            "area": "Metadata Kalitesi",
            "description": f"{db_info['missing_metadata_chunks']} chunk'ta eksik metadata — kaynak güvenirliğini düşürüyor",
        })
    
    # Slow responses
    slow_tests = [ev for ev in evaluations if ev["elapsed_sec"] > 60]
    if slow_tests:
        recommendations.append({
            "priority": "P1",
            "area": "Performans",
            "description": f"{len(slow_tests)} testte yanıt süresi 60s üzerinde — embedding cache veya retriever optimizasyonu gerekli",
        })
    
    # Guardrail issues
    guardrail_fails = [ev for ev in evaluations if ev["category"] == "Kapsam Dışı" and ev["score"] < 7]
    if guardrail_fails:
        recommendations.append({
            "priority": "P1",
            "area": "Guardrails",
            "description": f"{len(guardrail_fails)} kapsam dışı soruya yanlış yanıt — prompt guardrails güçlendirilmeli",
        })
    
    # Source relevance
    no_source = [ev for ev in evaluations if ev["source_count"] == 0]
    if no_source:
        recommendations.append({
            "priority": "P1",
            "area": "Retrieval",
            "description": f"{len(no_source)} testte kaynak belge bulunamadı — retriever kapsamı artırılmalı",
        })
    
    # Duplicate chunks
    if db_info.get("duplicate_chunks", 0) > 0:
        recommendations.append({
            "priority": "P2",
            "area": "Veri Temizliği",
            "description": f"{db_info['duplicate_chunks']} tekrarlı içerik — DuplicatePolicy.OVERWRITE kontrol edilmeli",
        })
    
    recommendations.sort(key=lambda x: x["priority"])
    
    report_lines.append(f"| Öncelik | Alan | Açıklama |")
    report_lines.append(f"|---------|------|----------|")
    for r in recommendations:
        report_lines.append(f"| **{r['priority']}** | {r['area']} | {r['description']} |")
    report_lines.append(f"")
    
    if not recommendations:
        report_lines.append(f"(Kritik iyileştirme önerisi tespit edilmedi)")
    
    return "\n".join(report_lines)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  UniChat — Uçtan Uca Kullanıcı Deneyimi Test Suite         ║")
    print("║  Tarih: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    
    # Phase 1: DB inspection
    db_info = db_inspection()
    
    # Phase 2: Build pipeline
    service = build_test_pipeline()
    
    # Phase 3: Run tests
    results, evaluations = run_all_tests(service)
    
    # Phase 4: Generate report
    print("\n" + "="*80)
    print("PHASE 4: RAPOR OLUŞTURMA")
    print("="*80)
    
    report = generate_report(db_info, evaluations, results)
    
    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "..", "doc", "e2e_test_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n📄 Rapor kaydedildi: {report_path}")
    
    # Save raw results as JSON
    json_path = os.path.join(os.path.dirname(__file__), "..", "doc", "e2e_test_results.json")
    raw_data = {
        "timestamp": datetime.now().isoformat(),
        "db_info": db_info,
        "results": results,
        "evaluations": evaluations,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    print(f"📊 Ham veriler kaydedildi: {json_path}")
    
    # Print summary
    total = len(evaluations)
    passed = sum(1 for ev in evaluations if ev["score"] >= 7)
    partial = sum(1 for ev in evaluations if 4 <= ev["score"] < 7)
    failed = sum(1 for ev in evaluations if ev["score"] < 4)
    avg = sum(ev["score"] for ev in evaluations) / total if total else 0
    
    print(f"\n{'='*60}")
    print(f"📊 SONUÇ: {passed}✅ / {partial}⚠️ / {failed}❌  |  Ort. Skor: {avg:.1f}/10")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
