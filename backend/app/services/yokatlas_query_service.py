"""
UniChat — YÖK Atlas tercih/yerleşme DB-first yanıt servisi.

Bu servis canlı YÖK Atlas isteği atmaz ve veri yazmaz. Chatbot'un tercih,
yerleşme, kontenjan, taban puan ve program sorularını RAG'e gitmeden önce
mevcut `yokatlas_*` tablolarından yanıtlaması için kullanılır.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.yokatlas_query_repository import YokatlasQueryRepository

logger = logging.getLogger(__name__)

OSYM_CODE_RE = re.compile(r"\b\d{9}\b")

YOKATLAS_TRIGGER_RE = re.compile(
    r"\b("
    r"yök\s*atlas|yok\s*atlas|tercih|yerleş\w*|yerles\w*|"
    r"kontenjan|kontejan|taban\s+puan|başarı\s+sıra|basari\s+sira|sıralama|siralama|"
    r"puan\s+tür|puan\s+tur|ösym|osym|özel\s+koşul|ozel\s+kosul|öğretim\s+dili|öğrenim\s+dili|"
    r"kaç\s+puan|kac\s+puan|kaçla\s+al|kacla\s+al|kaç\s+kişi|kac\s+kisi"
    r")\b",
    re.IGNORECASE,
)

LIST_PROGRAM_RE = re.compile(
    r"\b(lisans|ön\s*lisans|on\s*lisans|onlisans)\b.*\b(program|bölüm|bolum|neler|hangileri)\b"
    r"|\b(program|bölüm|bolum)\b.*\b(lisans|ön\s*lisans|on\s*lisans|onlisans)\b",
    re.IGNORECASE,
)

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
    "program",
    "programi",
    "bolum",
    "bolumu",
    "lisans",
    "onlisans",
    "on",
    "tercih",
    "yerlesme",
    "yerlesen",
    "yok",
    "atlas",
    "taban",
    "puan",
    "puani",
    "basari",
    "sira",
    "sirasi",
    "siralama",
    "kontenjan",
    "kontejan",
    "kontenjani",
    "kontejani",
    "bilgisi",
    "genel",
    "toplam",
    "okul",
    "birincisi",
    "birincilik",
    "birinci",
    "kac",
    "kisi",
    "kisilik",
    "ogrenci",
    "alir",
    "aliyor",
    "alıyor",
    "alıyor",
    "aldi",
    "aldı",
    "nedir",
    "ne",
    "neler",
    "hangi",
    "hangisi",
    "hangileri",
    "mi",
    "mı",
    "mu",
    "mü",
    "tur",
    "turu",
    "dil",
    "dili",
    "ogretim",
    "ogrenim",
    "egitim",
    "ozel",
    "kosul",
    "kosullari",
    "osym",
    "kodu",
})

PROGRAM_ALIASES: dict[str, tuple[str, ...]] = {
    "111210046": ("tıp", "tip", "tıp bölümü", "tip bölümü"),
    "111210012": (
        "bilg müh",
        "bilg muh",
        "bilg mühendisliği",
        "bilg muhendisligi",
        "bil müh",
        "bil muh",
        "bil mühendisliği",
        "bil muhendisligi",
        "bilgisayar müh",
        "bilgisayar muh",
        "bilgisayar mühendisliği",
        "bilgisayar muhendisligi",
        "bm",
    ),
    "111210011": (
        "eee",
        "eem",
        "elektrik elektronik",
        "elektirik elektronik",
        "elektrik-elektronik",
        "elektrik elektronik müh",
        "elektrik elektronik muh",
        "elektrik elektronik mühendisliği",
        "elektrik elektronik muhendisligi",
    ),
    "111210102": (
        "em",
        "endüstri",
        "endustri",
        "endsütri",
        "endsutri",
        "end müh",
        "end muh",
        "end mühendisliği",
        "end muhendisligi",
        "endüstri ing",
        "endustri ing",
        "endüstri mühendisliği",
        "endustri muhendisligi",
    ),
    "111210016": ("ebelik",),
    "111210032": ("ftr", "fizyoterapi", "fizyo", "fizyoterapi rehabilitasyon"),
    "111210017": ("hemşirelik", "hemsirelik"),
    "111210039": ("gastronomi", "gastronomi mutfak", "gastronomi ve mutfak"),
    "111210123": ("ilahiyat",),
    "111210130": ("ilahiyat mtok", "ilahiyat m t o k", "ilahiyat m.t.o.k"),
    "111210109": ("arapça ilahiyat", "arapca ilahiyat", "ilahiyat arapça", "ilahiyat arapca"),
    "111210116": (
        "arapça mtok",
        "arapca mtok",
        "arapça ilahiyat mtok",
        "arapca ilahiyat mtok",
        "ilahiyat arapça mtok",
        "ilahiyat arapca mtok",
    ),
    "111210074": ("arapça mütercim", "arapca mutercim", "arapça tercümanlık", "arapca tercumanlik"),
    "111210081": ("ingilizce mütercim", "ing mütercim", "ing mutercim", "ing tercümanlık", "ing tercumanlik"),
    "111210053": ("ameliyathane", "ameliyathane hizmetleri"),
    "111210022": ("tıbbi lab", "tibbi lab", "laboratuvar", "tıbbi laboratuvar", "tibbi laboratuvar"),
    "111210021": ("ilk acil", "paramedik", "ilk ve acil yardım", "ilk ve acil yardim"),
    "111210023": (
        "bilgisayar program",
        "bilgisayar prog",
        "bp",
        "bilgisayar programcılığı",
        "bilgisayar programciligi",
        "bilgisayar programclığı",
        "bilgisayar programcligi",
    ),
    "111210024": ("makine",),
}

NORMALIZATION_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bkontejan\w*\b"), "kontenjan"),
    (re.compile(r"\bkontenjani\b"), "kontenjan"),
    (re.compile(r"\bkontenjan\s+bilgisi\b"), "kontenjan"),
    (re.compile(r"\bogrenim\s+dili\b"), "ogretim dili"),
    (re.compile(r"\begitim\s+dili\b"), "ogretim dili"),
    (re.compile(r"\bprogramcligi\b"), "programciligi"),
    (re.compile(r"\bprogramcilig[iı]\b"), "programciligi"),
    (re.compile(r"\bmuh\b"), "muhendisligi"),
)


@dataclass(frozen=True)
class ProgramMatch:
    status: str
    method: str
    program: dict[str, Any] | None = None
    candidates: tuple[dict[str, Any], ...] = ()
    normalized_query: str = ""


def _normalize(text: Any) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_query(text: Any) -> str:
    value = _normalize(text)
    for pattern, replacement in NORMALIZATION_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return re.sub(r"\s+", " ", value).strip()


def _format_decimal_tr(value: Any) -> str:
    if value is None:
        return "kaynakta belirtilmemiş"
    if isinstance(value, Decimal):
        text = format(value, "f").rstrip("0").rstrip(".")
        return text.replace(".", ",")
    if isinstance(value, float):
        text = f"{value:.5f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    return str(value)


def _format_integer_tr(value: Any) -> str:
    if value is None:
        return "kaynakta belirtilmemiş"
    return f"{int(value):,}".replace(",", ".")


def _format_count(value: Any) -> str:
    if value is None:
        return "kaynakta belirtilmemiş"
    return f"{int(value):,}".replace(",", ".")


def _source_url(program: dict[str, Any]) -> str | None:
    return program.get("program_year_source_url") or program.get("program_source_url")


class YokatlasQueryService:
    """YÖK Atlas program sorularını structured DB kayıtlarından yanıtlar."""

    def __init__(self, repository: YokatlasQueryRepository | None = None) -> None:
        self._repository = repository or YokatlasQueryRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        normalized_question = _normalize_query(question)
        intent = self._detect_intent(question, normalized_question)
        if intent is None:
            return None

        if intent == "last_admitted_nets":
            return self._response(
                response=(
                    "Son yerleşen netleri bu sistemin mevcut YÖK Atlas tercih/yerleşme veri kapsamına alınmamıştır. "
                    "Bu nedenle net bilgisi için kesin yanıt üretemiyorum."
                ),
                sources=[],
                intent=intent,
                normalized_query=normalized_question,
                match_method="out_of_scope",
            )

        try:
            programs = self._repository.list_latest_programs()
        except Exception as exc:  # noqa: BLE001 - canlı/RAG fallback yok
            logger.warning("YÖK Atlas DB-first sorgusu DB'den okunamadı: %s", exc, exc_info=True)
            return self._response(
                response=(
                    "YÖK Atlas tercih/yerleşme verisi için ana kaynak ÜniChat DB'dir. "
                    "Şu anda DB kaydı okunamadığı için canlı scrape veya RAG tahmini yapılmadı."
                ),
                sources=[],
                intent=intent,
                normalized_query=normalized_question,
                match_method="db_unavailable",
            )

        if not programs:
            return self._response(
                response="YÖK Atlas tercih/yerleşme verisi DB'de bulunamadı; tahmini yanıt üretilmedi.",
                sources=[],
                intent=intent,
                normalized_query=normalized_question,
                match_method="not_found",
            )

        if intent in {"list_lisans", "list_onlisans"}:
            level = "lisans" if intent == "list_lisans" else "onlisans"
            return self._format_program_list(programs, level, intent, normalized_question)

        if intent == "conditions" and self._is_conditions_list_query(normalized_question):
            return self._format_programs_with_conditions(programs, intent, normalized_question)

        match = self._resolve_program(question, normalized_question, programs)
        if match.status == "ambiguous":
            return self._clarification_response(match, intent)
        if match.status == "not_found" or not match.program:
            return self._program_required_response(programs, intent, normalized_question)

        return self._format_program_answer(match.program, intent, match)

    @staticmethod
    def _detect_intent(original_question: str, normalized_question: str) -> str | None:
        if "net" in normalized_question and ("yerlesen" in normalized_question or "son" in normalized_question):
            return "last_admitted_nets"

        is_program_list_query = bool(
            re.search(r"\b(program|programlari|bolum|bolumleri|neler|hangileri)\b", normalized_question)
        )
        if re.search(r"\bon\s*lisans\b|\bonlisans\b", normalized_question) and is_program_list_query:
            return "list_onlisans"
        if "lisans" in normalized_question and "onlisans" not in normalized_question and "on lisans" not in normalized_question and is_program_list_query:
            return "list_lisans"

        if "ozel kosul" in normalized_question or "kosul" in normalized_question:
            return "conditions"
        if "osym" in normalized_question or OSYM_CODE_RE.search(original_question):
            return "osym_code"
        if "puan tur" in normalized_question or "puan turu" in normalized_question:
            return "score_type"
        if (
            "basari sira" in normalized_question
            or "basari siralama" in normalized_question
            or "siralama" in normalized_question
            or "siralamasi" in normalized_question
            or re.search(r"\bkac\s+bin\w*\b", normalized_question)
            or re.search(r"\bkacinci\s+siradan\b", normalized_question)
        ):
            return "success_rank"
        if "yerlesen" in normalized_question:
            return "placed"
        if (
            "kontenjan" in normalized_question
            or "kac kisi" in normalized_question
            or "kac kisilik" in normalized_question
            or "kisi al" in normalized_question
            or "kac ogrenci" in normalized_question
            or "ogrenci al" in normalized_question
        ):
            return "quota"
        if (
            "taban puan" in normalized_question
            or "kac puan" in normalized_question
            or "puanla al" in normalized_question
            or "kacla al" in normalized_question
            or "puani kac" in normalized_question
            or "puani" in normalized_question
        ):
            return "base_score"
        if (
            "ogretim dili" in normalized_question
            or "hangi dilde" in normalized_question
            or re.search(r"\b(ingilizce|arapca|turkce)\s+mi\b", normalized_question)
        ):
            return "language"
        has_atlas_trigger = (
            bool(YOKATLAS_TRIGGER_RE.search(original_question))
            or any(
                term in normalized_question
                for term in (
                    "kontenjan",
                    "taban puan",
                    "basari sira",
                    "siralama",
                    "puan tur",
                    "ogretim dili",
                    "ozel kosul",
                    "yerlesen",
                )
            )
        )
        if "puan" in normalized_question and has_atlas_trigger:
            return "base_score"

        has_program_signal = any(
            YokatlasQueryService._contains_alias(normalized_question, _normalize_query(alias))
            for aliases in PROGRAM_ALIASES.values()
            for alias in aliases
        )
        if has_atlas_trigger and has_program_signal:
            return "summary"
        return None

    @staticmethod
    def _has_program_hint(normalized_question: str) -> bool:
        if OSYM_CODE_RE.search(normalized_question):
            return True
        for aliases in PROGRAM_ALIASES.values():
            if any(YokatlasQueryService._contains_alias(normalized_question, _normalize_query(alias)) for alias in aliases):
                return True
        return bool(YokatlasQueryService._program_query_tokens(normalized_question))

    @staticmethod
    def _is_conditions_list_query(normalized_question: str) -> bool:
        if OSYM_CODE_RE.search(normalized_question):
            return False
        for aliases in PROGRAM_ALIASES.values():
            if any(YokatlasQueryService._contains_alias(normalized_question, _normalize_query(alias)) for alias in aliases):
                return False
        return any(token in normalized_question for token in ("hangileri", "neler", "bulunan", "olan"))

    def _resolve_program(
        self,
        original_question: str,
        normalized_question: str,
        programs: list[dict[str, Any]],
    ) -> ProgramMatch:
        by_code = {str(program.get("program_code")): program for program in programs}
        code_match = OSYM_CODE_RE.search(original_question)
        if code_match:
            program = by_code.get(code_match.group(0))
            if program:
                return ProgramMatch("matched", "osym_code", program, normalized_query=normalized_question)
            return ProgramMatch("not_found", "osym_code", normalized_query=normalized_question)

        alias_match = self._alias_match(normalized_question, by_code)
        if alias_match.status != "not_found":
            return alias_match

        exact_match = self._exact_match(normalized_question, programs)
        if exact_match.status != "not_found":
            return exact_match

        return self._fuzzy_match(normalized_question, programs)

    @staticmethod
    def _alias_match(normalized_question: str, by_code: dict[str, dict[str, Any]]) -> ProgramMatch:
        scored: list[tuple[int, str]] = []
        for code, aliases in PROGRAM_ALIASES.items():
            if code not in by_code:
                continue
            for alias in aliases:
                normalized_alias = _normalize_query(alias)
                if YokatlasQueryService._contains_alias(normalized_question, normalized_alias):
                    token_bonus = len(normalized_alias.split()) * 12
                    scored.append((120 + token_bonus + len(normalized_alias), code))

        if not scored:
            return ProgramMatch("not_found", "alias", normalized_query=normalized_question)

        scored.sort(reverse=True)
        top_score = scored[0][0]
        top_codes = []
        for score, code in scored:
            if top_score - score <= 8 and code not in top_codes:
                top_codes.append(code)

        if len(top_codes) > 1:
            return ProgramMatch(
                "ambiguous",
                "clarification_required",
                candidates=tuple(by_code[code] for code in top_codes),
                normalized_query=normalized_question,
            )
        return ProgramMatch("matched", "alias", by_code[top_codes[0]], normalized_query=normalized_question)

    @staticmethod
    def _contains_alias(normalized_question: str, normalized_alias: str) -> bool:
        if not normalized_alias:
            return False
        tokens = normalized_alias.split()
        question_tokens = set(normalized_question.split())
        if len(tokens) == 1 and len(normalized_alias) <= 4:
            return normalized_alias in question_tokens
        return f" {normalized_alias} " in f" {normalized_question} "

    @staticmethod
    def _exact_match(normalized_question: str, programs: list[dict[str, Any]]) -> ProgramMatch:
        matches: list[dict[str, Any]] = []
        for program in programs:
            names = {
                _normalize(program.get("program_name_raw")),
                _normalize(program.get("program_name_clean")),
            }
            names.discard("")
            if any(f" {name} " in f" {normalized_question} " for name in names):
                matches.append(program)
        if not matches:
            return ProgramMatch("not_found", "exact", normalized_query=normalized_question)
        if len(matches) > 1:
            return ProgramMatch("ambiguous", "clarification_required", candidates=tuple(matches), normalized_query=normalized_question)
        return ProgramMatch("matched", "exact", matches[0], normalized_query=normalized_question)

    @staticmethod
    def _fuzzy_match(normalized_question: str, programs: list[dict[str, Any]]) -> ProgramMatch:
        query_tokens = YokatlasQueryService._program_query_tokens(normalized_question)
        if not query_tokens:
            return ProgramMatch("not_found", "fuzzy", normalized_query=normalized_question)

        scored: list[tuple[int, dict[str, Any]]] = []
        query_text = " ".join(query_tokens)
        for program in programs:
            candidate_texts = {
                _normalize(program.get("program_name_raw")),
                _normalize(program.get("program_name_clean")),
            }
            candidate_texts.update(_normalize_query(alias) for alias in PROGRAM_ALIASES.get(str(program.get("program_code")), ()))
            best_score = 0
            for candidate in candidate_texts:
                best_score = max(best_score, YokatlasQueryService._candidate_score(query_text, query_tokens, candidate))
            if best_score >= 62:
                scored.append((best_score, program))

        if not scored:
            return ProgramMatch("not_found", "fuzzy", normalized_query=normalized_question)

        scored.sort(key=lambda item: item[0], reverse=True)
        top_score = scored[0][0]
        close = [program for score, program in scored if top_score - score <= 12]
        if len(close) > 1:
            return ProgramMatch("ambiguous", "clarification_required", candidates=tuple(close), normalized_query=normalized_question)
        return ProgramMatch("matched", "fuzzy", scored[0][1], normalized_query=normalized_question)

    @staticmethod
    def _program_query_tokens(normalized_question: str) -> list[str]:
        return [
            token
            for token in normalized_question.split()
            if token not in QUERY_NOISE_TOKENS and len(token) > 1 and not token.isdigit()
        ]

    @staticmethod
    def _candidate_score(query_text: str, query_tokens: list[str], candidate: str) -> int:
        if not candidate:
            return 0
        if candidate == query_text:
            return 170
        if candidate in query_text or query_text in candidate:
            return 125 + min(len(query_text), 35)

        candidate_tokens = [token for token in candidate.split() if token not in QUERY_NOISE_TOKENS]
        if not candidate_tokens:
            return 0

        matched_scores: list[int] = []
        used_indexes: set[int] = set()
        for candidate_token in candidate_tokens:
            best = 0
            best_index = -1
            for index, query_token in enumerate(query_tokens):
                if index in used_indexes:
                    continue
                token_score = YokatlasQueryService._token_match_score(query_token, candidate_token)
                if token_score > best:
                    best = token_score
                    best_index = index
            if best_index >= 0 and best > 0:
                used_indexes.add(best_index)
                matched_scores.append(best)

        if not matched_scores:
            return int(SequenceMatcher(None, query_text, candidate).ratio() * 70)

        coverage = len(matched_scores) / len(candidate_tokens)
        query_coverage = len(used_indexes) / max(len(query_tokens), 1)
        ratio = SequenceMatcher(None, query_text, candidate).ratio()
        return int(45 + sum(matched_scores) + coverage * 25 + query_coverage * 20 + ratio * 30)

    @staticmethod
    def _token_match_score(query_token: str, candidate_token: str) -> int:
        if query_token == candidate_token:
            return 38
        if len(query_token) >= 3 and candidate_token.startswith(query_token):
            return 30
        if len(candidate_token) >= 4 and query_token.startswith(candidate_token):
            return 28
        if len(query_token) < 4 or len(candidate_token) < 4:
            return 0
        ratio = SequenceMatcher(None, query_token, candidate_token).ratio()
        if ratio >= 0.82:
            return int(ratio * 28)
        return 0

    @staticmethod
    def _detect_quota_subtype(normalized_question: str) -> str:
        if (
            "okul birincisi" in normalized_question
            or "birincilik" in normalized_question
            or re.search(r"\bbirinci\s+kontenjan\b", normalized_question)
        ):
            return "school_first"
        if "toplam" in normalized_question:
            return "total"
        if "ozel" in normalized_question:
            return "special"
        return "general"

    @staticmethod
    def _format_quota_answer(program: dict[str, Any], quota_subtype: str) -> str:
        lines = [YokatlasQueryService._program_heading(program), ""]

        if quota_subtype == "school_first":
            lines.extend([
                f"- Okul birincisi kontenjanı: {_format_count(program.get('school_first_quota'))}",
                f"- Okul birincisi yerleşen: {_format_count(program.get('school_first_placed'))}",
                f"- Genel kontenjan: {_format_count(program.get('general_quota'))}",
                f"- Genel yerleşen: {_format_count(program.get('general_placed'))}",
                f"- Puan türü: {program.get('score_type')}",
            ])
            if program.get("school_first_quota") is None:
                lines.append(
                    "- Not: Bu kontenjan alt türü için DB'de ayrı değer bulunamadı; genel kontenjan bilgisi gösterildi."
                )
            return "\n".join(lines)

        if quota_subtype == "total":
            lines.extend([
                f"- Toplam bilinen kontenjan: {_format_count(program.get('total_quota_known'))}",
                f"- Toplam bilinen yerleşen: {_format_count(program.get('total_placed_known'))}",
                f"- Genel kontenjan: {_format_count(program.get('general_quota'))}",
                f"- Genel yerleşen: {_format_count(program.get('general_placed'))}",
                f"- Puan türü: {program.get('score_type')}",
            ])
            return "\n".join(lines)

        if quota_subtype == "special":
            lines.extend([
                "- Not: DB'de tek bir 'özel kontenjan' alanı yok; bilinen kontenjan alt türleri listelendi.",
                f"- Okul birincisi kontenjanı: {_format_count(program.get('school_first_quota'))}",
                f"- Depremzede kontenjanı: {_format_count(program.get('earthquake_quota'))}",
                f"- 34 yaş üstü kadın kontenjanı: {_format_count(program.get('women_34_plus_quota'))}",
                f"- Şehit/gazi yakını kontenjanı: {_format_count(program.get('martyr_veteran_quota'))}",
                f"- Genel kontenjan: {_format_count(program.get('general_quota'))}",
            ])
            return "\n".join(lines)

        lines.extend([
            f"- Genel kontenjan: {_format_count(program.get('general_quota'))}",
            f"- Genel yerleşen: {_format_count(program.get('general_placed'))}",
            f"- Toplam bilinen kontenjan: {_format_count(program.get('total_quota_known'))}",
            f"- Puan türü: {program.get('score_type')}",
        ])
        return "\n".join(lines)

    def _format_program_answer(self, program: dict[str, Any], intent: str, match: ProgramMatch) -> dict[str, Any]:
        heading = self._program_heading(program)
        quota_subtype = None
        if intent == "osym_code":
            response = (
                f"ÖSYM kodu {program['program_code']}, **{program.get('program_name_raw')}** programına aittir.\n\n"
                f"- Birim: {program.get('academic_unit_name')}\n"
                f"- Veri yılı: {program.get('data_year')}\n"
                f"- Puan türü: {program.get('score_type')}\n"
                f"- Öğretim dili: {program.get('language')}"
            )
        elif intent == "quota":
            quota_subtype = self._detect_quota_subtype(match.normalized_query)
            response = self._format_quota_answer(program, quota_subtype)
        elif intent == "placed":
            response = "\n".join([
                heading,
                "",
                f"- Genel yerleşen: {_format_count(program.get('general_placed'))}",
                f"- Genel kontenjan: {_format_count(program.get('general_quota'))}",
                f"- Toplam bilinen yerleşen: {_format_count(program.get('total_placed_known'))}",
                f"- Puan türü: {program.get('score_type')}",
            ])
        elif intent == "base_score":
            response = "\n".join([
                heading,
                "",
                f"- Taban puan: {_format_decimal_tr(program.get('base_score'))}",
                f"- Başarı sırası: {_format_integer_tr(program.get('base_rank'))}",
                f"- Puan türü: {program.get('score_type')}",
                f"- Öğretim dili: {program.get('language')}",
            ])
        elif intent == "success_rank":
            response = "\n".join([
                heading,
                "",
                f"- Başarı sırası: {_format_integer_tr(program.get('base_rank'))}",
                f"- Taban puan: {_format_decimal_tr(program.get('base_score'))}",
                f"- Puan türü: {program.get('score_type')}",
                f"- Öğretim dili: {program.get('language')}",
            ])
        elif intent == "score_type":
            response = "\n".join([
                heading,
                "",
                f"- Puan türü: {program.get('score_type')}",
                f"- Taban puan: {_format_decimal_tr(program.get('base_score'))}",
                f"- Öğretim dili: {program.get('language')}",
            ])
        elif intent == "language":
            response = "\n".join([
                heading,
                "",
                f"- Öğretim dili: {program.get('language')}",
                f"- Puan türü: {program.get('score_type')}",
                f"- Taban puan: {_format_decimal_tr(program.get('base_score'))}",
                f"- Başarı sırası: {_format_integer_tr(program.get('base_rank'))}",
            ])
        elif intent == "conditions":
            response = self._format_program_conditions(program)
        else:
            response = self._format_program_summary(program)

        if intent != "conditions":
            response = self._append_condition_note(response, program)
        response = self._append_source_label(response)

        tables = list(self._source_tables_for_intent(intent))
        if int(program.get("condition_count") or 0) > 0 and "yokatlas_program_conditions" not in tables:
            tables.append("yokatlas_program_conditions")

        return self._response(
            response=response,
            sources=self._sources_for_program(program),
            intent=intent,
            normalized_query=match.normalized_query,
            match_method=match.method,
            program=program,
            quota_subtype=quota_subtype,
            tables=tuple(tables),
        )

    def _format_program_conditions(self, program: dict[str, Any]) -> str:
        condition_count = int(program.get("condition_count") or 0)
        if condition_count <= 0:
            return (
                f"**{program.get('program_name_raw')}** için {program.get('data_year')} YÖK Atlas verilerine göre "
                "özel koşul bulunmuyor."
            )
        conditions = self._repository.get_conditions_for_program_year(str(program["program_year_id"]))
        lines = [
            f"**{program.get('program_name_raw')}** için {program.get('data_year')} YÖK Atlas verilerine göre özel koşullar:",
            "",
        ]
        for condition in conditions[:5]:
            code = condition.get("condition_code")
            text = str(condition.get("condition_text") or "").strip()
            prefix = f"- Koşul {code}: " if code else "- "
            lines.append(prefix + text)
        if len(conditions) > 5:
            lines.append(f"- Ayrıca {len(conditions) - 5} koşul daha var.")
        return "\n".join(lines)

    @staticmethod
    def _append_condition_note(response: str, program: dict[str, Any]) -> str:
        condition_count = int(program.get("condition_count") or 0)
        if condition_count <= 0:
            return response
        return (
            f"{response}\n"
            f"- Özel koşul notu: Bu programda {condition_count} özel koşul kaydı bulunuyor."
        )

    @staticmethod
    def _append_source_label(response: str) -> str:
        if "Kaynak: YÖK Atlas" in response:
            return response
        return f"{response}\n\nKaynak: YÖK Atlas"

    @staticmethod
    def _program_heading(program: dict[str, Any]) -> str:
        return f"**{program.get('program_name_raw')}** için {program.get('data_year')} YÖK Atlas verilerine göre:"

    @staticmethod
    def _format_program_summary(program: dict[str, Any]) -> str:
        return "\n".join([
            YokatlasQueryService._program_heading(program),
            "",
            f"- Puan türü: {program.get('score_type')}",
            f"- Kontenjan / yerleşen: {_format_count(program.get('general_quota'))} / {_format_count(program.get('general_placed'))}",
            f"- Taban puan: {_format_decimal_tr(program.get('base_score'))}",
            f"- Başarı sırası: {_format_integer_tr(program.get('base_rank'))}",
            f"- Öğretim dili: {program.get('language')}",
        ])

    def _format_program_list(
        self,
        programs: list[dict[str, Any]],
        level: str,
        intent: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        selected = [program for program in programs if program.get("program_level") == level]
        label = "lisans" if level == "lisans" else "ön lisans"
        year = selected[0].get("data_year") if selected else None
        lines = [f"GİBTÜ {year} YÖK Atlas verilerine göre {label} programları:", ""]
        for program in selected:
            lines.append(
                f"- {program.get('program_name_raw')} - {program.get('score_type')}, "
                f"{program.get('academic_unit_name')}"
            )
        return self._response(
            response=self._append_source_label("\n".join(lines)),
            sources=self._sources_for_programs(selected),
            intent=intent,
            normalized_query=normalized_query,
            match_method="list",
            tables=("yokatlas_programs", "yokatlas_program_years"),
        )

    def _format_programs_with_conditions(
        self,
        programs: list[dict[str, Any]],
        intent: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        selected = [program for program in programs if int(program.get("condition_count") or 0) > 0]
        year = selected[0].get("data_year") if selected else None
        lines = [f"{year} YÖK Atlas verilerine göre özel koşul bulunan GİBTÜ programları:", ""]
        for program in selected:
            lines.append(
                f"- {program.get('program_name_raw')}: {program.get('condition_count')} koşul"
            )
        return self._response(
            response=self._append_source_label("\n".join(lines)),
            sources=self._sources_for_programs(selected),
            intent=intent,
            normalized_query=normalized_query,
            match_method="list",
            tables=("yokatlas_programs", "yokatlas_program_years", "yokatlas_program_conditions"),
        )

    def _clarification_response(self, match: ProgramMatch, intent: str) -> dict[str, Any]:
        options = [
            f"{program.get('program_name_raw')} (ÖSYM {program.get('program_code')}, {program.get('program_level')})"
            for program in match.candidates[:5]
        ]
        return self._response(
            response=(
                "Bu soru birden fazla YÖK Atlas programıyla eşleşiyor. "
                "Hangisini kastettiğinizi belirtir misiniz?\n- " + "\n- ".join(options)
            ),
            sources=self._sources_for_programs(list(match.candidates)),
            intent=intent,
            normalized_query=match.normalized_query,
            match_method="clarification_required",
            candidates=list(match.candidates),
            tables=("yokatlas_programs", "yokatlas_program_years"),
        )

    def _program_required_response(
        self,
        programs: list[dict[str, Any]],
        intent: str,
        normalized_query: str,
    ) -> dict[str, Any]:
        options = ", ".join(
            f"{program.get('program_name_raw')} (ÖSYM {program.get('program_code')})"
            for program in programs[:8]
        )
        return self._response(
            response=(
                "Bu soru YÖK Atlas tercih/yerleşme verisi kapsamında algılandı; "
                "ancak yanıtlayabilmem için programı netleştirmeniz gerekiyor. "
                f"Örnek seçenekler: {options}."
            ),
            sources=[],
            intent=intent,
            normalized_query=normalized_query,
            match_method="clarification_required",
            tables=("yokatlas_programs", "yokatlas_program_years"),
        )

    @staticmethod
    def _sources_for_program(program: dict[str, Any]) -> list[dict[str, Any]]:
        return YokatlasQueryService._sources_for_programs([program])

    @staticmethod
    def _sources_for_programs(programs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for program in programs:
            url = _source_url(program)
            key = url or str(program.get("program_code"))
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append({
                "content": (
                    f"{program.get('program_name_raw')} YÖK Atlas tercih/yerleşme kaydı "
                    f"({program.get('data_year')})."
                ),
                "source_url": url,
                "source_public_url": url,
                "category": "YÖK Atlas",
                "title": program.get("program_name_raw"),
                "doc_kind": "yokatlas_program_year",
            })
        return sources

    @staticmethod
    def _source_tables_for_intent(intent: str) -> tuple[str, ...]:
        base = ["yokatlas_programs", "yokatlas_program_years"]
        if intent in {"quota", "placed", "summary"}:
            base.append("yokatlas_quota_statistics")
        if intent in {"base_score", "success_rank", "summary"}:
            base.append("yokatlas_score_statistics")
        if intent == "conditions":
            base.append("yokatlas_program_conditions")
        return tuple(base)

    @staticmethod
    def _response(
        *,
        response: str,
        sources: list[dict[str, Any]],
        intent: str,
        normalized_query: str,
        match_method: str,
        program: dict[str, Any] | None = None,
        candidates: list[dict[str, Any]] | None = None,
        quota_subtype: str | None = None,
        tables: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "response": response,
            "sources": sources,
            "metadata": {
                "db_first": True,
                "service": "yokatlas_query_service",
                "intent": intent,
                "normalized_query": normalized_query,
                "match_method": match_method,
                "quota_subtype": quota_subtype,
                "matched_program_code": program.get("program_code") if program else None,
                "matched_program_name": program.get("program_name_raw") if program else None,
                "candidate_program_codes": [candidate.get("program_code") for candidate in candidates or []],
                "source_tables": list(tables),
                "rag_fallback_used": False,
            },
        }


@lru_cache()
def get_yokatlas_query_service() -> YokatlasQueryService:
    return YokatlasQueryService()
