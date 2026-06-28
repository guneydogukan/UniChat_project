"""
Mühendislik bölüm duyuruları için deterministik intent ve fuzzy eşleşme.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

DEPARTMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "bilgisayar_muhendisligi": (
        "bilgisayar muhendisligi",
        "bilgisayar muh",
        "bilgisayar bolumu",
        "bilgisayar",
        "bmb",
    ),
    "elektrik_elektronik_muhendisligi": (
        "elektrik elektronik muhendisligi",
        "elektrik elektronik",
        "elektrik-elektronik",
        "elektrik muhendisligi",
        "eem",
        "eem bolumu",
    ),
    "endustri_muhendisligi": (
        "endustri muhendisligi",
        "endustri muh",
        "endustri bolumu",
        "endustri",
        "emb",
    ),
}

TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "summer_school": ("yaz okulu", "yazokulu"),
    "course_schedule": ("ders programi", "ders programlari", "haftalik ders programi"),
    "midterm_exam": ("vize", "ara sinav", "ara sinav tarih", "arasınav"),
    "final_exam": ("final", "final sinav", "yariyil sonu sinav", "donem sonu sinav"),
    "makeup_exam": ("butunleme", "but", "butler", "büt", "bütünleme"),
    "internship": ("staj", "yaz staji", "zorunlu staj"),
    "project_exhibition": ("bitirme projesi", "bitirme projeleri", "proje sergisi", "bitirme sergisi"),
    "excuse_exam": ("mazeret sinavi", "mazeret sinav", "make up exam"),
}

LATEST_ANNOUNCEMENT_RE = re.compile(
    r"\b(son|en\s+son|guncel|güncel|yeni)\s+(?:\w+\s+){0,4}duyuru\w*|"
    r"\bduyuru\w*\s+(?:neler|nelerdir|listele\w*|goster\w*|göster\w*)\b",
    re.IGNORECASE,
)

PUBLICATION_SIGNAL_RE = re.compile(
    r"\b(duyuru\w*|aciklandi\s*mi|acildi\s*mi|yayinlandi\s*mi|ilan\s+edildi\s*mi|"
    r"takvimi|son\s+duyuru\w*)\b",
    re.IGNORECASE,
)

ANNOUNCEMENT_SIGNAL_RE = re.compile(
    r"\b(duyuru\w*|aciklandi\s*mi|acildi\s*mi|yayinlandi\s*mi|ilan\s+edildi\s*mi|"
    r"programi|programlari|takvimi|listesi|guncel|revize|son\s+duyuru\w*|var\s+mi|var\s+mı)\b",
    re.IGNORECASE,
)

PROCESS_OR_FORM_BLOCK_RE = re.compile(
    r"\b("
    r"is\s+akis\w*|iş\s+akış\w*|surec\w*|süreç\w*|"
    r"nasil\s+(?:hazirlan\w*|yapil\w*|isler\w*)|nasıl\s+(?:hazırlan\w*|yapıl\w*|işler\w*)|"
    r"form\w*|dilekce\w*|dilekçe\w*|itiraz\w*|basvuru\s+surec\w*|başvuru\s+süreç\w*"
    r")\b",
    re.IGNORECASE,
)

CATALOG_OR_INVENTORY_BLOCK_RE = re.compile(
    r"\b("
    r"aday\s+ogrenci|aday\s+öğrenci|ogrenim\s+sayfa\w*|öğrenim\s+sayfa\w*|"
    r"ogretim\s+plani|öğretim\s+planı|hangi\s+fakulte\w*|hangi\s+fakülte\w*|"
    r"kontenjan\w*|programi\s+var\s+mi|programı\s+var\s+mı|program\s+var\s+mi"
    r")\b",
    re.IGNORECASE,
)

GENERAL_CALENDAR_ONLY_RE = re.compile(
    r"^\s*(vize|final|but|büt|butunleme|bütünleme|ara\s+sınav|ara\s+sinav)\s+"
    r"(ne\s+zaman|hangi\s+tarih|ne\s+vakit)\s*\??\s*$",
    re.IGNORECASE,
)

STOPWORDS: frozenset[str] = frozenset({
    "ne", "nedir", "neler", "hangi", "ne zaman", "mi", "mı", "mu", "mü",
    "acaba", "icin", "için", "ile", "ve", "veya", "bir", "bu", "su", "şu",
    "gibtu", "gibtu", "universite", "üniversite", "muhendisligi", "muhendislik",
})


@dataclass(frozen=True)
class DepartmentAnnouncementQuery:
    original_query: str
    normalized_query: str
    is_announcement_query: bool
    department_codes: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    has_announcement_signal: bool = False
    is_latest_query: bool = False
    calendar_fallback_preferred: bool = False


def normalize_department_announcement_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def infer_department_announcement_tags(text: str) -> list[str]:
    normalized = normalize_department_announcement_text(text)
    tags = []
    for tag, aliases in TOPIC_ALIASES.items():
        if any(_alias_matches(normalized, alias) for alias in aliases):
            tags.append(tag)
    return tags


def extract_department_announcement_request(query: str) -> DepartmentAnnouncementQuery:
    normalized = normalize_department_announcement_text(query)
    departments = _extract_departments(normalized)
    topics = infer_department_announcement_tags(query)
    has_signal = bool(ANNOUNCEMENT_SIGNAL_RE.search(normalized))
    has_publication_signal = bool(PUBLICATION_SIGNAL_RE.search(normalized))
    has_process_blocker = bool(PROCESS_OR_FORM_BLOCK_RE.search(query) or PROCESS_OR_FORM_BLOCK_RE.search(normalized))
    has_catalog_blocker = bool(
        CATALOG_OR_INVENTORY_BLOCK_RE.search(query) or CATALOG_OR_INVENTORY_BLOCK_RE.search(normalized)
    )
    is_latest = bool(LATEST_ANNOUNCEMENT_RE.search(query) or LATEST_ANNOUNCEMENT_RE.search(normalized))
    calendar_only = bool(GENERAL_CALENDAR_ONLY_RE.search(query)) or bool(GENERAL_CALENDAR_ONLY_RE.search(normalized))
    terms = _query_terms(normalized)

    is_announcement_query = False
    blocked_by_process = has_process_blocker and not has_publication_signal and not is_latest
    blocked_by_catalog = has_catalog_blocker and not has_publication_signal and not is_latest and not topics
    if not calendar_only and not blocked_by_process and not blocked_by_catalog:
        if departments and (topics or has_signal or is_latest):
            is_announcement_query = True
        elif has_signal and topics:
            is_announcement_query = True
        elif is_latest and departments:
            is_announcement_query = True
        elif departments and "duyuru" in normalized:
            is_announcement_query = True

    return DepartmentAnnouncementQuery(
        original_query=query,
        normalized_query=normalized,
        is_announcement_query=is_announcement_query,
        department_codes=departments,
        topic_tags=topics,
        query_terms=terms,
        has_announcement_signal=has_signal,
        is_latest_query=is_latest,
        calendar_fallback_preferred=calendar_only or not is_announcement_query,
    )


def _extract_departments(normalized_query: str) -> list[str]:
    matches: list[str] = []
    tokens = normalized_query.split()
    for code, aliases in DEPARTMENT_ALIASES.items():
        if any(_alias_matches(normalized_query, alias, tokens=tokens) for alias in aliases):
            matches.append(code)
    return matches


def _alias_matches(normalized_query: str, alias: str, tokens: list[str] | None = None) -> bool:
    normalized_alias = normalize_department_announcement_text(alias)
    if not normalized_alias:
        return False
    if normalized_alias in normalized_query:
        return True
    tokens = tokens or normalized_query.split()
    alias_tokens = normalized_alias.split()
    if len(alias_tokens) == 1:
        token = alias_tokens[0]
        return any(
            candidate.startswith(token)
            or token.startswith(candidate)
            or SequenceMatcher(None, candidate, token).ratio() >= 0.86
            for candidate in tokens
            if len(candidate) >= 3
        )
    window_size = len(alias_tokens)
    for index in range(0, max(len(tokens) - window_size + 1, 0)):
        window = " ".join(tokens[index:index + window_size])
        if SequenceMatcher(None, window, normalized_alias).ratio() >= 0.88:
            return True
    return False


def _query_terms(normalized_query: str) -> list[str]:
    terms = []
    for token in normalized_query.split():
        if len(token) < 3 or token in STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms[:12]
