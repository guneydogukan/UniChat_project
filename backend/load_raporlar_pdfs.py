"""
Görev 3.2.5 — Raporlar PDF'lerini yükle.
Sadece data/pdfs/raporlar_web altındaki PDF'leri ingestion pipeline'a gönderir.

Kullanım:
    ..\\.venv\\Scripts\\python.exe load_raporlar_pdfs.py --dry-run
    ..\\.venv\\Scripts\\python.exe load_raporlar_pdfs.py
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(_backend_dir, "..", ".env"))

from app.ingestion.loader import load_pdf_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PDF_DIR = Path(_backend_dir) / "data" / "pdfs" / "raporlar_web"


def main():
    parser = argparse.ArgumentParser(description="Raporlar PDF yükleme (3.2.5)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not PDF_DIR.is_dir():
        logger.error("PDF dizini bulunamadı: %s", PDF_DIR)
        sys.exit(1)

    pdf_files = sorted(f for f in PDF_DIR.iterdir() if f.suffix.lower() == ".pdf")
    logger.info("=" * 60)
    logger.info("Raporlar PDF Yükleme — %d dosya", len(pdf_files))
    logger.info("Mod: %s", "DRY-RUN" if args.dry_run else "GERÇEK YÜKLEME")
    logger.info("=" * 60)

    total_written = 0
    errors = 0

    for pdf_path in pdf_files:
        name_lower = pdf_path.stem.lower()

        # contact_unit tespiti
        contact_unit = "Strateji Geliştirme Daire Başkanlığı"

        logger.info("📄 %s", pdf_path.name)
        try:
            written = load_pdf_file(
                path=str(pdf_path),
                category="genel_bilgi",
                doc_kind="rapor",
                dry_run=args.dry_run,
                contact_unit=contact_unit,
                contact_info="strateji@gibtu.edu.tr",
            )
            total_written += written
            logger.info("   ✅ %d chunk yazıldı", written)
        except Exception as e:
            errors += 1
            logger.error("   ❌ Hata: %s", e)

    logger.info("")
    logger.info("=" * 60)
    logger.info("SONUÇ: %d PDF → %d chunk | %d hata", len(pdf_files), total_written, errors)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
