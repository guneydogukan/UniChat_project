"""Derslik/idari alan konum DB-first repository katmanı.

Bu repository yalnız normalize `classrooms`, `campus_spaces` ve `campus_buildings`
tablolarından okuma yapar; ingestion veya migration çalıştırmaz.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import get_settings


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _row_to_classroom(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if result.get("id") is not None:
        result["id"] = str(result["id"])
    return result


def _row_to_building(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if result.get("id") is not None:
        result["id"] = str(result["id"])
    result["aliases"] = _decode_json(result.get("aliases")) or []
    result["normalized_aliases"] = _decode_json(result.get("normalized_aliases")) or []
    return result


def _row_to_space(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if result.get("id") is not None:
        result["id"] = str(result["id"])
    result["aliases"] = _decode_json(result.get("aliases")) or []
    result["normalized_aliases"] = _decode_json(result.get("normalized_aliases")) or []
    return result


class ClassroomRepository:
    """Derslik ve kampüs alanı konum tabloları için read-only repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or get_settings().DATABASE_URL

    def _connect_readonly(self):
        conn = psycopg2.connect(self._database_url)
        conn.set_session(readonly=True, autocommit=True)
        return conn

    def list_buildings(self) -> list[dict[str, Any]]:
        """Kayıtlı binaları ve alias listelerini döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, building_name, normalized_building_name, aliases,
                           normalized_aliases, source_file, created_at, updated_at
                    FROM campus_buildings
                    ORDER BY building_name
                    """
                )
                return [
                    building
                    for row in cur.fetchall()
                    if (building := _row_to_building(row)) is not None
                ]

    def find_by_room_code(self, normalized_room_code: str) -> list[dict[str, Any]]:
        """Oda koduna göre exact match derslik kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM classrooms
                    WHERE normalized_room_code = %s
                    ORDER BY building_name, department_code NULLS LAST, room_code
                    """,
                    (normalized_room_code,),
                )
                return [
                    classroom
                    for row in cur.fetchall()
                    if (classroom := _row_to_classroom(row)) is not None
                ]

    def find_by_room_and_building(
        self,
        normalized_room_code: str,
        normalized_building_name: str,
    ) -> list[dict[str, Any]]:
        """Exact oda kodu + exact normalize bina adı ile kayıt döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM classrooms
                    WHERE normalized_room_code = %s
                      AND normalized_building_name = %s
                    ORDER BY department_code NULLS LAST, room_code
                    """,
                    (normalized_room_code, normalized_building_name),
                )
                return [
                    classroom
                    for row in cur.fetchall()
                    if (classroom := _row_to_classroom(row)) is not None
                ]

    def find_by_department_and_room(
        self,
        department_code: str,
        normalized_room_code: str,
    ) -> list[dict[str, Any]]:
        """Exact bölüm kodu + exact oda kodu ile kayıt döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM classrooms
                    WHERE department_code = %s
                      AND normalized_room_code = %s
                    ORDER BY building_name, room_code
                    """,
                    (department_code.upper(), normalized_room_code),
                )
                return [
                    classroom
                    for row in cur.fetchall()
                    if (classroom := _row_to_classroom(row)) is not None
                ]

    def list_by_department(self, department_code: str) -> list[dict[str, Any]]:
        """Bölüm koduna göre derslikleri listeler."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM classrooms
                    WHERE department_code = %s
                    ORDER BY building_name, normalized_room_code
                    """,
                    (department_code.upper(),),
                )
                return [
                    classroom
                    for row in cur.fetchall()
                    if (classroom := _row_to_classroom(row)) is not None
                ]

    def list_spaces(self) -> list[dict[str, Any]]:
        """Oda numarası olmayan idari/ortak alan konum kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM campus_spaces
                    ORDER BY building_name, floor_label, space_name
                    """
                )
                return [
                    space
                    for row in cur.fetchall()
                    if (space := _row_to_space(row)) is not None
                ]

    def find_spaces_by_building(self, normalized_building_name: str) -> list[dict[str, Any]]:
        """Normalize bina adına göre idari/ortak alan kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM campus_spaces
                    WHERE normalized_building_name = %s
                    ORDER BY floor_label, space_name
                    """,
                    (normalized_building_name,),
                )
                return [
                    space
                    for row in cur.fetchall()
                    if (space := _row_to_space(row)) is not None
                ]

    def find_spaces_by_department(self, department_code: str) -> list[dict[str, Any]]:
        """Bölüm koduna göre idari/ortak alan kayıtlarını döndürür."""
        with self._connect_readonly() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM campus_spaces
                    WHERE department_code = %s
                    ORDER BY building_name, floor_label, space_name
                    """,
                    (department_code.upper(),),
                )
                return [
                    space
                    for row in cur.fetchall()
                    if (space := _row_to_space(row)) is not None
                ]


__all__ = ["ClassroomRepository"]
