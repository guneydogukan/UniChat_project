-- UniChat — GİBTÜ bölüm/program alt birim yönetim şeması
-- Yalnız yeni subunit_management_* tablolarını oluşturur.
-- Production uygulaması öncesinde DB backup alınması zorunlu kabul edilmelidir.

BEGIN;

CREATE TABLE IF NOT EXISTS subunit_management_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'department_program_management',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    target_url_count INTEGER NOT NULL DEFAULT 0,
    processed_url_count INTEGER NOT NULL DEFAULT 0,
    record_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    partial_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    ignored_non_management_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subunit_management_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_unit_name TEXT NOT NULL,
    target_unit_name_normalized TEXT NOT NULL,
    parent_unit_name TEXT,
    department_or_program_name TEXT NOT NULL,
    department_or_program_name_normalized TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'department_program_management',
    source_url TEXT NOT NULL UNIQUE,
    source_page_type TEXT NOT NULL,
    source_birim_id INTEGER,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_subunit_management_targets_birim_page
ON subunit_management_targets(source_birim_id, source_page_type)
WHERE source_birim_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_subunit_management_targets_normalized
ON subunit_management_targets(target_unit_name_normalized, department_or_program_name_normalized);

CREATE TABLE IF NOT EXISTS subunit_management_pages (
    snapshot_id TEXT PRIMARY KEY,
    scrape_run_id TEXT NOT NULL REFERENCES subunit_management_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    target_id UUID REFERENCES subunit_management_targets(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    source_page_type TEXT NOT NULL,
    target_unit_name TEXT NOT NULL,
    parent_unit_name TEXT,
    department_or_program_name TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'department_program_management',
    source_birim_id INTEGER,
    http_status INTEGER,
    source_checksum TEXT NOT NULL,
    fetched_at TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    record_count INTEGER NOT NULL DEFAULT 0,
    ignored_non_management_count INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    raw_html TEXT,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subunit_management_pages_run
ON subunit_management_pages(scrape_run_id);

CREATE INDEX IF NOT EXISTS idx_subunit_management_pages_source
ON subunit_management_pages(source_url, parse_status);

CREATE TABLE IF NOT EXISTS subunit_management_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id UUID NOT NULL REFERENCES subunit_management_targets(id) ON DELETE CASCADE,
    snapshot_id TEXT REFERENCES subunit_management_pages(snapshot_id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    source_page_type TEXT NOT NULL,
    target_unit_name TEXT NOT NULL,
    parent_unit_name TEXT,
    department_or_program_name TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'department_program_management',
    management_role TEXT,
    management_role_key TEXT NOT NULL DEFAULT '',
    academic_title TEXT,
    person_name TEXT,
    person_name_normalized TEXT NOT NULL DEFAULT '',
    full_display_name TEXT,
    email TEXT,
    phone TEXT,
    office_location TEXT,
    profile_url TEXT,
    image_url TEXT,
    raw_text TEXT,
    evidence_html_selector TEXT,
    evidence_text TEXT,
    scraped_at TIMESTAMP,
    source_checksum TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    parse_confidence NUMERIC,
    needs_review_reason TEXT,
    validation_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    stable_person_key TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    source_birim_id INTEGER,
    group_title TEXT,
    group_order INTEGER NOT NULL DEFAULT 0,
    record_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subunit_management_records_target_active
ON subunit_management_records(target_id, is_active, parse_status);

CREATE INDEX IF NOT EXISTS idx_subunit_management_records_role
ON subunit_management_records(management_role_key, person_name_normalized);

CREATE TABLE IF NOT EXISTS subunit_management_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id UUID NOT NULL REFERENCES subunit_management_targets(id) ON DELETE CASCADE,
    alias_text TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    source_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (alias_normalized, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_subunit_management_aliases_lookup
ON subunit_management_aliases(alias_normalized, is_active);

COMMIT;
