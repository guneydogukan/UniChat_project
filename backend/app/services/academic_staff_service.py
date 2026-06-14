"""
ÜniChat — YÖK Akademik bölüm/program akademik kadro yanıt servisi.

Bu fazda akademik kadro yanıtları yalnız YÖK Akademik kaynaklı structured
katmandan üretilir. Fakülte genel kadro listesi ve yönetim rolleri kapsam dışıdır.
"""

from __future__ import annotations

import logging
import re
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
    r"akademik\s+kadro\w*|akademik\s+personel\w*|akademisyen\w*|öğretim\s+üyes\w*|ogretim\s+uyes\w*|"
    r"öğretim\s+görevl\w*|ogretim\s+gorevl\w*|araştırma\s+görevl\w*|arastirma\s+gorevl\w*|"
    r"bölüm\s+başkan\w*|bolum\s+baskan\w*|dekan\w*|rektörlük\s+kadro\w*|rektorluk\s+kadro\w*|"
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
    r"\b(akademik\s+kadro\w*|akademik\s+personel\w*|akademisyen\w*|öğretim\s+üyes\w*|ogretim\s+uyes\w*|"
    r"öğretim\s+görevl\w*|ogretim\s+gorevl\w*|araştırma\s+görevl\w*|arastirma\s+gorevl\w*|kadro\w*)\b",
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
    "un",
    "in",
    "nin",
    "nun",
    "nün",
    "ve",
    "ile",
    "ait",
})

UNIT_SUFFIXES: tuple[str, ...] = (
    " bolumu",
    " programi",
    " fakultesi",
    " meslek yuksekokulu",
    " yuksekokulu",
    " enstitusu",
    " rektorlugu",
)

UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "muhendislik ve doga bilimleri fakultesi": ("mdbf", "muhendislik ve doga bilimleri"),
    "bilgisayar muhendisligi bolumu": ("bilgisayar muhendisligi", "bilgisayar"),
    "endustri muhendisligi bolumu": ("endustri muhendisligi", "endustri"),
    "elektrik elektronik muhendisligi bolumu": ("elektrik elektronik muhendisligi", "elektrik elektronik"),
    "elektrik-elektronik muhendisligi bolumu": ("elektrik elektronik muhendisligi", "elektrik elektronik"),
    "rektorluk": ("rektorluk kadrosu", "rektorluk"),
}


class AcademicStaffService:
    """YÖK Akademik structured bölüm/program kadro verisinden yanıt üretir."""

    def __init__(self, repository: AcademicRepository | None = None) -> None:
        self._repository = repository or AcademicRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        """Akademik kadro/profil sorusunu yanıtlar; değilse None döner."""
        if not ACADEMIC_STAFF_QUERY_RE.search(question):
            return None

        normalized_question = normalize_for_match(question)
        try:
            if MANAGEMENT_QUERY_RE.search(question):
                return None

            if PROFILE_QUERY_RE.search(question):
                profile_answer = self._answer_person_profile(question, normalized_question)
                if profile_answer is not None:
                    return profile_answer

            unit = self._match_unit(normalized_question)
            if unit and STAFF_QUERY_RE.search(question):
                return self._answer_staff(unit)
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
                f"{unit['unit_name']} için YÖK Akademik üzerinden doğrulanmış bölüm/program akademik kadro kaydı bulunamadı.",
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
            if self._is_department_or_program_unit(child)
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
        unit_name = str(unit.get("unit_name") or "")
        normalized_name = str(unit.get("unit_name_normalized") or normalize_for_match(unit_name))
        aliases = list(self._unit_aliases(normalized_name))
        best = 0
        for alias in aliases:
            if not alias:
                continue
            if alias in normalized_question:
                best = max(best, 100 + len(alias))
                continue
            tokens = [token for token in alias.split() if len(token) > 2]
            if len(tokens) >= 2 and all(token in normalized_question.split() for token in tokens):
                best = max(best, 40 + len(tokens))
        return best

    @staticmethod
    def _unit_aliases(normalized_name: str) -> tuple[str, ...]:
        aliases = {normalized_name}
        for suffix in UNIT_SUFFIXES:
            if normalized_name.endswith(suffix):
                aliases.add(normalized_name[: -len(suffix)].strip())
        aliases.update(UNIT_ALIASES.get(normalized_name, ()))
        return tuple(alias for alias in aliases if alias)

    @staticmethod
    def _extract_name_query(normalized_question: str) -> str:
        tokens = [
            token
            for token in normalized_question.split()
            if len(token) > 1 and token not in QUERY_NOISE_TOKENS
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
        lines.append("Bu liste YÖK Akademik filtreli bölüm/program sonuçları ve profil Kadro Veri alanı baz alınarak oluşturulmuştur.")
        if official_staff:
            lines.extend(self._format_person_line(person) for person in official_staff)
        else:
            lines.append("- YÖK Akademik üzerinden doğrulanmış bölüm/program personel kaydı bulunamadı.")
        if review_staff:
            lines.append("")
            lines.append(
                f"Not: {len(review_staff)} kayıt bölüm/program eşleşmesi, kurum uyumu veya profil URL eksikliği nedeniyle kesin kadro listesine alınmadı."
            )
        return "\n".join(lines)

    def _format_person_line(self, person: dict[str, Any]) -> str:
        title = f"{person.get('title')} " if person.get("title") else ""
        details: list[str] = []
        yok_url = self._yok_url(person)
        if yok_url:
            details.append(f"YÖK Akademik: {yok_url}")
        else:
            details.append("YÖK Akademik: not_resolved")
        yok_unit_text = self._yok_unit_text(person)
        if yok_unit_text:
            details.append(f"YÖK birim: {yok_unit_text}")
        details.append("kaynak: YÖK Akademik")
        details.append(f"durum: {self._confidence_label(person)}")
        if person.get("last_checked_at"):
            details.append(f"son kontrol: {self._format_checked_at(person.get('last_checked_at'))}")
        suffix = f" ({'; '.join(details)})" if details else ""
        return f"- {title}{person.get('full_name')}{suffix}"

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

    @staticmethod
    def _not_found_response(message: str, unit: dict[str, Any], review_count: int = 0) -> dict[str, Any]:
        source_url = unit.get("source_url")
        response = (
            f"{message}\n\n"
            "Bu alan için tahmin yapılmadı; sahte YÖK Akademik URL'si üretilmedi."
        )
        if review_count:
            response += (
                f"\n\nNot: {review_count} kayıt YÖK profil URL'si, kurum uyumu veya bölüm/program eşleşmesi "
                "net olmadığı için kesin kadro listesine alınmadı."
            )
        sources = []
        if source_url:
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
