"""
UniChat — Faz 4.1.2: MapGuidedScraper Tabanlı Gelişmiş Birim Scraper

MapGuidedScraper sınıfını extend ederek birim-spesifik scrape mantığı sağlar.
Blueprint path otomatik keşfi, toplu scrape modu ve kalite raporu entegrasyonu.

Kullanım:
    from scrapers.department_scraper import DepartmentScraper

    # Tek birim
    scraper = DepartmentScraper()
    report = scraper.scrape_department(
        blueprint_path="doc/gibtu/FAKÜLTELER/.../MDBF.html",
        category="bolumler",
        department="Mühendislik ve Doğa Bilimleri Fakültesi",
    )

    # Tüm haritası olan birimler
    reports = scraper.scrape_all_departments(dry_run=True)

CLI:
    python -m scrapers.department_scraper --list           # Mevcut blueprint'leri listele
    python -m scrapers.department_scraper --all --dry-run  # Tümünü dry-run
    python -m scrapers.department_scraper --blueprint "doc/gibtu/..." --ingest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 — Windows stdout UTF-8

from scrapers.map_guided_scraper import MapGuidedScraper, ScrapeReport
from scrapers.quality_checker import QualityChecker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Blueprint Keşif Dizini ──
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_GIBTU_DIR = _PROJECT_ROOT / "doc" / "gibtu"


# ── Bilinen birim-blueprint eşleştirmeleri ──
# Her bir blueprint için category, department ve contact_unit bilgisi
DEPARTMENT_REGISTRY: list[dict] = [
    # ── Fakülteler ──
    {
        "blueprint": "FAKÜLTELER/İlahiyat Fakültesi/İlahiyat-Türkçe-Arapca.html",
        "category": "bolumler",
        "department": "İlahiyat Fakültesi",
        "contact_unit": "İlahiyat Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Mühendislik ve Doğa Bilimleri Fakültesi/Mühendislik_ve_Doğa_Bilimleri _Fakültesi.html",
        "category": "bolumler",
        "department": "Mühendislik ve Doğa Bilimleri Fakültesi",
        "contact_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Mühendislik ve Doğa Bilimleri Fakültesi/Bilgisayar_Mühendisliği_Bölümü.html",
        "category": "bolumler",
        "department": "Bilgisayar Mühendisliği Bölümü",
        "contact_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Mühendislik ve Doğa Bilimleri Fakültesi/Elektrik_Elektronik_Mühendisliği_Bölümü.html",
        "category": "bolumler",
        "department": "Elektrik-Elektronik Mühendisliği Bölümü",
        "contact_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Mühendislik ve Doğa Bilimleri Fakültesi/Endüstri_Mühendisliği_Bölümü.html",
        "category": "bolumler",
        "department": "Endüstri Mühendisliği Bölümü",
        "contact_unit": "Mühendislik ve Doğa Bilimleri Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Sağlık Bilimleri Fakültesi/Sağlık_Bilimleri_Fakültesi.html",
        "category": "bolumler",
        "department": "Sağlık Bilimleri Fakültesi",
        "contact_unit": "Sağlık Bilimleri Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Tıp Fakültesi/Tıp.html",
        "category": "bolumler",
        "department": "Tıp Fakültesi",
        "contact_unit": "Tıp Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/İktisadi İdari ve Sosyal Bilimler Fakültesi/İktisadi_İdari_ve_Sosyal_Bilimler_Fakültesi.html",
        "category": "bolumler",
        "department": "İktisadi İdari ve Sosyal Bilimler Fakültesi",
        "contact_unit": "İktisadi İdari ve Sosyal Bilimler Fakültesi",
    },
    {
        "blueprint": "FAKÜLTELER/Güzel Sanatlar Tasarım ve Mimarlık Fakültesi/Güzel_Sanatlar_Tasarım_ve_Mimarlık_Fakültesi.html",
        "category": "bolumler",
        "department": "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
        "contact_unit": "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
    },
    # ── MYO'lar ──
    {
        "blueprint": "MYO/Sağlık Hizmetleri MYO/Sağlık_Hizmetleri_Meslek_Yüksekokulu_Genel_Yapısı.html",
        "category": "bolumler",
        "department": "Sağlık Hizmetleri MYO",
        "contact_unit": "Sağlık Hizmetleri MYO",
    },
    {
        "blueprint": "MYO/Teknik Bilimler MYO/Teknik_Bilimler_Meslek_Yüksekokulu_Genel_Yapısı.html",
        "category": "bolumler",
        "department": "Teknik Bilimler MYO",
        "contact_unit": "Teknik Bilimler MYO",
    },
    # ── Yüksekokullar ──
    {
        "blueprint": "YÜKSEKOKULLAR/Yabancı_Diller_Yüksekokulu.html",
        "category": "bolumler",
        "department": "Yabancı Diller Yüksekokulu",
        "contact_unit": "Yabancı Diller Yüksekokulu",
    },
    # ── Daire Başkanlıkları ──
    {
        "blueprint": "Öğrenci_İşleri_Daire_Başkanlığı.html",
        "category": "idari",
        "department": "Öğrenci İşleri Daire Başkanlığı",
        "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
    },
    {
        "blueprint": "Kütüphane_ve_Dokümantasyon_Daire_Başkanlığı.html",
        "category": "kutuphane",
        "department": "Kütüphane ve Dokümantasyon Daire Başkanlığı",
        "contact_unit": "Kütüphane ve Dokümantasyon Daire Başkanlığı",
    },
    {
        "blueprint": "Sağlık_Kültür_ve_Spor_Daire_Başkanlığı.html",
        "category": "kampus",
        "department": "Sağlık Kültür ve Spor Daire Başkanlığı",
        "contact_unit": "Sağlık Kültür ve Spor Daire Başkanlığı",
    },
    # ── Koordinatörlükler ──
    {
        "blueprint": "Dış_İlişkiler_Koordinatörlüğü.html",
        "category": "uluslararasi",
        "department": "Dış İlişkiler Koordinatörlüğü",
        "contact_unit": "Dış İlişkiler Koordinatörlüğü",
    },
    {
        "blueprint": "Erasmus+Koordinatörlüğü.html",
        "category": "uluslararasi",
        "department": "Erasmus+ Koordinatörlüğü",
        "contact_unit": "Erasmus+ Koordinatörlüğü",
    },
]


@dataclass
class DepartmentScrapeResult:
    """Tek bir birim scrape sonucu."""
    department: str = ""
    blueprint: str = ""
    success: bool = False
    documents_count: int = 0
    valid_pages: int = 0
    failed_pages: int = 0
    chars: int = 0
    error: str = ""


class DepartmentScraper:
    """
    MapGuidedScraper tabanlı gelişmiş birim scraper.
    
    Tüm haritası olan birimler için tek noktadan scrape yönetimi sağlar.
    """

    def __init__(self, gibtu_dir: Path | None = None):
        self.gibtu_dir = gibtu_dir or _GIBTU_DIR
        self._quality_checker = QualityChecker()

    def discover_blueprints(self) -> list[dict]:
        """
        doc/gibtu/ altındaki mevcut blueprint'leri keşfeder.
        DEPARTMENT_REGISTRY ile eşleştirip bulunanları döndürür.
        """
        found = []
        for entry in DEPARTMENT_REGISTRY:
            bp_path = self.gibtu_dir / entry["blueprint"]
            if bp_path.exists():
                found.append({
                    **entry,
                    "full_path": str(bp_path),
                    "size_kb": round(bp_path.stat().st_size / 1024, 1),
                })
            else:
                logger.debug("Blueprint bulunamadı: %s", bp_path)
        return found

    def scrape_department(
        self,
        blueprint_path: str | Path,
        category: str = "bolumler",
        department: str = "",
        contact_unit: str = "",
        dry_run: bool = False,
        url_limit: int | None = None,
        with_quality_report: bool = True,
    ) -> DepartmentScrapeResult:
        """
        Tek bir birimi MapGuidedScraper ile scrape eder.

        Args:
            blueprint_path: Blueprint HTML dosya yolu.
            category: Belge kategorisi.
            department: Birim adı.
            contact_unit: İletişim birimi.
            dry_run: True ise DB'ye yazmaz.
            url_limit: Test için URL sınırı.
            with_quality_report: Kalite raporu üretilsin mi.

        Returns:
            DepartmentScrapeResult nesnesi.
        """
        result = DepartmentScrapeResult(
            department=department,
            blueprint=str(blueprint_path),
        )

        try:
            scraper = MapGuidedScraper(
                blueprint_path=blueprint_path,
                category=category,
                department=department,
                contact_unit=contact_unit,
                url_limit=url_limit,
            )

            report = scraper.scrape_all(dry_run=dry_run)

            result.success = True
            result.documents_count = report.total_documents
            result.valid_pages = report.total_valid
            result.failed_pages = report.total_failed
            result.chars = report.total_chars

            # JSON rapor kaydet
            output_dir = Path(__file__).resolve().parent
            safe_dept = department.lower().replace(" ", "_")[:30]
            json_path = output_dir / f"dept_{safe_dept}_output.json"
            scraper.save_report_json(report, str(json_path))

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.error("Scrape hatası (%s): %s", department, e)

        return result

    def scrape_all_departments(
        self,
        dry_run: bool = False,
        url_limit: int | None = None,
    ) -> list[DepartmentScrapeResult]:
        """
        Tüm keşfedilmiş blueprint'ler üzerinden toplu scrape.

        Args:
            dry_run: True ise DB'ye yazmaz.
            url_limit: Test için URL sınırı.

        Returns:
            DepartmentScrapeResult listesi.
        """
        blueprints = self.discover_blueprints()
        if not blueprints:
            logger.warning("Hiç blueprint bulunamadı!")
            return []

        logger.info("=" * 65)
        logger.info("TOPLU BİRİM SCRAPE — %d blueprint bulundu", len(blueprints))
        logger.info("=" * 65)

        results = []
        for i, bp in enumerate(blueprints):
            logger.info(
                "\n[%d/%d] %s — %s",
                i + 1, len(blueprints), bp["department"], bp["blueprint"],
            )

            result = self.scrape_department(
                blueprint_path=bp["full_path"],
                category=bp["category"],
                department=bp["department"],
                contact_unit=bp.get("contact_unit", ""),
                dry_run=dry_run,
                url_limit=url_limit,
            )
            results.append(result)

            status = "✅" if result.success else "❌"
            logger.info(
                "  %s %s: %d doc, %d valid, %d failed, %d kar",
                status, result.department,
                result.documents_count, result.valid_pages,
                result.failed_pages, result.chars,
            )

        # Özet
        ok = sum(1 for r in results if r.success)
        fail = sum(1 for r in results if not r.success)
        total_docs = sum(r.documents_count for r in results)
        total_chars = sum(r.chars for r in results)

        logger.info("\n" + "=" * 65)
        logger.info("TOPLU SCRAPE ÖZET")
        logger.info("=" * 65)
        logger.info("  Başarılı:   %d / %d", ok, len(results))
        logger.info("  Başarısız:  %d", fail)
        logger.info("  Toplam doc: %d", total_docs)
        logger.info("  Toplam kar: %s", f"{total_chars:,}")
        logger.info("=" * 65)

        return results

    def list_blueprints(self):
        """Mevcut blueprint'leri listeler."""
        blueprints = self.discover_blueprints()

        print("\n" + "=" * 65)
        print(f"📁 Mevcut Blueprint'ler — {self.gibtu_dir}")
        print("=" * 65)

        if not blueprints:
            print("  Hiç blueprint bulunamadı!")
            return

        for bp in blueprints:
            print(f"  📄 {bp['department']}")
            print(f"     Path: {bp['blueprint']}")
            print(f"     Kategori: {bp['category']}, Boyut: {bp['size_kb']} KB")
            print()

        print(f"  Toplam: {len(blueprints)} blueprint")
        print("=" * 65)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniChat Birim Scraper (Faz 4.1.2)",
    )
    parser.add_argument("--list", action="store_true", help="Mevcut blueprint'leri listele")
    parser.add_argument("--all", action="store_true", help="Tüm birimleri scrape et")
    parser.add_argument("--blueprint", default=None, help="Tek blueprint path")
    parser.add_argument("--category", default="bolumler", help="Kategori")
    parser.add_argument("--department", default="", help="Birim adı")
    parser.add_argument("--limit", type=int, default=None, help="URL limiti (test)")
    parser.add_argument("--ingest", action="store_true", help="DB'ye yükle")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan çalıştır")
    args = parser.parse_args()

    ds = DepartmentScraper()

    if args.list:
        ds.list_blueprints()
        return

    if args.all:
        is_dry = args.dry_run or not args.ingest
        ds.scrape_all_departments(dry_run=is_dry, url_limit=args.limit)
        return

    if args.blueprint:
        is_dry = args.dry_run or not args.ingest
        result = ds.scrape_department(
            blueprint_path=args.blueprint,
            category=args.category,
            department=args.department,
            dry_run=is_dry,
            url_limit=args.limit,
        )
        status = "BAŞARILI" if result.success else "BAŞARISIZ"
        print(f"\n🏁 Birim scrape {status}: {result.documents_count} Document")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
