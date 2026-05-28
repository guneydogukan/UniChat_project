"""
UniChat Backend — Yemekhane Menü API Router
/api/yemek-menu endpoint'i.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.services.food_menu_service import get_food_menu_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["yemek-menu"])


@router.get("/yemek-menu")
async def get_yemek_menu(
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    startDate: str | None = Query(default=None, description="YYYY-MM-DD"),
    endDate: str | None = Query(default=None, description="YYYY-MM-DD"),
):
    """Tek tarih veya tarih aralığı için yemekhane menüsünü döndürür."""
    if (startDate and not endDate) or (endDate and not startDate):
        raise HTTPException(
            status_code=400,
            detail="startDate ve endDate birlikte gönderilmelidir.",
        )
    if date and (startDate or endDate):
        raise HTTPException(
            status_code=400,
            detail="date ile startDate/endDate aynı istekte birlikte kullanılamaz.",
        )

    service = get_food_menu_service()
    try:
        if startDate and endDate:
            return service.get_menus_by_date_range(startDate, endDate)
        return service.get_menu_by_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Yemekhane menüsü API hatası: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Yemek menüsüne şu anda ulaşılamıyor. Lütfen daha sonra tekrar deneyiniz.",
        ) from exc
