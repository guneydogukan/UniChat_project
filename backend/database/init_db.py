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

    -- YÖK Atlas GİBTÜ yapılandırılmış veri tabloları
    CREATE TABLE IF NOT EXISTS yokatlas_scrape_runs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scrape_run_id TEXT NOT NULL UNIQUE,
        scraper_name TEXT NOT NULL,
        metadata_version TEXT NOT NULL,
        university_id INTEGER,
        university_name TEXT,
        data_year INTEGER,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        status TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        expected_program_count INTEGER NOT NULL DEFAULT 0,
        matched_program_count INTEGER NOT NULL DEFAULT 0,
        normalized_program_count INTEGER NOT NULL DEFAULT 0,
        snapshot_count INTEGER NOT NULL DEFAULT 0,
        critical_count INTEGER NOT NULL DEFAULT 0,
        warning_count INTEGER NOT NULL DEFAULT 0,
        rate_limit_seconds NUMERIC,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS yokatlas_raw_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        scrape_run_id TEXT NOT NULL REFERENCES yokatlas_scrape_runs(scrape_run_id) ON DELETE CASCADE,
        snapshot_type TEXT NOT NULL,
        source_url TEXT NOT NULL,
        method TEXT NOT NULL,
        request_body JSONB,
        response_payload JSONB,
        response_hash TEXT NOT NULL,
        fetched_at TIMESTAMP,
        file_path TEXT,
        data_year INTEGER,
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS yokatlas_programs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        program_code BIGINT NOT NULL UNIQUE,
        source_program_id BIGINT,
        university_id INTEGER NOT NULL,
        university_name TEXT NOT NULL,
        university_type TEXT,
        city TEXT,
        academic_unit_id BIGINT,
        academic_unit_name TEXT NOT NULL,
        program_name_raw TEXT NOT NULL,
        program_name_clean TEXT NOT NULL,
        program_language_from_name TEXT,
        program_variant TEXT,
        program_level TEXT NOT NULL,
        source_level_id INTEGER NOT NULL,
        source_level_name TEXT,
        duration_years INTEGER,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        old_program_code BIGINT,
        old_program_id BIGINT,
        source_url TEXT,
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        data_year INTEGER,
        scrape_run_id TEXT REFERENCES yokatlas_scrape_runs(scrape_run_id),
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS yokatlas_program_years (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        program_id UUID NOT NULL REFERENCES yokatlas_programs(id) ON DELETE CASCADE,
        program_code BIGINT NOT NULL,
        data_year INTEGER NOT NULL,
        exam TEXT,
        term TEXT,
        table_type TEXT,
        score_type TEXT,
        education_mode TEXT,
        education_mode_id INTEGER,
        language TEXT,
        language_id INTEGER,
        funding_type TEXT,
        funding_id INTEGER,
        tuition_fee NUMERIC,
        source_url TEXT NOT NULL,
        catalog_snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        detail_snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        scrape_run_id TEXT NOT NULL REFERENCES yokatlas_scrape_runs(scrape_run_id),
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (program_code, data_year)
    );

    CREATE TABLE IF NOT EXISTS yokatlas_quota_statistics (
        program_year_id UUID PRIMARY KEY REFERENCES yokatlas_program_years(id) ON DELETE CASCADE,
        general_quota INTEGER,
        general_placed INTEGER,
        school_first_quota INTEGER,
        school_first_placed INTEGER,
        earthquake_quota INTEGER,
        earthquake_placed INTEGER,
        women_34_plus_quota INTEGER,
        women_34_plus_placed INTEGER,
        martyr_veteran_quota INTEGER,
        martyr_veteran_placed INTEGER,
        total_quota_known INTEGER,
        total_placed_known INTEGER,
        source_url TEXT,
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        data_year INTEGER,
        scrape_run_id TEXT REFERENCES yokatlas_scrape_runs(scrape_run_id),
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS yokatlas_score_statistics (
        program_year_id UUID PRIMARY KEY REFERENCES yokatlas_program_years(id) ON DELETE CASCADE,
        base_score NUMERIC,
        base_rank INTEGER,
        last_admitted_score NUMERIC,
        last_admitted_rank INTEGER,
        min_rank_condition INTEGER,
        min_rank_condition_text TEXT,
        fill_status TEXT,
        historical JSONB NOT NULL DEFAULT '[]'::jsonb,
        last_admitted_nets_status TEXT,
        last_admitted_nets JSONB NOT NULL DEFAULT '{}'::jsonb,
        average_nets_status TEXT,
        average_nets JSONB NOT NULL DEFAULT '{}'::jsonb,
        null_reason TEXT,
        source_url TEXT,
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        data_year INTEGER,
        scrape_run_id TEXT REFERENCES yokatlas_scrape_runs(scrape_run_id),
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS yokatlas_program_conditions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        program_year_id UUID NOT NULL REFERENCES yokatlas_program_years(id) ON DELETE CASCADE,
        condition_code TEXT NOT NULL,
        condition_text TEXT NOT NULL,
        source_url TEXT,
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        data_year INTEGER,
        scrape_run_id TEXT REFERENCES yokatlas_scrape_runs(scrape_run_id),
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (program_year_id, condition_code)
    );

    CREATE TABLE IF NOT EXISTS yokatlas_validation_results (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scrape_run_id TEXT NOT NULL REFERENCES yokatlas_scrape_runs(scrape_run_id) ON DELETE CASCADE,
        program_year_id UUID REFERENCES yokatlas_program_years(id) ON DELETE SET NULL,
        severity TEXT NOT NULL,
        code TEXT NOT NULL,
        message TEXT NOT NULL,
        program_key TEXT,
        program_code BIGINT,
        source_url TEXT,
        snapshot_id TEXT REFERENCES yokatlas_raw_snapshots(snapshot_id),
        response_hash TEXT,
        fetched_at TIMESTAMP,
        data_year INTEGER,
        validation_status TEXT NOT NULL DEFAULT 'unknown',
        created_at TIMESTAMP DEFAULT NOW()
    );

    -- Chat logları için index
    CREATE INDEX IF NOT EXISTS idx_chat_logs_session
    ON chat_logs(session_id);

    CREATE INDEX IF NOT EXISTS idx_chat_logs_timestamp
    ON chat_logs(timestamp DESC);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_food_menus_date
    ON food_menus(date);

    CREATE INDEX IF NOT EXISTS idx_yokatlas_program_years_program_code_year
    ON yokatlas_program_years(program_code, data_year);

    CREATE INDEX IF NOT EXISTS idx_yokatlas_programs_level
    ON yokatlas_programs(program_level);

    CREATE INDEX IF NOT EXISTS idx_yokatlas_validation_results_run
    ON yokatlas_validation_results(scrape_run_id, severity);
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
