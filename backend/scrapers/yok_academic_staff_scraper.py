"""
YÖK Akademik bölüm/program odaklı akademik kadro extractor'ı.

Bu modül GİBTÜ web sitesi, PBS, PDF, duyuru, haber, rapor, arşiv, yönetim
sayfaları veya YÖK Atlas'ı akademik kadro kaynağı olarak kullanmaz. Hedefler
YÖK Akademik "Üniversiteler > Tümü > GİBTÜ" akışındaki filtreli bölüm/program
sonuç sayfalarından üretilir; kişi ve profil detayları yine YÖK Akademik
DOM/profil sayfalarından alan bazlı parse edilir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

try:
    from haystack import Document
except ImportError:  # pragma: no cover
    @dataclass
    class Document:  # type: ignore[no-redef]
        content: str
        meta: dict[str, Any]
        id: str | None = None


logger = logging.getLogger(__name__)

YOK_AKADEMIK_BASE_URL = "https://akademik.yok.gov.tr"
YOK_AKADEMIK_HOME_URL = f"{YOK_AKADEMIK_BASE_URL}/AkademikArama/"
YOK_AKADEMIK_UNIVERSITY_LIST_URL = f"{YOK_AKADEMIK_BASE_URL}/AkademikArama/view/universityListview.jsp"
YOK_AKADEMIK_HOST = "akademik.yok.gov.tr"
UNIVERSITY_NAME = "Gaziantep İslam Bilim ve Teknoloji Üniversitesi"
UNIVERSITY_SOURCE_URL = YOK_AKADEMIK_HOME_URL
SCRAPER_NAME = "yok_academic_staff_scraper"
METADATA_VERSION = "yok_academic_staff.v3"

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_MIN_DELAY_SECONDS = 1.5
DEFAULT_MAX_DELAY_SECONDS = 3.0
DEFAULT_MAX_PAGES = 30

VERIFIED_STATUSES = {
    "verified_from_yok_academic",
    "verified_from_filtered_context",
    "verified_from_kadro_veri",
}
REVIEW_STATUSES = {
    "ambiguous_department_or_program",
    "ambiguous_department",
    "conflict_department_or_program",
    "unmatched_program",
    "conflict_institution",
    "not_resolved",
    "missing_kadro_veri",
}
ALLOWED_SOURCE_KINDS = {
    "yok_academic_university_list",
    "yok_academic_university_home",
    "yok_academic_filtered_result",
    "yok_academic_university_staff",
    "yok_academic_profile",
}

TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"prof\.?\s*dr\.?|profesör|profesor", "Prof. Dr."),
    (r"doç\.?\s*dr\.?|doc\.?\s*dr\.?|doçent|docent", "Doç. Dr."),
    (r"dr\.?\s*öğr\.?\s*üyesi|dr\.?\s*ogr\.?\s*uyesi|doktor\s+öğretim\s+üyesi", "Dr. Öğr. Üyesi"),
    (r"öğr\.?\s*gör\.?\s*dr\.?|ogr\.?\s*gor\.?\s*dr\.?", "Öğr. Gör. Dr."),
    (r"öğr\.?\s*gör\.?|ogr\.?\s*gor\.?|öğretim\s+görevlisi", "Öğr. Gör."),
    (r"arş\.?\s*gör\.?\s*dr\.?|araş\.?\s*gör\.?\s*dr\.?|ars\.?\s*gor\.?\s*dr\.?", "Arş. Gör. Dr."),
    (r"arş\.?\s*gör\.?|araş\.?\s*gör\.?|ars\.?\s*gor\.?|araştırma\s+görevlisi", "Arş. Gör."),
)

TITLE_RE = re.compile(
    r"(?P<title>" + "|".join(f"(?:{pattern})" for pattern, _ in TITLE_PATTERNS) + r")",
    re.IGNORECASE,
)

PROFILE_URL_HINTS = (
    "viewAuthor",
    "AkademisyenGorevOgrenimBilgileri",
    "authorId",
)


@dataclass(frozen=True)
class YokAcademicTarget:
    parent_unit_name: str
    unit_name: str
    unit_type: str = "department"
    filtered_result_url: str | None = None
    filtered_context: dict[str, Any] = field(default_factory=dict)
    expected_result_count: int | None = None
    aliases: tuple[str, ...] = ()
    parent_unit_type: str | None = None

    @property
    def faculty_key(self) -> str:
        return normalize_for_match(self.parent_unit_name)

    @property
    def faculty_name(self) -> str:
        """Eski çağıranlar için üst birim adını döndürür."""
        return self.parent_unit_name

    @property
    def unit_key(self) -> str:
        return normalize_for_match(self.unit_name)


def _target_from_allowlist_entry(entry: Any) -> YokAcademicTarget:
    unit_name = _display_unit_name(entry.program_name, entry.academic_unit, entry.level)
    return YokAcademicTarget(
        parent_unit_name=entry.academic_unit,
        unit_name=unit_name,
        unit_type=_unit_type_for_program(entry.program_name, entry.academic_unit),
        aliases=_program_aliases(entry.program_name, unit_name),
        parent_unit_type=_parent_unit_type(entry.academic_unit),
    )


def _default_targets() -> tuple[YokAcademicTarget, ...]:
    return (
        YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Bilgisayar Mühendisliği Bölümü",
            "department",
            aliases=("Bilgisayar Mühendisliği",),
            parent_unit_type="faculty",
        ),
        YokAcademicTarget(
            "Mühendislik ve Doğa Bilimleri Fakültesi",
            "Elektrik-Elektronik Mühendisliği Bölümü",
            "department",
            aliases=("Elektrik-Elektronik Mühendisliği", "Elektrik Elektronik Mühendisliği"),
            parent_unit_type="faculty",
        ),
        YokAcademicTarget(
            "Teknik Bilimler Meslek Yüksekokulu",
            "Bilgisayar Programcılığı Programı",
            "program",
            aliases=("Bilgisayar Programcılığı",),
            parent_unit_type="vocational_school",
        ),
    )


DEFAULT_TARGETS: tuple[YokAcademicTarget, ...] = _default_targets()

SMOKE_TARGET_PRIORITY_KEYS: tuple[str, ...] = (
    "bilgisayar muhendisligi bolumu",
    "elektrik elektronik muhendisligi bolumu",
    "bilgisayar programciligi programi",
    "endustri muhendisligi ingilizce bolumu",
    "endustri muhendisligi bolumu",
)


@dataclass
class YokPersonRecord:
    full_name: str
    normalized_name: str
    title: str | None
    yok_profile_url: str | None
    yok_researcher_id: str | None
    university_from_yok: str | None
    faculty_from_yok: str | None
    department_from_yok: str | None
    unit_text_from_yok: str | None
    source_url: str
    source_status: str
    confidence_status: str
    confidence_score: float
    needs_manual_review: bool
    last_checked_at: str
    matched_target_key: str | None = None
    listing_context: dict[str, Any] = field(default_factory=dict)
    kadro_veri_raw: str | None = None
    kadro_university: str | None = None
    kadro_parent_unit: str | None = None
    kadro_department: str | None = None
    kadro_subunit: str | None = None
    kadro_parse_status: str = "not_checked"
    match_evidence: list[str] = field(default_factory=list)
    exclusion_reason: str | None = None

    @property
    def person_key(self) -> str:
        if self.yok_profile_url:
            return f"yok:{self.yok_profile_url.strip().lower()}"
        if self.yok_researcher_id:
            return f"yok_id:{self.yok_researcher_id}"
        return f"name:{self.normalized_name}:{normalize_for_match(self.unit_text_from_yok)}"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "YokPersonRecord":
        return cls(**payload)


@dataclass
class YokSourceEvidence:
    evidence_key: str
    source_url: str
    source_kind: str
    content_hash: str
    fetched_at: str
    field_names: list[str]
    raw_excerpt: str


@dataclass
class YokRawSnapshot:
    snapshot_id: str
    source_url: str
    source_kind: str
    http_status: int | None
    content_hash: str
    fetched_at: str
    response_text: str
    parse_status: str
    extracted_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class YokUnitSnapshot:
    target: YokAcademicTarget
    source_urls: list[str]
    person_keys: list[str]
    missing_fields: list[str]
    validation_status: str
    last_checked_at: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class YokAcademicStaffScrapeReport:
    success: bool
    scrape_run_id: str
    started_at: str
    finished_at: str = ""
    dry_run: bool = True
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    targets: list[YokAcademicTarget] = field(default_factory=list)
    persons: list[YokPersonRecord] = field(default_factory=list)
    source_evidence: list[YokSourceEvidence] = field(default_factory=list)
    raw_snapshots: list[YokRawSnapshot] = field(default_factory=list)
    staff_snapshots: list[YokUnitSnapshot] = field(default_factory=list)
    answer_documents: list[Document] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    yokatlas_program_count: int = 0
    yok_academic_profile_count: int = 0
    pagination_pages_visited: int = 0
    duplicate_profile_count: int = 0
    target_metrics: list[dict[str, Any]] = field(default_factory=list)
    failed_urls: list[str] = field(default_factory=list)
    retry_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["answer_documents"] = [
            {"id": doc.id, "content": doc.content, "meta": doc.meta}
            for doc in self.answer_documents
        ]
        return data


class CheckpointStore:
    """YÖK Akademik ara sonuçları için basit JSON checkpoint deposu."""

    def __init__(self, checkpoint_dir: str | Path | None) -> None:
        self.root = Path(checkpoint_dir) if checkpoint_dir else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    def load_json(self, name: str, default: Any) -> Any:
        if not self.root:
            return default
        path = self.root / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def save_json(self, name: str, payload: Any) -> None:
        if not self.root:
            return
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_for_match(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_for_match(value)
    for pattern, canonical in TITLE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return canonical
    return " ".join(str(value).split())


def is_allowed_yok_academic_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    blocked_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == YOK_AKADEMIK_HOST
        and not path.endswith(blocked_extensions)
        and ("/akademikarama" in path or path in {"", "/"})
    )


def is_allowed_academic_source_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")):
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc.lower() == YOK_AKADEMIK_HOST
    )


def build_search_url(target: YokAcademicTarget) -> str:
    """Serbest arama akışı bu fazda bilinçli olarak kapalıdır."""
    raise RuntimeError(
        f"YÖK Akademik serbest arama kullanılmaz; hedef {target.unit_name} için Üniversiteler > GİBTÜ akışı kullanılmalıdır."
    )


def select_smoke_targets(limit: int | None = 3) -> tuple[YokAcademicTarget, ...]:
    """Smoke test için bölüm/program hedeflerini küçük ve temsilî sırayla seçer."""
    department_program_targets = [
        target for target in DEFAULT_TARGETS
        if target.unit_type in {"department", "program"}
    ]
    preferred: list[YokAcademicTarget] = []
    for key in SMOKE_TARGET_PRIORITY_KEYS:
        for target in department_program_targets:
            if target.unit_key == key and target not in preferred:
                preferred.append(target)
                break
    remaining = [target for target in department_program_targets if target not in preferred]
    selected = [*preferred, *remaining]
    if limit is None:
        return tuple(selected)
    if limit <= 0:
        raise ValueError("Smoke hedef limiti pozitif olmalıdır.")
    return tuple(selected[:limit])


def build_targets_from_yokatlas_programs(programs: list[dict[str, Any]]) -> tuple[YokAcademicTarget, ...]:
    """Eski çağıranlar için isim bazlı hedef üretir; kadro akışı bunu kullanmaz."""
    targets: list[YokAcademicTarget] = []
    seen: set[tuple[str, str]] = set()
    for item in programs:
        academic_unit = item.get("academic_unit") or {}
        program = item.get("program") or {}
        faculty_name = str(academic_unit.get("name") or "").strip()
        clean_name = str(program.get("program_name_clean") or program.get("program_name_raw") or "").strip()
        raw_name = str(program.get("program_name_raw") or clean_name).strip()
        display_name = raw_name or clean_name
        if not faculty_name or not display_name:
            continue

        unit_name = _display_unit_name(display_name, faculty_name, program.get("level"))
        key = (normalize_for_match(faculty_name), normalize_for_match(unit_name))
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            YokAcademicTarget(
                parent_unit_name=faculty_name,
                unit_name=unit_name,
                unit_type=_unit_type_for_program(clean_name, faculty_name),
                aliases=_program_aliases(raw_name, clean_name, unit_name),
                parent_unit_type=_parent_unit_type(faculty_name),
            )
        )
    return tuple(targets)


def build_scrape_quality_report(
    report: YokAcademicStaffScrapeReport,
    expected_target_count: int | None = None,
) -> dict[str, Any]:
    """Dry-run veya DB öncesi YÖK Akademik kalite özetini üretir."""
    target_count = expected_target_count
    if target_count is None:
        target_count = sum(1 for target in report.targets if target.unit_type in {"department", "program"})

    staff_snapshots = [
        snapshot for snapshot in report.staff_snapshots
        if snapshot.target.unit_type in {"department", "program"}
    ]
    faculty_snapshot_count = sum(
        1 for snapshot in report.staff_snapshots
        if snapshot.target.unit_type in {"faculty", "fakulte", "school", "vocational_school"}
    )
    verified_people = [person for person in report.persons if person.source_status in VERIFIED_STATUSES]
    not_resolved_people = [person for person in report.persons if person.source_status == "not_resolved"]
    ambiguous_people = [
        person for person in report.persons
        if person.source_status in {"ambiguous_department_or_program", "ambiguous_department", "unmatched_program"}
    ]
    conflict_people = [person for person in report.persons if person.source_status == "conflict_institution"]
    duplicate_suspicion = _duplicate_suspicion_count(report.persons)
    invalid_sources = [
        evidence.source_url for evidence in report.source_evidence
        if not is_allowed_academic_source_url(evidence.source_url)
        or evidence.source_kind not in ALLOWED_SOURCE_KINDS
    ]
    invalid_raw_snapshots = [
        snapshot.source_url for snapshot in report.raw_snapshots
        if not is_allowed_academic_source_url(snapshot.source_url)
    ]
    incomplete_snapshots = [
        snapshot for snapshot in staff_snapshots
        if not snapshot.last_checked_at or not snapshot.source_urls or snapshot.person_keys is None
    ]
    missing_snapshot_count = max(0, int(target_count) - len(staff_snapshots))
    snapshot_person_keys = {
        key for snapshot in staff_snapshots for key in snapshot.person_keys
    }

    checks = {
        "department_program_snapshots_complete": missing_snapshot_count == 0,
        "no_faculty_staff_snapshot": faculty_snapshot_count == 0,
        "sources_only_yok_academic": not invalid_sources and not invalid_raw_snapshots,
        "ambiguous_or_conflict_not_in_snapshots": not any(
            person.person_key in snapshot_person_keys
            for person in [*ambiguous_people, *conflict_people, *not_resolved_people]
        ),
        "no_duplicate_suspicion": duplicate_suspicion == 0,
        "snapshots_have_required_fields": not incomplete_snapshots,
    }

    return {
        "success": all(checks.values()) and report.success,
        "scrape_run_id": report.scrape_run_id,
        "toplam_hedef_bolum_program_sayisi": int(target_count),
        "snapshot_olusan_bolum_program_sayisi": len(staff_snapshots),
        "eksik_snapshot_sayisi": missing_snapshot_count,
        "toplam_kisi_sayisi": len(report.persons),
        "verified_yok_kisi_sayisi": len(verified_people),
        "not_resolved_kisi_sayisi": len(not_resolved_people),
        "ambiguous_department_sayisi": len(ambiguous_people),
        "ambiguous_department_or_program_sayisi": len(ambiguous_people),
        "conflict_institution_sayisi": len(conflict_people),
        "duplicate_suphesi": duplicate_suspicion,
        "duplicate_profile_link_tekrari": report.duplicate_profile_count,
        "fakulte_snapshot_var_mi": faculty_snapshot_count > 0,
        "yonetim_tablosuna_yazim_var_mi": False,
        "yokatlas_program_sayisi": 0,
        "yok_akademik_gibtu_profil_sayisi": report.yok_academic_profile_count,
        "pagination_sayfa_sayisi": report.pagination_pages_visited,
        "hedef_bazli_metrikler": report.target_metrics,
        "source_evidence_sayisi": len(report.source_evidence),
        "raw_snapshot_sayisi": len(report.raw_snapshots),
        "affiliation_sayisi": len(snapshot_person_keys),
        "basarisiz_url_listesi": report.failed_urls,
        "retry_url_listesi": report.retry_urls,
        "kontroller": checks,
        "errors": [*report.errors, *[key for key, passed in checks.items() if not passed]],
    }


def parse_yok_university_list(html: str, source_url: str = YOK_AKADEMIK_UNIVERSITY_LIST_URL) -> str | None:
    """YÖK Akademik üniversiteler listesinden GİBTÜ bağlantısını bulur."""
    soup = BeautifulSoup(html or "", "html.parser")
    expected = normalize_for_match(UNIVERSITY_NAME)
    for anchor in soup.find_all("a", href=True):
        text = normalize_for_match(anchor.get_text(" ", strip=True))
        if expected in text or "gaziantep islam bilim ve teknoloji" in text:
            url = _absolute_yok_url(anchor.get("href", ""), source_url)
            if is_allowed_yok_academic_url(url):
                return url
    return None


def parse_filtered_result_context(html: str, source_url: str) -> dict[str, Any]:
    """Filtreli YÖK Akademik sonuç sayfasının başlık/context bilgisini parse eder."""
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    alert_parts = [
        tag.get_text(" ", strip=True)
        for tag in root.select("div.alert.alert-info, .alert.alert-info")
        if tag.get_text(" ", strip=True)
    ]
    title_parts = [
        tag.get_text(" ", strip=True)
        for tag in root.find_all(["h1", "h2", "h3", "h4"], limit=8)
        if tag.get_text(" ", strip=True)
    ]
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(" ", strip=True):
        title_parts.append(title_tag.get_text(" ", strip=True))
    text = _single_line(" ".join(alert_parts if alert_parts else title_parts))
    context = _context_from_text(text, source_url)
    if not context.get("unit_name"):
        label_context = _context_from_label_lines(root, source_url)
        for key, value in label_context.items():
            if not context.get(key) and value:
                context[key] = value
    return context


def parse_yok_filtered_targets(html: str, source_url: str) -> tuple[YokAcademicTarget, ...]:
    """GİBTÜ YÖK Akademik sayfasındaki bölüm/program filtreli hedef linklerini bulur."""
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    targets: list[YokAcademicTarget] = []
    seen: set[tuple[str, str, str]] = set()

    page_context = parse_filtered_result_context(html, source_url)
    if _is_complete_gibtu_target_context(page_context):
        target = _target_from_context(page_context, source_url)
        if target:
            targets.append(target)
            seen.add((target.faculty_key, target.unit_key, target.filtered_result_url or source_url))

    for anchor in root.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        url = _absolute_yok_url(href, source_url)
        if not is_allowed_yok_academic_url(url) or _is_profile_url(url):
            continue
        if _is_result_or_keyword_anchor(anchor):
            continue
        anchor_text = _clean_anchor_text(anchor)
        if not anchor_text:
            continue
        unit_name = _extract_unit_name_from_text(anchor_text) or _clean_context_unit_name(anchor_text) or anchor_text
        if not _is_department_or_program_name(unit_name):
            continue
        context: dict[str, Any]
        if page_context.get("parent_unit_name") and _is_parent_unit_name(str(page_context.get("parent_unit_name"))):
            parent_unit_name = str(page_context.get("parent_unit_name") or "")
            university_name = str(page_context.get("university") or UNIVERSITY_NAME)
            context = {
                "university": university_name,
                "parent_unit_name": parent_unit_name,
                "unit_name": unit_name,
                "result_count": None,
                "raw_title": _single_line(" / ".join(part for part in (university_name, parent_unit_name, unit_name) if part)),
                "source_url": url,
            }
        else:
            context_node = _target_context_node(anchor)
            context_text = _single_line(context_node.get_text(" ", strip=True))
            context = _context_from_text(" / ".join(part for part in (context_text, unit_name) if part), url)
            if not context.get("unit_name"):
                context = _context_from_text(unit_name, url)
        if not context.get("parent_unit_name"):
            parent = _nearest_previous_unit_heading(anchor)
            if parent:
                context["parent_unit_name"] = parent
        if not context.get("university"):
            context["university"] = page_context.get("university")
        if not _is_complete_gibtu_target_context(context):
            continue
        target = _target_from_context(context, url)
        if not target:
            continue
        key = (target.faculty_key, target.unit_key, target.filtered_result_url or url)
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)

    return tuple(targets)


def parse_yok_upper_unit_links(html: str, source_url: str) -> tuple[dict[str, str], ...]:
    """GİBTÜ sayfasından fakülte/yüksekokul/MYO üst birim linklerini çıkarır."""
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in root.find_all("a", href=True):
        if _is_result_or_keyword_anchor(anchor):
            continue
        url = _absolute_yok_url(str(anchor.get("href") or ""), source_url)
        if not is_allowed_yok_academic_url(url) or _is_profile_url(url):
            continue
        anchor_text = _clean_anchor_text(anchor)
        parent_unit_name = _extract_parent_unit_from_text(anchor_text) or _clean_context_unit_name(anchor_text)
        if not parent_unit_name or not _is_parent_unit_name(parent_unit_name):
            continue
        key = (normalize_for_match(parent_unit_name), url)
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "parent_unit_name": parent_unit_name,
            "url": url,
            "parent_unit_type": _parent_unit_type(parent_unit_name),
        })
    return tuple(_prioritize_upper_unit_links(links))


def parse_yok_pagination_links(html: str, source_url: str) -> list[str]:
    """GİBTÜ YÖK Akademik liste sayfasındaki kontrollü pagination URL'lerini döndürür."""
    soup = BeautifulSoup(html or "", "html.parser")
    links: list[str] = []
    containers = soup.select("ul.pagination, .pagination")
    search_roots: list[Tag] = list(containers) if containers else [_main_content(soup)]
    for root in search_roots:
        for anchor in root.find_all("a", href=True):
            parent = anchor.find_parent("li")
            parent_classes = {normalize_for_match(item) for item in (parent.get("class") or [])} if parent else set()
            if parent_classes.intersection({"active", "disabled"}):
                continue
            href = str(anchor.get("href") or "")
            url = _absolute_yok_url(href, source_url)
            if not is_allowed_yok_academic_url(url):
                continue
            if _is_profile_url(url):
                continue
            text = normalize_for_match(" ".join([
                anchor.get_text(" ", strip=True),
                str(anchor.get("title") or ""),
                str(anchor.get("aria-label") or ""),
                href,
            ]))
            if (
                re.fullmatch(r"\d+", normalize_for_match(anchor.get_text(" ", strip=True)))
                or any(token in text for token in ("sonraki", "ileri", "next", "sayfa", "page", "paging"))
                or any(key in dict(parse_qsl(urlparse(url).query)) for key in ("page", "sayfa", "p", "start", "offset"))
            ):
                if url not in links:
                    links.append(url)
    return links

def parse_yok_university_staff_page(
    html: str,
    source_url: str,
    checked_at: str | None = None,
    target: YokAcademicTarget | None = None,
    filtered_context: dict[str, Any] | None = None,
) -> list[YokPersonRecord]:
    """YÖK Akademik GİBTÜ liste sayfasından gerçek profil bağlantılarını çıkarır."""
    checked_at = checked_at or utc_now_iso()
    filtered_context = filtered_context or (target.filtered_context if target else {})
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    records_by_key: dict[str, YokPersonRecord] = {}

    for anchor in root.find_all("a", href=True):
        anchor_text = _clean_anchor_text(anchor)
        if not anchor_text:
            continue
        profile_url = _absolute_yok_url(anchor.get("href", ""), source_url)
        if not _is_profile_url(profile_url):
            continue

        context_node = _profile_context_node(anchor)
        if context_node is None:
            continue
        if _unique_profile_url_count(context_node, source_url) > 1:
            continue
        context = _single_line(context_node.get_text(" ", strip=True))
        title, name = _extract_title_and_name(anchor_text)
        if not name or not _looks_like_person_name(name):
            continue
        context_title, _ = _extract_title_and_name(context)
        listing_path = _parse_slash_unit_path(context)

        record = YokPersonRecord(
            full_name=name,
            normalized_name=normalize_for_match(name),
            title=title or context_title,
            yok_profile_url=profile_url,
            yok_researcher_id=extract_yok_researcher_id(profile_url, context),
            university_from_yok=listing_path.get("university") or _text_after_label(context_node, ("üniversite", "universite", "university", "kurum")),
            faculty_from_yok=listing_path.get("parent_unit") or _text_after_label(context_node, ("fakülte", "fakulte", "faculty", "yüksekokul", "yuksekokul")),
            department_from_yok=listing_path.get("department") or _text_after_label(context_node, ("bölüm", "bolum", "department", "program", "anabilim", "ana bilim", "birim")),
            unit_text_from_yok=context,
            source_url=source_url,
            source_status="unmatched_program",
            confidence_status="unmatched_program",
            confidence_score=0.0,
            needs_manual_review=True,
            last_checked_at=checked_at,
            matched_target_key=target.unit_key if target and _is_complete_gibtu_target_context(filtered_context) else None,
            listing_context=dict(filtered_context),
            match_evidence=["filtered_result_page"] if target and _is_complete_gibtu_target_context(filtered_context) else [],
        )
        records_by_key[record.person_key] = record
    return list(records_by_key.values())


def parse_yok_profile_page(
    html: str,
    base_record: YokPersonRecord,
    target: YokAcademicTarget | None = None,
    source_url: str | None = None,
    checked_at: str | None = None,
) -> YokPersonRecord:
    """YÖK Akademik profil sayfasından kurum/birim detayını zenginleştirir."""
    checked_at = checked_at or utc_now_iso()
    source_url = source_url or base_record.yok_profile_url or base_record.source_url
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    text = root.get_text("\n", strip=True)
    flat_text = _single_line(text)
    kadro_veri = parse_kadro_veri_profile(html)

    title, name = _extract_profile_heading_title_and_name(root)
    record = YokPersonRecord(
        full_name=name or base_record.full_name,
        normalized_name=normalize_for_match(name or base_record.full_name),
        title=title or base_record.title,
        yok_profile_url=source_url if is_allowed_yok_academic_url(source_url) else base_record.yok_profile_url,
        yok_researcher_id=extract_yok_researcher_id(source_url, flat_text) or base_record.yok_researcher_id,
        university_from_yok=kadro_veri.get("university") or base_record.university_from_yok,
        faculty_from_yok=kadro_veri.get("parent_unit") or base_record.faculty_from_yok,
        department_from_yok=kadro_veri.get("department") or base_record.department_from_yok,
        unit_text_from_yok=flat_text,
        source_url=source_url,
        source_status=base_record.source_status,
        confidence_status=base_record.confidence_status,
        confidence_score=base_record.confidence_score,
        needs_manual_review=base_record.needs_manual_review,
        last_checked_at=checked_at,
        matched_target_key=base_record.matched_target_key,
        listing_context=dict(base_record.listing_context),
        kadro_veri_raw=kadro_veri.get("raw"),
        kadro_university=kadro_veri.get("university"),
        kadro_parent_unit=kadro_veri.get("parent_unit"),
        kadro_department=kadro_veri.get("department"),
        kadro_subunit=kadro_veri.get("subunit"),
        kadro_parse_status=str(kadro_veri.get("parse_status") or "not_found"),
        match_evidence=list(base_record.match_evidence),
        exclusion_reason=base_record.exclusion_reason,
    )
    if target:
        record = classify_yok_record(record, target)
    return record


def classify_yok_record(record: YokPersonRecord, target: YokAcademicTarget) -> YokPersonRecord:
    """Geriye dönük tek hedef sınıflandırması."""
    classified, matched_target = classify_yok_record_against_targets(record, (target,))
    classified.matched_target_key = matched_target.unit_key if matched_target else None
    return classified


def classify_yok_record_against_targets(
    record: YokPersonRecord,
    targets: tuple[YokAcademicTarget, ...] | list[YokAcademicTarget],
) -> tuple[YokPersonRecord, YokAcademicTarget | None]:
    """Kişiyi YÖK Akademik filtered context ve Kadro Veri kanıtıyla eşleştirir."""
    university_text = normalize_for_match(record.university_from_yok)
    kadro_university_text = normalize_for_match(record.kadro_university)
    faculty_text = normalize_for_match(record.kadro_parent_unit or record.faculty_from_yok)
    department_text = normalize_for_match(record.kadro_department or record.department_from_yok)
    subunit_text = normalize_for_match(record.kadro_subunit)

    university_ok = any(
        alias in " ".join(part for part in (kadro_university_text, university_text) if part)
        for alias in ("gaziantep islam bilim ve teknoloji universitesi", "gibtu")
    )
    has_institution_signal = bool(kadro_university_text or university_text)

    if not record.yok_profile_url:
        return _with_status(record, "not_resolved", 0.0, None), None
    if has_institution_signal and not university_ok:
        return _with_status(record, "conflict_institution", 0.0, None), None

    best_target: YokAcademicTarget | None = None
    best_score = 0.0
    best_evidence: list[str] = []
    matching_targets: list[tuple[float, YokAcademicTarget, list[str]]] = []
    for target in targets:
        if target.unit_type not in {"department", "program"}:
            continue
        evidence: list[str] = []
        filtered_ok = (
            record.matched_target_key == target.unit_key
            and _is_complete_gibtu_target_context(record.listing_context)
            and _target_context_matches(record.listing_context, target)
        )
        parent_ok = bool(target.faculty_key and target.faculty_key in faculty_text) if faculty_text else False
        kadro_ok = (
            record.kadro_parse_status == "parsed"
            and any(alias in department_text or alias in subunit_text for alias in _target_aliases(target))
        )
        structured_ok = any(alias in normalize_for_match(record.department_from_yok) for alias in _target_aliases(target))

        if filtered_ok:
            evidence.append("filtered_result_page")
        if kadro_ok:
            evidence.append("kadro_veri")
        if structured_ok and not kadro_ok and not filtered_ok:
            evidence.append("structured_unit")

        if not evidence:
            continue
        if kadro_ok and parent_ok:
            score = 0.99
        elif filtered_ok and kadro_ok:
            score = 0.98
        elif filtered_ok:
            score = 0.94
        elif kadro_ok:
            score = 0.91
        else:
            score = 0.84
        matching_targets.append((score, target, evidence))
        if score > best_score:
            best_score = score
            best_target = target
            best_evidence = evidence

    if matching_targets:
        top_matches = [item for item in matching_targets if item[0] == best_score]
        if len({item[1].unit_key for item in top_matches}) > 1:
            return _with_status(record, "ambiguous_department_or_program", 0.55, None), None

    if best_target:
        if "kadro_veri" in best_evidence:
            status = "verified_from_kadro_veri"
        elif "filtered_result_page" in best_evidence:
            status = "verified_from_filtered_context"
        else:
            classified = _with_status(record, "missing_kadro_veri", 0.45, best_target)
            classified.match_evidence = list(dict.fromkeys([*record.match_evidence, *best_evidence]))
            return classified, best_target
        classified = _with_status(record, status, best_score, best_target)
        classified.match_evidence = list(dict.fromkeys([*record.match_evidence, *best_evidence]))
        return classified, best_target

    if university_ok:
        if record.kadro_parse_status == "not_found" and record.matched_target_key:
            return _with_status(record, "missing_kadro_veri", 0.45, None), None
        return _with_status(record, "ambiguous_department_or_program", 0.45, None), None
    return _with_status(record, "unmatched_program", 0.35, None), None


class YokAcademicStaffScraper:
    """YÖK Akademik üniversite sayfasından bölüm/program kadrosu çıkarır."""

    def __init__(
        self,
        targets: tuple[YokAcademicTarget, ...] | None = None,
        session: requests.Session | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_seconds: float = DEFAULT_MIN_DELAY_SECONDS,
        max_rate_limit_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        max_pages: int = DEFAULT_MAX_PAGES,
        profile_limit: int | None = None,
        checkpoint_dir: str | Path | None = None,
        resume: bool = True,
        use_yokatlas_inventory: bool | None = None,
        yokatlas_limit: int | None = None,
        target_limit: int | None = None,
    ) -> None:
        self._explicit_targets = targets
        self.targets = targets or ()
        self.use_yokatlas_inventory = False
        self.yokatlas_limit = None
        self.target_limit = target_limit if target_limit is not None else yokatlas_limit
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 UniChatYokAcademicStaff/2.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.6,en;q=0.5",
        })
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.max_rate_limit_seconds = max(self.rate_limit_seconds, max_rate_limit_seconds)
        self.max_pages = max_pages
        self.profile_limit = profile_limit
        self.checkpoints = CheckpointStore(checkpoint_dir)
        self.resume = resume
        self._last_request_at = 0.0

    def scrape(
        self,
        dry_run: bool = True,
        write_db: bool = False,
        report_json: str | Path | None = None,
    ) -> YokAcademicStaffScrapeReport:
        started_at = utc_now_iso()
        scrape_run_id = f"{SCRAPER_NAME}:{_sha256_text(started_at)[:16]}"
        report = YokAcademicStaffScrapeReport(
            success=True,
            scrape_run_id=scrape_run_id,
            started_at=started_at,
            dry_run=dry_run,
        )

        university_url = self._resolve_yok_academic_university_url(report)
        if not university_url:
            report.errors.append("YÖK Akademik Üniversiteler listesinde GİBTÜ bağlantısı bulunamadı.")
            return self._finish_report(report, report_json, write_db, dry_run)

        targets = self._resolve_targets(report, university_url)
        self.targets = targets
        report.targets = list(targets)
        extraction_targets = [target for target in targets if target.unit_type in {"department", "program"}]
        if not extraction_targets:
            report.errors.append("YÖK Akademik GİBTÜ sayfasında bölüm/program filtered hedefi bulunamadı.")
            return self._finish_report(report, report_json, write_db, dry_run)

        all_listing_records: list[YokPersonRecord] = []
        profile_urls_seen: set[str] = set()
        profile_cache = self.checkpoints.load_json("yok_academic_profile_details.json", {}) if self.resume else {}

        records_by_key: dict[str, YokPersonRecord] = {}
        verified_keys_by_target: dict[str, list[str]] = {target.unit_key: [] for target in extraction_targets}
        for target in extraction_targets:
            target_records, metric = self._crawl_filtered_target(report, target, university_url)
            all_listing_records.extend(target_records)
            detailed_records: list[YokPersonRecord] = []
            for base_record in target_records:
                if self.profile_limit is not None and len(profile_urls_seen) >= self.profile_limit:
                    break
                if base_record.yok_profile_url:
                    profile_urls_seen.add(base_record.yok_profile_url)
                detailed_records.append(self._profile_detail_record(base_record, report, profile_cache))

            snapshot_person_keys: list[str] = []
            excluded: list[dict[str, Any]] = []
            for record in detailed_records:
                classified, matched_target = classify_yok_record_against_targets(record, (target,))
                records_by_key[classified.person_key] = self._prefer_record(records_by_key.get(classified.person_key), classified)
                if matched_target and classified.source_status in VERIFIED_STATUSES:
                    verified_keys_by_target[target.unit_key].append(classified.person_key)
                    snapshot_person_keys.append(classified.person_key)
                else:
                    classified.exclusion_reason = classified.source_status
                    excluded.append({
                        "full_name": classified.full_name,
                        "profile_url": classified.yok_profile_url,
                        "reason": classified.source_status,
                    })
                    report.validation_results.append({
                        "severity": "warning",
                        "code": classified.source_status,
                        "message": f"{classified.full_name} kaydı kesin bölüm/program kadrosuna eklenmedi.",
                        "source_url": classified.source_url,
                        "target": target.unit_name,
                    })

            person_keys = sorted(set(snapshot_person_keys))
            source_urls = sorted(set(
                url for url in [
                    target.filtered_result_url,
                    *[person.yok_profile_url or person.source_url for person in detailed_records if person.person_key in person_keys],
                ]
                if url
            ))
            metric.update({
                "snapshot_person_count": len(person_keys),
                "excluded_person_count": len(excluded),
                "excluded_people": excluded,
                "duplicate_count": max(0, metric.get("parsed_person_count", 0) - len({record.person_key for record in target_records})),
                "source_url": target.filtered_result_url,
                "last_checked_at": utc_now_iso(),
            })
            report.target_metrics.append(metric)
            report.staff_snapshots.append(
                self._unit_snapshot(
                    target=target,
                    person_keys=person_keys,
                    source_urls=source_urls or [target.filtered_result_url or university_url],
                    validation_status="valid" if person_keys else "empty_source",
                    checked_at=str(metric["last_checked_at"]),
                    raw_data={
                        "filtered_context": target.filtered_context,
                        "expected_result_count": metric.get("expected_result_count"),
                        "parsed_person_count": metric.get("parsed_person_count", 0),
                        "snapshot_person_count": len(person_keys),
                        "excluded_person_count": len(excluded),
                        "excluded_people": excluded,
                        "pagination_page_count": metric.get("pagination_page_count", 0),
                    },
                )
            )
        self.checkpoints.save_json("yok_academic_profile_details.json", profile_cache)

        report.persons = list(records_by_key.values())
        report.yok_academic_profile_count = len({record.yok_profile_url for record in all_listing_records if record.yok_profile_url})

        report.answer_documents = []
        return self._finish_report(report, report_json, write_db, dry_run)

    def write_report_to_database(self, report: YokAcademicStaffScrapeReport) -> dict[str, int]:
        from app.repositories.academic_repository import AcademicRepository

        repo = AcademicRepository()
        repo.ensure_schema()
        university_id = repo.upsert_university(
            source_url=UNIVERSITY_SOURCE_URL,
            last_checked_at=report.finished_at,
        )
        repo.upsert_scrape_run({
            "scrape_run_id": report.scrape_run_id,
            "scraper_name": report.scraper_name,
            "metadata_version": report.metadata_version,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "status": "success" if report.success else "partial",
            "validation_status": "valid" if report.success else "needs_review",
            "target_unit_count": len([target for target in report.targets if target.unit_type in {"department", "program"}]),
            "source_count": len(report.source_evidence),
            "person_count": len(report.persons),
            "affiliation_count": sum(1 for person in report.persons if person.source_status in VERIFIED_STATUSES),
            "management_role_count": 0,
            "candidate_count": sum(1 for person in report.persons if person.needs_manual_review),
            "config": {
                "sources": ["yok_akademik"],
                "yok_academic_flow": "universiteler_tumu_gibtu_filtered_department_program",
                "faculty_level_snapshots": False,
                "weekly_schedule": False,
                "export_primary_method": False,
            },
            "summary": {
                "errors": report.errors,
                "validation_results": report.validation_results,
                "pagination_pages_visited": report.pagination_pages_visited,
                "duplicate_profile_count": report.duplicate_profile_count,
                "yokatlas_program_count": 0,
                "yok_academic_profile_count": report.yok_academic_profile_count,
                "target_metrics": report.target_metrics,
            },
        })

        parent_unit_ids_by_key: dict[str, str] = {}
        target_unit_ids_by_key: dict[tuple[str, str], str] = {}
        counts = {
            "persons": 0,
            "affiliations": 0,
            "external_profiles": 0,
            "evidence": 0,
            "raw_snapshots": 0,
            "staff_snapshots": 0,
            "program_metadata": 0,
        }

        for target in report.targets:
            if target.faculty_key not in parent_unit_ids_by_key:
                parent_unit_ids_by_key[target.faculty_key] = repo.upsert_unit({
                    "unit_name": target.parent_unit_name,
                    "unit_name_normalized": target.faculty_key,
                    "unit_type": target.parent_unit_type or _parent_unit_type(target.parent_unit_name),
                    "source_url": target.filtered_result_url or UNIVERSITY_SOURCE_URL,
                    "last_checked_at": report.finished_at,
                }, university_id)
            if target.unit_type in {"department", "program"}:
                target_db_key = (target.faculty_key, target.unit_key)
                target_unit_ids_by_key[target_db_key] = repo.upsert_unit({
                    "unit_name": target.unit_name,
                    "unit_name_normalized": target.unit_key,
                    "unit_type": target.unit_type,
                    "source_url": target.filtered_result_url or UNIVERSITY_SOURCE_URL,
                    "last_checked_at": report.finished_at,
                }, university_id, parent_unit_id=parent_unit_ids_by_key[target.faculty_key])

        person_ids_by_key: dict[str, str] = {}
        for person in report.persons:
            person_id = repo.upsert_yok_person({
                "full_name": person.full_name,
                "normalized_name": person.normalized_name,
                "title": person.title,
                "source_status": person.source_status,
                "needs_manual_review": person.needs_manual_review,
                "yok_profile_url": person.yok_profile_url,
                "yok_researcher_id": person.yok_researcher_id,
            })
            person_ids_by_key[person.person_key] = person_id
            counts["persons"] += 1
            repo.upsert_external_profile({
                "person_id": person_id,
                "profile_type": "yok_akademik",
                "profile_url": person.yok_profile_url,
                "external_id": person.yok_researcher_id,
                "match_status": person.source_status if person.yok_profile_url else "not_resolved",
                "confidence_score": person.confidence_score if person.yok_profile_url else None,
                "source_url": person.source_url,
                "raw_data": {
                    "university_from_yok": person.university_from_yok,
                    "faculty_from_yok": person.faculty_from_yok,
                    "department_from_yok": person.department_from_yok,
                    "listing_context": person.listing_context,
                    "kadro_veri_raw": person.kadro_veri_raw,
                    "kadro_university": person.kadro_university,
                    "kadro_parent_unit": person.kadro_parent_unit,
                    "kadro_department": person.kadro_department,
                    "kadro_subunit": person.kadro_subunit,
                    "kadro_parse_status": person.kadro_parse_status,
                    "matched_target_key": person.matched_target_key,
                    "match_evidence": person.match_evidence,
                    "exclusion_reason": person.exclusion_reason,
                },
                "last_checked_at": person.last_checked_at,
            })
            counts["external_profiles"] += 1

        evidence_ids_by_key: dict[str, str] = {}
        for evidence in report.source_evidence:
            evidence_ids_by_key[evidence.evidence_key] = repo.insert_evidence({
                "scrape_run_id": report.scrape_run_id,
                "source_url": evidence.source_url,
                "source_type": _source_type_for_url(evidence.source_url),
                "source_kind": evidence.source_kind,
                "content_hash": evidence.content_hash,
                "fetched_at": evidence.fetched_at,
                "field_names": evidence.field_names,
                "raw_excerpt": evidence.raw_excerpt,
                "is_accessible": True,
            })
            counts["evidence"] += 1

        people_by_key = {person.person_key: person for person in report.persons}
        target_unit_ids = [
            target_unit_ids_by_key[(snapshot.target.faculty_key, snapshot.target.unit_key)]
            for snapshot in report.staff_snapshots
            if snapshot.target.unit_type in {"department", "program"}
            and (snapshot.target.faculty_key, snapshot.target.unit_key) in target_unit_ids_by_key
        ]
        counts["deactivated_affiliations"] = repo.deactivate_yok_staff_affiliations_for_units(
            target_unit_ids,
            last_checked_at=report.finished_at,
        )
        for snapshot in report.staff_snapshots:
            if snapshot.target.unit_type not in {"department", "program"}:
                continue
            unit_id = target_unit_ids_by_key.get((snapshot.target.faculty_key, snapshot.target.unit_key))
            if not unit_id:
                continue
            for person_key in snapshot.person_keys:
                person = people_by_key.get(person_key)
                person_id = person_ids_by_key.get(person_key)
                if not person or not person_id or person.source_status not in VERIFIED_STATUSES:
                    continue
                repo.upsert_affiliation({
                    "person_id": person_id,
                    "unit_id": unit_id,
                    "affiliation_type": "academic_staff",
                    "title": person.title,
                    "is_active": True,
                    "source_status": person.source_status,
                    "confidence_status": person.confidence_status,
                    "confidence_score": person.confidence_score,
                    "needs_manual_review": False,
                    "source_url": person.yok_profile_url or person.source_url,
                    "evidence_ids": list(evidence_ids_by_key.values()),
                    "last_checked_at": person.last_checked_at,
                })
                counts["affiliations"] += 1

        for snapshot in report.raw_snapshots:
            unit_id = None
            repo.insert_raw_snapshot({
                "snapshot_id": snapshot.snapshot_id,
                "scrape_run_id": report.scrape_run_id,
                "source_url": snapshot.source_url,
                "source_kind": snapshot.source_kind,
                "http_status": snapshot.http_status,
                "content_hash": snapshot.content_hash,
                "fetched_at": snapshot.fetched_at,
                "response_text": snapshot.response_text,
                "parse_status": snapshot.parse_status,
                "extracted_fields": snapshot.extracted_fields,
            }, unit_id=unit_id)
            counts["raw_snapshots"] += 1

        for snapshot in report.staff_snapshots:
            if snapshot.target.unit_type not in {"department", "program"}:
                continue
            unit_id = target_unit_ids_by_key.get((snapshot.target.faculty_key, snapshot.target.unit_key))
            if not unit_id:
                continue
            person_ids = [person_ids_by_key[key] for key in snapshot.person_keys if key in person_ids_by_key]
            repo.upsert_unit_staff_snapshot({
                "scrape_run_id": report.scrape_run_id,
                "source_urls": snapshot.source_urls,
                "staff_count": len(person_ids),
                "person_ids": person_ids,
                "missing_fields": snapshot.missing_fields,
                "validation_status": snapshot.validation_status,
                "last_checked_at": snapshot.last_checked_at,
                "raw_data": snapshot.raw_data,
            }, unit_id)
            counts["staff_snapshots"] += 1

        if report.answer_documents:
            try:
                from app.ingestion.loader import ingest_documents
                from haystack.document_stores.types import DuplicatePolicy

                counts["answer_chunks"] = ingest_documents(report.answer_documents, policy=DuplicatePolicy.OVERWRITE)
            except Exception as exc:  # noqa: BLE001 - structured DB yazımı RAG chunk hatasına bağlı kalmamalı
                logger.warning("YÖK Akademik answer chunk ingestion atlandı: %s", exc)
                counts["answer_chunks"] = 0
                counts["answer_chunks_error"] = str(exc)

        return counts

    def _resolve_targets(self, report: YokAcademicStaffScrapeReport, university_url: str) -> tuple[YokAcademicTarget, ...]:
        if self._explicit_targets:
            targets = tuple(self._explicit_targets)
            return self._limit_targets(targets)

        cached = self.checkpoints.load_json("yok_academic_filtered_targets.json", None) if self.resume else None
        if cached and cached.get("targets"):
            targets = tuple(YokAcademicTarget(**item) for item in cached["targets"])
            return self._limit_targets(targets)

        html, status_code = self._fetch(university_url, referer=YOK_AKADEMIK_UNIVERSITY_LIST_URL)
        fetched_at = utc_now_iso()
        if html is None:
            report.failed_urls.append(university_url)
            report.raw_snapshots.append(self._snapshot(university_url, "yok_academic_university_home", "", status_code, fetched_at, "fetch_failed"))
            return ()

        report.raw_snapshots.append(
            self._snapshot(
                university_url,
                "yok_academic_university_home",
                html,
                status_code,
                fetched_at,
                "fetched",
                {"source_kind": "yok_academic_university_home"},
            )
        )
        report.source_evidence.append(
            self._evidence(
                university_url,
                "yok_academic_university_home",
                html,
                fetched_at,
                ["filtered_department_program_links"],
            )
        )
        targets: list[YokAcademicTarget] = []
        seen_targets: set[tuple[str, str, str]] = set()

        def add_validated_target(candidate: YokAcademicTarget, referer: str) -> None:
            if self.target_limit is not None and len(targets) >= self.target_limit:
                return
            target = self._validate_target_candidate(report, candidate, referer)
            if target is None:
                return
            key = (target.faculty_key, target.unit_key, target.filtered_result_url or "")
            if key in seen_targets:
                return
            seen_targets.add(key)
            targets.append(target)

        for candidate in parse_yok_filtered_targets(html, university_url):
            add_validated_target(candidate, university_url)

        for upper_link in parse_yok_upper_unit_links(html, university_url):
            if self.target_limit is not None and len(targets) >= self.target_limit:
                break
            upper_url = upper_link["url"]
            upper_html, upper_status_code = self._fetch(upper_url, referer=university_url)
            upper_fetched_at = utc_now_iso()
            if upper_html is None:
                report.failed_urls.append(upper_url)
                report.raw_snapshots.append(
                    self._snapshot(
                        upper_url,
                        "yok_academic_filtered_result",
                        "",
                        upper_status_code,
                        upper_fetched_at,
                        "fetch_failed",
                    )
                )
                continue
            upper_context = parse_filtered_result_context(upper_html, upper_url)
            if not _is_gibtu_text(str(upper_context.get("university") or "")):
                report.validation_results.append({
                    "severity": "warning",
                    "code": "invalid_upper_unit_context",
                    "message": "YÖK Akademik üst birim sayfasında GİBTÜ context'i doğrulanamadı; hedef keşfine dahil edilmedi.",
                    "source_url": upper_url,
                    "parsed_context": upper_context,
                })
                report.raw_snapshots.append(
                    self._snapshot(
                        upper_url,
                        "yok_academic_filtered_result",
                        upper_html,
                        upper_status_code,
                        upper_fetched_at,
                        "invalid_filtered_context",
                        {
                            "source_kind": "yok_academic_filtered_result",
                            "filtered_context": upper_context,
                            "parent_unit_name": upper_link.get("parent_unit_name"),
                        },
                    )
                )
                continue
            report.raw_snapshots.append(
                self._snapshot(
                    upper_url,
                    "yok_academic_filtered_result",
                    upper_html,
                    upper_status_code,
                    upper_fetched_at,
                    "fetched",
                    {
                        "source_kind": "yok_academic_filtered_result",
                        "filtered_context": upper_context,
                        "parent_unit_name": upper_link.get("parent_unit_name"),
                        "target_discovery": True,
                    },
                )
            )
            report.source_evidence.append(
                self._evidence(
                    upper_url,
                    "yok_academic_filtered_result",
                    upper_html,
                    upper_fetched_at,
                    ["filtered_context", "department_program_links"],
                )
            )
            for target in parse_yok_filtered_targets(upper_html, upper_url):
                add_validated_target(target, upper_url)
            targets = _prioritize_targets(targets)

        targets = self._limit_targets(tuple(_prioritize_targets(targets)))
        self.checkpoints.save_json("yok_academic_filtered_targets.json", {
            "targets": [asdict(target) for target in targets],
            "fetched_at": fetched_at,
            "source_url": university_url,
        })
        return targets

    def _validate_target_candidate(
        self,
        report: YokAcademicStaffScrapeReport,
        candidate: YokAcademicTarget,
        referer: str,
    ) -> YokAcademicTarget | None:
        """Bölüm/program adayını canlı filtered context ile doğrulayıp target'a terfi ettirir."""
        candidate_url = candidate.filtered_result_url
        if not candidate_url:
            report.validation_results.append({
                "severity": "warning",
                "code": "rejected_target_candidate",
                "message": "YÖK Akademik aday linkinde filtered result URL bulunmadı; target üretilmedi.",
                "target": candidate.unit_name,
            })
            return None

        html, status_code = self._fetch(candidate_url, referer=referer)
        fetched_at = utc_now_iso()
        if html is None:
            report.failed_urls.append(candidate_url)
            report.raw_snapshots.append(
                self._snapshot(
                    candidate_url,
                    "yok_academic_filtered_result",
                    "",
                    status_code,
                    fetched_at,
                    "fetch_failed",
                    {
                        "source_kind": "yok_academic_filtered_result",
                        "target_discovery": True,
                        "candidate_unit": candidate.unit_name,
                    },
                )
            )
            return None

        page_context = parse_filtered_result_context(html, candidate_url)
        if not _is_complete_gibtu_target_context(page_context) or not _target_context_matches(page_context, candidate):
            report.validation_results.append({
                "severity": "info",
                "code": "rejected_target_candidate",
                "message": (
                    "YÖK Akademik bölüm/program adayı GİBTÜ + üst birim + bölüm/program "
                    "context doğrulamasından geçmedi; target üretilmedi."
                ),
                "source_url": candidate_url,
                "target": candidate.unit_name,
                "parsed_context": page_context,
            })
            report.raw_snapshots.append(
                self._snapshot(
                    candidate_url,
                    "yok_academic_filtered_result",
                    html,
                    status_code,
                    fetched_at,
                    "rejected_target_candidate",
                    {
                        "source_kind": "yok_academic_filtered_result",
                        "target_discovery": True,
                        "candidate_unit": candidate.unit_name,
                        "filtered_context": page_context,
                    },
                )
            )
            return None

        target = _target_from_context(page_context, candidate_url)
        if target is None:
            return None
        report.raw_snapshots.append(
            self._snapshot(
                candidate_url,
                "yok_academic_filtered_result",
                html,
                status_code,
                fetched_at,
                "validated_target_candidate",
                {
                    "source_kind": "yok_academic_filtered_result",
                    "target_discovery": True,
                    "filtered_context": page_context,
                },
            )
        )
        report.source_evidence.append(
            self._evidence(
                candidate_url,
                "yok_academic_filtered_result",
                html,
                fetched_at,
                ["filtered_context", "validated_target_candidate"],
            )
        )
        return target

    def _limit_targets(self, targets: tuple[YokAcademicTarget, ...]) -> tuple[YokAcademicTarget, ...]:
        if self.target_limit is None:
            return targets
        if self.target_limit <= 0:
            raise ValueError("Hedef limiti pozitif olmalıdır.")
        return targets[: self.target_limit]

    def _resolve_yok_academic_university_url(self, report: YokAcademicStaffScrapeReport) -> str | None:
        cached = self.checkpoints.load_json("yok_academic_university_url.json", None) if self.resume else None
        if cached and cached.get("url"):
            return str(cached["url"])

        html, status_code = self._fetch(YOK_AKADEMIK_UNIVERSITY_LIST_URL, referer=YOK_AKADEMIK_HOME_URL)
        fetched_at = utc_now_iso()
        if html is None:
            report.failed_urls.append(YOK_AKADEMIK_UNIVERSITY_LIST_URL)
            report.raw_snapshots.append(self._snapshot(YOK_AKADEMIK_UNIVERSITY_LIST_URL, "yok_academic_university_list", "", status_code, fetched_at, "fetch_failed"))
            return None
        report.raw_snapshots.append(self._snapshot(YOK_AKADEMIK_UNIVERSITY_LIST_URL, "yok_academic_university_list", html, status_code, fetched_at, "fetched"))
        report.source_evidence.append(self._evidence(YOK_AKADEMIK_UNIVERSITY_LIST_URL, "yok_academic_university_list", html, fetched_at, ["university_link"]))
        url = parse_yok_university_list(html, YOK_AKADEMIK_UNIVERSITY_LIST_URL)
        if url:
            self.checkpoints.save_json("yok_academic_university_url.json", {"url": url, "fetched_at": fetched_at})
        return url

    def _crawl_filtered_target(
        self,
        report: YokAcademicStaffScrapeReport,
        target: YokAcademicTarget,
        university_url: str,
    ) -> tuple[list[YokPersonRecord], dict[str, Any]]:
        start_url = target.filtered_result_url or university_url
        cache_name = f"filtered_records_{_sha256_text(start_url)[:16]}.json"
        cached = self.checkpoints.load_json(cache_name, None) if self.resume else None
        if cached and cached.get("records"):
            records = [YokPersonRecord.from_dict(item) for item in cached["records"]]
            metric = dict(cached.get("metric") or {})
            report.pagination_pages_visited += int(metric.get("pagination_page_count") or 0)
            report.duplicate_profile_count += int(metric.get("duplicate_count") or 0)
            fetched_at = cached.get("fetched_at") or utc_now_iso()
            report.source_evidence.append(
                self._evidence(
                    start_url,
                    "yok_academic_filtered_result",
                    json.dumps({"profile_count": len(records), "checkpoint": True}, ensure_ascii=False),
                    fetched_at,
                    ["profile_links", "checkpoint", "filtered_context"],
                )
            )
            return records, metric

        queue: list[tuple[str, str]] = [(start_url, university_url)]
        seen_pages: set[str] = set()
        seen_hashes: set[str] = set()
        records_by_profile: dict[str, YokPersonRecord] = {}
        duplicate_count = 0
        resolved_result_count = target.expected_result_count

        while queue and len(seen_pages) < self.max_pages:
            page_url, referer_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            html, status_code = self._fetch(page_url, referer=referer_url)
            fetched_at = utc_now_iso()
            if html is None:
                report.failed_urls.append(page_url)
                report.raw_snapshots.append(self._snapshot(page_url, "yok_academic_filtered_result", "", status_code, fetched_at, "fetch_failed"))
                continue

            content_hash = _sha256_text(html)
            if content_hash in seen_hashes:
                report.validation_results.append({
                    "severity": "warning",
                    "code": "repeated_pagination_page",
                    "message": "YÖK Akademik pagination tekrar eden içerik üretti; sayfa tekrar işlenmedi.",
                    "source_url": page_url,
                })
                continue
            seen_hashes.add(content_hash)
            page_context = parse_filtered_result_context(html, page_url)
            if not _is_complete_gibtu_target_context(page_context) or not _target_context_matches(page_context, target):
                message = (
                    "YÖK Akademik filtered target sayfasında GİBTÜ + üst birim + bölüm/program "
                    "context'i doğrulanamadı; sayfa kişi parse için kullanılmadı."
                )
                is_start_page = page_url == start_url and not records_by_profile
                if is_start_page:
                    report.errors.append(message)
                report.validation_results.append({
                    "severity": "critical" if is_start_page else "warning",
                    "code": "invalid_filtered_target_context" if is_start_page else "invalid_pagination_context",
                    "message": message,
                    "source_url": page_url,
                    "target": target.unit_name,
                    "parsed_context": page_context,
                })
                report.raw_snapshots.append(
                    self._snapshot(
                        page_url,
                        "yok_academic_filtered_result",
                        html,
                        status_code,
                        fetched_at,
                        "invalid_filtered_context",
                        {
                            "source_kind": "yok_academic_filtered_result",
                            "filtered_context": page_context,
                            "target_unit": target.unit_name,
                        },
                    )
                )
                if is_start_page:
                    break
                continue
            if page_context.get("unit_name"):
                target_context = {**target.filtered_context, **page_context}
            else:
                target_context = dict(target.filtered_context)
            if page_context.get("result_count") is not None and resolved_result_count is None:
                resolved_result_count = page_context.get("result_count")
            report.raw_snapshots.append(
                self._snapshot(
                    page_url,
                    "yok_academic_filtered_result",
                    html,
                    status_code,
                    fetched_at,
                    "fetched",
                    {
                        "source_kind": "yok_academic_filtered_result",
                        "filtered_context": target_context,
                        "target_unit": target.unit_name,
                    },
                )
            )
            report.source_evidence.append(self._evidence(page_url, "yok_academic_filtered_result", html, fetched_at, ["profile_links", "pagination", "filtered_context"]))

            page_profile_count = _unique_profile_url_count(root := _main_content(BeautifulSoup(html or "", "html.parser")), page_url)
            page_records = parse_yok_university_staff_page(html, page_url, fetched_at, target, target_context)
            if page_profile_count > len(page_records):
                report.validation_results.append({
                    "severity": "warning",
                    "code": "profile_card_parse_skipped",
                    "message": "Bazı profil linkleri temiz kişi kartı olarak izole edilemediği için parse edilmedi.",
                    "source_url": page_url,
                    "target": target.unit_name,
                    "profile_link_count": page_profile_count,
                    "parsed_record_count": len(page_records),
                })

            for record in page_records:
                key = record.yok_profile_url or record.person_key
                if key in records_by_profile:
                    duplicate_count += 1
                    records_by_profile[key] = self._prefer_record(records_by_profile[key], record)
                else:
                    records_by_profile[key] = record
                if self.profile_limit is not None and len(records_by_profile) >= self.profile_limit:
                    break

            if self.profile_limit is not None and len(records_by_profile) >= self.profile_limit:
                break

            if resolved_result_count is not None and len(records_by_profile) >= int(resolved_result_count):
                break

            for next_url in parse_yok_pagination_links(html, page_url):
                queued_urls = {queued_url for queued_url, _ in queue}
                if next_url not in seen_pages and next_url not in queued_urls:
                    queue.append((next_url, page_url))

        report.pagination_pages_visited += len(seen_pages)
        report.duplicate_profile_count += duplicate_count
        records = list(records_by_profile.values())
        metric = {
            "parent_unit_name": target.parent_unit_name,
            "unit_name": target.unit_name,
            "expected_result_count": resolved_result_count,
            "filtered_result_count": resolved_result_count,
            "parsed_person_count": len(records),
            "duplicate_count": duplicate_count,
            "pagination_page_count": len(seen_pages),
            "source_url": start_url,
        }
        self.checkpoints.save_json(cache_name, {
            "records": [asdict(record) for record in records],
            "metric": metric,
            "fetched_at": utc_now_iso(),
        })
        return records, metric

    def _profile_detail_record(
        self,
        base_record: YokPersonRecord,
        report: YokAcademicStaffScrapeReport,
        profile_cache: dict[str, Any],
    ) -> YokPersonRecord:
        profile_url = base_record.yok_profile_url
        if not profile_url:
            return base_record
        cache_key = _sha256_text(profile_url)
        if self.resume and cache_key in profile_cache:
            try:
                record = YokPersonRecord.from_dict(profile_cache[cache_key])
                report.source_evidence.append(
                    self._evidence(
                        profile_url,
                        "yok_academic_profile",
                        json.dumps(asdict(record), ensure_ascii=False),
                        record.last_checked_at,
                        ["profile", "institution", "unit", "checkpoint"],
                    )
                )
                return record
            except TypeError:
                pass

        html, status_code = self._fetch(profile_url, referer=base_record.source_url)
        fetched_at = utc_now_iso()
        if html is None:
            report.failed_urls.append(profile_url)
            report.raw_snapshots.append(self._snapshot(profile_url, "yok_academic_profile", "", status_code, fetched_at, "fetch_failed"))
            profile_cache[cache_key] = asdict(base_record)
            return base_record
        report.raw_snapshots.append(self._snapshot(profile_url, "yok_academic_profile", html, status_code, fetched_at, "fetched"))
        report.source_evidence.append(self._evidence(profile_url, "yok_academic_profile", html, fetched_at, ["profile", "institution", "unit", "title"]))
        record = parse_yok_profile_page(html, base_record, None, profile_url, fetched_at)
        profile_cache[cache_key] = asdict(record)
        return record

    def _finish_report(
        self,
        report: YokAcademicStaffScrapeReport,
        report_json: str | Path | None,
        write_db: bool,
        dry_run: bool,
    ) -> YokAcademicStaffScrapeReport:
        report.finished_at = utc_now_iso()
        report.success = not report.errors
        if report_json:
            path = Path(report_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        if write_db and not dry_run and report.success:
            self.write_report_to_database(report)
        return report

    @staticmethod
    def _prefer_record(current: YokPersonRecord | None, candidate: YokPersonRecord) -> YokPersonRecord:
        if current is None:
            return candidate
        if candidate.confidence_score > current.confidence_score:
            return candidate
        if candidate.yok_profile_url and not current.yok_profile_url:
            return candidate
        if candidate.department_from_yok and not current.department_from_yok:
            return candidate
        return current

    def _fetch(self, url: str, referer: str | None = None) -> tuple[str | None, int | None]:
        if not is_allowed_yok_academic_url(url):
            raise ValueError(f"YÖK Akademik kapsamı dışında URL reddedildi: {url}")

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout_seconds,
                    headers={"Referer": referer or YOK_AKADEMIK_HOME_URL},
                )
                self._last_request_at = time.time()
                status_code = int(getattr(response, "status_code", 200))
                if status_code in {403, 429}:
                    return None, status_code
                if status_code >= 500 or status_code in {408}:
                    raise requests.RequestException(f"Geçici HTTP hata: {status_code}")
                if 400 <= status_code < 500:
                    return None, status_code
                response.raise_for_status()
                if not response.encoding or response.encoding.upper() in {"ISO-8859-1", "ASCII"}:
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text, status_code
            except requests.RequestException as exc:
                logger.warning("YÖK Akademik kaynak alınamadı (%d/%d): %s - %s", attempt, self.max_retries, url, exc)
                if attempt < self.max_retries:
                    time.sleep(min(30.0, max(self.rate_limit_seconds, 1.0) * attempt))
        return None, None

    def _rate_limit(self) -> None:
        if not self._last_request_at:
            return
        elapsed = time.time() - self._last_request_at
        target_delay = random.uniform(self.rate_limit_seconds, self.max_rate_limit_seconds)
        if elapsed < target_delay:
            time.sleep(target_delay - elapsed)

    @staticmethod
    def _snapshot(
        source_url: str,
        source_kind: str,
        html: str,
        http_status: int | None,
        fetched_at: str,
        parse_status: str,
        extracted_fields: dict[str, Any] | None = None,
    ) -> YokRawSnapshot:
        content_hash = _sha256_text(html or f"{source_url}:{http_status}:{parse_status}")
        return YokRawSnapshot(
            snapshot_id=_sha256_text(f"{source_url}:{content_hash}")[:24],
            source_url=source_url,
            source_kind=source_kind,
            http_status=http_status,
            content_hash=content_hash,
            fetched_at=fetched_at,
            response_text=html,
            parse_status=parse_status,
            extracted_fields=extracted_fields or {"source_kind": source_kind},
        )

    @staticmethod
    def _evidence(source_url: str, source_kind: str, html: str, fetched_at: str, fields: list[str]) -> YokSourceEvidence:
        content_hash = _sha256_text(html)
        if html.lstrip().startswith("{") or html.lstrip().startswith("["):
            excerpt = _single_line(html)[:500]
        else:
            excerpt = _single_line(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))[:500]
        return YokSourceEvidence(
            evidence_key=f"{source_url}:{content_hash[:12]}",
            source_url=source_url,
            source_kind=source_kind,
            content_hash=content_hash,
            fetched_at=fetched_at,
            field_names=fields,
            raw_excerpt=excerpt,
        )

    @staticmethod
    def _unit_snapshot(
        target: YokAcademicTarget,
        person_keys: list[str],
        source_urls: list[str],
        validation_status: str,
        checked_at: str,
        raw_data: dict[str, Any] | None = None,
    ) -> YokUnitSnapshot:
        return YokUnitSnapshot(
            target=target,
            source_urls=source_urls,
            person_keys=person_keys,
            missing_fields=[] if person_keys else ["staff"],
            validation_status=validation_status,
            last_checked_at=checked_at,
            raw_data=raw_data or {
                "source_mix": ["yok_akademik"],
                "faculty_level_snapshot": False,
                "filtered_context": target.filtered_context,
                "expected_result_count": target.expected_result_count,
                "filtered_result_url": target.filtered_result_url,
            },
        )

    @staticmethod
    def _build_answer_documents(report: YokAcademicStaffScrapeReport) -> list[Document]:
        people_by_key = {person.person_key: person for person in report.persons}
        docs: list[Document] = []
        for snapshot in report.staff_snapshots:
            if snapshot.target.unit_type not in {"department", "program"}:
                continue
            people = [
                people_by_key[key]
                for key in snapshot.person_keys
                if key in people_by_key and people_by_key[key].source_status in VERIFIED_STATUSES
            ]
            if not people:
                continue
            lines = [
                f"## {snapshot.target.unit_name} akademik kadrosu",
                "Bu liste YÖK Akademik filtreli bölüm/program sonuç sayfası ve profil Kadro Veri alanı baz alınarak oluşturulmuştur.",
            ]
            for person in sorted(people, key=lambda item: item.full_name):
                lines.append(
                    f"- {person.title or ''} {person.full_name}".strip()
                    + f" | YÖK Akademik: {person.yok_profile_url or 'not_resolved'}"
                    + f" | YÖK birim: {person.department_from_yok or person.unit_text_from_yok or 'not_resolved'}"
                    + f" | Son kontrol: {person.last_checked_at}"
                )
            source_url = next((url for url in snapshot.source_urls if YOK_AKADEMIK_HOST in url), None) or snapshot.source_urls[0]
            source_id = f"yok_academic_staff/{snapshot.target.unit_key}"
            docs.append(
                Document(
                    id=_sha256_text(source_id),
                    content="\n".join(lines),
                    meta={
                        "metadata_version": METADATA_VERSION,
                        "category": "akademik_kadro",
                        "doc_kind": "personel",
                        "source_url": source_url,
                        "source_public_url": source_url,
                        "source_type": "web",
                        "source_id": source_id,
                        "last_updated": report.finished_at or utc_now_iso(),
                        "title": f"{snapshot.target.unit_name} — YÖK Akademik Kadro",
                        "department": snapshot.target.unit_name,
                        "faculty": snapshot.target.faculty_name,
                        "language": "tr",
                        "scraper_name": SCRAPER_NAME,
                    },
                )
            )
        return docs


def _duplicate_suspicion_count(persons: list[YokPersonRecord]) -> int:
    keys: dict[str, int] = {}
    for person in persons:
        key = person.yok_profile_url or person.yok_researcher_id or person.normalized_name
        keys[key] = keys.get(key, 0) + 1
    return sum(1 for count in keys.values() if count > 1)


def _sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", value).strip()


def _main_content(soup: BeautifulSoup) -> Tag:
    return soup.select_one("main") or soup.select_one("body") or soup


def _absolute_yok_url(href: str, base_url: str) -> str:
    url = urljoin(base_url, href)
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.netloc.lower() == YOK_AKADEMIK_HOST:
        return parsed._replace(scheme="https").geturl()
    return url


def _is_profile_url(url: str) -> bool:
    if not is_allowed_yok_academic_url(url):
        return False
    return any(hint.lower() in url.lower() for hint in PROFILE_URL_HINTS)


def _with_extra_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def extract_yok_researcher_id(url: str | None, text: str | None = None) -> str | None:
    haystack = " ".join(part for part in (url, text) if part)
    for pattern in (
        r"authorId=([A-Za-z0-9]+)",
        r"researcherId=([A-Za-z0-9]+)",
        r"YÖK\s*(?:Araştırmacı|Akademik)?\s*(?:ID|No)[:\s]*([A-Za-z0-9]+)",
        r"YOK\s*(?:Arastirmaci|Akademik)?\s*(?:ID|No)[:\s]*([A-Za-z0-9]+)",
    ):
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_title_and_name(text: str) -> tuple[str | None, str | None]:
    text = _single_line(text)
    title_match = TITLE_RE.search(text)
    title = normalize_title(title_match.group("title")) if title_match else None
    name_text = text[title_match.end():] if title_match else text
    name_text = re.split(
        r"\b(Gaziantep|İslam|Bilim|Teknoloji|Üniversite|Üniversitesi|Fakülte|Fakültesi|Bölüm|Bölümü|Anabilim|Ana Bilim|Program|Programı)\b",
        name_text,
        flags=re.IGNORECASE,
    )[0]
    name_text = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü'\- ]+", " ", name_text)
    words = [word.strip(" -") for word in name_text.split() if len(word.strip(" -")) > 1]
    if len(words) < 2:
        return title, None
    return title, " ".join(words[:4]).strip()


def _extract_profile_heading_title_and_name(root: Tag) -> tuple[str | None, str | None]:
    for node in root.find_all(["h1", "h2", "h3"], limit=8):
        text = _single_line(node.get_text(" ", strip=True))
        if not text or len(text) > 180:
            continue
        title, name = _extract_title_and_name(text)
        if name and _looks_like_person_name(name):
            return title, name
    return None, None


def _looks_like_person_name(value: str | None) -> bool:
    normalized = normalize_for_match(value)
    if not normalized:
        return False
    blocked_tokens = (
        "universite",
        "universitesi",
        "fakulte",
        "fakultesi",
        "bolum",
        "bolumu",
        "program",
        "programi",
        "anabilim",
        "ana bilim",
        "temel alan",
        "bilim alani",
        "gmail",
        "edu",
    )
    if any(token in normalized for token in blocked_tokens):
        return False
    words = normalized.split()
    return 2 <= len(words) <= 5 and all(len(word) > 1 for word in words)


def _clean_anchor_text(anchor: Tag) -> str:
    clone = BeautifulSoup(str(anchor), "html.parser")
    node = clone.find("a") or clone
    for hidden in node.select('[style*="visibility: hidden"], [hidden], .sr-only'):
        hidden.decompose()
    return _single_line(node.get_text(" ", strip=True))


def _profile_context_node(anchor: Tag) -> Tag | None:
    author_row = anchor.find_parent("tr", id=re.compile(r"^authorInfo_"))
    if author_row:
        return author_row
    for parent_name in ("li", "article", "section", "div"):
        parent = anchor.find_parent(parent_name)
        if (
            parent
            and len(parent.get_text(" ", strip=True)) < 2500
            and _has_result_card_signal(parent)
        ):
            return parent
    return None


def _has_result_card_signal(node: Tag) -> bool:
    classes = {normalize_for_match(item) for item in (node.get("class") or [])}
    if any(
        token in " ".join(classes)
        for token in ("result", "author", "person", "media", "card")
    ):
        return True
    return bool(node.find("a", href=re.compile(r"AkademisyenGorevOgrenimBilgileri|authorId", re.IGNORECASE)))


def _target_context_node(anchor: Tag) -> Tag:
    for parent_name in ("li", "article", "section", "div"):
        parent = anchor.find_parent(parent_name)
        if parent and parent.find_parent("tr") is None and len(parent.get_text(" ", strip=True)) < 1800:
            return parent
    return anchor


def _is_result_or_keyword_anchor(anchor: Tag) -> bool:
    classes = {normalize_for_match(item) for item in (anchor.get("class") or [])}
    if any(item in classes for item in {"anahtarkelime", "label", "labelsuccess"}):
        return True
    if anchor.find_parent("tr") is not None:
        return True
    text = normalize_for_match(anchor.get_text(" ", strip=True))
    return any(token in text for token in ("temel alan", "bilim alani", "anahtar kelime"))


def _unique_profile_url_count(root: Tag, source_url: str) -> int:
    urls: set[str] = set()
    for anchor in root.find_all("a", href=True):
        profile_url = _absolute_yok_url(anchor.get("href", ""), source_url)
        if _is_profile_url(profile_url):
            urls.add(profile_url)
    return len(urls)


def _text_after_label(root: Tag, labels: tuple[str, ...]) -> str | None:
    text = root.get_text("\n", strip=True)
    lines = [_single_line(line) for line in text.splitlines() if _single_line(line)]
    normalized_labels = tuple(normalize_for_match(label) for label in labels)
    for index, line in enumerate(lines):
        normalized = normalize_for_match(line)
        for label in normalized_labels:
            if label and label in normalized:
                for separator in (":", "：", "-"):
                    if separator in line:
                        value = line.split(separator, 1)[1].strip()
                        if value:
                            return value
                if index + 1 < len(lines):
                    next_line = lines[index + 1]
                    if normalize_for_match(next_line) not in normalized_labels:
                        return next_line
                return line
    return None


def parse_kadro_veri_profile(html: str) -> dict[str, Any]:
    """Profil HTML'inden yalnız label-aware Kadro Veri alanını parse eder."""
    soup = BeautifulSoup(html or "", "html.parser")
    root = _main_content(soup)
    lines = [_single_line(line) for line in root.get_text("\n", strip=True).splitlines() if _single_line(line)]
    raw = _extract_labeled_block(lines, "kadro veri")
    if not raw:
        return {
            "raw": None,
            "university": None,
            "parent_unit": None,
            "department": None,
            "subunit": None,
            "parse_status": "not_found",
        }
    parsed = _parse_slash_unit_path(raw)
    parsed["raw"] = raw
    parsed["parse_status"] = "parsed" if parsed.get("university") or parsed.get("department") else "unparsed"
    return parsed


def _extract_labeled_block(lines: list[str], label: str) -> str | None:
    label_norm = normalize_for_match(label)
    stop_labels = {
        "anahtar kelime",
        "temel alan",
        "bilim alan",
        "ogrenim bilgisi",
        "ogrenim bilgileri",
        "yayin",
        "yayinlar",
        "tez",
        "tezler",
        "akademik ilgi alanlari",
        "iletisim",
        "makale",
        "bildiri",
        "proje",
    }
    collected: list[str] = []
    collecting = False
    for line in lines:
        normalized = normalize_for_match(line)
        if not collecting and label_norm in normalized:
            collecting = True
            value = _value_after_label_text(line)
            if value:
                collected.append(value)
            continue
        if not collecting:
            continue
        if any(stop in normalized for stop in stop_labels):
            break
        if line:
            collected.append(line)
        if len(_parse_slash_unit_path(" ".join(collected)).get("subunit") or "") > 0:
            break
    raw = _single_line(" / ".join(collected) if len(collected) > 1 else " ".join(collected))
    return raw or None


def _value_after_label_text(line: str) -> str | None:
    for separator in (":", "：", "-"):
        if separator in line:
            value = line.split(separator, 1)[1].strip()
            if value:
                return value
    normalized = normalize_for_match(line)
    if normalized == "kadro veri":
        return None
    match = re.search(r"kadro\s*veri\s*(.*)$", line, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(" :-") or None
    return None


def _parse_slash_unit_path(raw: str) -> dict[str, str | None]:
    parts = [_single_line(part) for part in re.split(r"\s*/\s*", raw) if _single_line(part)]
    result = {
        "university": None,
        "parent_unit": None,
        "department": None,
        "subunit": None,
    }
    if not parts:
        return result
    university_index = next(
        (
            index for index, part in enumerate(parts)
            if "gaziantep islam bilim ve teknoloji" in normalize_for_match(part)
        ),
        0,
    )
    relevant = parts[university_index:]
    if relevant:
        result["university"] = _clean_university_name_from_segment(relevant[0])
    if len(relevant) > 1:
        result["parent_unit"] = _clean_context_unit_name(relevant[1])
    if len(relevant) > 2:
        result["department"] = _clean_context_unit_name(relevant[2])
    if len(relevant) > 3:
        result["subunit"] = _clean_context_unit_name(" / ".join(relevant[3:]))
    return result


def _clean_university_name_from_segment(value: str) -> str:
    match = re.search(
        r"(GAZİANTEP\s+İSLAM\s+BİLİM\s+VE\s+TEKNOLOJİ\s+ÜNİVERSİTESİ)",
        value or "",
        flags=re.IGNORECASE,
    )
    if match:
        return _single_line(match.group(1))
    return _single_line(value)


def _clean_context_unit_name(value: str | None) -> str | None:
    if not value:
        return None
    text = _single_line(value)
    text = re.split(
        r"\s+(?:için|icin)\s+arama\s+sonu[çc]lar[ıi]\b",
        text,
        flags=re.IGNORECASE,
    )[0]
    text = re.split(r"\bArama\s+Sonucu\b|\bSonuç\b|\bSonuc\b|\bToplam\b", text, flags=re.IGNORECASE)[0]
    text = re.sub(r"\(\s*\d+\s*(?:sonuç|sonuc|kayıt|kayit|kişi|kisi)?\s*\)\s*$", "", text, flags=re.IGNORECASE)
    return _single_line(text) or None


def _context_from_label_lines(root: Tag, source_url: str) -> dict[str, Any]:
    text = root.get_text("\n", strip=True)
    lines = [_single_line(line) for line in text.splitlines() if _single_line(line)]
    by_label: dict[str, str] = {}
    label_map = {
        "universite": ("üniversite", "universite", "university"),
        "parent_unit_name": ("fakülte", "fakulte", "yüksekokul", "yuksekokul", "meslek yüksekokulu", "meslek yuksekokulu", "birim"),
        "unit_name": ("bölüm", "bolum", "program", "anabilim", "ana bilim"),
        "result_count": ("arama sonucu", "sonuç", "sonuc", "toplam"),
    }
    for line in lines:
        normalized = normalize_for_match(line)
        for key, labels in label_map.items():
            if any(normalize_for_match(label) in normalized for label in labels):
                value = _value_after_generic_label(line)
                if value and key not in by_label:
                    by_label[key] = value
    return {
        "university": by_label.get("universite") or UNIVERSITY_NAME,
        "parent_unit_name": by_label.get("parent_unit_name"),
        "unit_name": by_label.get("unit_name"),
        "result_count": _parse_result_count(by_label.get("result_count") or text),
        "raw_title": _single_line(" ".join(lines[:8])),
        "source_url": source_url,
    }


def _context_from_text(text: str, source_url: str) -> dict[str, Any]:
    clean = _single_line(text)
    path = _parse_slash_unit_path(clean)
    if not _is_gibtu_text(path.get("university")):
        path = {"university": None, "parent_unit": None, "department": None, "subunit": None}
    parent = path.get("parent_unit")
    unit = path.get("department")
    if not unit:
        unit = _extract_unit_name_from_text(clean)
    if not parent:
        parent = _extract_parent_unit_from_text(clean)
    return {
        "university": path.get("university") or (UNIVERSITY_NAME if "gaziantep" in normalize_for_match(clean) else None),
        "parent_unit_name": parent,
        "unit_name": unit,
        "result_count": _parse_result_count(clean),
        "raw_title": clean[:500],
        "source_url": source_url,
    }


def _is_gibtu_text(value: str | None) -> bool:
    normalized = normalize_for_match(value)
    return "gaziantep islam bilim ve teknoloji universitesi" in normalized or "gibtu" in normalized


def _is_complete_gibtu_target_context(context: dict[str, Any] | None) -> bool:
    if not context:
        return False
    university = str(context.get("university") or "")
    parent = str(context.get("parent_unit_name") or "")
    unit = str(context.get("unit_name") or "")
    return (
        _is_gibtu_text(university)
        and bool(parent)
        and bool(unit)
        and _is_parent_unit_name(parent)
        and _is_department_or_program_name(unit)
    )


def _target_context_matches(context: dict[str, Any] | None, target: YokAcademicTarget) -> bool:
    if not _is_complete_gibtu_target_context(context):
        return False
    parent = normalize_for_match(str(context.get("parent_unit_name") or ""))
    unit = normalize_for_match(str(context.get("unit_name") or ""))
    return target.faculty_key in parent and any(alias in unit for alias in _target_aliases(target))


def _target_from_context(context: dict[str, Any], source_url: str) -> YokAcademicTarget | None:
    unit_name = _single_line(str(context.get("unit_name") or ""))
    parent_unit_name = _single_line(str(context.get("parent_unit_name") or ""))
    if not _is_complete_gibtu_target_context(context):
        return None
    if not unit_name or not _is_department_or_program_name(unit_name):
        return None
    unit_type = _unit_type_from_unit_name(unit_name, parent_unit_name)
    return YokAcademicTarget(
        parent_unit_name=parent_unit_name,
        unit_name=unit_name,
        unit_type=unit_type,
        filtered_result_url=source_url,
        filtered_context={
            "university": context.get("university") or UNIVERSITY_NAME,
            "parent_unit_name": parent_unit_name,
            "unit_name": unit_name,
            "result_count": context.get("result_count"),
            "raw_title": context.get("raw_title"),
        },
        expected_result_count=context.get("result_count"),
        aliases=_program_aliases(unit_name),
        parent_unit_type=_parent_unit_type(parent_unit_name),
    )


def _value_after_generic_label(line: str) -> str | None:
    for separator in (":", "："):
        if separator in line:
            value = line.split(separator, 1)[1].strip()
            if value:
                return value
    return None


def _parse_result_count(text: str | None) -> int | None:
    if not text:
        return None
    normalized = normalize_for_match(text)
    patterns = (
        r"(?:arama\s*)?sonuc(?:u)?\s*(?:sayisi)?\s*[:\-]?\s*(\d+)",
        r"toplam\s*(\d+)\s*(?:kayit|kisi|sonuc|akademisyen)",
        r"\((\d+)\s*(?:sonuc|kayit|kisi)?\)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _extract_unit_name_from_text(text: str) -> str | None:
    for segment in re.split(r"[/\n\r]+", text or ""):
        match = re.search(
            r"([A-ZÇĞİÖŞÜa-zçğıöşü0-9 ,.'()-]+?\s+(?:Bölümü|Bolumu|Programı|Programi))",
            segment,
            flags=re.IGNORECASE,
        )
        if match:
            return _single_line(match.group(1))
    return None


def _extract_parent_unit_from_text(text: str) -> str | None:
    for segment in re.split(r"[/\n\r]+", text or ""):
        match = re.search(
            r"([A-ZÇĞİÖŞÜa-zçğıöşü0-9 ,.'()-]+?\s+(?:Fakültesi|Fakultesi|Meslek Yüksekokulu|Meslek Yuksekokulu|Yüksekokulu|Yuksekokulu|Enstitüsü|Enstitusu))",
            segment,
            flags=re.IGNORECASE,
        )
        if match:
            return _single_line(match.group(1))
    return None


def _is_department_or_program_name(value: str) -> bool:
    normalized = normalize_for_match(value)
    return (
        bool(_extract_unit_name_from_text(value))
        or
        normalized.endswith("bolumu")
        or normalized.endswith("programi")
        or " bolumu " in f" {normalized} "
        or " programi " in f" {normalized} "
    )


def _is_parent_unit_name(value: str) -> bool:
    normalized = normalize_for_match(value)
    return (
        bool(_extract_parent_unit_from_text(value))
        or
        normalized.endswith("fakultesi")
        or normalized.endswith("yuksekokulu")
        or normalized.endswith("meslek yuksekokulu")
        or normalized.endswith("enstitusu")
        or " fakultesi " in f" {normalized} "
        or " yuksekokulu " in f" {normalized} "
        or " meslek yuksekokulu " in f" {normalized} "
        or " enstitusu " in f" {normalized} "
    )


def _unit_type_from_unit_name(unit_name: str, parent_unit_name: str) -> str:
    normalized = normalize_for_match(unit_name)
    parent = normalize_for_match(parent_unit_name)
    if normalized.endswith("programi") or "meslek yuksekokulu" in parent:
        return "program"
    return "department"


def _nearest_previous_unit_heading(anchor: Tag) -> str | None:
    for node in anchor.find_all_previous(["h1", "h2", "h3", "h4", "h5", "strong"], limit=12):
        text = _single_line(node.get_text(" ", strip=True))
        if _extract_parent_unit_from_text(text):
            return _extract_parent_unit_from_text(text)
    return None


def _extract_yok_affiliation_path(text: str) -> dict[str, str | None]:
    """Profildeki GİBTÜ/Fakülte/Bölüm slash yolunu alan metinlerinden ayırır."""
    if not text:
        return {"university": None, "faculty": None, "department": None}
    pattern = re.compile(
        r"(GAZİANTEP\s+İSLAM\s+BİLİM\s+VE\s+TEKNOLOJİ\s+ÜNİVERSİTESİ)\s*/\s*([^/]+?)\s*/\s*([^/]+?)\s*/",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return {"university": None, "faculty": None, "department": None}
    return {
        "university": _single_line(match.group(1)),
        "faculty": _single_line(match.group(2)),
        "department": _single_line(match.group(3)),
    }


def _target_aliases(target: YokAcademicTarget) -> tuple[str, ...]:
    aliases = {target.unit_name, *target.aliases}
    normalized_aliases = {normalize_for_match(alias) for alias in aliases}
    suffixes = (" bolumu", " programi", " anabilim dali", " ana bilim dali")
    for alias in list(normalized_aliases):
        for suffix in suffixes:
            if alias.endswith(suffix):
                normalized_aliases.add(alias[: -len(suffix)].strip())
    return tuple(alias for alias in normalized_aliases if alias)


def _prioritize_targets(targets: list[YokAcademicTarget] | tuple[YokAcademicTarget, ...]) -> list[YokAcademicTarget]:
    priority = {key: index for index, key in enumerate(SMOKE_TARGET_PRIORITY_KEYS)}
    return sorted(
        list(targets),
        key=lambda target: (
            priority.get(target.unit_key, len(priority) + 10),
            target.faculty_key,
            target.unit_key,
        ),
    )


def _prioritize_upper_unit_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    preferred = (
        "muhendislik ve doga bilimleri fakultesi",
        "teknik bilimler meslek yuksekokulu",
        "saglik hizmetleri meslek yuksekokulu",
    )
    priority = {key: index for index, key in enumerate(preferred)}
    return sorted(
        links,
        key=lambda link: (
            priority.get(normalize_for_match(link.get("parent_unit_name")), len(priority) + 10),
            normalize_for_match(link.get("parent_unit_name")),
        ),
    )


def _with_status(
    record: YokPersonRecord,
    status: str,
    score: float,
    target: YokAcademicTarget | None,
) -> YokPersonRecord:
    record.source_status = status
    record.confidence_status = status
    record.confidence_score = score
    record.needs_manual_review = status not in VERIFIED_STATUSES
    record.matched_target_key = target.unit_key if target else None
    return record


def _display_unit_name(program_name: str, faculty_name: str, level: str | None = None) -> str:
    clean = _single_line(program_name)
    normalized = normalize_for_match(clean)
    parent = normalize_for_match(faculty_name)
    if "muhendisligi" in normalized and not normalized.endswith("bolumu"):
        return f"{clean} Bölümü"
    if ("meslek yuksekokulu" in parent or level == "onlisans") and not normalized.endswith("programi"):
        return f"{clean} Programı"
    return clean


def _unit_type_for_program(program_name: str, faculty_name: str) -> str:
    normalized = normalize_for_match(program_name)
    parent = normalize_for_match(faculty_name)
    if "muhendisligi" in normalized and "fakultesi" in parent:
        return "department"
    return "program"


def _parent_unit_type(faculty_name: str) -> str:
    normalized = normalize_for_match(faculty_name)
    if "meslek yuksekokulu" in normalized:
        return "vocational_school"
    if "yuksekokulu" in normalized:
        return "school"
    return "faculty"


def _program_aliases(*names: str) -> tuple[str, ...]:
    aliases: set[str] = set()
    for name in names:
        if not name:
            continue
        single = _single_line(name)
        aliases.add(single)
        aliases.add(re.sub(r"\s*\([^)]*\)", "", single).strip())
        normalized = normalize_for_match(single)
        if normalized.endswith(" bolumu"):
            aliases.add(single.rsplit(" ", 1)[0])
        if normalized.endswith(" programi"):
            aliases.add(single.rsplit(" ", 1)[0])
    return tuple(alias for alias in aliases if alias)


def _source_type_for_url(url: str) -> str:
    return "yok_akademik"


def main() -> None:
    parser = argparse.ArgumentParser(description="YÖK Akademik Üniversiteler > GİBTÜ bölüm/program akademik kadro scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan çalıştır")
    parser.add_argument("--write-db", action="store_true", help="Structured DB yaz; canlı chatbot bu DB'den yanıtlar")
    parser.add_argument("--report-json", type=str, default=None, help="Rapor JSON dosyası")
    parser.add_argument("--limit-programs", type=int, default=None, help="Smoke test için YÖK Akademik bölüm/program hedef limiti")
    parser.add_argument("--limit-profiles", type=int, default=None, help="YÖK Akademik profil detayı limiti")
    parser.add_argument("--checkpoint-dir", type=str, default=None, help="Checkpoint klasörü")
    parser.add_argument("--rate-limit", type=float, default=DEFAULT_MIN_DELAY_SECONDS, help="Minimum istek bekleme süresi")
    args = parser.parse_args()

    scraper = YokAcademicStaffScraper(
        yokatlas_limit=args.limit_programs,
        profile_limit=args.limit_profiles,
        checkpoint_dir=args.checkpoint_dir,
        rate_limit_seconds=args.rate_limit,
    )
    report = scraper.scrape(dry_run=args.dry_run or not args.write_db, write_db=args.write_db, report_json=args.report_json)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
