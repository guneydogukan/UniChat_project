"""
GİBTÜ birim yönetim bilgileri için izole repository katmanı.

Bu repository scraper çalıştırmaz; yalnızca BirimYonetim.aspx kaynaklı
normalize yönetim kayıtlarını PostgreSQL'e yazar ve DB-first servis için okur.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings


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


class UnitManagementRepository:
    """Birim yönetim tablolarına erişen küçük ve izole repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def ensure_schema(self) -> None:
        """Kök init.sql içinden şemayı uygular."""
        schema_path = Path(__file__).resolve().parents[3] / "database" / "init.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def upsert_scrape_run(self, run: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO management_scrape_runs (
                        scrape_run_id, scraper_name, metadata_version,
                        started_at, finished_at, status, validation_status,
                        target_url_count, processed_url_count, group_count,
                        member_count, needs_review_count, config, summary
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id) DO UPDATE SET
                        finished_at = EXCLUDED.finished_at,
                        status = EXCLUDED.status,
                        validation_status = EXCLUDED.validation_status,
                        target_url_count = EXCLUDED.target_url_count,
                        processed_url_count = EXCLUDED.processed_url_count,
                        group_count = EXCLUDED.group_count,
                        member_count = EXCLUDED.member_count,
                        needs_review_count = EXCLUDED.needs_review_count,
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
                        run.get("target_url_count", 0),
                        run.get("processed_url_count", 0),
                        run.get("group_count", 0),
                        run.get("member_count", 0),
                        run.get("needs_review_count", 0),
                        Json(run.get("config") or {}, dumps=_json_dumps),
                        Json(run.get("summary") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_unit(self, unit: dict[str, Any]) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO organizational_units (
                        unit_name, unit_name_normalized, unit_type,
                        source_url, source_birim_id, aliases, is_active,
                        last_checked_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (source_url) DO UPDATE SET
                        unit_name = EXCLUDED.unit_name,
                        unit_name_normalized = EXCLUDED.unit_name_normalized,
                        unit_type = EXCLUDED.unit_type,
                        source_birim_id = COALESCE(EXCLUDED.source_birim_id, organizational_units.source_birim_id),
                        aliases = EXCLUDED.aliases,
                        is_active = EXCLUDED.is_active,
                        last_checked_at = COALESCE(EXCLUDED.last_checked_at, organizational_units.last_checked_at),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        unit["unit_name"],
                        unit["unit_name_normalized"],
                        unit["unit_type"],
                        unit["source_url"],
                        unit.get("source_birim_id"),
                        Json(unit.get("aliases") or [], dumps=_json_dumps),
                        unit.get("is_active", True),
                        unit.get("last_checked_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_snapshot(self, snapshot: dict[str, Any], unit_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO management_snapshots (
                        snapshot_id, scrape_run_id, unit_id, source_url,
                        http_status, content_hash, fetched_at, parse_status,
                        group_count, member_count, raw_text, raw_html,
                        validation_report
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb
                    )
                    ON CONFLICT (snapshot_id) DO UPDATE SET
                        scrape_run_id = EXCLUDED.scrape_run_id,
                        unit_id = EXCLUDED.unit_id,
                        source_url = EXCLUDED.source_url,
                        http_status = EXCLUDED.http_status,
                        content_hash = EXCLUDED.content_hash,
                        fetched_at = EXCLUDED.fetched_at,
                        parse_status = EXCLUDED.parse_status,
                        group_count = EXCLUDED.group_count,
                        member_count = EXCLUDED.member_count,
                        raw_text = EXCLUDED.raw_text,
                        raw_html = EXCLUDED.raw_html,
                        validation_report = EXCLUDED.validation_report,
                        updated_at = NOW()
                    """,
                    (
                        snapshot["snapshot_id"],
                        snapshot["scrape_run_id"],
                        unit_id,
                        snapshot["source_url"],
                        snapshot.get("http_status"),
                        snapshot["content_hash"],
                        snapshot.get("fetched_at"),
                        snapshot.get("parse_status", "unknown"),
                        snapshot.get("group_count", 0),
                        snapshot.get("member_count", 0),
                        snapshot.get("raw_text"),
                        snapshot.get("raw_html"),
                        Json(snapshot.get("validation_report") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_group(self, group: dict[str, Any], unit_id: str) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO unit_management_groups (
                        unit_id, snapshot_id, group_title, group_key,
                        group_order, source_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (unit_id, source_url, group_key, group_order) DO UPDATE SET
                        snapshot_id = EXCLUDED.snapshot_id,
                        group_title = EXCLUDED.group_title,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        unit_id,
                        group["snapshot_id"],
                        group["group_title"],
                        group["group_key"],
                        group["group_order"],
                        group["source_url"],
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_member(self, member: dict[str, Any], unit_id: str, group_id: str) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO unit_management_members (
                        unit_id, group_id, snapshot_id, stable_member_key,
                        full_name, full_name_normalized, academic_title,
                        role, phone_extension, email, profile_url, source_url,
                        member_order, page_order, raw_text, scrape_time,
                        content_hash, parse_status, validation_issues, is_active
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s::jsonb, TRUE
                    )
                    ON CONFLICT (unit_id, group_id, stable_member_key) DO UPDATE SET
                        snapshot_id = EXCLUDED.snapshot_id,
                        full_name = EXCLUDED.full_name,
                        full_name_normalized = EXCLUDED.full_name_normalized,
                        academic_title = EXCLUDED.academic_title,
                        role = EXCLUDED.role,
                        phone_extension = EXCLUDED.phone_extension,
                        email = EXCLUDED.email,
                        profile_url = EXCLUDED.profile_url,
                        source_url = EXCLUDED.source_url,
                        member_order = EXCLUDED.member_order,
                        page_order = EXCLUDED.page_order,
                        raw_text = EXCLUDED.raw_text,
                        scrape_time = EXCLUDED.scrape_time,
                        content_hash = EXCLUDED.content_hash,
                        parse_status = EXCLUDED.parse_status,
                        validation_issues = EXCLUDED.validation_issues,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        unit_id,
                        group_id,
                        member["snapshot_id"],
                        member["stable_member_key"],
                        member.get("full_name"),
                        member.get("full_name_normalized"),
                        member.get("academic_title"),
                        member.get("role"),
                        member.get("phone_extension"),
                        member.get("email"),
                        member.get("profile_url"),
                        member.get("source_url"),
                        member.get("member_order"),
                        member.get("page_order"),
                        member.get("raw_text"),
                        member.get("scrape_time"),
                        member.get("content_hash"),
                        member.get("parse_status", "unknown"),
                        Json(member.get("validation_issues") or [], dumps=_json_dumps),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def deactivate_members_not_seen(self, unit_id: str, source_url: str, seen_member_ids: list[str]) -> int:
        if not seen_member_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE unit_management_members
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE unit_id = %s
                      AND source_url = %s
                      AND is_active = TRUE
                      AND id <> ALL(%s::uuid[])
                    """,
                    (unit_id, source_url, seen_member_ids),
                )
                affected = int(cur.rowcount or 0)
            conn.commit()
        return affected

    def list_units(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id, unit_name, unit_name_normalized, unit_type,
                        source_url, source_birim_id, aliases, last_checked_at
                    FROM organizational_units
                    WHERE is_active = TRUE
                    ORDER BY unit_type, unit_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def get_management_members(
        self,
        unit_id: str,
        group_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [unit_id]
        group_filter = ""
        if group_keys:
            group_filter = "AND g.group_key = ANY(%s)"
            params.append(group_keys)

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        m.id AS member_id,
                        m.stable_member_key,
                        m.full_name,
                        m.full_name_normalized,
                        m.academic_title,
                        m.role,
                        m.phone_extension,
                        m.email,
                        m.profile_url,
                        m.source_url,
                        m.member_order,
                        m.page_order,
                        m.raw_text,
                        m.scrape_time,
                        m.content_hash,
                        m.parse_status,
                        m.validation_issues,
                        g.id AS group_id,
                        g.group_title,
                        g.group_key,
                        g.group_order,
                        u.id AS unit_id,
                        u.unit_name,
                        u.unit_name_normalized,
                        u.unit_type
                    FROM unit_management_members m
                    JOIN unit_management_groups g ON g.id = m.group_id
                    JOIN organizational_units u ON u.id = m.unit_id
                    WHERE m.unit_id = %s
                      AND m.is_active = TRUE
                      AND m.parse_status IN ('ok', 'partial')
                      {group_filter}
                    ORDER BY g.group_order ASC, m.page_order ASC, m.full_name ASC
                    """,
                    tuple(params),
                )
                rows = [dict(row) for row in cur.fetchall()]

        for row in rows:
            row["member_id"] = str(row["member_id"])
            row["group_id"] = str(row["group_id"])
            row["unit_id"] = str(row["unit_id"])
            row["validation_issues"] = _decode_json(row.get("validation_issues")) or []
        return rows


__all__ = ["UnitManagementRepository"]
