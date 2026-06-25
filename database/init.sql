-- UniChat — PostgreSQL Başlangıç
-- Docker container ilk oluşturulduğunda çalışır

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_food_menus_date
ON food_menus(date);

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

-- GİBTÜ akademik kadro/yönetim yapılandırılmış veri tabloları
CREATE TABLE IF NOT EXISTS academic_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    target_unit_count INTEGER NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    person_count INTEGER NOT NULL DEFAULT 0,
    affiliation_count INTEGER NOT NULL DEFAULT 0,
    management_role_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_universities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_url TEXT,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id UUID NOT NULL REFERENCES academic_universities(id) ON DELETE CASCADE,
    birim_id INTEGER,
    unit_name TEXT NOT NULL,
    unit_name_normalized TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    parent_unit_id UUID REFERENCES academic_units(id) ON DELETE SET NULL,
    slug TEXT,
    source_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (university_id, birim_id)
);

ALTER TABLE academic_units
DROP CONSTRAINT IF EXISTS academic_units_university_id_unit_name_normalized_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_units_root_name_unique
ON academic_units(university_id, unit_name_normalized)
WHERE parent_unit_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_units_child_parent_name_unique
ON academic_units(university_id, parent_unit_id, unit_name_normalized)
WHERE parent_unit_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS academic_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL UNIQUE REFERENCES academic_units(id) ON DELETE CASCADE,
    parent_unit_id UUID REFERENCES academic_units(id) ON DELETE SET NULL,
    program_code BIGINT,
    program_name TEXT NOT NULL,
    program_name_normalized TEXT NOT NULL,
    program_level TEXT,
    yok_atlas_url TEXT,
    source_url TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_programs_program_code
ON academic_programs(program_code)
WHERE program_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_academic_programs_parent
ON academic_programs(parent_unit_id);

CREATE TABLE IF NOT EXISTS academic_persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    title TEXT,
    email TEXT,
    pbs_profile_url TEXT,
    source_status TEXT NOT NULL DEFAULT 'official',
    needs_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_persons_pbs_url
ON academic_persons(pbs_profile_url)
WHERE pbs_profile_url IS NOT NULL AND pbs_profile_url <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_persons_email
ON academic_persons(email)
WHERE email IS NOT NULL AND email <> '';

CREATE INDEX IF NOT EXISTS idx_academic_persons_normalized_name
ON academic_persons(normalized_name);

CREATE TABLE IF NOT EXISTS academic_source_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT REFERENCES academic_scrape_runs(scrape_run_id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    unit_id UUID REFERENCES academic_units(id) ON DELETE SET NULL,
    person_id UUID REFERENCES academic_persons(id) ON DELETE SET NULL,
    content_hash TEXT,
    fetched_at TIMESTAMP,
    field_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_excerpt TEXT,
    is_accessible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_academic_source_evidence_url
ON academic_source_evidence(source_url);

CREATE TABLE IF NOT EXISTS academic_affiliations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES academic_persons(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES academic_units(id) ON DELETE CASCADE,
    affiliation_type TEXT NOT NULL,
    title TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_status TEXT NOT NULL DEFAULT 'official',
    confidence_status TEXT NOT NULL DEFAULT 'unknown',
    confidence_score NUMERIC,
    needs_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    source_url TEXT,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (person_id, unit_id, affiliation_type, source_url)
);

CREATE INDEX IF NOT EXISTS idx_academic_affiliations_unit
ON academic_affiliations(unit_id, affiliation_type, is_active);

CREATE TABLE IF NOT EXISTS academic_management_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES academic_persons(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES academic_units(id) ON DELETE CASCADE,
    role_name TEXT NOT NULL,
    role_key TEXT NOT NULL,
    source_priority INTEGER NOT NULL DEFAULT 100,
    source_status TEXT NOT NULL DEFAULT 'official',
    confidence_status TEXT NOT NULL DEFAULT 'unknown',
    confidence_score NUMERIC,
    needs_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    source_url TEXT,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (person_id, unit_id, role_key, source_url)
);

CREATE INDEX IF NOT EXISTS idx_academic_management_roles_unit
ON academic_management_roles(unit_id, role_key);

CREATE TABLE IF NOT EXISTS academic_external_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES academic_persons(id) ON DELETE CASCADE,
    profile_type TEXT NOT NULL,
    profile_url TEXT,
    external_id TEXT,
    match_status TEXT NOT NULL DEFAULT 'not_resolved',
    confidence_score NUMERIC,
    source_url TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (person_id, profile_type, profile_url)
);

CREATE INDEX IF NOT EXISTS idx_academic_external_profiles_person
ON academic_external_profiles(person_id, profile_type);

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_external_profiles_yok_url_unique
ON academic_external_profiles(profile_url)
WHERE profile_type = 'yok_akademik'
  AND profile_url IS NOT NULL
  AND profile_url <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_external_profiles_yok_external_id_unique
ON academic_external_profiles(external_id)
WHERE profile_type = 'yok_akademik'
  AND external_id IS NOT NULL
  AND external_id <> '';

CREATE TABLE IF NOT EXISTS academic_raw_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scrape_run_id TEXT NOT NULL REFERENCES academic_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    unit_id UUID REFERENCES academic_units(id) ON DELETE SET NULL,
    http_status INTEGER,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMP,
    response_text TEXT,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    extracted_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_unit_staff_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES academic_units(id) ON DELETE CASCADE,
    scrape_run_id TEXT NOT NULL REFERENCES academic_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    staff_count INTEGER NOT NULL DEFAULT 0,
    person_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at TIMESTAMP,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, scrape_run_id)
);

CREATE TABLE IF NOT EXISTS academic_unit_management_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES academic_units(id) ON DELETE CASCADE,
    scrape_run_id TEXT NOT NULL REFERENCES academic_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    role_count INTEGER NOT NULL DEFAULT 0,
    role_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at TIMESTAMP,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, scrape_run_id)
);

-- GİBTÜ BirimYonetim.aspx yapılandırılmış yönetim bilgileri
CREATE TABLE IF NOT EXISTS management_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    target_url_count INTEGER NOT NULL DEFAULT 0,
    processed_url_count INTEGER NOT NULL DEFAULT 0,
    group_count INTEGER NOT NULL DEFAULT 0,
    member_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organizational_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_name TEXT NOT NULL,
    unit_name_normalized TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    source_birim_id INTEGER,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizational_units_source_birim_id
ON organizational_units(source_birim_id)
WHERE source_birim_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_organizational_units_normalized
ON organizational_units(unit_name_normalized);

CREATE TABLE IF NOT EXISTS management_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scrape_run_id TEXT NOT NULL REFERENCES management_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    unit_id UUID REFERENCES organizational_units(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    http_status INTEGER,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    group_count INTEGER NOT NULL DEFAULT 0,
    member_count INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    raw_html TEXT,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_management_snapshots_run
ON management_snapshots(scrape_run_id);

CREATE TABLE IF NOT EXISTS unit_management_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES organizational_units(id) ON DELETE CASCADE,
    snapshot_id TEXT REFERENCES management_snapshots(snapshot_id) ON DELETE SET NULL,
    group_title TEXT NOT NULL,
    group_key TEXT NOT NULL,
    group_order INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, source_url, group_key, group_order)
);

CREATE INDEX IF NOT EXISTS idx_unit_management_groups_unit
ON unit_management_groups(unit_id, group_key);

CREATE TABLE IF NOT EXISTS unit_management_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id UUID NOT NULL REFERENCES organizational_units(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES unit_management_groups(id) ON DELETE CASCADE,
    snapshot_id TEXT REFERENCES management_snapshots(snapshot_id) ON DELETE SET NULL,
    stable_member_key TEXT NOT NULL,
    full_name TEXT,
    full_name_normalized TEXT NOT NULL DEFAULT '',
    academic_title TEXT,
    role TEXT,
    phone_extension TEXT,
    email TEXT,
    profile_url TEXT,
    source_url TEXT NOT NULL,
    member_order INTEGER NOT NULL DEFAULT 0,
    page_order INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    scrape_time TIMESTAMP,
    content_hash TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    validation_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_id, group_id, stable_member_key)
);

CREATE INDEX IF NOT EXISTS idx_unit_management_members_unit_active
ON unit_management_members(unit_id, is_active, parse_status);

CREATE INDEX IF NOT EXISTS idx_unit_management_members_group_order
ON unit_management_members(group_id, page_order);

-- GİBTÜ bölüm/program/alt birim yönetim bilgileri
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

-- GİBTÜ idari birim/personel yapılandırılmış veri hattı
CREATE TABLE IF NOT EXISTS administrative_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    target_url_count INTEGER NOT NULL DEFAULT 0,
    processed_url_count INTEGER NOT NULL DEFAULT 0,
    administrative_unit_count INTEGER NOT NULL DEFAULT 0,
    staff_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    critical_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    diff_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS administrative_source_pages (
    snapshot_id TEXT PRIMARY KEY,
    scrape_run_id TEXT NOT NULL REFERENCES administrative_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    parent_unit_name TEXT NOT NULL,
    parent_unit_type TEXT NOT NULL,
    website_unit_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    normalized_source_url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    http_status INTEGER,
    source_hash TEXT NOT NULL,
    fetched_at TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    administrative_unit_count INTEGER NOT NULL DEFAULT 0,
    staff_count INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    raw_html TEXT,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (scrape_run_id, normalized_source_url)
);

CREATE INDEX IF NOT EXISTS idx_administrative_source_pages_url
ON administrative_source_pages(normalized_source_url);

CREATE TABLE IF NOT EXISTS administrative_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_unit_name TEXT NOT NULL,
    parent_unit_type TEXT NOT NULL,
    website_unit_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    normalized_source_url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    administrative_unit_name TEXT NOT NULL,
    administrative_unit_key TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    normalized_text TEXT,
    search_text TEXT,
    source_hash TEXT NOT NULL,
    snapshot_id TEXT REFERENCES administrative_source_pages(snapshot_id) ON DELETE SET NULL,
    last_seen_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (website_unit_id, normalized_source_url, administrative_unit_key)
);

CREATE INDEX IF NOT EXISTS idx_administrative_units_parent_active
ON administrative_units(parent_unit_name, is_active);

CREATE INDEX IF NOT EXISTS idx_administrative_units_key
ON administrative_units(administrative_unit_key);

CREATE TABLE IF NOT EXISTS administrative_staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    administrative_unit_id UUID NOT NULL REFERENCES administrative_units(id) ON DELETE CASCADE,
    parent_unit_name TEXT NOT NULL,
    parent_unit_type TEXT NOT NULL,
    website_unit_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    normalized_source_url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    administrative_unit_name TEXT NOT NULL,
    stable_staff_key TEXT NOT NULL,
    person_name TEXT,
    person_name_normalized TEXT NOT NULL DEFAULT '',
    title_or_role TEXT,
    email TEXT,
    phone TEXT,
    internal_extension TEXT,
    office_location TEXT,
    description TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    normalized_text TEXT,
    search_text TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_hash TEXT NOT NULL,
    snapshot_id TEXT REFERENCES administrative_source_pages(snapshot_id) ON DELETE SET NULL,
    last_seen_at TIMESTAMP,
    parse_status TEXT NOT NULL DEFAULT 'unknown',
    validation_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (website_unit_id, administrative_unit_id, stable_staff_key)
);

CREATE INDEX IF NOT EXISTS idx_administrative_staff_unit_active
ON administrative_staff(administrative_unit_id, is_active, parse_status);

CREATE INDEX IF NOT EXISTS idx_administrative_staff_parent_active
ON administrative_staff(parent_unit_name, is_active);

CREATE INDEX IF NOT EXISTS idx_administrative_staff_search
ON administrative_staff(person_name_normalized, administrative_unit_name);

CREATE TABLE IF NOT EXISTS administrative_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias_text TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    canonical_type TEXT NOT NULL,
    website_unit_id INTEGER,
    source_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (alias_normalized, canonical_type, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_administrative_aliases_lookup
ON administrative_aliases(alias_normalized, is_active);

CREATE INDEX IF NOT EXISTS idx_yokatlas_program_years_program_code_year
ON yokatlas_program_years(program_code, data_year);

CREATE INDEX IF NOT EXISTS idx_yokatlas_programs_level
ON yokatlas_programs(program_level);

CREATE INDEX IF NOT EXISTS idx_yokatlas_validation_results_run
ON yokatlas_validation_results(scrape_run_id, severity);

-- GİBTÜ bölüm/program katalog bilgileri
-- Mevcut academic_units / academic_programs bilgi grafını değiştirmez.
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

-- MDBF öğrenci işleri workflow/form DB-first entegrasyonu
CREATE TABLE IF NOT EXISTS workflow_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL,
    metadata_version TEXT NOT NULL,
    unit_code TEXT NOT NULL,
    source_workflows_url TEXT NOT NULL,
    source_forms_url TEXT NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    workflow_count INTEGER NOT NULL DEFAULT 0,
    form_count INTEGER NOT NULL DEFAULT 0,
    mapping_count INTEGER NOT NULL DEFAULT 0,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unit_forms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_code TEXT NOT NULL,
    unit_name TEXT NOT NULL,
    unit_type TEXT NOT NULL DEFAULT 'fakülte',
    process_key TEXT,
    form_name TEXT NOT NULL,
    normalized_form_name TEXT NOT NULL,
    download_url TEXT NOT NULL,
    file_extension TEXT NOT NULL,
    http_status INTEGER,
    checksum TEXT,
    fetched_at TIMESTAMP,
    source_page_url TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_code, normalized_form_name)
);

CREATE INDEX IF NOT EXISTS idx_unit_forms_process
ON unit_forms(unit_code, process_key, is_active);

CREATE INDEX IF NOT EXISTS idx_unit_forms_download_url
ON unit_forms(download_url);

CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_code TEXT NOT NULL,
    unit_name TEXT NOT NULL,
    unit_type TEXT NOT NULL DEFAULT 'fakülte',
    process_key TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    source_page_url TEXT NOT NULL,
    pdf_url TEXT NOT NULL,
    pdf_checksum TEXT,
    pdf_size_bytes INTEGER,
    pdf_http_status INTEGER,
    workflow_summary TEXT,
    first_action_for_student TEXT,
    final_outcome TEXT,
    related_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence_score NUMERIC,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    extraction_method TEXT NOT NULL DEFAULT 'deterministic',
    raw_text TEXT,
    fetched_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (unit_code, process_key)
);

CREATE INDEX IF NOT EXISTS idx_workflows_process
ON workflows(unit_code, process_key, needs_review);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    actor TEXT,
    action_text TEXT NOT NULL,
    next_step_order INTEGER,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (workflow_id, step_order)
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow
ON workflow_steps(workflow_id, step_order);

CREATE TABLE IF NOT EXISTS workflow_forms_mapping (
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    form_id UUID NOT NULL REFERENCES unit_forms(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL DEFAULT 'rule',
    confidence_score NUMERIC,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workflow_id, form_id)
);
