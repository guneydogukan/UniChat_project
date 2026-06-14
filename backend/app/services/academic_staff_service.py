"""
ÜniChat — YÖK Akademik bölüm/program akademik kadro yanıt servisi.

Bu fazda akademik kadro yanıtları yalnız YÖK Akademik kaynaklı structured
katmandan üretilir. Fakülte genel kadro listesi ve yönetim rolleri kapsam dışıdır.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from app.repositories.academic_repository import AcademicRepository
from scrapers.yok_academic_staff_scraper import normalize_for_match

logger = logging.getLogger(__name__)

VERIFIED_YOK_STATUSES: frozenset[str] = frozenset({
    "verified_from_yok",
    "verified_from_yok_academic",
    "verified_from_filtered_context",
    "verified_from_kadro_veri",
})

REVIEW_YOK_STATUSES: frozenset[str] = frozenset({
    "ambiguous_department",
    "ambiguous_department_or_program",
    "conflict_department_or_program",
    "unmatched_program",
    "not_resolved",
    "conflict_institution",
    "missing_kadro_veri",
})


ACADEMIC_STAFF_QUERY_RE = re.compile(
    r"\b("
    r"akademik\s+kadro\w*|akademik\s+personel\w*|akademisyen\w*|hoca\w*|"
    r"öğretim\s+üye\w*|ogretim\s+uye\w*|öğretim\s+eleman\w*|ogretim\s+eleman\w*|"
    r"öğretim\s+görevl\w*|ogretim\s+gorevl\w*|araştırma\s+görevl\w*|arastirma\s+gorevl\w*|"
    r"kadro\w*|bölüm\s+başkan\w*|bolum\s+baskan\w*|dekan\w*|rektörlük\s+kadro\w*|rektorluk\s+kadro\w*|"
    r"rektör\s+yardımc\w*|rektor\s+yardimc\w*|rektör\s+danışman\w*|rektor\s+danisman\w*|"
    r"yök\s+akademik|yok\s+akademik|profil\s+bağlant\w*|profil\s+baglant\w*"
    r")\b",
    re.IGNORECASE,
)

PROFILE_QUERY_RE = re.compile(
    r"\b(yök\s+akademik|yok\s+akademik|profil\s+bağlant\w*|profil\s+baglant\w*|profil\s+url|"
    r"akademisyen\s+profil\w*)\b",
    re.IGNORECASE,
)

STAFF_QUERY_RE = re.compile(
    r"\b(akademik\s+kadro\w*|akademik\s+personel\w*|akademisyen\w*|hoca\w*|"
    r"öğretim\s+üye\w*|ogretim\s+uye\w*|öğretim\s+eleman\w*|ogretim\s+eleman\w*|"
    r"öğretim\s+görevl\w*|ogretim\s+gorevl\w*|araştırma\s+görevl\w*|arastirma\s+gorevl\w*|kadro\w*)\b",
    re.IGNORECASE,
)

PERSON_QUERY_RE = re.compile(
    r"\b(kim|kimdir|hangi\s+bolum\w*|hangi\s+birim\w*|nerede)\b",
    re.IGNORECASE,
)

MANAGEMENT_QUERY_RE = re.compile(
    r"\b("
    r"bölüm\s+başkan\w*|bolum\s+baskan\w*|dekan\w*|rektör\w*|rektor\w*|"
    r"rektörlük\s+kadro\w*|rektorluk\s+kadro\w*|yönetim\s+kadro\w*|yonetim\s+kadro\w*|"
    r"müdür\w*|mudur\w*|koordinatör\w*|koordinator\w*"
    r")\b",
    re.IGNORECASE,
)

QUERY_NOISE_TOKENS: frozenset[str] = frozenset({
    "kim",
    "kimin",
    "nedir",
    "nelerdir",
    "neredir",
    "hangi",
    "baglantisi",
    "baglanti",
    "url",
    "profil",
    "profili",
    "akademik",
    "yok",
    "kadro",
    "kadrosu",
    "kadrolari",
    "personel",
    "personeli",
    "hoca",
    "hocalar",
    "hocalari",
    "akademisyen",
    "akademisyenler",
    "akademisyenleri",
    "ogretim",
    "uyesi",
    "uyeleri",
    "elemani",
    "elemanlari",
    "gorevlisi",
    "gorevlileri",
    "un",
    "in",
    "nin",
    "nun",
    "nün",
    "ve",
    "ile",
    "ait",
})

PERSON_QUERY_NOISE_TOKENS: frozenset[str] = QUERY_NOISE_TOKENS.union({
    "kimdir",
    "bolum",
    "bolumu",
    "bolumde",
    "birim",
    "birimde",
    "hangi",
    "nerede",
    "calisiyor",
    "calisir",
    "yer",
    "aliyor",
    "gorev",
    "yapiyor",
})

UNIT_SUFFIXES: tuple[str, ...] = (
    " bolumu",
    " bolum",
    " programi",
    " program",
    " fakultesi",
    " fakulte",
    " meslek yuksekokulu",
    " yuksekokulu",
    " enstitusu",
    " rektorlugu",
)

ALIAS_STOPWORDS: frozenset[str] = frozenset({
    "ve",
    "ile",
})

UNIT_DESCRIPTOR_TOKENS: frozenset[str] = frozenset({
    "bolum",
    "bolumu",
    "program",
    "programi",
    "fakulte",
    "fakultesi",
    "yuksekokulu",
    "enstitusu",
    "rektorlugu",
})

UNIT_CONTEXT_TOKENS: frozenset[str] = frozenset({
    "bolum",
    "bolumu",
    "program",
    "programi",
    "fakulte",
    "fakultesi",
    "myo",
    "muh",
    "muhendisligi",
    "muhendislik",
})

LANGUAGE_QUALIFIER_TOKENS: frozenset[str] = frozenset({
    "arapca",
    "ingilizce",
    "turkce",
})

BROAD_SINGLE_TOKEN_ALIASES: frozenset[str] = frozenset({
    "bilgisayar",
    "elektrik",
    "elektronik",
    "endustri",
    "fizyoterapi",
    "ilahiyat",
    "makine",
    "mutercim",
    "saglik",
    "temel",
    "tibbi",
    "tip",
})

UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "muhendislik ve doga bilimleri fakultesi": ("mdbf", "muhendislik ve doga bilimleri"),
    "bilgisayar muhendisligi bolumu": (
        "bm",
        "b m",
        "bilgisayar muhendisligi",
        "bilgisayar muh",
        "bilgisayar muh bolumu",
        "bilgisayar bolumu",
        "bilgisayar",
    ),
    "bilgisayar programciligi programi": (
        "bilgisayar",
        "bilgisayar programciligi",
        "bilgisayar programi",
        "bilgisayar programciligi programi",
    ),
    "endustri muhendisligi bolumu": (
        "em",
        "e m",
        "endustri muhendisligi",
        "endustri muh",
        "endustri bolumu",
        "endustri",
    ),
    "elektrik elektronik muhendisligi bolumu": (
        "eee",
        "e e e",
        "elektrik elektronik muhendisligi",
        "elektrik elektronik",
        "elektrik muhendisligi",
        "elektrik muh",
        "elektrik bolumu",
        "elektrik",
    ),
    "elektrik-elektronik muhendisligi bolumu": (
        "eee",
        "e e e",
        "elektrik elektronik muhendisligi",
        "elektrik elektronik",
        "elektrik muhendisligi",
        "elektrik muh",
        "elektrik bolumu",
        "elektrik",
    ),
    "rektorluk": ("rektorluk kadrosu", "rektorluk"),
}

GENERIC_SINGLE_TOKEN_ALIASES: frozenset[str] = frozenset({
    "bilgisayar",
    "elektrik",
    "endustri",
})

MIN_UNIT_MATCH_SCORE = 72
AMBIGUOUS_UNIT_SCORE_GAP = 12
MIN_PERSON_MATCH_SCORE = 82
AMBIGUOUS_PERSON_SCORE_GAP = 8


class AcademicStaffService:
    """YÖK Akademik structured bölüm/program kadro verisinden yanıt üretir."""

    def __init__(self, repository: AcademicRepository | None = None) -> None:
        self._repository = repository or AcademicRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        """Akademik kadro/profil sorusunu yanıtlar; değilse None döner."""
        normalized_question = normalize_for_match(question)
        has_academic_staff_signal = bool(ACADEMIC_STAFF_QUERY_RE.search(question))
        has_person_query_signal = self._looks_like_person_query(normalized_question)
        if not has_academic_staff_signal and not has_person_query_signal:
            return None

        try:
            if MANAGEMENT_QUERY_RE.search(question):
                return None

            if PROFILE_QUERY_RE.search(question):
                profile_answer = self._answer_person_profile(question, normalized_question)
                if profile_answer is not None:
                    return profile_answer

            if has_person_query_signal:
                person_answer = self._answer_person_query(
                    normalized_question,
                    return_not_found=True,
                )
                if person_answer is not None:
                    return person_answer

            unit_match = self._resolve_unit_match(normalized_question)
            if unit_match["status"] == "ambiguous" and STAFF_QUERY_RE.search(question):
                return self._ambiguous_unit_response(unit_match["candidates"])
            if unit_match["unit"] and STAFF_QUERY_RE.search(question):
                return self._answer_staff(unit_match["unit"])
            if STAFF_QUERY_RE.search(question):
                return self._unit_required_response()
        except Exception as exc:  # noqa: BLE001 - akademik kadroda canlı scrape/RAG fallback yok
            logger.warning("Akademik kadro servisi yanıt üretemedi: %s", exc, exc_info=True)
            return self._db_unavailable_response()

        return None

    def _answer_staff(self, unit: dict[str, Any]) -> dict[str, Any] | None:
        if self._is_faculty_unit(unit):
            return self._faculty_clarification_response(unit)

        staff = self._dedup_people(self._repository.get_staff_by_unit(str(unit["id"])))
        official_staff, review_staff = self._split_official_and_candidate(staff)
        if not official_staff:
            return self._not_found_response(
                f"**{unit['unit_name']} akademik kadrosu**\n"
                "Bu bölüm/program için akademik kadro verisi henüz veritabanında bulunmuyor.",
                unit,
                review_count=len(review_staff),
            )

        response = self._format_staff_section(f"{unit['unit_name']} akademik kadrosu", official_staff, review_staff)
        return {
            "response": response,
            "sources": self._dedup_sources(self._sources_from_records(official_staff, "yok_akademik_staff")),
        }

    def _faculty_clarification_response(self, unit: dict[str, Any]) -> dict[str, Any]:
        children = [
            child for child in self._repository.get_child_units(str(unit["id"]))
            if self._is_academic_staff_option_unit(child)
        ]
        lines = [
            f"**{unit['unit_name']} için bölüm/program seçimi gerekli**",
            "Bu fazda fakülte düzeyinde birleşik akademik kadro listesi üretilmez.",
            "Bu fakülteye bağlı hangi bölüm veya programın akademik kadrosunu görmek istiyorsunuz?",
        ]
        if children:
            options = ", ".join(child["unit_name"] for child in children)
            lines.append(f"Bilinen seçenekler: {options}.")
        else:
            lines.append("Bu fakülte için kayıtlı bölüm/program seçenekleri henüz bulunmuyor.")

        sources: list[dict[str, Any]] = []
        if unit.get("source_url"):
            sources.append({
                "content": f"{unit.get('unit_name')} üst birim kaydı.",
                "source_url": unit.get("source_url"),
                "source_public_url": unit.get("source_url"),
                "category": "akademik_kadro",
                "title": unit.get("unit_name"),
                "doc_kind": "academic_unit_clarification",
            })
        return {"response": "\n".join(lines), "sources": sources}

    @staticmethod
    def _ambiguous_unit_response(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        lines = [
            "**Bölüm/program seçimi gerekli**",
            "Akademik kadro sorunuz birden fazla bölüm/programla eşleşiyor.",
            "Hangi bölüm veya programın akademik kadrosunu görmek istiyorsunuz?",
        ]
        options = ", ".join(str(unit.get("unit_name")) for unit in candidates if unit.get("unit_name"))
        if options:
            lines.append(f"Bilinen seçenekler: {options}.")
        return {"response": "\n".join(lines), "sources": []}

    @staticmethod
    def _management_scope_out_response() -> dict[str, Any]:
        return {
            "response": (
                "Bu fazda yalnız YÖK Akademik kaynaklı bölüm/program akademik kadro ve YÖK profil bilgileri yanıtlanır. "
                "Bölüm başkanı, dekan, rektörlük ve diğer yönetim kadrosu soruları ayrı yönetim modülünde ele alınacaktır."
            ),
            "sources": [],
        }

    def _unit_required_response(self) -> dict[str, Any]:
        children = [
            unit for unit in self._repository.list_units()
            if self._is_department_or_program_unit(unit)
        ]
        lines = [
            "**Bölüm/program seçimi gerekli**",
            "Akademik kadro bu fazda yalnız YÖK Akademik kaynaklı bölüm/program kayıtlarından yanıtlanır.",
            "Hangi bölüm veya programın akademik kadrosunu görmek istiyorsunuz?",
        ]
        if children:
            lines.append("Bilinen seçenekler: " + ", ".join(unit["unit_name"] for unit in children) + ".")
        else:
            lines.append("DB'de kayıtlı bölüm/program kadro verisi henüz bulunmuyor.")
        return {"response": "\n".join(lines), "sources": []}

    @staticmethod
    def _db_unavailable_response() -> dict[str, Any]:
        return {
            "response": (
                "Akademik kadro verisi için ana kaynak ÜniChat DB'dir. Şu anda DB kaydı okunamadığı için "
                "canlı YÖK Akademik scrape yapılmadı ve tahmini yanıt üretilmedi."
            ),
            "sources": [],
        }

    def _answer_person_profile(self, question: str, normalized_question: str) -> dict[str, Any] | None:
        name_query = self._extract_name_query(normalized_question)
        if not name_query:
            return None

        candidates = self._search_person_candidates(name_query)
        if not candidates:
            return {
                "response": (
                    "YÖK Akademik üzerinde bu kişi için doğrulanmış profil kaydı bulunamadı. "
                    "Tahmini profil URL'si üretilmedi; kayıt `not_resolved` kabul edilmelidir."
                ),
                "sources": [],
            }

        person_rows = self._dedup_people(candidates)
        primary = person_rows[0]
        profiles = self._profile_map(primary)
        yok_profile = profiles.get("yok_akademik")

        lines = [f"**{primary.get('full_name')} YÖK Akademik profili**"]
        if primary.get("title"):
            lines.append(f"- Unvan: {primary['title']}")
        if primary.get("unit_name"):
            unit_text = str(primary["unit_name"])
            if primary.get("parent_unit_name"):
                unit_text += f" / {primary['parent_unit_name']}"
            lines.append(f"- Birim: {unit_text}")
        yok_unit_text = self._yok_unit_text(primary)
        if yok_unit_text:
            lines.append(f"- YÖK'te görünen birim: {yok_unit_text}")
        if yok_profile and yok_profile.get("profile_url"):
            lines.append(f"- YÖK Akademik profil URL'si: {yok_profile['profile_url']}")
        else:
            lines.append("- YÖK Akademik profil URL'si: not_resolved")
        yok_id = yok_profile.get("external_id") if yok_profile else None
        if yok_id:
            lines.append(f"- YÖK Araştırmacı ID: {yok_id}")
        lines.append("- Kaynak: YÖK Akademik")
        lines.append(f"- Veri durumu: {self._confidence_label(primary)}")
        if self._needs_review(primary):
            lines.append("- Not: Bu kayıt manuel doğrulama gerektiriyor.")
        if primary.get("last_checked_at"):
            lines.append(f"- Son kontrol tarihi: {self._format_checked_at(primary.get('last_checked_at'))}")

        sources = self._sources_from_records([primary], "yok_akademik_profile")
        return {"response": "\n".join(lines), "sources": self._dedup_sources(sources)}

    def _answer_person_query(
        self,
        normalized_question: str,
        return_not_found: bool = False,
    ) -> dict[str, Any] | None:
        name_query = self._extract_name_query(normalized_question)
        if not name_query:
            return None

        person_match = self._resolve_person_match(name_query)
        if person_match["status"] == "ambiguous":
            return self._ambiguous_person_response(person_match["candidates"])
        if person_match["status"] == "not_found":
            return self._person_not_found_response() if return_not_found else None

        primary = person_match["person"]
        if not primary or not self._is_verified_yok_staff(primary):
            return self._person_not_found_response() if return_not_found else None

        return {
            "response": self._format_person_staff_answer(primary),
            "sources": self._dedup_sources(self._sources_from_records([primary], "yok_akademik_profile")),
        }

    def _resolve_person_match(self, name_query: str) -> dict[str, Any]:
        candidates = self._dedup_people(self._search_person_candidates(name_query))
        scored: list[tuple[int, dict[str, Any]]] = []
        for candidate in candidates:
            score = self._person_match_score(candidate, name_query)
            if score >= MIN_PERSON_MATCH_SCORE:
                scored.append((score, candidate))
        if not scored:
            return {"status": "not_found", "person": None, "candidates": []}

        scored.sort(key=lambda item: (item[0], self._record_score(item[1])), reverse=True)
        top_score, top_person = scored[0]
        close_candidates = [
            candidate
            for score, candidate in scored
            if top_score - score <= AMBIGUOUS_PERSON_SCORE_GAP
        ]
        candidate_ids = {str(candidate.get("person_id")) for candidate in close_candidates}
        if len(candidate_ids) > 1:
            return {"status": "ambiguous", "person": None, "candidates": close_candidates}
        return {"status": "matched", "person": top_person, "candidates": [top_person]}

    @staticmethod
    def _person_match_score(row: dict[str, Any], name_query: str) -> int:
        normalized_name = str(row.get("normalized_name") or normalize_for_match(row.get("full_name")))
        if not normalized_name or not name_query:
            return 0
        if normalized_name == name_query:
            return 170
        if normalized_name in name_query or name_query in normalized_name:
            return 132 + min(len(name_query), 30)

        query_tokens = [token for token in name_query.split() if len(token) > 1]
        fuzzy_score = AcademicStaffService._alias_fuzzy_score(normalized_name, query_tokens)
        full_ratio = SequenceMatcher(None, name_query, normalized_name).ratio()
        ratio_score = int(full_ratio * 120) if full_ratio >= 0.90 else 0
        return max(fuzzy_score, ratio_score)

    def _format_person_staff_answer(self, person: dict[str, Any]) -> str:
        title = f"{person.get('title')} " if person.get("title") else ""
        full_name = str(person.get("full_name") or "").strip()
        unit_name = str(person.get("unit_name") or "").strip()
        parent_unit_name = str(person.get("parent_unit_name") or "").strip()

        affiliation_parts = ["GİBTÜ"]
        if parent_unit_name:
            affiliation_parts.append(parent_unit_name)
        if unit_name:
            affiliation_parts.append(unit_name)
        affiliation_text = " ".join(affiliation_parts).strip()

        lines = [
            (
                f"{title}{full_name}, {affiliation_text} akademik kadrosunda yer almaktadır."
                if affiliation_text
                else f"{title}{full_name}, GİBTÜ akademik kadrosunda yer almaktadır."
            ),
            "Kaynak: YÖK Akademik.",
        ]
        if person.get("last_checked_at"):
            lines.append(f"Son kontrol: {self._format_checked_at(person.get('last_checked_at'))}.")
        return " ".join(lines)

    @staticmethod
    def _ambiguous_person_response(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        options = []
        for person in candidates:
            full_name = str(person.get("full_name") or "").strip()
            unit_name = str(person.get("unit_name") or "").strip()
            if full_name and unit_name:
                options.append(f"{full_name} ({unit_name})")
            elif full_name:
                options.append(full_name)
        response = "Şunu mu kastettiniz: " + ", ".join(options) + "?"
        return {"response": response, "sources": []}

    @staticmethod
    def _person_not_found_response() -> dict[str, Any]:
        return {
            "response": (
                "Bu akademisyen için güncel akademik kadro verisi henüz veritabanında bulunmuyor. "
                "Canlı scrape veya RAG tahmini yapılmadı."
            ),
            "sources": [],
        }

    def _resolve_unit_match(self, normalized_question: str) -> dict[str, Any]:
        scored = self._score_units(normalized_question)
        if not scored:
            return {"status": "not_found", "unit": None, "candidates": []}

        top_score, top_unit = scored[0]
        if top_score < MIN_UNIT_MATCH_SCORE:
            return {"status": "not_found", "unit": None, "candidates": []}

        close_candidates = [
            unit
            for score, unit in scored
            if score >= MIN_UNIT_MATCH_SCORE and top_score - score <= AMBIGUOUS_UNIT_SCORE_GAP
        ]
        department_program_candidates = self._department_program_candidates(close_candidates)
        language_disambiguated = self._disambiguate_language_variant(
            normalized_question,
            department_program_candidates,
        )
        if language_disambiguated is not None:
            return {
                "status": "matched",
                "unit": language_disambiguated,
                "candidates": [language_disambiguated],
            }

        token_disambiguated = self._disambiguate_exact_token_coverage(
            normalized_question,
            department_program_candidates,
        )
        if token_disambiguated is not None:
            return {
                "status": "matched",
                "unit": token_disambiguated,
                "candidates": [token_disambiguated],
            }

        staff_backed_disambiguated = self._disambiguate_staff_backed_equivalent_unit(
            department_program_candidates,
        )
        if staff_backed_disambiguated is not None:
            return {
                "status": "matched",
                "unit": staff_backed_disambiguated,
                "candidates": [staff_backed_disambiguated],
            }

        candidate_ids = {str(unit.get("id")) for unit in department_program_candidates}
        if len(candidate_ids) > 1:
            return {
                "status": "ambiguous",
                "unit": None,
                "candidates": department_program_candidates,
            }

        return {"status": "matched", "unit": top_unit, "candidates": [top_unit]}

    def _disambiguate_language_variant(
        self,
        normalized_question: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if len(candidates) < 2:
            return None

        query_language_tokens = set(normalized_question.split()).intersection(LANGUAGE_QUALIFIER_TOKENS)
        if query_language_tokens:
            explicit_language_matches = [
                unit
                for unit in candidates
                if query_language_tokens.intersection(self._unit_language_tokens(unit))
            ]
            if len(explicit_language_matches) == 1:
                return explicit_language_matches[0]
            return None

        non_language_candidates = [
            unit
            for unit in candidates
            if not self._unit_language_tokens(unit)
        ]
        if len(non_language_candidates) != 1:
            return None

        base_without_language = self._unit_base_without_language(non_language_candidates[0])
        if not base_without_language:
            return None

        equivalent_language_candidates = [
            unit
            for unit in candidates
            if self._unit_language_tokens(unit)
            and self._unit_base_without_language(unit) == base_without_language
        ]
        if equivalent_language_candidates:
            return non_language_candidates[0]
        return None

    def _disambiguate_exact_token_coverage(
        self,
        normalized_question: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if len(candidates) < 2:
            return None

        query_tokens = [
            token
            for token in self._query_match_tokens(normalized_question)
            if token not in UNIT_DESCRIPTOR_TOKENS
        ]
        if len(query_tokens) < 2:
            return None

        exact_matches = [
            unit
            for unit in candidates
            if set(query_tokens).issubset(self._unit_identity_tokens(unit))
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        return None

    def _disambiguate_staff_backed_equivalent_unit(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if len(candidates) < 2:
            return None

        candidate_cores = {
            self._unit_core_identity(unit)
            for unit in candidates
            if self._unit_core_identity(unit)
        }
        if len(candidate_cores) != 1:
            return None

        staff_backed_candidates = [
            unit
            for unit in candidates
            if self._unit_official_staff_count(unit) > 0
        ]
        if len(staff_backed_candidates) == 1:
            return staff_backed_candidates[0]
        return None

    def _match_unit(self, normalized_question: str) -> dict[str, Any] | None:
        """Geriye dönük kullanım için tek güçlü eşleşmeyi döndürür."""
        match = self._resolve_unit_match(normalized_question)
        return match["unit"] if match["status"] == "matched" else None

    def _score_units(self, normalized_question: str) -> list[tuple[int, dict[str, Any]]]:
        units = self._repository.list_units()
        scored: list[tuple[int, dict[str, Any]]] = []
        for unit in units:
            score = self._unit_match_score(unit, normalized_question)
            if score > 0:
                scored.append((score, unit))
        scored.sort(key=lambda item: (item[0], len(str(item[1].get("unit_name_normalized") or ""))), reverse=True)
        return scored

    def _unit_official_staff_count(self, unit: dict[str, Any]) -> int:
        unit_id = unit.get("id")
        if not unit_id:
            return 0
        staff = self._dedup_people(self._repository.get_staff_by_unit(str(unit_id)))
        return sum(1 for row in staff if self._is_verified_yok_staff(row))

    def _unit_match_score(self, unit: dict[str, Any], normalized_question: str) -> int:
        unit_name = str(unit.get("unit_name") or "")
        normalized_name = str(unit.get("unit_name_normalized") or normalize_for_match(unit_name))
        unit_type = str(unit.get("unit_type") or "")
        aliases = set(self._unit_aliases(normalized_name, unit_type))
        for alias in unit.get("aliases") or []:
            normalized_alias = normalize_for_match(alias)
            if normalized_alias:
                aliases.add(normalized_alias)
        best = 0
        query_tokens = self._query_match_tokens(normalized_question)
        query_token_set = set(query_tokens)
        query_match_text = " ".join(query_tokens)
        for alias in aliases:
            if not alias:
                continue
            if " " not in alias:
                if alias in query_token_set:
                    base_score = self._single_token_alias_score(alias, query_tokens, normalized_question)
                    best = max(best, base_score + len(alias))
                continue
            if alias in normalized_question or alias in query_match_text:
                exact_base = 82 if alias in BROAD_SINGLE_TOKEN_ALIASES else (92 if " " not in alias else 130)
                best = max(best, exact_base + len(alias))
                continue
            fuzzy_score = self._alias_fuzzy_score(alias, query_tokens)
            if fuzzy_score:
                best = max(best, fuzzy_score)
        return best

    @staticmethod
    def _unit_aliases(normalized_name: str, unit_type: str | None = None) -> tuple[str, ...]:
        aliases = {normalized_name}
        for suffix in UNIT_SUFFIXES:
            if normalized_name.endswith(suffix):
                aliases.add(normalized_name[: -len(suffix)].strip())
        aliases.update(AcademicStaffService._generated_unit_aliases(normalized_name, unit_type))
        aliases.update(UNIT_ALIASES.get(normalized_name, ()))
        return tuple(alias for alias in aliases if alias)

    @staticmethod
    def _generated_unit_aliases(normalized_name: str, unit_type: str | None = None) -> set[str]:
        normalized_name = AcademicStaffService._compact_known_abbreviations(normalized_name)
        aliases: set[str] = set()
        base_names = {normalized_name}
        for suffix in UNIT_SUFFIXES:
            if normalized_name.endswith(suffix):
                base_names.add(normalized_name[: -len(suffix)].strip())

        descriptor = AcademicStaffService._unit_descriptor(normalized_name, unit_type)
        for base_name in list(base_names):
            if not base_name:
                continue
            aliases.add(base_name)
            tokens = [token for token in base_name.split() if token]
            significant = [token for token in tokens if token not in ALIAS_STOPWORDS]
            no_stop = " ".join(significant)
            if no_stop:
                aliases.add(no_stop)

            aliases.update(AcademicStaffService._language_variant_aliases(significant))
            aliases.update(AcademicStaffService._technical_variant_aliases(significant))

            if len(significant) == 1:
                aliases.add(significant[0])
            elif len(significant) > 1:
                first_token = significant[0]
                first_two = " ".join(significant[:2])
                first_three = " ".join(significant[:3])
                aliases.add(first_two)
                if len(significant) >= 3:
                    aliases.add(first_three)
                if len(first_token) >= 5:
                    aliases.add(first_token)

                acronym = "".join(token[0] for token in significant if token and token not in UNIT_DESCRIPTOR_TOKENS)
                if len(acronym) >= 3:
                    aliases.add(acronym)
                    aliases.add(" ".join(acronym))

            if descriptor:
                for alias in list(aliases):
                    if alias and len(alias.split()) <= 3:
                        aliases.add(f"{alias} {descriptor}")
                        aliases.add(f"{alias} {descriptor}u")

        return {alias.strip() for alias in aliases if alias.strip()}

    @staticmethod
    def _compact_known_abbreviations(value: str) -> str:
        return re.sub(r"\bm\s*t\s*o\s*k\b", "mtok", value)

    @staticmethod
    def _unit_descriptor(normalized_name: str, unit_type: str | None = None) -> str | None:
        normalized_type = normalize_for_match(unit_type)
        if normalized_name.endswith((" bolumu", " bolum")) or normalized_type in {"department", "bolum"}:
            return "bolum"
        if normalized_name.endswith((" programi", " program")) or normalized_type == "program":
            return "program"
        if normalized_name.endswith((" fakultesi", " fakulte")) or normalized_type in {"faculty", "fakulte"}:
            return "fakulte"
        return None

    @staticmethod
    def _unit_language_tokens(unit: dict[str, Any]) -> set[str]:
        normalized_name = str(
            unit.get("unit_name_normalized")
            or normalize_for_match(unit.get("unit_name"))
        )
        return set(normalized_name.split()).intersection(LANGUAGE_QUALIFIER_TOKENS)

    @staticmethod
    def _unit_identity_tokens(unit: dict[str, Any]) -> set[str]:
        normalized_name = str(
            unit.get("unit_name_normalized")
            or normalize_for_match(unit.get("unit_name"))
        )
        return {
            token
            for token in normalized_name.split()
            if token and token not in ALIAS_STOPWORDS
        }

    @staticmethod
    def _unit_core_identity(unit: dict[str, Any]) -> str:
        normalized_name = str(
            unit.get("unit_name_normalized")
            or normalize_for_match(unit.get("unit_name"))
        )
        tokens = [
            token
            for token in normalized_name.split()
            if (
                token
                and token not in ALIAS_STOPWORDS
                and token not in UNIT_DESCRIPTOR_TOKENS
                and token not in LANGUAGE_QUALIFIER_TOKENS
            )
        ]
        return " ".join(tokens)

    @staticmethod
    def _unit_base_without_language(unit: dict[str, Any]) -> str:
        normalized_name = str(
            unit.get("unit_name_normalized")
            or normalize_for_match(unit.get("unit_name"))
        )
        tokens = [
            token
            for token in normalized_name.split()
            if token not in LANGUAGE_QUALIFIER_TOKENS
        ]
        return " ".join(tokens)

    @staticmethod
    def _language_variant_aliases(tokens: list[str]) -> set[str]:
        aliases: set[str] = set()
        languages = [token for token in tokens if token in LANGUAGE_QUALIFIER_TOKENS]
        if not languages:
            return aliases
        rest = [token for token in tokens if token not in LANGUAGE_QUALIFIER_TOKENS]
        rest_without_mtok = [token for token in rest if token != "mtok"]
        for language in languages:
            if rest_without_mtok:
                aliases.add(" ".join([language, *rest_without_mtok]))
                aliases.add(" ".join([*rest_without_mtok, language]))
            if "mtok" in rest:
                aliases.add(" ".join([language, *rest_without_mtok, "mtok"]))
                aliases.add(" ".join([*rest_without_mtok, language, "mtok"]))
        return aliases

    @staticmethod
    def _technical_variant_aliases(tokens: list[str]) -> set[str]:
        aliases: set[str] = set()
        if not tokens:
            return aliases

        def add_replaced(source: list[str], old: str, replacements: tuple[str, ...]) -> None:
            if old not in source:
                return
            for replacement in replacements:
                replaced = [replacement if token == old else token for token in source]
                aliases.add(" ".join(replaced))

        add_replaced(tokens, "muhendisligi", ("muh", "muhendislik"))
        add_replaced(tokens, "programciligi", ("programi", "program"))
        add_replaced(tokens, "tercumanlik", ("tercuman",))

        if "muhendisligi" in tokens:
            index = tokens.index("muhendisligi")
            prefix = tokens[:index]
            if prefix:
                aliases.add(" ".join([*prefix, "muh"]))
                aliases.add(" ".join([*prefix, "muhendislik"]))
        if "programciligi" in tokens:
            index = tokens.index("programciligi")
            prefix = tokens[:index]
            if prefix:
                aliases.add(" ".join([*prefix, "programi"]))
                aliases.add(" ".join([*prefix, "program"]))
        if "tercumanlik" in tokens and "mutercim" in tokens:
            without_mutercim = [token for token in tokens if token != "mutercim"]
            aliases.add(" ".join(without_mutercim))
        return aliases

    @staticmethod
    def _single_token_alias_score(alias: str, query_tokens: list[str], normalized_question: str) -> int:
        if len(query_tokens) == 1:
            return 150 if alias not in BROAD_SINGLE_TOKEN_ALIASES else 112
        if any(token in UNIT_CONTEXT_TOKENS for token in normalized_question.split()):
            return 108 if alias not in BROAD_SINGLE_TOKEN_ALIASES else 82
        if alias in GENERIC_SINGLE_TOKEN_ALIASES or alias in BROAD_SINGLE_TOKEN_ALIASES:
            return 36
        return 72

    @staticmethod
    def _query_match_tokens(normalized_question: str) -> list[str]:
        tokens: list[str] = []
        for token in normalized_question.split():
            if not token:
                continue
            if token in QUERY_NOISE_TOKENS:
                continue
            if (
                token.startswith("kadro")
                or token.startswith("hoca")
                or token.startswith("akademisyen")
                or token.startswith("gorevli")
            ):
                continue
            tokens.append(token)
        return tokens

    @staticmethod
    def _alias_fuzzy_score(alias: str, query_tokens: list[str]) -> int:
        alias_tokens = [token for token in alias.split() if token and token not in {"ve", "ile"}]
        if not alias_tokens or not query_tokens:
            return 0

        matched_scores: list[int] = []
        used_query_indexes: set[int] = set()
        for alias_token in alias_tokens:
            best_score = 0
            best_index = -1
            for index, query_token in enumerate(query_tokens):
                if index in used_query_indexes:
                    continue
                score = AcademicStaffService._token_match_score(query_token, alias_token)
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_score > 0 and best_index >= 0:
                used_query_indexes.add(best_index)
                matched_scores.append(best_score)

        matched_count = len(matched_scores)
        if not matched_count:
            return 0

        coverage = matched_count / len(alias_tokens)
        if len(alias_tokens) == 1:
            if max(matched_scores) < 12:
                return 0
        elif len(alias_tokens) == 2:
            if coverage < 1.0:
                return 0
        elif coverage < 0.72:
            return 0

        exactish_bonus = 16 if all(score >= 12 for score in matched_scores) else 0
        return int(45 + sum(matched_scores) + (coverage * 20) + exactish_bonus + min(len(alias), 30))

    @staticmethod
    def _token_match_score(query_token: str, alias_token: str) -> int:
        if query_token == alias_token:
            return 16
        if len(query_token) >= 3 and alias_token.startswith(query_token):
            return 13
        if len(alias_token) >= 4 and query_token.startswith(alias_token):
            return 12
        if len(query_token) < 4 or len(alias_token) < 4:
            return 0
        similarity = SequenceMatcher(None, query_token, alias_token).ratio()
        if similarity >= 0.88:
            return 12
        if similarity >= 0.82:
            return 9
        return 0

    def _department_program_candidates(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates = [unit for unit in units if self._is_department_or_program_unit(unit)]
        return candidates or units

    def _looks_like_person_query(self, normalized_question: str) -> bool:
        if not PERSON_QUERY_RE.search(normalized_question):
            return False
        name_query = self._extract_name_query(normalized_question)
        return len(name_query.split()) >= 2

    @staticmethod
    def _extract_name_query(normalized_question: str) -> str:
        tokens = [
            token
            for token in normalized_question.split()
            if len(token) > 1 and token not in PERSON_QUERY_NOISE_TOKENS
        ]
        cleaned: list[str] = []
        for token in tokens:
            if token in {"un", "in", "nin", "nun", "nün"}:
                continue
            cleaned.append(token)
        return " ".join(cleaned[:4]).strip()

    def _search_person_candidates(self, name_query: str) -> list[dict[str, Any]]:
        search_phrases = self._person_search_phrases(name_query)
        rows_by_key: dict[str, dict[str, Any]] = {}
        for phrase in search_phrases:
            for row in self._repository.search_persons(phrase):
                key = str(row.get("person_id") or row.get("normalized_name") or row.get("full_name"))
                rows_by_key.setdefault(key, row)
        return list(rows_by_key.values())

    @staticmethod
    def _person_search_phrases(name_query: str) -> list[str]:
        tokens = name_query.split()
        phrases: list[str] = []
        for size in range(min(4, len(tokens)), 1, -1):
            for index in range(0, len(tokens) - size + 1):
                phrase = " ".join(tokens[index:index + size])
                if phrase not in phrases:
                    phrases.append(phrase)
        if name_query and name_query not in phrases:
            phrases.append(name_query)
        for token in tokens:
            if len(token) >= 4 and token not in phrases:
                phrases.append(token)
        return phrases

    @staticmethod
    def _dedup_people(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(
                row.get("person_id")
                or AcademicStaffService._yok_url(row)
                or f"{row.get('normalized_name') or row.get('full_name')}:{row.get('unit_id') or ''}"
            )
            if key not in by_key:
                by_key[key] = row
                continue
            current = by_key[key]
            if AcademicStaffService._record_score(row) > AcademicStaffService._record_score(current):
                by_key[key] = row
        return sorted(by_key.values(), key=lambda item: str(item.get("full_name") or ""))

    @staticmethod
    def _record_score(row: dict[str, Any]) -> int:
        score = 0
        if AcademicStaffService._yok_url(row):
            score += 5
        if not AcademicStaffService._needs_review(row):
            score += 2
        if row.get("confidence_status") in VERIFIED_YOK_STATUSES:
            score += 2
        return score

    @staticmethod
    def _split_official_and_candidate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        official: list[dict[str, Any]] = []
        review_rows: list[dict[str, Any]] = []
        for row in rows:
            if AcademicStaffService._is_verified_yok_staff(row):
                official.append(row)
            else:
                review_rows.append(row)
        return official, review_rows

    @staticmethod
    def _is_verified_yok_staff(row: dict[str, Any]) -> bool:
        status_values = {
            str(row.get("source_status") or ""),
            str(row.get("person_source_status") or ""),
            str(row.get("confidence_status") or ""),
        }
        return (
            bool(status_values.intersection(VERIFIED_YOK_STATUSES))
            and not AcademicStaffService._needs_review(row)
            and bool(AcademicStaffService._yok_url(row))
        )

    def _format_staff_section(
        self,
        heading: str,
        official_staff: list[dict[str, Any]],
        review_staff: list[dict[str, Any]],
    ) -> str:
        lines = [f"**{heading}**"]
        if official_staff:
            lines.extend(self._format_person_line(person) for person in official_staff)
        else:
            lines.append("- YÖK Akademik üzerinden doğrulanmış bölüm/program personel kaydı bulunamadı.")
        lines.append("")
        lines.append("Kaynak: YÖK Akademik")
        last_checked_at = self._latest_checked_at(official_staff)
        if last_checked_at:
            lines.append(f"Son kontrol tarihi: {self._format_checked_at(last_checked_at)}")
        if review_staff:
            lines.append("")
            lines.append(
                f"Not: {len(review_staff)} kayıt bölüm/program eşleşmesi, kurum uyumu veya profil URL eksikliği nedeniyle kesin kadro listesine alınmadı."
            )
        return "\n".join(lines)

    def _format_person_line(self, person: dict[str, Any]) -> str:
        title = f"{person.get('title')} " if person.get("title") else ""
        return f"- {title}{person.get('full_name')}"

    @staticmethod
    def _latest_checked_at(rows: list[dict[str, Any]]) -> Any:
        values = [row.get("last_checked_at") for row in rows if row.get("last_checked_at")]
        if not values:
            return None
        return max(values, key=lambda item: str(item))

    @staticmethod
    def _profile_map(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for profile in row.get("external_profiles") or []:
            profile_type = str(profile.get("profile_type") or "")
            if profile_type:
                profiles.setdefault(profile_type, profile)
        return profiles

    @staticmethod
    def _yok_url(row: dict[str, Any]) -> str | None:
        for profile in row.get("external_profiles") or []:
            if profile.get("profile_type") == "yok_akademik" and profile.get("profile_url"):
                return str(profile["profile_url"])
        return None

    @staticmethod
    def _yok_unit_text(row: dict[str, Any]) -> str | None:
        for profile in row.get("external_profiles") or []:
            if profile.get("profile_type") != "yok_akademik":
                continue
            raw_data = profile.get("raw_data") or {}
            if isinstance(raw_data, str):
                raw_data = {}
            parts = [
                raw_data.get("kadro_parent_unit") or raw_data.get("faculty_from_yok"),
                raw_data.get("kadro_department") or raw_data.get("department_from_yok"),
                raw_data.get("kadro_subunit"),
            ]
            text = " / ".join(str(part) for part in parts if part)
            if text:
                return text
            unit_text = raw_data.get("kadro_veri_raw")
            if unit_text:
                return str(unit_text)[:180]
        return None

    @staticmethod
    def _confidence_label(row: dict[str, Any]) -> str:
        status = row.get("confidence_status") or row.get("match_status") or "unknown"
        score = row.get("confidence_score")
        if score is None:
            return str(status)
        try:
            return f"{status} ({float(score):.2f})"
        except (TypeError, ValueError):
            return str(status)

    @staticmethod
    def _needs_review(row: dict[str, Any]) -> bool:
        return bool(
            row.get("needs_manual_review")
            or row.get("person_needs_manual_review")
            or row.get("source_status") in REVIEW_YOK_STATUSES
            or row.get("person_source_status") in REVIEW_YOK_STATUSES
            or row.get("confidence_status") in REVIEW_YOK_STATUSES
        )

    @staticmethod
    def _format_checked_at(value: Any) -> str:
        text = str(value)
        if "T" in text:
            return text.split("T", 1)[0]
        return text.split(" ", 1)[0]

    def _sources_from_records(self, rows: list[dict[str, Any]], doc_kind: str) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for row in rows:
            source_url = self._yok_url(row) or row.get("source_url")
            if not source_url:
                continue
            sources.append({
                "content": self._source_content(row, doc_kind),
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "akademik_kadro",
                "title": row.get("unit_name") or row.get("full_name") or "Akademik kadro",
                "doc_kind": doc_kind,
            })
        return sources

    @staticmethod
    def _source_content(row: dict[str, Any], doc_kind: str) -> str:
        return f"{row.get('full_name')} — {row.get('unit_name')} — YÖK Akademik"

    @staticmethod
    def _dedup_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for source in sources:
            key = (str(source.get("source_url") or ""), str(source.get("content") or ""))
            if key in seen:
                continue
            seen.add(key)
            unique.append(source)
        return unique

    @staticmethod
    def _is_faculty_unit(unit: dict[str, Any]) -> bool:
        return str(unit.get("unit_type") or "") in {"fakulte", "faculty"}

    @staticmethod
    def _is_department_or_program_unit(unit: dict[str, Any]) -> bool:
        return str(unit.get("unit_type") or "") in {"bolum", "department", "program"}

    def _is_academic_staff_option_unit(self, unit: dict[str, Any]) -> bool:
        return (
            self._is_department_or_program_unit(unit)
            and (
                self._unit_official_staff_count(unit) > 0
                or self._is_yok_academic_source_url(unit.get("source_url"))
            )
        )

    @staticmethod
    def _is_yok_academic_source_url(source_url: Any) -> bool:
        return "akademik.yok.gov.tr" in str(source_url or "").lower()

    @staticmethod
    def _not_found_response(message: str, unit: dict[str, Any], review_count: int = 0) -> dict[str, Any]:
        source_url = unit.get("source_url")
        response = f"{message}\n\nBu alan için canlı scrape veya RAG tahmini yapılmadı."
        if review_count:
            response += (
                f"\n\nNot: {review_count} kayıt YÖK profil URL'si, kurum uyumu veya bölüm/program eşleşmesi "
                "net olmadığı için kesin kadro listesine alınmadı."
            )
        sources = []
        if AcademicStaffService._is_yok_academic_source_url(source_url):
            sources.append({
                "content": f"{unit.get('unit_name')} birim kaynağı.",
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "akademik_kadro",
                "title": unit.get("unit_name"),
                "doc_kind": "akademik_birim",
            })
        return {"response": response, "sources": sources}


@lru_cache()
def get_academic_staff_service() -> AcademicStaffService:
    return AcademicStaffService()
