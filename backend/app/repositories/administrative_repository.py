"""
GİBTÜ idari birim/personel bilgileri için izole repository katmanı.

Bu repository scraper çalıştırmaz; yalnızca normalize idari kayıtları
PostgreSQL'e yazar ve DB-first servis için okur.
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


class AdministrativeRepository:
    """İdari birim/personel tablolarına erişen küçük repository."""

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
                    INSERT INTO administrative_scrape_runs (
                        scrape_run_id, scraper_name, metadata_version,
                        started_at, finished_at, status, validation_status,
                        target_url_count, processed_url_count,
                        administrative_unit_count, staff_count,
                        warning_count, critical_count, config, summary,
                        diff_summary
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s::jsonb, %s::jsonb,
                        %s::jsonb
                    )
                    ON CONFLICT (scrape_run_id) DO UPDATE SET
                        finished_at = EXCLUDED.finished_at,
                        status = EXCLUDED.status,
                        validation_status = EXCLUDED.validation_status,
                        target_url_count = EXCLUDED.target_url_count,
                        processed_url_count = EXCLUDED.processed_url_count,
                        administrative_unit_count = EXCLUDED.administrative_unit_count,
                        staff_count = EXCLUDED.staff_count,
                        warning_count = EXCLUDED.warning_count,
                        critical_count = EXCLUDED.critical_count,
                        config = EXCLUDED.config,
                        summary = EXCLUDED.summary,
                        diff_summary = EXCLUDED.diff_summary,
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
                        run.get("administrative_unit_count", 0),
                        run.get("staff_count", 0),
                        run.get("warning_count", 0),
                        run.get("critical_count", 0),
                        Json(run.get("config") or {}, dumps=_json_dumps),
                        Json(run.get("summary") or {}, dumps=_json_dumps),
                        Json(run.get("diff_summary") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def update_scrape_run_diff(self, scrape_run_id: str, diff_summary: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE administrative_scrape_runs
                    SET diff_summary = %s::jsonb, updated_at = NOW()
                    WHERE scrape_run_id = %s
                    """,
                    (Json(diff_summary or {}, dumps=_json_dumps), scrape_run_id),
                )
            conn.commit()

    def upsert_source_page(self, page: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO administrative_source_pages (
                        snapshot_id, scrape_run_id, parent_unit_name, parent_unit_type,
                        website_unit_id, source_url, normalized_source_url, page_type,
                        http_status, source_hash, fetched_at, parse_status,
                        administrative_unit_count, staff_count, raw_text, raw_html,
                        validation_report
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb
                    )
                    ON CONFLICT (snapshot_id) DO UPDATE SET
                        scrape_run_id = EXCLUDED.scrape_run_id,
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        parent_unit_type = EXCLUDED.parent_unit_type,
                        website_unit_id = EXCLUDED.website_unit_id,
                        source_url = EXCLUDED.source_url,
                        normalized_source_url = EXCLUDED.normalized_source_url,
                        page_type = EXCLUDED.page_type,
                        http_status = EXCLUDED.http_status,
                        source_hash = EXCLUDED.source_hash,
                        fetched_at = EXCLUDED.fetched_at,
                        parse_status = EXCLUDED.parse_status,
                        administrative_unit_count = EXCLUDED.administrative_unit_count,
                        staff_count = EXCLUDED.staff_count,
                        raw_text = EXCLUDED.raw_text,
                        raw_html = EXCLUDED.raw_html,
                        validation_report = EXCLUDED.validation_report,
                        updated_at = NOW()
                    """,
                    (
                        page["snapshot_id"],
                        page["scrape_run_id"],
                        page["parent_unit_name"],
                        page["parent_unit_type"],
                        page["website_unit_id"],
                        page["source_url"],
                        page["normalized_source_url"],
                        page["page_type"],
                        page.get("http_status"),
                        page["source_hash"],
                        page.get("fetched_at"),
                        page.get("parse_status", "unknown"),
                        page.get("administrative_unit_count", 0),
                        page.get("staff_count", 0),
                        page.get("raw_text"),
                        page.get("raw_html"),
                        Json(page.get("validation_report") or {}, dumps=_json_dumps),
                    ),
                )
            conn.commit()

    def upsert_administrative_unit(self, unit: dict[str, Any]) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO administrative_units (
                        parent_unit_name, parent_unit_type, website_unit_id,
                        source_url, normalized_source_url, page_type,
                        administrative_unit_name, administrative_unit_key,
                        aliases, description, order_index, raw_text,
                        normalized_text, search_text, source_hash,
                        snapshot_id, last_seen_at, is_active
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s::jsonb, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, TRUE
                    )
                    ON CONFLICT (website_unit_id, normalized_source_url, administrative_unit_key)
                    DO UPDATE SET
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        parent_unit_type = EXCLUDED.parent_unit_type,
                        source_url = EXCLUDED.source_url,
                        page_type = EXCLUDED.page_type,
                        administrative_unit_name = EXCLUDED.administrative_unit_name,
                        aliases = EXCLUDED.aliases,
                        description = EXCLUDED.description,
                        order_index = EXCLUDED.order_index,
                        raw_text = EXCLUDED.raw_text,
                        normalized_text = EXCLUDED.normalized_text,
                        search_text = EXCLUDED.search_text,
                        source_hash = EXCLUDED.source_hash,
                        snapshot_id = EXCLUDED.snapshot_id,
                        last_seen_at = EXCLUDED.last_seen_at,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        unit["parent_unit_name"],
                        unit["parent_unit_type"],
                        unit["website_unit_id"],
                        unit["source_url"],
                        unit["normalized_source_url"],
                        unit["page_type"],
                        unit["administrative_unit_name"],
                        unit["administrative_unit_key"],
                        Json(unit.get("aliases") or [], dumps=_json_dumps),
                        unit.get("description"),
                        unit.get("order_index", 0),
                        unit.get("raw_text"),
                        unit.get("normalized_text"),
                        unit.get("search_text"),
                        unit["source_hash"],
                        unit.get("snapshot_id"),
                        unit.get("last_seen_at"),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def upsert_administrative_staff(self, staff: dict[str, Any], administrative_unit_id: str) -> str:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO administrative_staff (
                        administrative_unit_id, parent_unit_name, parent_unit_type,
                        website_unit_id, source_url, normalized_source_url, page_type,
                        administrative_unit_name, stable_staff_key, person_name,
                        person_name_normalized, title_or_role, email, phone,
                        internal_extension, office_location, description, order_index,
                        raw_text, normalized_text, search_text, aliases, source_hash,
                        snapshot_id, last_seen_at, parse_status, validation_issues,
                        is_active
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb, %s,
                        %s, %s, %s, %s::jsonb,
                        TRUE
                    )
                    ON CONFLICT (website_unit_id, administrative_unit_id, stable_staff_key)
                    DO UPDATE SET
                        parent_unit_name = EXCLUDED.parent_unit_name,
                        parent_unit_type = EXCLUDED.parent_unit_type,
                        source_url = EXCLUDED.source_url,
                        normalized_source_url = EXCLUDED.normalized_source_url,
                        page_type = EXCLUDED.page_type,
                        administrative_unit_name = EXCLUDED.administrative_unit_name,
                        person_name = EXCLUDED.person_name,
                        person_name_normalized = EXCLUDED.person_name_normalized,
                        title_or_role = EXCLUDED.title_or_role,
                        email = EXCLUDED.email,
                        phone = EXCLUDED.phone,
                        internal_extension = EXCLUDED.internal_extension,
                        office_location = EXCLUDED.office_location,
                        description = EXCLUDED.description,
                        order_index = EXCLUDED.order_index,
                        raw_text = EXCLUDED.raw_text,
                        normalized_text = EXCLUDED.normalized_text,
                        search_text = EXCLUDED.search_text,
                        aliases = EXCLUDED.aliases,
                        source_hash = EXCLUDED.source_hash,
                        snapshot_id = EXCLUDED.snapshot_id,
                        last_seen_at = EXCLUDED.last_seen_at,
                        parse_status = EXCLUDED.parse_status,
                        validation_issues = EXCLUDED.validation_issues,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        administrative_unit_id,
                        staff["parent_unit_name"],
                        staff["parent_unit_type"],
                        staff["website_unit_id"],
                        staff["source_url"],
                        staff["normalized_source_url"],
                        staff["page_type"],
                        staff["administrative_unit_name"],
                        staff["stable_staff_key"],
                        staff.get("person_name"),
                        staff.get("person_name_normalized"),
                        staff.get("title_or_role"),
                        staff.get("email"),
                        staff.get("phone"),
                        staff.get("internal_extension"),
                        staff.get("office_location"),
                        staff.get("description"),
                        staff.get("order_index", 0),
                        staff.get("raw_text"),
                        staff.get("normalized_text"),
                        staff.get("search_text"),
                        Json(staff.get("aliases") or [], dumps=_json_dumps),
                        staff["source_hash"],
                        staff.get("snapshot_id"),
                        staff.get("last_seen_at"),
                        staff.get("parse_status", "unknown"),
                        Json(staff.get("validation_issues") or [], dumps=_json_dumps),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row["id"])

    def deactivate_staff_not_seen(
        self,
        website_unit_id: int,
        normalized_source_url: str,
        seen_staff_ids: list[str],
    ) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if seen_staff_ids:
                    cur.execute(
                        """
                        UPDATE administrative_staff
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE website_unit_id = %s
                          AND normalized_source_url = %s
                          AND is_active = TRUE
                          AND id <> ALL(%s::uuid[])
                        """,
                        (website_unit_id, normalized_source_url, seen_staff_ids),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE administrative_staff
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE website_unit_id = %s
                          AND normalized_source_url = %s
                          AND is_active = TRUE
                        """,
                        (website_unit_id, normalized_source_url),
                    )
                affected = int(cur.rowcount or 0)
            conn.commit()
        return affected

    def upsert_aliases(
        self,
        canonical_name: str,
        canonical_type: str,
        aliases: list[str],
        website_unit_id: int | None = None,
        source_url: str | None = None,
    ) -> int:
        from scrapers.administrative_staff_scraper import normalize_for_match

        rows = []
        seen: set[str] = set()
        for alias in aliases:
            normalized = normalize_for_match(alias)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append((alias, normalized))

        if not rows:
            return 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                for alias_text, alias_normalized in rows:
                    cur.execute(
                        """
                        INSERT INTO administrative_aliases (
                            alias_text, alias_normalized, canonical_name,
                            canonical_type, website_unit_id, source_url,
                            is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT (alias_normalized, canonical_type, canonical_name)
                        DO UPDATE SET
                            alias_text = EXCLUDED.alias_text,
                            website_unit_id = COALESCE(EXCLUDED.website_unit_id, administrative_aliases.website_unit_id),
                            source_url = COALESCE(EXCLUDED.source_url, administrative_aliases.source_url),
                            is_active = TRUE,
                            updated_at = NOW()
                        """,
                        (
                            alias_text,
                            alias_normalized,
                            canonical_name,
                            canonical_type,
                            website_unit_id,
                            source_url,
                        ),
                    )
            conn.commit()
        return len(rows)

    def get_active_staff_keys(self) -> dict[tuple[int, str], set[str]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        s.website_unit_id,
                        s.normalized_source_url,
                        u.administrative_unit_key,
                        s.stable_staff_key
                    FROM administrative_staff s
                    JOIN administrative_units u ON u.id = s.administrative_unit_id
                    WHERE s.is_active = TRUE
                      AND u.is_active = TRUE
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]

        result: dict[tuple[int, str], set[str]] = {}
        for row in rows:
            key = (int(row["website_unit_id"]), str(row["normalized_source_url"]))
            staff_key = f"{row['administrative_unit_key']}|{row['stable_staff_key']}"
            result.setdefault(key, set()).add(staff_key)
        return result

    def list_parent_units(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        website_unit_id,
                        parent_unit_name,
                        parent_unit_type,
                        MIN(source_url) AS source_url,
                        MIN(normalized_source_url) AS normalized_source_url,
                        MAX(last_seen_at) AS last_seen_at,
                        COUNT(*) FILTER (WHERE is_active = TRUE) AS administrative_unit_count
                    FROM administrative_units
                    GROUP BY website_unit_id, parent_unit_name, parent_unit_type
                    ORDER BY parent_unit_type, parent_unit_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]

                cur.execute(
                    """
                    SELECT canonical_name, alias_text
                    FROM administrative_aliases
                    WHERE canonical_type = 'parent_unit'
                      AND is_active = TRUE
                    ORDER BY alias_text
                    """
                )
                alias_rows = [dict(row) for row in cur.fetchall()]

        aliases_by_name: dict[str, list[str]] = {}
        for row in alias_rows:
            aliases_by_name.setdefault(str(row["canonical_name"]), []).append(str(row["alias_text"]))

        for row in rows:
            row["aliases"] = aliases_by_name.get(str(row.get("parent_unit_name")), [])
        return rows

    def get_administrative_units(self, website_unit_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id, parent_unit_name, parent_unit_type, website_unit_id,
                        source_url, normalized_source_url, page_type,
                        administrative_unit_name, administrative_unit_key,
                        aliases, description, order_index, raw_text,
                        normalized_text, search_text, source_hash,
                        snapshot_id, last_seen_at, is_active
                    FROM administrative_units
                    WHERE website_unit_id = %s
                      AND is_active = TRUE
                    ORDER BY order_index ASC, administrative_unit_name ASC
                    """,
                    (website_unit_id,),
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def get_administrative_staff(
        self,
        website_unit_id: int,
        administrative_unit_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [website_unit_id]
        unit_filter = ""
        if administrative_unit_keys:
            unit_filter = "AND u.administrative_unit_key = ANY(%s)"
            params.append(administrative_unit_keys)

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        s.id AS staff_id,
                        s.administrative_unit_id,
                        s.parent_unit_name,
                        s.parent_unit_type,
                        s.website_unit_id,
                        s.source_url,
                        s.normalized_source_url,
                        s.page_type,
                        s.administrative_unit_name,
                        s.stable_staff_key,
                        s.person_name,
                        s.person_name_normalized,
                        s.title_or_role,
                        s.email,
                        s.phone,
                        s.internal_extension,
                        s.office_location,
                        s.description,
                        s.order_index,
                        s.raw_text,
                        s.normalized_text,
                        s.search_text,
                        s.aliases,
                        s.source_hash,
                        s.snapshot_id,
                        s.last_seen_at,
                        s.parse_status,
                        s.validation_issues,
                        u.administrative_unit_key,
                        u.order_index AS administrative_unit_order
                    FROM administrative_staff s
                    JOIN administrative_units u ON u.id = s.administrative_unit_id
                    WHERE s.website_unit_id = %s
                      AND s.is_active = TRUE
                      AND s.parse_status IN ('ok', 'partial')
                      AND u.is_active = TRUE
                      {unit_filter}
                    ORDER BY u.order_index ASC, s.order_index ASC, s.person_name ASC
                    """,
                    tuple(params),
                )
                rows = [dict(row) for row in cur.fetchall()]

        for row in rows:
            row["staff_id"] = str(row["staff_id"])
            row["administrative_unit_id"] = str(row["administrative_unit_id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
            row["validation_issues"] = _decode_json(row.get("validation_issues")) or []
        return rows


__all__ = ["AdministrativeRepository"]
