"""
UniChat — E5 Migrasyon Doğrulama Scripti
multilingual-e5-base geçişi sonrası doğrulama testleri.

Kontrol eder:
  1. Embedding doluluk oranı (%100 hedef)
  2. Vektör boyutu doğrulaması (768-dim)
  3. Türkçe semantik arama testi (örnek sorgular)
  4. Cosine similarity dağılımı raporu

Kullanım:
    python verify_e5_migration.py
"""

import logging
import os
import sys
import numpy as np

import psycopg2
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(__file__))
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Türkçe test sorguları ve beklenen bağlam
TEST_QUERIES = [
    {
        "query": "GİBTÜ ders kaydı nasıl yapılır?",
        "expected_keywords": ["kayıt", "ders", "öğrenci"],
        "description": "Ders kaydı süreci",
    },
    {
        "query": "Erasmus başvuru şartları nelerdir?",
        "expected_keywords": ["erasmus", "başvuru"],
        "description": "Erasmus programı",
    },
    {
        "query": "Yemekhanede bugün ne var?",
        "expected_keywords": ["yemek"],
        "description": "Yemekhane menüsü",
    },
    {
        "query": "Bilgisayar mühendisliği bölümü hakkında bilgi",
        "expected_keywords": ["bilgisayar", "mühendisliğ"],
        "description": "Bölüm tanıtımı",
    },
    {
        "query": "Sınav yönetmeliği kuralları",
        "expected_keywords": ["sınav", "yönetmelik"],
        "description": "Mevzuat araması",
    },
]


def get_connection():
    settings = get_settings()
    return psycopg2.connect(settings.DATABASE_URL)


def check_embedding_coverage(conn, table_name: str) -> dict:
    """Embedding doluluk kontrolü."""
    logger.info("─" * 50)
    logger.info("📊 Test 1: Embedding Doluluk Kontrolü")

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        total = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE embedding IS NOT NULL")
        with_emb = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE embedding IS NULL")
        without_emb = cur.fetchone()[0]

    coverage = with_emb / total * 100 if total > 0 else 0
    result = {
        "total": total,
        "with_embedding": with_emb,
        "without_embedding": without_emb,
        "coverage_pct": coverage,
        "passed": without_emb == 0,
    }

    if result["passed"]:
        logger.info("  ✅ BAŞARILI: %d/%d chunk embedding'li (%.1f%%)", with_emb, total, coverage)
    else:
        logger.error("  ❌ BAŞARISIZ: %d chunk embedding'siz!", without_emb)

    return result


def check_vector_dimension(conn, table_name: str, expected_dim: int) -> dict:
    """Vektör boyutu doğrulaması."""
    logger.info("─" * 50)
    logger.info("📊 Test 2: Vektör Boyutu Doğrulaması (beklenen: %d)", expected_dim)

    with conn.cursor() as cur:
        # İlk 5 vektörün boyutunu kontrol et
        cur.execute(f"""
            SELECT id, array_length(embedding::real[], 1)
            FROM {table_name}
            WHERE embedding IS NOT NULL
            LIMIT 5
        """)
        samples = cur.fetchall()

    if not samples:
        logger.warning("  ⚠️ Hiç embedding bulunamadı!")
        return {"passed": False, "error": "No embeddings found"}

    dimensions = [dim for _, dim in samples]
    all_correct = all(d == expected_dim for d in dimensions)

    result = {
        "expected": expected_dim,
        "sample_dimensions": dimensions,
        "passed": all_correct,
    }

    if all_correct:
        logger.info("  ✅ BAŞARILI: Tüm örnekler %d boyutlu", expected_dim)
    else:
        logger.error("  ❌ BAŞARISIZ: Beklenmeyen boyutlar: %s", dimensions)

    return result


def check_semantic_search(conn, table_name: str, model: SentenceTransformer, prefix: str) -> dict:
    """Türkçe semantik arama testi."""
    logger.info("─" * 50)
    logger.info("📊 Test 3: Türkçe Semantik Arama Testi")

    results = []

    for tq in TEST_QUERIES:
        query = tq["query"]

        # Sorguyu embed et
        query_embedding = model.encode(f"{prefix}{query}", normalize_embeddings=True)

        # En yakın 3 chunk'ı bul
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, content,
                       1 - (embedding <=> %s::vector) as cosine_sim
                FROM {table_name}
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 3
            """, (query_embedding.tolist(), query_embedding.tolist()))
            matches = cur.fetchall()

        if not matches:
            logger.warning("  ⚠️ '%s' için sonuç bulunamadı", query)
            results.append({"query": query, "passed": False, "reason": "No results"})
            continue

        top_id, top_content, top_sim = matches[0]
        content_preview = top_content[:120].replace("\n", " ")

        # Beklenen anahtar kelimeleri kontrol et
        found_kw = [kw for kw in tq["expected_keywords"]
                     if kw.lower() in top_content.lower()]
        kw_match = len(found_kw) > 0

        passed = top_sim > 0.3 and kw_match

        results.append({
            "query": query,
            "description": tq["description"],
            "top_similarity": round(top_sim, 4),
            "keyword_match": kw_match,
            "found_keywords": found_kw,
            "passed": passed,
            "content_preview": content_preview,
        })

        status = "✅" if passed else "❌"
        logger.info("  %s '%s'", status, query)
        logger.info("     Benzerlik: %.4f | Anahtar kelime: %s | %s",
                     top_sim, "✓" if kw_match else "✗", content_preview[:80])

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    logger.info("  Sonuç: %d/%d test başarılı", passed_count, total_count)

    return {
        "queries": results,
        "passed_count": passed_count,
        "total_count": total_count,
        "passed": passed_count >= total_count * 0.6,  # %60 eşik
    }


def check_similarity_distribution(conn, table_name: str, model: SentenceTransformer, prefix: str) -> dict:
    """Cosine similarity dağılım raporu."""
    logger.info("─" * 50)
    logger.info("📊 Test 4: Similarity Dağılım Raporu")

    # Rastgele bir sorgu ile tüm benzerlik skorlarını al
    test_query = "üniversite eğitim programı"
    query_embedding = model.encode(f"{prefix}{test_query}", normalize_embeddings=True)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT 1 - (embedding <=> %s::vector) as cosine_sim
            FROM {table_name}
            WHERE embedding IS NOT NULL
            ORDER BY cosine_sim DESC
            LIMIT 100
        """, (query_embedding.tolist(),))
        scores = [row[0] for row in cur.fetchall()]

    if not scores:
        logger.warning("  ⚠️ Benzerlik skorları hesaplanamadı")
        return {"passed": False}

    scores_arr = np.array(scores)
    result = {
        "test_query": test_query,
        "sample_size": len(scores),
        "max": round(float(scores_arr.max()), 4),
        "min": round(float(scores_arr.min()), 4),
        "mean": round(float(scores_arr.mean()), 4),
        "std": round(float(scores_arr.std()), 4),
        "top_5_scores": [round(float(s), 4) for s in scores_arr[:5]],
        "passed": True,  # Bilgi amaçlı, doğrudan pass/fail yok
    }

    logger.info("  Sorgu: '%s'", test_query)
    logger.info("  Top 5 skor: %s", result["top_5_scores"])
    logger.info("  Dağılım: min=%.4f, max=%.4f, ort=%.4f, std=%.4f",
                result["min"], result["max"], result["mean"], result["std"])

    return result


def main():
    settings = get_settings()
    table_name = settings.HAYSTACK_TABLE_NAME

    logger.info("=" * 60)
    logger.info("UniChat — E5 Migrasyon Doğrulama")
    logger.info("=" * 60)
    logger.info("Model: %s", settings.EMBEDDING_MODEL)
    logger.info("Tablo: %s", table_name)
    logger.info("Boyut: %d", settings.EMBEDDING_DIMENSION)

    conn = get_connection()
    try:
        # Test 1: Embedding doluluk
        t1 = check_embedding_coverage(conn, table_name)

        # Test 2: Vektör boyutu
        t2 = check_vector_dimension(conn, table_name, settings.EMBEDDING_DIMENSION)

        # Model yükle (Test 3 & 4 için)
        logger.info("─" * 50)
        logger.info("📥 Model yükleniyor: %s", settings.EMBEDDING_MODEL)
        model = SentenceTransformer(settings.EMBEDDING_MODEL)

        # Test 3: Semantik arama
        t3 = check_semantic_search(conn, table_name, model, settings.EMBEDDING_QUERY_PREFIX)

        # Test 4: Similarity dağılımı
        t4 = check_similarity_distribution(conn, table_name, model, settings.EMBEDDING_QUERY_PREFIX)

        # Sonuç özeti
        logger.info("\n" + "=" * 60)
        logger.info("📋 DOĞRULAMA ÖZETİ")
        logger.info("=" * 60)

        all_passed = True
        tests = [
            ("Embedding Doluluk", t1["passed"]),
            ("Vektör Boyutu", t2["passed"]),
            ("Semantik Arama", t3["passed"]),
            ("Similarity Dağılımı", t4["passed"]),
        ]

        for name, passed in tests:
            status = "✅ BAŞARILI" if passed else "❌ BAŞARISIZ"
            logger.info("  %s: %s", name, status)
            if not passed:
                all_passed = False

        logger.info("-" * 60)
        if all_passed:
            logger.info("🎉 TÜM TESTLER BAŞARILI — Migrasyon doğrulandı!")
        else:
            logger.warning("⚠️ Bazı testler başarısız — yukarıdaki detayları inceleyin.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
