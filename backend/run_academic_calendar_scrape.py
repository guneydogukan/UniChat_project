"""GİBTÜ akademik takvim hedefli scraper çalıştırıcı."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR.parent / ".env")

import scrapers._encoding_fix  # noqa: F401
from scrapers.academic_calendar_scraper import AcademicCalendarScraper


def main() -> None:
    parser = argparse.ArgumentParser(description="GİBTÜ akademik takvim scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan parse et")
    parser.add_argument("--force", action="store_true", help="Hash kontrolünü atla")
    parser.add_argument(
        "--report-json",
        default=str(BACKEND_DIR / "academic_calendar_scrape_report.json"),
        help="Rapor JSON çıktı yolu",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = AcademicCalendarScraper()
    report = scraper.scrape(
        dry_run=args.dry_run,
        force=args.force,
        report_json=args.report_json,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))

    if not report.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
