"""
UniChat — Faz 4.4: APScheduler ile Periyodik Güncelleme Zamanlayıcı

Tüm scraper modüllerini periyodik olarak çalıştıran merkezi zamanlayıcı.

Job Tanımları:
  - Duyurular:            Günde 1 kez (saat 08:00)
  - Yemekhane menüsü:     Günde 1 kez (saat 07:00)
  - Akademik kadro:       Haftada 1 kez (Pazartesi 03:00)
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
    python -m scrapers.scheduler --run-now yemek
    python -m scrapers.scheduler --run-now kadro
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


def job_yemek_update():
    """Yemekhane menü güncelleme job'ı."""
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
            "✅ Job tamamlandı: %s — değişti: %s, %d öğe, %.1fs",
            job_name, result.content_changed, result.menu_items_count, duration,
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
    """Akademik kadro güncelleme job'ı (haftalık)."""
    start = time.time()
    job_name = "kadro_update"
    logger.info("👥 Job başlıyor: %s", job_name)

    try:
        from scrapers.staff_scraper import StaffScraper

        scraper = StaffScraper()
        result = scraper.scrape(dry_run=False, force=False)

        duration = time.time() - start
        _append_job_log({
            "job": job_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": result.success,
            "new_documents": result.new_documents,
            "chunks": result.chunks_written,
            "duration_seconds": round(duration, 1),
        })

        logger.info(
            "✅ Job tamamlandı: %s — %d yeni, %d chunk, %.1fs",
            job_name, result.new_documents, result.chunks_written, duration,
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

        # Kadro force güncelle
        from scrapers.staff_scraper import StaffScraper
        staff_scraper = StaffScraper()
        staff_result = staff_scraper.scrape(dry_run=False, force=True)

        duration = time.time() - start
        total_docs = (
            ann_result.documents_created
            + menu_result.documents_created
            + staff_result.new_documents
        )
        total_chunks = (
            ann_result.chunks_written
            + menu_result.chunks_written
            + staff_result.chunks_written
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
                "kadro": {"new": staff_result.new_documents, "chunks": staff_result.chunks_written},
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

    # 2. Yemekhane: Günde 1 kez (07:00)
    scheduler.add_job(
        job_yemek_update,
        trigger=CronTrigger(hour=7, minute=0),
        id="yemek_update",
        name="Yemekhane Menü Güncelleme",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 3. Akademik kadro: Haftada 1 kez (Pazartesi 03:00)
    scheduler.add_job(
        job_kadro_update,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="kadro_update",
        name="Akademik Kadro Haftalık Güncelleme",
        replace_existing=True,
        misfire_grace_time=7200,  # 2 saat tolerance
    )

    # 4. Tam yeniden indeksleme: Ayda 1 kez (ayın 1'i, 02:00)
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
        {"id": "yemek_update", "name": "Yemekhane Menü",
         "schedule": "Her gün 07:00", "mode": "diff kontrolü ile"},
        {"id": "kadro_update", "name": "Akademik Kadro",
         "schedule": "Her Pazartesi 03:00", "mode": "yeni eklenenler"},
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
    job_map = {
        "duyuru": job_duyuru_update,
        "yemek": job_yemek_update,
        "kadro": job_kadro_update,
        "full_reindex": job_full_reindex,
    }

    if job_name not in job_map:
        logger.error("Bilinmeyen job: %s. Geçerli: %s", job_name, ", ".join(job_map.keys()))
        return

    logger.info("⚡ Job hemen çalıştırılıyor: %s", job_name)
    job_map[job_name]()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniChat Periyodik Güncelleme Zamanlayıcı (Faz 4.4)",
    )
    parser.add_argument("--list", action="store_true",
                        help="Tanımlı job'ları listele")
    parser.add_argument("--run-now", type=str, default=None,
                        help="Job'ı hemen çalıştır (duyuru/yemek/kadro/full_reindex)")
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
