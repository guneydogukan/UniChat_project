"""MDBF öğrenci işleri workflow/form scrape runner."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from haystack.document_stores.types import DuplicatePolicy

from app.config import get_settings
from app.ingestion.loader import ingest_documents
from app.repositories.workflow_repository import WorkflowRepository
from scrapers.mdbf_workflow_forms_scraper import MdbfWorkflowFormsScraper


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(
        description="MDBF öğrenci işleri iş akışları ve birim formlarını DB-first yapıya aktarır.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Varsayılan davranış; DB'ye yazmadan doğrulama yapar.")
    parser.add_argument("--write-db", action="store_true", help="Relational DB tablolarına UPSERT yapar.")
    parser.add_argument("--ingest-rag", action="store_true", help="Workflow/form Haystack dokümanlarını source_id bazlı replace ederek yazar.")
    parser.add_argument("--no-ai", action="store_true", help="Ollama vision extraction'ı kapatır, yalnız deterministik extraction kullanır.")
    parser.add_argument("--output", default="", help="Validation raporunu JSON olarak kaydedecek dosya yolu.")
    parser.add_argument("--ollama-url", default="", help="Varsayılan OLLAMA_URL değerini override eder.")
    parser.add_argument("--ollama-model", default="", help="Varsayılan OLLAMA_MODEL değerini override eder.")
    args = parser.parse_args()

    settings = get_settings()
    scraper = MdbfWorkflowFormsScraper()
    result = scraper.run(
        use_ai=not args.no_ai,
        ollama_url=args.ollama_url or settings.OLLAMA_URL,
        ollama_model=args.ollama_model or settings.OLLAMA_MODEL,
    )

    report = result["validation_report"]
    print("\nMDBF Workflow/Form Scrape Özeti")
    print("=" * 42)
    print(f"Workflow: {report['workflow_found_count']}/{report['workflow_expected_count']}")
    print(f"Form:     {report['form_found_count']}")
    print(f"Mapping:  {report['mapping_count']} ({report['mapping_success_rate']:.2%})")
    if report["needs_review"]:
        print(f"Review:   {', '.join(report['needs_review'])}")
    else:
        print("Review:   yok")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Rapor yazıldı: {output_path}")

    if args.write_db:
        repository = WorkflowRepository()
        repository.ensure_schema()
        counts = repository.upsert_scrape_result(result)
        print(f"DB UPSERT tamamlandı: {counts}")
    else:
        print("Dry-run: relational DB'ye yazılmadı. Yazmak için --write-db kullan.")

    if args.ingest_rag:
        source_ids = [
            doc.meta["source_id"]
            for doc in result["rag_documents"]
            if doc.meta and doc.meta.get("source_id")
        ]
        written = ingest_documents(
            result["rag_documents"],
            policy=DuplicatePolicy.OVERWRITE,
            replace_source_ids=source_ids,
        )
        print(f"RAG ingestion tamamlandı: {written} belge/chunk yazıldı.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
