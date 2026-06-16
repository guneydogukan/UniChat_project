"""
ÜniChat — GİBTÜ idari birim/personel DB-first cevap servisi.

İdari personel ve idari birim soruları RAG/LLM öncesinde bu servis tarafından
yanıtlanır. Veri yoksa tahmin yapılmaz.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.administrative_repository import AdministrativeRepository
from scrapers.administrative_staff_scraper import DEFAULT_TARGETS, AdministrativeTarget, normalize_for_match

logger = logging.getLogger(__name__)

ADMINISTRATIVE_QUERY_RE = re.compile(
    r"\b("
    r"idari\s+personel\w*|idari\s+birim\w*|idari\s+kadro\w*|"
    r"idari\s+i(?:ş|s)\w*|"
    r"sekreter\w*|sekreterlik\w*|"
    r"öğrenci\s+iş\w*|ogrenci\s+is\w*|"
    r"mali\s+iş\w*|mali\s+is\w*|"
    r"personel\s+iş\w*|personel\s+is\w*|"
    r"fakülte\s+memur\w*|fakulte\s+memur\w*|"
    r"yüksekokul\s+memur\w*|yuksekokul\s+memur\w*|"
    r"memur\s+bilgi\w*|personel\s+bilgi\w*|"
    r"yönetim\s*/?\s*idari\s+personel\w*|yonetim\s*/?\s*idari\s+personel\w*|"
    r"yönetim\s+personel\w*|yonetim\s+personel\w*"
    r")\b",
    re.IGNORECASE,
)

ADMINISTRATIVE_UNIT_QUERY_RE = re.compile(
    r"\b(idari\s+birim\w*|birim\w*\s+kimlerden|birim\w*\s+nelerdir)\b",
    re.IGNORECASE,
)

ADMINISTRATIVE_STAFF_QUERY_RE = re.compile(
    r"\b(idari\s+personel\w*|idari\s+kadro\w*|memur\w*|personel\w*)\b",
    re.IGNORECASE,
)

CONTACT_QUERY_RE = re.compile(
    r"\b(telefon|tel|dahili|e\s?posta|eposta|mail)\w*",
    re.IGNORECASE,
)

UNIT_SUFFIXES: tuple[str, ...] = (
    " fakultesi",
    " fakulte",
    " meslek yuksekokulu",
    " yuksekokulu",
)

MIN_UNIT_MATCH_SCORE = 72
AMBIGUOUS_UNIT_SCORE_GAP = 12

QUERY_NOISE_TOKENS: frozenset[str] = frozenset({
    "hangi",
    "kim",
    "kime",
    "kimin",
    "nedir",
    "var",
    "mi",
    "midir",
    "goster",
    "gosterir",
    "gosterir misin",
    "bilgi",
    "bilgisi",
    "bilgileri",
    "idari",
    "personel",
    "personeli",
    "birim",
    "birimi",
    "birimleri",
    "kadro",
    "sekreter",
    "sekreteri",
    "sekreterlik",
    "telefon",
    "tel",
    "dahili",
    "eposta",
    "posta",
    "mail",
    "memur",
    "is",
    "isleri",
    "islere",
    "bakiyor",
    "bakiyorlar",
    "ilgileniyor",
    "gorevli",
    "yonetim",
})

UNIT_DESCRIPTOR_PREFIXES: tuple[str, ...] = (
    "fakulte",
    "fakultesi",
    "fakultesinde",
    "yuksekokul",
    "yuksekokulu",
    "yuksekokulunda",
    "myo",
)


class AdministrativeStaffService:
    """İdari birim/personel sorularını normalize DB kayıtlarından yanıtlar."""

    def __init__(self, repository: AdministrativeRepository | None = None) -> None:
        self._repository = repository or AdministrativeRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        if not ADMINISTRATIVE_QUERY_RE.search(question):
            return None

        normalized_question = normalize_for_match(question)
        try:
            if self._has_explicit_unsupported_unit(normalized_question):
                return self._unsupported_unit_response()

            unit_match = self._resolve_unit_match(normalized_question)
            if unit_match["status"] == "ambiguous":
                return self._ambiguous_unit_response(unit_match["candidates"])
            if unit_match["status"] == "not_found":
                return self._unit_required_response()

            unit = unit_match["unit"]
            if not unit:
                return self._unit_required_response()

            requested_filter = self._requested_filter(normalized_question)
            administrative_units = self._repository.get_administrative_units(int(unit["website_unit_id"]))
            staff = self._repository.get_administrative_staff(
                int(unit["website_unit_id"]),
                administrative_unit_keys=requested_filter.get("unit_keys"),
            )
            staff = self._filter_staff(staff, requested_filter)

            if requested_filter["kind"] == "units":
                return self._answer_units(unit, administrative_units, staff)

            if not staff:
                if administrative_units:
                    return self._not_found_response(unit, requested_filter["label"])
                return self._unit_data_missing_response(unit)

            return {
                "response": self._format_staff_response(unit, staff, requested_filter["label"]),
                "sources": self._sources_from_records(staff, unit),
            }
        except Exception as exc:  # noqa: BLE001 - idari veride canlı fallback yok
            logger.warning("İdari personel servisi DB yanıtı üretemedi: %s", exc, exc_info=True)
            return {
                "response": (
                    "İdari personel verisi için ana kaynak ÜniChat DB'dir. "
                    "Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi."
                ),
                "sources": [],
            }

    def _resolve_unit_match(self, normalized_question: str) -> dict[str, Any]:
        candidates = self._unit_candidates()
        strict_match = self._strict_unit_match(candidates, normalized_question)
        if strict_match is not None:
            return {"status": "matched", "unit": strict_match, "candidates": [strict_match]}

        if self._is_ambiguous_health_query(normalized_question):
            health_candidates = [
                candidate for candidate in candidates
                if candidate["website_unit_id"] in {21, 31}
            ]
            return {"status": "ambiguous", "unit": None, "candidates": health_candidates}

        scored: list[tuple[int, dict[str, Any]]] = []
        for candidate in candidates:
            score = self._unit_match_score(candidate, normalized_question)
            if score >= MIN_UNIT_MATCH_SCORE:
                scored.append((score, candidate))

        if not scored:
            return {"status": "not_found", "unit": None, "candidates": []}

        scored.sort(key=lambda item: (item[0], len(str(item[1].get("parent_unit_name") or ""))), reverse=True)
        top_score, top_unit = scored[0]
        close_candidates = [
            candidate for score, candidate in scored
            if top_score - score <= AMBIGUOUS_UNIT_SCORE_GAP
        ]
        if len({candidate["website_unit_id"] for candidate in close_candidates}) > 1:
            return {"status": "ambiguous", "unit": None, "candidates": close_candidates}
        return {"status": "matched", "unit": top_unit, "candidates": [top_unit]}

    def _has_explicit_unsupported_unit(self, normalized_question: str) -> bool:
        candidates = self._unit_candidates()
        if self._strict_unit_match(candidates, normalized_question) is not None:
            return False
        tokens = normalized_question.split()
        descriptor_index = next(
            (
                index for index, token in enumerate(tokens)
                if any(token.startswith(prefix) for prefix in UNIT_DESCRIPTOR_PREFIXES)
            ),
            -1,
        )
        if descriptor_index < 0:
            return False
        before_descriptor = [
            token
            for token in tokens[:descriptor_index]
            if token not in QUERY_NOISE_TOKENS and len(token) > 2
        ]
        return bool(before_descriptor)

    def _strict_unit_match(
        self,
        candidates: list[dict[str, Any]],
        normalized_question: str,
    ) -> dict[str, Any] | None:
        matches: list[tuple[int, dict[str, Any]]] = []
        question_tokens = set(normalized_question.split())
        for candidate in candidates:
            normalized_name = normalize_for_match(candidate.get("parent_unit_name"))
            aliases = set(self._unit_aliases(normalized_name))
            for alias in candidate.get("aliases") or []:
                normalized_alias = normalize_for_match(alias)
                if normalized_alias:
                    aliases.add(normalized_alias)

            best = 0
            for alias in aliases:
                if not alias:
                    continue
                if len(alias) <= 6 and " " not in alias:
                    if alias in question_tokens:
                        best = max(best, 180 + len(alias))
                    continue
                if self._contains_alias_phrase(alias, normalized_question):
                    best = max(best, 160 + min(len(alias), 40))
                    continue
                alias_tokens = [token for token in alias.split() if token not in {"ve", "ile"} and len(token) > 2]
                if len(alias_tokens) >= 2 and all(token in question_tokens for token in alias_tokens):
                    best = max(best, 140 + len(alias_tokens))
            if best:
                matches.append((best, candidate))

        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        top_score, top_candidate = matches[0]
        close = [candidate for score, candidate in matches if top_score - score <= AMBIGUOUS_UNIT_SCORE_GAP]
        if len({candidate["website_unit_id"] for candidate in close}) > 1:
            return None
        return top_candidate

    def _unit_candidates(self) -> list[dict[str, Any]]:
        rows_by_id: dict[int, dict[str, Any]] = {}
        try:
            for row in self._repository.list_parent_units():
                rows_by_id[int(row["website_unit_id"])] = row
        except Exception:
            rows_by_id = {}

        candidates = []
        for target in DEFAULT_TARGETS:
            row = rows_by_id.get(target.website_unit_id, {})
            aliases = list(target.aliases)
            aliases.extend(row.get("aliases") or [])
            candidates.append({
                "website_unit_id": target.website_unit_id,
                "parent_unit_name": row.get("parent_unit_name") or target.parent_unit_name,
                "parent_unit_type": row.get("parent_unit_type") or target.parent_unit_type,
                "source_url": row.get("source_url") or target.source_url,
                "normalized_source_url": row.get("normalized_source_url"),
                "last_seen_at": row.get("last_seen_at"),
                "aliases": aliases,
            })
        return candidates

    @staticmethod
    def _is_ambiguous_health_query(normalized_question: str) -> bool:
        tokens = set(normalized_question.split())
        if "saglik" not in tokens:
            return False
        disambiguators = {
            "bilimleri",
            "hizmetleri",
            "myo",
            "meslek",
            "sbf",
            "shmyo",
            "fakultesi",
            "fakulte",
        }
        return not bool(tokens.intersection(disambiguators))

    def _unit_match_score(self, unit: dict[str, Any], normalized_question: str) -> int:
        normalized_name = normalize_for_match(unit.get("parent_unit_name"))
        aliases = set(self._unit_aliases(normalized_name))
        for alias in unit.get("aliases") or []:
            normalized_alias = normalize_for_match(alias)
            if normalized_alias:
                aliases.add(normalized_alias)

        best = 0
        question_tokens = set(normalized_question.split())
        query_tokens = [token for token in normalized_question.split() if len(token) > 2]

        for alias in aliases:
            if not alias:
                continue
            if len(alias) <= 6 and " " not in alias:
                if alias in question_tokens:
                    best = max(best, 150 + len(alias))
                continue
            if self._contains_alias_phrase(alias, normalized_question):
                best = max(best, 120 + min(len(alias), 40))
                continue
            alias_tokens = [token for token in alias.split() if token not in {"ve", "ile"} and len(token) > 2]
            if len(alias_tokens) >= 2 and all(token in question_tokens for token in alias_tokens):
                best = max(best, 96 + len(alias_tokens))
                continue
            fuzzy = self._alias_fuzzy_score(alias_tokens, query_tokens)
            best = max(best, fuzzy)
        return best

    @staticmethod
    def _unit_aliases(normalized_name: str) -> tuple[str, ...]:
        aliases = {normalized_name}
        for suffix in UNIT_SUFFIXES:
            if normalized_name.endswith(suffix):
                aliases.add(normalized_name[: -len(suffix)].strip())
        return tuple(alias for alias in aliases if alias)

    @staticmethod
    def _contains_alias_phrase(alias: str, normalized_question: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_question))

    @staticmethod
    def _alias_fuzzy_score(alias_tokens: list[str], query_tokens: list[str]) -> int:
        if not alias_tokens or not query_tokens:
            return 0
        matched = 0
        for alias_token in alias_tokens:
            if any(AdministrativeStaffService._token_matches(query_token, alias_token) for query_token in query_tokens):
                matched += 1
        coverage = matched / len(alias_tokens)
        if len(alias_tokens) == 1 and matched == 1:
            return 80
        if len(alias_tokens) == 2 and coverage < 1.0:
            return 0
        if len(alias_tokens) > 2 and coverage < 0.72:
            return 0
        return int(70 + coverage * 35 + matched)

    @staticmethod
    def _token_matches(query_token: str, alias_token: str) -> bool:
        if query_token == alias_token:
            return True
        if len(query_token) >= 4 and alias_token.startswith(query_token):
            return True
        if len(alias_token) >= 4 and query_token.startswith(alias_token):
            return True
        if len(query_token) < 4 or len(alias_token) < 4:
            return False
        return SequenceMatcher(None, query_token, alias_token).ratio() >= 0.86

    def _requested_filter(self, normalized_question: str) -> dict[str, Any]:
        if ADMINISTRATIVE_UNIT_QUERY_RE.search(normalized_question):
            return {"kind": "units", "label": "idari birimleri"}
        if "sekreter" in normalized_question:
            return {
                "kind": "staff",
                "label": "sekreterlik bilgisi",
                "unit_key_includes": ("sekreter",),
                "role_includes": ("sekreter",),
            }
        if "ogrenci is" in normalized_question:
            return {
                "kind": "staff",
                "label": "öğrenci işleri bilgisi",
                "unit_key_includes": ("ogrenci",),
                "role_includes": ("ogrenci",),
            }
        if "mali is" in normalized_question or "tahakkuk" in normalized_question:
            return {
                "kind": "staff",
                "label": "mali işler bilgisi",
                "unit_key_includes": ("mali", "tahakkuk"),
                "role_includes": ("mali", "tahakkuk"),
            }
        if "personel is" in normalized_question:
            return {
                "kind": "staff",
                "label": "personel işleri bilgisi",
                "unit_key_includes": ("personel",),
                "role_includes": ("personel",),
            }
        if "memur" in normalized_question:
            return {"kind": "staff", "label": "idari personel bilgileri"}
        if "idari is" in normalized_question:
            return {"kind": "staff", "label": "idari personel bilgileri"}
        if CONTACT_QUERY_RE.search(normalized_question):
            return {"kind": "staff", "label": "idari personel iletişim bilgileri"}
        if ADMINISTRATIVE_STAFF_QUERY_RE.search(normalized_question):
            return {"kind": "staff", "label": "idari personel bilgileri"}
        return {"kind": "staff", "label": "idari personel bilgileri"}

    def _filter_staff(self, staff: list[dict[str, Any]], requested_filter: dict[str, Any]) -> list[dict[str, Any]]:
        if not requested_filter.get("unit_key_includes") and not requested_filter.get("role_includes"):
            return self._dedup_records(staff)

        filtered = []
        for item in staff:
            unit_key = normalize_for_match(item.get("administrative_unit_name") or item.get("administrative_unit_key"))
            role = normalize_for_match(item.get("title_or_role"))
            unit_match = any(included in unit_key for included in requested_filter.get("unit_key_includes", ()))
            role_match = any(included in role for included in requested_filter.get("role_includes", ()))
            if unit_match or role_match:
                filtered.append(item)
        return self._dedup_records(filtered)

    def _answer_units(
        self,
        unit: dict[str, Any],
        administrative_units: list[dict[str, Any]],
        staff: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not administrative_units:
            return self._unit_data_missing_response(unit)

        staff_by_unit: dict[str, list[dict[str, Any]]] = {}
        for item in staff:
            staff_by_unit.setdefault(str(item.get("administrative_unit_key")), []).append(item)

        lines = [f"**{unit.get('parent_unit_name')} idari birimleri**"]
        for administrative_unit in administrative_units:
            unit_key = str(administrative_unit.get("administrative_unit_key") or "")
            unit_staff = staff_by_unit.get(unit_key, [])
            if not unit_staff:
                lines.append(
                    f"- Birim: {administrative_unit.get('administrative_unit_name')} | "
                    "Personel: Kaynak sayfada bu idari birim için personel kaydı yer almıyor."
                )
                continue
            names = ", ".join(self._person_display_name(item) for item in unit_staff)
            lines.append(f"- Birim: {administrative_unit.get('administrative_unit_name')} | Personel: {names}")

        source_url = unit.get("source_url")
        if source_url:
            lines.append(f"\nKaynak: {source_url}")
        return {"response": "\n".join(lines), "sources": self._unit_source(unit)}

    def _format_staff_response(self, unit: dict[str, Any], staff: list[dict[str, Any]], label: str) -> str:
        lines = [f"**{unit.get('parent_unit_name')} {label}**"]
        for item in staff:
            phone_text = self._phone_text(item)
            email_text = item.get("email") or "Kaynak sayfada yer almıyor."
            lines.append(
                "- "
                f"Birim: {item.get('administrative_unit_name') or unit.get('parent_unit_name')} | "
                f"Personel: {self._person_display_name(item)} | "
                f"Görev: {item.get('title_or_role') or 'Kaynak sayfada yer almıyor.'} | "
                f"Telefon: {phone_text} | "
                f"E-posta: {email_text}"
            )

        source_url = staff[0].get("source_url") or unit.get("source_url")
        if source_url:
            lines.append(f"\nKaynak: {source_url}")
        return "\n".join(lines)

    @staticmethod
    def _person_display_name(item: dict[str, Any]) -> str:
        return str(item.get("person_name") or "İsim kaynakta parse edilemedi")

    @staticmethod
    def _phone_text(item: dict[str, Any]) -> str:
        if item.get("phone"):
            return str(item["phone"])
        if (
            str(item.get("internal_extension") or "").strip() == "0000"
            or "placeholder_internal_extension_0000" in (item.get("validation_issues") or [])
        ):
            return "Kaynakta dahili 0000 görünüyor; geçerli telefon belirtilmemiş."
        if item.get("internal_extension"):
            return f"Dahili {item['internal_extension']}"
        return "Kaynak sayfada yer almıyor."

    @staticmethod
    def _dedup_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for record in records:
            key = str(
                record.get("staff_id")
                or f"{record.get('website_unit_id')}:{record.get('administrative_unit_id')}:{record.get('stable_staff_key')}"
            )
            by_key.setdefault(key, record)
        return list(by_key.values())

    @staticmethod
    def _ambiguous_unit_response(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        names = [str(candidate.get("parent_unit_name")) for candidate in candidates if candidate.get("parent_unit_name")]
        options = " / ".join(names)
        response = "Hangi fakülte/yüksekokulu sorduğunuzu netleştirir misiniz?"
        if options:
            response += f" Seçenekler: {options}."
        return {"response": response, "sources": []}

    def _unit_required_response(self) -> dict[str, Any]:
        candidates = self._unit_candidates()
        options = ", ".join(str(candidate.get("parent_unit_name")) for candidate in candidates if candidate.get("parent_unit_name"))
        response = "Hangi fakülte/yüksekokul için idari personel bilgisini istediğinizi belirtir misiniz?"
        if options:
            response += f" Bilinen birimler: {options}."
        return {"response": response, "sources": []}

    def _unit_data_missing_response(self, unit: dict[str, Any]) -> dict[str, Any]:
        response = f"{unit.get('parent_unit_name')} için idari personel bilgisi veritabanında bulunamadı."
        if unit.get("source_url"):
            response += f"\n\nKaynak: {unit.get('source_url')}"
        return {"response": response, "sources": self._unit_source(unit)}

    @staticmethod
    def _unsupported_unit_response() -> dict[str, Any]:
        return {
            "response": "Bu fakülte/yüksekokul için idari personel bilgisi veritabanında bulunamadı.",
            "sources": [],
        }

    def _not_found_response(self, unit: dict[str, Any], label: str) -> dict[str, Any]:
        response = f"{unit.get('parent_unit_name')} için {label} kaynak sayfada bulunamadı."
        if unit.get("source_url"):
            response += f"\n\nKaynak: {unit.get('source_url')}"
        return {"response": response, "sources": self._unit_source(unit)}

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
                "content": f"{unit.get('parent_unit_name')} idari personel kaynağı.",
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "idari_personel",
                "title": unit.get("parent_unit_name"),
                "doc_kind": "administrative_staff",
            })
        return sources

    @staticmethod
    def _unit_source(unit: dict[str, Any]) -> list[dict[str, Any]]:
        source_url = unit.get("source_url")
        if not source_url:
            return []
        return [{
            "content": f"{unit.get('parent_unit_name')} idari personel kaynağı.",
            "source_url": source_url,
            "source_public_url": source_url,
            "category": "idari_personel",
            "title": unit.get("parent_unit_name"),
            "doc_kind": "administrative_staff",
        }]

    @staticmethod
    def _format_checked_at(value: Any) -> str:
        text = str(value)
        if "T" in text:
            return text.split("T", 1)[0]
        return text.split(" ", 1)[0]


@lru_cache()
def get_administrative_staff_service() -> AdministrativeStaffService:
    return AdministrativeStaffService()
