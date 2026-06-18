"""
GİBTÜ bölüm/program katalog repository katmanı.

Bu repository scraper çalıştırmaz. Hazır dry-run raporunu idempotent biçimde
yazabilir ve chatbot DB-first servisi için read-only katalog listeleri döndürür.
Tek scrape run'da görülmeyen kayıtları otomatik pasife almaz.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings
from scrapers.program_catalog_scraper import normalize_for_match, normalize_program_name


REQUIRED_PROGRAM_CATALOG_TABLES: tuple[str, ...] = (
    "program_catalog_scrape_runs",
    "program_catalog_raw_snapshots",
    "program_catalog_units",
    "program_catalog_unit_aliases",
    "program_catalog_departments",
    "program_catalog_programs",
    "program_catalog_program_aliases",
    "program_catalog_sources",
    "program_catalog_candidate_ogrenim_imports",
    "program_catalog_candidate_ogrenim_entries",
    "program_catalog_quality_issues",
)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resolve_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _masked_database_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if not parsed.password:
        return database_url
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:***@{hostname}{port}" if username else f"***@{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


class ProgramCatalogRepository:
    """Program katalog tablolarına erişen izole repository."""

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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    """,
                    (list(REQUIRED_PROGRAM_CATALOG_TABLES),),
                )
                existing = {row[0] for row in cur.fetchall()}
        return [table for table in REQUIRED_PROGRAM_CATALOG_TABLES if table not in existing]

    def database_target_summary(self) -> dict[str, Any]:
        parsed = urlsplit(self._database_url)
        summary = {
            "masked_url": _masked_database_url(self._database_url),
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.lstrip("/") or None,
        }
        try:
            with self._connect() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            current_database() AS current_database,
                            current_user AS current_user,
                            inet_server_addr()::text AS server_addr,
                            inet_server_port() AS server_port
                        """
                    )
                    summary["server"] = dict(cur.fetchone())
        except Exception as exc:  # noqa: BLE001 - bağlantı raporu best-effort
            summary["connection_check_error"] = f"{type(exc).__name__}: {exc}"
        return summary

    def import_candidate_ogrenim_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Aday öğrenci #ogrenim raporunu ayrı candidate tablosuna yazar."""
        self._validate_candidate_ogrenim_report(report)
        self.ensure_schema()
        missing_tables = self.missing_required_tables()
        if missing_tables:
            raise RuntimeError(f"Program catalog tabloları eksik: {', '.join(missing_tables)}")

        records = list(report.get("records") or [])
        report_checksum = _sha256_text(_stable_json(report))
        import_run_id = f"candidate_ogrenim:{report.get('snapshot_id') or report_checksum[:24]}"
        raw_snapshot = self._candidate_snapshot_from_path(
            report.get("raw_snapshot_path"),
            import_run_id,
            report.get("source_url"),
            "candidate_page_ogrenim_raw",
            report.get("http_status"),
            report.get("fetched_at"),
        )
        section_snapshot = self._candidate_snapshot_from_path(
            report.get("section_snapshot_path"),
            import_run_id,
            report.get("source_url"),
            "candidate_page_ogrenim_section",
            report.get("http_status"),
            report.get("fetched_at"),
        )

        import_summary: dict[str, Any] = {
            "dry_run": False,
            "write_db_requested": True,
            "write_db_executed": False,
            "db_write_executed": False,
            "production_db_write_attempted": False,
            "source_type": "candidate_page_ogrenim",
            "source_confidence": "candidate_support",
            "answer_scope": "candidate_page_only",
            "is_authoritative": False,
            "is_active_verified": False,
            "db_first_answerable": True,
            "import_run_id": import_run_id,
            "source_url": report.get("source_url"),
            "report_checksum": report_checksum,
            "raw_snapshot_checksum": raw_snapshot.get("checksum") if raw_snapshot else None,
            "section_snapshot_checksum": section_snapshot.get("checksum") if section_snapshot else None,
            "database_target": self.database_target_summary(),
            "records_written": 0,
            "records_inserted": 0,
            "records_updated": 0,
            "duplicate_count": int(report.get("duplicate_count") or 0),
            "missing_field_count": sum(len(record.get("missing_fields") or []) for record in records),
            "description_missing_count": sum(1 for record in records if record.get("description_missing") is True),
            "description_missing_expected": len(records),
            "description_missing_verified": False,
            "candidate_page_ogrenim_total": 0,
            "snapshots_upserted": 0,
            "records_deactivated": 0,
            "records_deleted": 0,
        }

        with self._connect() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    existing_ids = self._existing_candidate_record_ids(cur)
                    self._upsert_candidate_scrape_run(cur, report, import_run_id, import_summary)
                    for snapshot in (raw_snapshot, section_snapshot):
                        if snapshot:
                            self._upsert_candidate_raw_snapshot(cur, snapshot)
                            import_summary["snapshots_upserted"] += 1
                    self._upsert_candidate_import_manifest(
                        cur,
                        report,
                        import_run_id,
                        report_checksum,
                        raw_snapshot,
                        section_snapshot,
                        import_summary,
                    )
                    for record in records:
                        detail_snapshot = self._candidate_snapshot_from_path(
                            record.get("detail_snapshot_path"),
                            import_run_id,
                            record.get("detail_url"),
                            "candidate_page_ogrenim_detail",
                            record.get("detail_http_status"),
                            report.get("fetched_at"),
                        )
                        if detail_snapshot:
                            self._upsert_candidate_raw_snapshot(cur, detail_snapshot)
                            import_summary["snapshots_upserted"] += 1
                        self._upsert_candidate_ogrenim_entry(
                            cur,
                            report,
                            record,
                            import_run_id,
                            report_checksum,
                            raw_snapshot,
                        )
                        import_summary["records_written"] += 1
                        if record.get("record_id") in existing_ids:
                            import_summary["records_updated"] += 1
                        else:
                            import_summary["records_inserted"] += 1

                    cur.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM program_catalog_candidate_ogrenim_entries
                        WHERE source_type = 'candidate_page_ogrenim'
                          AND is_current = TRUE
                        """
                    )
                    import_summary["candidate_page_ogrenim_total"] = int(cur.fetchone()["total"])
                    import_summary["description_missing_verified"] = (
                        import_summary["description_missing_count"] == import_summary["description_missing_expected"]
                    )
                    import_summary["write_db_executed"] = True
                    import_summary["db_write_executed"] = True
                    self._update_candidate_import_summary(cur, import_run_id, import_summary)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return import_summary

    @staticmethod
    def _validate_candidate_ogrenim_report(report: dict[str, Any]) -> None:
        if report.get("source_url") != "https://adayogrenci.gibtu.edu.tr/#ogrenim":
            raise RuntimeError("Aday öğrenci #ogrenim dışı kaynak DB'ye yazılamaz.")
        records = report.get("records") or []
        if len(records) != 23:
            raise RuntimeError(f"Aday öğrenci raporu 23 kayıt içermiyor: {len(records)}")
        if int(report.get("duplicate_count") or 0) != 0:
            raise RuntimeError("Aday öğrenci raporunda duplicate var; DB yazımı durduruldu.")
        if len(report.get("parse_warnings") or []) != 0:
            raise RuntimeError("Aday öğrenci raporunda parse warning var; DB yazımı durduruldu.")
        if int(report.get("description_missing_count") or 0) != 23:
            raise RuntimeError("Aday öğrenci raporunda description_missing=23 doğrulaması sağlanmadı.")
        for record in records:
            if not record.get("record_id") or not record.get("program_name"):
                raise RuntimeError("Aday öğrenci kaydında record_id/program_name eksik.")

    @staticmethod
    def _candidate_snapshot_from_path(
        path_value: Any,
        scrape_run_id: str,
        source_url: Any,
        source_type: str,
        http_status: Any,
        fetched_at: Any,
    ) -> dict[str, Any] | None:
        path = _resolve_path(path_value)
        if not path or not path.exists():
            return None
        raw_content = path.read_text(encoding="utf-8")
        checksum = _sha256_text(raw_content)
        return {
            "snapshot_id": f"{source_type}:{checksum[:24]}",
            "scrape_run_id": scrape_run_id,
            "source_url": str(source_url or ""),
            "source_type": source_type,
            "http_status": http_status,
            "checksum": checksum,
            "fetched_at": fetched_at,
            "raw_content": raw_content,
            "parse_status": "parsed",
            "path": str(path),
        }

    @staticmethod
    def _candidate_record_checksum(record: dict[str, Any]) -> str:
        payload = {
            "record_id": record.get("record_id"),
            "program_name": record.get("program_name"),
            "parent_unit": record.get("parent_unit"),
            "education_level": record.get("education_level"),
            "program_type": record.get("program_type"),
            "detail_url": record.get("detail_url"),
            "description_missing": record.get("description_missing"),
        }
        return _sha256_text(_stable_json(payload))

    @staticmethod
    def _candidate_unit_type(record: dict[str, Any]) -> str:
        program_type = str(record.get("program_type") or "")
        parent = normalize_for_match(record.get("parent_unit"))
        if program_type == "graduate_candidate":
            return "candidate_group"
        if "associate" in program_type or "meslek yuksekokulu" in parent:
            return "vocational_school"
        if "school" in program_type or "yuksekokul" in parent:
            return "school"
        if "faculty" in program_type or "fakulte" in parent:
            return "faculty"
        return "candidate_group"

    @staticmethod
    def _existing_candidate_record_ids(cur: Any) -> set[str]:
        cur.execute(
            """
            SELECT record_id
            FROM program_catalog_candidate_ogrenim_entries
            WHERE source_type = 'candidate_page_ogrenim'
            """
        )
        return {str(row["record_id"]) for row in cur.fetchall()}

    def _upsert_candidate_scrape_run(
        self,
        cur: Any,
        report: dict[str, Any],
        import_run_id: str,
        import_summary: dict[str, Any],
    ) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_scrape_runs (
                scrape_run_id, scraper_name, metadata_version,
                started_at, finished_at, status, validation_status,
                processed_url_count, skipped_url_count, successful_url_count,
                failed_url_count, not_processed_due_to_limit_count,
                unit_count, department_count, program_count, alias_count,
                needs_review_count, duplicate_count, critical_error_count,
                config, summary
            )
            VALUES (
                %s, %s, %s,
                %s, NOW(), 'success', 'candidate_page_only',
                %s, 0, %s,
                0, 0,
                0, 0, %s, %s,
                0, %s, 0,
                %s::jsonb, %s::jsonb
            )
            ON CONFLICT (scrape_run_id) DO UPDATE SET
                finished_at = NOW(),
                status = EXCLUDED.status,
                validation_status = EXCLUDED.validation_status,
                processed_url_count = EXCLUDED.processed_url_count,
                successful_url_count = EXCLUDED.successful_url_count,
                program_count = EXCLUDED.program_count,
                alias_count = EXCLUDED.alias_count,
                duplicate_count = EXCLUDED.duplicate_count,
                config = EXCLUDED.config,
                summary = EXCLUDED.summary,
                updated_at = NOW()
            """,
            (
                import_run_id,
                report.get("scraper_name"),
                report.get("metadata_version"),
                report.get("fetched_at"),
                int(report.get("detail_processed_record_count") or report.get("record_count") or 0),
                int(report.get("detail_processed_record_count") or report.get("record_count") or 0),
                int(report.get("record_count") or 0),
                sum(len(record.get("aliases") or []) for record in report.get("records") or []),
                int(report.get("duplicate_count") or 0),
                Json({
                    "source_type": "candidate_page_ogrenim",
                    "answer_scope": "candidate_page_only",
                    "write_db_requested": True,
                }, dumps=_json_dumps),
                Json(import_summary, dumps=_json_dumps),
            ),
        )

    @staticmethod
    def _upsert_candidate_raw_snapshot(cur: Any, snapshot: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_raw_snapshots (
                snapshot_id, scrape_run_id, source_url, source_type,
                http_status, checksum, fetched_at, raw_content, parse_status,
                validation_report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                scrape_run_id = EXCLUDED.scrape_run_id,
                source_url = EXCLUDED.source_url,
                source_type = EXCLUDED.source_type,
                http_status = EXCLUDED.http_status,
                checksum = EXCLUDED.checksum,
                fetched_at = EXCLUDED.fetched_at,
                raw_content = EXCLUDED.raw_content,
                parse_status = EXCLUDED.parse_status,
                updated_at = NOW()
            """,
            (
                snapshot.get("snapshot_id"),
                snapshot.get("scrape_run_id"),
                snapshot.get("source_url"),
                snapshot.get("source_type"),
                snapshot.get("http_status"),
                snapshot.get("checksum"),
                snapshot.get("fetched_at"),
                snapshot.get("raw_content"),
                snapshot.get("parse_status"),
            ),
        )

    def _upsert_candidate_import_manifest(
        self,
        cur: Any,
        report: dict[str, Any],
        import_run_id: str,
        report_checksum: str,
        raw_snapshot: dict[str, Any] | None,
        section_snapshot: dict[str, Any] | None,
        import_summary: dict[str, Any],
    ) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_candidate_ogrenim_imports (
                import_run_id, source_url, report_checksum,
                raw_snapshot_checksum, section_snapshot_checksum,
                snapshot_id, raw_snapshot_path, section_snapshot_path,
                record_count, detail_link_record_count, detail_unique_url_count,
                detail_processed_record_count, description_missing_count,
                duplicate_count, parse_warning_count, db_write_executed,
                import_summary, report_json
            )
            VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, FALSE,
                %s::jsonb, %s::jsonb
            )
            ON CONFLICT (import_run_id) DO UPDATE SET
                report_checksum = EXCLUDED.report_checksum,
                raw_snapshot_checksum = EXCLUDED.raw_snapshot_checksum,
                section_snapshot_checksum = EXCLUDED.section_snapshot_checksum,
                snapshot_id = EXCLUDED.snapshot_id,
                raw_snapshot_path = EXCLUDED.raw_snapshot_path,
                section_snapshot_path = EXCLUDED.section_snapshot_path,
                record_count = EXCLUDED.record_count,
                detail_link_record_count = EXCLUDED.detail_link_record_count,
                detail_unique_url_count = EXCLUDED.detail_unique_url_count,
                detail_processed_record_count = EXCLUDED.detail_processed_record_count,
                description_missing_count = EXCLUDED.description_missing_count,
                duplicate_count = EXCLUDED.duplicate_count,
                parse_warning_count = EXCLUDED.parse_warning_count,
                import_summary = EXCLUDED.import_summary,
                report_json = EXCLUDED.report_json,
                updated_at = NOW()
            """,
            (
                import_run_id,
                report.get("source_url"),
                report_checksum,
                raw_snapshot.get("checksum") if raw_snapshot else None,
                section_snapshot.get("checksum") if section_snapshot else None,
                report.get("snapshot_id"),
                report.get("raw_snapshot_path"),
                report.get("section_snapshot_path"),
                int(report.get("record_count") or 0),
                int(report.get("detail_link_record_count") or 0),
                int(report.get("detail_unique_url_count") or 0),
                int(report.get("detail_processed_record_count") or 0),
                int(report.get("description_missing_count") or 0),
                int(report.get("duplicate_count") or 0),
                len(report.get("parse_warnings") or []),
                Json(import_summary, dumps=_json_dumps),
                Json(report, dumps=_json_dumps),
            ),
        )

    @staticmethod
    def _update_candidate_import_summary(cur: Any, import_run_id: str, import_summary: dict[str, Any]) -> None:
        cur.execute(
            """
            UPDATE program_catalog_candidate_ogrenim_imports
            SET db_write_executed = TRUE,
                import_summary = %s::jsonb,
                updated_at = NOW()
            WHERE import_run_id = %s
            """,
            (Json(import_summary, dumps=_json_dumps), import_run_id),
        )

    def _upsert_candidate_ogrenim_entry(
        self,
        cur: Any,
        report: dict[str, Any],
        record: dict[str, Any],
        import_run_id: str,
        report_checksum: str,
        raw_snapshot: dict[str, Any] | None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_candidate_ogrenim_entries (
                record_id, raw_visible_name, program_name, normalized_program_name,
                parent_unit, normalized_parent_unit, unit_type,
                education_level, education_label, education_language, duration,
                program_type, description, description_missing,
                program_card_link, detail_url, detail_http_status,
                detail_processed, detail_snapshot_path,
                source_url, source_type, source_confidence, answer_scope,
                is_authoritative, is_active_verified, db_first_answerable,
                aliases, missing_fields, parse_warnings,
                snapshot_id, checksum, report_checksum, import_run_id, is_current
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, 'candidate_page_ogrenim', 'candidate_support', 'candidate_page_only',
                FALSE, FALSE, TRUE,
                %s::jsonb, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s, TRUE
            )
            ON CONFLICT (record_id) DO UPDATE SET
                raw_visible_name = EXCLUDED.raw_visible_name,
                program_name = EXCLUDED.program_name,
                normalized_program_name = EXCLUDED.normalized_program_name,
                parent_unit = EXCLUDED.parent_unit,
                normalized_parent_unit = EXCLUDED.normalized_parent_unit,
                unit_type = EXCLUDED.unit_type,
                education_level = EXCLUDED.education_level,
                education_label = EXCLUDED.education_label,
                education_language = EXCLUDED.education_language,
                duration = EXCLUDED.duration,
                program_type = EXCLUDED.program_type,
                description = EXCLUDED.description,
                description_missing = EXCLUDED.description_missing,
                program_card_link = EXCLUDED.program_card_link,
                detail_url = EXCLUDED.detail_url,
                detail_http_status = EXCLUDED.detail_http_status,
                detail_processed = EXCLUDED.detail_processed,
                detail_snapshot_path = EXCLUDED.detail_snapshot_path,
                source_url = EXCLUDED.source_url,
                source_type = EXCLUDED.source_type,
                source_confidence = EXCLUDED.source_confidence,
                answer_scope = EXCLUDED.answer_scope,
                is_authoritative = EXCLUDED.is_authoritative,
                is_active_verified = EXCLUDED.is_active_verified,
                db_first_answerable = EXCLUDED.db_first_answerable,
                aliases = EXCLUDED.aliases,
                missing_fields = EXCLUDED.missing_fields,
                parse_warnings = EXCLUDED.parse_warnings,
                snapshot_id = EXCLUDED.snapshot_id,
                checksum = EXCLUDED.checksum,
                report_checksum = EXCLUDED.report_checksum,
                import_run_id = EXCLUDED.import_run_id,
                is_current = TRUE,
                updated_at = NOW()
            """,
            (
                record.get("record_id"),
                record.get("raw_visible_name"),
                record.get("program_name"),
                record.get("normalized_name") or normalize_program_name(record.get("program_name")),
                record.get("parent_unit"),
                record.get("normalized_parent_unit"),
                self._candidate_unit_type(record),
                record.get("education_level"),
                record.get("education_label"),
                record.get("education_language"),
                record.get("duration"),
                record.get("program_type"),
                record.get("description"),
                bool(record.get("description_missing")),
                record.get("program_card_link"),
                record.get("detail_url"),
                record.get("detail_http_status"),
                bool(record.get("detail_processed")),
                record.get("detail_snapshot_path"),
                report.get("source_url"),
                Json(record.get("aliases") or [], dumps=_json_dumps),
                Json(record.get("missing_fields") or [], dumps=_json_dumps),
                Json(record.get("parse_warnings") or [], dumps=_json_dumps),
                raw_snapshot.get("snapshot_id") if raw_snapshot else None,
                self._candidate_record_checksum(record),
                report_checksum,
                import_run_id,
            ),
        )

    def import_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Hazır scrape raporunu yazar; pasife alma yapmaz."""
        validation = report.get("validation_report") or {}
        if validation.get("critical_error_count", 0) != 0:
            raise RuntimeError("Program catalog raporunda critical error var; DB yazımı durduruldu.")
        if validation.get("duplicate_count", 0) != 0:
            raise RuntimeError("Program catalog raporunda duplicate var; DB yazımı durduruldu.")

        self.ensure_schema()
        missing_tables = self.missing_required_tables()
        if missing_tables:
            raise RuntimeError(f"Program catalog tabloları eksik: {', '.join(missing_tables)}")

        counts = {
            "write_db_executed": True,
            "production_db_write_attempted": False,
            "runs_upserted": 0,
            "snapshots_upserted": 0,
            "units_upserted": 0,
            "unit_aliases_upserted": 0,
            "departments_upserted": 0,
            "programs_upserted": 0,
            "program_aliases_upserted": 0,
            "sources_inserted": 0,
            "quality_issues_inserted": 0,
            "units_skipped_needs_review": 0,
            "records_skipped_needs_review": 0,
            "records_skipped_missing_unit": 0,
            "records_marked_missing_in_current_run": 0,
            "records_deactivated": 0,
        }

        with self._connect() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    self._upsert_run(cur, report)
                    counts["runs_upserted"] = 1
                    for snapshot in report.get("snapshots") or []:
                        self._upsert_snapshot(cur, report, snapshot)
                        counts["snapshots_upserted"] += 1

                    unit_ids: dict[str, str] = {}
                    for unit in report.get("units") or []:
                        if not self._can_import_unit(unit):
                            counts["units_skipped_needs_review"] += 1
                            continue
                        unit_id = self._upsert_unit(cur, report, unit)
                        unit_ids[str(unit.get("normalized_unit_name"))] = unit_id
                        counts["units_upserted"] += 1
                        counts["unit_aliases_upserted"] += self._upsert_unit_aliases(cur, unit_id, unit)

                    for record in report.get("records") or []:
                        if not self._can_import_record(record):
                            counts["records_skipped_needs_review"] += 1
                            continue
                        unit_id = unit_ids.get(str(record.get("normalized_unit_name")))
                        if not unit_id:
                            counts["records_skipped_missing_unit"] += 1
                            continue
                        if record.get("item_kind") in {"department", "academic_department"}:
                            entity_id = self._upsert_department(cur, report, record, unit_id)
                            counts["departments_upserted"] += 1
                            counts["program_aliases_upserted"] += self._upsert_program_aliases(
                                cur,
                                record,
                                department_id=entity_id,
                            )
                            self._insert_source(cur, report, record, unit_id, department_id=entity_id)
                        else:
                            entity_id = self._upsert_program(cur, report, record, unit_id)
                            counts["programs_upserted"] += 1
                            counts["program_aliases_upserted"] += self._upsert_program_aliases(
                                cur,
                                record,
                                program_id=entity_id,
                            )
                            self._insert_source(cur, report, record, unit_id, program_id=entity_id)
                        counts["sources_inserted"] += 1

                    self._replace_quality_issues(cur, report)
                    counts["quality_issues_inserted"] = len(report.get("quality_issues") or [])
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return counts

    @staticmethod
    def _can_import_unit(unit: dict[str, Any]) -> bool:
        if not unit.get("needs_review"):
            return True
        return unit.get("source_type") == "official_gibtu" and unit.get("match_status") == "official"

    @staticmethod
    def _can_import_record(record: dict[str, Any]) -> bool:
        return not bool(record.get("needs_review"))

    def list_units(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    WITH official_units AS (
                        SELECT
                            u.id::text AS id,
                            u.unit_name,
                            u.normalized_unit_name,
                            u.unit_type,
                            u.source_url,
                            u.official_gibtu_url,
                            u.match_status,
                            u.needs_review,
                            u.missing_in_current_run,
                            NULL::text AS source_type,
                            NULL::text AS source_confidence,
                            NULL::text AS answer_scope,
                            TRUE AS is_authoritative,
                            TRUE AS is_active_verified,
                            TRUE AS db_first_answerable,
                            COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                        FROM program_catalog_units u
                        LEFT JOIN program_catalog_unit_aliases a
                            ON a.unit_id = u.id AND a.is_active = TRUE
                        WHERE u.is_active = TRUE
                        GROUP BY u.id
                    ),
                    candidate_units AS (
                        SELECT
                            ('candidate-ogrenim-unit:' || normalized_parent_unit) AS id,
                            parent_unit AS unit_name,
                            normalized_parent_unit AS normalized_unit_name,
                            unit_type,
                            source_url,
                            NULL::text AS official_gibtu_url,
                            source_confidence AS match_status,
                            FALSE AS needs_review,
                            FALSE AS missing_in_current_run,
                            source_type,
                            source_confidence,
                            answer_scope,
                            is_authoritative,
                            is_active_verified,
                            db_first_answerable,
                            CASE normalized_parent_unit
                                WHEN 'saglik hizmetleri meslek yuksekokulu'
                                    THEN jsonb_build_array(parent_unit, 'SHMYO', 'Sağlık Hizmetleri MYO')
                                WHEN 'teknik bilimler meslek yuksekokulu'
                                    THEN jsonb_build_array(parent_unit, 'TBMYO', 'Teknik Bilimler MYO')
                                WHEN 'muhendislik ve doga bilimleri fakultesi'
                                    THEN jsonb_build_array(parent_unit, 'MDBF')
                                WHEN 'saglik bilimleri fakultesi'
                                    THEN jsonb_build_array(parent_unit, 'SBF')
                                WHEN 'yabanci diller yuksekokulu'
                                    THEN jsonb_build_array(parent_unit, 'YDYO')
                                ELSE jsonb_build_array(parent_unit)
                            END AS aliases
                        FROM program_catalog_candidate_ogrenim_entries
                        WHERE source_type = 'candidate_page_ogrenim'
                          AND is_current = TRUE
                          AND db_first_answerable = TRUE
                          AND parent_unit IS NOT NULL
                        GROUP BY
                            normalized_parent_unit, parent_unit, unit_type, source_url,
                            source_type, source_confidence, answer_scope,
                            is_authoritative, is_active_verified, db_first_answerable
                    )
                    SELECT *
                    FROM official_units
                    UNION ALL
                    SELECT *
                    FROM candidate_units
                    ORDER BY unit_type, unit_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def list_catalog_entries(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    WITH official_entries AS (
                        SELECT
                            d.id::text AS id,
                            'department' AS item_kind,
                            d.department_name AS program_name,
                            d.normalized_department_name AS normalized_program_name,
                            d.education_level,
                            d.source_url,
                            d.official_gibtu_url,
                            d.yokatlas_url,
                            NULL::text AS program_code,
                            d.match_status,
                            d.needs_review,
                            d.missing_in_current_run,
                            u.id::text AS unit_id,
                            u.unit_name,
                            u.normalized_unit_name,
                            u.unit_type,
                            NULL::text AS source_type,
                            NULL::text AS source_confidence,
                            NULL::text AS answer_scope,
                            TRUE AS is_authoritative,
                            TRUE AS is_active_verified,
                            TRUE AS db_first_answerable,
                            NULL::text AS education_language,
                            NULL::text AS duration,
                            'department'::text AS program_type,
                            FALSE AS description_missing,
                            NULL::text AS detail_url,
                            NULL::text AS program_card_link,
                            COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                        FROM program_catalog_departments d
                        JOIN program_catalog_units u ON u.id = d.unit_id
                        LEFT JOIN program_catalog_program_aliases a
                            ON a.department_id = d.id AND a.is_active = TRUE
                        WHERE d.is_active = TRUE AND u.is_active = TRUE
                        GROUP BY d.id, u.id
                        UNION ALL
                        SELECT
                            p.id::text AS id,
                            p.program_kind AS item_kind,
                            p.program_name,
                            p.normalized_program_name,
                            p.education_level,
                            p.source_url,
                            p.official_gibtu_url,
                            p.yokatlas_url,
                            p.program_code,
                            p.match_status,
                            p.needs_review,
                            p.missing_in_current_run,
                            u.id::text AS unit_id,
                            u.unit_name,
                            u.normalized_unit_name,
                            u.unit_type,
                            NULL::text AS source_type,
                            NULL::text AS source_confidence,
                            NULL::text AS answer_scope,
                            TRUE AS is_authoritative,
                            TRUE AS is_active_verified,
                            TRUE AS db_first_answerable,
                            NULL::text AS education_language,
                            NULL::text AS duration,
                            p.program_kind AS program_type,
                            FALSE AS description_missing,
                            NULL::text AS detail_url,
                            NULL::text AS program_card_link,
                            COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                        FROM program_catalog_programs p
                        JOIN program_catalog_units u ON u.id = p.unit_id
                        LEFT JOIN program_catalog_program_aliases a
                            ON a.program_id = p.id AND a.is_active = TRUE
                        WHERE p.is_active = TRUE AND u.is_active = TRUE
                        GROUP BY p.id, u.id
                    ),
                    candidate_entries AS (
                        SELECT
                            id::text AS id,
                            program_type AS item_kind,
                            program_name,
                            normalized_program_name,
                            education_level,
                            source_url,
                            NULL::text AS official_gibtu_url,
                            NULL::text AS yokatlas_url,
                            NULL::text AS program_code,
                            source_confidence AS match_status,
                            FALSE AS needs_review,
                            FALSE AS missing_in_current_run,
                            COALESCE('candidate-ogrenim-unit:' || normalized_parent_unit, 'candidate-ogrenim-unit:graduate') AS unit_id,
                            COALESCE(parent_unit, 'Aday Öğrenci Öğrenim Lisansüstü Adayları') AS unit_name,
                            COALESCE(normalized_parent_unit, 'aday ogrenci ogrenim lisansustu adaylari') AS normalized_unit_name,
                            unit_type,
                            source_type,
                            source_confidence,
                            answer_scope,
                            is_authoritative,
                            is_active_verified,
                            db_first_answerable,
                            education_language,
                            duration,
                            program_type,
                            description_missing,
                            detail_url,
                            program_card_link,
                            aliases
                        FROM program_catalog_candidate_ogrenim_entries
                        WHERE source_type = 'candidate_page_ogrenim'
                          AND is_current = TRUE
                          AND db_first_answerable = TRUE
                    )
                    SELECT *
                    FROM official_entries
                    UNION ALL
                    SELECT *
                    FROM candidate_entries
                    ORDER BY unit_name, program_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["unit_id"] = str(row["unit_id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def _legacy_list_units_unused(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        u.id,
                        u.unit_name,
                        u.normalized_unit_name,
                        u.unit_type,
                        u.source_url,
                        u.official_gibtu_url,
                        u.match_status,
                        u.needs_review,
                        u.missing_in_current_run,
                        COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                    FROM program_catalog_units u
                    LEFT JOIN program_catalog_unit_aliases a
                        ON a.unit_id = u.id AND a.is_active = TRUE
                    WHERE u.is_active = TRUE
                    GROUP BY u.id
                    ORDER BY u.unit_type, u.unit_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def _legacy_list_catalog_entries_unused(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        d.id,
                        'department' AS item_kind,
                        d.department_name AS program_name,
                        d.normalized_department_name AS normalized_program_name,
                        d.education_level,
                        d.source_url,
                        d.official_gibtu_url,
                        d.yokatlas_url,
                        NULL::text AS program_code,
                        d.match_status,
                        d.needs_review,
                        d.missing_in_current_run,
                        u.id AS unit_id,
                        u.unit_name,
                        u.normalized_unit_name,
                        u.unit_type,
                        COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                    FROM program_catalog_departments d
                    JOIN program_catalog_units u ON u.id = d.unit_id
                    LEFT JOIN program_catalog_program_aliases a
                        ON a.department_id = d.id AND a.is_active = TRUE
                    WHERE d.is_active = TRUE AND u.is_active = TRUE
                    GROUP BY d.id, u.id
                    UNION ALL
                    SELECT
                        p.id,
                        p.program_kind AS item_kind,
                        p.program_name,
                        p.normalized_program_name,
                        p.education_level,
                        p.source_url,
                        p.official_gibtu_url,
                        p.yokatlas_url,
                        p.program_code,
                        p.match_status,
                        p.needs_review,
                        p.missing_in_current_run,
                        u.id AS unit_id,
                        u.unit_name,
                        u.normalized_unit_name,
                        u.unit_type,
                        COALESCE(jsonb_agg(a.alias_text) FILTER (WHERE a.alias_text IS NOT NULL), '[]'::jsonb) AS aliases
                    FROM program_catalog_programs p
                    JOIN program_catalog_units u ON u.id = p.unit_id
                    LEFT JOIN program_catalog_program_aliases a
                        ON a.program_id = p.id AND a.is_active = TRUE
                    WHERE p.is_active = TRUE AND u.is_active = TRUE
                    GROUP BY p.id, u.id
                    ORDER BY unit_name, program_name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["id"] = str(row["id"])
            row["unit_id"] = str(row["unit_id"])
            row["aliases"] = _decode_json(row.get("aliases")) or []
        return rows

    def _upsert_run(self, cur: Any, report: dict[str, Any]) -> None:
        validation = report.get("validation_report") or {}
        cur.execute(
            """
            INSERT INTO program_catalog_scrape_runs (
                scrape_run_id, scraper_name, metadata_version,
                started_at, finished_at, status, validation_status,
                processed_url_count, skipped_url_count, successful_url_count,
                failed_url_count, not_processed_due_to_limit_count,
                unit_count, department_count, program_count, alias_count,
                needs_review_count, duplicate_count, critical_error_count,
                config, summary
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s::jsonb, %s::jsonb
            )
            ON CONFLICT (scrape_run_id) DO UPDATE SET
                finished_at = EXCLUDED.finished_at,
                status = EXCLUDED.status,
                validation_status = EXCLUDED.validation_status,
                processed_url_count = EXCLUDED.processed_url_count,
                skipped_url_count = EXCLUDED.skipped_url_count,
                successful_url_count = EXCLUDED.successful_url_count,
                failed_url_count = EXCLUDED.failed_url_count,
                not_processed_due_to_limit_count = EXCLUDED.not_processed_due_to_limit_count,
                unit_count = EXCLUDED.unit_count,
                department_count = EXCLUDED.department_count,
                program_count = EXCLUDED.program_count,
                alias_count = EXCLUDED.alias_count,
                needs_review_count = EXCLUDED.needs_review_count,
                duplicate_count = EXCLUDED.duplicate_count,
                critical_error_count = EXCLUDED.critical_error_count,
                config = EXCLUDED.config,
                summary = EXCLUDED.summary,
                updated_at = NOW()
            """,
            (
                report.get("scrape_run_id"),
                report.get("scraper_name"),
                report.get("metadata_version"),
                report.get("started_at"),
                report.get("finished_at"),
                "success" if report.get("success") else "partial",
                "valid" if validation.get("db_write_ready") else "needs_review",
                validation.get("processed_url_count", 0),
                validation.get("skipped_url_count", 0),
                validation.get("successful_url_count", 0),
                validation.get("failed_url_count", 0),
                validation.get("not_processed_due_to_limit_count", 0),
                validation.get("academic_unit_count", 0),
                validation.get("department_count", 0),
                validation.get("program_count", 0),
                validation.get("alias_count", 0),
                len(validation.get("needs_review_records") or []),
                validation.get("duplicate_count", 0),
                validation.get("critical_error_count", 0),
                Json({"dry_run": report.get("dry_run"), "write_db_requested": report.get("write_db_requested")}, dumps=_json_dumps),
                Json(validation, dumps=_json_dumps),
            ),
        )

    def _upsert_snapshot(self, cur: Any, report: dict[str, Any], snapshot: dict[str, Any]) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_raw_snapshots (
                snapshot_id, scrape_run_id, source_url, source_type,
                http_status, checksum, fetched_at, raw_content, parse_status,
                validation_report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, '{}'::jsonb)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                scrape_run_id = EXCLUDED.scrape_run_id,
                source_url = EXCLUDED.source_url,
                source_type = EXCLUDED.source_type,
                http_status = EXCLUDED.http_status,
                checksum = EXCLUDED.checksum,
                fetched_at = EXCLUDED.fetched_at,
                parse_status = EXCLUDED.parse_status,
                updated_at = NOW()
            """,
            (
                snapshot.get("snapshot_id"),
                report.get("scrape_run_id"),
                snapshot.get("source_url"),
                snapshot.get("source_type"),
                snapshot.get("http_status"),
                snapshot.get("checksum"),
                snapshot.get("fetched_at"),
                snapshot.get("parse_status", "unknown"),
            ),
        )

    def _upsert_unit(self, cur: Any, report: dict[str, Any], unit: dict[str, Any]) -> str:
        academic_match = self._match_existing_academic_unit(cur, unit)
        cur.execute(
            """
            INSERT INTO program_catalog_units (
                unit_name, normalized_unit_name, unit_type,
                source_url, official_gibtu_url, existing_academic_unit_id,
                matched_academic_unit_key, source_priority, match_status,
                needs_review, missing_in_current_run, is_active,
                snapshot_id, checksum, last_seen_run_id
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, TRUE,
                %s, %s, %s
            )
            ON CONFLICT (normalized_unit_name) WHERE parent_unit_id IS NULL
            DO UPDATE SET
                unit_name = EXCLUDED.unit_name,
                unit_type = EXCLUDED.unit_type,
                source_url = COALESCE(EXCLUDED.source_url, program_catalog_units.source_url),
                official_gibtu_url = COALESCE(EXCLUDED.official_gibtu_url, program_catalog_units.official_gibtu_url),
                existing_academic_unit_id = COALESCE(EXCLUDED.existing_academic_unit_id, program_catalog_units.existing_academic_unit_id),
                matched_academic_unit_key = COALESCE(EXCLUDED.matched_academic_unit_key, program_catalog_units.matched_academic_unit_key),
                match_status = EXCLUDED.match_status,
                needs_review = EXCLUDED.needs_review,
                missing_in_current_run = EXCLUDED.missing_in_current_run,
                snapshot_id = COALESCE(EXCLUDED.snapshot_id, program_catalog_units.snapshot_id),
                checksum = COALESCE(EXCLUDED.checksum, program_catalog_units.checksum),
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                updated_at = NOW()
            RETURNING id
            """,
            (
                unit.get("unit_name"),
                unit.get("normalized_unit_name") or normalize_for_match(unit.get("unit_name")),
                unit.get("unit_type"),
                unit.get("source_url"),
                unit.get("official_gibtu_url") or unit.get("source_url"),
                academic_match.get("id"),
                academic_match.get("key") or unit.get("matched_academic_unit_key"),
                self._source_priority(unit.get("source_type")),
                unit.get("match_status", "unknown"),
                bool(unit.get("needs_review")),
                bool(unit.get("missing_in_current_run")),
                unit.get("snapshot_id"),
                unit.get("checksum"),
                report.get("scrape_run_id"),
            ),
        )
        return str(cur.fetchone()["id"])

    @staticmethod
    def _match_existing_academic_unit(cur: Any, unit: dict[str, Any]) -> dict[str, Any]:
        normalized = unit.get("normalized_unit_name") or normalize_for_match(unit.get("unit_name"))
        try:
            cur.execute(
                """
                SELECT id, unit_name_normalized
                FROM academic_units
                WHERE unit_name_normalized = %s
                LIMIT 1
                """,
                (normalized,),
            )
            row = cur.fetchone()
        except Exception:
            row = None
        if not row:
            return {}
        return {"id": row["id"], "key": row["unit_name_normalized"]}

    def _upsert_unit_aliases(self, cur: Any, unit_id: str, unit: dict[str, Any]) -> int:
        count = 0
        aliases = set(unit.get("aliases") or [])
        aliases.add(str(unit.get("unit_name") or ""))
        for alias in aliases:
            normalized = normalize_for_match(alias)
            if not normalized:
                continue
            cur.execute(
                """
                INSERT INTO program_catalog_unit_aliases (
                    unit_id, alias_text, normalized_alias, alias_type, source_url, is_active
                )
                VALUES (%s, %s, %s, 'generated', %s, TRUE)
                ON CONFLICT (normalized_alias, unit_id) DO UPDATE SET
                    alias_text = EXCLUDED.alias_text,
                    source_url = COALESCE(EXCLUDED.source_url, program_catalog_unit_aliases.source_url),
                    is_active = TRUE,
                    updated_at = NOW()
                """,
                (unit_id, alias, normalized, unit.get("source_url")),
            )
            count += 1
        return count

    def _upsert_department(self, cur: Any, report: dict[str, Any], record: dict[str, Any], unit_id: str) -> str:
        cur.execute(
            """
            INSERT INTO program_catalog_departments (
                unit_id, department_name, normalized_department_name,
                education_level, source_url, official_gibtu_url, yokatlas_url,
                source_priority, match_status, needs_review,
                missing_in_current_run, is_active, snapshot_id, checksum,
                last_seen_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            ON CONFLICT (unit_id, normalized_department_name) DO UPDATE SET
                department_name = EXCLUDED.department_name,
                education_level = EXCLUDED.education_level,
                source_url = COALESCE(EXCLUDED.source_url, program_catalog_departments.source_url),
                official_gibtu_url = COALESCE(EXCLUDED.official_gibtu_url, program_catalog_departments.official_gibtu_url),
                yokatlas_url = COALESCE(EXCLUDED.yokatlas_url, program_catalog_departments.yokatlas_url),
                match_status = EXCLUDED.match_status,
                needs_review = EXCLUDED.needs_review,
                missing_in_current_run = EXCLUDED.missing_in_current_run,
                snapshot_id = COALESCE(EXCLUDED.snapshot_id, program_catalog_departments.snapshot_id),
                checksum = COALESCE(EXCLUDED.checksum, program_catalog_departments.checksum),
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                updated_at = NOW()
            RETURNING id
            """,
            (
                unit_id,
                record.get("program_name"),
                record.get("normalized_program_name") or normalize_program_name(record.get("program_name")),
                record.get("education_level"),
                record.get("source_url"),
                record.get("official_gibtu_url"),
                record.get("yokatlas_url"),
                self._source_priority(record.get("source_type")),
                record.get("match_status"),
                bool(record.get("needs_review")),
                bool(record.get("missing_in_current_run")),
                record.get("snapshot_id"),
                record.get("checksum"),
                report.get("scrape_run_id"),
            ),
        )
        return str(cur.fetchone()["id"])

    def _upsert_program(self, cur: Any, report: dict[str, Any], record: dict[str, Any], unit_id: str) -> str:
        cur.execute(
            """
            INSERT INTO program_catalog_programs (
                unit_id, program_name, normalized_program_name,
                education_level, program_kind, source_url, official_gibtu_url,
                yokatlas_url, program_code, source_priority, match_status,
                needs_review, missing_in_current_run, is_active, snapshot_id,
                checksum, last_seen_run_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
            ON CONFLICT (unit_id, normalized_program_name, education_level) DO UPDATE SET
                program_name = EXCLUDED.program_name,
                program_kind = EXCLUDED.program_kind,
                source_url = COALESCE(EXCLUDED.source_url, program_catalog_programs.source_url),
                official_gibtu_url = COALESCE(EXCLUDED.official_gibtu_url, program_catalog_programs.official_gibtu_url),
                yokatlas_url = COALESCE(EXCLUDED.yokatlas_url, program_catalog_programs.yokatlas_url),
                program_code = COALESCE(EXCLUDED.program_code, program_catalog_programs.program_code),
                match_status = EXCLUDED.match_status,
                needs_review = EXCLUDED.needs_review,
                missing_in_current_run = EXCLUDED.missing_in_current_run,
                snapshot_id = COALESCE(EXCLUDED.snapshot_id, program_catalog_programs.snapshot_id),
                checksum = COALESCE(EXCLUDED.checksum, program_catalog_programs.checksum),
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                updated_at = NOW()
            RETURNING id
            """,
            (
                unit_id,
                record.get("program_name"),
                record.get("normalized_program_name") or normalize_program_name(record.get("program_name")),
                record.get("education_level"),
                record.get("item_kind", "program"),
                record.get("source_url"),
                record.get("official_gibtu_url"),
                record.get("yokatlas_url"),
                record.get("program_code"),
                self._source_priority(record.get("source_type")),
                record.get("match_status"),
                bool(record.get("needs_review")),
                bool(record.get("missing_in_current_run")),
                record.get("snapshot_id"),
                record.get("checksum"),
                report.get("scrape_run_id"),
            ),
        )
        return str(cur.fetchone()["id"])

    def _upsert_program_aliases(
        self,
        cur: Any,
        record: dict[str, Any],
        program_id: str | None = None,
        department_id: str | None = None,
    ) -> int:
        count = 0
        aliases = set(record.get("aliases") or [])
        aliases.add(str(record.get("program_name") or ""))
        for alias in aliases:
            normalized = normalize_program_name(alias)
            if not normalized:
                continue
            cur.execute(
                """
                INSERT INTO program_catalog_program_aliases (
                    program_id, department_id, alias_text, normalized_alias,
                    alias_type, source_url, is_active
                )
                VALUES (%s, %s, %s, %s, 'generated', %s, TRUE)
                ON CONFLICT DO NOTHING
                """,
                (program_id, department_id, alias, normalized, record.get("source_url")),
            )
            count += 1
        return count

    def _insert_source(
        self,
        cur: Any,
        report: dict[str, Any],
        record: dict[str, Any],
        unit_id: str,
        department_id: str | None = None,
        program_id: str | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO program_catalog_sources (
                scrape_run_id, unit_id, department_id, program_id,
                source_type, source_url, source_priority, match_status,
                evidence_text, snapshot_id, checksum
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                report.get("scrape_run_id"),
                unit_id,
                department_id,
                program_id,
                record.get("source_type"),
                record.get("source_url") or record.get("yokatlas_url") or "",
                self._source_priority(record.get("source_type")),
                record.get("match_status"),
                record.get("evidence_text"),
                record.get("snapshot_id"),
                record.get("checksum"),
            ),
        )

    def _replace_quality_issues(self, cur: Any, report: dict[str, Any]) -> None:
        cur.execute(
            "DELETE FROM program_catalog_quality_issues WHERE scrape_run_id = %s",
            (report.get("scrape_run_id"),),
        )
        for issue in report.get("quality_issues") or []:
            cur.execute(
                """
                INSERT INTO program_catalog_quality_issues (
                    scrape_run_id, severity, issue_code, message, source_url,
                    entity_type, entity_name, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    report.get("scrape_run_id"),
                    issue.get("severity"),
                    issue.get("issue_code"),
                    issue.get("message"),
                    issue.get("source_url"),
                    issue.get("entity_type"),
                    issue.get("entity_name"),
                    Json(issue.get("details") or {}, dumps=_json_dumps),
                ),
            )

    @staticmethod
    def _source_priority(source_type: str | None) -> int:
        return {
            "official_gibtu": 10,
            "yokatlas": 20,
            "candidate": 30,
            "candidate_page_ogrenim": 30,
        }.get(str(source_type or ""), 100)


__all__ = ["ProgramCatalogRepository", "REQUIRED_PROGRAM_CATALOG_TABLES"]
