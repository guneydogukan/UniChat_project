"""Yıllık YÖK Atlas raporları için saf diff yardımcıları."""

from __future__ import annotations

from typing import Any

from yokatlas.contracts import (
    STATUS_IDENTITY_CHANGED,
    STATUS_NEW_PROGRAM,
    STATUS_PASSIVE_PROGRAM,
    STATUS_SOURCE_URL_CHANGED,
    STATUS_UNIT_CHANGED,
)


IDENTITY_FIELDS = {
    "program_name_raw": ("program", "program_name_raw", STATUS_IDENTITY_CHANGED),
    "program_name_clean": ("program", "program_name_clean", STATUS_IDENTITY_CHANGED),
    "program_language_from_name": ("program", "program_language_from_name", STATUS_IDENTITY_CHANGED),
    "program_variant": ("program", "program_variant", STATUS_IDENTITY_CHANGED),
    "academic_unit_name": ("academic_unit", "name", STATUS_UNIT_CHANGED),
    "level": ("program", "level", STATUS_IDENTITY_CHANGED),
    "duration_years": ("program", "duration_years", STATUS_IDENTITY_CHANGED),
}

YEARLY_FIELDS = {
    "score_type": ("education", "score_type", "score_type_changed"),
    "education_language": ("education", "language", "language_changed"),
    "education_mode": ("education", "education_mode", "education_type_changed"),
    "funding_type": ("education", "funding_type", "fee_status_changed"),
    "general_quota": ("quota_statistics", "general.quota", "quota_changed"),
    "general_placed": ("quota_statistics", "general.placed", "placed_changed"),
    "base_score": ("admission_statistics", "base_score", "admission_stats_updated"),
    "base_rank": ("admission_statistics", "base_rank", "admission_stats_updated"),
    "last_admitted_nets_status": ("last_admitted_nets", "status", "nets_updated"),
    "source_url": ("program_year", "source_url", STATUS_SOURCE_URL_CHANGED),
}

MANUAL_STATUSES = {
    STATUS_IDENTITY_CHANGED,
    STATUS_NEW_PROGRAM,
    STATUS_PASSIVE_PROGRAM,
    STATUS_UNIT_CHANGED,
    "language_changed",
    "education_type_changed",
    "fee_status_changed",
}


def program_code(program: dict[str, Any]) -> str:
    value = (program.get("program") or {}).get("program_code")
    return "" if value is None else str(value).strip()


def build_program_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        code: program
        for program in report.get("programs") or []
        if (code := program_code(program))
    }


def diff_reports(current_report: dict[str, Any], previous_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """ÖSYM kodu odaklı yıllık değişim raporu üretir."""
    current_index = build_program_index(current_report)
    if not current_report.get("success", False):
        return _skipped_diff(
            current_report,
            previous_report,
            "current_scrape_failed",
            "Güncel scrape başarısız olduğu için yıllık diff üretilmedi.",
        )

    if previous_report is None:
        return {
            "summary": {
                "compared": False,
                "skipped": False,
                "skip_reason": None,
                "skip_message": None,
                "current_run_id": current_report.get("run_id"),
                "previous_run_id": None,
                "current_data_year": current_report.get("data_year"),
                "previous_data_year": None,
                "new_program_count": 0,
                "passive_program_count": 0,
                "changed_program_count": 0,
                "manual_review_count": 0,
            },
            "changes": [],
            "new_programs": [],
            "passive_programs": [],
            "changed_programs": [],
            "manual_review_items": [],
        }

    previous_index = build_program_index(previous_report or {})
    if previous_index and not current_index and current_report.get("errors"):
        return _skipped_diff(
            current_report,
            previous_report,
            "current_programs_empty_after_error",
            "Güncel program listesi hata sonrası boş geldiği için pasif aday üretilmedi.",
        )

    current_codes = set(current_index)
    previous_codes = set(previous_index)

    changes: list[dict[str, Any]] = []
    manual_review_items: list[dict[str, Any]] = []

    for code in sorted(current_codes - previous_codes):
        program = current_index[code]
        change = _change_record(code, "program_status", None, "listed", STATUS_NEW_PROGRAM, program, True)
        changes.append(change)
        manual_review_items.append(_manual_item(change, "Güncel YÖK Atlas listesinde yeni program adayı."))

    for code in sorted(previous_codes - current_codes):
        program = previous_index[code]
        change = _change_record(code, "program_status", "listed", None, STATUS_PASSIVE_PROGRAM, program, True)
        changes.append(change)
        manual_review_items.append(_manual_item(change, "Önceki yılda vardı, güncel listede görünmüyor."))

    for code in sorted(current_codes & previous_codes):
        current_program = current_index[code]
        previous_program = previous_index[code]
        for field_name, path_spec in {**IDENTITY_FIELDS, **YEARLY_FIELDS}.items():
            section, dotted_key, status = path_spec
            old_value = _nested_value(previous_program.get(section) or {}, dotted_key)
            new_value = _nested_value(current_program.get(section) or {}, dotted_key)
            if old_value != new_value:
                manual = status in MANUAL_STATUSES
                change = _change_record(code, field_name, old_value, new_value, status, current_program, manual)
                changes.append(change)
                if manual:
                    manual_review_items.append(_manual_item(change, "Kimlik/varyasyon alanı değişti; otomatik merge yapılmamalı."))

        previous_conditions = _condition_codes(previous_program)
        current_conditions = _condition_codes(current_program)
        if previous_conditions != current_conditions:
            change = _change_record(code, "special_conditions", previous_conditions, current_conditions, "conditions_changed", current_program, True)
            changes.append(change)
            manual_review_items.append(_manual_item(change, "Özel koşul kodları/metinleri değişti."))

    return {
        "summary": {
            "compared": bool(previous_report),
            "skipped": False,
            "skip_reason": None,
            "skip_message": None,
            "current_run_id": current_report.get("run_id"),
            "previous_run_id": (previous_report or {}).get("run_id"),
            "current_data_year": current_report.get("data_year"),
            "previous_data_year": (previous_report or {}).get("data_year"),
            "new_program_count": len(current_codes - previous_codes),
            "passive_program_count": len(previous_codes - current_codes),
            "changed_program_count": len({change["program_code"] for change in changes if change["change_type"] not in {STATUS_NEW_PROGRAM, STATUS_PASSIVE_PROGRAM}}),
            "manual_review_count": len(manual_review_items),
        },
        "changes": changes,
        "new_programs": [current_index[code] for code in sorted(current_codes - previous_codes)],
        "passive_programs": [previous_index[code] for code in sorted(previous_codes - current_codes)],
        "changed_programs": sorted({change["program_code"] for change in changes}),
        "manual_review_items": manual_review_items,
    }


def _skipped_diff(
    current_report: dict[str, Any],
    previous_report: dict[str, Any] | None,
    reason: str,
    message: str,
) -> dict[str, Any]:
    return {
        "summary": {
            "compared": False,
            "skipped": True,
            "skip_reason": reason,
            "skip_message": message,
            "current_run_id": current_report.get("run_id"),
            "previous_run_id": (previous_report or {}).get("run_id"),
            "current_data_year": current_report.get("data_year"),
            "previous_data_year": (previous_report or {}).get("data_year"),
            "new_program_count": 0,
            "passive_program_count": 0,
            "changed_program_count": 0,
            "manual_review_count": 0,
        },
        "changes": [],
        "new_programs": [],
        "passive_programs": [],
        "changed_programs": [],
        "manual_review_items": [],
    }


def _nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _condition_codes(program: dict[str, Any]) -> list[str]:
    return sorted(str(condition.get("condition_code")) for condition in program.get("conditions") or [])


def _change_record(
    code: str,
    field_name: str,
    old_value: Any,
    new_value: Any,
    status: str,
    program: dict[str, Any],
    manual_review_required: bool,
) -> dict[str, Any]:
    source = program.get("program_year") or program.get("source") or {}
    return {
        "program_code": code,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "change_type": status,
        "status": status,
        "source_url": source.get("source_url"),
        "manual_review_required": manual_review_required,
        "confidence": 1.0,
    }


def _manual_item(change: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "program_code": change.get("program_code"),
        "reason": reason,
        "status": change.get("status"),
        "field_name": change.get("field_name"),
        "old_value": change.get("old_value"),
        "new_value": change.get("new_value"),
        "source_url": change.get("source_url"),
    }


__all__ = ["build_program_index", "diff_reports", "program_code"]
