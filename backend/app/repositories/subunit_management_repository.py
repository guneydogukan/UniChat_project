"""
GİBTÜ bölüm/program alt birim yönetim bilgileri için izole repository katmanı.

Bu repository scraper çalıştırmaz. Yalnızca subunit_management_* tablolarına
yazar ve DB-first chatbot servisi için okuma yapar.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings

REQUIRED_SUBUNIT_MANAGEMENT_TABLES: tuple[str, ...] = (
    "subunit_management_scrape_runs",
    "subunit_management_targets",
    "subunit_management_pages",
    "subunit_management_records",
    "subunit_management_aliases",
)


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


class SubunitManagementRepository:
    """Alt birim yönetim tablolarına erişen küçük ve izole repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def ensure_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[3] / "database" / "init.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def missing_required_tables(self) -> list[str]:
        """Yazım öncesi şema preflight kontrolü; tablo oluşturmaz."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    """,
                    (list(REQUIRED_SUBUNIT_MANAGEMENT_TABLES),),
                )
                existing = {row[0] for row in cur.fetchall()}
        return [table for table in REQUIRED_SUBUNIT_MANAGEMENT_TABLES if table not in existing]

    def upsert_scrape_run(self, run: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO subunit_management_scrape_runs (
                        scrape_run_id, scraper_name, metadata_version, scope_type,
                        started_at, finished_at, status, validation_status,
                        target_url_count, processed_url_count, record_count,
                        valid_count, partial_count, needs_review_count,
                        ignored_non_management_count, config, summary
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id) DO UPDATE SET
                        finished_at = EXCLUDED.finished_at,
                        status = EXCLUDED.status,
                        validation_status = EXCLUDED.validation_status,
                        target_url_count = EXCLUDED.target_url_count,
                        processed_url_count = EXCLUDED.processed_url_count,
                        record_count = EXCLUDED.record_count,
                        valid_count = EXCLUDED.valid_count,
                        partial_count = EXCLUDED.partial_count,
                        needs_review_count = EXCLUDED.needs_review_count,
                        ignored_non_management_count = EXCLUDED.ignored_non_management_count,
                        config = EXCLUDED.config,
                        summary = EXCLUDED.summary,
                        updated_at = NOW()
                    """,
                    (
                        run.get("scrape_run_id"),
                        run.get("scraper_name"),
                        run.get("metadata_version"),
                        run.get("scope_type"),
                        run.get("started_at"),
                        run.get("finished_at"),
                        run.get("status", "success"),
                        run.get("validation_status", "unknown"),
                        run.get("target_url_count", 0),
                        run.get("processed_url_count", 0),
                        run.get("record_count", 0),
                        run.get("valid_count", 0),
                        run.get("partial_count", 0),
                        run.get("needs_review_count", 0),
                        run.get("ignored_non_management_count", 0),
                        Json(run.get("config") or {}, dumps=_json_dumps),
                        Json(run.get("summary") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_target(self, target: dict[str, Any]) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO subunit_management_targets (
                        target_unit_name, target_unit_name_normalized,
                        parent_unit_name, department_or_program_name,
                        department_or_program_name_normalized, unit_type,
                        scope_type, source_url, source_page_type,
                        source_birim_id, aliases, is_active, last_checked_at
                    )
                    VALUES (
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb, TRUE, %s
                    )
                    ON CONFLICT (source_url) DO UPDATE SET
                        target_unit_name = EXCLUDED.target_unit_name,
                        target_unit_name_normalized = EXCLUDED.target_unit_name_normalized,
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        department_or_program_name = EXCLUDED.department_or_program_name,
                        department_or_program_name_normalized = EXCLUDED.department_or_program_name_normalized,
                        unit_type = EXCLUDED.unit_type,
                        scope_type = EXCLUDED.scope_type,
                        source_page_type = EXCLUDED.source_page_type,
                        source_birim_id = COALESCE(EXCLUDED.source_birim_id, subunit_management_targets.source_birim_id),
                        aliases = EXCLUDED.aliases,
                        is_active = TRUE,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, subunit_management_targets.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        target["target_unit_name"],
                        target["target_unit_name_normalized"],
                        target.get("parent_unit_name"),
                        target["department_or_program_name"],
                        target["department_or_program_name_normalized"],
                        target.get("unit_type", "department"),
                        target.get("scope_type"),
                        target["source_url"],
                        target["source_page_type"],
                        target.get("source_birim_id"),
                        Json(target.get("aliases") or [], dumps=_json_dumps),
                        target.get("last_checked_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_page(self, page: dict[str, Any], target_id: str | None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO subunit_management_pages (
                        snapshot_id, scrape_run_id, target_id, source_url,
                        source_page_type, target_unit_name, parent_unit_name,
                        department_or_program_name, scope_type, source_birim_id,
                        http_status, source_checksum, fetched_at, parse_status,
                        record_count, ignored_non_management_count, raw_text,
                        raw_html, validation_report
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb
                    )
                    ON CONFLICT (snapshot_id) DO UPDATE SET
                        scrape_run_id = EXCLUDED.scrape_run_id,
                        target_id = EXCLUDED.target_id,
                        source_url = EXCLUDED.source_url,
                        source_page_type = EXCLUDED.source_page_type,
                        target_unit_name = EXCLUDED.target_unit_name,
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        department_or_program_name = EXCLUDED.department_or_program_name,
                        scope_type = EXCLUDED.scope_type,
                        source_birim_id = EXCLUDED.source_birim_id,
                        http_status = EXCLUDED.http_status,
                        source_checksum = EXCLUDED.source_checksum,
                        fetched_at = EXCLUDED.fetched_at,
                        parse_status = EXCLUDED.parse_status,
                        record_count = EXCLUDED.record_count,
                        ignored_non_management_count = EXCLUDED.ignored_non_management_count,
                        raw_text = EXCLUDED.raw_text,
                        raw_html = EXCLUDED.raw_html,
                        validation_report = EXCLUDED.validation_report,
                        updated_at = NOW()
                    """,
                    (
                        page["snapshot_id"],
                        page["scrape_run_id"],
                        target_id,
                        page["source_url"],
                        page["source_page_type"],
                        page["target_unit_name"],
                        page.get("parent_unit_name"),
                        page["department_or_program_name"],
                        page["scope_type"],
                        page["source_birim_id"],
                        page.get("http_status"),
                        page["source_checksum"],
                        page.get("fetched_at"),
                        page.get("parse_status", "unknown"),
                        page.get("record_count", 0),
                        page.get("ignored_non_management_count", 0),
                        page.get("raw_text"),
                        page.get("raw_html"),
                        Json(page.get("validation_report") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_record(self, record: dict[str, Any], target_id: str) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO subunit_management_records (
                        target_id, snapshot_id, source_url, source_page_type,
                        target_unit_name, parent_unit_name,
                        department_or_program_name, scope_type,
                        management_role, management_role_key,
                        academic_title, person_name, person_name_normalized,
                        full_display_name, email, phone, office_location,
                        profile_url, image_url, raw_text,
                        evidence_html_selector, evidence_text, scraped_at,
                        source_checksum, parse_status, parse_confidence,
                        needs_review_reason, validation_issues,
                        stable_person_key, dedup_key, source_birim_id,
                        group_title, group_order, record_order, is_active
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb,
                        %s, %s, %s,
                        %s, %s, %s, TRUE
                    )
                    ON CONFLICT (dedup_key) DO UPDATE SET
                        target_id = EXCLUDED.target_id,
                        snapshot_id = EXCLUDED.snapshot_id,
                        source_page_type = EXCLUDED.source_page_type,
                        target_unit_name = EXCLUDED.target_unit_name,
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        department_or_program_name = EXCLUDED.department_or_program_name,
                        scope_type = EXCLUDED.scope_type,
                        management_role = EXCLUDED.management_role,
                        management_role_key = EXCLUDED.management_role_key,
                        academic_title = EXCLUDED.academic_title,
                        person_name = EXCLUDED.person_name,
                        person_name_normalized = EXCLUDED.person_name_normalized,
                        full_display_name = EXCLUDED.full_display_name,
                        email = EXCLUDED.email,
                        phone = EXCLUDED.phone,
                        office_location = EXCLUDED.office_location,
                        profile_url = EXCLUDED.profile_url,
                        image_url = EXCLUDED.image_url,
                        raw_text = EXCLUDED.raw_text,
                        evidence_html_selector = EXCLUDED.evidence_html_selector,
                        evidence_text = EXCLUDED.evidence_text,
                        scraped_at = EXCLUDED.scraped_at,
                        source_checksum = EXCLUDED.source_checksum,
                        parse_status = EXCLUDED.parse_status,
                        parse_confidence = EXCLUDED.parse_confidence,
                        needs_review_reason = EXCLUDED.needs_review_reason,
                        validation_issues = EXCLUDED.validation_issues,
                        stable_person_key = EXCLUDED.stable_person_key,
                        source_birim_id = EXCLUDED.source_birim_id,
                        group_title = EXCLUDED.group_title,
                        group_order = EXCLUDED.group_order,
                        record_order = EXCLUDED.record_order,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        target_id,
                        record["snapshot_id"],
                        record["source_url"],
                        record["source_page_type"],
                        record["target_unit_name"],
                        record.get("parent_unit_name"),
                        record["department_or_program_name"],
                        record["scope_type"],
                        record.get("management_role"),
                        record.get("management_role_key"),
                        record.get("academic_title"),
                        record.get("person_name"),
                        record.get("person_name_normalized"),
                        record.get("full_display_name"),
                        record.get("email"),
                        record.get("phone"),
                        record.get("office_location"),
                        record.get("profile_url"),
                        record.get("image_url"),
                        record.get("raw_text"),
                        record.get("evidence_html_selector"),
                        record.get("evidence_text"),
                        record.get("scraped_at"),
                        record.get("source_checksum"),
                        record.get("parse_status", "unknown"),
                        record.get("parse_confidence"),
                        record.get("needs_review_reason"),
                        Json(record.get("validation_issues") or [], dumps=_json_dumps),
                        record.get("stable_person_key"),
                        record.get("dedup_key"),
                        record.get("source_birim_id"),
                        record.get("group_title"),
                        record.get("group_order", 0),
                        record.get("record_order", 0),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_aliases(
        self,
        target_id: str,
        canonical_name: str,
        aliases: list[str],
        source_url: str,
    ) -> int:
        count = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for alias in aliases:
                    normalized_alias = self._normalize_alias(alias)
                    if not normalized_alias:
                        continue
                    cur.execute(
                        """
                        INSERT INTO subunit_management_aliases (
                            target_id, alias_text, alias_normalized,
                            canonical_name, source_url, is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT (alias_normalized, canonical_name) DO UPDATE SET
                            target_id = EXCLUDED.target_id,
                            alias_text = EXCLUDED.alias_text,
                            source_url = EXCLUDED.source_url,
                            is_active = TRUE,
                            updated_at = NOW()
                        """,
                        (target_id, alias, normalized_alias, canonical_name, source_url),
                    )
                    count += 1
            conn.commit()
        return count

    def deactivate_records_not_seen(self, source_url: str, seen_record_ids: list[str]) -> int:
        if not seen_record_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE subunit_management_records
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE source_url = %s
                      AND is_active = TRUE
                      AND id <> ALL(%s::uuid[])
                    """,
                    (source_url, seen_record_ids),
                )
                affected = int(cur.rowcount or 0)
            conn.commit()
        return affected

    def list_targets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id, target_unit_name, target_unit_name_normalized,
                        parent_unit_name, department_or_program_name,
                        department_or_program_name_normalized, unit_type,
                        scope_type, source_url, source_page_type,
                        source_birim_id, aliases, last_checked_at
                    FROM subunit_management_targets
                    WHERE is_active = TRUE
                    ORDER BY target_unit_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]

        for row in rows:
            row["id"] = str(row["id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def get_management_records(
        self,
        target_id: str,
        role_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [target_id]
        role_filter = ""
        if role_keys:
            role_filter = "AND r.management_role_key = ANY(%s)"
            params.append(role_keys)

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        r.id AS record_id,
                        r.target_id,
                        r.snapshot_id,
                        r.source_url,
                        r.source_page_type,
                        r.target_unit_name,
                        r.parent_unit_name,
                        r.department_or_program_name,
                        r.scope_type,
                        r.management_role,
                        r.management_role_key,
                        r.academic_title,
                        r.person_name,
                        r.person_name_normalized,
                        r.full_display_name,
                        r.email,
                        r.phone,
                        r.office_location,
                        r.profile_url,
                        r.image_url,
                        r.raw_text,
                        r.evidence_html_selector,
                        r.evidence_text,
                        r.scraped_at,
                        r.source_checksum,
                        r.parse_status,
                        r.parse_confidence,
                        r.validation_issues,
                        r.group_title,
                        r.group_order,
                        r.record_order,
                        t.last_checked_at
                    FROM subunit_management_records r
                    JOIN subunit_management_targets t ON t.id = r.target_id
                    WHERE r.target_id = %s
                      AND r.is_active = TRUE
                      AND r.parse_status IN ('valid', 'partial')
                      {role_filter}
                    ORDER BY r.group_order ASC, r.record_order ASC, r.person_name ASC
                    """,
                    tuple(params),
                )
                rows = [dict(row) for row in cur.fetchall()]

        for row in rows:
            row["record_id"] = str(row["record_id"])
            row["target_id"] = str(row["target_id"])
            row["validation_issues"] = _decode_json(row.get("validation_issues")) or []
        return rows

    @staticmethod
    def _normalize_alias(value: str | None) -> str:
        if not value:
            return ""
        text = unicodedata.normalize("NFKD", str(value).casefold())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        replacements = {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()


__all__ = ["SubunitManagementRepository"]
