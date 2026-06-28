"""
Mühendislik bölüm duyuruları admin API router'ı.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.services.department_announcement_service import get_department_announcement_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/department-announcements", tags=["department-announcements"])


@router.get("/status")
async def get_department_announcement_status():
    """Duyuru DB şeması ve onaylı veri durumunu raporlar."""
    return get_department_announcement_service().get_status()


@router.post("/scrape")
async def scrape_department_announcements():
    """Aktif bölüm duyuru kaynaklarını scrape edip staging'e alır."""
    try:
        return get_department_announcement_service().scrape_to_staging()
    except Exception as exc:  # noqa: BLE001
        logger.error("Bölüm duyurusu scrape API hatası: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Bölüm duyuruları şu anda staging'e alınamadı.",
        ) from exc


@router.get("/staging")
async def list_department_announcement_staging(
    status: str | None = Query(default=None, description="pending/approved/rejected"),
    runId: str | None = Query(default=None, description="Scrape run id"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Staging kayıtlarını listeler."""
    try:
        return get_department_announcement_service().list_staging(
            status=status,
            scrape_run_id=runId,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Bölüm duyurusu staging listeleme hatası: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Staging kayıtları okunamadı.") from exc


@router.post("/staging/{staging_id}/approve")
async def approve_department_announcement_staging(
    staging_id: str,
    reviewedBy: str | None = Query(default=None),
    note: str | None = Query(default=None),
):
    """Tek staging duyurusunu production tablosuna onaylar."""
    try:
        return get_department_announcement_service().approve_staging(
            staging_id,
            reviewed_by=reviewedBy,
            review_note=note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Bölüm duyurusu onay hatası: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Duyuru onaylanamadı.") from exc


@router.post("/staging/{staging_id}/reject")
async def reject_department_announcement_staging(
    staging_id: str,
    reviewedBy: str | None = Query(default=None),
    note: str | None = Query(default=None),
):
    """Tek staging duyurusunu reddeder."""
    try:
        return get_department_announcement_service().reject_staging(
            staging_id,
            reviewed_by=reviewedBy,
            review_note=note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Bölüm duyurusu red hatası: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Duyuru reddedilemedi.") from exc


@router.post("/runs/{run_id}/approve")
async def approve_department_announcement_run(
    run_id: str,
    reviewedBy: str | None = Query(default=None),
    note: str | None = Query(default=None),
):
    """Aynı run'daki valid pending kayıtları toplu onaylar."""
    try:
        return get_department_announcement_service().approve_run(
            run_id,
            reviewed_by=reviewedBy,
            review_note=note,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Bölüm duyurusu toplu onay hatası: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Run kayıtları toplu onaylanamadı.") from exc
