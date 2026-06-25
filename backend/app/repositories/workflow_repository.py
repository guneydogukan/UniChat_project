"""MDBF workflow/form DB-first repository katmanı."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class WorkflowRepository:
    """Workflow ve form tablolarına erişen küçük repository."""

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

    def upsert_scrape_result(self, result: dict[str, Any]) -> dict[str, int]:
        forms = result.get("forms") or []
        workflows = result.get("workflows") or []
        scrape_run = result.get("scrape_run") or {}

        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                form_ids_by_name: dict[str, str] = {}
                for form in forms:
                    form_id = self._upsert_form(cur, form)
                    form_ids_by_name[str(form["form_name"])] = form_id

                workflow_count = 0
                mapping_count = 0
                for workflow in workflows:
                    workflow_id = self._upsert_workflow(cur, workflow)
                    workflow_count += 1
                    self._replace_workflow_steps(cur, workflow_id, workflow.get("steps") or [])
                    mapped_form_ids = [
                        form_ids_by_name[name]
                        for name in workflow.get("mapped_form_names", [])
                        if name in form_ids_by_name
                    ]
                    mapping_count += self._replace_workflow_mappings(cur, workflow_id, mapped_form_ids)

                self._upsert_scrape_run(cur, scrape_run)
            conn.commit()

        return {
            "forms": len(forms),
            "workflows": workflow_count,
            "mappings": mapping_count,
        }

    def _upsert_scrape_run(self, cur: RealDictCursor, run: dict[str, Any]) -> None:
        if not run:
            return
        cur.execute(
            """
            INSERT INTO workflow_scrape_runs (
                scrape_run_id, scraper_name, metadata_version, unit_code,
                source_workflows_url, source_forms_url,
                started_at, finished_at, status,
                workflow_count, form_count, mapping_count, validation_report
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scrape_run_id) DO UPDATE SET
                finished_at = EXCLUDED.finished_at,
                status = EXCLUDED.status,
                workflow_count = EXCLUDED.workflow_count,
                form_count = EXCLUDED.form_count,
                mapping_count = EXCLUDED.mapping_count,
                validation_report = EXCLUDED.validation_report,
                updated_at = NOW()
            """,
            (
                run.get("scrape_run_id"),
                run.get("scraper_name"),
                run.get("metadata_version"),
                run.get("unit_code"),
                run.get("source_workflows_url"),
                run.get("source_forms_url"),
                run.get("started_at"),
                run.get("finished_at"),
                run.get("status"),
                run.get("workflow_count", 0),
                run.get("form_count", 0),
                run.get("mapping_count", 0),
                Json(run.get("validation_report") or {}),
            ),
        )

    def _upsert_form(self, cur: RealDictCursor, form: dict[str, Any]) -> str:
        cur.execute(
            """
            INSERT INTO unit_forms (
                unit_code, unit_name, unit_type, process_key,
                form_name, normalized_form_name, download_url, file_extension,
                http_status, checksum, fetched_at, source_page_url,
                is_active, needs_review
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (unit_code, normalized_form_name) DO UPDATE SET
                process_key = EXCLUDED.process_key,
                form_name = EXCLUDED.form_name,
                download_url = EXCLUDED.download_url,
                file_extension = EXCLUDED.file_extension,
                http_status = EXCLUDED.http_status,
                checksum = EXCLUDED.checksum,
                fetched_at = EXCLUDED.fetched_at,
                source_page_url = EXCLUDED.source_page_url,
                is_active = EXCLUDED.is_active,
                needs_review = EXCLUDED.needs_review,
                updated_at = NOW()
            RETURNING id
            """,
            (
                form.get("unit_code"),
                form.get("unit_name"),
                form.get("unit_type"),
                form.get("process_key"),
                form.get("form_name"),
                form.get("normalized_form_name"),
                form.get("download_url"),
                form.get("file_extension"),
                form.get("http_status"),
                form.get("checksum"),
                form.get("fetched_at"),
                form.get("source_page_url"),
                form.get("is_active", True),
                form.get("needs_review", False),
            ),
        )
        return str(cur.fetchone()["id"])

    def _upsert_workflow(self, cur: RealDictCursor, workflow: dict[str, Any]) -> str:
        cur.execute(
            """
            INSERT INTO workflows (
                unit_code, unit_name, unit_type, process_key,
                title, normalized_title, source_page_url, pdf_url,
                pdf_checksum, pdf_size_bytes, pdf_http_status,
                workflow_summary, first_action_for_student, final_outcome,
                related_documents, decision_points, confidence_score,
                needs_review, extraction_method, raw_text, fetched_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (unit_code, process_key) DO UPDATE SET
                title = EXCLUDED.title,
                normalized_title = EXCLUDED.normalized_title,
                source_page_url = EXCLUDED.source_page_url,
                pdf_url = EXCLUDED.pdf_url,
                pdf_checksum = EXCLUDED.pdf_checksum,
                pdf_size_bytes = EXCLUDED.pdf_size_bytes,
                pdf_http_status = EXCLUDED.pdf_http_status,
                workflow_summary = EXCLUDED.workflow_summary,
                first_action_for_student = EXCLUDED.first_action_for_student,
                final_outcome = EXCLUDED.final_outcome,
                related_documents = EXCLUDED.related_documents,
                decision_points = EXCLUDED.decision_points,
                confidence_score = EXCLUDED.confidence_score,
                needs_review = EXCLUDED.needs_review,
                extraction_method = EXCLUDED.extraction_method,
                raw_text = EXCLUDED.raw_text,
                fetched_at = EXCLUDED.fetched_at,
                updated_at = NOW()
            RETURNING id
            """,
            (
                workflow.get("unit_code"),
                workflow.get("unit_name"),
                workflow.get("unit_type"),
                workflow.get("process_key"),
                workflow.get("title"),
                workflow.get("normalized_title"),
                workflow.get("source_page_url"),
                workflow.get("pdf_url"),
                workflow.get("pdf_checksum"),
                workflow.get("pdf_size_bytes"),
                workflow.get("pdf_http_status"),
                workflow.get("workflow_summary"),
                workflow.get("first_action_for_student"),
                workflow.get("final_outcome"),
                Json(workflow.get("related_documents") or []),
                Json(workflow.get("decision_points") or []),
                workflow.get("confidence_score"),
                workflow.get("needs_review", False),
                workflow.get("extraction_method"),
                workflow.get("raw_text"),
                workflow.get("fetched_at"),
            ),
        )
        return str(cur.fetchone()["id"])

    @staticmethod
    def _replace_workflow_steps(cur: RealDictCursor, workflow_id: str, steps: list[dict[str, Any]]) -> None:
        cur.execute("DELETE FROM workflow_steps WHERE workflow_id = %s", (workflow_id,))
        for index, step in enumerate(steps, start=1):
            cur.execute(
                """
                INSERT INTO workflow_steps (
                    workflow_id, step_order, actor, action_text,
                    next_step_order, needs_review
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    workflow_id,
                    step.get("step_order") or index,
                    step.get("actor"),
                    step.get("action_text"),
                    step.get("next_step_order"),
                    step.get("needs_review", False),
                ),
            )

    @staticmethod
    def _replace_workflow_mappings(cur: RealDictCursor, workflow_id: str, form_ids: list[str]) -> int:
        cur.execute("DELETE FROM workflow_forms_mapping WHERE workflow_id = %s", (workflow_id,))
        for form_id in form_ids:
            cur.execute(
                """
                INSERT INTO workflow_forms_mapping (
                    workflow_id, form_id, match_method, confidence_score, needs_review
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (workflow_id, form_id) DO UPDATE SET
                    confidence_score = EXCLUDED.confidence_score,
                    needs_review = EXCLUDED.needs_review
                """,
                (workflow_id, form_id, "rule", 1.0, False),
            )
        return len(form_ids)

    def get_workflow_by_process(self, process_key: str, unit_code: str = "MDBF") -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM workflows
                    WHERE unit_code = %s AND process_key = %s
                    """,
                    (unit_code, process_key),
                )
                workflow = cur.fetchone()
                if not workflow:
                    return None
                result = dict(workflow)
                result["related_documents"] = _decode_json(result.get("related_documents")) or []
                result["decision_points"] = _decode_json(result.get("decision_points")) or []
                result["steps"] = self._fetch_steps(cur, str(result["id"]))
                result["forms"] = self._fetch_forms_for_workflow(cur, str(result["id"]))
                return result

    def list_forms(self, unit_code: str = "MDBF") -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM unit_forms
                    WHERE unit_code = %s AND is_active = TRUE
                    ORDER BY form_name
                    """,
                    (unit_code,),
                )
                return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _fetch_steps(cur: RealDictCursor, workflow_id: str) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT step_order, actor, action_text, next_step_order, needs_review
            FROM workflow_steps
            WHERE workflow_id = %s
            ORDER BY step_order
            """,
            (workflow_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def _fetch_forms_for_workflow(cur: RealDictCursor, workflow_id: str) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT f.*
            FROM unit_forms f
            JOIN workflow_forms_mapping m ON m.form_id = f.id
            WHERE m.workflow_id = %s AND f.is_active = TRUE
            ORDER BY f.form_name
            """,
            (workflow_id,),
        )
        return [dict(row) for row in cur.fetchall()]

