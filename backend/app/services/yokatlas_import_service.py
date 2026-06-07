"""
YÖK Atlas DB import servis katmanı.

Scraper raporunu değerlendirir, critical validation varsa temiz program verisi
yazılmasını engeller ve repository'ye yalnız güvenli import talimatı verir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.repositories.yokatlas_repository import YokatlasRepository


@dataclass
class YokatlasDatabaseImportReport:
    write_db_requested: bool
    success: bool
    validation_status: str
    program_write_allowed: bool
    critical_count: int
    warning_count: int
    info_count: int
    inserted: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    db_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_db_requested": self.write_db_requested,
            "success": self.success,
            "validation_status": self.validation_status,
            "program_write_allowed": self.program_write_allowed,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "db_counts": self.db_counts,
            "errors": self.errors,
        }


class YokatlasImportService:
    """YÖK Atlas scrape raporunu DB'ye yazma politikasını uygular."""

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or YokatlasRepository()

    def import_report(
        self,
        report: dict[str, Any],
        write_db: bool,
        ensure_schema: bool = True,
        config: dict[str, Any] | None = None,
    ) -> YokatlasDatabaseImportReport:
        severity_counts = _severity_counts(report)
        validation_status = "invalid" if severity_counts["critical"] else "valid"
        program_write_allowed = bool(write_db and validation_status == "valid")

        import_report = YokatlasDatabaseImportReport(
            write_db_requested=write_db,
            success=not write_db,
            validation_status=validation_status,
            program_write_allowed=program_write_allowed,
            critical_count=severity_counts["critical"],
            warning_count=severity_counts["warning"],
            info_count=severity_counts["info"],
        )

        if not write_db:
            import_report.skipped = {"database_write": 1, "programs": len(report.get("programs") or [])}
            return import_report

        try:
            if ensure_schema and hasattr(self.repository, "ensure_schema"):
                self.repository.ensure_schema()
            counts = self.repository.import_report(
                report,
                allow_program_write=program_write_allowed,
                validation_status=validation_status,
                config=config or {},
            )
            import_report.inserted = {
                "snapshots": counts.get("snapshots_inserted", 0),
                "programs": counts.get("programs_inserted", 0),
                "program_years": counts.get("program_years_inserted", 0),
                "conditions": counts.get("conditions_inserted", 0),
                "validation_results": counts.get("validation_results_inserted", 0),
            }
            import_report.updated = {
                "snapshots": counts.get("snapshots_updated", 0),
                "programs": counts.get("programs_updated", 0),
                "program_years": counts.get("program_years_updated", 0),
                "quota_statistics": counts.get("quota_statistics_upserted", 0),
                "score_statistics": counts.get("score_statistics_upserted", 0),
            }
            import_report.skipped = {"programs": counts.get("skipped_programs", 0)}
            if hasattr(self.repository, "fetch_counts"):
                import_report.db_counts = self.repository.fetch_counts(str(report.get("run_id")))
            import_report.success = True
        except Exception as exc:  # noqa: BLE001 - CLI raporuna açık hata
            import_report.success = False
            import_report.errors.append(str(exc))

        return import_report


def _severity_counts(report: dict[str, Any]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for issue in report.get("validation_results") or []:
        severity = str(issue.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


__all__ = ["YokatlasDatabaseImportReport", "YokatlasImportService"]
