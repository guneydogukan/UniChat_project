"""DB write öncesi ek kalite kontrol yardımcıları.

Bu modül mevcut scraper validation engine'ini değiştirmez; rapor çıktısı
üzerinden ek denetim yapılmasını sağlar. Fonksiyonlar saf tutulduğu için
fixture ve regression testlerinde güvenle kullanılabilir.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

from scrapers.yokatlas_gibtu_scraper import _to_decimal, _to_int
from yokatlas.contracts import EXPECTED_SCORE_TYPES


def normalize_enum_text(value: Any) -> str:
    """Enum karşılaştırmaları için Unicode ve boşluk normalizasyonu yapar."""
    text = "" if value is None else str(value)
    return unicodedata.normalize("NFC", text).strip().upper()


def is_valid_osym_code(value: Any) -> bool:
    text = "" if value is None else str(value).strip()
    return text.isdigit() and len(text) == 9


def validate_program_payloads(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize program payload'ları üzerinde kalite kontrol listesi üretir."""
    programs = list(report.get("programs") or [])
    issues: list[dict[str, Any]] = []
    keys: list[tuple[str, int | None]] = []

    for program in programs:
        program_info = program.get("program") or {}
        program_year = program.get("program_year") or {}
        education = program.get("education") or {}
        quotas = program.get("quota_statistics") or {}
        admissions = program.get("admission_statistics") or {}
        nets = program.get("last_admitted_nets") or {}

        code = program_info.get("program_code")
        year = _to_int(program_year.get("data_year") or report.get("data_year"))
        source_url = program_year.get("source_url") or (program.get("source") or {}).get("source_url")
        record_key = f"{code or 'unknown'}/{year or 'unknown'}"
        keys.append((str(code or ""), year))

        if not is_valid_osym_code(code):
            issues.append(_issue("critical", "osym_format", "ÖSYM kodu 9 haneli değil.", record_key, code, source_url))

        if not source_url:
            issues.append(_issue("critical", "missing_source_url", "Kaynak URL boş.", record_key, code, source_url))

        score_type = normalize_enum_text(education.get("score_type"))
        if score_type and score_type not in EXPECTED_SCORE_TYPES:
            issues.append(_issue("critical", "score_type_enum", "Beklenmeyen puan türü.", record_key, code, source_url))

        general_quota = (quotas.get("general") or {}).get("quota")
        general_placed = (quotas.get("general") or {}).get("placed")
        quota_value = _to_int(general_quota)
        placed_value = _to_int(general_placed)
        if quota_value is None:
            issues.append(_issue("critical", "quota_numeric", "Genel kontenjan sayısal değil.", record_key, code, source_url))
        if placed_value is None:
            issues.append(_issue("critical", "placed_numeric", "Genel yerleşen sayısı sayısal değil.", record_key, code, source_url))
        if quota_value is not None and placed_value is not None and placed_value > quota_value:
            issues.append(_issue(
                "warning",
                "placed_gt_quota",
                "Yerleşen sayısı genel kontenjandan büyük; özel/ek kontenjan açıklaması kontrol edilmeli.",
                record_key,
                code,
                source_url,
            ))

        base_score = admissions.get("base_score")
        base_rank = admissions.get("base_rank")
        if base_score not in (None, "") and _to_decimal(base_score) is None:
            issues.append(_issue("critical", "base_score_numeric", "Taban puan numeric formata çevrilemedi.", record_key, code, source_url))
        if base_rank not in (None, "") and _to_int(base_rank) is None:
            issues.append(_issue("critical", "rank_integer", "Başarı sırası integer formata çevrilemedi.", record_key, code, source_url))

        if nets.get("status") in {"not_available", "not_discovered"}:
            issues.append(_issue(
                "warning",
                "panel_not_discovered",
                "Son yerleşen netleri panel/endpoint keşfiyle doğrulanmalı.",
                record_key,
                code,
                source_url,
            ))

    duplicate_counts = Counter(keys)
    for code_year, count in duplicate_counts.items():
        code, year = code_year
        if count > 1:
            issues.append(_issue(
                "critical",
                "osym_unique",
                f"Aynı ÖSYM kodu + veri yılı birden fazla görünüyor: {code}/{year}.",
                f"{code}/{year}",
                code,
                None,
            ))

    return issues


def _issue(
    severity: str,
    rule_code: str,
    message: str,
    record_key: str,
    program_code: Any,
    source_url: Any,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "rule_code": rule_code,
        "code": rule_code,
        "message": message,
        "record_key": record_key,
        "program_code": None if program_code is None else str(program_code),
        "source_url": source_url,
        "automatic_fixable": severity != "critical",
        "manual_review_required": severity in {"critical", "warning"},
        "db_write_blocking": severity == "critical",
    }


__all__ = ["is_valid_osym_code", "normalize_enum_text", "validate_program_payloads"]
