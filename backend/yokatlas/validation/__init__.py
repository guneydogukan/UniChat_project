"""YÖK Atlas validation katmanı."""

from __future__ import annotations

from scrapers.yokatlas_gibtu_scraper import ValidationEngine, ValidationIssue
from yokatlas.validation.quality_rules import validate_program_payloads

__all__ = ["ValidationEngine", "ValidationIssue", "validate_program_payloads"]
