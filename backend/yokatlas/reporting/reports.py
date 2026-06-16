"""YÖK Atlas rapor paketi üreticileri."""

from __future__ import annotations

from typing import Any

from yokatlas.contracts import SOURCE_SYSTEM, STATUS_IMPORT_BLOCKED, STATUS_IMPORT_READY, UNIVERSITY_NAME
from yokatlas.validation.quality_rules import validate_program_payloads
from yokatlas.versioning.diff import diff_reports

OUT_OF_SCOPE_CODES = {"nets_not_available", "panel_not_discovered"}


def severity_counts(report: dict[str, Any], extra_issues: list[dict[str, Any]] | None = None) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in [*(report.get("validation_results") or []), *(extra_issues or [])]:
        severity = str(issue.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def build_validation_report(report: dict[str, Any]) -> dict[str, Any]:
    extra_issues = _filtered_quality_issues(report)
    raw_results = [*(report.get("validation_results") or []), *extra_issues]
    core_results = [_core_validation_item(report, issue) for issue in raw_results]
    counts = _counts_for_items(core_results)
    return {
        "run_id": report.get("run_id"),
        "crawl_run_id": report.get("run_id"),
        "source_system": SOURCE_SYSTEM,
        "university": UNIVERSITY_NAME,
        "data_year": report.get("data_year"),
        "summary": counts,
        "raw_summary": severity_counts(report, extra_issues),
        "results": report.get("validation_results") or [],
        "quality_rule_results": extra_issues,
        "core_results": core_results,
    }


def build_crawl_run_manifest(report: dict[str, Any]) -> dict[str, Any]:
    snapshots = [
        {key: value for key, value in snapshot.items() if key != "response_payload"}
        for snapshot in report.get("snapshots") or []
    ]
    return {
        "crawl_run_id": report.get("run_id"),
        "run_id": report.get("run_id"),
        "source_system": SOURCE_SYSTEM,
        "university": UNIVERSITY_NAME,
        "data_year": report.get("data_year"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "dry_run": report.get("dry_run"),
        "snapshot_count": report.get("snapshot_count"),
        "snapshots": snapshots,
        "identity": {
            "public_university_code": "1112",
            "api_university_id": report.get("university_id"),
            "university_name": report.get("university_name"),
        },
    }


def build_manual_review_items(report: dict[str, Any], diff_report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    program_urls = _program_source_urls(report)
    for issue in [*(report.get("validation_results") or []), *_filtered_quality_issues(report)]:
        core_item = _core_validation_item(report, issue)
        if not core_item.get("manual_review_required"):
            continue
        program_code = issue.get("program_code")
        items.append({
            "crawl_run_id": report.get("run_id"),
            "data_year": report.get("data_year"),
            "program_code": None if program_code is None else str(program_code),
            "severity": core_item.get("severity"),
            "status": core_item.get("status"),
            "reason": core_item.get("message"),
            "rule_code": core_item.get("rule_code"),
            "source_url": program_urls.get(str(program_code)),
            "manual_review_required": True,
        })

    if diff_report:
        for item in diff_report.get("manual_review_items") or []:
            enriched = dict(item)
            enriched.setdefault("crawl_run_id", report.get("run_id"))
            enriched.setdefault("data_year", report.get("data_year"))
            enriched.setdefault("manual_review_required", True)
            items.append(enriched)

    return _deduplicate_manual_items(items)


def build_import_ready_report(
    report: dict[str, Any],
    db_report: dict[str, Any] | None = None,
    manual_review_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation_report = build_validation_report(report)
    counts = validation_report["summary"]
    db_errors = (db_report or {}).get("errors") or []
    write_db_requested = bool((db_report or {}).get("write_db_requested"))
    program_write_allowed = bool((db_report or {}).get("program_write_allowed"))
    scrape_errors = report.get("errors") or []
    scrape_success = bool(report.get("success"))
    critical_count = counts.get("critical", 0)
    data_quality_ready = scrape_success and critical_count == 0 and not db_errors
    ready = data_quality_ready and write_db_requested and program_write_allowed
    status = STATUS_IMPORT_READY if ready else STATUS_IMPORT_BLOCKED
    core_import_decision = _core_import_decision(data_quality_ready, counts)
    manual_review_decision = "manual_review_required" if manual_review_items else "manual_review_passed"
    return {
        "crawl_run_id": report.get("run_id"),
        "source_system": SOURCE_SYSTEM,
        "university": UNIVERSITY_NAME,
        "data_year": report.get("data_year"),
        "status": status,
        "ready_for_db_write": ready,
        "data_quality_ready": data_quality_ready,
        "core_import_decision": core_import_decision,
        "manual_review_decision": manual_review_decision,
        "production_write_requires_user_approval": True,
        "critical_count": critical_count,
        "warning_count": counts.get("warning", 0),
        "info_count": counts.get("info", 0),
        "manual_review_required": bool(manual_review_items),
        "manual_review_count": len(manual_review_items or []),
        "db_report": db_report or {},
        "blocking_reasons": _blocking_reasons(
            critical_count,
            db_errors,
            scrape_success,
            scrape_errors,
            write_db_requested,
            program_write_allowed,
        ),
    }


def build_report_bundle(
    report: dict[str, Any],
    db_report: dict[str, Any] | None = None,
    previous_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diff_report = diff_reports(report, previous_report)
    manual_review_items = build_manual_review_items(report, diff_report)
    return {
        "crawl_run_manifest": build_crawl_run_manifest(report),
        "validation_report": build_validation_report(report),
        "diff_report": diff_report,
        "manual_review_items": manual_review_items,
        "import_ready_report": build_import_ready_report(report, db_report, manual_review_items),
    }


def _program_source_urls(report: dict[str, Any]) -> dict[str, str | None]:
    urls: dict[str, str | None] = {}
    for program in report.get("programs") or []:
        program_info = program.get("program") or {}
        code = program_info.get("program_code")
        if code is None:
            continue
        year = program.get("program_year") or {}
        source = program.get("source") or {}
        urls[str(code)] = year.get("source_url") or source.get("source_url")
    return urls


def _core_validation_item(report: dict[str, Any], issue: dict[str, Any]) -> dict[str, Any]:
    rule_code = str(issue.get("rule_code") or issue.get("code") or "")
    program_code = None if issue.get("program_code") is None else str(issue.get("program_code"))
    if rule_code in OUT_OF_SCOPE_CODES:
        return {
            "severity": "info",
            "rule_code": rule_code,
            "original_rule_code": rule_code,
            "status": "out_of_scope",
            "message": "Son yerleşen netleri core YÖK Atlas import kapsamı dışında; opsiyonel olarak toplanabilir.",
            "program_code": program_code,
            "manual_review_required": False,
            "db_write_blocking": False,
        }

    if rule_code == "placed_gt_quota" and _placed_gt_quota_explained(report, program_code):
        return {
            "severity": "warning",
            "rule_code": "expected_warning",
            "original_rule_code": rule_code,
            "status": "expected_warning",
            "message": "Genel yerleşen fazlası okul birincisi veya özel/ek kontenjan kapasitesiyle açıklanıyor.",
            "program_code": program_code,
            "manual_review_required": False,
            "db_write_blocking": False,
        }

    severity = str(issue.get("severity") or "info")
    return {
        "severity": severity,
        "rule_code": rule_code,
        "original_rule_code": rule_code,
        "status": "validation_review" if severity != "info" else "info",
        "message": issue.get("message"),
        "program_code": program_code,
        "manual_review_required": severity != "info",
        "db_write_blocking": severity == "critical",
    }


def _placed_gt_quota_explained(report: dict[str, Any], program_code: str | None) -> bool:
    if not program_code:
        return False
    program = _program_by_code(report).get(str(program_code))
    if not program:
        return False
    quota = program.get("quota_statistics") or {}
    general = quota.get("general") or {}
    general_quota = _to_int(general.get("quota"))
    general_placed = _to_int(general.get("placed"))
    if general_quota is None or general_placed is None:
        return False
    excess = general_placed - general_quota
    if excess <= 0:
        return False

    school_first_quota = _to_int((quota.get("school_first") or {}).get("quota")) or 0
    special_quota_capacity = sum(
        _to_int((quota.get(key) or {}).get("quota")) or 0
        for key in ("school_first", "earthquake", "women_34_plus", "martyr_veteran")
    )
    total_quota_known = _to_int(quota.get("total_quota_known"))
    total_placed_known = _to_int(quota.get("total_placed_known"))
    total_is_consistent = (
        total_quota_known is not None
        and total_placed_known is not None
        and total_placed_known <= total_quota_known
    )
    return total_is_consistent and (excess == school_first_quota or excess <= special_quota_capacity)


def _program_by_code(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    programs: dict[str, dict[str, Any]] = {}
    for program in report.get("programs") or []:
        code = (program.get("program") or {}).get("program_code")
        if code is not None:
            programs[str(code)] = program
    return programs


def _to_int(value: Any) -> int | None:
    if value in {"", None}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _counts_for_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for item in items:
        severity = str(item.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _core_import_decision(data_quality_ready: bool, counts: dict[str, int]) -> str:
    if not data_quality_ready:
        return "import_blocked"
    if counts.get("warning", 0):
        return "import_ready_with_warnings"
    return "import_ready"


def _filtered_quality_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    existing_rule_keys = {
        (str(issue.get("code")), str(issue.get("program_code")))
        for issue in report.get("validation_results") or []
        if issue.get("code")
    }
    existing_panel_codes = {
        str(issue.get("program_code"))
        for issue in report.get("validation_results") or []
        if issue.get("code") == "nets_not_available" and issue.get("program_code") is not None
    }
    filtered: list[dict[str, Any]] = []
    for issue in validate_program_payloads(report):
        rule_key = (str(issue.get("rule_code")), str(issue.get("program_code")))
        if rule_key in existing_rule_keys:
            continue
        if issue.get("rule_code") == "panel_not_discovered" and str(issue.get("program_code")) in existing_panel_codes:
            continue
        filtered.append(issue)
    return filtered


def _deduplicate_manual_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any, Any]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        rule_key = item.get("rule_code") or item.get("status")
        if item.get("status") == "panel_not_discovered":
            rule_key = "panel_not_discovered"
        key = (
            item.get("program_code"),
            rule_key,
            item.get("field_name"),
            item.get("reason"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _blocking_reasons(
    critical_count: int,
    db_errors: list[Any],
    scrape_success: bool,
    scrape_errors: list[Any],
    write_db_requested: bool,
    program_write_allowed: bool,
) -> list[str]:
    reasons: list[str] = []
    if not scrape_success:
        reasons.append("scrape_failed")
    if scrape_errors:
        reasons.append("scrape_errors")
    if critical_count:
        reasons.append("critical_validation_errors")
    if db_errors:
        reasons.append("database_import_errors")
    if not write_db_requested:
        reasons.append("database_write_not_requested")
    elif not program_write_allowed:
        reasons.append("program_write_not_allowed")
    return reasons


__all__ = [
    "build_crawl_run_manifest",
    "build_import_ready_report",
    "build_manual_review_items",
    "build_report_bundle",
    "build_validation_report",
    "severity_counts",
]
