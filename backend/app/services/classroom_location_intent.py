"""Derslik/sınıf konum sorguları için deterministik intent ayrıştırma."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


ROOM_CODE_RE = re.compile(r"(?<![a-z0-9])(?P<room>z\s*-?\s*\d{2,3}|\d{2,3})(?![a-z0-9])", re.IGNORECASE)
COMPACT_Z_ROOM_RE = re.compile(r"(?<![a-z0-9])(?P<room>z\d{2,3})(?![a-z0-9])", re.IGNORECASE)

CLASSROOM_SIGNAL_RE = re.compile(
    r"\b("
    r"derslik\w*|sınıf\w*|sinif\w*|amfi\w*|laboratuvar\w*|lab\b|"
    r"konferans\s+salon\w*|oda\w*|nolu|numaralı|numarali|"
    r"hangi\s+kat\w*|katta|nerede|nereye|nasıl\s+gider\w*|nasil\s+gider\w*|"
    r"bina\w*|fakülte\w*|fakulte\w*|mdbf"
    r")\b",
    re.IGNORECASE,
)

LIST_SIGNAL_RE = re.compile(r"\b(derslikleri|sınıfları|siniflari|laboratuvarları|laboratuvarlari|listele\w*|hangi)\b", re.IGNORECASE)
FLOOR_SIGNAL_RE = re.compile(r"\b(hangi\s+kat\w*|katta|katı|kati)\b", re.IGNORECASE)
DIRECTION_SIGNAL_RE = re.compile(r"\b(nasıl\s+gider\w*|nasil\s+gider\w*|nereden\s+gid\w*)\b", re.IGNORECASE)
SPACE_SIGNAL_RE = re.compile(
    r"\b("
    r"idari\s+ofis\w*|öğrenci\s+iş\w*|ogrenci\s+is\w*|"
    r"fakülte\s+sekreterliğ\w*|fakulte\s+sekreterlig\w*|sekreterlik\w*|"
    r"dekanlık\w*|dekanlik\w*|dekan\s+yardımc\w*|dekan\s+yardimc\w*|dekan\w*|"
    r"bölüm\s+başkanlığ\w*|bolum\s+baskanlig\w*|"
    r"akademik\s+personel\s+oda\w*"
    r")\b",
    re.IGNORECASE,
)
LOCATION_SIGNAL_RE = re.compile(
    r"\b(nerede|nereye|hangi\s+kat\w*|katta|nasıl\s+gider\w*|nasil\s+gider\w*|konum\w*)\b",
    re.IGNORECASE,
)

ROOM_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Konferans Salonu", ("konferans salonu", "konferans")),
    ("Laboratuvar", ("laboratuvar", "lab")),
    ("Amfi", ("amfi",)),
    ("Derslik", ("derslik", "sınıf", "sinif")),
)

DEPARTMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "BM": ("bm", "bilgisayar mühendisliği", "bilgisayar muhendisligi", "bilgisayar"),
    "BP": ("bp", "bilgisayar programcılığı", "bilgisayar programciligi"),
    "EEM": (
        "eem",
        "elektrik elektronik mühendisliği",
        "elektrik elektronik muhendisligi",
        "elektrik elektronik",
    ),
}


@dataclass(frozen=True)
class ClassroomLocationRequest:
    is_classroom_query: bool
    normalized_query: str = ""
    room_code: str | None = None
    space_query: str | None = None
    department_code: str | None = None
    room_type: str | None = None
    wants_list: bool = False
    wants_floor: bool = False
    wants_directions: bool = False


def normalize_for_match(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value.casefold().replace("\xa0", " "))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_room_code(value: str | None) -> str | None:
    if not value:
        return None
    text = value.casefold().replace("\xa0", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text.strip())
    text = re.sub(r"^z[-]?(\d{2,3})$", r"z-\1", text)
    text = re.sub(r"^([a-z])[-]?(\d{2,3})$", r"\1-\2", text)
    return text


def extract_classroom_location_request(query: str) -> ClassroomLocationRequest:
    normalized_query = normalize_for_match(query)
    room_code = _extract_room_code(query)
    space_query = _extract_space_query(normalized_query)
    department_code = _extract_department_code(normalized_query)
    room_type = _extract_room_type(normalized_query)
    has_classroom_signal = bool(CLASSROOM_SIGNAL_RE.search(query) or CLASSROOM_SIGNAL_RE.search(normalized_query))
    has_location_signal = bool(LOCATION_SIGNAL_RE.search(query) or LOCATION_SIGNAL_RE.search(normalized_query))
    wants_list = bool(LIST_SIGNAL_RE.search(query) or LIST_SIGNAL_RE.search(normalized_query))
    wants_floor = bool(FLOOR_SIGNAL_RE.search(query) or FLOOR_SIGNAL_RE.search(normalized_query))
    wants_directions = bool(DIRECTION_SIGNAL_RE.search(query) or DIRECTION_SIGNAL_RE.search(normalized_query))

    is_classroom_query = False
    if room_code and (has_classroom_signal or department_code or _has_building_signal(normalized_query)):
        is_classroom_query = True
    elif space_query and has_location_signal:
        is_classroom_query = True
    elif wants_list and has_classroom_signal and department_code and room_type:
        is_classroom_query = True

    return ClassroomLocationRequest(
        is_classroom_query=is_classroom_query,
        normalized_query=normalized_query,
        room_code=room_code,
        space_query=space_query,
        department_code=department_code,
        room_type=room_type,
        wants_list=wants_list,
        wants_floor=wants_floor,
        wants_directions=wants_directions,
    )


def _extract_room_code(query: str) -> str | None:
    match = COMPACT_Z_ROOM_RE.search(query) or ROOM_CODE_RE.search(query)
    if not match:
        return None
    return normalize_room_code(match.group("room"))


def _extract_department_code(normalized_query: str) -> str | None:
    tokens = set(normalized_query.split())
    for code, aliases in DEPARTMENT_ALIASES.items():
        normalized_aliases = [normalize_for_match(alias) for alias in aliases]
        if code.casefold() in tokens:
            return code
        for alias in normalized_aliases:
            if " " in alias and alias in normalized_query:
                return code
            if alias in tokens:
                return code
    return None


def _extract_space_query(normalized_query: str) -> str | None:
    if re.search(r"\bogrenci\s+is\w*", normalized_query):
        return "ogrenci isleri"
    if re.search(r"\bfakulte\s+sekreterlig\w*|\bsekreterlik\w*", normalized_query):
        return "fakulte sekreterligi"
    if re.search(r"\bdekan\s+yardimc\w*", normalized_query):
        return "dekan yardimcisi"
    if re.search(r"\bdekanlik\w*|\bdekan\w*", normalized_query):
        return "dekanlik"
    if re.search(r"\bbolum\s+baskanlig\w*", normalized_query):
        return "bolum baskanligi"
    if re.search(r"\bakademik\s+personel\s+oda\w*", normalized_query):
        return "akademik personel odalari"
    if re.search(r"\bidari\s+ofis\w*", normalized_query):
        return "idari ofis"
    return None


def _extract_room_type(normalized_query: str) -> str | None:
    for display, aliases in ROOM_TYPE_RULES:
        if any(normalize_for_match(alias) in normalized_query for alias in aliases):
            return display
    return None


def _has_building_signal(normalized_query: str) -> bool:
    return any(
        token in normalized_query
        for token in (
            "mdbf",
            "muhendislik",
            "fakulte",
            "bina",
            "doga bilimleri",
            "idari ofis",
        )
    )


__all__ = [
    "ClassroomLocationRequest",
    "extract_classroom_location_request",
    "normalize_for_match",
    "normalize_room_code",
]
