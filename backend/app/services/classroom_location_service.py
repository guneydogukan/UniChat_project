"""Derslik konumları için DB-first deterministik cevap servisi."""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.classroom_repository import ClassroomRepository
from app.services.classroom_location_intent import (
    ClassroomLocationRequest,
    extract_classroom_location_request,
    normalize_for_match,
)

logger = logging.getLogger(__name__)

ENGINEERING_BUILDING_NORMALIZED = "muhendislik ve doga bilimleri fakultesi"
STATIC_BUILDING_ALIASES: dict[str, tuple[str, ...]] = {
    ENGINEERING_BUILDING_NORMALIZED: (
        "mdbf",
        "m d b f",
        "muhendislik",
        "muhendislik fakultesi",
        "muhendislik binasi",
        "muhendislik ve doga bilimleri",
        "muhendislik ve doga bilimleri fakultesi",
        "doga bilimleri",
    ),
}

SPACE_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "ogrenci isleri": ("ogrenci isleri", "ogrenci isleri ofisi"),
    "fakulte sekreterligi": ("fakulte sekreterligi", "sekreterlik"),
    "dekanlik": ("dekanlik", "dekan"),
    "dekan yardimcisi": ("dekan yardimcisi", "dekan yardimciligi"),
    "bolum baskanligi": ("bolum baskanligi",),
    "akademik personel odalari": ("akademik personel odalari", "akademik personel"),
    "idari ofis": ("idari ofis",),
}


class ClassroomLocationService:
    """Derslik/sınıf/lab/amfi konum sorularını RAG'e düşürmeden yanıtlar."""

    def __init__(self, repository: ClassroomRepository | None = None) -> None:
        self._repository = repository or ClassroomRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        request = extract_classroom_location_request(question)
        if not request.is_classroom_query:
            return None

        try:
            if request.wants_list and not request.room_code and request.department_code:
                records = self._repository.list_by_department(request.department_code)
                if not records:
                    return self._not_found_response("department_list", request)
                return self._department_list_response(records, request)

            if not request.room_code and request.space_query:
                matched_space = self._match_space(request)
                if matched_space["status"] == "matched":
                    return self._single_space_response(matched_space["records"][0], request, matched_space["method"])
                if matched_space["status"] == "ambiguous":
                    return self._ambiguous_space_response(matched_space["records"], request)
                return self._not_found_response(matched_space["method"], request)

            if not request.room_code:
                return self._not_found_response("missing_room_code", request)

            matched = self._match_room(request)
            if matched["status"] == "matched":
                return self._single_room_response(matched["records"][0], request, matched["method"])
            if matched["status"] == "ambiguous":
                return self._ambiguous_response(matched["records"], request)
            return self._not_found_response(matched["method"], request)
        except Exception as exc:  # noqa: BLE001 - derslikte canlı/RAG fallback yok
            logger.warning("Derslik konum servisi DB yanıtı üretemedi: %s", exc, exc_info=True)
            return self._response(
                "Derslik konum verisi için ana kaynak ÜniChat DB'dir. "
                "Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi.",
                [],
                request,
                "db_unavailable",
            )

    def _match_room(self, request: ClassroomLocationRequest) -> dict[str, Any]:
        room_code = str(request.room_code)
        building_match = self._resolve_building(request.normalized_query)
        if building_match:
            building_records = self._repository.find_by_room_and_building(
                room_code,
                str(building_match["normalized_building_name"]),
            )
            if building_records:
                return {"status": self._status_for_records(building_records), "records": building_records, "method": building_match["method"]}

        room_records = self._repository.find_by_room_code(room_code)
        type_filtered = self._filter_by_room_type(room_records, request.room_type)
        if len(type_filtered) == 1:
            return {"status": "matched", "records": type_filtered, "method": "exact_room_type"}
        if len(room_records) == 1:
            return {"status": "matched", "records": room_records, "method": "exact_room_unique"}

        if request.department_code:
            department_records = self._repository.find_by_department_and_room(request.department_code, room_code)
            if department_records:
                return {
                    "status": self._status_for_records(department_records),
                    "records": department_records,
                    "method": "exact_department_room",
                }

        if room_records:
            return {"status": "ambiguous", "records": room_records, "method": "exact_room_ambiguous"}
        return {"status": "not_found", "records": [], "method": "not_found"}

    def _match_space(self, request: ClassroomLocationRequest) -> dict[str, Any]:
        building_match = self._resolve_building(request.normalized_query)
        if building_match:
            records = self._repository.find_spaces_by_building(str(building_match["normalized_building_name"]))
        elif request.department_code:
            records = self._repository.find_spaces_by_department(request.department_code)
            if not records:
                records = self._repository.list_spaces()
        else:
            records = self._repository.list_spaces()

        candidates = self._filter_spaces_by_query(records, request)
        if request.department_code:
            department_candidates = [
                record for record in candidates if self._space_department_matches(record, request.department_code)
            ]
            if department_candidates:
                candidates = department_candidates

        if len(candidates) == 1:
            return {"status": "matched", "records": candidates, "method": "exact_space_alias"}
        if len(candidates) > 1:
            return {"status": "ambiguous", "records": candidates, "method": "space_ambiguous"}
        return {"status": "not_found", "records": [], "method": "space_not_found"}

    def _resolve_building(self, normalized_query: str) -> dict[str, str] | None:
        candidates = self._building_candidates()
        exact_name = [item for item in candidates if self._contains_alias(item["normalized_building_name"], normalized_query)]
        if exact_name:
            return {**exact_name[0], "method": "exact_building_name"}

        exact_aliases: list[dict[str, str]] = []
        fuzzy: list[tuple[int, dict[str, str]]] = []
        query_tokens = normalized_query.split()
        for candidate in candidates:
            aliases = [candidate["normalized_building_name"], *candidate.get("normalized_aliases", [])]
            for alias in aliases:
                if self._contains_alias(alias, normalized_query):
                    exact_aliases.append(candidate)
                    break
                score = self._fuzzy_alias_score(alias, query_tokens)
                if score:
                    fuzzy.append((score, candidate))

        if exact_aliases:
            return {**exact_aliases[0], "method": "exact_building_alias"}
        if fuzzy:
            fuzzy.sort(key=lambda item: item[0], reverse=True)
            return {**fuzzy[0][1], "method": "fuzzy_building_alias"}
        return None

    def _building_candidates(self) -> list[dict[str, Any]]:
        try:
            buildings = self._repository.list_buildings()
        except Exception:
            buildings = []

        by_normalized: dict[str, dict[str, Any]] = {}
        for building in buildings:
            normalized_name = str(building.get("normalized_building_name") or normalize_for_match(building.get("building_name")))
            aliases = [normalize_for_match(alias) for alias in building.get("aliases") or []]
            aliases.extend(building.get("normalized_aliases") or [])
            aliases.extend(STATIC_BUILDING_ALIASES.get(normalized_name, ()))
            by_normalized[normalized_name] = {
                "building_name": building.get("building_name") or normalized_name,
                "normalized_building_name": normalized_name,
                "normalized_aliases": self._dedup_aliases(aliases),
            }

        for normalized_name, aliases in STATIC_BUILDING_ALIASES.items():
            by_normalized.setdefault(
                normalized_name,
                {
                    "building_name": "Mühendislik ve Doğa Bilimleri Fakültesi",
                    "normalized_building_name": normalized_name,
                    "normalized_aliases": self._dedup_aliases(aliases),
                },
            )

        return list(by_normalized.values())

    @staticmethod
    def _status_for_records(records: list[dict[str, Any]]) -> str:
        return "matched" if len(records) == 1 else "ambiguous"

    @staticmethod
    def _dedup_aliases(values: list[Any] | tuple[Any, ...]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = normalize_for_match(str(value))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _contains_alias(alias: str, normalized_query: str) -> bool:
        if not alias:
            return False
        if " " not in alias and len(alias) <= 5:
            return alias in set(normalized_query.split())
        return f" {alias} " in f" {normalized_query} "

    @staticmethod
    def _fuzzy_alias_score(alias: str, query_tokens: list[str]) -> int:
        alias_tokens = [token for token in alias.split() if len(token) > 3 and token not in {"fakultesi", "fakulte"}]
        if not alias_tokens or not query_tokens:
            return 0
        matched = 0
        for alias_token in alias_tokens:
            if any(
                query_token == alias_token
                or (len(query_token) >= 4 and alias_token.startswith(query_token))
                or (len(query_token) >= 4 and SequenceMatcher(None, query_token, alias_token).ratio() >= 0.88)
                for query_token in query_tokens
            ):
                matched += 1
        coverage = matched / len(alias_tokens)
        if coverage < 0.72:
            return 0
        return int(80 + coverage * 30 + min(len(alias), 30))

    @staticmethod
    def _filter_by_room_type(records: list[dict[str, Any]], requested_type: str | None) -> list[dict[str, Any]]:
        if not requested_type:
            return []
        normalized_type = normalize_for_match(requested_type)
        return [
            record
            for record in records
            if normalized_type and normalized_type in normalize_for_match(str(record.get("room_type") or ""))
        ]

    def _filter_spaces_by_query(
        self,
        records: list[dict[str, Any]],
        request: ClassroomLocationRequest,
    ) -> list[dict[str, Any]]:
        return [record for record in records if self._space_matches_query(record, request)]

    def _space_matches_query(self, record: dict[str, Any], request: ClassroomLocationRequest) -> bool:
        query_aliases = SPACE_QUERY_ALIASES.get(request.space_query or "", (request.space_query or "",))
        normalized_aliases = [
            normalize_for_match(alias)
            for alias in [
                record.get("space_name"),
                record.get("space_type"),
                record.get("department_name"),
                *(record.get("aliases") or []),
                *(record.get("normalized_aliases") or []),
            ]
        ]
        normalized_aliases = [alias for alias in normalized_aliases if alias]

        if request.space_query == "idari ofis":
            return any(alias == "idari ofis" or "idari ofis" in alias for alias in normalized_aliases)

        for query_alias in query_aliases:
            normalized_query_alias = normalize_for_match(query_alias)
            if not normalized_query_alias:
                continue
            if any(
                normalized_query_alias == alias
                or f" {normalized_query_alias} " in f" {alias} "
                or f" {alias} " in f" {request.normalized_query} "
                for alias in normalized_aliases
            ):
                return True

        if request.department_code and request.space_query == "bolum baskanligi":
            return self._space_department_matches(record, request.department_code)
        return False

    @staticmethod
    def _space_department_matches(record: dict[str, Any], department_code: str) -> bool:
        normalized_code = normalize_for_match(department_code)
        if str(record.get("department_code") or "").upper() == department_code.upper():
            return True
        aliases = [normalize_for_match(alias) for alias in record.get("aliases") or []]
        aliases.extend(normalize_for_match(alias) for alias in record.get("normalized_aliases") or [])
        return normalized_code in aliases

    def _single_room_response(
        self,
        record: dict[str, Any],
        request: ClassroomLocationRequest,
        match_method: str,
    ) -> dict[str, Any]:
        building = str(record.get("building_name") or "Belirtilen bina")
        room_code = str(record.get("room_code") or request.room_code)
        floor_label = str(record.get("floor_label") or "").strip()
        room_type = str(record.get("room_type") or "Derslik").strip()

        location = self._floor_sentence(floor_label)
        response = f"{building} {room_code} numaralı derslik{location}."

        details: list[str] = []
        if room_type:
            details.append(f"Derslik tipi {room_type}")
        if record.get("capacity") is not None:
            details.append(f"kapasitesi {int(record['capacity'])} kişidir")
        if record.get("is_shared") is True:
            details.append("ortak kullanıma açıktır")
        elif record.get("department_name"):
            details.append(f"{record.get('department_name')} kullanımındadır")
        if details:
            response += " " + self._join_sentence_parts(details) + "."

        if floor_label:
            response += f" Binaya gittikten sonra {self._direction_floor_text(floor_label)} {room_code} numaralı {self._room_type_object(room_type)} bulabilirsin."

        return self._response(response, self._sources_from_records([record]), request, match_method)

    def _single_space_response(
        self,
        record: dict[str, Any],
        request: ClassroomLocationRequest,
        match_method: str,
    ) -> dict[str, Any]:
        building = str(record.get("building_name") or "Belirtilen bina")
        space_name = self._space_display_name(record, request)
        floor_label = str(record.get("floor_label") or "").strip()
        space_type = str(record.get("space_type") or "Alan").strip()

        response = f"{space_name}, {building} binasının {self._space_floor_sentence(floor_label)}."
        if space_type:
            response += f" Bu kayıt {space_type} olarak işaretlenmiştir."

        return self._response(response, self._sources_from_records([record]), request, match_method)

    def _department_list_response(
        self,
        records: list[dict[str, Any]],
        request: ClassroomLocationRequest,
    ) -> dict[str, Any]:
        department_label = records[0].get("department_name") or request.department_code or "Bu bölüm"
        lines = [f"{department_label} için veritabanında kayıtlı derslikler:"]
        for record in records[:12]:
            details = [
                f"{record.get('building_name')}",
                f"{record.get('room_code')}",
            ]
            if record.get("floor_label"):
                details.append(f"{self._floor_display(record.get('floor_label'))}")
            if record.get("room_type"):
                details.append(str(record.get("room_type")))
            lines.append(f"- {' / '.join(str(item) for item in details if item)}")
        if len(records) > 12:
            lines.append(f"- ... ve {len(records) - 12} kayıt daha")
        return self._response("\n".join(lines), self._sources_from_records(records), request, "department_list")

    def _ambiguous_response(
        self,
        records: list[dict[str, Any]],
        request: ClassroomLocationRequest,
    ) -> dict[str, Any]:
        lines = [
            "Bu oda kodu birden fazla derslikle eşleşiyor. Lütfen bina veya bölüm bilgisini netleştir:",
        ]
        for record in records[:8]:
            parts = [
                str(record.get("building_name") or ""),
                f"Oda {record.get('room_code')}",
                self._floor_display(record.get("floor_label")),
                str(record.get("room_type") or ""),
                str(record.get("department_code") or ""),
            ]
            lines.append(f"- {' / '.join(part for part in parts if part)}")
        return self._response("\n".join(lines), self._sources_from_records(records), request, "ambiguous")

    def _ambiguous_space_response(
        self,
        records: list[dict[str, Any]],
        request: ClassroomLocationRequest,
    ) -> dict[str, Any]:
        lines = [
            "Bu ifade birden fazla idari alanla eşleşiyor. Lütfen birini netleştir:",
        ]
        for record in records[:8]:
            parts = [
                self._space_display_name(record, request),
                str(record.get("building_name") or ""),
                self._floor_display(record.get("floor_label")),
                str(record.get("space_type") or ""),
            ]
            lines.append(f"- {' / '.join(part for part in parts if part)}")
        return self._response("\n".join(lines), self._sources_from_records(records), request, "space_ambiguous")

    def _not_found_response(self, match_method: str, request: ClassroomLocationRequest) -> dict[str, Any]:
        message = "Bu derslik veritabanında bulunamadı." if request.room_code else "Bu konum veritabanında bulunamadı."
        return self._response(message, [], request, match_method)

    @staticmethod
    def _floor_sentence(floor_label: str) -> str:
        if not floor_label:
            return " için kat bilgisi veritabanında belirtilmemiştir"
        if normalize_for_match(floor_label) == "zemin":
            return ", binanın zemin katındadır"
        return f", binanın {floor_label}. katındadır"

    @staticmethod
    def _space_floor_sentence(floor_label: str) -> str:
        if not floor_label:
            return "kat bilgisi veritabanında belirtilmemiştir"
        if normalize_for_match(floor_label) == "zemin":
            return "zemin katındadır"
        return f"{floor_label}. katındadır"

    @staticmethod
    def _space_display_name(record: dict[str, Any], request: ClassroomLocationRequest) -> str:
        aliases = [str(alias) for alias in record.get("aliases") or [] if alias]
        for alias in sorted(aliases, key=lambda value: len(normalize_for_match(value)), reverse=True):
            normalized_alias = normalize_for_match(alias)
            if normalized_alias and f" {normalized_alias} " in f" {request.normalized_query} ":
                return alias
        return str(record.get("space_name") or "Belirtilen alan")

    @staticmethod
    def _floor_display(floor_label: Any) -> str:
        text = str(floor_label or "").strip()
        if not text:
            return ""
        if normalize_for_match(text) == "zemin":
            return "Zemin kat"
        return f"{text}. kat"

    @staticmethod
    def _direction_floor_text(floor_label: str) -> str:
        if normalize_for_match(floor_label) == "zemin":
            return "zemin katta"
        return f"{floor_label}. kata çıkarak"

    @staticmethod
    def _room_type_object(room_type: str) -> str:
        normalized = normalize_for_match(room_type)
        if "amfi" in normalized:
            return "amfiyi"
        if "laboratuvar" in normalized or normalized == "lab":
            return "laboratuvarı"
        if "konferans" in normalized:
            return "konferans salonunu"
        if "derslik" in normalized or "sinif" in normalized:
            return "dersliği"
        return "alanı"

    @staticmethod
    def _join_sentence_parts(parts: list[str]) -> str:
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " ve " + parts[-1]

    @staticmethod
    def _sources_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            source_file = str(record.get("source_file") or "Derslikler.xlsx")
            if source_file in seen:
                continue
            seen.add(source_file)
            sources.append(
                {
                    "content": "Derslik/idari alan konum veritabanı kaydı.",
                    "source_url": None,
                    "source_public_url": None,
                    "category": "classroom_location",
                    "title": source_file,
                    "doc_kind": "classroom_location",
                }
            )
        return sources

    @staticmethod
    def _response(
        response: str,
        sources: list[dict[str, Any]],
        request: ClassroomLocationRequest,
        match_method: str,
    ) -> dict[str, Any]:
        return {
            "response": response,
            "sources": sources,
            "metadata": {
                "db_first": True,
                "service": "classroom_location_service",
                "intent": "classroom_location",
                "normalized_query": request.normalized_query,
                "match_method": match_method,
                "rag_fallback_used": False,
            },
        }


@lru_cache()
def get_classroom_location_service() -> ClassroomLocationService:
    return ClassroomLocationService()


__all__ = ["ClassroomLocationService", "get_classroom_location_service"]
