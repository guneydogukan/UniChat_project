"""
GİBTÜ aday öğrenci portalı entegrasyon wrapper'ı.

Asıl iş mantığı scrapers.candidate_portal_scraper içindedir. Bu dosya sadece
CLI giriş noktası olarak kalır.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401 - Windows stdout UTF-8
from scrapers.candidate_portal_scraper import BASE_URL, CandidatePortalScraper


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("unichat.candidate_portal")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GİBTÜ aday öğrenci portalını hedefli RAG document'larına dönüştürür.",
    )
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan parse ve rapor üret")
    parser.add_argument("--no-cleanup", action="store_true", help="Eski aday portal chunk cleanup adımını atla")
    parser.add_argument("--report-json", default=None, help="Raporu JSON dosyasına yaz")
    parser.add_argument("--url", default=BASE_URL, help="Yalnızca adayogrenci.gibtu.edu.tr kapsamındaki portal URL'i")
    args = parser.parse_args()

    scraper = CandidatePortalScraper(url=args.url)
    report = scraper.scrape(
        dry_run=args.dry_run,
        cleanup=not args.no_cleanup,
        report_json=args.report_json,
    )

    print("\n" + "=" * 65)
    print("GİBTÜ ADAY ÖĞRENCİ PORTALI SCRAPE RAPORU")
    print("=" * 65)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    print("=" * 65)

    if not report.success:
        logger.error("Aday öğrenci portalı entegrasyonu başarısız: %s", report.errors)
        return 1

    logger.info(
        "Aday portal tamamlandı: %d document, %d chunk, SSS=%d, olanak=%d",
        report.documents_created,
        report.chunks_written,
        report.faq_count,
        report.opportunity_count,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
