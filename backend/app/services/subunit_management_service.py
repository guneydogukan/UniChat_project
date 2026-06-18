"""
ÜniChat — GİBTÜ bölüm/program alt birim yönetim DB-first cevap servisi.

Bu servis yalnız bölüm/program/alt birim yönetim intent'i algılandığında çalışır.
Veri yoksa RAG/LLM fallback'e düşmeden kontrollü yanıt üretir.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.subunit_management_repository import SubunitManagementRepository
from scrapers.subunit_management_scraper import DEFAULT_TARGETS, normalize_for_match

logger = logging.getLogger(__name__)

MIN_UNIT_MATCH_SCORE = 72
AMBIGUOUS_UNIT_SCORE_GAP = 12

MANAGEMENT_INTENT_RE = re.compile(
    r"\b("
    r"bölüm\s+başkan\w*|bolum\s+baskan\w*|"
    r"program\s+başkan\w*|program\s+baskan\w*|"
    r"başkan\w*|baskan\w*|"
    r"başkan\s+yardımc\w*|baskan\s+yardimc\w*|"
    r"yönetim\w*|yonetim\w*|yönetici\w*|yonetici\w*|"
    r"yönetim\s+kadrosu|yonetim\s+kadrosu|"
    r"müdür\w*|mudur\w*|dekan\w*|koordinatör\w*|koordinator\w*|"
    r"sorumlu\w*|kaynağ\w*|kaynag\w*|güncellenme|guncellenme|"
    r"hangi\s+bölüm|hangi\s+bolum|hangi\s+birim|bağlı|bagli"
    r")\b",
    re.IGNORECASE,
)

OUT_OF_SCOPE_GENERAL_MANAGEMENT_RE = re.compile(
    r"\b("
    r"dekan\w*|"
    r"fakülte\s+sekreter\w*|fakulte\s+sekreter\w*|"
    r"fakülte\s+yönetim\s+kurul\w*|fakulte\s+yonetim\s+kurul\w*|"
    r"fakülte\s+kurul\w*|fakulte\s+kurul\w*|"
    r"yüksekokul\s+müdür\w*|yuksekokul\s+mudur\w*|"
    r"yüksekokul\s+sekreter\w*|yuksekokul\s+sekreter\w*|"
    r"yüksekokul\s+yönetim\s+kurul\w*|yuksekokul\s+yonetim\s+kurul\w*|"
    r"idari\s+personel|idarî\s+personel|idari\s+kadro"
    r")\b",
    re.IGNORECASE,
)

GENERIC_SUBUNIT_RE = re.compile(
    r"\b("
    r"bölüm|bolum|program|birim|"
    r"bölüm\s+başkan|bolum\s+baskan|program\s+başkan|program\s+baskan|"
    r"yönetim\s+bilgi|yonetim\s+bilgi|yönetim\s+kadrosu|yonetim\s+kadrosu"
    r")\b",
    re.IGNORECASE,
)

CONTACT_QUERY_RE = re.compile(r"\b(e\s?posta|eposta|mail|telefon|dahili|iletişim|iletisim|ofis)\b", re.IGNORECASE)
SOURCE_QUERY_RE = re.compile(r"\b(kaynak|resmi|url|güncellenme|guncellenme|tarih)\b", re.IGNORECASE)
HIERARCHY_QUERY_RE = re.compile(r"\b(hangi\s+bölüm|hangi\s+bolum|hangi\s+birim|üst|ust|bağlı|bagli|altında|altinda)\b", re.IGNORECASE)

QUERY_NOISE_TOKENS: frozenset[str] = frozenset({
    "kim",
    "nedir",
    "neler",
    "hangi",
    "kac",
    "mi",
    "mı",
    "mu",
    "mü",
    "var",
    "yok",
    "goster",
    "göster",
    "getir",
    "bilgi",
    "bilgisi",
    "bilgileri",
    "kadrosu",
    "ekibi",
    "gorev",
    "görev",
    "gorevleri",
    "görevleri",
    "yonetim",
    "yönetim",
    "yoneticiler",
    "yöneticiler",
    "baskan",
    "başkan",
    "baskani",
    "başkanı",
    "yardimcisi",
    "yardımcısı",
    "program",
    "bolum",
    "bölüm",
    "birim",
    "altinda",
    "altında",
    "bagli",
    "bağlı",
})

UNIT_SUFFIXES: tuple[str, ...] = (
    " bolumu",
    " bolum",
    " programi",
    " program",
    " birimi",
    " birim",
)

ROLE_FILTERS: dict[str, tuple[str, ...]] = {
    "assistant": ("baskan yardim", "baskan yrd", "yardimci", "yardimcisi"),
    "head": ("bolum baskan", "program baskan", "baskan v", "baskani", "baskan"),
    "dean": ("dekan",),
    "director": ("mudur",),
    "coordinator": ("koordinator", "sorumlu"),
}


class SubunitManagementService:
    """Bölüm/program yönetim sorularını normalize DB kayıtlarından yanıtlar."""

    def __init__(self, repository: SubunitManagementRepository | None = None) -> None:
        self._repository = repository or SubunitManagementRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        normalized_question = normalize_for_match(question)
        if not self._looks_like_subunit_management_query(question, normalized_question):
            return None

        try:
            unit_match = self._resolve_unit_match(normalized_question)
            if unit_match["status"] == "ambiguous":
                return self._ambiguous_unit_response(unit_match["candidates"])
            if unit_match["status"] == "not_found":
                if self._is_generic_subunit_request(question, normalized_question):
                    return self._unit_required_response()
                return None

            unit = unit_match["unit"]
            if not unit:
                return self._unit_required_response()

            if HIERARCHY_QUERY_RE.search(normalized_question):
                return self._hierarchy_response(unit)

            records = []
            if unit.get("id"):
                records = self._repository.get_management_records(str(unit["id"]))
            records = self._dedup_records(records)
            requested_filter = self._requested_filter(normalized_question)
            filtered = self._filter_records(records, requested_filter)

            if SOURCE_QUERY_RE.search(normalized_question) and not filtered:
                return self._source_only_response(unit)

            if not filtered:
                return self._not_found_response(unit, requested_filter["label"])

            return {
                "response": self._format_response(unit, filtered, requested_filter["label"]),
                "sources": self._sources_from_records(filtered, unit),
            }
        except Exception as exc:  # noqa: BLE001 - yönetim bilgisinde canlı/RAG fallback yok
            logger.warning("Alt birim yönetim servisi DB yanıtı üretemedi: %s", exc, exc_info=True)
            return {
                "response": (
                    "* **Durum:** Bölüm/program yönetim verisi için ana kaynak ÜniChat DB'dir.\n"
                    "* **Sonuç:** Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi."
                ),
                "sources": [],
            }

    def _looks_like_subunit_management_query(self, original_question: str, normalized_question: str) -> bool:
        if self._is_out_of_scope_general_management_query(original_question, normalized_question):
            return False
        if not MANAGEMENT_INTENT_RE.search(original_question):
            return False
        if self._is_generic_subunit_request(original_question, normalized_question):
            return True
        return self._resolve_unit_match(normalized_question)["status"] != "not_found"

    @staticmethod
    def _is_out_of_scope_general_management_query(original_question: str, normalized_question: str) -> bool:
        if OUT_OF_SCOPE_GENERAL_MANAGEMENT_RE.search(original_question):
            return True
        has_subunit_anchor = any(token in normalized_question for token in ("bolum", "program"))
        if has_subunit_anchor:
            return False
        if "fakulte" in normalized_question and any(
            token in normalized_question for token in ("yonetim", "kurul", "sekreter", "dekan")
        ):
            return True
        if "yuksekokul" in normalized_question and any(
            token in normalized_question for token in ("yonetim", "kurul", "sekreter", "mudur")
        ):
            return True
        return False

    @staticmethod
    def _is_generic_subunit_request(original_question: str, normalized_question: str) -> bool:
        return bool(GENERIC_SUBUNIT_RE.search(original_question)) or any(
            phrase in normalized_question
            for phrase in (
                "bolum baskan",
                "program baskan",
                "bu bolum",
                "bu program",
                "ilgili birim",
                "yonetim kadrosu",
                "hangi bolum altinda",
                "hangi birime bagli",
            )
        )

    def _resolve_unit_match(self, normalized_question: str) -> dict[str, Any]:
        candidates = self._unit_candidates()
        scored: list[tuple[int, dict[str, Any]]] = []
        for candidate in candidates:
            score = self._unit_match_score(candidate, normalized_question)
            if score >= MIN_UNIT_MATCH_SCORE:
                scored.append((score, candidate))

        if not scored:
            return {"status": "not_found", "unit": None, "candidates": []}

        scored.sort(key=lambda item: (item[0], len(str(item[1].get("target_unit_name_normalized") or ""))), reverse=True)
        top_score, top_unit = scored[0]
        close_candidates = [
            candidate for score, candidate in scored
            if top_score - score <= AMBIGUOUS_UNIT_SCORE_GAP
        ]
        close_candidates = self._dedup_units(close_candidates)

        context_unit = self._disambiguate_by_context(normalized_question, close_candidates)
        if context_unit is not None:
            return {"status": "matched", "unit": context_unit, "candidates": [context_unit]}

        if len({self._unit_identity(candidate) for candidate in close_candidates}) > 1:
            return {"status": "ambiguous", "unit": None, "candidates": close_candidates}
        return {"status": "matched", "unit": top_unit, "candidates": [top_unit]}

    def _unit_candidates(self) -> list[dict[str, Any]]:
        rows_by_url: dict[str, dict[str, Any]] = {}
        try:
            for row in self._repository.list_targets():
                rows_by_url[str(row.get("source_url"))] = row
        except Exception:
            rows_by_url = {}

        candidates = []
        for target in DEFAULT_TARGETS:
            row = rows_by_url.get(target.source_url, {})
            aliases = list(target.aliases)
            aliases.extend(row.get("aliases") or [])
            candidates.append({
                "id": row.get("id"),
                "target_unit_name": row.get("target_unit_name") or target.target_unit_name,
                "target_unit_name_normalized": row.get("target_unit_name_normalized")
                or normalize_for_match(target.target_unit_name),
                "parent_unit_name": row.get("parent_unit_name") or target.parent_unit_name,
                "department_or_program_name": row.get("department_or_program_name") or target.department_or_program_name,
                "department_or_program_name_normalized": row.get("department_or_program_name_normalized")
                or normalize_for_match(target.department_or_program_name),
                "unit_type": row.get("unit_type") or target.unit_type,
                "scope_type": row.get("scope_type") or "department_program_management",
                "source_url": row.get("source_url") or target.source_url,
                "source_page_type": row.get("source_page_type") or target.source_page_type,
                "source_birim_id": row.get("source_birim_id") or target.birim_id,
                "aliases": aliases,
                "last_checked_at": row.get("last_checked_at"),
            })
        return candidates

    def _unit_match_score(self, unit: dict[str, Any], normalized_question: str) -> int:
        aliases = set(self._unit_aliases(unit))
        question_tokens = set(normalized_question.split())
        query_tokens = self._query_match_tokens(normalized_question)
        query_text = " ".join(query_tokens)
        best = 0
        for alias in aliases:
            if not alias:
                continue
            alias_tokens = [token for token in alias.split() if token not in {"ve", "ile"}]
            if len(alias_tokens) == 1:
                token = alias_tokens[0]
                if token in question_tokens and len(token) >= 2:
                    best = max(best, 120 + len(token))
                continue
            if f" {alias} " in f" {normalized_question} " or f" {alias} " in f" {query_text} ":
                best = max(best, 150 + min(len(alias), 40))
                continue
            fuzzy = self._alias_fuzzy_score(alias_tokens, query_tokens)
            best = max(best, fuzzy)
        return best

    def _unit_aliases(self, unit: dict[str, Any]) -> tuple[str, ...]:
        names = {
            str(unit.get("target_unit_name_normalized") or normalize_for_match(unit.get("target_unit_name"))),
            str(unit.get("department_or_program_name_normalized") or normalize_for_match(unit.get("department_or_program_name"))),
        }
        for alias in unit.get("aliases") or []:
            normalized_alias = normalize_for_match(alias)
            if normalized_alias:
                names.add(normalized_alias)
        generated: set[str] = set()
        for name in list(names):
            generated.add(name)
            for suffix in UNIT_SUFFIXES:
                if name.endswith(suffix):
                    generated.add(name[: -len(suffix)].strip())
            tokens = [token for token in name.split() if token and token not in {"ve", "ile"}]
            if len(tokens) >= 2:
                generated.add(" ".join(tokens[:2]))
                if len(tokens[0]) >= 5:
                    generated.add(tokens[0])
                acronym = "".join(token[0] for token in tokens if token not in {"bolumu", "programi", "birimi"})
                if len(acronym) >= 2:
                    generated.add(acronym)
        return tuple(alias for alias in names | generated if alias)

    @staticmethod
    def _query_match_tokens(normalized_question: str) -> list[str]:
        return [
            token
            for token in normalized_question.split()
            if token not in QUERY_NOISE_TOKENS and len(token) > 1 and not token.isdigit()
        ]

    @staticmethod
    def _alias_fuzzy_score(alias_tokens: list[str], query_tokens: list[str]) -> int:
        if not alias_tokens or not query_tokens:
            return 0
        matched_scores: list[int] = []
        used_indexes: set[int] = set()
        for alias_token in alias_tokens:
            best_score = 0
            best_index = -1
            for index, query_token in enumerate(query_tokens):
                if index in used_indexes:
                    continue
                score = SubunitManagementService._token_match_score(query_token, alias_token)
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_score and best_index >= 0:
                used_indexes.add(best_index)
                matched_scores.append(best_score)

        if not matched_scores:
            return 0
        coverage = len(matched_scores) / len(alias_tokens)
        if len(alias_tokens) == 1:
            if max(matched_scores) < 18:
                return 0
        elif len(alias_tokens) == 2:
            if coverage < 1.0:
                return 0
        elif coverage < 0.72:
            return 0
        return int(48 + sum(matched_scores) + coverage * 28 + min(len(" ".join(alias_tokens)), 24))

    @staticmethod
    def _token_match_score(query_token: str, alias_token: str) -> int:
        if query_token == alias_token:
            return 34
        if len(query_token) >= 3 and alias_token.startswith(query_token):
            return 28
        if len(alias_token) >= 4 and query_token.startswith(alias_token):
            return 24
        if len(query_token) < 4 or len(alias_token) < 4:
            return 0
        ratio = SequenceMatcher(None, query_token, alias_token).ratio()
        if ratio >= 0.86:
            return int(ratio * 26)
        return 0

    @staticmethod
    def _dedup_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for unit in units:
            key = SubunitManagementService._unit_identity(unit)
            by_key.setdefault(key, unit)
        return list(by_key.values())

    @staticmethod
    def _unit_identity(unit: dict[str, Any]) -> str:
        return str(unit.get("source_url") or unit.get("source_birim_id") or unit.get("target_unit_name"))

    @staticmethod
    def _disambiguate_by_context(normalized_question: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(candidates) < 2:
            return None
        tokens = set(normalized_question.split())
        if "program" in tokens or "programi" in tokens:
            program_candidates = [unit for unit in candidates if normalize_for_match(unit.get("unit_type")) == "program"]
            if len(program_candidates) == 1:
                return program_candidates[0]
        return None

    def _requested_filter(self, normalized_question: str) -> dict[str, Any]:
        if CONTACT_QUERY_RE.search(normalized_question):
            return {"label": "iletişim bilgileri"}
        if "baskan yardim" in normalized_question or "baskan yrd" in normalized_question:
            return {"label": "başkan yardımcısı", "role_includes": ROLE_FILTERS["assistant"]}
        if "program baskan" in normalized_question or "bolum baskan" in normalized_question:
            return {
                "label": "başkan bilgisi",
                "role_includes": ROLE_FILTERS["head"],
                "role_excludes": ROLE_FILTERS["assistant"],
            }
        if "dekan" in normalized_question:
            return {"label": "dekan bilgisi", "role_includes": ROLE_FILTERS["dean"]}
        if "mudur" in normalized_question:
            return {"label": "müdür bilgisi", "role_includes": ROLE_FILTERS["director"]}
        if "koordinator" in normalized_question or "sorumlu" in normalized_question:
            return {"label": "koordinatör/sorumlu bilgisi", "role_includes": ROLE_FILTERS["coordinator"]}
        return {"label": "yönetim bilgileri"}

    def _filter_records(self, records: list[dict[str, Any]], requested_filter: dict[str, Any]) -> list[dict[str, Any]]:
        includes = requested_filter.get("role_includes") or ()
        if not includes:
            return records
        filtered = []
        for record in records:
            role_text = normalize_for_match(record.get("management_role") or record.get("group_title"))
            if any(item in role_text for item in requested_filter.get("role_excludes") or ()):
                continue
            if any(item in role_text for item in includes):
                filtered.append(record)
        return filtered

    @staticmethod
    def _dedup_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for record in records:
            key = str(
                record.get("record_id")
                or f"{record.get('target_id')}:{record.get('management_role_key')}:{record.get('stable_person_key')}"
            )
            by_key.setdefault(key, record)
        return list(by_key.values())

    def _format_response(self, unit: dict[str, Any], records: list[dict[str, Any]], label: str) -> str:
        blocks: list[str] = []
        for record in records:
            lines = [
                f"* **Birim:** {record.get('target_unit_name') or unit.get('target_unit_name')}",
                f"* **Görev:** {record.get('management_role') or 'Kaynakta görev parse edilemedi.'}",
                f"* **Ad Soyad:** {record.get('full_display_name') or record.get('person_name') or 'Kaynakta isim parse edilemedi.'}",
            ]
            if record.get("email"):
                lines.append(f"* **E-posta:** {record['email']}")
            elif CONTACT_QUERY_RE.search(label):
                lines.append("* **E-posta:** Kaynak sayfada yer almıyor.")
            phone = self._display_phone(record.get("phone"))
            if phone:
                lines.append(f"* **Telefon:** {phone}")
            elif CONTACT_QUERY_RE.search(label):
                lines.append("* **Telefon:** Kaynak sayfada yer almıyor.")
            if record.get("office_location"):
                lines.append(f"* **Ofis:** {record['office_location']}")
            lines.append(f"* **Kaynak:** {record.get('source_url') or unit.get('source_url')}")
            if record.get("scraped_at"):
                lines.append(f"* **Son kontrol:** {self._format_checked_at(record.get('scraped_at'))}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _hierarchy_response(self, unit: dict[str, Any]) -> dict[str, Any]:
        parent = unit.get("parent_unit_name")
        lines = [
            f"* **Birim:** {unit.get('target_unit_name')}",
            f"* **Bölüm/Program:** {unit.get('department_or_program_name')}",
        ]
        if parent:
            lines.append(f"* **Üst Birim:** {parent}")
        else:
            lines.append("* **Üst Birim:** Bu hedef için üst birim metadata kaydı bulunmuyor.")
        if unit.get("source_url"):
            lines.append(f"* **Kaynak:** {unit.get('source_url')}")
        return {"response": "\n".join(lines), "sources": self._unit_source(unit)}

    def _source_only_response(self, unit: dict[str, Any]) -> dict[str, Any]:
        lines = [
            f"* **Birim:** {unit.get('target_unit_name')}",
            f"* **Kaynak:** {unit.get('source_url')}",
        ]
        if unit.get("last_checked_at"):
            lines.append(f"* **Son kontrol:** {self._format_checked_at(unit.get('last_checked_at'))}")
        return {"response": "\n".join(lines), "sources": self._unit_source(unit)}

    def _not_found_response(self, unit: dict[str, Any], label: str) -> dict[str, Any]:
        response = (
            f"* **Birim:** {unit.get('target_unit_name')}\n"
            f"* **Sonuç:** Bu bölüm/program için {label} veritabanında bulunamadı.\n"
            f"* **Kaynak:** {unit.get('source_url')}"
        )
        return {"response": response, "sources": self._unit_source(unit)}

    def _unit_required_response(self) -> dict[str, Any]:
        options = ", ".join(unit["target_unit_name"] for unit in self._unit_candidates())
        response = (
            "* **Durum:** Hangi bölüm veya programı kastettiğinizi netleştirir misiniz?\n"
            f"* **Bilinen seçenekler:** {options}"
        )
        return {"response": response, "sources": []}

    @staticmethod
    def _ambiguous_unit_response(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        options = ", ".join(str(unit.get("target_unit_name")) for unit in candidates if unit.get("target_unit_name"))
        response = (
            "* **Durum:** Sorgunuz birden fazla bölüm/programla eşleşiyor.\n"
            f"* **Lütfen netleştirin:** {options}"
        )
        return {"response": response, "sources": []}

    @staticmethod
    def _display_phone(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text or text == "0000":
            return None
        return f"Dahili {text}" if len(text) <= 5 else text

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
                "content": f"{unit.get('target_unit_name')} bölüm/program yönetim kaynağı.",
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "subunit_management",
                "title": unit.get("target_unit_name"),
                "doc_kind": "department_program_management",
            })
        return sources

    @staticmethod
    def _unit_source(unit: dict[str, Any]) -> list[dict[str, Any]]:
        source_url = unit.get("source_url")
        if not source_url:
            return []
        return [{
            "content": f"{unit.get('target_unit_name')} bölüm/program yönetim kaynağı.",
            "source_url": source_url,
            "source_public_url": source_url,
            "category": "subunit_management",
            "title": unit.get("target_unit_name"),
            "doc_kind": "department_program_management",
        }]

    @staticmethod
    def _format_checked_at(value: Any) -> str:
        text = str(value)
        if "T" in text:
            return text.split("T", 1)[0]
        return text.split(" ", 1)[0]


@lru_cache()
def get_subunit_management_service() -> SubunitManagementService:
    return SubunitManagementService()
