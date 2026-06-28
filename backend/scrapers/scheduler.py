"""
UniChat — Faz 4.4: APScheduler ile Periyodik Güncelleme Zamanlayıcı

Tüm scraper modüllerini periyodik olarak çalıştıran merkezi zamanlayıcı.

Job Tanımları:
  - Duyurular:            Günde 1 kez (saat 08:00)
  - Bölüm duyuruları:     Haftada 1 kez (Pazartesi 08:30, staging)
  - Yemekhane menüsü:     Günde 1 kez (saat 07:00, food_menus upsert)
  - Akademik takvim:      Yılda 1 kez eğitim-öğretim yılı başında (1 Eylül 05:30)
  - Birim yönetimi:       Dönem başlarında (1 Şubat ve 1 Eylül, 02:30)
  - İdari personel:       Dönem başlarında (1 Şubat ve 1 Eylül, 02:45)
  - Akademik kadro:       Dönem başlarında (1 Şubat ve 1 Eylül, 03:00)
  - Aday öğrenci portalı: Dönem başlarında (1 Şubat ve 1 Eylül, 04:00)
  - Tam yeniden indeks:   Ayda 1 kez (ayın 1'i, 02:00)

Güvenlik:
  - PID kontrolü ile çoklu instance önleme
  - replace_existing=True ile job duplicate önleme
  - Graceful shutdown (SIGTERM/SIGINT)
  - Her job çalışması loglanır

Kullanım:
    python -m scrapers.scheduler                    # Tüm job'ları başlat
    python -m scrapers.scheduler --list             # Mevcut job'ları listele
    python -m scrapers.scheduler --run-now duyuru   # Belirli job'ı hemen çalıştır
    python -m scrapers.scheduler --run-now bolum_duyuru
    python -m scrapers.scheduler --run-now yemek
    python -m scrapers.scheduler --run-now akademik_takvim
    python -m scrapers.scheduler --run-now yonetim
    python -m scrapers.scheduler --run-now idari_personel
    python -m scrapers.scheduler --run-now kadro
    python -m scrapers.scheduler --run-now aday_ogrenci
    python -m scrapers.scheduler --run-now full_reindex

Bağımlılık:
    pip install apscheduler
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 — Windows stdout UTF-8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("unichat.scheduler")

# ── PID Kontrolü ──
LOCK_FILE = Path(__file__).resolve().parent / ".scheduler.lock"
LOG_FILE = Path(__file__).resolve().parent / "scheduler_log.json"
KADRO_UPDATE_MONTHS = "2,9"
KADRO_UPDATE_DAY = 1
KADRO_UPDATE_HOUR = 3
KADRO_UPDATE_MINUTE = 0
UNIT_MANAGEMENT_UPDATE_MONTHS = "2,9"
UNIT_MANAGEMENT_UPDATE_DAY = 1
UNIT_MANAGEMENT_UPDATE_HOUR = 2
UNIT_MANAGEMENT_UPDATE_MINUTE = 30
ADMINISTRATIVE_STAFF_UPDATE_MONTHS = "2,9"
ADMINISTRATIVE_STAFF_UPDATE_DAY = 1
ADMINISTRATIVE_STAFF_UPDATE_HOUR = 2
ADMINISTRATIVE_STAFF_UPDATE_MINUTE = 45


def _acquire_pid_lock() -> bool:
    """PID tabanlı dosya kilidi. Aynı anda birden fazla scheduler çalışmasını engeller."""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            try:
                os.kill(old_pid, 0)
                logger.error(
                    "Başka bir scheduler zaten çalışıyor (PID=%d). Çıkılıyor.", old_pid
                )
                return False
            except OSError:
                logger.warning("Eski lock temizleniyor (PID=%d artık yok)", old_pid)
                LOCK_FILE.unlink(missing_ok=True)
        except (ValueError, IOError):
            LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_pid_lock():
    """Lock dosyasını sil."""
    LOCK_FILE.unlink(missing_ok=True)


def _append_job_log(entry: dict):
    """Job çalışma loguna kayıt ekle."""
    logs = []
    if LOG_FILE.exists():
        try:
            logs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            logs = []

    logs.append(entry)

    # Son 200 kaydı tut
    if len(logs) > 200:
        logs = logs[-200:]

    LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=1), encoding="utf-8")


# ── Job Fonksiyonları ──

def job_duyuru_update():
    """Duyuru arşivi delta güncelleme job'ı."""
    start = time.time()
    job_name = "duyuru_update"
    logger.info("🔔 Job başlıyor: %s", job_name)

    try:
        from scrapers.announcement_scraper import AnnouncementScraper

        scraper = AnnouncementScraper()
        result = scraper.scrape(mode="delta", dry_run=False)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "documents": result.documents_created,
            "chunks": result.chunks_written,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — %d doc, %d chunk, %.1fs",
            job_name, result.documents_created, result.chunks_written, duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_department_announcement_staging():
    """Mühendislik bölüm duyurularını staging'e alan haftalık job."""
    start = time.time()
    job_name = "department_announcement_staging"
    logger.info("🔔 Job başlıyor: %s", job_name)

    try:
        from app.services.department_announcement_service import get_department_announcement_service

        result = get_department_announcement_service().scrape_to_staging()

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.get("success", False),
            "scrape_run_id": result.get("scrape_run_id"),
            "fetched": result.get("fetched", 0),
            "staged": result.get("staged", 0),
            "duplicates": result.get("duplicates", 0),
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — %d fetched, %d staged, %d duplicate, %.1fs",
            job_name,
            result.get("fetched", 0),
            result.get("staged", 0),
            result.get("duplicates", 0),
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_yemek_update():
    """Yemekhane menüsünü food_menus tablosuna güncelleyen job."""
    start = time.time()
    job_name = "yemek_update"
    logger.info("🍽️ Job başlıyor: %s", job_name)

    try:
        from scrapers.menu_scraper import MenuScraper

        scraper = MenuScraper()
        result = scraper.scrape(dry_run=False)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "content_changed": result.content_changed,
            "menu_items": result.menu_items_count,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — %d günlük menü, %d upsert, %.1fs",
            job_name, result.menu_items_count, result.chunks_written, duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_academic_calendar_update():
    """Akademik takvim ana URL'sini yıllık hash kontrolüyle günceller."""
    start = time.time()
    job_name = "academic_calendar_update"
    logger.info("📅 Job başlıyor: %s", job_name)

    try:
        from scrapers.academic_calendar_scraper import AcademicCalendarScraper

        scraper = AcademicCalendarScraper()
        result = scraper.scrape(dry_run=False, force=False, skip_unchanged=True)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "sources_discovered": result.sources_discovered,
            "sources_processed": result.sources_processed,
            "sources_unchanged": result.sources_unchanged,
            "events_created": result.events_created,
            "chunks": result.chunks_written,
            "duration_seconds": round(duration, 1),
            "errors": result.errors,
        })

        logger.info(
            "✅ Job tamamlandı: %s — kaynak=%d, işlenen=%d, değişmeyen=%d, event=%d, chunk=%d, %.1fs",
            job_name,
            result.sources_discovered,
            result.sources_processed,
            result.sources_unchanged,
            result.events_created,
            result.chunks_written,
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_kadro_update():
    """YÖK Akademik bölüm/program akademik kadro güncelleme job'ı (dönem başı)."""
    start = time.time()
    job_name = "kadro_update"
    logger.info("👥 Job başlıyor: %s", job_name)

    try:
        from scrapers.yok_academic_staff_scraper import YokAcademicStaffScraper

        scraper = YokAcademicStaffScraper()
        result = scraper.scrape(dry_run=False, write_db=True)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "targets": len(result.targets),
            "persons": len(result.persons),
            "staff_snapshots": len(result.staff_snapshots),
            "answer_chunks": len(result.answer_documents),
            "validation_results": len(result.validation_results),
            "errors": result.errors,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — hedef=%d, kişi=%d, bölüm/program_snapshot=%d, answer_chunk=%d, %.1fs",
            job_name,
            len(result.targets),
            len(result.persons),
            len(result.staff_snapshots),
            len(result.answer_documents),
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_unit_management_update():
    """GİBTÜ BirimYonetim yönetim bilgilerini dönem başında güncelleyen job."""
    start = time.time()
    job_name = "unit_management_update"
    logger.info("🏛️ Job başlıyor: %s", job_name)

    try:
        from scrapers.unit_management_scraper import UnitManagementScraper

        scraper = UnitManagementScraper()
        result = scraper.scrape(dry_run=False, write_db=True)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "processed_urls": result.validation_report.get("processed_url_count"),
            "groups": result.validation_report.get("group_count"),
            "members": result.validation_report.get("member_count"),
            "needs_review": len(result.validation_report.get("needs_review_records") or []),
            "errors": result.errors,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — URL=%s, grup=%s, kişi=%s, %.1fs",
            job_name,
            result.validation_report.get("processed_url_count"),
            result.validation_report.get("group_count"),
            result.validation_report.get("member_count"),
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_administrative_staff_update():
    """GİBTÜ idari birim/personel bilgilerini dönem başında güncelleyen job."""
    start = time.time()
    job_name = "administrative_staff_update"
    logger.info("🗂️ Job başlıyor: %s", job_name)

    try:
        from scrapers.administrative_staff_scraper import AdministrativeStaffScraper

        scraper = AdministrativeStaffScraper()
        result = scraper.scrape(dry_run=False, write_db=True)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "processed_urls": result.validation_report.get("processed_url_count"),
            "administrative_units": result.validation_report.get("administrative_unit_count"),
            "staff": result.validation_report.get("staff_count"),
            "warnings": result.validation_report.get("warning_count"),
            "critical": result.validation_report.get("critical_count"),
            "errors": result.errors,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — URL=%s, idari_birim=%s, personel=%s, %.1fs",
            job_name,
            result.validation_report.get("processed_url_count"),
            result.validation_report.get("administrative_unit_count"),
            result.validation_report.get("staff_count"),
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_candidate_portal_update():
    """Aday öğrenci portalını dönem başlarında güncelleyen job."""
    start = time.time()
    job_name = "candidate_portal_update"
    logger.info("🎓 Job başlıyor: %s", job_name)

    try:
        from scrapers.candidate_portal_scraper import CandidatePortalScraper

        scraper = CandidatePortalScraper()
        result = scraper.scrape(dry_run=False, cleanup=True)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "documents": result.documents_created,
            "chunks": result.chunks_written,
            "faq_count": result.faq_count,
            "opportunity_count": result.opportunity_count,
            "duration_seconds": round(duration, 1),
            "errors": result.errors,
        })

        logger.info(
            "✅ Job tamamlandı: %s — %d doc, %d chunk, SSS=%d, olanak=%d, %.1fs",
            job_name,
            result.documents_created,
            result.chunks_written,
            result.faq_count,
            result.opportunity_count,
            duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Job hatası: %s — %s", job_name, e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


def job_full_reindex():
    """Tam yeniden indeksleme job'ı (aylık)."""
    start = time.time()
    job_name = "full_reindex"
    logger.info("🔄 Job başlıyor: %s (aylık tam yeniden indeksleme)", job_name)

    try:
        # Duyuruları tam modda çek
        from scrapers.announcement_scraper import AnnouncementScraper
        ann_scraper = AnnouncementScraper()
        ann_result = ann_scraper.scrape(mode="full", dry_run=False)

        # Menüyü zorla güncelle
        from scrapers.menu_scraper import MenuScraper
        menu_scraper = MenuScraper()
        menu_result = menu_scraper.scrape(dry_run=False, force=True)

        duration = time.time() - start
        total_docs = (
            ann_result.documents_created
            + menu_result.documents_created
        )
        total_chunks = (
            ann_result.chunks_written
            + menu_result.chunks_written
        )

        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "sub_jobs": {
                "duyuru": {"docs": ann_result.documents_created, "chunks": ann_result.chunks_written},
                "yemek": {"changed": menu_result.content_changed, "chunks": menu_result.chunks_written},
                "kadro": {
                    "skipped": True,
                    "reason": "YÖK Akademik kadro yalnız dönem başı job'ında güncellenir.",
                },
                "yonetim": {
                    "skipped": True,
                    "reason": "Birim yönetim bilgileri yalnız dönem başı job'ında güncellenir.",
                },
                "idari_personel": {
                    "skipped": True,
                    "reason": "İdari birim/personel bilgileri yalnız dönem başı job'ında güncellenir.",
                },
            },
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Full reindex tamamlandı: %d doc, %d chunk, %.1fs",
            total_docs, total_chunks, duration,
        )

    except Exception as e:
        duration = time.time() - start
        logger.error("❌ Full reindex hatası: %s", e)
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(e),
            "duration_seconds": round(duration, 1),
        })


JOB_RUNNERS = {
    "duyuru": job_duyuru_update,
    "bolum_duyuru": job_department_announcement_staging,
    "yemek": job_yemek_update,
    "akademik_takvim": job_academic_calendar_update,
    "yonetim": job_unit_management_update,
    "idari_personel": job_administrative_staff_update,
    "kadro": job_kadro_update,
    "aday_ogrenci": job_candidate_portal_update,
    "full_reindex": job_full_reindex,
}


# ── Scheduler Kurulumu ──

def create_scheduler():
    """APScheduler instance oluşturur ve job'ları tanımlar."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error(
            "APScheduler yüklü değil! Yüklemek için:\n"
            "  pip install apscheduler"
        )
        sys.exit(1)

    scheduler = BlockingScheduler(timezone="Europe/Istanbul")

    # ── Job Tanımları ──

    # 1. Duyurular: Günde 1 kez (08:00)
    scheduler.add_job(
        job_duyuru_update,
        trigger=CronTrigger(hour=8, minute=0),
        id="duyuru_update",
        name="Duyuru Arşivi Delta Güncelleme",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 saat tolerance
    )

    # 2. Bölüm duyuruları: Haftada 1 kez, staging'e alır (Pazartesi 08:30)
    scheduler.add_job(
        job_department_announcement_staging,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=30),
        id="department_announcement_staging",
        name="Mühendislik Bölüm Duyuruları Staging",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # 3. Yemekhane: Günde 1 kez (07:00)
    scheduler.add_job(
        job_yemek_update,
        trigger=CronTrigger(hour=7, minute=0),
        id="yemek_update",
        name="Yemekhane Menü Güncelleme",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 4. Akademik takvim: Yılda 1 kez eğitim-öğretim yılı başında (1 Eylül 05:30)
    scheduler.add_job(
        job_academic_calendar_update,
        trigger=CronTrigger(month=9, day=1, hour=5, minute=30),
        id="academic_calendar_update",
        name="Akademik Takvim Yıllık Güncelleme",
        replace_existing=True,
        misfire_grace_time=86400,
    )

    # 5. Birim yönetimi: Dönem başlarında (1 Şubat ve 1 Eylül, 02:30)
    scheduler.add_job(
        job_unit_management_update,
        trigger=CronTrigger(
            month=UNIT_MANAGEMENT_UPDATE_MONTHS,
            day=UNIT_MANAGEMENT_UPDATE_DAY,
            hour=UNIT_MANAGEMENT_UPDATE_HOUR,
            minute=UNIT_MANAGEMENT_UPDATE_MINUTE,
        ),
        id="unit_management_update",
        name="Birim Yönetim Dönem Başı Güncelleme",
        replace_existing=True,
        misfire_grace_time=14400,
    )

    # 6. İdari personel: Dönem başlarında (1 Şubat ve 1 Eylül, 02:45)
    scheduler.add_job(
        job_administrative_staff_update,
        trigger=CronTrigger(
            month=ADMINISTRATIVE_STAFF_UPDATE_MONTHS,
            day=ADMINISTRATIVE_STAFF_UPDATE_DAY,
            hour=ADMINISTRATIVE_STAFF_UPDATE_HOUR,
            minute=ADMINISTRATIVE_STAFF_UPDATE_MINUTE,
        ),
        id="administrative_staff_update",
        name="İdari Birim/Personel Dönem Başı Güncelleme",
        replace_existing=True,
        misfire_grace_time=14400,
    )

    # 7. Akademik kadro: Dönem başlarında (1 Şubat ve 1 Eylül, 03:00)
    scheduler.add_job(
        job_kadro_update,
        trigger=CronTrigger(
            month=KADRO_UPDATE_MONTHS,
            day=KADRO_UPDATE_DAY,
            hour=KADRO_UPDATE_HOUR,
            minute=KADRO_UPDATE_MINUTE,
        ),
        id="kadro_update",
        name="Akademik Kadro Dönem Başı Güncelleme",
        replace_existing=True,
        misfire_grace_time=14400,  # 4 saat tolerance
    )

    # 8. Aday öğrenci portalı: Dönem başlarında (1 Şubat ve 1 Eylül, 04:00)
    scheduler.add_job(
        job_candidate_portal_update,
        trigger=CronTrigger(month="2,9", day=1, hour=4, minute=0),
        id="candidate_portal_update",
        name="Aday Öğrenci Portalı Dönemlik Güncelleme",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # 9. Tam yeniden indeksleme: Ayda 1 kez (ayın 1'i, 02:00)
    scheduler.add_job(
        job_full_reindex,
        trigger=CronTrigger(day=1, hour=2, minute=0),
        id="full_reindex",
        name="Aylık Tam Yeniden İndeksleme",
        replace_existing=True,
        misfire_grace_time=14400,  # 4 saat tolerance
    )

    return scheduler


def list_jobs(scheduler=None):
    """Tanımlı job'ları listeler."""
    print("\n" + "=" * 65)
    print("📋 ZAMANLANMIŞ GÖREVLER")
    print("=" * 65)

    jobs_info = [
        {"id": "duyuru_update", "name": "Duyuru Güncelleme",
         "schedule": "Her gün 08:00", "mode": "delta (3 sayfa)"},
        {"id": "department_announcement_staging", "name": "Bölüm Duyuruları",
         "schedule": "Her Pazartesi 08:30", "mode": "mühendislik duyuruları staging/onay"},
        {"id": "yemek_update", "name": "Yemekhane Menü",
         "schedule": "Her gün 07:00", "mode": "food_menus upsert"},
        {"id": "academic_calendar_update", "name": "Akademik Takvim",
         "schedule": "Her yıl 1 Eylül 05:30", "mode": "ana URL hash kontrolü + değişen kaynak parse"},
        {"id": "unit_management_update", "name": "Birim Yönetim",
         "schedule": "1 Şubat ve 1 Eylül 02:30", "mode": "GİBTÜ BirimYonetim allowlist DB-first"},
        {"id": "administrative_staff_update", "name": "İdari Birim/Personel",
         "schedule": "1 Şubat ve 1 Eylül 02:45", "mode": "GİBTÜ idari birim/personel allowlist DB-first"},
        {"id": "kadro_update", "name": "Akademik Kadro",
         "schedule": "1 Şubat ve 1 Eylül 03:00", "mode": "YÖK Akademik filtered bölüm/program staff"},
        {"id": "candidate_portal_update", "name": "Aday Öğrenci Portalı",
         "schedule": "1 Şubat ve 1 Eylül 04:00", "mode": "dönemlik tek sayfa scrape"},
        {"id": "full_reindex", "name": "Tam Yeniden İndeks",
         "schedule": "Her ayın 1'i 02:00", "mode": "full (tüm kaynaklar)"},
    ]

    for job in jobs_info:
        print(f"\n  🕐 {job['name']} [{job['id']}]")
        print(f"     Zamanlama: {job['schedule']}")
        print(f"     Mod:       {job['mode']}")

    if scheduler:
        print(f"\n  Aktif job sayısı: {len(scheduler.get_jobs())}")
        for job in scheduler.get_jobs():
            print(f"    → {job.id}: sonraki çalışma = {job.next_run_time}")

    # Son logları göster
    if LOG_FILE.exists():
        try:
            logs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            if logs:
                print(f"\n  📜 Son {min(5, len(logs))} çalışma:")
                for entry in logs[-5:]:
                    status = "✅" if entry.get("success") else "❌"
                    print(f"     {status} {entry.get('job', '?')} — "
                          f"{entry.get('timestamp', '?')[:19]} "
                          f"({entry.get('duration_seconds', '?')}s)")
        except Exception:
            pass

    print("\n" + "=" * 65)


def run_job_now(job_name: str):
    """Belirli bir job'ı hemen çalıştırır."""
    if job_name not in JOB_RUNNERS:
        logger.error("Bilinmeyen job: %s. Geçerli: %s", job_name, ", ".join(JOB_RUNNERS.keys()))
        return

    logger.info("⚡ Job hemen çalıştırılıyor: %s", job_name)
    JOB_RUNNERS[job_name]()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniChat Periyodik Güncelleme Zamanlayıcı (Faz 4.4)",
    )
    parser.add_argument("--list", action="store_true",
                        help="Tanımlı job'ları listele")
    parser.add_argument("--run-now", type=str, default=None,
                        help="Job'ı hemen çalıştır (duyuru/bolum_duyuru/yemek/akademik_takvim/yonetim/idari_personel/kadro/aday_ogrenci/full_reindex)")
    parser.add_argument("--start", action="store_true",
                        help="Scheduler'ı başlat (arka planda çalışır)")
    args = parser.parse_args()

    if args.list:
        list_jobs()
        return

    if args.run_now:
        run_job_now(args.run_now)
        return

    if args.start or (not args.list and not args.run_now):
        # PID kontrolü
        if not _acquire_pid_lock():
            sys.exit(1)

        atexit.register(_release_pid_lock)

        # Graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Shutdown sinyali alındı, scheduler durduruluyor...")
            _release_pid_lock()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        # Scheduler oluştur ve başlat
        scheduler = create_scheduler()

        logger.info("=" * 65)
        logger.info("🚀 UniChat Scheduler başlatılıyor...")
        logger.info("   PID: %d", os.getpid())
        logger.info("   Timezone: Europe/Istanbul")
        logger.info("   Job sayısı: %d", len(scheduler.get_jobs()))
        logger.info("=" * 65)

        list_jobs(scheduler)

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler durduruldu.")
        finally:
            _release_pid_lock()


if __name__ == "__main__":
    main()
