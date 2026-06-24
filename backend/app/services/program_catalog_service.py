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

EXPLICIT_CATALOG_SIGNAL_RE = re.compile(
    r"\b("
    r"fakülte\w*|fakulte\w*|yüksekokul\w*|yuksekokul\w*|myo|"
    r"meslek\s+yüksekokul\w*|meslek\s+yuksekokul\w*|enstitü\w*|enstitu\w*|"
    r"bölüm\w*|bolum\w*|program\w*|lisans|ön\s*lisans|on\s*lisans|onlisans|"
    r"hangi\s+birim\w*|hangi\s+fakülte\w*|hangi\s+fakulte\w*|hangi\s+myo\w*|"
    r"hangi\s+okul\w*|hangi\s+yüksekokul\w*|hangi\s+yuksekokul\w*|"
    r"bağlı|bagli|bünyesinde|bunyesinde"
    r")\b",
    re.IGNORECASE,
)

CATALOG_SIGNAL_RE = re.compile(
    r"\b("
    r"fakülte\w*|fakulte\w*|yüksekokul\w*|yuksekokul\w*|myo|"
    r"meslek\s+yüksekokul\w*|meslek\s+yuksekokul\w*|enstitü\w*|enstitu\w*|"
    r"bölüm\w*|bolum\w*|program\w*|lisans|ön\s*lisans|on\s*lisans|onlisans|"
    r"hangi\s+birim\w*|hangi\s+fakülte\w*|hangi\s+fakulte\w*|hangi\s+myo\w*|"
    r"hangi\s+okul\w*|hangi\s+yüksekokul\w*|hangi\s+yuksekokul\w*|"
    r"bağlı|bagli|bünyesinde|bunyesinde|"
    r"var\s*m[ıi]|varm[ıi]|mevcut\s*m[ıiuü]|mevcutm[ıiuü]|"
    r"bulun(?:uyor|ur)\s*m[ıiuü]|yok\s*m[ıiuü]|yokm[ıiuü]|"
    r"aç(?:ıl(?:dı|di|mış|mis)|ık)\s*m[ıi]|ac(?:il(?:di|mis)|ik)\s*m[ıi]|"
    r"aç(?:ıldı|ildi|ılmış|ilmis)m[ıi]|ac(?:ildi|ilmis)m[ıi]|aktif\s*m[ıi]|aktifm[ıi]"
    r")\b",
    re.IGNORECASE,
)

LIST_WORD_RE = re.compile(r"\b(hangi|hangileri|neler|nelerdir|liste|listesi|listele\w*|say|göster|goster)\b", re.IGNORECASE)
EXISTS_RE = re.compile(
    r"\b("
    r"var\s*m[ıi]|varm[ıi]|"
    r"mevcut\s*m[ıiuü]|mevcutm[ıiuü]|"
    r"bulun(?:uyor|ur)\s*m[ıiuü]|"
    r"yok\s*m[ıiuü]|yokm[ıiuü]|"
    r"aç(?:ıl(?:dı|di|mış|mis)|ık)\s*m[ıi]|ac(?:il(?:di|mis)|ik)\s*m[ıi]|"
    r"aç(?:ıldı|ildi|ılmış|ilmis)m[ıi]|ac(?:ildi|ilmis)m[ıi]|"
    r"aktif\s*m[ıi]|aktifm[ıi]"
    r")\b",
    re.IGNORECASE,
)
UNIT_LOOKUP_RE = re.compile(
    r"\b("
    r"hangi\s+fakulte\w*|hangi\s+fakülte\w*|hangi\s+birim\w*|"
    r"hangi\s+myo\w*|hangi\s+okul\w*|hangi\s+yüksekokul\w*|hangi\s+yuksekokul\w*|"
    r"nerede|nereye\s+bagli|nereye\s+bağlı|"
    r"hangi\s+birime\s+bagli|hangi\s+birime\s+bağlı|bagli|bağlı|"
    r"bünyesinde|bunyesinde"
    r")\b",
    re.IGNORECASE,
)

NAMED_CATALOG_EXISTS_RE = re.compile(
    r"\b(\w+\s+){0,5}(muhendisligi|fakultesi|bolumu|programi|hekimligi)\b|"
    r"\b(tip|ebelik|hemsirelik|fizyoterapi|eczacilik|veteriner|psikoloji|mimarlik|gastronomi|tercumanlik|ilahiyat)\b",
    re.IGNORECASE,
)

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
    r"idari\s+birim\w*|idari\s+personel\w*|öğrenci\s+iş\w*|ogrenci\s+is\w*|"
    r"taban\s+puan\w*|kaç\s+puan\w*|kac\s+puan\w*|"
    r"başarı\s+sıra\w*|basari\s+sira\w*|sıralama\w*|siralama\w*|"
    r"puan\s+tür\w*|puan\s+tur\w*|ösym|osym|kontenjan\w*|"
    r"ders\s+kayd\w*|ders\s+kayit\w*|akademik\s+takvim|"
    r"yemek\w*|yemekhane\w*|ulaşım\w*|ulasim\w*|yurt\w*|"
    r"erasmus|değişim\w*|degisim\w*|burs\w*|staj\w*|"
    r"kütüphane\w*|kutuphane\w*|kampüs\w*|kampus\w*|"
    r"imkan\w*|olanak\w*|kulüp\w*|kulup\w*|topluluk\w*|"
    r"sıkça\s+sorulan|sikca\s+sorulan|sık\s+sorulan|sik\s+sorulan|sss|faq"
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
    r"sıkça\s+sorulan|sikca\s+sorulan|sık\s+sorulan|sik\s+sorulan|sss|"
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
    "hangisi",
    "hangileri",
    "neler",
    "nelerdir",
    "nedir",
    "mi",
    "mı",
    "mu",
    "mü",
    "var",
    "varmi",
    "yok",
    "yokmu",
    "mevcut",
    "mevcutmu",
    "bulunuyor",
    "bulunur",
    "bulunuyormu",
    "bulunurmu",
    "mudur",
    "midir",
    "acik",
    "acikmi",
    "acildi",
    "acildimi",
    "acilmis",
    "acilmismi",
    "aktif",
    "aktifmi",
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

LIST_DESCRIPTOR_TOKENS: frozenset[str] = frozenset({
    "birimler",
    "birimleri",
    "bolumler",
    "bolumleri",
    "enstituler",
    "enstituleri",
    "fakulteler",
    "fakulteleri",
    "programlar",
    "programlari",
    "yuksekokullar",
    "yuksekokullari",
})

CHILD_LIST_TOKENS: frozenset[str] = frozenset({
    "bolum",
    "bolumu",
    "bolumler",
    "bolumleri",
    "program",
    "programi",
    "programlar",
    "programlari",
})

CATALOG_TYPE_SUFFIXES: tuple[str, ...] = (
    "meslek yuksekokulu",
    "meslek yuksekokul",
    "yuksekokulu",
    "yuksekokul",
    "fakultesi",
    "fakulte",
    "enstitusu",
    "enstitu",
    "bolumu",
    "bolum",
    "programi",
    "program",
)

ACRONYM_STOPWORDS: frozenset[str] = frozenset({"ve", "ile", "the", "of"})

COMMON_RUNTIME_ALIASES: dict[str, set[str]] = {
    "fizyoterapi": {"ftr", "fizik tedavi", "fizik tedavi rehabilitasyon"},
    "fizyoterapi ve rehabilitasyon": {"ftr", "fizik tedavi", "fizik tedavi rehabilitasyon"},
}

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


def _has_list_signal(value: str) -> bool:
    normalized = normalize_for_match(value)
    tokens = set(normalized.split())
    return bool(
        LIST_WORD_RE.search(value)
        or LIST_WORD_RE.search(normalized)
        or tokens.intersection(LIST_DESCRIPTOR_TOKENS)
    )


def _strip_catalog_type_suffix(value: str) -> str:
    text = normalize_for_match(value)
    previous = None
    while previous != text:
        previous = text
        for suffix in CATALOG_TYPE_SUFFIXES:
            if text == suffix:
                return ""
            if text.endswith(f" {suffix}"):
                text = text[: -(len(suffix) + 1)].strip()
                break
    return text


def _compact_alias(value: str) -> str:
    return re.sub(r"\s+", "", normalize_for_match(value))


def _acronym(tokens: list[str]) -> str:
    return "".join(token[0] for token in tokens if token and token not in ACRONYM_STOPWORDS)


def _generated_acronyms(normalized_value: str) -> set[str]:
    tokens = [token for token in normalized_value.split() if token]
    useful_tokens = [token for token in tokens if token not in ACRONYM_STOPWORDS]
    aliases: set[str] = set()
    base = _acronym(useful_tokens)
    if 2 <= len(base) <= 10:
        aliases.add(base)

    if len(tokens) >= 2 and tokens[-2:] in (["meslek", "yuksekokulu"], ["meslek", "yuksekokul"]):
        content = [token for token in tokens[:-2] if token not in ACRONYM_STOPWORDS]
        content_base = _acronym(content)
        if content_base:
            aliases.add(f"{content_base}myo")
    if tokens and tokens[-1] in {"yuksekokulu", "yuksekokul"}:
        content = [token for token in tokens[:-1] if token not in ACRONYM_STOPWORDS]
        content_base = _acronym(content)
        if content_base:
            aliases.add(f"{content_base}yo")
    if tokens and tokens[-1] in {"enstitusu", "enstitu"}:
        content = [token for token in tokens[:-1] if token not in ACRONYM_STOPWORDS]
        content_base = _acronym(content)
        if content_base:
            aliases.add(f"{content_base}e")
    return aliases


def _generated_shorthand_aliases(normalized_value: str) -> set[str]:
    tokens = [token for token in normalized_value.split() if token]
    aliases: set[str] = set()
    if len(tokens) >= 3 and tokens[-2:] in (["meslek", "yuksekokulu"], ["meslek", "yuksekokul"]):
        content = [token for token in tokens[:-2] if token not in ACRONYM_STOPWORDS]
        if content:
            first = content[0]
            aliases.add(f"{first} meslek yuksekokulu")
            aliases.add(f"{first} meslek yuksekokul")
            aliases.add(f"{first} myo")
    return aliases


def _generated_leading_aliases(normalized_value: str, allow_single_token: bool) -> set[str]:
    stripped = _strip_catalog_type_suffix(normalized_value)
    tokens = [token for token in stripped.split() if token and token not in ACRONYM_STOPWORDS]
    aliases: set[str] = set()
    if not tokens:
        return aliases

    max_phrase_len = min(3, len(tokens))
    for size in range(2, max_phrase_len + 1):
        aliases.add(" ".join(tokens[:size]))

    connector_based_single = any(connector in normalized_value.split() for connector in ACRONYM_STOPWORDS)
    if allow_single_token or connector_based_single:
        first = tokens[0]
        if len(first) >= 4:
            aliases.add(first)
    return aliases


def _catalog_aliases(
    name: Any,
    aliases: list[Any],
    allow_single_token_alias: bool = False,
) -> set[str]:
    alias_values: set[str] = set()

    def add_generated(candidate: str, include_stripped: bool) -> None:
        candidate = candidate.strip()
        if not candidate:
            return
        alias_values.add(candidate)
        compact = _compact_alias(candidate)
        if len(compact) >= 4:
            alias_values.add(compact)
        if include_stripped:
            stripped = _strip_catalog_type_suffix(candidate)
            if stripped:
                alias_values.add(stripped)
                stripped_compact = _compact_alias(stripped)
                if len(stripped_compact) >= 4:
                    alias_values.add(stripped_compact)
        alias_values.update(_generated_acronyms(candidate))
        alias_values.update(_generated_shorthand_aliases(candidate))
        alias_values.update(_generated_leading_aliases(candidate, allow_single_token_alias))

    normalized_names = {normalize_for_match(name), normalize_program_name(name)}
    for candidate in normalized_names:
        add_generated(candidate, include_stripped=True)
    for candidate in normalized_names:
        for catalog_name, common_aliases in COMMON_RUNTIME_ALIASES.items():
            if candidate == catalog_name or catalog_name in candidate:
                for common_alias in common_aliases:
                    add_generated(common_alias, include_stripped=False)
    for alias in aliases:
        normalized_alias = normalize_for_match(alias)
        add_generated(normalized_alias, include_stripped=False)

    alias_values.discard("")
    return alias_values


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
        has_exists_query = self._has_existence_signal(normalized_question)

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

        raw_units = units
        raw_entries = entries
        units = self._visible_units(raw_units, candidate_context=candidate_context)
        entries = self._visible_entries(raw_entries, candidate_context=candidate_context)

        if not candidate_context:
            fallback_units = self._candidate_fallback_units(raw_units)
            fallback_entries = self._candidate_fallback_entries(raw_entries)
            if not entries and fallback_entries:
                entries = fallback_entries
                units = self._merge_units(units, fallback_units)
            elif not units and fallback_units:
                units = fallback_units

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
        entry = entry_match.get("entry")

        if unit and self._asks_if_unit_is_department(normalized_question):
            return self._unit_type_response(unit, normalized_question)

        if unit and self._is_unit_children_query(normalized_question):
            child_kind = "program" if unit.get("unit_type") == "vocational_school" else "department"
            return self._format_unit_children(unit, entries, child_kind, normalized_question)

        if entry and self._is_entry_unit_lookup(normalized_question):
            return self._entry_unit_response(entry, normalized_question)

        if unit and self._is_entry_unit_lookup(normalized_question):
            return self._unit_type_response(unit, normalized_question)

        if entry_match["status"] == "ambiguous":
            if EXISTS_RE.search(normalized_question):
                candidate_multi = self._candidate_same_name_exists_response(entry_match["candidates"], normalized_question)
                if candidate_multi:
                    return candidate_multi
            return self._ambiguous_entries(entry_match["candidates"], normalized_question)

        if has_exists_query:
            if unit and self._is_unit_existence_query(normalized_question):
                return self._unit_type_response(unit, normalized_question)
            if entry:
                return self._entry_exists_response(entry, normalized_question)
            if unit and not self._is_program_field_existence_query(normalized_question):
                return self._unit_type_response(unit, normalized_question)
            if not self._should_return_negative_exists(question, normalized_question, candidate_context):
                return None
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
        normalized_question = normalize_for_match(original_question)
        return bool(
            CATALOG_HARD_BLOCKER_RE.search(original_question)
            or CATALOG_HARD_BLOCKER_RE.search(normalized_question)
        )

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
        if self._has_explicit_catalog_signal(original_question, normalized_question):
            return True
        return self._has_existence_signal(normalized_question)

    @staticmethod
    def _has_explicit_catalog_signal(original_question: str, normalized_question: str) -> bool:
        return bool(
            EXPLICIT_CATALOG_SIGNAL_RE.search(original_question)
            or EXPLICIT_CATALOG_SIGNAL_RE.search(normalized_question)
        )

    @staticmethod
    def _has_existence_signal(normalized_question: str) -> bool:
        return bool(EXISTS_RE.search(normalized_question))

    def _should_return_negative_exists(
        self,
        original_question: str,
        normalized_question: str,
        candidate_context: bool,
    ) -> bool:
        return (
            candidate_context
            or self._contains_nonexistent_guard(normalized_question)
            or self._has_explicit_catalog_signal(original_question, normalized_question)
            or self._has_named_catalog_exists_hint(normalized_question)
        )

    @staticmethod
    def _contains_nonexistent_guard(normalized_question: str) -> bool:
        return any(f" {guard} " in f" {normalized_question} " for guard in NON_EXISTENT_PROGRAMS)

    @staticmethod
    def _has_named_catalog_exists_hint(normalized_question: str) -> bool:
        return bool(NAMED_CATALOG_EXISTS_RE.search(normalized_question))

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
    def _candidate_fallback_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            ProgramCatalogService._candidate_record_as_general(unit)
            for unit in units
            if unit.get("match_status") != "candidate_only"
            and unit.get("db_first_answerable", True) is not False
            and ProgramCatalogService._is_candidate_unit(unit)
        ]

    @staticmethod
    def _candidate_fallback_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            ProgramCatalogService._candidate_record_as_general(entry)
            for entry in entries
            if entry.get("match_status") != "candidate_only"
            and entry.get("db_first_answerable", True) is not False
            and ProgramCatalogService._is_candidate_entry(entry)
            and not ProgramCatalogService._candidate_entry_is_unit_card(entry)
        ]

    @staticmethod
    def _candidate_record_as_general(record: dict[str, Any]) -> dict[str, Any]:
        general_record = dict(record)
        general_record["source_type"] = "candidate_page_general_catalog_fallback"
        general_record["answer_scope"] = "general_catalog_fallback"
        general_record["candidate_general_fallback"] = True
        return general_record

    @staticmethod
    def _candidate_entry_is_unit_card(entry: dict[str, Any]) -> bool:
        program_name = normalize_for_match(entry.get("program_name") or "")
        unit_name = normalize_for_match(entry.get("unit_name") or "")
        return bool(
            program_name
            and unit_name
            and program_name == unit_name
            and entry.get("unit_type") in {"faculty", "school", "vocational_school", "institute"}
        )

    @staticmethod
    def _merge_units(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = list(primary)
        seen = {
            normalize_for_match(unit.get("normalized_unit_name") or unit.get("unit_name") or "")
            for unit in primary
        }
        for unit in fallback:
            key = normalize_for_match(unit.get("normalized_unit_name") or unit.get("unit_name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(unit)
        return merged

    @staticmethod
    def _is_ambiguous_health_query(normalized_question: str) -> bool:
        if any(token in normalized_question for token in ("meslek", "myo", "yuksekokul")):
            return False
        return (
            "saglik" in normalized_question
            and "bilimleri" not in normalized_question
            and "hizmetleri" not in normalized_question
            and bool(set(normalized_question.split()).intersection(CHILD_LIST_TOKENS) or _has_list_signal(normalized_question))
        )

    @staticmethod
    def _asks_if_unit_is_department(normalized_question: str) -> bool:
        return "bolum mu" in normalized_question or "program mi" in normalized_question or "bolum mudur" in normalized_question

    @staticmethod
    def _is_unit_children_query(normalized_question: str) -> bool:
        return _has_list_signal(normalized_question) and bool(
            set(normalized_question.split()).intersection(CHILD_LIST_TOKENS)
        )

    @staticmethod
    def _is_entry_unit_lookup(normalized_question: str) -> bool:
        return bool(UNIT_LOOKUP_RE.search(normalized_question)) or (
            "hangi" in normalized_question
            and ("fak" in normalized_question or "birim" in normalized_question or "myo" in normalized_question or "okul" in normalized_question)
        )

    @staticmethod
    def _is_unit_existence_query(normalized_question: str) -> bool:
        return bool(
            re.search(
                r"\b(fakulte\w*|myo\w*|meslek\s+yuksekokul\w*|yuksekokul\w*|enstitu\w*)\b",
                normalized_question,
            )
        )

    @staticmethod
    def _is_program_field_existence_query(normalized_question: str) -> bool:
        return bool(re.search(r"\b(muhendisligi|hekimligi)\b", normalized_question))

    def _resolve_unit(self, normalized_question: str, units: list[dict[str, Any]]) -> dict[str, Any]:
        strong_scored: list[tuple[int, dict[str, Any]]] = []
        weak_scored: list[tuple[int, dict[str, Any]]] = []
        query_tokens = self._query_tokens(normalized_question)
        for unit in units:
            strong_score = self._name_score(
                unit.get("unit_name"),
                unit.get("aliases") or [],
                normalized_question,
                query_tokens,
                allow_single_token_alias=False,
            )
            if strong_score >= MIN_ENTRY_MATCH_SCORE:
                strong_scored.append((strong_score, unit))
                continue

            weak_score = self._name_score(
                unit.get("unit_name"),
                unit.get("aliases") or [],
                normalized_question,
                query_tokens,
                allow_single_token_alias=True,
            )
            if weak_score >= MIN_ENTRY_MATCH_SCORE:
                weak_scored.append((weak_score, unit))
        return self._resolve_scored(strong_scored or weak_scored, "unit")

    def _resolve_entry(self, normalized_question: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        if self._contains_nonexistent_guard(normalized_question):
            return {"status": "not_found", "entry": None, "candidates": []}
        scored: list[tuple[int, dict[str, Any]]] = []
        query_tokens = self._query_tokens(normalized_question)
        for entry in entries:
            if not self._entry_matches_field_suffix_context(entry, normalized_question, query_tokens):
                continue
            if self._single_token_entry_is_overextended(entry, normalized_question):
                continue
            score = self._name_score(entry.get("program_name"), entry.get("aliases") or [], normalized_question, query_tokens)
            if score >= MIN_ENTRY_MATCH_SCORE:
                scored.append((score, entry))
        return self._resolve_scored(scored, "entry")

    @staticmethod
    def _entry_matches_field_suffix_context(
        entry: dict[str, Any],
        normalized_question: str,
        query_tokens: list[str],
    ) -> bool:
        suffix_tokens = {"muhendisligi", "hekimligi"}
        active_suffixes = set(normalized_question.split()).intersection(suffix_tokens)
        if not active_suffixes:
            return True

        entry_tokens = [
            token
            for token in normalize_for_match(entry.get("program_name") or "").split()
            if token not in ACRONYM_STOPWORDS
        ]
        query_specific_tokens = [
            token
            for token in query_tokens
            if token not in suffix_tokens and token not in ACRONYM_STOPWORDS
        ]
        entry_specific_tokens = [token for token in entry_tokens if token not in suffix_tokens]

        for suffix in active_suffixes:
            if suffix not in entry_tokens:
                return False
        if not query_specific_tokens:
            return True
        return any(
            ProgramCatalogService._token_score(query_token, entry_token) >= 20
            for query_token in query_specific_tokens
            for entry_token in entry_specific_tokens
        )

    @staticmethod
    def _single_token_entry_is_overextended(entry: dict[str, Any], normalized_question: str) -> bool:
        entry_name = normalize_for_match(entry.get("program_name") or "")
        entry_tokens = entry_name.split()
        if len(entry_tokens) != 1:
            return False
        query_tokens = normalized_question.split()
        entry_token = entry_tokens[0]
        if entry_token not in query_tokens:
            return False
        index = query_tokens.index(entry_token)
        suffix_window = set(query_tokens[index + 1:index + 3])
        return bool(suffix_window.intersection({"muhendisligi", "fakultesi", "hekimligi"}))

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
        allow_single_token_alias: bool = False,
    ) -> int:
        alias_values = _catalog_aliases(name, aliases, allow_single_token_alias=allow_single_token_alias)
        question_tokens = set(normalized_question.split())
        compact_question = _compact_alias(normalized_question)
        best = 0
        for alias in alias_values:
            tokens = alias.split()
            if len(tokens) == 1 and len(alias) <= 3:
                if alias in question_tokens:
                    best = max(best, 150 + len(alias))
                continue
            if len(tokens) == 1 and len(alias) <= 5:
                if alias in question_tokens:
                    best = max(best, 150 + len(alias))
                    continue
                if any(token.startswith(alias) and len(token) - len(alias) <= 4 for token in question_tokens):
                    best = max(best, 128 + len(alias))
                    continue
            if f" {alias} " in f" {normalized_question} ":
                best = max(best, 140 + min(len(alias), 40))
                continue
            if " " not in alias and len(alias) >= 4 and alias in compact_question:
                best = max(best, 130 + min(len(alias), 40))
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
        return int(ratio * 24) if ratio >= 0.80 else 0

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
    has_list_signal = _has_list_signal(original_question) or _has_list_signal(normalized)
    if re.search(r"\b(2|iki)\s*yillik\b", normalized) and has_list_signal:
        return "associate_degree_programs_query"
    if re.search(r"\b(4|dort)\s*yillik\b", normalized) and has_list_signal:
        return "undergraduate_programs_query"
    if "meslek yuksekokul" in normalized or "myo" in normalized:
        if has_list_signal and "program" not in normalized:
            return "vocational_school_list_query"
    if "yuksekokul" in normalized and "meslek" not in normalized:
        if has_list_signal and "program" not in normalized and "bolum" not in normalized:
            return "school_list_query"
    if "fakulte" in normalized and has_list_signal and "bolum" not in normalized:
        return "faculty_list_query"
    if "enstitu" in normalized and has_list_signal:
        return "institute_list_query"
    if "akademik birim" in normalized:
        return "academic_unit_list_query"
    if ("onlisans" in normalized or "on lisans" in normalized) and has_list_signal:
        return "associate_degree_programs_query"
    if "lisans" in normalized and "onlisans" not in normalized and "on lisans" not in normalized and has_list_signal:
        return "undergraduate_programs_query"
    if "program" in normalized and has_list_signal:
        return "program_list_query"
    if "bolum" in normalized and has_list_signal:
        return "department_list_query"
    if EXISTS_RE.search(original_question) or EXISTS_RE.search(normalized):
        return "program_exists_query"
    if UNIT_LOOKUP_RE.search(original_question) or UNIT_LOOKUP_RE.search(normalized):
        return "program_faculty_query"
    if EXPLICIT_CATALOG_SIGNAL_RE.search(original_question) or EXPLICIT_CATALOG_SIGNAL_RE.search(normalized):
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
