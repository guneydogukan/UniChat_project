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
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS knowledge_base (
        id SERIAL PRIMARY KEY,
        content TEXT,
        source_url TEXT,
        category VARCHAR(50),
        meta_data JSONB,
        embedding VECTOR(768)
    );

    CREATE TABLE IF NOT EXISTS chat_logs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id VARCHAR(100),
        user_query TEXT,
        bot_response TEXT,
        timestamp TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS department_feeds (
        id SERIAL PRIMARY KEY,
        department_name VARCHAR(100),
        title TEXT,
        content TEXT,
        file_url TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        embedding VECTOR(768)
    );
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
