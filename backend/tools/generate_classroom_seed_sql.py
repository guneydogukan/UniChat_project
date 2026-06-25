"""Derslikler.xlsx dosyasından normalize classroom/space seed SQL üretir.

Bu script RAG dokümanı oluşturmaz; Excel'i yalnız yapılandırılmış
`classrooms`, `campus_spaces` ve `campus_buildings` DB seed verisine dönüştürür.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

DEFAULT_SOURCE_FILE = "Derslikler.xlsx"

DEFAULT_BUILDING_ALIASES: dict[str, tuple[str, ...]] = {
    "muhendislik ve doga bilimleri fakultesi": (
        "Mühendislik ve Doğa Bilimleri Fakültesi",
        "Mühendislik Fakültesi",
        "Mühendislik Binası",
        "Mühendislik",
        "MDBF",
        "M.D.B.F.",
        "Mühendislik ve Doğa Bilimleri",
        "Mühendislik ve Doğa Bilimleri Fakültesi Binası",
    ),
}

SPACE_DEPARTMENT_CODE_HINTS: dict[str, str] = {
    "bilgisayar muhendisligi": "BM",
    "elektrik elektronik muhendisligi": "EEM",
    "radyo televizyon ve sinema": "RTV",
}

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "building": (
        "bina",
        "bina adi",
        "bina adı",
        "fakulte",
        "fakülte",
        "fakulte adi",
        "fakülte adı",
        "yer",
        "konum",
    ),
    "floor": (
        "kat",
        "kat bilgisi",
        "bulundugu kat",
        "bulunduğu kat",
        "floor",
    ),
    "room": (
        "derslik",
        "derslik adi",
        "derslik adı",
        "derslik no",
        "derslik numarasi",
        "derslik numarası",
        "oda",
        "oda no",
        "oda kodu",
        "sinif",
        "sınıf",
        "room",
        "room code",
    ),
    "room_type": (
        "tur",
        "tür",
        "derslik turu",
        "derslik türü",
        "oda tipi",
        "sinif turu",
        "sınıf türü",
        "tip",
    ),
    "capacity": (
        "kapasite",
        "kontenjan",
        "kisi sayisi",
        "kişi sayısı",
        "capacity",
    ),
    "department": (
        "bolum",
        "bölüm",
        "birim",
        "program",
        "kullanim",
        "kullanım",
        "birim kullanim",
        "birim kullanım",
        "departman",
        "department",
    ),
}

REQUIRED_COLUMNS = ("building", "floor", "room")


@dataclass(frozen=True)
class ClassroomRecord:
    building_name: str
    floor_label: str | None
    room_code: str
    room_type: str | None
    capacity: int | None
    department_name: str | None
    department_code: str | None
    is_shared: bool
    normalized_room_code: str
    normalized_building_name: str
    search_text: str
    source_file: str


@dataclass(frozen=True)
class CampusSpaceRecord:
    building_name: str
    floor_label: str | None
    space_name: str
    space_type: str | None
    department_name: str | None
    department_code: str | None
    aliases: list[str]
    normalized_space_name: str
    normalized_aliases: list[str]
    normalized_building_name: str
    search_text: str
    source_file: str


@dataclass(frozen=True)
class ClassroomSeedData:
    classrooms: list[ClassroomRecord]
    spaces: list[CampusSpaceRecord]


def normalize_for_match(value: Any) -> str:
    """Türkçe görüntü metnini bozmadan karşılaştırma anahtarı üretir."""
    if value is None:
        return ""
    text = str(value).casefold().replace("\xa0", " ")
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_room_code(value: Any) -> str:
    """Oda kodunu exact-match anahtarına çevirir; fuzzy eşleşme için kullanılmaz."""
    text = _cell_to_text(value).casefold()
    text = text.replace("\xa0", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text.strip())
    text = re.sub(r"^zemin[-]?(\d+)$", r"z-\1", text)
    text = re.sub(r"^z[-]?(\d+)$", r"z-\1", text)
    text = re.sub(r"^([a-z])[-]?(\d+)$", r"\1-\2", text)
    return text


def clean_floor_label(value: Any) -> str | None:
    text = _cell_to_text(value)
    if not text:
        return None
    normalized = normalize_for_match(text)
    if normalized in {"z", "zemin", "zemin kat", "giris", "giris kat", "0"}:
        return "Zemin"
    match = re.search(r"\b(\d+)\b", normalized)
    if match:
        return match.group(1)
    return text


def extract_department(value: Any) -> tuple[str | None, str | None, bool]:
    text = _cell_to_text(value)
    if not text:
        return None, None, False

    code: str | None = None
    match = re.search(r"\((.*?)\)", text)
    if match:
        code = match.group(1).strip() or None

    name = re.sub(r"\s*\(.*?\)\s*", " ", text).strip()
    name = re.sub(r"\s+", " ", name) or text
    is_shared = "ortak" in normalize_for_match(text)
    return name, code.upper() if code else None, is_shared


def infer_space_department_code(value: Any) -> str | None:
    normalized = normalize_for_match(value)
    for hint, code in SPACE_DEPARTMENT_CODE_HINTS.items():
        if hint in normalized:
            return code
    return None


def build_space_aliases(
    space_name: str,
    department_name: str | None = None,
    department_code: str | None = None,
) -> list[str]:
    """Oda numarası olmayan idari alanlar için deterministik alias üretir."""
    aliases: list[str] = [space_name]
    if department_name and department_name != space_name:
        aliases.append(department_name)

    normalized = normalize_for_match(space_name)
    if "," in space_name and "bolum baskanligi" not in normalized:
        aliases.extend(part.strip() for part in space_name.split(","))

    if "ogrenci isleri" in normalized:
        aliases.extend(["Öğrenci İşleri", "Öğrenci İşleri Ofisi"])
    if "fakulte sekreterligi" in normalized or "sekreterlik" in normalized:
        aliases.extend(["Fakülte Sekreterliği", "Sekreterlik"])
    if "dekan" in normalized:
        aliases.extend(["Dekanlık", "Dekan", "Dekan Yardımcılığı", "Dekan Yardımcısı"])
    if "akademik personel" in normalized:
        aliases.extend(["Akademik Personel Odaları", "Akademik Personel"])
    if "bolum baskanligi" in normalized:
        aliases.append("Bölüm Başkanlığı")
        if department_name:
            aliases.append(department_name)
        if department_code:
            aliases.extend([
                department_code.upper(),
                f"{department_code.upper()} Bölüm Başkanlığı",
            ])

    return _dedup_preserve_order(aliases)


def load_xlsx_rows(path: Path, sheet_name: str | None = None) -> list[list[str]]:
    """İlk veya adı verilen worksheet'i stdlib ile satır listesine çevirir."""
    with zipfile.ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        worksheet_path = _resolve_worksheet_path(archive, sheet_name)
        root = ET.fromstring(archive.read(worksheet_path))

    rows: list[list[str]] = []
    for row in root.findall(f".//{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row"):
        values_by_index: dict[int, str] = {}
        for cell in row.findall(f"{{{NS_MAIN}}}c"):
            ref = cell.attrib.get("r", "")
            column_index = _column_index_from_ref(ref)
            values_by_index[column_index] = _read_cell_value(cell, shared_strings)
        if values_by_index:
            max_index = max(values_by_index)
            rows.append([values_by_index.get(index, "") for index in range(max_index + 1)])
    return rows


def parse_seed_data_from_rows(rows: list[list[Any]], source_file: str = DEFAULT_SOURCE_FILE) -> ClassroomSeedData:
    header_index, column_map = _detect_header(rows)
    classrooms: list[ClassroomRecord] = []
    spaces: list[CampusSpaceRecord] = []
    for row in rows[header_index + 1:]:
        if not any(_cell_to_text(cell) for cell in row):
            continue

        building_name = _value_at(row, column_map["building"])
        if not building_name:
            continue

        room_code = _value_at(row, column_map["room"])
        floor_label = clean_floor_label(_value_at(row, column_map["floor"]))
        room_type = _optional_value(row, column_map.get("room_type"))
        department_value = _optional_value(row, column_map.get("department"))

        if not room_code:
            if _is_administrative_space(room_type, department_value):
                space_name = _cell_to_text(department_value)
                if not space_name:
                    continue
                department_name, department_code, _ = extract_department(space_name)
                if department_code is None:
                    department_code = infer_space_department_code(space_name)
                normalized_building_name = normalize_for_match(building_name)
                normalized_space_name = normalize_for_match(space_name)
                aliases = build_space_aliases(space_name, department_name, department_code)
                normalized_aliases = _dedup_preserve_order(
                    normalize_for_match(alias) for alias in aliases
                )
                search_text = " ".join(
                    part
                    for part in [
                        building_name,
                        floor_label,
                        space_name,
                        room_type,
                        department_name,
                        department_code,
                        " ".join(aliases),
                        normalized_building_name,
                        normalized_space_name,
                        " ".join(normalized_aliases),
                    ]
                    if part
                )

                spaces.append(
                    CampusSpaceRecord(
                        building_name=building_name,
                        floor_label=floor_label,
                        space_name=space_name,
                        space_type=room_type,
                        department_name=department_name,
                        department_code=department_code,
                        aliases=aliases,
                        normalized_space_name=normalized_space_name,
                        normalized_aliases=normalized_aliases,
                        normalized_building_name=normalized_building_name,
                        search_text=search_text,
                        source_file=source_file,
                    )
                )
            continue

        capacity = _parse_capacity(_optional_value(row, column_map.get("capacity")))
        department_name, department_code, is_shared = extract_department(department_value)
        normalized_building_name = normalize_for_match(building_name)
        normalized_room_code = normalize_room_code(room_code)
        search_text = " ".join(
            part
            for part in [
                building_name,
                floor_label,
                room_code,
                room_type,
                department_name,
                department_code,
                normalized_building_name,
                normalized_room_code,
            ]
            if part
        )

        classrooms.append(
            ClassroomRecord(
                building_name=building_name,
                floor_label=floor_label,
                room_code=room_code,
                room_type=room_type,
                capacity=capacity,
                department_name=department_name,
                department_code=department_code,
                is_shared=is_shared,
                normalized_room_code=normalized_room_code,
                normalized_building_name=normalized_building_name,
                search_text=search_text,
                source_file=source_file,
            )
        )
    return ClassroomSeedData(classrooms=classrooms, spaces=spaces)


def records_from_rows(rows: list[list[Any]], source_file: str = DEFAULT_SOURCE_FILE) -> list[ClassroomRecord]:
    return parse_seed_data_from_rows(rows, source_file).classrooms


def space_records_from_rows(rows: list[list[Any]], source_file: str = DEFAULT_SOURCE_FILE) -> list[CampusSpaceRecord]:
    return parse_seed_data_from_rows(rows, source_file).spaces


def generate_seed_sql(
    records: list[ClassroomRecord],
    source_file: str = DEFAULT_SOURCE_FILE,
    spaces: list[CampusSpaceRecord] | None = None,
) -> str:
    spaces = spaces or []
    buildings = _building_rows(records, spaces, source_file)
    lines = [
        "-- UniChat classroom seed SQL",
        "-- Bu dosya backend/tools/generate_classroom_seed_sql.py ile üretilir.",
        "BEGIN;",
        f"DELETE FROM campus_spaces WHERE source_file = {_sql_literal(source_file)};",
        f"DELETE FROM classrooms WHERE source_file = {_sql_literal(source_file)};",
        "",
    ]

    if buildings:
        lines.append(
            "INSERT INTO campus_buildings (building_name, normalized_building_name, aliases, normalized_aliases, source_file)"
        )
        lines.append("VALUES")
        lines.append(",\n".join(_building_sql_row(row) for row in buildings))
        lines.append(
            "ON CONFLICT (normalized_building_name) DO UPDATE SET\n"
            "    building_name = EXCLUDED.building_name,\n"
            "    aliases = EXCLUDED.aliases,\n"
            "    normalized_aliases = EXCLUDED.normalized_aliases,\n"
            "    source_file = EXCLUDED.source_file,\n"
            "    updated_at = NOW();"
        )
        lines.append("")

    if records:
        lines.append(
            "INSERT INTO classrooms ("
            "building_name, floor_label, room_code, room_type, capacity, "
            "department_name, department_code, is_shared, normalized_room_code, "
            "normalized_building_name, search_text, source_file"
            ")"
        )
        lines.append("VALUES")
        lines.append(",\n".join(_classroom_sql_row(record) for record in records))
        lines.append(";")
        lines.append("")

    if spaces:
        lines.append(
            "INSERT INTO campus_spaces ("
            "building_name, floor_label, space_name, space_type, department_name, "
            "department_code, aliases, normalized_space_name, normalized_aliases, "
            "normalized_building_name, search_text, source_file"
            ")"
        )
        lines.append("VALUES")
        lines.append(",\n".join(_space_sql_row(record) for record in spaces))
        lines.append(";")
        lines.append("")

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Derslikler.xlsx dosyasından classroom seed SQL üretir.")
    parser.add_argument("--input", required=True, help="Derslikler.xlsx dosya yolu")
    parser.add_argument("--output", required=True, help="Üretilecek SQL dosya yolu")
    parser.add_argument("--sheet", help="Okunacak sheet adı; verilmezse ilk sheet kullanılır")
    parser.add_argument("--source-file", default=DEFAULT_SOURCE_FILE, help="DB source_file değeri")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Excel dosyası bulunamadı: {input_path}")

    rows = load_xlsx_rows(input_path, args.sheet)
    seed_data = parse_seed_data_from_rows(rows, args.source_file)
    if not seed_data.classrooms and not seed_data.spaces:
        raise ValueError("Excel içinde derslik veya idari alan kaydı üretilemedi; kolon ve satırları kontrol edin.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        generate_seed_sql(seed_data.classrooms, args.source_file, seed_data.spaces),
        encoding="utf-8",
    )
    print(f"{len(seed_data.classrooms)} derslik, {len(seed_data.spaces)} idari alan kaydı yazıldı: {output_path}")


def _detect_header(rows: list[list[Any]]) -> tuple[int, dict[str, int]]:
    for row_index, row in enumerate(rows[:25]):
        normalized_headers = [normalize_for_match(cell) for cell in row]
        column_map: dict[str, int] = {}
        for key, aliases in HEADER_ALIASES.items():
            alias_set = {normalize_for_match(alias) for alias in aliases}
            for index, header in enumerate(normalized_headers):
                if header in alias_set:
                    column_map[key] = index
                    break
        if all(key in column_map for key in REQUIRED_COLUMNS):
            return row_index, column_map

    required = ", ".join(REQUIRED_COLUMNS)
    raise ValueError(f"Zorunlu derslik kolonları bulunamadı: {required}")


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall(f"{{{NS_MAIN}}}si"):
        text_parts = [node.text or "" for node in item.findall(f".//{{{NS_MAIN}}}t")]
        strings.append("".join(text_parts))
    return strings


def _resolve_worksheet_path(archive: zipfile.ZipFile, sheet_name: str | None) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall(f"{{{NS_PACKAGE_REL}}}Relationship")
    }
    sheets = workbook.findall(f".//{{{NS_MAIN}}}sheet")
    if not sheets:
        raise ValueError("Excel içinde worksheet bulunamadı.")

    selected = None
    for sheet in sheets:
        if sheet_name is None or sheet.attrib.get("name") == sheet_name:
            selected = sheet
            break
    if selected is None:
        names = ", ".join(sheet.attrib.get("name", "") for sheet in sheets)
        raise ValueError(f"Sheet bulunamadı: {sheet_name}. Mevcut sheetler: {names}")

    rel_id = selected.attrib.get(f"{{{NS_REL}}}id")
    target = rel_targets.get(rel_id)
    if not target:
        raise ValueError(f"Worksheet ilişki hedefi bulunamadı: {selected.attrib.get('name')}")
    return _normalize_xlsx_path(target)


def _normalize_xlsx_path(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{NS_MAIN}}}t")).strip()

    value_node = cell.find(f"{{{NS_MAIN}}}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except (IndexError, ValueError):
            return raw
    return _cell_to_text(raw)


def _column_index_from_ref(ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", ref.upper())
    if not letters:
        return 0
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return re.sub(r"\s+", " ", text)


def _value_at(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    return _cell_to_text(row[index])


def _optional_value(row: list[Any], index: int | None) -> str | None:
    if index is None:
        return None
    value = _value_at(row, index)
    return value or None


def _parse_capacity(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _is_administrative_space(room_type: str | None, department_value: str | None) -> bool:
    if not department_value:
        return False
    normalized_type = normalize_for_match(room_type)
    return "idari ofis" in normalized_type


def _building_rows(
    records: list[ClassroomRecord],
    spaces: list[CampusSpaceRecord],
    source_file: str,
) -> list[dict[str, Any]]:
    by_normalized: dict[str, str] = {}
    for record in records:
        by_normalized.setdefault(record.normalized_building_name, record.building_name)
    for record in spaces:
        by_normalized.setdefault(record.normalized_building_name, record.building_name)

    rows: list[dict[str, Any]] = []
    for normalized_name, building_name in sorted(by_normalized.items()):
        aliases = [building_name]
        aliases.extend(DEFAULT_BUILDING_ALIASES.get(normalized_name, ()))
        if "muhendislik" in normalized_name and "doga" in normalized_name:
            aliases.extend(DEFAULT_BUILDING_ALIASES["muhendislik ve doga bilimleri fakultesi"])
        aliases = _dedup_preserve_order(aliases)
        rows.append(
            {
                "building_name": building_name,
                "normalized_building_name": normalized_name,
                "aliases": aliases,
                "normalized_aliases": _dedup_preserve_order(normalize_for_match(alias) for alias in aliases),
                "source_file": source_file,
            }
        )
    return rows


def _dedup_preserve_order(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _cell_to_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _building_sql_row(row: dict[str, Any]) -> str:
    return (
        "    ("
        f"{_sql_literal(row['building_name'])}, "
        f"{_sql_literal(row['normalized_building_name'])}, "
        f"{_sql_jsonb(row['aliases'])}, "
        f"{_sql_jsonb(row['normalized_aliases'])}, "
        f"{_sql_literal(row['source_file'])}"
        ")"
    )


def _classroom_sql_row(record: ClassroomRecord) -> str:
    return (
        "    ("
        f"{_sql_literal(record.building_name)}, "
        f"{_sql_literal(record.floor_label)}, "
        f"{_sql_literal(record.room_code)}, "
        f"{_sql_literal(record.room_type)}, "
        f"{record.capacity if record.capacity is not None else 'NULL'}, "
        f"{_sql_literal(record.department_name)}, "
        f"{_sql_literal(record.department_code)}, "
        f"{'TRUE' if record.is_shared else 'FALSE'}, "
        f"{_sql_literal(record.normalized_room_code)}, "
        f"{_sql_literal(record.normalized_building_name)}, "
        f"{_sql_literal(record.search_text)}, "
        f"{_sql_literal(record.source_file)}"
        ")"
    )


def _space_sql_row(record: CampusSpaceRecord) -> str:
    return (
        "    ("
        f"{_sql_literal(record.building_name)}, "
        f"{_sql_literal(record.floor_label)}, "
        f"{_sql_literal(record.space_name)}, "
        f"{_sql_literal(record.space_type)}, "
        f"{_sql_literal(record.department_name)}, "
        f"{_sql_literal(record.department_code)}, "
        f"{_sql_jsonb(record.aliases)}, "
        f"{_sql_literal(record.normalized_space_name)}, "
        f"{_sql_jsonb(record.normalized_aliases)}, "
        f"{_sql_literal(record.normalized_building_name)}, "
        f"{_sql_literal(record.search_text)}, "
        f"{_sql_literal(record.source_file)}"
        ")"
    )


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _sql_jsonb(value: Any) -> str:
    return _sql_literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"


if __name__ == "__main__":
    main()
