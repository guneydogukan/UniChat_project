"""
Mühendislik bölüm duyuruları için structured DB repository katmanı.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
from psycopg2 import OperationalError, errorcodes
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings

logger = logging.getLogger(__name__)


REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES: tuple[str, ...] = (
    "department_announcement_sources",
    "department_announcement_scrape_runs",
    "department_announcement_staging",
    "department_announcements",
)


DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS department_announcement_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id INTEGER NOT NULL UNIQUE,
    department_code TEXT NOT NULL UNIQUE,
    department_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS department_announcement_scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL UNIQUE,
    scraper_name TEXT NOT NULL DEFAULT 'department_announcement_scraper',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pending',
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    source_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    staged_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    invalid_count INTEGER NOT NULL DEFAULT 0,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS department_announcement_staging (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id TEXT NOT NULL REFERENCES department_announcement_scrape_runs(scrape_run_id) ON DELETE CASCADE,
    source_id UUID REFERENCES department_announcement_sources(id) ON DELETE SET NULL,
    unit_id INTEGER NOT NULL,
    department_code TEXT NOT NULL,
    department_name TEXT NOT NULL,
    title TEXT NOT NULL,
    announcement_date DATE,
    published_at TIMESTAMP,
    detail_url TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash TEXT NOT NULL,
    search_text TEXT,
    intent_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_status TEXT NOT NULL DEFAULT 'unknown',
    validation_issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP,
    reviewed_by TEXT,
    review_note TEXT,
    production_announcement_id UUID,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (scrape_run_id, detail_url)
);

CREATE TABLE IF NOT EXISTS department_announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    unit_id INTEGER NOT NULL,
    department_code TEXT NOT NULL,
    department_name TEXT NOT NULL,
    title TEXT NOT NULL,
    announcement_date DATE,
    published_at TIMESTAMP,
    detail_url TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash TEXT NOT NULL,
    search_text TEXT NOT NULL,
    intent_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_staging_id UUID REFERENCES department_announcement_staging(id) ON DELETE SET NULL,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    approved_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_department_announcement_sources_active
ON department_announcement_sources(is_active, unit_id);

CREATE INDEX IF NOT EXISTS idx_department_announcement_staging_run_status
ON department_announcement_staging(scrape_run_id, status, validation_status);

CREATE INDEX IF NOT EXISTS idx_department_announcement_staging_detail
ON department_announcement_staging(detail_url);

CREATE INDEX IF NOT EXISTS idx_department_announcements_department_date
ON department_announcements(department_code, announcement_date DESC);

CREATE INDEX IF NOT EXISTS idx_department_announcements_tags
ON department_announcements USING GIN(intent_tags);

CREATE INDEX IF NOT EXISTS idx_department_announcements_search
ON department_announcements USING GIN (to_tsvector('simple', search_text));

INSERT INTO department_announcement_sources (unit_id, department_code, department_name, source_url, is_active)
VALUES
    (18, 'bilgisayar_muhendisligi', 'Bilgisayar Mühendisliği', 'https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=18', TRUE),
    (16, 'elektrik_elektronik_muhendisligi', 'Elektrik-Elektronik Mühendisliği', 'https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=16', TRUE),
    (19, 'endustri_muhendisligi', 'Endüstri Mühendisliği', 'https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=19', TRUE)
ON CONFLICT (unit_id) DO UPDATE SET
    department_code = EXCLUDED.department_code,
    department_name = EXCLUDED.department_name,
    source_url = EXCLUDED.source_url,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();
"""


def _json_dumps(value: Any) -> str:
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
    result = dict(row)
    for key in ("attachments", "intent_tags", "validation_issues", "raw_data", "config", "summary"):
        if key in result:
            result[key] = _decode_json(result.get(key))
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif value is not None and key.endswith("_id"):
            result[key] = str(value)
    if result.get("id") is not None:
        result["id"] = str(result["id"])
    if result.get("source_id") is not None:
        result["source_id"] = str(result["source_id"])
    if result.get("production_announcement_id") is not None:
        result["production_announcement_id"] = str(result["production_announcement_id"])
    return result


def classify_department_announcement_db_error(exc: Exception) -> str:
    """Duyuru DB hatalarını kullanıcıya sızdırmadan operasyonel tipe ayırır."""
    if isinstance(exc, OperationalError):
        return "db_connection_error"
    if getattr(exc, "pgcode", None) == errorcodes.UNDEFINED_TABLE:
        return "schema_missing"
    return "query_failed"


def ensure_department_announcement_schema(
    database_url: str | None = None,
    *,
    connect_timeout: int = 3,
) -> dict[str, Any]:
    """Sadece mühendislik bölüm duyuru tablolarını idempotent şekilde doğrular/oluşturur."""
    dsn = database_url or get_settings().DATABASE_URL
    with psycopg2.connect(dsn, connect_timeout=connect_timeout) as conn:
        with conn.cursor() as cur:
            cur.execute("SET lock_timeout TO '2000ms'")
            cur.execute("SET statement_timeout TO '5000ms'")
            cur.execute(DEPARTMENT_ANNOUNCEMENT_SCHEMA_SQL)
        conn.commit()
    logger.info("Duyuru tabloları doğrulandı/oluşturuldu.")
    return {
        "schema_ready": True,
        "tables": list(REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES),
        "seeded_sources": 3,
    }


class DepartmentAnnouncementRepository:
    """Duyuru staging/production tablolarına erişen küçük repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def get_status(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                table_values = ", ".join(["(%s)"] * len(REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES))
                cur.execute(
                    f"""
                    SELECT table_name, to_regclass(table_name) IS NOT NULL AS exists
                    FROM (VALUES {table_values}) AS required(table_name)
                    """,
                    REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES,
                )
                table_rows = cur.fetchall()
                missing_tables = [row["table_name"] for row in table_rows if not row["exists"]]
                schema_ready = not missing_tables

                status: dict[str, Any] = {
                    "schema_ready": schema_ready,
                    "missing_tables": missing_tables,
                    "active_source_count": 0,
                    "production_count": 0,
                    "pending_staging_count": 0,
                    "last_scrape_run": None,
                }
                if not schema_ready:
                    return status

                cur.execute(
                    "SELECT COUNT(*) AS count FROM department_announcement_sources WHERE is_active = TRUE"
                )
                status["active_source_count"] = int(cur.fetchone()["count"])

                cur.execute(
                    "SELECT COUNT(*) AS count FROM department_announcements WHERE is_active = TRUE"
                )
                status["production_count"] = int(cur.fetchone()["count"])

                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM department_announcement_staging
                    WHERE status = 'pending'
                    """
                )
                status["pending_staging_count"] = int(cur.fetchone()["count"])

                cur.execute(
                    """
                    SELECT scrape_run_id, status, validation_status, fetched_count,
                           staged_count, duplicate_count, error_count, valid_count,
                           invalid_count, started_at, finished_at, created_at, summary
                    FROM department_announcement_scrape_runs
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                status["last_scrape_run"] = _row_to_dict(cur.fetchone())
                return status

    def get_active_sources(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, unit_id, department_code, department_name, source_url, is_active
                    FROM department_announcement_sources
                    WHERE is_active = TRUE
                    ORDER BY unit_id
                    """
                )
                return [_row_to_dict(row) for row in cur.fetchall()]

    def create_scrape_run(
        self,
        scrape_run_id: str,
        source_count: int,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO department_announcement_scrape_runs (
                        scrape_run_id, scraper_name, started_at, status,
                        validation_status, source_count, config
                    )
                    VALUES (
                        %s, 'department_announcement_scraper', NOW(), 'running',
                        'unknown', %s, %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id) DO UPDATE SET
                        started_at = EXCLUDED.started_at,
                        status = EXCLUDED.status,
                        validation_status = EXCLUDED.validation_status,
                        source_count = EXCLUDED.source_count,
                        config = EXCLUDED.config,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        scrape_run_id,
                        source_count,
                        Json(config or {}, dumps=_json_dumps),
                    ),
                )
                row = _row_to_dict(cur.fetchone())
                conn.commit()
                return row or {}

    def update_scrape_run(
        self,
        scrape_run_id: str,
        *,
        status: str,
        validation_status: str,
        fetched_count: int,
        staged_count: int,
        duplicate_count: int,
        error_count: int,
        valid_count: int,
        invalid_count: int,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE department_announcement_scrape_runs
                    SET finished_at = NOW(),
                        status = %s,
                        validation_status = %s,
                        fetched_count = %s,
                        staged_count = %s,
                        duplicate_count = %s,
                        error_count = %s,
                        valid_count = %s,
                        invalid_count = %s,
                        summary = %s::jsonb,
                        updated_at = NOW()
                    WHERE scrape_run_id = %s
                    RETURNING *
                    """,
                    (
                        status,
                        validation_status,
                        fetched_count,
                        staged_count,
                        duplicate_count,
                        error_count,
                        valid_count,
                        invalid_count,
                        Json(summary or {}, dumps=_json_dumps),
                        scrape_run_id,
                    ),
                )
                row = _row_to_dict(cur.fetchone())
                conn.commit()
                return row or {}

    def find_production_by_detail_url(self, detail_url: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM department_announcements
                    WHERE detail_url = %s
                    """,
                    (detail_url,),
                )
                return _row_to_dict(cur.fetchone())

    def stage_announcement(
        self,
        *,
        scrape_run_id: str,
        source_id: str | None,
        announcement: dict[str, Any],
        validation_status: str,
        validation_issues: list[str],
        search_text: str,
        intent_tags: list[str],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO department_announcement_staging (
                        scrape_run_id, source_id, unit_id, department_code, department_name,
                        title, announcement_date, published_at, detail_url, content,
                        attachments, content_hash, search_text, intent_tags,
                        validation_status, validation_issues, status, raw_data
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s::jsonb,
                        %s, %s::jsonb, 'pending', %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id, detail_url) DO UPDATE SET
                        title = EXCLUDED.title,
                        announcement_date = EXCLUDED.announcement_date,
                        published_at = EXCLUDED.published_at,
                        content = EXCLUDED.content,
                        attachments = EXCLUDED.attachments,
                        content_hash = EXCLUDED.content_hash,
                        search_text = EXCLUDED.search_text,
                        intent_tags = EXCLUDED.intent_tags,
                        validation_status = EXCLUDED.validation_status,
                        validation_issues = EXCLUDED.validation_issues,
                        raw_data = EXCLUDED.raw_data,
                        status = CASE
                            WHEN department_announcement_staging.status = 'approved'
                            THEN department_announcement_staging.status
                            ELSE 'pending'
                        END,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        scrape_run_id,
                        source_id,
                        announcement["unit_id"],
                        announcement["department_code"],
                        announcement["department_name"],
                        announcement["title"],
                        announcement.get("announcement_date"),
                        announcement.get("published_at"),
                        announcement["detail_url"],
                        announcement["content"],
                        Json(announcement.get("attachments") or [], dumps=_json_dumps),
                        announcement["content_hash"],
                        search_text,
                        Json(intent_tags, dumps=_json_dumps),
                        validation_status,
                        Json(validation_issues, dumps=_json_dumps),
                        Json(announcement.get("raw_data") or {}, dumps=_json_dumps),
                    ),
                )
                row = _row_to_dict(cur.fetchone())
                conn.commit()
                return row or {}

    def list_staging(
        self,
        *,
        status: str | None = None,
        scrape_run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if scrape_run_id:
            clauses.append("scrape_run_id = %s")
            params.append(scrape_run_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM department_announcement_staging
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [_row_to_dict(row) for row in cur.fetchall()]

    def approve_staging(
        self,
        staging_id: str,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM department_announcement_staging
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (staging_id,),
                )
                staging = cur.fetchone()
                if staging is None:
                    raise LookupError("Staging duyuru kaydı bulunamadı.")
                if staging["validation_status"] != "valid":
                    raise ValueError("Validation durumu valid olmayan kayıt onaylanamaz.")
                if staging["status"] == "rejected":
                    raise ValueError("Reddedilmiş kayıt doğrudan onaylanamaz.")

                cur.execute(
                    """
                    INSERT INTO department_announcements (
                        unit_id, department_code, department_name, title,
                        announcement_date, published_at, detail_url, content,
                        attachments, content_hash, search_text, intent_tags,
                        source_staging_id, first_seen_at, approved_at, last_seen_at, is_active
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s::jsonb,
                        %s, NOW(), NOW(), NOW(), TRUE
                    )
                    ON CONFLICT (detail_url) DO UPDATE SET
                        unit_id = EXCLUDED.unit_id,
                        department_code = EXCLUDED.department_code,
                        department_name = EXCLUDED.department_name,
                        title = EXCLUDED.title,
                        announcement_date = EXCLUDED.announcement_date,
                        published_at = EXCLUDED.published_at,
                        content = EXCLUDED.content,
                        attachments = EXCLUDED.attachments,
                        content_hash = EXCLUDED.content_hash,
                        search_text = EXCLUDED.search_text,
                        intent_tags = EXCLUDED.intent_tags,
                        source_staging_id = EXCLUDED.source_staging_id,
                        approved_at = NOW(),
                        last_seen_at = NOW(),
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        staging["unit_id"],
                        staging["department_code"],
                        staging["department_name"],
                        staging["title"],
                        staging["announcement_date"],
                        staging["published_at"],
                        staging["detail_url"],
                        staging["content"],
                        Json(_decode_json(staging["attachments"]) or [], dumps=_json_dumps),
                        staging["content_hash"],
                        staging["search_text"],
                        Json(_decode_json(staging["intent_tags"]) or [], dumps=_json_dumps),
                        staging["id"],
                    ),
                )
                production = cur.fetchone()

                cur.execute(
                    """
                    UPDATE department_announcement_staging
                    SET status = 'approved',
                        approved_at = NOW(),
                        reviewed_by = %s,
                        review_note = %s,
                        production_announcement_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (reviewed_by, review_note, production["id"], staging_id),
                )
                updated_staging = _row_to_dict(cur.fetchone())
                conn.commit()
                return {
                    "staging": updated_staging,
                    "production": _row_to_dict(production),
                }

    def reject_staging(
        self,
        staging_id: str,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE department_announcement_staging
                    SET status = 'rejected',
                        rejected_at = NOW(),
                        reviewed_by = %s,
                        review_note = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (reviewed_by, review_note, staging_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError("Staging duyuru kaydı bulunamadı.")
                conn.commit()
                return _row_to_dict(row) or {}

    def search_announcements(
        self,
        *,
        department_codes: list[str] | None = None,
        limit: int = 150,
    ) -> list[dict[str, Any]]:
        clauses = ["is_active = TRUE"]
        params: list[Any] = []
        if department_codes:
            clauses.append("department_code = ANY(%s)")
            params.append(department_codes)
        params.append(limit)

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM department_announcements
                    WHERE {' AND '.join(clauses)}
                    ORDER BY announcement_date DESC NULLS LAST, approved_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return [_row_to_dict(row) for row in cur.fetchall()]
