"""
GİBTÜ akademik yapılandırılmış veri repository katmanı.

Bu katman scraper çalıştırmaz; yalnızca akademik birim, kişi, affiliation,
yönetim rolü, dış profil ve kaynak kanıtı kayıtlarını PostgreSQL'e yazar/okur.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings


UNIVERSITY_CANONICAL_NAME = "gaziantep islam bilim ve teknoloji universitesi"
UNIVERSITY_DISPLAY_NAME = "Gaziantep İslam Bilim ve Teknoloji Üniversitesi"
UNIVERSITY_SOURCE_URL = "https://www.gibtu.edu.tr"


def _json_dumps(value: Any) -> str:
    """JSONB alanlarını Türkçe karakterleri koruyarak yazar."""
    return json.dumps(value, ensure_ascii=False)


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        key: _decode_json(str(value)) if key == "meta_json_string" else _decode_json(value)
        for key, value in dict(row).items()
    }


class AcademicRepository:
    """Akademik bilgi grafı tablolarına erişen repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def ensure_schema(self) -> None:
        """Kök init.sql içinden akademik tablo şemasını uygular."""
        schema_path = Path(__file__).resolve().parents[3] / "database" / "init.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def upsert_university(
        self,
        canonical_name: str = UNIVERSITY_CANONICAL_NAME,
        display_name: str = UNIVERSITY_DISPLAY_NAME,
        source_url: str = UNIVERSITY_SOURCE_URL,
        last_checked_at: str | None = None,
    ) -> str:
        """GİBTÜ university kaydını döndürür veya oluşturur."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO academic_universities (
                        canonical_name, display_name, source_url, last_checked_at
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (canonical_name) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        source_url = EXCLUDED.source_url,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_universities.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (canonical_name, display_name, source_url, last_checked_at),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_scrape_run(self, run: dict[str, Any]) -> None:
        """Scrape run özetini idempotent biçimde yazar."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO academic_scrape_runs (
                        scrape_run_id, scraper_name, metadata_version, started_at, finished_at,
                        status, validation_status, target_unit_count, source_count,
                        person_count, affiliation_count, management_role_count, candidate_count,
                        config, summary
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id) DO UPDATE SET
                        finished_at = EXCLUDED.finished_at,
                        status = EXCLUDED.status,
                        validation_status = EXCLUDED.validation_status,
                        target_unit_count = EXCLUDED.target_unit_count,
                        source_count = EXCLUDED.source_count,
                        person_count = EXCLUDED.person_count,
                        affiliation_count = EXCLUDED.affiliation_count,
                        management_role_count = EXCLUDED.management_role_count,
                        candidate_count = EXCLUDED.candidate_count,
                        config = EXCLUDED.config,
                        summary = EXCLUDED.summary,
                        updated_at = NOW()
                    """,
                    (
                        run.get("scrape_run_id"),
                        run.get("scraper_name"),
                        run.get("metadata_version"),
                        run.get("started_at"),
                        run.get("finished_at"),
                        run.get("status", "success"),
                        run.get("validation_status", "unknown"),
                        run.get("target_unit_count", 0),
                        run.get("source_count", 0),
                        run.get("person_count", 0),
                        run.get("affiliation_count", 0),
                        run.get("management_role_count", 0),
                        run.get("candidate_count", 0),
                        Json(run.get("config") or {}, dumps=_json_dumps),
                        Json(run.get("summary") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_unit(self, unit: dict[str, Any], university_id: str, parent_unit_id: str | None = None) -> str:
        """Birim kaydını birim_id veya üst birim + normalize ad ile upsert eder."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                birim_id = unit.get("birim_id")
                cur.execute(
                    """
                    SELECT id
                    FROM academic_units
                    WHERE university_id = %s
                      AND (
                          (%s IS NOT NULL AND birim_id = %s)
                          OR (
                              unit_name_normalized = %s
                              AND (
                                  (%s IS NULL AND parent_unit_id IS NULL)
                                  OR parent_unit_id = %s
                              )
                          )
                      )
                    ORDER BY CASE WHEN %s IS NOT NULL AND birim_id = %s THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (
                        university_id,
                        birim_id,
                        birim_id,
                        unit["unit_name_normalized"],
                        parent_unit_id,
                        parent_unit_id,
                        birim_id,
                        birim_id,
                    ),
                )
                existing = cur.fetchone()
                params = (
                    birim_id,
                    unit["unit_name"],
                    unit["unit_name_normalized"],
                    unit["unit_type"],
                    parent_unit_id,
                    unit.get("slug"),
                    unit.get("source_url"),
                    unit.get("is_active", True),
                    unit.get("last_checked_at"),
                )
                if existing:
                    cur.execute(
                        """
                        UPDATE academic_units
                        SET
                            birim_id = COALESCE(%s, birim_id),
                            unit_name = %s,
                            unit_name_normalized = %s,
                            unit_type = %s,
                            parent_unit_id = %s,
                            slug = COALESCE(%s, slug),
                            source_url = COALESCE(%s, source_url),
                            is_active = %s,
                            last_checked_at = COALESCE(%s, last_checked_at),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (*params, existing["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO academic_units (
                            university_id, birim_id, unit_name, unit_name_normalized,
                            unit_type, parent_unit_id, slug, source_url, is_active, last_checked_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (university_id, *params),
                    )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_program_metadata(
        self,
        program: dict[str, Any],
        unit_id: str,
        parent_unit_id: str | None = None,
    ) -> str:
        """YÖK Atlas program kodu/seviyesi/URL metadata'sını bölüm/program unit'ine bağlar."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                program_code = program.get("program_code")
                cur.execute(
                    """
                    SELECT id
                    FROM academic_programs
                    WHERE unit_id = %s
                       OR (%s IS NOT NULL AND program_code = %s)
                    ORDER BY CASE WHEN unit_id = %s THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (unit_id, program_code, program_code, unit_id),
                )
                existing = cur.fetchone()
                params = (
                    unit_id,
                    parent_unit_id,
                    program_code,
                    program["program_name"],
                    program["program_name_normalized"],
                    program.get("program_level"),
                    program.get("yok_atlas_url"),
                    program.get("source_url"),
                    Json(program.get("aliases") or [], dumps=_json_dumps),
                    program.get("is_active", True),
                    program.get("last_checked_at"),
                )
                if existing:
                    cur.execute(
                        """
                        UPDATE academic_programs
                        SET
                            unit_id = %s,
                            parent_unit_id = COALESCE(%s, parent_unit_id),
                            program_code = COALESCE(%s, program_code),
                            program_name = %s,
                            program_name_normalized = %s,
                            program_level = COALESCE(%s, program_level),
                            yok_atlas_url = COALESCE(%s, yok_atlas_url),
                            source_url = COALESCE(%s, source_url),
                            aliases = %s::jsonb,
                            is_active = %s,
                            last_checked_at = COALESCE(%s, last_checked_at),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (*params, existing["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO academic_programs (
                            unit_id, parent_unit_id, program_code, program_name,
                            program_name_normalized, program_level, yok_atlas_url,
                            source_url, aliases, is_active, last_checked_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        RETURNING id
                        """,
                        params,
                    )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_person(self, person: dict[str, Any]) -> str:
        """Kişiyi PBS URL/e-posta/normalize ad sinyallerine göre tekilleştirir."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM academic_persons
                    WHERE
                        (%s IS NOT NULL AND %s <> '' AND pbs_profile_url = %s)
                        OR (%s IS NOT NULL AND %s <> '' AND email = %s)
                        OR (normalized_name = %s AND COALESCE(email, '') = COALESCE(%s, ''))
                    ORDER BY
                        CASE WHEN pbs_profile_url = %s THEN 0 ELSE 1 END,
                        CASE WHEN email = %s THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (
                        person.get("pbs_profile_url"),
                        person.get("pbs_profile_url"),
                        person.get("pbs_profile_url"),
                        person.get("email"),
                        person.get("email"),
                        person.get("email"),
                        person["normalized_name"],
                        person.get("email"),
                        person.get("pbs_profile_url"),
                        person.get("email"),
                    ),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        UPDATE academic_persons
                        SET
                            full_name = %s,
                            title = COALESCE(%s, title),
                            email = COALESCE(%s, email),
                            pbs_profile_url = COALESCE(%s, pbs_profile_url),
                            source_status = %s,
                            needs_manual_review = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (
                            person["full_name"],
                            person.get("title"),
                            person.get("email"),
                            person.get("pbs_profile_url"),
                            person.get("source_status", "official"),
                            person.get("needs_manual_review", False),
                            existing["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO academic_persons (
                            full_name, normalized_name, title, email, pbs_profile_url,
                            source_status, needs_manual_review
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            person["full_name"],
                            person["normalized_name"],
                            person.get("title"),
                            person.get("email"),
                            person.get("pbs_profile_url"),
                            person.get("source_status", "official"),
                            person.get("needs_manual_review", False),
                        ),
                    )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_yok_person(self, person: dict[str, Any]) -> str:
        """Kişiyi YÖK Akademik profil URL/ID sinyallerine göre tekilleştirir."""
        yok_profile_url = person.get("yok_profile_url")
        yok_researcher_id = person.get("yok_researcher_id")

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                existing = None
                if yok_profile_url or yok_researcher_id:
                    cur.execute(
                        """
                        SELECT person_id AS id
                        FROM academic_external_profiles
                        WHERE profile_type = 'yok_akademik'
                          AND (
                              (%s IS NOT NULL AND profile_url = %s)
                              OR (%s IS NOT NULL AND external_id = %s)
                          )
                        ORDER BY
                            CASE WHEN profile_url = %s THEN 0 ELSE 1 END,
                            CASE WHEN external_id = %s THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (
                            yok_profile_url,
                            yok_profile_url,
                            yok_researcher_id,
                            yok_researcher_id,
                            yok_profile_url,
                            yok_researcher_id,
                        ),
                    )
                    existing = cur.fetchone()

                if existing is None and not yok_profile_url and not yok_researcher_id:
                    cur.execute(
                        """
                        SELECT id
                        FROM academic_persons
                        WHERE normalized_name = %s
                          AND source_status IN (
                              'not_resolved',
                              'ambiguous_department',
                              'ambiguous_department_or_program',
                              'conflict_department_or_program',
                              'unmatched_program',
                              'missing_kadro_veri',
                              'verified_from_yok',
                              'verified_from_yok_academic',
                              'verified_from_filtered_context',
                              'verified_from_kadro_veri'
                          )
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (person["normalized_name"],),
                    )
                    existing = cur.fetchone()

                if existing:
                    cur.execute(
                        """
                        UPDATE academic_persons
                        SET
                            full_name = %s,
                            title = COALESCE(%s, title),
                            source_status = %s,
                            needs_manual_review = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id
                        """,
                        (
                            person["full_name"],
                            person.get("title"),
                            person.get("source_status", "not_resolved"),
                            person.get("needs_manual_review", True),
                            existing["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO academic_persons (
                            full_name, normalized_name, title, source_status, needs_manual_review
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            person["full_name"],
                            person["normalized_name"],
                            person.get("title"),
                            person.get("source_status", "not_resolved"),
                            person.get("needs_manual_review", True),
                        ),
                    )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def insert_evidence(
        self,
        evidence: dict[str, Any],
        unit_id: str | None = None,
        person_id: str | None = None,
    ) -> str:
        """Alan bazlı kaynak kanıtı kaydı oluşturur."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO academic_source_evidence (
                        scrape_run_id, source_url, source_type, source_kind, unit_id,
                        person_id, content_hash, fetched_at, field_names,
                        raw_excerpt, is_accessible
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    RETURNING id
                    """,
                    (
                        evidence.get("scrape_run_id"),
                        evidence["source_url"],
                        evidence["source_type"],
                        evidence["source_kind"],
                        unit_id,
                        person_id,
                        evidence.get("content_hash"),
                        evidence.get("fetched_at"),
                        Json(evidence.get("field_names") or [], dumps=_json_dumps),
                        evidence.get("raw_excerpt"),
                        evidence.get("is_accessible", True),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_affiliation(self, affiliation: dict[str, Any]) -> str:
        """Kişi-birim ilişkisini idempotent biçimde yazar."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO academic_affiliations (
                        person_id, unit_id, affiliation_type, title, is_active,
                        source_status, confidence_status, confidence_score,
                        needs_manual_review, source_url, evidence_ids, last_checked_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (person_id, unit_id, affiliation_type, source_url) DO UPDATE SET
                        title = COALESCE(EXCLUDED.title, academic_affiliations.title),
                        is_active = EXCLUDED.is_active,
                        source_status = EXCLUDED.source_status,
                        confidence_status = EXCLUDED.confidence_status,
                        confidence_score = EXCLUDED.confidence_score,
                        needs_manual_review = EXCLUDED.needs_manual_review,
                        evidence_ids = EXCLUDED.evidence_ids,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_affiliations.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        affiliation["person_id"],
                        affiliation["unit_id"],
                        affiliation["affiliation_type"],
                        affiliation.get("title"),
                        affiliation.get("is_active", True),
                        affiliation.get("source_status", "official"),
                        affiliation.get("confidence_status", "unknown"),
                        affiliation.get("confidence_score"),
                        affiliation.get("needs_manual_review", False),
                        affiliation.get("source_url"),
                        Json(affiliation.get("evidence_ids") or [], dumps=_json_dumps),
                        affiliation.get("last_checked_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def deactivate_yok_staff_affiliations_for_units(
        self,
        unit_ids: list[str],
        last_checked_at: str | None = None,
    ) -> int:
        """Hedef birimlerde eski YÖK Akademik kadro ilişkilerini yeni snapshot öncesi pasifleştirir."""
        if not unit_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE academic_affiliations
                    SET
                        is_active = FALSE,
                        last_checked_at = COALESCE(%s, last_checked_at),
                        updated_at = NOW()
                    WHERE unit_id = ANY(%s::uuid[])
                      AND affiliation_type = 'academic_staff'
                      AND source_url LIKE 'https://akademik.yok.gov.tr/%%'
                    """,
                    (last_checked_at, unit_ids),
                )
                affected = int(cur.rowcount or 0)
            conn.commit()
        return affected

    def upsert_management_role(self, role: dict[str, Any]) -> str:
        """Birim + rol + kişi ilişkisini yazar."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO academic_management_roles (
                        person_id, unit_id, role_name, role_key, source_priority,
                        source_status, confidence_status, confidence_score,
                        needs_manual_review, source_url, evidence_ids, last_checked_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (person_id, unit_id, role_key, source_url) DO UPDATE SET
                        role_name = EXCLUDED.role_name,
                        source_priority = EXCLUDED.source_priority,
                        source_status = EXCLUDED.source_status,
                        confidence_status = EXCLUDED.confidence_status,
                        confidence_score = EXCLUDED.confidence_score,
                        needs_manual_review = EXCLUDED.needs_manual_review,
                        evidence_ids = EXCLUDED.evidence_ids,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_management_roles.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        role["person_id"],
                        role["unit_id"],
                        role["role_name"],
                        role["role_key"],
                        role.get("source_priority", 100),
                        role.get("source_status", "official"),
                        role.get("confidence_status", "unknown"),
                        role.get("confidence_score"),
                        role.get("needs_manual_review", False),
                        role.get("source_url"),
                        Json(role.get("evidence_ids") or [], dumps=_json_dumps),
                        role.get("last_checked_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_external_profile(self, profile: dict[str, Any]) -> str:
        """PBS/YÖK Akademik dış profil kaydını yazar."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if profile.get("profile_url") is None:
                    if profile.get("profile_type") == "yok_akademik" and profile.get("external_id"):
                        cur.execute(
                            """
                            SELECT id
                            FROM academic_external_profiles
                            WHERE profile_type = 'yok_akademik'
                              AND external_id = %s
                            LIMIT 1
                            """,
                            (profile.get("external_id"),),
                        )
                        existing_by_external_id = cur.fetchone()
                        if existing_by_external_id:
                            cur.execute(
                                """
                                UPDATE academic_external_profiles
                                SET
                                    person_id = %s,
                                    match_status = %s,
                                    confidence_score = %s,
                                    source_url = COALESCE(%s, source_url),
                                    raw_data = %s::jsonb,
                                    last_checked_at = COALESCE(%s, last_checked_at),
                                    updated_at = NOW()
                                WHERE id = %s
                                RETURNING id
                                """,
                                (
                                    profile["person_id"],
                                    profile.get("match_status", "not_resolved"),
                                    profile.get("confidence_score"),
                                    profile.get("source_url"),
                                    Json(profile.get("raw_data") or {}, dumps=_json_dumps),
                                    profile.get("last_checked_at"),
                                    existing_by_external_id["id"],
                                ),
                            )
                            row = cur.fetchone()
                            conn.commit()
                            return str(row["id"])

                    cur.execute(
                        """
                        SELECT id
                        FROM academic_external_profiles
                        WHERE person_id = %s
                          AND profile_type = %s
                          AND profile_url IS NULL
                          AND COALESCE(source_url, '') = COALESCE(%s, '')
                        LIMIT 1
                        """,
                        (
                            profile["person_id"],
                            profile["profile_type"],
                            profile.get("source_url"),
                        ),
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE academic_external_profiles
                            SET
                                external_id = COALESCE(%s, external_id),
                                match_status = %s,
                                confidence_score = %s,
                                raw_data = %s::jsonb,
                                last_checked_at = COALESCE(%s, last_checked_at),
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING id
                            """,
                            (
                                profile.get("external_id"),
                                profile.get("match_status", "not_resolved"),
                                profile.get("confidence_score"),
                                Json(profile.get("raw_data") or {}, dumps=_json_dumps),
                                profile.get("last_checked_at"),
                                existing["id"],
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO academic_external_profiles (
                                person_id, profile_type, profile_url, external_id, match_status,
                                confidence_score, source_url, raw_data, last_checked_at
                            )
                            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s::jsonb, %s)
                            RETURNING id
                            """,
                            (
                                profile["person_id"],
                                profile["profile_type"],
                                profile.get("external_id"),
                                profile.get("match_status", "not_resolved"),
                                profile.get("confidence_score"),
                                profile.get("source_url"),
                                Json(profile.get("raw_data") or {}, dumps=_json_dumps),
                                profile.get("last_checked_at"),
                            ),
                        )
                    row = cur.fetchone()
                    conn.commit()
                    return str(row["id"])

                if profile.get("profile_type") == "yok_akademik":
                    cur.execute(
                        """
                        SELECT id
                        FROM academic_external_profiles
                        WHERE profile_type = 'yok_akademik'
                          AND (
                              profile_url = %s
                              OR (%s IS NOT NULL AND external_id = %s)
                          )
                        ORDER BY CASE WHEN profile_url = %s THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (
                            profile.get("profile_url"),
                            profile.get("external_id"),
                            profile.get("external_id"),
                            profile.get("profile_url"),
                        ),
                    )
                    existing_yok_profile = cur.fetchone()
                    if existing_yok_profile:
                        cur.execute(
                            """
                            UPDATE academic_external_profiles
                            SET
                                person_id = %s,
                                profile_url = COALESCE(%s, profile_url),
                                external_id = COALESCE(%s, external_id),
                                match_status = %s,
                                confidence_score = %s,
                                source_url = COALESCE(%s, source_url),
                                raw_data = %s::jsonb,
                                last_checked_at = COALESCE(%s, last_checked_at),
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING id
                            """,
                            (
                                profile["person_id"],
                                profile.get("profile_url"),
                                profile.get("external_id"),
                                profile.get("match_status", "not_resolved"),
                                profile.get("confidence_score"),
                                profile.get("source_url"),
                                Json(profile.get("raw_data") or {}, dumps=_json_dumps),
                                profile.get("last_checked_at"),
                                existing_yok_profile["id"],
                            ),
                        )
                        row = cur.fetchone()
                        conn.commit()
                        return str(row["id"])

                cur.execute(
                    """
                    INSERT INTO academic_external_profiles (
                        person_id, profile_type, profile_url, external_id, match_status,
                        confidence_score, source_url, raw_data, last_checked_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (person_id, profile_type, profile_url) DO UPDATE SET
                        external_id = COALESCE(EXCLUDED.external_id, academic_external_profiles.external_id),
                        match_status = EXCLUDED.match_status,
                        confidence_score = EXCLUDED.confidence_score,
                        source_url = COALESCE(EXCLUDED.source_url, academic_external_profiles.source_url),
                        raw_data = EXCLUDED.raw_data,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_external_profiles.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        profile["person_id"],
                        profile["profile_type"],
                        profile.get("profile_url"),
                        profile.get("external_id"),
                        profile.get("match_status", "not_resolved"),
                        profile.get("confidence_score"),
                        profile.get("source_url"),
                        Json(profile.get("raw_data") or {}, dumps=_json_dumps),
                        profile.get("last_checked_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def insert_raw_snapshot(self, snapshot: dict[str, Any], unit_id: str | None = None) -> None:
        """Ham HTML/text snapshot kaydını saklar."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO academic_raw_snapshots (
                        snapshot_id, scrape_run_id, source_url, source_kind, unit_id,
                        http_status, content_hash, fetched_at, response_text,
                        parse_status, extracted_fields
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (snapshot_id) DO UPDATE SET
                        scrape_run_id = EXCLUDED.scrape_run_id,
                        source_url = EXCLUDED.source_url,
                        source_kind = EXCLUDED.source_kind,
                        unit_id = COALESCE(EXCLUDED.unit_id, academic_raw_snapshots.unit_id),
                        http_status = EXCLUDED.http_status,
                        content_hash = EXCLUDED.content_hash,
                        fetched_at = EXCLUDED.fetched_at,
                        response_text = EXCLUDED.response_text,
                        parse_status = EXCLUDED.parse_status,
                        extracted_fields = EXCLUDED.extracted_fields,
                        updated_at = NOW()
                    """,
                    (
                        snapshot["snapshot_id"],
                        snapshot["scrape_run_id"],
                        snapshot["source_url"],
                        snapshot["source_kind"],
                        unit_id,
                        snapshot.get("http_status"),
                        snapshot["content_hash"],
                        snapshot.get("fetched_at"),
                        snapshot.get("response_text"),
                        snapshot.get("parse_status", "unknown"),
                        Json(snapshot.get("extracted_fields") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_unit_staff_snapshot(self, snapshot: dict[str, Any], unit_id: str) -> None:
        """Birim bazlı akademik kadro snapshot kaydını yazar."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO academic_unit_staff_snapshots (
                        unit_id, scrape_run_id, source_urls, staff_count, person_ids,
                        missing_fields, validation_status, last_checked_at, raw_data
                    )
                    VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (unit_id, scrape_run_id) DO UPDATE SET
                        source_urls = EXCLUDED.source_urls,
                        staff_count = EXCLUDED.staff_count,
                        person_ids = EXCLUDED.person_ids,
                        missing_fields = EXCLUDED.missing_fields,
                        validation_status = EXCLUDED.validation_status,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_unit_staff_snapshots.last_checked_at),
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                    """,
                    (
                        unit_id,
                        snapshot["scrape_run_id"],
                        Json(snapshot.get("source_urls") or [], dumps=_json_dumps),
                        snapshot.get("staff_count", 0),
                        Json(snapshot.get("person_ids") or [], dumps=_json_dumps),
                        Json(snapshot.get("missing_fields") or [], dumps=_json_dumps),
                        snapshot.get("validation_status", "unknown"),
                        snapshot.get("last_checked_at"),
                        Json(snapshot.get("raw_data") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_unit_management_snapshot(self, snapshot: dict[str, Any], unit_id: str) -> None:
        """Birim bazlı yönetim rolü snapshot kaydını yazar."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO academic_unit_management_snapshots (
                        unit_id, scrape_run_id, source_urls, role_count, role_ids,
                        missing_fields, validation_status, last_checked_at, raw_data
                    )
                    VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (unit_id, scrape_run_id) DO UPDATE SET
                        source_urls = EXCLUDED.source_urls,
                        role_count = EXCLUDED.role_count,
                        role_ids = EXCLUDED.role_ids,
                        missing_fields = EXCLUDED.missing_fields,
                        validation_status = EXCLUDED.validation_status,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, academic_unit_management_snapshots.last_checked_at),
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                    """,
                    (
                        unit_id,
                        snapshot["scrape_run_id"],
                        Json(snapshot.get("source_urls") or [], dumps=_json_dumps),
                        snapshot.get("role_count", 0),
                        Json(snapshot.get("role_ids") or [], dumps=_json_dumps),
                        Json(snapshot.get("missing_fields") or [], dumps=_json_dumps),
                        snapshot.get("validation_status", "unknown"),
                        snapshot.get("last_checked_at"),
                        Json(snapshot.get("raw_data") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def list_units(self) -> list[dict[str, Any]]:
        """Cevap servisinin eşleştirme yapması için aktif birimleri döndürür."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        u.id, u.birim_id, u.unit_name, u.unit_name_normalized, u.unit_type,
                        u.parent_unit_id, parent.unit_name AS parent_unit_name,
                        u.slug, u.source_url, u.last_checked_at
                    FROM academic_units u
                    LEFT JOIN academic_units parent ON parent.id = u.parent_unit_id
                    WHERE u.is_active = TRUE
                    ORDER BY u.unit_type, u.unit_name
                    """
                )
                return [dict(row) for row in cur.fetchall()]

    def get_child_units(self, parent_unit_id: str) -> list[dict[str, Any]]:
        """Bir üst birime bağlı aktif alt birimleri döndürür."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, birim_id, unit_name, unit_name_normalized, unit_type,
                           parent_unit_id, slug, source_url, last_checked_at
                    FROM academic_units
                    WHERE parent_unit_id = %s AND is_active = TRUE
                    ORDER BY unit_name
                    """,
                    (parent_unit_id,),
                )
                return [dict(row) for row in cur.fetchall()]

    def get_staff_by_unit(self, unit_id: str) -> list[dict[str, Any]]:
        """Birim akademik kadrosunu kişi ve profil bilgileriyle döndürür."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        p.id AS person_id, p.full_name, p.normalized_name,
                        COALESCE(a.title, p.title) AS title,
                        p.email, p.pbs_profile_url, p.source_status AS person_source_status,
                        p.needs_manual_review AS person_needs_manual_review,
                        a.affiliation_type, a.source_status, a.confidence_status,
                        a.confidence_score, a.needs_manual_review,
                        a.source_url, a.last_checked_at,
                        u.id AS unit_id, u.unit_name, u.unit_type,
                        parent.unit_name AS parent_unit_name
                    FROM academic_affiliations a
                    JOIN academic_persons p ON p.id = a.person_id
                    JOIN academic_units u ON u.id = a.unit_id
                    LEFT JOIN academic_units parent ON parent.id = u.parent_unit_id
                    WHERE a.unit_id = %s
                      AND a.affiliation_type = 'academic_staff'
                      AND a.is_active = TRUE
                    ORDER BY p.full_name
                    """,
                    (unit_id,),
                )
                rows = [dict(row) for row in cur.fetchall()]
        return self._attach_profiles(rows)

    def get_management_roles(
        self,
        unit_id: str,
        role_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Birim yönetim rollerini döndürür."""
        params: list[Any] = [unit_id]
        role_filter = ""
        if role_keys:
            role_filter = "AND r.role_key = ANY(%s)"
            params.append(role_keys)

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        r.id AS role_id, r.role_name, r.role_key, r.source_priority,
                        r.source_status, r.confidence_status, r.confidence_score,
                        r.needs_manual_review, r.source_url, r.last_checked_at,
                        p.id AS person_id, p.full_name, p.normalized_name,
                        p.title, p.email, p.pbs_profile_url,
                        u.id AS unit_id, u.unit_name, u.unit_type,
                        parent.unit_name AS parent_unit_name
                    FROM academic_management_roles r
                    JOIN academic_persons p ON p.id = r.person_id
                    JOIN academic_units u ON u.id = r.unit_id
                    LEFT JOIN academic_units parent ON parent.id = u.parent_unit_id
                    WHERE r.unit_id = %s
                    {role_filter}
                    ORDER BY r.source_priority ASC, r.role_name, p.full_name
                    """,
                    tuple(params),
                )
                rows = [dict(row) for row in cur.fetchall()]
        return self._attach_profiles(rows)

    def search_persons(self, normalized_query: str) -> list[dict[str, Any]]:
        """Normalize kişi adı parçasıyla kişi arar."""
        needle = f"%{normalized_query}%"
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        p.id AS person_id, p.full_name, p.normalized_name,
                        p.title, p.email, p.pbs_profile_url, p.source_status,
                        p.needs_manual_review,
                        u.id AS unit_id, u.unit_name, u.unit_type,
                        parent.unit_name AS parent_unit_name,
                        a.confidence_status, a.confidence_score,
                        a.source_url, a.last_checked_at
                    FROM academic_persons p
                    LEFT JOIN academic_affiliations a
                        ON a.person_id = p.id AND a.is_active = TRUE
                    LEFT JOIN academic_units u ON u.id = a.unit_id
                    LEFT JOIN academic_units parent ON parent.id = u.parent_unit_id
                    WHERE p.normalized_name LIKE %s
                    ORDER BY p.full_name, u.unit_name
                    LIMIT 20
                    """,
                    (needle,),
                )
                rows = [dict(row) for row in cur.fetchall()]
        return self._attach_profiles(rows)

    def _attach_profiles(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        person_ids = sorted({str(row["person_id"]) for row in rows if row.get("person_id")})
        if not person_ids:
            return rows

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT person_id, profile_type, profile_url, external_id,
                           match_status, confidence_score, source_url, raw_data, last_checked_at
                    FROM academic_external_profiles
                    WHERE person_id = ANY(%s::uuid[])
                    """,
                    (person_ids,),
                )
                profiles = [dict(row) for row in cur.fetchall()]

        by_person: dict[str, list[dict[str, Any]]] = {}
        for profile in profiles:
            by_person.setdefault(str(profile["person_id"]), []).append(profile)

        for row in rows:
            row["external_profiles"] = by_person.get(str(row.get("person_id")), [])
        return rows

    def build_yok_staff_db_quality_report(
        self,
        scrape_run_id: str | None = None,
        expected_target_count: int | None = None,
    ) -> dict[str, Any]:
        """YÖK Akademik bölüm/program kadro aktarımı için DB kalite raporu üretir."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                run = self._resolve_academic_run(cur, scrape_run_id)
                if run is None:
                    return {
                        "success": False,
                        "scrape_run_id": scrape_run_id,
                        "errors": ["YÖK Akademik scrape run kaydı bulunamadı."],
                    }

                run_id = str(run["scrape_run_id"])
                target_count = int(expected_target_count or run.get("target_unit_count") or 0)
                snapshot_stats = self._fetch_one(cur, """
                    SELECT
                        COUNT(*) FILTER (WHERE u.unit_type IN ('department', 'program', 'bolum')) AS department_program_snapshot_count,
                        COUNT(*) FILTER (WHERE u.unit_type IN ('faculty', 'fakulte')) AS faculty_snapshot_count,
                        COUNT(*) FILTER (
                            WHERE s.last_checked_at IS NULL
                               OR s.source_urls = '[]'::jsonb
                               OR s.staff_count IS NULL
                        ) AS incomplete_snapshot_count
                    FROM academic_unit_staff_snapshots s
                    JOIN academic_units u ON u.id = s.unit_id
                    WHERE s.scrape_run_id = %s
                """, (run_id,))

                source_stats = self._fetch_one(cur, """
                    SELECT
                        COUNT(*) AS source_evidence_count,
                        COUNT(*) FILTER (
                            WHERE source_type <> 'yok_akademik'
                               OR source_url NOT LIKE 'https://akademik.yok.gov.tr/%%'
                               OR source_url ~* '(gibtu\\.edu\\.tr|pbs\\.gibtu|duyuru|haber|rapor|faaliyet|kalite|\\.pdf|BirimAkademikPersonel|BirimYonetim)'
                        ) AS non_yok_or_blocked_source_count
                    FROM academic_source_evidence
                    WHERE scrape_run_id = %s
                """, (run_id,))

                raw_stats = self._fetch_one(cur, """
                    SELECT
                        COUNT(*) AS raw_snapshot_count,
                        COUNT(*) FILTER (
                            WHERE fetched_at IS NULL
                               OR source_url NOT LIKE 'https://akademik.yok.gov.tr/%%'
                               OR source_url ~* '(gibtu\\.edu\\.tr|pbs\\.gibtu|duyuru|haber|rapor|faaliyet|kalite|\\.pdf|BirimAkademikPersonel|BirimYonetim)'
                        ) AS invalid_raw_snapshot_count
                    FROM academic_raw_snapshots
                    WHERE scrape_run_id = %s
                """, (run_id,))

                person_stats = self._fetch_one(cur, """
                    WITH run_sources AS (
                        SELECT source_url
                        FROM academic_source_evidence
                        WHERE scrape_run_id = %s
                    ),
                    run_profiles AS (
                        SELECT DISTINCT ep.person_id, ep.profile_url, ep.external_id, ep.source_url, ep.match_status
                        FROM academic_external_profiles ep
                        WHERE ep.profile_type = 'yok_akademik'
                          AND (
                              ep.source_url IN (SELECT source_url FROM run_sources)
                              OR ep.profile_url IN (SELECT source_url FROM run_sources)
                          )
                    ),
                    run_people AS (
                        SELECT DISTINCT p.*, rp.profile_url, rp.external_id, rp.match_status
                        FROM run_profiles rp
                        JOIN academic_persons p ON p.id = rp.person_id
                    )
                    SELECT
                        COUNT(DISTINCT id) AS total_person_count,
                        COUNT(DISTINCT id) FILTER (
                            WHERE source_status IN (
                                'verified_from_yok',
                                'verified_from_yok_academic',
                                'verified_from_filtered_context',
                                'verified_from_kadro_veri'
                            )
                        ) AS verified_yok_person_count,
                        COUNT(DISTINCT id) FILTER (WHERE source_status = 'not_resolved') AS not_resolved_person_count,
                        COUNT(DISTINCT id) FILTER (
                            WHERE source_status IN (
                                'ambiguous_department',
                                'ambiguous_department_or_program',
                                'conflict_department_or_program',
                                'unmatched_program',
                                'missing_kadro_veri'
                            )
                        ) AS ambiguous_department_count,
                        COUNT(DISTINCT id) FILTER (WHERE source_status = 'conflict_institution') AS conflict_institution_count,
                        COUNT(DISTINCT id) FILTER (
                            WHERE profile_url IS NULL
                              AND source_status <> 'not_resolved'
                              AND needs_manual_review IS FALSE
                        ) AS unresolved_profile_policy_violation_count
                    FROM run_people
                """, (run_id,))

                affiliation_stats = self._fetch_one(cur, """
                    WITH run_sources AS (
                        SELECT source_url
                        FROM academic_source_evidence
                        WHERE scrape_run_id = %s
                    ),
                    run_people AS (
                        SELECT DISTINCT ep.person_id
                        FROM academic_external_profiles ep
                        WHERE ep.profile_type = 'yok_akademik'
                          AND (
                              ep.source_url IN (SELECT source_url FROM run_sources)
                              OR ep.profile_url IN (SELECT source_url FROM run_sources)
                          )
                    )
                    SELECT
                        COUNT(*) AS affiliation_count,
                        COUNT(*) FILTER (WHERE u.unit_type NOT IN ('department', 'program', 'bolum')) AS non_department_program_affiliation_count,
                        COUNT(*) FILTER (
                            WHERE a.source_status IN ('ambiguous_department', 'ambiguous_department_or_program', 'conflict_department_or_program', 'unmatched_program', 'missing_kadro_veri', 'not_resolved', 'conflict_institution')
                               OR p.source_status IN ('ambiguous_department', 'ambiguous_department_or_program', 'conflict_department_or_program', 'unmatched_program', 'missing_kadro_veri', 'not_resolved', 'conflict_institution')
                               OR a.needs_manual_review IS TRUE
                        ) AS unsafe_affiliation_count
                    FROM academic_affiliations a
                    JOIN academic_units u ON u.id = a.unit_id
                    JOIN academic_persons p ON p.id = a.person_id
                    WHERE a.person_id IN (SELECT person_id FROM run_people)
                      AND a.is_active = TRUE
                """, (run_id,))

                duplicate_stats = self._fetch_one(cur, """
                    WITH run_sources AS (
                        SELECT source_url
                        FROM academic_source_evidence
                        WHERE scrape_run_id = %s
                    ),
                    run_people AS (
                        SELECT DISTINCT
                            p.id,
                            p.normalized_name,
                            ep.profile_url,
                            ep.external_id
                        FROM academic_external_profiles ep
                        JOIN academic_persons p ON p.id = ep.person_id
                        WHERE ep.profile_type = 'yok_akademik'
                          AND (
                              ep.source_url IN (SELECT source_url FROM run_sources)
                              OR ep.profile_url IN (SELECT source_url FROM run_sources)
                          )
                    )
                    SELECT COUNT(*) AS duplicate_suspicion_count
                    FROM (
                        SELECT COALESCE(profile_url, external_id, normalized_name) AS dedup_key
                        FROM run_people
                        GROUP BY COALESCE(profile_url, external_id, normalized_name)
                        HAVING COUNT(*) > 1
                    ) duplicate_keys
                """, (run_id,))

                management_stats = self._fetch_one(cur, """
                    SELECT
                        %s::integer AS run_management_role_count,
                        COUNT(*) FILTER (
                            WHERE source_url LIKE 'https://akademik.yok.gov.tr/%%'
                               OR source_status IN ('verified_from_yok', 'verified_from_yok_academic', 'verified_from_filtered_context', 'verified_from_kadro_veri')
                        ) AS yok_management_role_count
                    FROM academic_management_roles
                """, (int(run.get("management_role_count") or 0),))

        snapshot_count = int(snapshot_stats.get("department_program_snapshot_count") or 0)
        faculty_snapshot_count = int(snapshot_stats.get("faculty_snapshot_count") or 0)
        missing_snapshot_count = max(0, target_count - snapshot_count)
        source_problem_count = int(source_stats.get("non_yok_or_blocked_source_count") or 0)
        invalid_raw_snapshot_count = int(raw_stats.get("invalid_raw_snapshot_count") or 0)
        non_department_affiliation_count = int(affiliation_stats.get("non_department_program_affiliation_count") or 0)
        unsafe_affiliation_count = int(affiliation_stats.get("unsafe_affiliation_count") or 0)
        unresolved_policy_violation_count = int(person_stats.get("unresolved_profile_policy_violation_count") or 0)
        duplicate_suspicion_count = int(duplicate_stats.get("duplicate_suspicion_count") or 0)
        management_write_count = int(management_stats.get("run_management_role_count") or 0)
        yok_management_role_count = int(management_stats.get("yok_management_role_count") or 0)

        checks = {
            "department_program_snapshots_complete": missing_snapshot_count == 0,
            "no_faculty_staff_snapshot": faculty_snapshot_count == 0,
            "affiliations_only_department_program": non_department_affiliation_count == 0,
            "sources_only_yok_academic": source_problem_count == 0 and invalid_raw_snapshot_count == 0,
            "unresolved_profiles_marked_for_review": unresolved_policy_violation_count == 0,
            "ambiguous_or_conflict_not_in_affiliations": unsafe_affiliation_count == 0,
            "no_duplicate_suspicion": duplicate_suspicion_count == 0,
            "snapshots_have_required_fields": int(snapshot_stats.get("incomplete_snapshot_count") or 0) == 0,
            "no_management_write_for_run": management_write_count == 0 and yok_management_role_count == 0,
        }

        return {
            "success": all(checks.values()),
            "scrape_run_id": run_id,
            "toplam_hedef_bolum_program_sayisi": target_count,
            "snapshot_olusan_bolum_program_sayisi": snapshot_count,
            "eksik_snapshot_sayisi": missing_snapshot_count,
            "toplam_kisi_sayisi": int(person_stats.get("total_person_count") or 0),
            "verified_yok_kisi_sayisi": int(person_stats.get("verified_yok_person_count") or 0),
            "not_resolved_kisi_sayisi": int(person_stats.get("not_resolved_person_count") or 0),
            "ambiguous_department_sayisi": int(person_stats.get("ambiguous_department_count") or 0),
            "ambiguous_department_or_program_sayisi": int(person_stats.get("ambiguous_department_count") or 0),
            "conflict_institution_sayisi": int(person_stats.get("conflict_institution_count") or 0),
            "duplicate_suphesi": duplicate_suspicion_count,
            "fakulte_snapshot_var_mi": faculty_snapshot_count > 0,
            "yonetim_tablosuna_yazim_var_mi": management_write_count > 0 or yok_management_role_count > 0,
            "yokatlas_program_sayisi": 0,
            "yok_akademik_gibtu_profil_sayisi": (run.get("summary") or {}).get("yok_academic_profile_count"),
            "pagination_sayfa_sayisi": (run.get("summary") or {}).get("pagination_pages_visited"),
            "hedef_bazli_metrikler": (run.get("summary") or {}).get("target_metrics"),
            "source_evidence_sayisi": int(source_stats.get("source_evidence_count") or 0),
            "raw_snapshot_sayisi": int(raw_stats.get("raw_snapshot_count") or 0),
            "affiliation_sayisi": int(affiliation_stats.get("affiliation_count") or 0),
            "kontroller": checks,
            "errors": [] if all(checks.values()) else [
                key for key, passed in checks.items() if not passed
            ],
        }

    def build_academic_staff_cleanup_dry_run(self) -> dict[str, Any]:
        """Akademik kadro cevaplarını kirletebilecek eski RAG chunk'larını silmeden sayar."""
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                haystack_exists = self._fetch_one(cur, "SELECT to_regclass('haystack_docs') AS table_name", ())
                if not haystack_exists.get("table_name"):
                    return {
                        "success": True,
                        "haystack_docs_exists": False,
                        "would_delete": {},
                        "sample_sources": [],
                    }

                counts = self._fetch_one(cur, """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE meta->>'source_url' ILIKE '%%BirimAkademikPersonel%%'
                               OR meta->>'source_url' ILIKE '%%BirimYonetim%%'
                        ) AS official_site_personel_or_management_chunks,
                        COUNT(*) FILTER (
                            WHERE meta->>'source_url' ILIKE '%%akademik.yok.gov.tr%%'
                               AND meta->>'scraper_name' = 'yok_academic_staff_scraper'
                        ) AS old_yok_academic_answer_chunks,
                        COUNT(*) FILTER (
                            WHERE meta->>'category' = 'akademik_kadro'
                               OR meta->>'doc_kind' = 'personel'
                        ) AS academic_or_personel_chunks
                    FROM haystack_docs
                """, ())
                samples = self._fetch_all(cur, """
                    SELECT meta->>'source_url' AS source_url,
                           meta->>'title' AS title,
                           meta->>'category' AS category,
                           meta->>'doc_kind' AS doc_kind,
                           COUNT(*) AS chunk_count
                    FROM haystack_docs
                    WHERE meta->>'source_url' ILIKE '%%BirimAkademikPersonel%%'
                       OR meta->>'source_url' ILIKE '%%BirimYonetim%%'
                       OR (
                            meta->>'source_url' ILIKE '%%akademik.yok.gov.tr%%'
                            AND meta->>'scraper_name' = 'yok_academic_staff_scraper'
                       )
                    GROUP BY meta->>'source_url', meta->>'title', meta->>'category', meta->>'doc_kind'
                    ORDER BY chunk_count DESC, source_url
                    LIMIT 50
                """, ())

        return {
            "success": True,
            "haystack_docs_exists": True,
            "would_delete": counts,
            "sample_sources": samples,
            "note": "Dry-run raporudur; veri silmez.",
        }

    @staticmethod
    def _resolve_academic_run(cur: RealDictCursor, scrape_run_id: str | None) -> dict[str, Any] | None:
        if scrape_run_id:
            cur.execute(
                """
                SELECT *
                FROM academic_scrape_runs
                WHERE scrape_run_id = %s
                """,
                (scrape_run_id,),
            )
        else:
            cur.execute(
                """
                SELECT *
                FROM academic_scrape_runs
                WHERE scraper_name = 'yok_academic_staff_scraper'
                ORDER BY finished_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _fetch_one(cur: RealDictCursor, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else {}

    @staticmethod
    def _fetch_all(cur: RealDictCursor, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


__all__ = [
    "AcademicRepository",
    "UNIVERSITY_CANONICAL_NAME",
    "UNIVERSITY_DISPLAY_NAME",
    "UNIVERSITY_SOURCE_URL",
]
