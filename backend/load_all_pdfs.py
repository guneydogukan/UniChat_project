"""
UniChat — Faz 3.1 P0: Tüm PDF'leri Toplu Yükleme
==================================================
backend/data/pdfs/ altındaki TÜM alt klasörlerdeki PDF dosyalarını
ingestion pipeline üzerinden veritabanına yükler.

Her dosya için dosya adından akıllı doc_kind ve category ataması yapılır.

Kullanım:
    # Dry-run (veritabanına yazmadan kontrol):
    python load_all_pdfs.py --dry-run

    # Gerçek yükleme:
    python load_all_pdfs.py
"""

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

# Backend dizinini Python path'e ekle
_backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _backend_dir)

from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv(os.path.join(_backend_dir, "..", ".env"))

from app.ingestion.loader import load_pdf_file

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_all_pdfs")


# ══════════════════════════════════════════════════════════════════════
# Klasör → Varsayılan Metadata Eşleme Tablosu
# ══════════════════════════════════════════════════════════════════════

FOLDER_CONFIG = {
    "yonetmelikler": {
        "category": "egitim",
        "doc_kind": "yonetmelik",
    },
    "yonergeler": {
        "category": "egitim",
        "doc_kind": "yonerge",
    },
    "fakulte_dokumanlari": {
        "category": "bolumler",
        "doc_kind": "genel",
    },
    "idari_belgeler": {
        "category": "ogrenci_isleri",
        "doc_kind": "genel",
    },
    "diger": {
        "category": "genel_bilgi",
        "doc_kind": "genel",
    },
    "mevzuat_web": {
        "category": "egitim",
        "doc_kind": "yonetmelik",
    },
}


# ══════════════════════════════════════════════════════════════════════
# Dosya Adından Akıllı doc_kind Tespiti
# ══════════════════════════════════════════════════════════════════════

_DOC_KIND_PATTERNS = [
    # Yönetmelik / Yönerge
    (re.compile(r"yönetmeli[kğ]", re.IGNORECASE), "yonetmelik"),
    (re.compile(r"yönerge", re.IGNORECASE), "yonerge"),

    # Ders planı / Müfredat
    (re.compile(r"(müfredat|mufredat|ders\s*içerik|öğretim\s*plan)", re.IGNORECASE), "ders_plani"),

    # Tanıtım
    (re.compile(r"(tanıtım|tanitim)", re.IGNORECASE), "tanitim"),
    (re.compile(r"^detay\s+", re.IGNORECASE), "tanitim"),

    # Rehber / İş Akışı / Kılavuz
    (re.compile(r"(iş\s*akış|is\s*akis|kılavuz|kilavuz|el\s*kitab)", re.IGNORECASE), "rehber"),
    (re.compile(r"(usul\s+ve\s+esas|uygulama\s+esas|uygulama\s+ilke)", re.IGNORECASE), "rehber"),

    # Kanun → yonetmelik
    (re.compile(r"kanun", re.IGNORECASE), "yonetmelik"),

    # Form / Başvuru dosyası
    (re.compile(r"(form|başvuru\s+dosya)", re.IGNORECASE), "form"),
]


def _detect_doc_kind(filename: str, folder_default: str) -> str:
    """Dosya adından doc_kind tespiti. Klasör yonetmelik/yonerge ise override etmez."""
    if folder_default in ("yonetmelik", "yonerge"):
        return folder_default

    for pattern, kind in _DOC_KIND_PATTERNS:
        if pattern.search(filename):
            return kind

    return folder_default


def _detect_category(filename: str, folder_default: str) -> str:
    """Dosya adından daha spesifik category tespiti."""
    name_lower = filename.lower()

    if "erasmus" in name_lower or "ka131" in name_lower or "ka171" in name_lower:
        return "erasmus"
    if "dış ilişkiler" in name_lower or "dis iliskiler" in name_lower:
        return "erasmus"
    if "uluslararası öğrenci" in name_lower:
        return "erasmus"
    if "lisansüstü" in name_lower or "enstitü" in name_lower:
        return "lisansustu"
    if "tez " in name_lower or "tez\t" in name_lower or "seminer" in name_lower:
        return "lisansustu"
    if "akademik yükseltme" in name_lower or "puan tablosu" in name_lower:
        return "akademik_kadro"
    if "hizmet içi" in name_lower:
        return "genel_bilgi"
    if "uzaktan" in name_lower and ("öğretim" in name_lower or "eğitim" in name_lower):
        return "egitim"
    if "akademik takvim" in name_lower:
        return "egitim"
    if "ders kayıt" in name_lower or "ders kayit" in name_lower:
        return "egitim"
    if "staj" in name_lower:
        return "egitim"
    if "yatay geçiş" in name_lower or "yatay gecis" in name_lower:
        return "ogrenci_isleri"
    if "askerlik" in name_lower:
        return "ogrenci_isleri"
    if "yükseköğretim kanunu" in name_lower:
        return "genel_bilgi"
    if "sınav" in name_lower:
        return "egitim"
    if "diploma" in name_lower:
        return "ogrenci_isleri"
    if "öğrenci" in name_lower and "kural" in name_lower:
        return "egitim"

    return folder_default


def _detect_department(filename: str) -> str | None:
    """Dosya adından bölüm/fakülte tespiti."""
    name_lower = filename.lower()

    if "bilgisayar mühendisliği" in name_lower or name_lower.startswith("bmb"):
        return "Bilgisayar Mühendisliği"
    if "elektrik" in name_lower or "elektronik" in name_lower or name_lower.startswith("eem"):
        return "Elektrik-Elektronik Mühendisliği"
    if "endüstri mühendisliği" in name_lower:
        return "Endüstri Mühendisliği"
    if "tıp" in name_lower or "tip" in name_lower.split():
        return "Tıp Fakültesi"
    if "hemşire" in name_lower or "hemsire" in name_lower:
        return "Hemşirelik"
    if "ebe" in name_lower.split():
        return "Ebelik"
    if "fizyoterapi" in name_lower:
        return "Fizyoterapi"
    if "arapça" in name_lower or "arapca" in name_lower:
        return "Arapça Mütercim ve Tercümanlık"
    if "ingilizce" in name_lower and "mütercim" in name_lower:
        return "İngilizce Mütercim ve Tercümanlık"
    if "islami ilimler" in name_lower or "İslami İlimler" in filename:
        return "İslami İlimler"
    if "radyo" in name_lower:
        return "Radyo ve Televizyon Teknolojisi"
    if "makine" in name_lower:
        return "Makine ve Metal Teknolojileri"
    if "laboratuvar" in name_lower:
        return "Tıbbi Laboratuvar Teknikleri"
    if "acil yardım" in name_lower or "ilk ve acil" in name_lower:
        return "İlk ve Acil Yardım"
    if "ameliyathane" in name_lower:
        return "Ameliyathane Hizmetleri"
    if "yaşlı bakım" in name_lower or "yasli bakim" in name_lower:
        return "Yaşlı Bakım"
    if "bilgisayar programcılığı" in name_lower or "bilgisayarprogramciligi" in name_lower:
        return "Bilgisayar Programcılığı"
    if "yabancı diller yüksekokulu" in name_lower:
        return "Yabancı Diller Yüksekokulu"
    if "kariyer" in name_lower:
        return "Kariyer Geliştirme Merkezi"

    return None


# ══════════════════════════════════════════════════════════════════════
# Contact Unit — Yönlendirme bilgisi
# ══════════════════════════════════════════════════════════════════════

def _detect_contact_unit(filename: str, category: str) -> str | None:
    """Belge kategorisine göre yönlendirme birimi."""
    name_lower = filename.lower()

    if "erasmus" in name_lower or category == "erasmus":
        return "Dış İlişkiler Koordinatörlüğü / Erasmus+ Ofisi"
    if "lisansüstü" in name_lower or "enstitü" in name_lower or category == "lisansustu":
        return "Lisansüstü Eğitim Enstitüsü"
    if category == "ogrenci_isleri":
        return "Öğrenci İşleri Daire Başkanlığı"
    if "staj" in name_lower:
        return "İlgili Bölüm Staj Komisyonu"
    if "diploma" in name_lower:
        return "Öğrenci İşleri Daire Başkanlığı"

    return None


# ══════════════════════════════════════════════════════════════════════
# Ana Yükleme Fonksiyonu
# ══════════════════════════════════════════════════════════════════════

def load_all_pdfs(dry_run: bool = False) -> dict:
    """Tüm PDF alt klasörlerini sırayla, her dosya için ayrı metadata ile yükler.

    Returns:
        Klasör bazında sonuç raporu.
    """
    pdfs_root = os.path.join(_backend_dir, "data", "pdfs")

    if not os.path.isdir(pdfs_root):
        logger.error("PDF dizini bulunamadı: %s", pdfs_root)
        sys.exit(1)

    results = {}
    grand_total_written = 0
    grand_total_pdfs = 0
    grand_total_errors = 0
    start_time = time.time()

    logger.info("=" * 65)
    logger.info("  Faz 3.1 P0 — Toplu PDF Yükleme Başlıyor")
    logger.info("  PDF kök dizini: %s", pdfs_root)
    logger.info("  Mod: %s", "DRY-RUN" if dry_run else "GERÇEK YÜKLEME")
    logger.info("=" * 65)

    for folder_name, folder_cfg in FOLDER_CONFIG.items():
        folder_path = os.path.join(pdfs_root, folder_name)

        if not os.path.isdir(folder_path):
            logger.warning("⚠️ Klasör bulunamadı, atlanıyor: %s", folder_path)
            results[folder_name] = {"status": "ATLANILDI", "pdf_count": 0, "written": 0, "errors": 0}
            continue

        pdf_files = sorted(
            [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]
        )
        if not pdf_files:
            logger.warning("⚠️ Klasörde PDF yok: %s", folder_name)
            results[folder_name] = {"status": "BOŞ", "pdf_count": 0, "written": 0, "errors": 0}
            continue

        logger.info("")
        logger.info("━" * 65)
        logger.info("📁 %s  (%d PDF)", folder_name.upper(), len(pdf_files))
        logger.info("━" * 65)

        folder_written = 0
        folder_errors = 0

        for pdf_file in pdf_files:
            pdf_path = os.path.join(folder_path, pdf_file)

            # Akıllı metadata tespiti
            doc_kind = _detect_doc_kind(pdf_file, folder_cfg["doc_kind"])
            category = _detect_category(pdf_file, folder_cfg["category"])
            department = _detect_department(pdf_file)
            contact_unit = _detect_contact_unit(pdf_file, category)

            extra_meta = {}
            if department:
                extra_meta["department"] = department
            if contact_unit:
                extra_meta["contact_unit"] = contact_unit

            logger.info("  📄 %s", pdf_file)
            logger.info("     → category=%s, doc_kind=%s%s%s",
                        category, doc_kind,
                        f", dept={department}" if department else "",
                        f", contact={contact_unit}" if contact_unit else "")

            try:
                written = load_pdf_file(
                    path=pdf_path,
                    category=category,
                    doc_kind=doc_kind,
                    dry_run=dry_run,
                    **extra_meta,
                )
                folder_written += written
                logger.info("     ✅ %d belge/chunk", written)

            except Exception as e:
                folder_errors += 1
                logger.error("     ❌ Hata: %s", e)

        grand_total_written += folder_written
        grand_total_pdfs += len(pdf_files)
        grand_total_errors += folder_errors

        results[folder_name] = {
            "status": "OK",
            "pdf_count": len(pdf_files),
            "written": folder_written,
            "errors": folder_errors,
        }

    # ── Özet Rapor ──
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 65)
    logger.info("  📊 TOPLU YÜKLEME SONUÇ RAPORU")
    logger.info("=" * 65)

    for folder_name, r in results.items():
        status = r.get("status", "?")
        pdf_count = r.get("pdf_count", 0)
        written = r.get("written", 0)
        errors = r.get("errors", 0)

        if status == "OK":
            err_str = f"  ({errors} hata)" if errors else ""
            logger.info("  ✅ %-25s  %3d PDF → %4d belge/chunk%s",
                        folder_name, pdf_count, written, err_str)
        else:
            logger.info("  ⚠️ %-25s  %s", folder_name, status)

    logger.info("  ─" * 32)
    logger.info("  TOPLAM: %d PDF → %d belge/chunk  |  %d hata  |  %.1f sn",
                grand_total_pdfs, grand_total_written, grand_total_errors, elapsed)
    logger.info("=" * 65)

    return results


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="UniChat Faz 3.1 P0 — Tüm PDF'leri toplu yükleme"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veritabanına yazmadan rapor ver.",
    )
    args = parser.parse_args()

    load_all_pdfs(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
