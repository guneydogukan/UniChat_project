"""
YÖK Atlas DB-first sorgu repository katmanı.

Bu repository scraper çalıştırmaz, migration uygulamaz ve veri yazmaz. Chatbot
yanıtları için yalnız mevcut `yokatlas_*` tablolarından read-only SELECT yapar.
"""

from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import get_settings


def _row_to_program(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if result.get("program_year_id") is not None:
        result["program_year_id"] = str(result["program_year_id"])
    if result.get("program_id") is not None:
        result["program_id"] = str(result["program_id"])
    if result.get("program_code") is not None:
        result["program_code"] = str(result["program_code"])
    return result


class YokatlasQueryRepository:
    """YÖK Atlas tercih/yerleşme tabloları için read-only repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect_readonly(self):
        conn = psycopg2.connect(self._database_url)
        conn.set_session(readonly=True, autocommit=True)
        return conn

    def list_latest_programs(self) -> list[dict[str, Any]]:
        """En güncel veri yılındaki program kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    WITH latest AS (
                        SELECT max(data_year) AS data_year
                        FROM yokatlas_program_years
                    ),
                    condition_counts AS (
                        SELECT program_year_id, COUNT(*)::int AS condition_count
                        FROM yokatlas_program_conditions
                        GROUP BY program_year_id
                    )
                    SELECT
                        p.id AS program_id,
                        py.id AS program_year_id,
                        p.program_code::text AS program_code,
                        p.program_name_raw,
                        p.program_name_clean,
                        p.program_variant,
                        p.program_level,
                        p.duration_years,
                        p.academic_unit_name,
                        p.university_name,
                        p.city,
                        p.source_url AS program_source_url,
                        py.data_year,
                        py.score_type,
                        py.education_mode,
                        py.language,
                        py.funding_type,
                        py.source_url AS program_year_source_url,
                        q.general_quota,
                        q.general_placed,
                        q.school_first_quota,
                        q.school_first_placed,
                        q.earthquake_quota,
                        q.earthquake_placed,
                        q.women_34_plus_quota,
                        q.women_34_plus_placed,
                        q.martyr_veteran_quota,
                        q.martyr_veteran_placed,
                        q.total_quota_known,
                        q.total_placed_known,
                        s.base_score,
                        s.base_rank,
                        s.min_rank_condition,
                        s.fill_status,
                        COALESCE(cc.condition_count, 0)::int AS condition_count
                    FROM yokatlas_program_years py
                    JOIN latest ON latest.data_year = py.data_year
                    JOIN yokatlas_programs p ON p.id = py.program_id
                    LEFT JOIN yokatlas_quota_statistics q ON q.program_year_id = py.id
                    LEFT JOIN yokatlas_score_statistics s ON s.program_year_id = py.id
                    LEFT JOIN condition_counts cc ON cc.program_year_id = py.id
                    ORDER BY p.program_level, p.academic_unit_name, p.program_name_raw, p.program_code
                    """
                )
                return [
                    program
                    for row in cur.fetchall()
                    if (program := _row_to_program(row)) is not None
                ]

    def get_latest_program_by_code(self, program_code: str | int) -> dict[str, Any] | None:
        """ÖSYM program koduyla en güncel program kaydını döndürür."""
        code = int(str(program_code))
        programs = self.list_latest_programs()
        return next((program for program in programs if int(program["program_code"]) == code), None)

    def get_conditions_for_program_year(self, program_year_id: str) -> list[dict[str, Any]]:
        """Program-yıl için özel koşul kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        condition_code,
                        condition_text,
                        source_url,
                        data_year
                    FROM yokatlas_program_conditions
                    WHERE program_year_id = %s
                    ORDER BY condition_code NULLS LAST, condition_text
                    """,
                    (program_year_id,),
                )
                return [dict(row) for row in cur.fetchall()]
