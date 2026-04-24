"""
Gorev 3.4-A — SKS Spor Tesisleri Canli Scrape
Blueprint-guided scrape: Saglik Kultur ve Spor Daire Baskanligi (BirimID=8)
Ek icerik sayfalari + kalite/duyuru detay + PDF'ler.
"""
import sys, io, hashlib, time, json, logging
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint, extract_body_content
from scrapers.map_guided_scraper import MapGuidedScraper
from scrapers.utils import clean_html
from bs4 import BeautifulSoup
import requests
from app.ingestion.loader import ingest_documents
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BIRIM_ID = 8
CATEGORY = "spor"
DEPARTMENT = "Saglik Kultur ve Spor Daire Baskanligi"
CONTACT_UNIT = "Saglik Kultur ve Spor Daire Baskanligi"
CONTACT_INFO = "sks@gibtu.edu.tr"

GIBTU = Path(__file__).resolve().parent.parent / "doc" / "gibtu"
BLUEPRINT = GIBTU / "Sağlık_Kültür_ve_Spor_Daire_Başkanlığı.html"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"


def main():
    print("=" * 65)
    print("3.4-A: SKS Spor Tesisleri — Blueprint Gudumlu Deep Scrape")
    print("=" * 65)

    # Use MapGuidedScraper with blueprint
    scraper = MapGuidedScraper(
        blueprint_path=BLUEPRINT,
        category=CATEGORY,
        department=DEPARTMENT,
        doc_kind="genel",
        contact_unit=CONTACT_UNIT,
        contact_info=CONTACT_INFO,
    )

    report = scraper.scrape_all(dry_run=False)

    # Save report
    json_path = OUTPUT_DIR / "sks_spor_output.json"
    scraper.save_report_json(report, str(json_path))

    # Print summary
    print(f"\n{'='*65}")
    print(f"SONUC: {report.total_documents} doc, {report.total_valid} valid, "
          f"{report.total_failed} failed, {report.total_chars:,} chars")
    print(f"PDF: {len(report.discovered_pdfs)} | doc_kinds: {report.doc_kind_distribution}")
    print(f"Rapor: {json_path}")

    # Summary JSON
    summary = {
        "task": "3.4-A", "description": "SKS Spor Tesisleri Scrape",
        "birim_id": BIRIM_ID,
        "total_valid": report.total_valid,
        "total_failed": report.total_failed,
        "total_documents": report.total_documents,
        "total_chars": report.total_chars,
        "pdf_count": len(report.discovered_pdfs),
        "doc_kind_distribution": report.doc_kind_distribution,
    }
    summary_path = OUTPUT_DIR / "sks_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Ozet: {summary_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
