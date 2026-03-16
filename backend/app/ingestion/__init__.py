"""
UniChat Backend — Ingestion Pipeline
Veri yükleme modülü: JSON, PDF ve scraper çıktılarını tek pipeline'dan geçirir.
"""

from app.ingestion.loader import (
    load_json_file,
    load_pdf_file,
    load_pdf_directory,
    ingest_documents,
)

__all__ = [
    "load_json_file",
    "load_pdf_file",
    "load_pdf_directory",
    "ingest_documents",
]
