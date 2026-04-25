"""
Gorev 3.5 P4 — Duyuru Arsivi Periyodik Guncelleme Wrapper

Delta modu ile mevcut run_duyuru_scrape.py'yi cagirir.
Cron/scheduler ile periyodik calistirma icin tasarlandi.

Kullanim:
    python run_duyuru_update.py                # delta modu (son 3 sayfa)
    python run_duyuru_update.py --full          # tam tarama (son 15 sayfa)
    python run_duyuru_update.py --dry-run       # DB'ye yazmadan test

Periyodik calistirma (cron ornegi):
    # Her 6 saatte bir delta guncelleme
    0 */6 * * * cd /path/to/backend && python run_duyuru_update.py

Guvenlik:
    - PID kilidi: ayni anda birden fazla calismayi engeller
    - Timeout: her istek icin 20s sinir
    - Hata yakalama: yanit vermeyen sayfalar atlanir
"""
import sys
import json
import os
import logging
import tempfile
import atexit
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"
LOCK_FILE = OUTPUT_DIR / ".duyuru_update.lock"
LOG_FILE = OUTPUT_DIR / "duyuru_update_log.json"


def _acquire_lock() -> bool:
    """PID tabanli dosya kilidi. Ayni anda birden fazla calismayi engeller."""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            # PID hala aktif mi kontrol et
            try:
                os.kill(old_pid, 0)
                logger.error(
                    "Baska bir duyuru guncelleme islemi zaten calisiyor (PID=%d). Cikiliyor.",
                    old_pid,
                )
                return False
            except OSError:
                # PID artik yok, eski lock — temizle
                logger.warning("Eski lock dosyasi temizleniyor (PID=%d artik yok)", old_pid)
                LOCK_FILE.unlink(missing_ok=True)
        except (ValueError, IOError):
            LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock():
    """Lock dosyasini sil."""
    LOCK_FILE.unlink(missing_ok=True)


def _append_log(entry: dict):
    """Guncelleme loguna yeni kayit ekle."""
    logs = []
    if LOG_FILE.exists():
        try:
            logs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            logs = []

    logs.append(entry)

    # Son 100 kaydi tut
    if len(logs) > 100:
        logs = logs[-100:]

    LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Duyuru Arsivi Periyodik Guncelleme (Delta Wrapper)"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Tam tarama modu (15 sayfa). Varsayilan: delta (3 sayfa)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DB'ye yazmadan test calistirmasi"
    )
    args = parser.parse_args()

    mode = "full" if args.full else "delta"
    start_time = datetime.now()

    logger.info("=" * 65)
    logger.info("DUYURU GUNCELLEME BASLATILIYOR — mod: %s", mode.upper())
    logger.info("Zaman: %s", start_time.isoformat())
    logger.info("=" * 65)

    # PID kilidi al
    if not _acquire_lock():
        return 1

    atexit.register(_release_lock)

    try:
        # run_duyuru_scrape.py'yi subprocess olarak calistir
        import subprocess

        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "run_duyuru_scrape.py"),
            "--mode", mode,
        ]
        if args.dry_run:
            cmd.append("--dry-run")

        logger.info("Komut: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            capture_output=False,
            timeout=1800,  # 30 dakika max
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        success = result.returncode == 0

        # Log kaydi
        log_entry = {
            "timestamp": start_time.isoformat(),
            "mode": mode,
            "dry_run": args.dry_run,
            "duration_seconds": round(duration, 1),
            "return_code": result.returncode,
            "success": success,
        }
        _append_log(log_entry)

        logger.info("\n" + "=" * 65)
        status = "BASARILI" if success else "BASARISIZ"
        logger.info("DUYURU GUNCELLEME %s — sure: %.1f sn", status, duration)
        logger.info("=" * 65)

        return result.returncode

    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT: Duyuru guncelleme 30 dakikayi asti!")
        _append_log({
            "timestamp": start_time.isoformat(),
            "mode": mode,
            "error": "TIMEOUT (30 dakika)",
            "success": False,
        })
        return 1

    except Exception as e:
        logger.error("Beklenmeyen hata: %s", e)
        _append_log({
            "timestamp": start_time.isoformat(),
            "mode": mode,
            "error": str(e),
            "success": False,
        })
        return 1

    finally:
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
