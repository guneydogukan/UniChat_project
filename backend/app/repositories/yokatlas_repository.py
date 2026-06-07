"""
YÖK Atlas yapılandırılmış veri repository katmanı.

Bu sınıf scraper çalıştırmaz; yalnızca hazır YÖK Atlas raporunu PostgreSQL'e
transaction içinde, idempotent biçimde yazar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _as_decimal(value: Any) -> Any:
    return value if value not in {"", None} else None


class YokatlasRepository:
    """YÖK Atlas tablolarına erişen PostgreSQL repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def ensure_schema(self) -> None:
        """Mevcut proje standardındaki init.sql içinden tablo şemasını uygular."""
        schema_path = Path(__file__).resolve().parents[3] / "database" / "init.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    def import_report(
        self,
        report: dict[str, Any],
        allow_program_write: bool,
        validation_status: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Hazır scrape raporunu transaction içinde DB'ye yazar."""
        counts = {
            "runs_upserted": 0,
            "snapshots_inserted": 0,
            "snapshots_updated": 0,
            "programs_inserted": 0,
            "programs_updated": 0,
            "program_years_inserted": 0,
            "program_years_updated": 0,
            "quota_statistics_upserted": 0,
            "score_statistics_upserted": 0,
            "conditions_inserted": 0,
            "validation_results_inserted": 0,
            "skipped_programs": 0,
        }

        with self._connect() as conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    self._upsert_run(cur, report, validation_status, config or {})
                    counts["runs_upserted"] = 1
                    snapshot_counts = self._upsert_snapshots(cur, report, validation_status)
                    counts["snapshots_inserted"] = snapshot_counts["inserted"]
                    counts["snapshots_updated"] = snapshot_counts["updated"]

                    program_year_ids: dict[tuple[int, int], str] = {}
                    if allow_program_write:
                        for program in report.get("programs") or []:
                            upsert_counts, program_year_id = self._upsert_program_bundle(
                                cur,
                                report,
                                program,
                                validation_status,
                            )
                            for key, value in upsert_counts.items():
                                counts[key] += value
                            program_code = program.get("program", {}).get("program_code")
                            data_year = program.get("program_year", {}).get("data_year")
                            if program_code is not None and data_year is not None:
                                program_year_ids[(int(program_code), int(data_year))] = program_year_id
                    else:
                        counts["skipped_programs"] = len(report.get("programs") or [])

                    self._replace_validation_results(cur, report, program_year_ids, validation_status)
                    counts["validation_results_inserted"] = len(report.get("validation_results") or [])

                conn.commit()
                return counts
            except Exception:
                conn.rollback()
                raise

    def fetch_counts(self, scrape_run_id: str) -> dict[str, int]:
        """Belirli run için DB kayıt sayılarını döndürür."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                result: dict[str, int] = {}
                for table, column in (
                    ("yokatlas_scrape_runs", "scrape_run_id"),
                    ("yokatlas_raw_snapshots", "scrape_run_id"),
                    ("yokatlas_programs", "scrape_run_id"),
                    ("yokatlas_program_years", "scrape_run_id"),
                    ("yokatlas_quota_statistics", "scrape_run_id"),
                    ("yokatlas_score_statistics", "scrape_run_id"),
                    ("yokatlas_program_conditions", "scrape_run_id"),
                    ("yokatlas_validation_results", "scrape_run_id"),
                ):
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = %s", (scrape_run_id,))
                    result[table] = int(cur.fetchone()[0])
                return result

    def _upsert_run(
        self,
        cur: Any,
        report: dict[str, Any],
        validation_status: str,
        config: dict[str, Any],
    ) -> None:
        severity_counts = _severity_counts(report)
        cur.execute(
            """
            INSERT INTO yokatlas_scrape_runs (
                scrape_run_id, scraper_name, metadata_version, university_id, university_name,
                data_year, started_at, finished_at, status, validation_status,
                expected_program_count, matched_program_count, normalized_program_count,
                snapshot_count, critical_count, warning_count, rate_limit_seconds,
                config, summary
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, %s::jsonb
            )
            ON CONFLICT (scrape_run_id) DO UPDATE SET
                status = EXCLUDED.status,
                validation_status = EXCLUDED.validation_status,
                matched_program_count = EXCLUDED.matched_program_count,
                normalized_program_count = EXCLUDED.normalized_program_count,
                snapshot_count = EXCLUDED.snapshot_count,
                critical_count = EXCLUDED.critical_count,
                warning_count = EXCLUDED.warning_count,
                config = EXCLUDED.config,
                summary = EXCLUDED.summary,
                updated_at = NOW()
            """,
            (
                report.get("run_id"),
                report.get("scraper_name"),
                report.get("metadata_version"),
                report.get("university_id"),
                report.get("university_name"),
                report.get("data_year"),
                report.get("started_at"),
                report.get("finished_at"),
                "success" if report.get("success") else "failed",
                validation_status,
                report.get("expected_program_count") or 0,
                report.get("matched_program_count") or 0,
                report.get("normalized_program_count") or 0,
                report.get("snapshot_count") or 0,
                severity_counts["critical"],
                severity_counts["warning"],
                report.get("rate_limit_seconds"),
                Json(config, dumps=_json_dumps),
                Json(_summary_payload(report), dumps=_json_dumps),
            ),
        )

    def _upsert_snapshots(self, cur: Any, report: dict[str, Any], validation_status: str) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0}
        for snapshot in report.get("snapshots") or []:
            cur.execute(
                """
                INSERT INTO yokatlas_raw_snapshots (
                    snapshot_id, scrape_run_id, snapshot_type, source_url, method,
                    request_body, response_payload, response_hash, fetched_at, file_path,
                    data_year, validation_status
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    scrape_run_id = EXCLUDED.scrape_run_id,
                    snapshot_type = EXCLUDED.snapshot_type,
                    source_url = EXCLUDED.source_url,
                    method = EXCLUDED.method,
                    request_body = EXCLUDED.request_body,
                    response_payload = EXCLUDED.response_payload,
                    response_hash = EXCLUDED.response_hash,
                    fetched_at = EXCLUDED.fetched_at,
                    file_path = EXCLUDED.file_path,
                    data_year = EXCLUDED.data_year,
                    validation_status = EXCLUDED.validation_status,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    snapshot.get("snapshot_id"),
                    report.get("run_id"),
                    snapshot.get("snapshot_type"),
                    snapshot.get("source_url"),
                    snapshot.get("method"),
                    Json(snapshot.get("request_body"), dumps=_json_dumps),
                    Json(snapshot.get("response_payload"), dumps=_json_dumps),
                    snapshot.get("response_hash"),
                    snapshot.get("fetched_at"),
                    snapshot.get("path"),
                    report.get("data_year"),
                    validation_status,
                ),
            )
            if bool(cur.fetchone()["inserted"]):
                counts["inserted"] += 1
            else:
                counts["updated"] += 1
        return counts

    def _upsert_program_bundle(
        self,
        cur: Any,
        report: dict[str, Any],
        program: dict[str, Any],
        validation_status: str,
    ) -> tuple[dict[str, int], str]:
        counts = {
            "programs_inserted": 0,
            "programs_updated": 0,
            "program_years_inserted": 0,
            "program_years_updated": 0,
            "quota_statistics_upserted": 0,
            "score_statistics_upserted": 0,
            "conditions_inserted": 0,
        }
        snapshot = _program_snapshot(report, program)
        program_info = program["program"]
        university = program["university"]
        academic_unit = program["academic_unit"]
        year = program["program_year"]
        education = program["education"]
        source_url = year.get("source_url")
        metadata = _record_metadata(report, snapshot, year, validation_status)

        cur.execute(
            """
            INSERT INTO yokatlas_programs (
                program_code, source_program_id, university_id, university_name, university_type,
                city, academic_unit_id, academic_unit_name, program_name_raw, program_name_clean,
                program_language_from_name, program_variant, program_level, source_level_id,
                source_level_name, duration_years, is_active, old_program_code, old_program_id,
                source_url, snapshot_id, response_hash, fetched_at, data_year, scrape_run_id,
                validation_status
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s
            )
            ON CONFLICT (program_code) DO UPDATE SET
                source_program_id = EXCLUDED.source_program_id,
                university_id = EXCLUDED.university_id,
                university_name = EXCLUDED.university_name,
                university_type = EXCLUDED.university_type,
                city = EXCLUDED.city,
                academic_unit_id = EXCLUDED.academic_unit_id,
                academic_unit_name = EXCLUDED.academic_unit_name,
                program_name_raw = EXCLUDED.program_name_raw,
                program_name_clean = EXCLUDED.program_name_clean,
                program_language_from_name = EXCLUDED.program_language_from_name,
                program_variant = EXCLUDED.program_variant,
                program_level = EXCLUDED.program_level,
                source_level_id = EXCLUDED.source_level_id,
                source_level_name = EXCLUDED.source_level_name,
                duration_years = EXCLUDED.duration_years,
                is_active = EXCLUDED.is_active,
                old_program_code = EXCLUDED.old_program_code,
                old_program_id = EXCLUDED.old_program_id,
                source_url = EXCLUDED.source_url,
                snapshot_id = EXCLUDED.snapshot_id,
                response_hash = EXCLUDED.response_hash,
                fetched_at = EXCLUDED.fetched_at,
                data_year = EXCLUDED.data_year,
                scrape_run_id = EXCLUDED.scrape_run_id,
                validation_status = EXCLUDED.validation_status,
                updated_at = NOW()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                program_info.get("program_code"),
                program_info.get("source_program_id"),
                university.get("source_university_id"),
                university.get("name"),
                university.get("type"),
                university.get("city"),
                academic_unit.get("source_unit_id"),
                academic_unit.get("name"),
                program_info.get("program_name_raw"),
                program_info.get("program_name_clean"),
                program_info.get("program_language_from_name"),
                program_info.get("program_variant"),
                program_info.get("level"),
                program_info.get("source_level_id"),
                program_info.get("source_level_name"),
                program_info.get("duration_years"),
                program_info.get("is_active"),
                program_info.get("old_program_code"),
                program_info.get("old_program_id"),
                source_url,
                metadata["snapshot_id"],
                metadata["response_hash"],
                metadata["fetched_at"],
                metadata["data_year"],
                metadata["scrape_run_id"],
                validation_status,
            ),
        )
        row = cur.fetchone()
        program_id = row["id"]
        counts["programs_inserted" if bool(row["inserted"]) else "programs_updated"] += 1

        cur.execute(
            """
            INSERT INTO yokatlas_program_years (
                program_id, program_code, data_year, exam, term, table_type, score_type,
                education_mode, education_mode_id, language, language_id, funding_type,
                funding_id, tuition_fee, source_url, catalog_snapshot_id, detail_snapshot_id,
                snapshot_id, response_hash, fetched_at, scrape_run_id, validation_status
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (program_code, data_year) DO UPDATE SET
                program_id = EXCLUDED.program_id,
                exam = EXCLUDED.exam,
                term = EXCLUDED.term,
                table_type = EXCLUDED.table_type,
                score_type = EXCLUDED.score_type,
                education_mode = EXCLUDED.education_mode,
                education_mode_id = EXCLUDED.education_mode_id,
                language = EXCLUDED.language,
                language_id = EXCLUDED.language_id,
                funding_type = EXCLUDED.funding_type,
                funding_id = EXCLUDED.funding_id,
                tuition_fee = EXCLUDED.tuition_fee,
                source_url = EXCLUDED.source_url,
                catalog_snapshot_id = EXCLUDED.catalog_snapshot_id,
                detail_snapshot_id = EXCLUDED.detail_snapshot_id,
                snapshot_id = EXCLUDED.snapshot_id,
                response_hash = EXCLUDED.response_hash,
                fetched_at = EXCLUDED.fetched_at,
                scrape_run_id = EXCLUDED.scrape_run_id,
                validation_status = EXCLUDED.validation_status,
                updated_at = NOW()
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                program_id,
                program_info.get("program_code"),
                year.get("data_year"),
                year.get("exam"),
                year.get("term"),
                year.get("table_type"),
                education.get("score_type"),
                education.get("education_mode"),
                education.get("education_mode_id"),
                education.get("language"),
                education.get("language_id"),
                education.get("funding_type"),
                education.get("funding_id"),
                _as_decimal(education.get("tuition_fee")),
                source_url,
                year.get("catalog_snapshot_id"),
                year.get("detail_snapshot_id"),
                metadata["snapshot_id"],
                metadata["response_hash"],
                metadata["fetched_at"],
                metadata["scrape_run_id"],
                validation_status,
            ),
        )
        row = cur.fetchone()
        program_year_id = row["id"]
        counts["program_years_inserted" if bool(row["inserted"]) else "program_years_updated"] += 1

        self._upsert_quota(cur, program_year_id, program, metadata)
        counts["quota_statistics_upserted"] += 1
        self._upsert_scores(cur, program_year_id, program, metadata)
        counts["score_statistics_upserted"] += 1
        counts["conditions_inserted"] += self._replace_conditions(cur, program_year_id, program, metadata)
        return counts, str(program_year_id)

    def _upsert_quota(self, cur: Any, program_year_id: str, program: dict[str, Any], metadata: dict[str, Any]) -> None:
        quota = program["quota_statistics"]
        cur.execute(
            """
            INSERT INTO yokatlas_quota_statistics (
                program_year_id, general_quota, general_placed, school_first_quota,
                school_first_placed, earthquake_quota, earthquake_placed,
                women_34_plus_quota, women_34_plus_placed, martyr_veteran_quota,
                martyr_veteran_placed, total_quota_known, total_placed_known,
                source_url, snapshot_id, response_hash, fetched_at, data_year,
                scrape_run_id, validation_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (program_year_id) DO UPDATE SET
                general_quota = EXCLUDED.general_quota,
                general_placed = EXCLUDED.general_placed,
                school_first_quota = EXCLUDED.school_first_quota,
                school_first_placed = EXCLUDED.school_first_placed,
                earthquake_quota = EXCLUDED.earthquake_quota,
                earthquake_placed = EXCLUDED.earthquake_placed,
                women_34_plus_quota = EXCLUDED.women_34_plus_quota,
                women_34_plus_placed = EXCLUDED.women_34_plus_placed,
                martyr_veteran_quota = EXCLUDED.martyr_veteran_quota,
                martyr_veteran_placed = EXCLUDED.martyr_veteran_placed,
                total_quota_known = EXCLUDED.total_quota_known,
                total_placed_known = EXCLUDED.total_placed_known,
                source_url = EXCLUDED.source_url,
                snapshot_id = EXCLUDED.snapshot_id,
                response_hash = EXCLUDED.response_hash,
                fetched_at = EXCLUDED.fetched_at,
                data_year = EXCLUDED.data_year,
                scrape_run_id = EXCLUDED.scrape_run_id,
                validation_status = EXCLUDED.validation_status,
                updated_at = NOW()
            """,
            (
                program_year_id,
                quota.get("general", {}).get("quota"),
                quota.get("general", {}).get("placed"),
                quota.get("school_first", {}).get("quota"),
                quota.get("school_first", {}).get("placed"),
                quota.get("earthquake", {}).get("quota"),
                quota.get("earthquake", {}).get("placed"),
                quota.get("women_34_plus", {}).get("quota"),
                quota.get("women_34_plus", {}).get("placed"),
                quota.get("martyr_veteran", {}).get("quota"),
                quota.get("martyr_veteran", {}).get("placed"),
                quota.get("total_quota_known"),
                quota.get("total_placed_known"),
                metadata["source_url"],
                metadata["snapshot_id"],
                metadata["response_hash"],
                metadata["fetched_at"],
                metadata["data_year"],
                metadata["scrape_run_id"],
                metadata["validation_status"],
            ),
        )

    def _upsert_scores(self, cur: Any, program_year_id: str, program: dict[str, Any], metadata: dict[str, Any]) -> None:
        admission = program["admission_statistics"]
        scores = program["score_statistics"]
        last_nets = program["last_admitted_nets"]
        average_nets = program["average_nets"]
        cur.execute(
            """
            INSERT INTO yokatlas_score_statistics (
                program_year_id, base_score, base_rank, last_admitted_score,
                last_admitted_rank, min_rank_condition, min_rank_condition_text,
                fill_status, historical, last_admitted_nets_status,
                last_admitted_nets, average_nets_status, average_nets, null_reason,
                source_url, snapshot_id, response_hash, fetched_at, data_year,
                scrape_run_id, validation_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (program_year_id) DO UPDATE SET
                base_score = EXCLUDED.base_score,
                base_rank = EXCLUDED.base_rank,
                last_admitted_score = EXCLUDED.last_admitted_score,
                last_admitted_rank = EXCLUDED.last_admitted_rank,
                min_rank_condition = EXCLUDED.min_rank_condition,
                min_rank_condition_text = EXCLUDED.min_rank_condition_text,
                fill_status = EXCLUDED.fill_status,
                historical = EXCLUDED.historical,
                last_admitted_nets_status = EXCLUDED.last_admitted_nets_status,
                last_admitted_nets = EXCLUDED.last_admitted_nets,
                average_nets_status = EXCLUDED.average_nets_status,
                average_nets = EXCLUDED.average_nets,
                null_reason = EXCLUDED.null_reason,
                source_url = EXCLUDED.source_url,
                snapshot_id = EXCLUDED.snapshot_id,
                response_hash = EXCLUDED.response_hash,
                fetched_at = EXCLUDED.fetched_at,
                data_year = EXCLUDED.data_year,
                scrape_run_id = EXCLUDED.scrape_run_id,
                validation_status = EXCLUDED.validation_status,
                updated_at = NOW()
            """,
            (
                program_year_id,
                _as_decimal(admission.get("base_score")),
                admission.get("base_rank"),
                _as_decimal(admission.get("last_admitted_score")),
                admission.get("last_admitted_rank"),
                admission.get("min_rank_condition"),
                admission.get("min_rank_condition_text"),
                admission.get("fill_status"),
                Json(scores.get("historical") or [], dumps=_json_dumps),
                last_nets.get("status"),
                Json(last_nets, dumps=_json_dumps),
                average_nets.get("status"),
                Json(average_nets, dumps=_json_dumps),
                last_nets.get("null_reason") or average_nets.get("null_reason"),
                metadata["source_url"],
                metadata["snapshot_id"],
                metadata["response_hash"],
                metadata["fetched_at"],
                metadata["data_year"],
                metadata["scrape_run_id"],
                metadata["validation_status"],
            ),
        )

    def _replace_conditions(self, cur: Any, program_year_id: str, program: dict[str, Any], metadata: dict[str, Any]) -> int:
        cur.execute("DELETE FROM yokatlas_program_conditions WHERE program_year_id = %s", (program_year_id,))
        inserted = 0
        for condition in program.get("conditions") or []:
            cur.execute(
                """
                INSERT INTO yokatlas_program_conditions (
                    program_year_id, condition_code, condition_text, source_url,
                    snapshot_id, response_hash, fetched_at, data_year, scrape_run_id,
                    validation_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    program_year_id,
                    condition.get("condition_code"),
                    condition.get("condition_text"),
                    metadata["source_url"],
                    metadata["snapshot_id"],
                    metadata["response_hash"],
                    metadata["fetched_at"],
                    metadata["data_year"],
                    metadata["scrape_run_id"],
                    metadata["validation_status"],
                ),
            )
            inserted += 1
        return inserted

    def _replace_validation_results(
        self,
        cur: Any,
        report: dict[str, Any],
        program_year_ids: dict[tuple[int, int], str],
        validation_status: str,
    ) -> None:
        cur.execute("DELETE FROM yokatlas_validation_results WHERE scrape_run_id = %s", (report.get("run_id"),))
        for issue in report.get("validation_results") or []:
            program_code = issue.get("program_code")
            program_year_id = None
            if program_code is not None and report.get("data_year") is not None:
                program_year_id = program_year_ids.get((int(program_code), int(report["data_year"])))
            cur.execute(
                """
                INSERT INTO yokatlas_validation_results (
                    scrape_run_id, program_year_id, severity, code, message,
                    program_key, program_code, source_url, snapshot_id, response_hash,
                    fetched_at, data_year, validation_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    report.get("run_id"),
                    program_year_id,
                    issue.get("severity"),
                    issue.get("code"),
                    issue.get("message"),
                    issue.get("program_key"),
                    issue.get("program_code"),
                    None,
                    None,
                    None,
                    report.get("finished_at"),
                    report.get("data_year"),
                    validation_status,
                ),
            )


def _severity_counts(report: dict[str, Any]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in report.get("validation_results") or []:
        severity = str(issue.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _summary_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_program_count": report.get("expected_program_count"),
        "matched_program_count": report.get("matched_program_count"),
        "normalized_program_count": report.get("normalized_program_count"),
        "snapshot_count": report.get("snapshot_count"),
        "missing_programs": report.get("missing_programs") or [],
        "unexpected_programs": report.get("unexpected_programs") or [],
    }


def _snapshot_lookup(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(snapshot.get("snapshot_id")): snapshot
        for snapshot in report.get("snapshots") or []
        if snapshot.get("snapshot_id")
    }


def _program_snapshot(report: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
    lookup = _snapshot_lookup(report)
    year = program.get("program_year", {})
    snapshot_id = year.get("detail_snapshot_id") or year.get("catalog_snapshot_id")
    return lookup.get(str(snapshot_id), {})


def _record_metadata(
    report: dict[str, Any],
    snapshot: dict[str, Any],
    year: dict[str, Any],
    validation_status: str,
) -> dict[str, Any]:
    snapshot_id = snapshot.get("snapshot_id") or year.get("detail_snapshot_id") or year.get("catalog_snapshot_id")
    return {
        "source_url": year.get("source_url"),
        "snapshot_id": snapshot_id,
        "response_hash": snapshot.get("response_hash"),
        "fetched_at": snapshot.get("fetched_at") or report.get("finished_at"),
        "data_year": year.get("data_year") or report.get("data_year"),
        "scrape_run_id": report.get("run_id"),
        "validation_status": validation_status,
    }


__all__ = ["YokatlasRepository"]
