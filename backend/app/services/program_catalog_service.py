"""
ÜniChat — GİBTÜ bölüm/program katalog DB-first cevap servisi.

Bu servis yalnız akademik birim, bölüm ve program envanteri sorularını yanıtlar.
YÖK Atlas metrik soruları mevcut YokatlasQueryService akışında kalır.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.program_catalog_repository import ProgramCatalogRepository
from scrapers.program_catalog_scraper import normalize_for_match, normalize_program_name

logger = logging.getLogger(__name__)

METRIC_QUERY_RE = re.compile(
    r"\b("
    r"taban\s+puan\w*|kaç\s+puan\w*|kac\s+puan\w*|puan\s+tür\w*|puan\s+tur\w*|"
    r"başarı\s+sıra\w*|basari\s+sira\w*|sıralama\w*|siralama\w*|"
    r"kontenjan\w*|kontejan\w*|yerleş\w*|yerles\w*|ösym|osym|"
    r"özel\s+koşul\w*|ozel\s+kosul\w*|netleri|kaç\s+kişi|kac\s+kisi"
    r")\b",
    re.IGNORECASE,
)

CATALOG_SIGNAL_RE = re.compile(
    r"\b("
    r"fakülte\w*|fakulte\w*|yüksekokul\w*|yuksekokul\w*|myo|"
    r"meslek\s+yüksekokul\w*|meslek\s+yuksekokul\w*|enstitü\w*|enstitu\w*|"
    r"bölüm\w*|bolum\w*|program\w*|lisans|ön\s*lisans|on\s*lisans|onlisans|"
    r"hangi\s+birim|hangi\s+fakülte|hangi\s+fakulte|bünyesinde|bunyesinde|"
    r"var\s+mi|var\s+mı|yok\s+mu"
    r")\b",
    re.IGNORECASE,
)

LIST_WORD_RE = re.compile(r"\b(hangi|neler|nelerdir|liste|listesi|say|göster|goster)\b", re.IGNORECASE)
EXISTS_RE = re.compile(r"\b(var\s+mi|var\s+mı|mevcut\s+mu|bulunuyor\s+mu|yok\s+mu)\b", re.IGNORECASE)
UNIT_LOOKUP_RE = re.compile(r"\b(hangi\s+fakulte|hangi\s+fakülte|hangi\s+birim|nerede|nereye\s+bagli|nereye\s+bağlı|bünyesinde|bunyesinde)\b", re.IGNORECASE)

CATALOG_HARD_BLOCKER_RE = re.compile(
    r"\b("
    r"bölüm\s+başkan\w*|bolum\s+baskan\w*|başkan\w*|baskan\w*|"
    r"dekan\w*|müdür\w*|mudur\w*|müdürlük\w*|mudurluk\w*|"
    r"yönetim\w*|yonetim\w*|danışman\w*|danisman\w*|kurul\w*|"
    r"sekreter\w*|dekan\s+yardımc\w*|dekan\s+yardimc\w*|"
    r"müdür\s+yardımc\w*|mudur\s+yardimc\w*|"
    r"akademik\s+kadro\w*|hoca\w*|akademisyen\w*|"
    r"öğretim\s+üye\w*|ogretim\s+uye\w*|"
    r"öğretim\s+eleman\w*|ogretim\s+eleman\w*|"
    r"personel\s+kadro\w*|kadro\w*|"
    r"taban\s+puan\w*|kaç\s+puan\w*|kac\s+puan\w*|"
    r"başarı\s+sıra\w*|basari\s+sira\w*|sıralama\w*|siralama\w*|"
    r"puan\s+tür\w*|puan\s+tur\w*|ösym|osym|kontenjan\w*|"
    r"ders\s+kayd\w*|ders\s+kayit\w*|akademik\s+takvim|"
    r"yemek\w*|yemekhane\w*|ulaşım\w*|ulasim\w*|yurt\w*"
    r")\b",
    re.IGNORECASE,
)

CANDIDATE_OGRENIM_CONTEXT_RE = re.compile(
    r"#ogrenim|#ögrenim|#öğrenim|"
    r"\b(öğrenim|ogrenim)\s+(sayfa\w*|bölüm\w*|bolum\w*|program\w*|liste\w*)|"
    r"\b(aday\s+öğrenci\w*|aday\s+ogrenci\w*|aday\s+portal\w*|aday\s+sayfa\w*|tercih\s+sayfa\w*)\b"
    r".*\b(öğrenim|ogrenim|program\w*|bölüm\w*|bolum\w*|lisans|ön\s*lisans|on\s*lisans|onlisans|var\s+mı|var\s+mi)\b|"
    r"\b(öğrenim|ogrenim|program\w*|bölüm\w*|bolum\w*|lisans|ön\s*lisans|on\s*lisans|onlisans)\b"
    r".*\b(aday\s+öğrenci\w*|aday\s+ogrenci\w*|aday\s+portal\w*|aday\s+sayfa\w*|tercih\s+sayfa\w*)\b",
    re.IGNORECASE,
)

CANDIDATE_OGRENIM_CONTEXT_NORMALIZED_RE = re.compile(
    r"#ogrenim|"
    r"\bogrenim\s+(sayfa\w*|bolum\w*|program\w*|liste\w*)|"
    r"\b(aday\s+ogrenci\w*|aday\s+portal\w*|aday\s+sayfa\w*|tercih\s+sayfa\w*)\b"
    r".*\b(ogrenim|program\w*|bolum\w*|lisans|onlisans|var\s+mi)\b|"
    r"\b(ogrenim|program\w*|bolum\w*|lisans|onlisans)\b"
    r".*\b(aday\s+ogrenci\w*|aday\s+portal\w*|aday\s+sayfa\w*|tercih\s+sayfa\w*)\b"
)

CANDIDATE_NON_OGRENIM_RE = re.compile(
    r"\b("
    r"sık\s+sorulan|sik\s+sorulan|sss|"
    r"olanak\w*|imkan\w*|burs\w*|yurt\w*|barınma\w*|barinma\w*|"
    r"kampüs\w*|kampus\w*|ulaşım\w*|ulasim\w*|kayıt\s+hakk|kayit\s+hakk|"
    r"kayıt\s+bilg|kayit\s+bilg|tercih\s+rehber\w*|"
    r"kütüphane\w*|kutuphane\w*|erasmus|kariyer|iletişim|iletisim"
    r")\b",
    re.IGNORECASE,
)

NON_EXISTENT_PROGRAMS: frozenset[str] = frozenset({
    "hukuk",
    "hukuk fakultesi",
    "dis hekimligi",
    "diş hekimliği",
    "psikoloji",
})

NON_EXISTENT_PROGRAM_DISPLAY = {
    "hukuk": "Hukuk",
    "hukuk fakultesi": "Hukuk",
    "dis hekimligi": "Diş Hekimliği",
    "diş hekimliği": "Diş Hekimliği",
    "psikoloji": "Psikoloji",
}

QUERY_NOISE_TOKENS: frozenset[str] = frozenset({
    "gibtu",
    "gibtunun",
    "gibtude",
    "gaziantep",
    "islam",
    "bilim",
    "teknoloji",
    "universitesi",
    "universite",
    "universitede",
    "universitedeki",
    "universitenin",
    "de",
    "da",
    "te",
    "ta",
    "hangi",
    "neler",
    "nelerdir",
    "nedir",
    "mi",
    "mı",
    "mu",
    "mü",
    "var",
    "yok",
    "bolum",
    "bolumu",
    "bolumler",
    "bolumleri",
    "program",
    "programi",
    "programlar",
    "programlari",
    "fakulte",
    "fakultesi",
    "birim",
    "birimde",
    "bunyesinde",
    "lisans",
    "onlisans",
    "on",
    "myo",
})

CANDIDATE_CONTEXT_NOISE_TOKENS: frozenset[str] = frozenset({
    "aday",
    "ogrenci",
    "ogrenim",
    "ogreniminde",
    "ogrenimde",
    "ogrenimindeki",
    "sayfa",
    "sayfasi",
    "sayfasinda",
    "sayfasina",
    "sayfasindaki",
    "sayfadaki",
    "portal",
    "portalindaki",
    "portalinda",
    "tercih",
    "bolumunde",
    "bolumundeki",
    "kaynak",
    "kaynagina",
    "gore",
})

UNIT_TYPE_LABELS = {
    "faculty": "fakülte",
    "school": "yüksekokul",
    "vocational_school": "meslek yüksekokulu",
    "institute": "enstitü",
}

EDUCATION_LABELS = {
    "undergraduate": "lisans",
    "associate": "ön lisans",
    "graduate": "lisansüstü",
    "prep": "hazırlık",
    "unknown": "program",
}

MIN_ENTRY_MATCH_SCORE = 76
AMBIGUOUS_SCORE_GAP = 10


class ProgramCatalogInMemoryRepository:
    """Dry-run ve test için report dict üzerinden repository arayüzü."""

    def __init__(self, units: list[dict[str, Any]], entries: list[dict[str, Any]]) -> None:
        self._units = units
        self._entries = entries

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "ProgramCatalogInMemoryRepository":
        units = []
        for unit in report.get("units") or []:
            units.append({
                "id": unit.get("normalized_unit_name"),
                "unit_name": unit.get("unit_name"),
                "normalized_unit_name": unit.get("normalized_unit_name"),
                "unit_type": unit.get("unit_type"),
                "source_url": unit.get("source_url"),
                "official_gibtu_url": unit.get("official_gibtu_url"),
                "match_status": unit.get("match_status"),
                "needs_review": unit.get("needs_review"),
                "missing_in_current_run": unit.get("missing_in_current_run"),
                "aliases": unit.get("aliases") or [],
            })
        entries = []
        for record in report.get("records") or []:
            entries.append({
                "id": f"{record.get('normalized_unit_name')}:{record.get('normalized_program_name')}",
                "item_kind": record.get("item_kind"),
                "program_name": record.get("program_name"),
                "normalized_program_name": record.get("normalized_program_name"),
                "education_level": record.get("education_level"),
                "source_url": record.get("source_url"),
                "official_gibtu_url": record.get("official_gibtu_url"),
                "yokatlas_url": record.get("yokatlas_url"),
                "program_code": record.get("program_code"),
                "match_status": record.get("match_status"),
                "needs_review": record.get("needs_review"),
                "missing_in_current_run": record.get("missing_in_current_run"),
                "unit_id": record.get("normalized_unit_name"),
                "unit_name": record.get("unit_name"),
                "normalized_unit_name": record.get("normalized_unit_name"),
                "unit_type": "vocational_school" if record.get("education_level") == "associate" else "faculty",
                "aliases": record.get("aliases") or [],
            })
        return cls(units, entries)

    def list_units(self) -> list[dict[str, Any]]:
        return list(self._units)

    def list_catalog_entries(self) -> list[dict[str, Any]]:
        return list(self._entries)


class ProgramCatalogService:
    """Akademik birim/bölüm/program envanteri sorularını DB-first yanıtlar."""

    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository or ProgramCatalogRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        normalized_question = normalize_for_match(question)
        if self._has_catalog_hard_blocker(question):
            return None

        candidate_context = self._is_candidate_ogrenim_context(question, normalized_question)
        if not self._looks_like_catalog_query(question, normalized_question, candidate_context):
            return None

        try:
            units = self._repository.list_units()
            entries = self._repository.list_catalog_entries()
        except Exception as exc:  # noqa: BLE001 - katalogda canlı/RAG fallback yok
            logger.warning("Program katalog DB yanıtı üretilemedi: %s", exc, exc_info=True)
            return self._response(
                "Bölüm/program katalog verisi için ana kaynak ÜniChat DB'dir. Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi.",
                [],
                "db_unavailable",
                normalized_question,
                "db_unavailable",
            )

        units = self._visible_units(units, candidate_context=candidate_context)
        entries = self._visible_entries(entries, candidate_context=candidate_context)

        if not units and not entries:
            if not candidate_context:
                return None
            return self._response(
                "Aday öğrenci Öğrenim verisi DB'de bulunamadı; tahmini yanıt üretilmedi.",
                [],
                "not_found",
                normalized_question,
                "empty_catalog",
            )

        if self._is_ambiguous_health_query(normalized_question):
            return self._response(
                "Sağlık alanıyla ilgili birden fazla birim olabilir. Sağlık Bilimleri Fakültesi bölümlerini mi, yoksa Sağlık Hizmetleri Meslek Yüksekokulu programlarını mı sormak istiyorsunuz?",
                [],
                "ambiguous_program_query",
                normalized_question,
                "clarification_required",
            )

        intent = classify_program_catalog_intent(question, normalized_question)
        unit_match = self._resolve_unit(normalized_question, units)
        if unit_match["status"] == "ambiguous":
            return self._ambiguous_units(unit_match["candidates"], normalized_question)
        unit = unit_match.get("unit")

        entry_match = self._resolve_entry(normalized_question, entries)
        if entry_match["status"] == "ambiguous":
            if EXISTS_RE.search(normalized_question):
                candidate_multi = self._candidate_same_name_exists_response(entry_match["candidates"], normalized_question)
                if candidate_multi:
                    return candidate_multi
            return self._ambiguous_entries(entry_match["candidates"], normalized_question)
        entry = entry_match.get("entry")

        if unit and self._asks_if_unit_is_department(normalized_question):
            return self._unit_type_response(unit, normalized_question)

        if unit and self._is_unit_children_query(normalized_question):
            child_kind = "program" if unit.get("unit_type") == "vocational_school" else "department"
            return self._format_unit_children(unit, entries, child_kind, normalized_question)

        if entry and self._is_entry_unit_lookup(normalized_question):
            return self._entry_unit_response(entry, normalized_question)

        if EXISTS_RE.search(normalized_question):
            if entry:
                return self._entry_exists_response(entry, normalized_question)
            requested_name = self._extract_requested_name(normalized_question)
            return self._not_found_exists_response(
                requested_name,
                normalized_question,
                candidate_scope=candidate_context,
            )

        if intent == "faculty_list_query":
            return self._format_unit_list(units, "faculty", intent, normalized_question)
        if intent == "school_list_query":
            return self._format_unit_list(units, "school", intent, normalized_question)
        if intent == "vocational_school_list_query":
            return self._format_unit_list(units, "vocational_school", intent, normalized_question)
        if intent == "institute_list_query":
            return self._format_unit_list(units, "institute", intent, normalized_question)
        if intent == "academic_unit_list_query":
            return self._format_all_units(units, intent, normalized_question)
        if intent == "undergraduate_programs_query":
            return self._format_level_list(entries, "undergraduate", intent, normalized_question)
        if intent == "associate_degree_programs_query":
            return self._format_level_list(entries, "associate", intent, normalized_question)

        if intent in {"department_list_query", "program_list_query"}:
            return self._format_all_entries(entries, intent, normalized_question)

        if entry:
            return self._entry_exists_response(entry, normalized_question)

        if unit:
            return self._unit_type_response(unit, normalized_question)

        return None

    @staticmethod
    def _has_catalog_hard_blocker(original_question: str) -> bool:
        return bool(CATALOG_HARD_BLOCKER_RE.search(original_question))

    @staticmethod
    def _is_candidate_ogrenim_context(original_question: str, normalized_question: str) -> bool:
        if CANDIDATE_NON_OGRENIM_RE.search(original_question):
            return False
        return bool(
            CANDIDATE_OGRENIM_CONTEXT_RE.search(original_question)
            or CANDIDATE_OGRENIM_CONTEXT_NORMALIZED_RE.search(normalized_question)
        )

    def _looks_like_catalog_query(
        self,
        original_question: str,
        normalized_question: str,
        candidate_context: bool = False,
    ) -> bool:
        if METRIC_QUERY_RE.search(original_question):
            return False
        if candidate_context:
            return True
        if CATALOG_SIGNAL_RE.search(original_question):
            return True
        return bool(EXISTS_RE.search(normalized_question) and self._contains_nonexistent_guard(normalized_question))

    @staticmethod
    def _contains_nonexistent_guard(normalized_question: str) -> bool:
        return any(f" {guard} " in f" {normalized_question} " for guard in NON_EXISTENT_PROGRAMS)

    @staticmethod
    def _visible_units(units: list[dict[str, Any]], candidate_context: bool = False) -> list[dict[str, Any]]:
        return [
            unit for unit in units
            if unit.get("match_status") != "candidate_only"
            and unit.get("db_first_answerable", True) is not False
            and (ProgramCatalogService._is_candidate_unit(unit) if candidate_context else not ProgramCatalogService._is_candidate_unit(unit))
        ]

    @staticmethod
    def _visible_entries(entries: list[dict[str, Any]], candidate_context: bool = False) -> list[dict[str, Any]]:
        return [
            entry for entry in entries
            if entry.get("match_status") != "candidate_only"
            and entry.get("db_first_answerable", True) is not False
            and (ProgramCatalogService._is_candidate_entry(entry) if candidate_context else not ProgramCatalogService._is_candidate_entry(entry))
        ]

    @staticmethod
    def _is_ambiguous_health_query(normalized_question: str) -> bool:
        return (
            "saglik" in normalized_question
            and "bilimleri" not in normalized_question
            and "hizmetleri" not in normalized_question
            and ("bolum" in normalized_question or "program" in normalized_question or "neler" in normalized_question)
        )

    @staticmethod
    def _asks_if_unit_is_department(normalized_question: str) -> bool:
        return "bolum mu" in normalized_question or "program mi" in normalized_question or "bolum mudur" in normalized_question

    @staticmethod
    def _is_unit_children_query(normalized_question: str) -> bool:
        return bool(LIST_WORD_RE.search(normalized_question)) and (
            "bolum" in normalized_question or "program" in normalized_question or "neler" in normalized_question
        )

    @staticmethod
    def _is_entry_unit_lookup(normalized_question: str) -> bool:
        return bool(UNIT_LOOKUP_RE.search(normalized_question)) or (
            "hangi" in normalized_question
            and ("fak" in normalized_question or "birim" in normalized_question)
        )

    def _resolve_unit(self, normalized_question: str, units: list[dict[str, Any]]) -> dict[str, Any]:
        scored: list[tuple[int, dict[str, Any]]] = []
        query_tokens = self._query_tokens(normalized_question)
        for unit in units:
            score = self._name_score(unit.get("unit_name"), unit.get("aliases") or [], normalized_question, query_tokens)
            if score >= MIN_ENTRY_MATCH_SCORE:
                scored.append((score, unit))
        return self._resolve_scored(scored, "unit")

    def _resolve_entry(self, normalized_question: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if self._contains_nonexistent_guard(normalized_question):
            return {"status": "not_found", "entry": None, "candidates": []}
        scored: list[tuple[int, dict[str, Any]]] = []
        query_tokens = self._query_tokens(normalized_question)
        for entry in entries:
            score = self._name_score(entry.get("program_name"), entry.get("aliases") or [], normalized_question, query_tokens)
            if score >= MIN_ENTRY_MATCH_SCORE:
                scored.append((score, entry))
        return self._resolve_scored(scored, "entry")

    @staticmethod
    def _resolve_scored(scored: list[tuple[int, dict[str, Any]]], result_key: str) -> dict[str, Any]:
        if not scored:
            return {"status": "not_found", result_key: None, "candidates": []}
        scored.sort(key=lambda item: (item[0], len(str(item[1].get("program_name") or item[1].get("unit_name") or ""))), reverse=True)
        top_score = scored[0][0]
        close = [item for score, item in scored if top_score - score <= AMBIGUOUS_SCORE_GAP]
        identities = {
            str(item.get("id") or f"{item.get('unit_name')}:{item.get('program_name')}")
            for item in close
        }
        if len(identities) > 1:
            return {"status": "ambiguous", result_key: None, "candidates": close}
        return {"status": "matched", result_key: scored[0][1], "candidates": [scored[0][1]]}

    @staticmethod
    def _name_score(
        name: Any,
        aliases: list[Any],
        normalized_question: str,
        query_tokens: list[str],
    ) -> int:
        alias_values = {normalize_program_name(name), normalize_for_match(name)}
        alias_values.update(normalize_for_match(alias) for alias in aliases)
        alias_values.discard("")
        question_tokens = set(normalized_question.split())
        best = 0
        for alias in alias_values:
            tokens = alias.split()
            if len(tokens) == 1 and len(alias) <= 4:
                if alias in question_tokens:
                    best = max(best, 150 + len(alias))
                continue
            if f" {alias} " in f" {normalized_question} ":
                best = max(best, 140 + min(len(alias), 40))
                continue
            best = max(best, ProgramCatalogService._fuzzy_score(tokens, query_tokens))
        return best

    @staticmethod
    def _fuzzy_score(alias_tokens: list[str], query_tokens: list[str]) -> int:
        if not alias_tokens or not query_tokens:
            return 0
        matched: list[int] = []
        used: set[int] = set()
        for alias_token in [token for token in alias_tokens if token not in {"ve", "ile"}]:
            best = 0
            best_index = -1
            for index, query_token in enumerate(query_tokens):
                if index in used:
                    continue
                score = ProgramCatalogService._token_score(query_token, alias_token)
                if score > best:
                    best = score
                    best_index = index
            if best and best_index >= 0:
                matched.append(best)
                used.add(best_index)
        if not matched:
            return 0
        coverage = len(matched) / max(len(alias_tokens), 1)
        if len(alias_tokens) >= 2 and coverage < 0.75:
            return 0
        return int(48 + sum(matched) + coverage * 28 + min(len(" ".join(alias_tokens)), 28))

    @staticmethod
    def _token_score(query_token: str, alias_token: str) -> int:
        if query_token == alias_token:
            return 34
        if len(query_token) >= 3 and alias_token.startswith(query_token):
            return 27
        if len(alias_token) >= 4 and query_token.startswith(alias_token):
            return 24
        if len(query_token) < 4 or len(alias_token) < 4:
            return 0
        ratio = SequenceMatcher(None, query_token, alias_token).ratio()
        return int(ratio * 24) if ratio >= 0.86 else 0

    @staticmethod
    def _query_tokens(normalized_question: str) -> list[str]:
        return [
            token
            for token in normalized_question.split()
            if token not in QUERY_NOISE_TOKENS and len(token) > 1 and not token.isdigit()
        ]

    @staticmethod
    def _is_candidate_entry(entry: dict[str, Any]) -> bool:
        return entry.get("source_type") == "candidate_page_ogrenim" or entry.get("answer_scope") == "candidate_page_only"

    @staticmethod
    def _is_candidate_unit(unit: dict[str, Any]) -> bool:
        return unit.get("source_type") == "candidate_page_ogrenim" or unit.get("answer_scope") == "candidate_page_only"

    @staticmethod
    def _all_candidate_entries(entries: list[dict[str, Any]]) -> bool:
        return bool(entries) and all(ProgramCatalogService._is_candidate_entry(entry) for entry in entries)

    @staticmethod
    def _candidate_scope_note() -> str:
        return "Kaynak: aday öğrenci öğrenim verisi."

    def _candidate_same_name_exists_response(
        self,
        candidates: list[dict[str, Any]],
        normalized_query: str,
    ) -> dict[str, Any] | None:
        candidate_entries = [entry for entry in candidates if self._is_candidate_entry(entry)]
        if len(candidate_entries) < 2:
            return None
        normalized_names = {entry.get("normalized_program_name") for entry in candidate_entries}
        if len(normalized_names) != 1:
            return None
        program_name = str(candidate_entries[0].get("program_name") or "Bu kayıt")
        lines = [f"Aday öğrenci Öğrenim bölümünde {program_name} birden fazla bağlamda listeleniyor:"]
        for entry in sorted(candidate_entries, key=lambda item: (str(item.get("education_level")), str(item.get("unit_name")))):
            level = EDUCATION_LABELS.get(str(entry.get("education_level")), str(entry.get("education_level") or "program"))
            lines.append(f"- {level}: {entry.get('unit_name')}")
        lines.extend(["", self._candidate_scope_note()])
        return self._response(
            "\n".join(lines),
            self._sources_from_entries(candidate_entries),
            "program_exists_query",
            normalized_query,
            "matched",
        )

    def _format_unit_list(
        self,
        units: list[dict[str, Any]],
        unit_type: str,
        intent: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        selected = [unit for unit in units if unit.get("unit_type") == unit_type]
        label = UNIT_TYPE_LABELS[unit_type]
        if not selected:
            return self._response(f"GİBTÜ katalog DB'sinde {label} kaydı bulunamadı.", [], intent, normalized_query, "not_found")
        lines = [f"GİBTÜ'deki {label} kayıtları şunlardır:", ""]
        lines.extend(f"- {unit['unit_name']}" for unit in selected)
        return self._response("\n".join(lines), self._sources_from_units(selected), intent, normalized_query, "list")

    def _format_all_units(self, units: list[dict[str, Any]], intent: str, normalized_query: str) -> dict[str, Any]:
        lines = ["GİBTÜ'deki akademik birimler:"]
        for unit_type in ("faculty", "school", "vocational_school", "institute"):
            selected = [unit for unit in units if unit.get("unit_type") == unit_type]
            if not selected:
                continue
            lines.extend(["", f"{UNIT_TYPE_LABELS[unit_type].title()}:", *[f"- {unit['unit_name']}" for unit in selected]])
        return self._response("\n".join(lines), self._sources_from_units(units), intent, normalized_query, "list")

    def _format_level_list(
        self,
        entries: list[dict[str, Any]],
        level: str,
        intent: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        selected = [entry for entry in entries if entry.get("education_level") == level]
        label = EDUCATION_LABELS[level]
        if not selected:
            return self._response(f"GİBTÜ katalog DB'sinde {label} programı bulunamadı.", [], intent, normalized_query, "not_found")
        grouped = self._group_by_unit(selected)
        if self._all_candidate_entries(selected):
            lines = [f"Aday öğrenci Öğrenim bölümünde listelenen {label} kayıtları:"]
        else:
            lines = [f"GİBTÜ'deki {label} programları:"]
        for unit_name, unit_entries in grouped.items():
            lines.extend(["", f"{unit_name}:", *[f"- {entry['program_name']}" for entry in unit_entries]])
        if self._all_candidate_entries(selected):
            lines.extend(["", self._candidate_scope_note()])
        return self._response("\n".join(lines), self._sources_from_entries(selected), intent, normalized_query, "list")

    def _format_unit_children(
        self,
        unit: dict[str, Any],
        entries: list[dict[str, Any]],
        child_kind: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        selected = [
            entry for entry in entries
            if entry.get("normalized_unit_name") == unit.get("normalized_unit_name")
        ]
        if child_kind == "department":
            selected = [entry for entry in selected if entry.get("education_level") != "associate"]
            label = "bölümler"
            intent = "faculty_departments_query"
        else:
            selected = [entry for entry in selected if entry.get("education_level") == "associate"]
            label = "programlar"
            intent = "vocational_school_programs_query"
        if not selected:
            return self._response(
                f"{unit.get('unit_name')} için katalog DB'sinde {label} bulunamadı.",
                self._sources_from_units([unit]),
                intent,
                normalized_query,
                "not_found",
            )
        if self._all_candidate_entries(selected):
            lines = [f"Aday öğrenci Öğrenim bölümünde {unit.get('unit_name')} altında listelenen {label} şunlardır:", ""]
        else:
            lines = [f"GİBTÜ {unit.get('unit_name')} bünyesindeki {label} şunlardır:", ""]
        lines.extend(f"- {entry['program_name']}" for entry in selected)
        if self._all_candidate_entries(selected):
            lines.extend(["", self._candidate_scope_note()])
        return self._response("\n".join(lines), self._sources_from_entries(selected), intent, normalized_query, "unit_children")

    def _format_all_entries(self, entries: list[dict[str, Any]], intent: str, normalized_query: str) -> dict[str, Any]:
        if not entries:
            return self._response("GİBTÜ katalog DB'sinde bölüm/program kaydı bulunamadı.", [], intent, normalized_query, "not_found")
        grouped = self._group_by_unit(entries)
        if self._all_candidate_entries(entries):
            lines = ["Aday öğrenci Öğrenim bölümünde listelenen bölüm/program/kart kayıtları:"]
        else:
            lines = ["GİBTÜ'deki bölüm/program kayıtları:"]
        for unit_name, unit_entries in grouped.items():
            lines.extend(["", f"{unit_name}:", *[f"- {entry['program_name']}" for entry in unit_entries]])
        if self._all_candidate_entries(entries):
            lines.extend(["", self._candidate_scope_note()])
        return self._response("\n".join(lines), self._sources_from_entries(entries), intent, normalized_query, "list")

    @staticmethod
    def _group_by_unit(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            grouped.setdefault(str(entry.get("unit_name")), []).append(entry)
        return grouped

    def _entry_exists_response(self, entry: dict[str, Any], normalized_query: str) -> dict[str, Any]:
        if self._is_candidate_entry(entry):
            level = EDUCATION_LABELS.get(str(entry.get("education_level")), str(entry.get("education_level") or "program"))
            response = (
                f"Aday öğrenci Öğrenim bölümünde {entry.get('program_name')}, "
                f"{entry.get('unit_name')} altında {level} kaydı olarak listeleniyor. "
                f"{self._candidate_scope_note()}"
            )
            return self._response(response, self._sources_from_entries([entry]), "program_exists_query", normalized_query, "matched", matched_entry=entry)
        label = "program" if entry.get("education_level") == "associate" else "bölüm/program"
        response = f"Evet. {entry.get('program_name')}, GİBTÜ {entry.get('unit_name')} bünyesinde yer alan bir {label} kaydıdır."
        return self._response(response, self._sources_from_entries([entry]), "program_exists_query", normalized_query, "matched", matched_entry=entry)

    def _entry_unit_response(self, entry: dict[str, Any], normalized_query: str) -> dict[str, Any]:
        if self._is_candidate_entry(entry):
            response = (
                f"Aday öğrenci Öğrenim bölümünde {entry.get('program_name')}, "
                f"{entry.get('unit_name')} altında listeleniyor. {self._candidate_scope_note()}"
            )
            return self._response(response, self._sources_from_entries([entry]), "program_faculty_query", normalized_query, "matched", matched_entry=entry)
        response = f"{entry.get('program_name')}, {entry.get('unit_name')} bünyesindedir."
        return self._response(response, self._sources_from_entries([entry]), "program_faculty_query", normalized_query, "matched", matched_entry=entry)

    def _not_found_exists_response(self, requested_name: str, normalized_query: str, candidate_scope: bool = False) -> dict[str, Any]:
        display = self._nonexistent_display_name(normalized_query) or (requested_name.title() if requested_name else "Bu bölüm/program")
        if candidate_scope:
            return self._response(
                f"Aday öğrenci Öğrenim bölümünde {display} kaydı bulunamadı; bu, üniversitede kesin yoktur anlamına gelmez.",
                [],
                "program_exists_query",
                normalized_query,
                "not_found",
            )
        return self._response(
            f"Mevcut GİBTÜ bölüm/program envanterinde {display} kaydı bulunmuyor.",
            [],
            "program_exists_query",
            normalized_query,
            "not_found",
        )

    @staticmethod
    def _nonexistent_display_name(normalized_query: str) -> str | None:
        for guard, display in NON_EXISTENT_PROGRAM_DISPLAY.items():
            if f" {guard} " in f" {normalized_query} ":
                return display
        return None

    def _unit_type_response(self, unit: dict[str, Any], normalized_query: str) -> dict[str, Any]:
        label = UNIT_TYPE_LABELS.get(str(unit.get("unit_type")), "akademik birim")
        if unit.get("unit_type") in {"school", "vocational_school", "institute", "faculty"}:
            response = f"{unit.get('unit_name')} bölüm/program değil; GİBTÜ'de bir {label} olarak kayıtlıdır."
        else:
            response = f"{unit.get('unit_name')} GİBTÜ katalog DB'sinde {label} olarak kayıtlıdır."
        return self._response(response, self._sources_from_units([unit]), "academic_unit_list_query", normalized_query, "matched")

    @staticmethod
    def _extract_requested_name(normalized_question: str) -> str:
        tokens = [
            token for token in normalized_question.split()
            if token not in QUERY_NOISE_TOKENS
            and token not in CANDIDATE_CONTEXT_NOISE_TOKENS
            and token not in {"var", "yok"}
        ]
        return " ".join(tokens).strip()

    def _ambiguous_units(self, units: list[dict[str, Any]], normalized_query: str) -> dict[str, Any]:
        options = ", ".join(str(unit.get("unit_name")) for unit in units[:5])
        return self._response(
            f"Sorgunuz birden fazla akademik birimle eşleşiyor. Hangisini kastettiğinizi belirtir misiniz? {options}.",
            [],
            "ambiguous_program_query",
            normalized_query,
            "clarification_required",
        )

    def _ambiguous_entries(self, entries: list[dict[str, Any]], normalized_query: str) -> dict[str, Any]:
        options = ", ".join(f"{entry.get('program_name')} ({entry.get('unit_name')})" for entry in entries[:5])
        return self._response(
            f"Sorgunuz birden fazla bölüm/programla eşleşiyor. Hangisini kastettiğinizi belirtir misiniz? {options}.",
            [],
            "ambiguous_program_query",
            normalized_query,
            "clarification_required",
        )

    @staticmethod
    def _sources_from_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources = []
        seen: set[str] = set()
        for unit in units:
            url = unit.get("official_gibtu_url") or unit.get("source_url")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({
                "content": f"{unit.get('unit_name')} akademik birim kaydı.",
                "source_url": url,
                "source_public_url": url,
                "category": "program_catalog",
                "title": unit.get("unit_name"),
                "doc_kind": "academic_unit",
            })
        return sources

    @staticmethod
    def _sources_from_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources = []
        seen: set[str] = set()
        for entry in entries:
            if ProgramCatalogService._is_candidate_entry(entry):
                url = entry.get("source_url")
                if url and url not in seen:
                    seen.add(url)
                    sources.append({
                        "content": f"{entry.get('program_name')} aday öğrenci Öğrenim sayfası kaydı.",
                        "source_url": url,
                        "source_public_url": url,
                        "detail_url": entry.get("detail_url") or entry.get("program_card_link"),
                        "category": "program_catalog_candidate",
                        "title": entry.get("program_name"),
                        "doc_kind": "candidate_ogrenim_entry",
                    })
                continue
            for url in (entry.get("official_gibtu_url"), entry.get("yokatlas_url"), entry.get("source_url")):
                if not url or url in seen:
                    continue
                seen.add(url)
                sources.append({
                    "content": f"{entry.get('program_name')} katalog kaydı.",
                    "source_url": url,
                    "source_public_url": url,
                    "category": "program_catalog",
                    "title": entry.get("program_name"),
                    "doc_kind": "program_catalog_entry",
                })
                break
        return sources

    @staticmethod
    def _response(
        response: str,
        sources: list[dict[str, Any]],
        intent: str,
        normalized_query: str,
        match_method: str,
        matched_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "response": response,
            "sources": sources,
            "metadata": {
                "db_first": True,
                "service": "program_catalog_service",
                "intent": intent,
                "normalized_query": normalized_query,
                "match_method": match_method,
                "matched_program_name": matched_entry.get("program_name") if matched_entry else None,
                "matched_unit_name": matched_entry.get("unit_name") if matched_entry else None,
                "rag_fallback_used": False,
            },
        }


def classify_program_catalog_intent(original_question: str, normalized_question: str | None = None) -> str | None:
    normalized = normalized_question or normalize_for_match(original_question)
    if "meslek yuksekokul" in normalized or "myo" in normalized:
        if LIST_WORD_RE.search(original_question) and "program" not in normalized:
            return "vocational_school_list_query"
    if "yuksekokul" in normalized and "meslek" not in normalized:
        if LIST_WORD_RE.search(original_question) and "program" not in normalized and "bolum" not in normalized:
            return "school_list_query"
    if "fakulte" in normalized and LIST_WORD_RE.search(original_question) and "bolum" not in normalized:
        return "faculty_list_query"
    if "enstitu" in normalized and LIST_WORD_RE.search(original_question):
        return "institute_list_query"
    if "akademik birim" in normalized:
        return "academic_unit_list_query"
    if ("onlisans" in normalized or "on lisans" in normalized) and LIST_WORD_RE.search(original_question):
        return "associate_degree_programs_query"
    if "lisans" in normalized and "onlisans" not in normalized and "on lisans" not in normalized and LIST_WORD_RE.search(original_question):
        return "undergraduate_programs_query"
    if "program" in normalized and LIST_WORD_RE.search(original_question):
        return "program_list_query"
    if "bolum" in normalized and LIST_WORD_RE.search(original_question):
        return "department_list_query"
    if EXISTS_RE.search(original_question):
        return "program_exists_query"
    if UNIT_LOOKUP_RE.search(original_question):
        return "program_faculty_query"
    if CATALOG_SIGNAL_RE.search(original_question):
        return "ambiguous_program_query"
    return None


@lru_cache()
def get_program_catalog_service() -> ProgramCatalogService:
    return ProgramCatalogService()


__all__ = [
    "ProgramCatalogInMemoryRepository",
    "ProgramCatalogService",
    "classify_program_catalog_intent",
    "get_program_catalog_service",
]
