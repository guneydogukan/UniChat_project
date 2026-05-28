"""
UniChat Backend — Veritabanı Başlatma
Tablolar ve gerekli extension'lar oluşturulur.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# .env dosyasını yükle (proje kök dizininden)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


def init_database():
    """Veritabanı tablolarını oluşturur."""
    sql_commands = """
    -- PgVector extension
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    -- Chat logları tablosu
    CREATE TABLE IF NOT EXISTS chat_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(100),
        user_query TEXT,
        bot_response TEXT,
        source_documents JSONB,
        timestamp TIMESTAMP DEFAULT NOW()
    );

    -- Yemekhane menüleri: tarih bazlı kalıcı ana veri kaynağı
    CREATE TABLE IF NOT EXISTS food_menus (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        date DATE NOT NULL UNIQUE,
        menu_items JSONB NOT NULL,
        source_url TEXT NOT NULL,
        raw_text TEXT,
        raw_data JSONB,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    -- Not: Belge yönetimi Haystack PgvectorDocumentStore üzerinden yapılır.
    -- Eski department_feeds tablosu kaldırılmıştır (Faz 0 kalıntısı).

    -- Chat logları için index
    CREATE INDEX IF NOT EXISTS idx_chat_logs_session
    ON chat_logs(session_id);

    CREATE INDEX IF NOT EXISTS idx_chat_logs_timestamp
    ON chat_logs(timestamp DESC);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_food_menus_date
    ON food_menus(date);
    """

    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql_commands)
        cur.close()
        conn.close()
        print("Tablolar başarıyla oluşturuldu!")
    except Exception as e:
        print(f"\033[91mHata oluştu: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    init_database()
