"""
UniChat Backend — Veritabanı Başlatma
Tablolar ve gerekli extension'lar oluşturulur.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

# .env dosyasını yükle (proje kök dizininden)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


def init_database():
    """Veritabanı tablolarını oluşturur."""
    sql_commands = """
    -- PgVector extension
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Chat logları tablosu
    CREATE TABLE IF NOT EXISTS chat_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(100),
        user_query TEXT,
        bot_response TEXT,
        source_documents JSONB,
        timestamp TIMESTAMP DEFAULT NOW()
    );

    -- Not: Belge yönetimi Haystack PgvectorDocumentStore üzerinden yapılır.
    -- Eski department_feeds tablosu kaldırılmıştır (Faz 0 kalıntısı).

    -- Chat logları için index
    CREATE INDEX IF NOT EXISTS idx_chat_logs_session
    ON chat_logs(session_id);

    CREATE INDEX IF NOT EXISTS idx_chat_logs_timestamp
    ON chat_logs(timestamp DESC);
    """

    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql_commands)
        cur.close()
        conn.close()
        print("✅ Tablolar başarıyla oluşturuldu!")
    except Exception as e:
        print(f"\033[91m❌ Hata oluştu: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    init_database()
