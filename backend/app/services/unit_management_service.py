"""
ÜniChat — GİBTÜ birim yönetim DB-first cevap servisi.

Yönetim soruları RAG/LLM öncesinde bu servis tarafından yanıtlanır. Veri yoksa
tahmin yapılmaz ve kaynakta bulunamadığı açıkça söylenir.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from app.repositories.unit_management_repository import UnitManagementRepository
from scrapers.unit_management_scraper import normalize_for_match

logger = logging.getLogger(__name__)

MANAGEMENT_QUERY_RE = re.compile(
    r"\b("
    r"dekan\w*|müdür\w*|mudur\w*|sekreter\w*|"
    r"yönetim\s+kurul\w*|yonetim\s+kurul\w*|"
    r"fakülte\s+kurul\w*|fakulte\s+kurul\w*|"
    r"yüksekokul\s+kurul\w*|yuksekokul\s+kurul\w*|"
    r"bölüm\s+başkan\w*|bolum\s+baskan\w*|"
    r"yönetiminde|yonetiminde|kurulunda"
    r")\b",
    re.IGNORECASE,
)

UNIT_SUFFIXES: tuple[str, ...] = (
    " fakultesi",
    " meslek yuksekokulu",
    " yuksekokulu",
)

FACULTY_UNIT_TYPES: frozenset[str] = frozenset({"faculty", "fakulte"})
VOCATIONAL_SCHOOL_UNIT_TYPES: frozenset[str] = frozenset({"vocational school", "meslek yuksekokulu", "myo"})

STATIC_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "ilahiyat fakultesi": ("if", "i f", "ilahiyat", "ilahiyat fak", "ilahiyat fakultesi"),
    "muhendislik ve doga bilimleri fakultesi": (
        "mdbf",
        "m d b f",
        "mdb",
        "m d b",
        "mdb fak",
        "muh doga bil",
        "muhendislik",
        "muhendislik fak",
        "muhendislik fakultesi",
        "muhendislik doga bilimleri",
        "muhendislik doga bilimleri fak",
        "muhendislik ve doga bilimleri",
        "muhendislik ve doga bilimleri fak",
        "doga bilimleri",
    ),
    "saglik bilimleri fakultesi": (
        "sbf",
        "s b f",
        "saglik bilimleri",
        "saglik bilimleri fak",
        "saglik bilimleri fakultesi",
    ),
    "tip fakultesi": ("tf", "t f", "tip", "tip fak", "tip fakultesi"),
    "iktisadi idari ve sosyal bilimler fakultesi": (
        "iisbf",
        "i i s b f",
        "iibf",
        "i i b f",
        "iisbf fak",
        "iibf fak",
        "iktisadi",
        "iktisadi idari",
        "iktisadi ve idari",
        "iktisadi ve idari bilimler",
        "iktisadi idari sosyal bilimler",
        "iktisadi idari ve sosyal bilimler",
        "idari sosyal bilimler",
        "sosyal bilimler fakultesi",
    ),
    "guzel sanatlar tasarim ve mimarlik fakultesi": (
        "gstm",
        "g s t m",
        "gstmf",
        "g s t m f",
        "gsmf",
        "g s m f",
        "gsf",
        "g s f",
        "guzel sanatlar",
        "guzel sanatlar fak",
        "guzel sanatlar fakultesi",
        "guzel sanatlar tasarim",
        "guzel sanatlar tasarim mimarlik",
        "sanat tasarim",
        "tasarim",
        "tasarim fakultesi",
        "tasarim mimarlik",
        "mimarlik",
        "mimarlik fakultesi",
    ),
    "saglik hizmetleri meslek yuksekokulu": (
        "shmyo",
        "s h m y o",
        "sh myo",
        "saglik myo",
        "saglik hizmetleri",
        "saglik hizmetleri myo",
        "saglik hizmetleri meslek yuksekokulu",
    ),
    "teknik bilimler meslek yuksekokulu": (
        "tbmyo",
        "t b m y o",
        "tb myo",
        "teknik myo",
        "teknik bilimler",
        "teknik bilimler myo",
        "teknik bilimler meslek yuksekokulu",
    ),
    "yabanci diller yuksekokulu": (
        "ydyo",
        "y d y o",
        "yd yo",
        "yabanci dil",
        "yabanci diller",
        "yabanci diller yo",
        "yabanci diller y o",
        "yabanci diller yuksekokulu",
    ),
}


class UnitManagementService:
    """Birim yönetim sorularını normalize DB kayıtlarından yanıtlar."""

    def __init__(self, repository: UnitManagementRepository | None = None) -> None:
        self._repository = repository or UnitManagementRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        if not MANAGEMENT_QUERY_RE.search(question):
            return None

        normalized_question = normalize_for_match(question)
        try:
            unit = self._match_unit(normalized_question)
            if not unit:
                return self._unit_required_response()

            requested_filter = self._requested_filter(normalized_question, unit)
            records = self._repository.get_management_members(str(unit["id"]))
            records = self._dedup_records(records)
            filtered = self._filter_records(records, requested_filter)
            if not filtered:
                return self._not_found_response(unit, requested_filter["label"])

            return {
                "response": self._format_response(unit, filtered, requested_filter["label"]),
                "sources": self._sources_from_records(filtered, unit),
            }
        except Exception as exc:  # noqa: BLE001 - yönetim bilgisinde canlı fallback yok
            logger.warning("Birim yönetim servisi DB yanıtı üretemedi: %s", exc, exc_info=True)
            return {
                "response": (
                    "Birim yönetim verisi için ana kaynak ÜniChat DB'dir. "
                    "Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi."
                ),
                "sources": [],
            }

    def _match_unit(self, normalized_question: str) -> dict[str, Any] | None:
        units = self._repository.list_units()
        scored: list[tuple[int, dict[str, Any]]] = []
        for unit in units:
            score = self._unit_match_score(unit, normalized_question)
            if score > 0:
                scored.append((score, unit))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], len(str(item[1].get("unit_name_normalized") or ""))), reverse=True)
        return scored[0][1]

    def _unit_match_score(self, unit: dict[str, Any], normalized_question: str) -> int:
        normalized_name = str(unit.get("unit_name_normalized") or normalize_for_match(unit.get("unit_name")))
        aliases = set(self._unit_aliases(normalized_name))
        for alias in unit.get("aliases") or []:
            normalized_alias = normalize_for_match(alias)
            if normalized_alias:
                aliases.add(normalized_alias)
        best = 0
        question_tokens = set(normalized_question.split())
        for alias in aliases:
            if not alias:
                continue
            if len(alias) <= 4 and " " not in alias:
                if alias in question_tokens:
                    best = max(best, 120 + len(alias))
                continue
            if alias in normalized_question:
                best = max(best, 100 + len(alias))
                continue
            tokens = [token for token in alias.split() if len(token) > 2]
            if len(tokens) >= 2 and all(token in question_tokens for token in tokens):
                best = max(best, 40 + len(tokens))
        return best

    @staticmethod
    def _unit_aliases(normalized_name: str) -> tuple[str, ...]:
        aliases = {normalized_name}
        for suffix in UNIT_SUFFIXES:
            if normalized_name.endswith(suffix):
                aliases.add(normalized_name[: -len(suffix)].strip())
        aliases.update(STATIC_UNIT_ALIASES.get(normalized_name, ()))
        return tuple(alias for alias in aliases if alias)

    def _requested_filter(self, normalized_question: str, unit: dict[str, Any]) -> dict[str, Any]:
        if "yonetim kurulu" in normalized_question:
            return self._management_board_filter(unit)
        if "fakulte kurulu" in normalized_question:
            if self._is_faculty(unit):
                return {
                    "label": "fakülte kurulu",
                    "group_includes": ("fakulte kurulu",),
                    "group_excludes": ("yonetim kurulu",),
                }
            return self._management_board_filter(unit)
        if "yuksekokul kurulu" in normalized_question:
            if self._is_faculty(unit):
                return {
                    "label": "fakülte kurulu",
                    "group_includes": ("fakulte kurulu",),
                    "group_excludes": ("yonetim kurulu",),
                }
            return {
                "label": self._school_council_label(unit),
                "group_includes": ("yuksekokul kurulu", "meslek yuksekokulu kurulu", "myo kurulu"),
                "group_excludes": ("yonetim kurulu",),
            }
        if "bolum baskan" in normalized_question:
            return {
                "label": "bölüm başkanı",
                "group_includes": ("bolum baskan",),
                "role_includes": ("bolum baskan",),
            }
        if "dekan yard" in normalized_question or "dekan yrd" in normalized_question:
            return self._assistant_role_filter(unit)
        if "dekan" in normalized_question:
            return self._top_role_filter(unit)
        if "mudur yard" in normalized_question or "mudur yrd" in normalized_question:
            return self._assistant_role_filter(unit)
        if "mudur" in normalized_question:
            return self._top_role_filter(unit)
        if "sekreter" in normalized_question:
            return {
                "label": self._secretary_label(unit),
                "group_includes": ("sekreter",),
                "role_includes": ("sekreter",),
            }
        return {"label": "yönetim bilgileri"}

    def _top_role_filter(self, unit: dict[str, Any]) -> dict[str, Any]:
        if self._is_faculty(unit):
            return {
                "label": "dekanı",
                "group_includes": ("dekan", "dekanlik"),
                "role_includes": ("dekan",),
                "group_excludes": ("dekan yardim", "dekan yrd"),
                "role_excludes": ("yardim", "yrd"),
            }
        return {
            "label": "müdürü",
            "group_includes": ("mudur",),
            "role_includes": ("mudur",),
            "group_excludes": ("mudur yardim", "mudur yrd"),
            "role_excludes": ("yardim", "yrd"),
        }

    def _assistant_role_filter(self, unit: dict[str, Any]) -> dict[str, Any]:
        if self._is_faculty(unit):
            return {
                "label": "dekan yardımcıları",
                "group_includes": ("dekan yardim", "dekan yrd"),
                "role_includes": ("dekan yardim", "dekan yrd"),
            }
        return {
            "label": "müdür yardımcıları",
            "group_includes": ("mudur yardim", "mudur yrd"),
            "role_includes": ("mudur yardim", "mudur yrd"),
        }

    def _management_board_filter(self, unit: dict[str, Any]) -> dict[str, Any]:
        if self._is_faculty(unit):
            return {"label": "fakülte yönetim kurulu", "group_includes": ("yonetim kurulu",)}
        return {"label": "yönetim kurulu", "group_includes": ("yonetim kurulu",)}

    def _secretary_label(self, unit: dict[str, Any]) -> str:
        return "sekreteri"

    def _school_council_label(self, unit: dict[str, Any]) -> str:
        if self._is_vocational_school(unit):
            return "MYO kurulu"
        return "yüksekokul kurulu"

    @staticmethod
    def _unit_type(unit: dict[str, Any]) -> str:
        return normalize_for_match(str(unit.get("unit_type") or ""))

    def _is_faculty(self, unit: dict[str, Any]) -> bool:
        return self._unit_type(unit) in FACULTY_UNIT_TYPES

    def _is_vocational_school(self, unit: dict[str, Any]) -> bool:
        return self._unit_type(unit) in VOCATIONAL_SCHOOL_UNIT_TYPES

    def _filter_records(self, records: list[dict[str, Any]], requested_filter: dict[str, Any]) -> list[dict[str, Any]]:
        if not requested_filter.get("group_includes") and not requested_filter.get("role_includes"):
            return records

        filtered = []
        for record in records:
            group_text = normalize_for_match(record.get("group_title") or record.get("group_key"))
            role_text = normalize_for_match(record.get("role"))

            if any(excluded in group_text for excluded in requested_filter.get("group_excludes", ())):
                continue
            if any(excluded in role_text for excluded in requested_filter.get("role_excludes", ())):
                continue

            group_match = any(included in group_text for included in requested_filter.get("group_includes", ()))
            role_match = any(included in role_text for included in requested_filter.get("role_includes", ()))
            if group_match or role_match:
                filtered.append(record)
        return filtered

    @staticmethod
    def _dedup_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for record in records:
            key = str(
                record.get("member_id")
                or f"{record.get('unit_id')}:{record.get('group_id')}:{record.get('stable_member_key')}"
            )
            by_key.setdefault(key, record)
        return list(by_key.values())

    def _format_response(self, unit: dict[str, Any], records: list[dict[str, Any]], label: str) -> str:
        lines = [f"**{unit.get('unit_name')} {label}**"]
        for record in records:
            name_parts = []
            if record.get("academic_title"):
                name_parts.append(str(record["academic_title"]))
            if record.get("full_name"):
                name_parts.append(str(record["full_name"]))
            display_name = " ".join(name_parts).strip() or str(record.get("full_name") or "İsim kaynakta parse edilemedi")
            role = self._display_role(record)
            details = []
            if record.get("email"):
                details.append(f"E-posta: {record['email']}")
            phone = self._display_phone(record.get("phone_extension"))
            if phone:
                details.append(f"Dahili: {phone}")
            detail_text = f" ({'; '.join(details)})" if details else ""
            lines.append(f"- {display_name} - {role}{detail_text}")

        source_url = records[0].get("source_url") or unit.get("source_url")
        checked_at = records[0].get("scrape_time")
        if source_url:
            lines.append(f"\nKaynak: {source_url}")
        if checked_at:
            lines.append(f"Son scrape tarihi: {self._format_checked_at(checked_at)}")
        return "\n".join(lines)

    @staticmethod
    def _display_role(record: dict[str, Any]) -> str:
        role = str(record.get("role") or "").strip()
        title = str(record.get("academic_title") or "").strip()
        if not role:
            return str(record.get("group_title") or "Görev kaynakta belirtilmemiş")
        if title and normalize_for_match(role) == normalize_for_match(title):
            return str(record.get("group_title") or role)
        return role

    @staticmethod
    def _display_phone(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text or text == "0000":
            return None
        return text

    def _not_found_response(self, unit: dict[str, Any], label: str) -> dict[str, Any]:
        source_url = unit.get("source_url")
        response = f"{unit.get('unit_name')} için {label} bilgisi mevcut kaynakta bulunamadı."
        if source_url:
            response += f"\n\nKaynak: {source_url}"
        return {
            "response": response,
            "sources": self._unit_source(unit),
        }

    def _unit_required_response(self) -> dict[str, Any]:
        units = self._repository.list_units()
        if units:
            options = ", ".join(str(unit.get("unit_name")) for unit in units)
            response = f"Hangi birimin yönetim bilgisini istediğinizi belirtir misiniz? Bilinen birimler: {options}."
        else:
            response = "Birim yönetim verisi mevcut kaynakta bulunamadı."
        return {"response": response, "sources": []}

    @staticmethod
    def _sources_from_records(records: list[dict[str, Any]], unit: dict[str, Any]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            source_url = record.get("source_url") or unit.get("source_url")
            if not source_url or source_url in seen:
                continue
            seen.add(source_url)
            sources.append({
                "content": f"{unit.get('unit_name')} birim yönetim kaynağı.",
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "unit_management",
                "title": unit.get("unit_name"),
                "doc_kind": "unit_management",
            })
        return sources

    @staticmethod
    def _unit_source(unit: dict[str, Any]) -> list[dict[str, Any]]:
        source_url = unit.get("source_url")
        if not source_url:
            return []
        return [{
            "content": f"{unit.get('unit_name')} birim yönetim kaynağı.",
            "source_url": source_url,
            "source_public_url": source_url,
            "category": "unit_management",
            "title": unit.get("unit_name"),
            "doc_kind": "unit_management",
        }]

    @staticmethod
    def _format_checked_at(value: Any) -> str:
        text = str(value)
        if "T" in text:
            return text.split("T", 1)[0]
        return text.split(" ", 1)[0]


@lru_cache()
def get_unit_management_service() -> UnitManagementService:
    return UnitManagementService()
