-- UniChat — GİBTÜ bölüm/program katalog şeması
-- Mevcut academic_units / academic_programs bilgi grafını değiştirmez.

BEGIN;

CREATE TABLE IF NOT EXISTS program_catalog_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    processed_url_count INTEGER NOT NULL DEFAULT 0,
    skipped_url_count INTEGER NOT NULL DEFAULT 0,
    successful_url_count INTEGER NOT NULL DEFAULT 0,
    failed_url_count INTEGER NOT NULL DEFAULT 0,
    not_processed_due_to_limit_count INTEGER NOT NULL DEFAULT 0,
    unit_count INTEGER NOT NULL DEFAULT 0,
    department_count INTEGER NOT NULL DEFAULT 0,
    program_count INTEGER NOT NULL DEFAULT 0,
    alias_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    critical_error_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS program_catalog_raw_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scrape_run_id TEXT NOT NULL REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    http_status INTEGER,
    checksum TEXT NOT NULL,
    fetched_at TIMESTAMP,
    raw_content TEXT,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS program_catalog_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_unit_id UUID REFERENCES program_catalog_units(id) ON DELETE SET NULL,
    unit_name TEXT NOT NULL,
    normalized_unit_name TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    source_url TEXT,
    official_gibtu_url TEXT,
    existing_academic_unit_id UUID NULL,
    matched_academic_unit_key TEXT,
    source_priority INTEGER NOT NULL DEFAULT 100,
    match_status TEXT NOT NULL DEFAULT 'unknown',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    missing_in_current_run BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    snapshot_id TEXT REFERENCES program_catalog_raw_snapshots(snapshot_id) ON DELETE SET NULL,
    checksum TEXT,
    last_seen_run_id TEXT REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_program_catalog_units_root_name
ON program_catalog_units(normalized_unit_name)
WHERE parent_unit_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_program_catalog_units_child_name
ON program_catalog_units(parent_unit_id, normalized_unit_name)
WHERE parent_unit_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_program_catalog_units_type
ON program_catalog_units(unit_type, is_active, needs_review);

CREATE TABLE IF NOT EXISTS program_catalog_unit_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES program_catalog_units(id) ON DELETE CASCADE,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'manual',
    source_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (normalized_alias, unit_id)
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_unit_aliases_lookup
ON program_catalog_unit_aliases(normalized_alias, is_active);

CREATE TABLE IF NOT EXISTS program_catalog_departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES program_catalog_units(id) ON DELETE CASCADE,
    department_name TEXT NOT NULL,
    normalized_department_name TEXT NOT NULL,
    education_level TEXT NOT NULL DEFAULT 'undergraduate',
    source_url TEXT,
    official_gibtu_url TEXT,
    yokatlas_url TEXT,
    source_priority INTEGER NOT NULL DEFAULT 100,
    match_status TEXT NOT NULL DEFAULT 'unknown',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    missing_in_current_run BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    snapshot_id TEXT REFERENCES program_catalog_raw_snapshots(snapshot_id) ON DELETE SET NULL,
    checksum TEXT,
    last_seen_run_id TEXT REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, normalized_department_name)
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_departments_lookup
ON program_catalog_departments(normalized_department_name, is_active, needs_review);

CREATE TABLE IF NOT EXISTS program_catalog_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES program_catalog_units(id) ON DELETE CASCADE,
    department_id UUID REFERENCES program_catalog_departments(id) ON DELETE SET NULL,
    program_name TEXT NOT NULL,
    normalized_program_name TEXT NOT NULL,
    education_level TEXT NOT NULL DEFAULT 'unknown',
    program_kind TEXT NOT NULL DEFAULT 'program',
    source_url TEXT,
    official_gibtu_url TEXT,
    yokatlas_url TEXT,
    program_code TEXT,
    source_priority INTEGER NOT NULL DEFAULT 100,
    match_status TEXT NOT NULL DEFAULT 'unknown',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    missing_in_current_run BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    snapshot_id TEXT REFERENCES program_catalog_raw_snapshots(snapshot_id) ON DELETE SET NULL,
    checksum TEXT,
    last_seen_run_id TEXT REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, normalized_program_name, education_level)
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_programs_lookup
ON program_catalog_programs(normalized_program_name, education_level, is_active, needs_review);

CREATE INDEX IF NOT EXISTS idx_program_catalog_programs_status
ON program_catalog_programs(match_status, needs_review, is_active);

CREATE TABLE IF NOT EXISTS program_catalog_program_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID REFERENCES program_catalog_programs(id) ON DELETE CASCADE,
    department_id UUID REFERENCES program_catalog_departments(id) ON DELETE CASCADE,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'manual',
    source_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CHECK (program_id IS NOT NULL OR department_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_program_catalog_program_alias_unique
ON program_catalog_program_aliases(normalized_alias, COALESCE(program_id, department_id));

CREATE INDEX IF NOT EXISTS idx_program_catalog_program_aliases_lookup
ON program_catalog_program_aliases(normalized_alias, is_active);

CREATE TABLE IF NOT EXISTS program_catalog_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE SET NULL,
    unit_id UUID REFERENCES program_catalog_units(id) ON DELETE CASCADE,
    department_id UUID REFERENCES program_catalog_departments(id) ON DELETE CASCADE,
    program_id UUID REFERENCES program_catalog_programs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_priority INTEGER NOT NULL DEFAULT 100,
    match_status TEXT NOT NULL DEFAULT 'unknown',
    evidence_text TEXT,
    snapshot_id TEXT REFERENCES program_catalog_raw_snapshots(snapshot_id) ON DELETE SET NULL,
    checksum TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_sources_entity
ON program_catalog_sources(unit_id, department_id, program_id, source_type);

CREATE TABLE IF NOT EXISTS program_catalog_candidate_ogrenim_imports (
    import_run_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    report_checksum TEXT NOT NULL,
    raw_snapshot_checksum TEXT,
    section_snapshot_checksum TEXT,
    snapshot_id TEXT,
    raw_snapshot_path TEXT,
    section_snapshot_path TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    detail_link_record_count INTEGER NOT NULL DEFAULT 0,
    detail_unique_url_count INTEGER NOT NULL DEFAULT 0,
    detail_processed_record_count INTEGER NOT NULL DEFAULT 0,
    description_missing_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    parse_warning_count INTEGER NOT NULL DEFAULT 0,
    db_write_executed BOOLEAN NOT NULL DEFAULT FALSE,
    import_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS program_catalog_candidate_ogrenim_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id TEXT NOT NULL UNIQUE,
    raw_visible_name TEXT NOT NULL,
    program_name TEXT NOT NULL,
    normalized_program_name TEXT NOT NULL,
    parent_unit TEXT,
    normalized_parent_unit TEXT,
    unit_type TEXT NOT NULL DEFAULT 'candidate_group',
    education_level TEXT NOT NULL,
    education_label TEXT,
    education_language TEXT,
    duration TEXT,
    program_type TEXT NOT NULL,
    description TEXT,
    description_missing BOOLEAN NOT NULL DEFAULT TRUE,
    program_card_link TEXT,
    detail_url TEXT,
    detail_http_status INTEGER,
    detail_processed BOOLEAN NOT NULL DEFAULT FALSE,
    detail_snapshot_path TEXT,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'candidate_page_ogrenim',
    source_confidence TEXT NOT NULL DEFAULT 'candidate_support',
    answer_scope TEXT NOT NULL DEFAULT 'candidate_page_only',
    is_authoritative BOOLEAN NOT NULL DEFAULT FALSE,
    is_active_verified BOOLEAN NOT NULL DEFAULT FALSE,
    db_first_answerable BOOLEAN NOT NULL DEFAULT TRUE,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    parse_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot_id TEXT,
    checksum TEXT NOT NULL,
    report_checksum TEXT NOT NULL,
    import_run_id TEXT REFERENCES program_catalog_candidate_ogrenim_imports(import_run_id) ON DELETE SET NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_candidate_ogrenim_lookup
ON program_catalog_candidate_ogrenim_entries(normalized_program_name, education_level, db_first_answerable);

CREATE INDEX IF NOT EXISTS idx_program_catalog_candidate_ogrenim_source
ON program_catalog_candidate_ogrenim_entries(source_type, answer_scope, is_current);

CREATE INDEX IF NOT EXISTS idx_program_catalog_candidate_ogrenim_unit
ON program_catalog_candidate_ogrenim_entries(normalized_parent_unit, unit_type);

CREATE TABLE IF NOT EXISTS program_catalog_quality_issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL REFERENCES program_catalog_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_url TEXT,
    entity_type TEXT,
    entity_name TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_program_catalog_quality_issues_run
ON program_catalog_quality_issues(scrape_run_id, severity, issue_code);

COMMIT;
