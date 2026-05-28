"""
UniChat Backend — Yemekhane Menü Repository
food_menus tablosu için tarih bazlı okuma ve upsert işlemleri.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.config import get_settings

logger = logging.getLogger(__name__)


def _json_dumps(value: Any) -> str:
    """JSONB alanlarına Türkçe karakterleri bozmadan değer hazırlar."""
    return json.dumps(value, ensure_ascii=False)


def _normalize_date(value: date | datetime | str) -> date:
    """Repository girişindeki tarih değerini date nesnesine çevirir."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Desteklenmeyen tarih tipi: {type(value).__name__}")


def _decode_json(value: Any) -> Any:
    """psycopg2 ayarına göre string gelebilen JSONB değerlerini çözer."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Veritabanı satırını servis katmanının beklediği sözlüğe dönüştürür."""
    if row is None:
        return None

    menu_date = row.get("date")
    return {
        "id": str(row.get("id")) if row.get("id") is not None else None,
        "date": menu_date.isoformat() if hasattr(menu_date, "isoformat") else str(menu_date),
        "menu_items": _decode_json(row.get("menu_items")) or [],
        "source_url": row.get("source_url"),
        "raw_text": row.get("raw_text"),
        "raw_data": _decode_json(row.get("raw_data")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


class FoodMenuRepository:
    """food_menus tablosuna erişen küçük ve izole repository."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def find_menu_by_date(self, menu_date: date | datetime | str) -> dict[str, Any] | None:
        """Tek tarih için menü kaydını döndürür."""
        normalized_date = _normalize_date(menu_date)
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, date, menu_items, source_url, raw_text, raw_data, created_at, updated_at
                    FROM food_menus
                    WHERE date = %s
                    """,
                    (normalized_date,),
                )
                return _row_to_dict(cur.fetchone())

    def get_menus_by_date_range(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict[str, Any]]:
        """Verilen tarih aralığındaki menüleri tarih sırasıyla döndürür."""
        normalized_start = _normalize_date(start_date)
        normalized_end = _normalize_date(end_date)
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, date, menu_items, source_url, raw_text, raw_data, created_at, updated_at
                    FROM food_menus
                    WHERE date BETWEEN %s AND %s
                    ORDER BY date ASC
                    """,
                    (normalized_start, normalized_end),
                )
                return [row for row in (_row_to_dict(r) for r in cur.fetchall()) if row]

    def upsert_menu(
        self,
        menu_date: date | datetime | str,
        menu_items: list[str],
        source_url: str,
        raw_data: dict[str, Any] | None = None,
        raw_text: str | None = None,
    ) -> dict[str, Any]:
        """Aynı tarih için duplicate oluşturmadan menüyü ekler veya günceller."""
        normalized_date = _normalize_date(menu_date)
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO food_menus (date, menu_items, source_url, raw_text, raw_data)
                    VALUES (%s, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (date) DO UPDATE SET
                        menu_items = EXCLUDED.menu_items,
                        source_url = EXCLUDED.source_url,
                        raw_text = EXCLUDED.raw_text,
                        raw_data = EXCLUDED.raw_data,
                        updated_at = NOW()
                    RETURNING id, date, menu_items, source_url, raw_text, raw_data, created_at, updated_at
                    """,
                    (
                        normalized_date,
                        Json(menu_items, dumps=_json_dumps),
                        source_url,
                        raw_text,
                        Json(raw_data or {}, dumps=_json_dumps),
                    ),
                )
                row = _row_to_dict(cur.fetchone())
                conn.commit()
                if row is None:
                    raise RuntimeError("Yemekhane menüsü upsert sonrası kayıt döndürmedi.")
                return row
