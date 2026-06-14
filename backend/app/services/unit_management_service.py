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

STATIC_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "ilahiyat fakultesi": ("ilahiyat",),
    "muhendislik ve doga bilimleri fakultesi": ("mdbf", "muhendislik", "muhendislik fakultesi", "muhendislik ve doga bilimleri"),
    "saglik bilimleri fakultesi": ("sbf", "saglik bilimleri"),
    "tip fakultesi": ("tip",),
    "iktisadi idari ve sosyal bilimler fakultesi": ("iisbf", "iktisadi idari sosyal bilimler"),
    "guzel sanatlar tasarim ve mimarlik fakultesi": ("gstm", "gsmf", "guzel sanatlar", "mimarlik fakultesi"),
    "saglik hizmetleri meslek yuksekokulu": ("shmyo", "saglik hizmetleri myo", "saglik hizmetleri"),
    "teknik bilimler meslek yuksekokulu": ("tbmyo", "teknik bilimler myo", "teknik bilimler"),
    "yabanci diller yuksekokulu": ("ydyo", "yabanci diller"),
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

            requested_filter = self._requested_filter(normalized_question)
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
            if len(alias) <= 4:
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

    @staticmethod
    def _requested_filter(normalized_question: str) -> dict[str, Any]:
        if "yonetim kurulu" in normalized_question:
            return {"label": "yönetim kurulu", "group_includes": ("yonetim kurulu",)}
        if "fakulte kurulu" in normalized_question:
            return {"label": "fakülte kurulu", "group_includes": ("fakulte kurulu",)}
        if "yuksekokul kurulu" in normalized_question:
            return {
                "label": "yüksekokul kurulu",
                "group_includes": ("yuksekokul kurulu",),
                "group_excludes": ("yonetim kurulu",),
            }
        if "bolum baskan" in normalized_question:
            return {
                "label": "bölüm başkanı",
                "group_includes": ("bolum baskan",),
                "role_includes": ("bolum baskan",),
            }
        if "dekan yard" in normalized_question or "dekan yrd" in normalized_question:
            return {
                "label": "dekan yardımcıları",
                "group_includes": ("dekan yardim", "dekan yrd"),
                "role_includes": ("dekan yardim", "dekan yrd"),
            }
        if "dekan" in normalized_question:
            return {
                "label": "dekanlık",
                "group_includes": ("dekan", "dekanlik"),
                "role_includes": ("dekan",),
                "group_excludes": ("dekan yardim", "dekan yrd"),
                "role_excludes": ("yardim", "yrd"),
            }
        if "mudur yard" in normalized_question or "mudur yrd" in normalized_question:
            return {
                "label": "müdür yardımcıları",
                "group_includes": ("mudur yardim", "mudur yrd"),
                "role_includes": ("mudur yardim", "mudur yrd"),
            }
        if "mudur" in normalized_question:
            return {
                "label": "müdürlük",
                "group_includes": ("mudur",),
                "role_includes": ("mudur",),
                "group_excludes": ("mudur yardim", "mudur yrd"),
                "role_excludes": ("yardim", "yrd"),
            }
        if "sekreter" in normalized_question:
            return {
                "label": "sekreterlik",
                "group_includes": ("sekreter",),
                "role_includes": ("sekreter",),
            }
        return {"label": "yönetim bilgileri"}

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
