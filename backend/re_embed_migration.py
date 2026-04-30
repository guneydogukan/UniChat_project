"""
UniChat — Embedding Model Migrasyon Scripti
all-mpnet-base-v2 → intfloat/multilingual-e5-base

Bu script veritabanındaki tüm mevcut chunk'ları yeni embedding modeliyle
yeniden vektörize eder. Raw text (content kolonu) korunduğundan yeniden
scraping gerekli değildir.

Kullanım:
    python re_embed_migration.py                  # Tam migrasyon
    python re_embed_migration.py --dry-run        # Sadece rapor
    python re_embed_migration.py --batch-size 32  # Batch boyutunu ayarla
"""

import argparse
import logging
import os
import sys
import time

import psycopg2
from sentence_transformers import SentenceTransformer

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.dirname(__file__))
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="UniChat Embedding Migrasyon Scripti")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Veritabanını değiştirmeden kaç chunk etkileneceğini gösterir",
    )
    parser.add_argument(
        "--batch-size", type=int, default=64,
        help="Embedding batch boyutu (default: 64)",
    )
    return parser.parse_args()


def get_connection():
    """Veritabanına bağlanır."""
    settings = get_settings()
    return psycopg2.connect(settings.DATABASE_URL)


def get_chunk_count(conn, table_name: str) -> int:
    """Toplam chunk sayısını döndürür."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cur.fetchone()[0]


def get_embedding_stats(conn, table_name: str) -> dict:
    """Embedding istatistiklerini döndürür."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        total = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE embedding IS NOT NULL")
        with_embedding = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE embedding IS NULL")
        without_embedding = cur.fetchone()[0]

    return {
        "total": total,
        "with_embedding": with_embedding,
        "without_embedding": without_embedding,
    }


def drop_hnsw_index(conn, table_name: str):
    """HNSW vektör indeksini drop eder (performans için)."""
    logger.info("🔧 HNSW indeksi drop ediliyor...")
    with conn.cursor() as cur:
        # Haystack PgVector'ün oluşturduğu indeks adı
        index_name = f"haystack_hnsw_index"
        cur.execute(f"""
            SELECT indexname FROM pg_indexes
            WHERE tablename = %s AND indexname LIKE '%%hnsw%%'
        """, (table_name,))
        indexes = cur.fetchall()

        if indexes:
            for (idx_name,) in indexes:
                logger.info("  Dropping index: %s", idx_name)
                cur.execute(f"DROP INDEX IF EXISTS {idx_name}")
            conn.commit()
            logger.info("  ✅ HNSW indeks(ler)i silindi")
        else:
            logger.info("  ℹ️ HNSW indeksi bulunamadı, atlanıyor")


def rebuild_hnsw_index(conn, table_name: str, dimension: int):
    """HNSW vektör indeksini yeniden oluşturur."""
    logger.info("🔧 HNSW indeksi yeniden oluşturuluyor...")
    with conn.cursor() as cur:
        index_name = "haystack_hnsw_index"
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {table_name}
            USING hnsw (embedding vector_cosine_ops)
        """)
        conn.commit()
    logger.info("  ✅ HNSW indeksi oluşturuldu: %s", index_name)


def nullify_embeddings(conn, table_name: str):
    """Tüm mevcut embedding'leri NULL yapar."""
    logger.info("🗑️ Mevcut embedding'ler NULL yapılıyor...")
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {table_name} SET embedding = NULL")
        affected = cur.rowcount
        conn.commit()
    logger.info("  ✅ %d satır güncellendi", affected)
    return affected


def re_embed_all(conn, table_name: str, model: SentenceTransformer, batch_size: int, prefix: str):
    """
    Tüm chunk'ları batch halinde yeniden embed eder.

    Args:
        conn: Veritabanı bağlantısı
        table_name: Tablo adı
        model: SentenceTransformer modeli
        batch_size: Batch boyutu
        prefix: E5 passage prefix'i ("passage: ")
    """
    logger.info("📊 Toplam chunk sayısı alınıyor...")

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        total = cur.fetchone()[0]

    logger.info("📦 %d chunk yeniden embed edilecek (batch_size=%d)", total, batch_size)

    offset = 0
    embedded_count = 0
    start_time = time.time()

    while offset < total:
        # Batch oku
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, content FROM {table_name} ORDER BY id LIMIT %s OFFSET %s",
                (batch_size, offset),
            )
            batch = cur.fetchall()

        if not batch:
            break

        ids = [row[0] for row in batch]
        contents = [row[1] for row in batch]

        # Prefix ekle ve embed et
        prefixed_contents = [f"{prefix}{c}" for c in contents]
        embeddings = model.encode(prefixed_contents, normalize_embeddings=True, show_progress_bar=False)

        # Veritabanına yaz
        with conn.cursor() as cur:
            for doc_id, embedding in zip(ids, embeddings):
                cur.execute(
                    f"UPDATE {table_name} SET embedding = %s WHERE id = %s",
                    (embedding.tolist(), doc_id),
                )
        conn.commit()

        embedded_count += len(batch)
        elapsed = time.time() - start_time
        rate = embedded_count / elapsed if elapsed > 0 else 0
        eta = (total - embedded_count) / rate if rate > 0 else 0

        logger.info(
            "  📈 İlerleme: %d/%d (%.1f%%) | Hız: %.1f chunk/s | ETA: %.0fs",
            embedded_count, total,
            embedded_count / total * 100,
            rate, eta,
        )

        offset += batch_size

    total_time = time.time() - start_time
    logger.info(
        "✅ Re-embedding tamamlandı: %d chunk, %.1f saniye (%.1f chunk/s)",
        embedded_count, total_time, embedded_count / total_time if total_time > 0 else 0,
    )
    return embedded_count


def main():
    args = parse_args()
    settings = get_settings()
    table_name = settings.HAYSTACK_TABLE_NAME

    logger.info("=" * 60)
    logger.info("UniChat — Embedding Model Migrasyon Scripti")
    logger.info("=" * 60)
    logger.info("Model: %s", settings.EMBEDDING_MODEL)
    logger.info("Prefix: '%s'", settings.EMBEDDING_PASSAGE_PREFIX)
    logger.info("Dimension: %d", settings.EMBEDDING_DIMENSION)
    logger.info("Tablo: %s", table_name)
    logger.info("Batch boyutu: %d", args.batch_size)
    logger.info("Dry-run: %s", args.dry_run)
    logger.info("-" * 60)

    # Veritabanına bağlan
    conn = get_connection()
    try:
        # Mevcut durum raporu
        stats = get_embedding_stats(conn, table_name)
        logger.info("📊 Mevcut durum:")
        logger.info("  Toplam chunk: %d", stats["total"])
        logger.info("  Embedding olan: %d", stats["with_embedding"])
        logger.info("  Embedding olmayan: %d", stats["without_embedding"])

        if stats["total"] == 0:
            logger.warning("⚠️ Veritabanında hiç chunk yok. İşlem sonlandırılıyor.")
            return

        if args.dry_run:
            logger.info("\n🔍 DRY-RUN: %d chunk re-embed edilecek. Veritabanı DEĞİŞTİRİLMEDİ.", stats["total"])
            return

        # Kullanıcı onayı
        logger.info("\n⚠️ Bu işlem %d chunk'ın embedding'ini yeniden hesaplayacak.", stats["total"])
        confirm = input("Devam etmek istiyor musunuz? (evet/hayır): ").strip().lower()
        if confirm not in ("evet", "e", "yes", "y"):
            logger.info("İşlem iptal edildi.")
            return

        # 1. Modeli yükle
        logger.info("\n📥 Model yükleniyor: %s", settings.EMBEDDING_MODEL)
        model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("  ✅ Model yüklendi (boyut: %d)", model.get_sentence_embedding_dimension())

        # 2. HNSW indeksini drop et
        drop_hnsw_index(conn, table_name)

        # 3. Mevcut embedding'leri NULL yap
        nullify_embeddings(conn, table_name)

        # 4. Tüm chunk'ları yeniden embed et
        embedded = re_embed_all(
            conn, table_name, model,
            batch_size=args.batch_size,
            prefix=settings.EMBEDDING_PASSAGE_PREFIX,
        )

        # 5. HNSW indeksini yeniden oluştur
        rebuild_hnsw_index(conn, table_name, settings.EMBEDDING_DIMENSION)

        # 6. Son durum raporu
        final_stats = get_embedding_stats(conn, table_name)
        logger.info("\n" + "=" * 60)
        logger.info("📊 MİGRASYON TAMAMLANDI")
        logger.info("=" * 60)
        logger.info("  Model: %s", settings.EMBEDDING_MODEL)
        logger.info("  Toplam chunk: %d", final_stats["total"])
        logger.info("  Embedding olan: %d", final_stats["with_embedding"])
        logger.info("  Embedding olmayan: %d", final_stats["without_embedding"])
        logger.info("  Başarı oranı: %.1f%%",
                     final_stats["with_embedding"] / final_stats["total"] * 100
                     if final_stats["total"] > 0 else 0)

        if final_stats["without_embedding"] > 0:
            logger.warning("⚠️ %d chunk hala embedding'siz!", final_stats["without_embedding"])
        else:
            logger.info("✅ Tüm chunk'lar başarıyla re-embed edildi!")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
