"""
GİBTÜ bölüm/program/alt birim yönetim bilgileri için izole scraper.

Bu modül genel crawler değildir. Yalnızca DEFAULT_TARGETS allowlist'indeki
resmi BirimYonetim.aspx ve özel BirimAkademikPersonel.aspx kaynaklarını işler.
Profil linkleri sadece kaynak sayfada göründüğü kadarıyla kaydedilir; ek profil
fetch'i yapılmaz.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 - Windows stdout UTF-8

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
SCRAPER_NAME = "subunit_management_scraper"
METADATA_VERSION = "subunit_management.v1"
SCOPE_TYPE = "department_program_management"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 1.0

VALID_STATUSES = {"valid", "partial"}
REPORT_ONLY_STATUSES = {"needs_review", "ignored_non_management", "empty", "failed"}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}", re.IGNORECASE)

TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"prof\.?\s*dr\.?|profesör|profesor", "Prof. Dr."),
    (r"doç\.?\s*dr\.?|doc\.?\s*dr\.?|doçent|docent", "Doç. Dr."),
    (r"dr\.?\s*öğr\.?\s*üyesi|dr\.?\s*ogr\.?\s*uyesi|doktor\s+öğretim\s+üyesi", "Dr. Öğr. Üyesi"),
    (r"öğr\.?\s*gör\.?\s*dr\.?|ogr\.?\s*gor\.?\s*dr\.?", "Öğr. Gör. Dr."),
    (r"öğr\.?\s*gör\.?|ogr\.?\s*gor\.?|öğretim\s+görevlisi", "Öğr. Gör."),
    (r"arş\.?\s*gör\.?\s*dr\.?|araş\.?\s*gör\.?\s*dr\.?|ars\.?\s*gor\.?\s*dr\.?", "Arş. Gör. Dr."),
    (r"arş\.?\s*gör\.?|araş\.?\s*gör\.?|ars\.?\s*gor\.?|araştırma\s+görevlisi", "Arş. Gör."),
)

TITLE_AT_START_RE = re.compile(
    r"^\s*(?P<title>" + "|".join(f"(?:{pattern})" for pattern, _ in TITLE_PATTERNS) + r")\s+",
    re.IGNORECASE,
)

MANAGEMENT_ROLE_KEYWORDS: tuple[str, ...] = (
    "baskan",
    "baskanlik",
    "baskan v",
    "baskan yardim",
    "dekan",
    "mudur",
    "yonetici",
    "yonetim",
    "koordinator",
    "sorumlu",
    "sekreter",
    "kurul",
)

GENERIC_GROUP_KEYS: frozenset[str] = frozenset({
    "yonetim",
    "akademik",
    "akademik personel",
    "personel",
})

DB_CANDIDATE_ROLE_KEYS: frozenset[str] = frozenset({
    "bolum baskani",
    "bolum baskan v",
    "bolum baskan vekili",
    "bolum baskan yardimcisi",
    "program baskani",
    "program baskan yardimcisi",
    "anabilim dali baskani",
})

OUT_OF_SCOPE_ROLE_MARKERS: tuple[str, ...] = (
    "dekan",
    "fakulte kurulu",
    "fakulte yonetim kurulu",
    "fakulte sekreteri",
    "meslek yuksekokul mudur",
    "yuksekokul mudur",
    "yuksekokul sekreteri",
    "yuksekokul yonetim kurulu",
    "raportor",
    "ogretim elemani",
)

ALLOWED_PARTIAL_ISSUES: frozenset[str] = frozenset({
    "missing_email",
    "missing_phone",
    "placeholder_phone_0000",
})


@dataclass(frozen=True)
class SubunitManagementTarget:
    target_unit_name: str
    department_or_program_name: str
    source_url: str
    source_page_type: str
    birim_id: int
    unit_type: str = "department"
    parent_unit_name: str | None = None
    aliases: tuple[str, ...] = ()


DEFAULT_TARGETS: tuple[SubunitManagementTarget, ...] = (
    SubunitManagementTarget(
        "Bilgisayar Mühendisliği Bölümü",
        "Bilgisayar Mühendisliği Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=18",
        "BirimYonetim",
        18,
        aliases=("bm", "bilgisayar müh", "bilgisayar muh", "bilgisayar muhendisligi"),
    ),
    SubunitManagementTarget(
        "Elektrik Elektronik Mühendisliği Bölümü",
        "Elektrik Elektronik Mühendisliği Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=16",
        "BirimYonetim",
        16,
        aliases=("eem", "elektrik elektronik", "elektrik-elektronik", "elektrik elektronik muhendisligi"),
    ),
    SubunitManagementTarget(
        "Endüstri Mühendisliği Bölümü",
        "Endüstri Mühendisliği Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=19",
        "BirimYonetim",
        19,
        aliases=("endustri muh", "endüstri", "endustri", "endustri muhendisligi"),
    ),
    SubunitManagementTarget(
        "Temel İslam Bilimleri Bölümü",
        "Temel İslam Bilimleri Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=12",
        "BirimYonetim",
        12,
        parent_unit_name="İlahiyat Fakültesi",
        aliases=("temel islami bilimler", "temel islam bilimleri", "tib"),
    ),
    SubunitManagementTarget(
        "Felsefe ve Din Bilimleri Bölümü",
        "Felsefe ve Din Bilimleri Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=13",
        "BirimYonetim",
        13,
        parent_unit_name="İlahiyat Fakültesi",
        aliases=("fdb", "felsefe din bilimleri"),
    ),
    SubunitManagementTarget(
        "Tıp Fakültesi / Tıp Bölümü",
        "Tıp Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=20",
        "BirimYonetim",
        20,
        parent_unit_name="Tıp Fakültesi",
        aliases=("tip", "tıp", "tip bolumu", "tıp bölümü"),
    ),
    SubunitManagementTarget(
        "Mütercim Tercümanlık Bölümü",
        "Mütercim Tercümanlık Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=94",
        "BirimYonetim",
        94,
        aliases=("mutercim tercumanlik", "tercümanlık", "tercumanlik"),
    ),
    SubunitManagementTarget(
        "Gastronomi ve Mutfak Sanatları Bölümü",
        "Gastronomi ve Mutfak Sanatları Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=105",
        "BirimYonetim",
        105,
        aliases=("gastronomi", "gastronomi ve mutfak sanatlari"),
    ),
    SubunitManagementTarget(
        "Fizyoterapi Programı / Fizyoterapi ve Rehabilitasyon Bölümü",
        "Fizyoterapi Programı / Fizyoterapi ve Rehabilitasyon Bölümü",
        "https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id=96",
        "BirimAkademikPersonel",
        96,
        unit_type="program",
        aliases=("fizyoterapi programi", "fizyoterapi programı", "ftr program", "ftr"),
    ),
    SubunitManagementTarget(
        "Yaşlı Bakımı Programı / Sağlık ve Bakım Hizmetleri Bölümü",
        "Yaşlı Bakımı Programı",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=97",
        "BirimYonetim",
        97,
        unit_type="program",
        parent_unit_name="Sağlık ve Bakım Hizmetleri Bölümü",
        aliases=("yasli bakimi", "yaşlı bakımı"),
    ),
    SubunitManagementTarget(
        "Tıbbi Laboratuvar Teknikleri Programı / Tıbbi Hizmetler ve Teknikler Bölümü",
        "Tıbbi Laboratuvar Teknikleri Programı",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=99",
        "BirimYonetim",
        99,
        unit_type="program",
        parent_unit_name="Tıbbi Hizmetler ve Teknikler Bölümü",
        aliases=("tlt", "tibbi lab teknikleri", "tıbbi laboratuvar teknikleri"),
    ),
    SubunitManagementTarget(
        "Bilgisayar Teknolojisi Bölümü / Bilgisayar Programcılığı",
        "Bilgisayar Programcılığı",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=46",
        "BirimYonetim",
        46,
        unit_type="program",
        parent_unit_name="Bilgisayar Teknolojisi Bölümü",
        aliases=("bilgisayar programciligi", "bilgisayar programcılığı"),
    ),
    SubunitManagementTarget(
        "Makine ve Metal Teknolojisi Bölümü / Makine Programı",
        "Makine Programı",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=47",
        "BirimYonetim",
        47,
        unit_type="program",
        parent_unit_name="Makine ve Metal Teknolojisi Bölümü",
        aliases=("makine programi", "makine programı", "makine"),
    ),
    SubunitManagementTarget(
        "Elektronik ve Otomasyon Bölümü / Radyo ve Televizyon Teknolojisi",
        "Radyo ve Televizyon Teknolojisi",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=48",
        "BirimYonetim",
        48,
        unit_type="program",
        parent_unit_name="Elektronik ve Otomasyon Bölümü",
        aliases=("radyo tv", "rtt", "radyo ve televizyon teknolojisi"),
    ),
    SubunitManagementTarget(
        "Hemşirelik Bölümü",
        "Hemşirelik Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=29",
        "BirimYonetim",
        29,
        aliases=("hemsirelik", "hemşirelik"),
    ),
    SubunitManagementTarget(
        "Sağlık Bilimleri Fakültesi / Fizyoterapi ve Rehabilitasyon Bölümü",
        "Fizyoterapi ve Rehabilitasyon Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=32",
        "BirimYonetim",
        32,
        parent_unit_name="Sağlık Bilimleri Fakültesi",
        aliases=("fizyoterapi ve rehabilitasyon", "fizyoterapi", "ftr bolum", "ftr bölüm"),
    ),
    SubunitManagementTarget(
        "Ebelik Bölümü",
        "Ebelik Bölümü",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=30",
        "BirimYonetim",
        30,
        aliases=("ebelik",),
    ),
    SubunitManagementTarget(
        "Yabancı Diller Bölümü / Birimi",
        "Yabancı Diller Bölümü / Birimi",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=34",
        "BirimYonetim",
        34,
        unit_type="unit",
        aliases=("yabanci diller", "yabancı diller", "yabanci dil", "yabancı dil", "ydyo"),
    ),
)

TARGET_BY_ALLOWLIST_KEY: dict[tuple[str, int], SubunitManagementTarget] = {
    (Path(urlparse(target.source_url).path.lower()).name, target.birim_id): target
    for target in DEFAULT_TARGETS
}
TARGET_BY_SOURCE_URL: dict[str, SubunitManagementTarget] = {
    target.source_url: target for target in DEFAULT_TARGETS
}


@dataclass
class SubunitManagementPageRecord:
    snapshot_id: str
    scrape_run_id: str
    source_url: str
    source_page_type: str
    target_unit_name: str
    parent_unit_name: str | None
    department_or_program_name: str
    scope_type: str
    source_birim_id: int
    http_status: int | None
    source_checksum: str
    fetched_at: str
    parse_status: str
    record_count: int
    ignored_non_management_count: int
    raw_text: str
    raw_html: str
    validation_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubunitManagementRecord:
    source_url: str
    source_page_type: str
    target_unit_name: str
    parent_unit_name: str | None
    department_or_program_name: str
    scope_type: str
    management_role: str | None
    management_role_key: str
    academic_title: str | None
    person_name: str | None
    person_name_normalized: str
    full_display_name: str | None
    email: str | None
    phone: str | None
    office_location: str | None
    profile_url: str | None
    image_url: str | None
    raw_text: str
    evidence_html_selector: str | None
    evidence_text: str
    scraped_at: str
    source_checksum: str
    parse_status: str
    parse_confidence: float
    needs_review_reason: str | None
    validation_issues: list[str]
    stable_person_key: str
    dedup_key: str
    snapshot_id: str
    source_birim_id: int
    group_title: str | None
    group_order: int
    record_order: int


@dataclass
class IgnoredNonManagementRecord:
    source_url: str
    source_page_type: str
    target_unit_name: str
    raw_text: str
    evidence_text: str
    reason: str
    group_title: str | None
    record_order: int


@dataclass
class SuppressedDuplicateRecord:
    source_url: str
    source_page_type: str
    target_unit_name: str
    management_role: str | None
    person_name: str | None
    dedup_key: str
    kept_record_order: int
    duplicate_record_order: int
    raw_text: str
    reason: str = "Aynı kişi, aynı rol ve aynı kaynak URL için tekrar kayıt bastırıldı."


@dataclass
class SubunitManagementScrapeReport:
    success: bool = False
    scrape_run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    scope_type: str = SCOPE_TYPE
    target_url_count: int = 0
    pages: list[SubunitManagementPageRecord] = field(default_factory=list)
    records: list[SubunitManagementRecord] = field(default_factory=list)
    ignored_non_management_records: list[IgnoredNonManagementRecord] = field(default_factory=list)
    duplicate_suppressed_records: list[SuppressedDuplicateRecord] = field(default_factory=list)
    validation_report: dict[str, Any] = field(default_factory=dict)
    import_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(value: str | None) -> str:
    """Türkçe görüntü değerini bozmadan karşılaştırma anahtarı üretir."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    replacements = {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_for_match(value)
    for pattern, canonical in TITLE_PATTERNS:
        if re.fullmatch(pattern, normalized, re.IGNORECASE) or re.search(pattern, normalized, re.IGNORECASE):
            return canonical
    return _single_line(value)


def split_academic_title_and_name(value: str | None) -> tuple[str | None, str | None]:
    text = _single_line(value)
    if not text:
        return None, None
    match = TITLE_AT_START_RE.search(text)
    if not match:
        return None, text
    title = normalize_title(match.group("title"))
    name = _single_line(text[match.end():])
    return title, name or None


def _looks_like_academic_title(value: str | None) -> bool:
    normalized = normalize_for_match(value)
    if not normalized:
        return False
    return any(re.fullmatch(pattern, normalized, re.IGNORECASE) for pattern, _ in TITLE_PATTERNS)


def _looks_like_management_role(value: str | None) -> bool:
    normalized = normalize_for_match(value)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in MANAGEMENT_ROLE_KEYWORDS)


def _header_charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _mojibake_score(text: str) -> int:
    return text.count("\ufffd") + text.count("Ã") + text.count("Ä") + text.count("Å")


def _decode_response(response: requests.Response) -> str:
    """Yanıtı Türkçe karakterleri koruyacak en düşük mojibake skoruyla decode eder."""
    content = getattr(response, "content", None)
    if not content:
        return getattr(response, "text", "") or ""

    candidates = [
        _header_charset(response.headers.get("Content-Type") if hasattr(response, "headers") else None),
        getattr(response, "apparent_encoding", None),
        "utf-8",
        "iso-8859-9",
        "windows-1254",
        getattr(response, "encoding", None),
    ]
    decoded: list[tuple[int, str]] = []
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            text = content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        decoded.append((_mojibake_score(text), text))

    if decoded:
        decoded.sort(key=lambda item: item[0])
        return decoded[0][1]
    return content.decode("utf-8", errors="replace")


def _target_from_url(url: str) -> SubunitManagementTarget | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme != "https":
        return None
    if host not in {"www.gibtu.edu.tr", "gibtu.edu.tr"}:
        return None
    page_name = Path(parsed.path.lower()).name
    if page_name not in {"birimyonetim.aspx", "birimakademikpersonel.aspx"}:
        return None
    query = parse_qs(parsed.query)
    if set(query) != {"id"}:
        return None
    values = query.get("id") or []
    if len(values) != 1 or not values[0].isdigit():
        return None
    return TARGET_BY_ALLOWLIST_KEY.get((page_name, int(values[0])))


def is_allowed_subunit_management_url(url: str) -> bool:
    return _target_from_url(url) is not None


def _main_content(soup: BeautifulSoup) -> Tag:
    for selector in (
        "div.birim_safya_body_detay",
        "section.birim_safya_body",
        "div.page_body",
        "main",
        "body",
    ):
        node = soup.select_one(selector)
        if node:
            return node
    return soup


def _clean_soup(root: Tag) -> None:
    for selector in (
        "script",
        "style",
        "noscript",
        "iframe",
        "footer",
        "nav",
        "ul.collapsible",
        "span.birim-menu",
        "span#birim-menu-slide",
    ):
        for node in root.select(selector):
            node.decompose()


def _li_text(card: Tag, selector: str) -> str:
    node = card.select_one(selector)
    if not node:
        return ""
    for icon in node.select("i.material-icons"):
        icon.decompose()
    return _single_line(node.get_text(" ", strip=True))


def _extract_email(value: str) -> str | None:
    match = EMAIL_RE.search(value or "")
    return match.group(0).lower() if match else None


def _normalize_phone(value: str | None) -> str | None:
    text = _single_line(value)
    if not text:
        return None
    digits = re.sub(r"\D+", "", text)
    return digits or None


def _stable_person_key(name: str | None, email: str | None, profile_url: str | None, raw_text: str | None = None) -> str:
    if profile_url:
        return f"profile:{profile_url.strip().lower()}"
    if email:
        return f"email:{email.strip().lower()}"
    if name:
        return f"name:{normalize_for_match(name)}"
    return f"unknown:{_sha256_text(raw_text or '')[:12]}"


def _status_confidence(status: str) -> float:
    if status == "valid":
        return 0.95
    if status == "partial":
        return 0.78
    if status == "needs_review":
        return 0.35
    return 0.1


def _role_from_group_and_card(group_title: str | None, card_role: str | None) -> tuple[str | None, str | None]:
    group = _single_line(group_title)
    role = _single_line(card_role)
    group_key = normalize_for_match(group)

    if role and not _looks_like_academic_title(role):
        return role, None
    if role and _looks_like_academic_title(role):
        title = normalize_title(role)
        if group and group_key not in GENERIC_GROUP_KEYS:
            return group, title
        return None, title
    if group and group_key not in GENERIC_GROUP_KEYS:
        return group, None
    return role or None, None


def _record_status(
    source_url: str,
    target_unit_name: str,
    management_role: str | None,
    person_name: str | None,
    email: str | None,
    phone: str | None,
) -> tuple[str, list[str], str | None]:
    issues: list[str] = []
    if not source_url:
        issues.append("missing_source_url")
    if not target_unit_name:
        issues.append("missing_target_unit_name")
    if not management_role:
        issues.append("missing_management_role")
    if not person_name:
        issues.append("missing_person_name")

    required_missing = [issue for issue in issues if issue.startswith("missing_") and issue not in {"missing_email"}]
    if required_missing:
        return "needs_review", issues, ", ".join(required_missing)

    if not email:
        issues.append("missing_email")
    if not phone:
        issues.append("missing_phone")
    elif phone == "0000":
        issues.append("placeholder_phone_0000")

    if any(issue in issues for issue in ("missing_email", "missing_phone", "placeholder_phone_0000")):
        return "partial", issues, None
    return "valid", issues, None


def _is_department_or_program_context(record: SubunitManagementRecord) -> bool:
    target = TARGET_BY_SOURCE_URL.get(record.source_url)
    if target:
        context = normalize_for_match(f"{target.target_unit_name} {target.department_or_program_name}")
        return target.unit_type in {"department", "program"} or "bolum" in context or "program" in context
    context = normalize_for_match(f"{record.target_unit_name} {record.department_or_program_name}")
    return "bolum" in context or "program" in context


def _role_is_out_of_scope(role_key: str) -> bool:
    if not role_key:
        return False
    if role_key == "uye":
        return True
    return any(marker in role_key for marker in OUT_OF_SCOPE_ROLE_MARKERS)


def _role_is_db_candidate(record: SubunitManagementRecord) -> bool:
    role_key = record.management_role_key or normalize_for_match(record.management_role)
    if not role_key or _role_is_out_of_scope(role_key):
        return False
    if role_key in DB_CANDIDATE_ROLE_KEYS:
        return True
    if "koordinator" in role_key or "sorumlu" in role_key:
        return True
    if role_key == "baskan" and _is_department_or_program_context(record):
        return True
    return False


def _partial_issues_are_warnings(record: SubunitManagementRecord) -> bool:
    if record.parse_status != "partial":
        return True
    return set(record.validation_issues).issubset(ALLOWED_PARTIAL_ISSUES)


def db_candidate_rejection_reason(record: SubunitManagementRecord) -> str | None:
    if record.parse_status == "needs_review":
        return "needs_review_records_are_report_only"
    if record.parse_status not in VALID_STATUSES:
        return f"parse_status_{record.parse_status}_is_not_writable"
    if not _partial_issues_are_warnings(record):
        return "partial_has_required_field_issue"
    if _role_is_db_candidate(record):
        return None
    role_key = record.management_role_key or normalize_for_match(record.management_role)
    if _role_is_out_of_scope(role_key):
        return "excluded_out_of_scope_role"
    return "role_not_in_db_candidate_allowlist"


def is_db_candidate_record(record: SubunitManagementRecord) -> bool:
    return db_candidate_rejection_reason(record) is None


def db_candidate_records(records: list[SubunitManagementRecord]) -> list[SubunitManagementRecord]:
    return [record for record in records if is_db_candidate_record(record)]


def excluded_out_of_scope_records(records: list[SubunitManagementRecord]) -> list[SubunitManagementRecord]:
    return [
        record
        for record in records
        if record.parse_status in VALID_STATUSES and db_candidate_rejection_reason(record) is not None
    ]


def _evidence_selector(group_order: int, record_order: int) -> str:
    return f"div.personel_listesi group[{group_order}] card[{record_order}]"


def _raw_text(root: Tag) -> str:
    return "\n".join(
        line for line in (_single_line(line) for line in root.get_text("\n", strip=True).splitlines()) if line
    )


def parse_subunit_management_page(
    html: str,
    target: SubunitManagementTarget,
    source_url: str,
    scrape_run_id: str,
    http_status: int | None = 200,
    fetched_at: str | None = None,
) -> tuple[
    SubunitManagementPageRecord,
    list[SubunitManagementRecord],
    list[IgnoredNonManagementRecord],
    list[SuppressedDuplicateRecord],
]:
    fetched_at = fetched_at or utc_now_iso()
    source_checksum = _sha256_text(html or f"{source_url}:{http_status}")
    snapshot_id = _sha256_text(f"{scrape_run_id}:{source_url}:{source_checksum}")[:24]

    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)
    raw_text = _raw_text(root)

    container = root.select_one("div.personel_listesi") or root
    records: list[SubunitManagementRecord] = []
    ignored: list[IgnoredNonManagementRecord] = []
    suppressed_duplicates: list[SuppressedDuplicateRecord] = []
    seen_dedup_orders: dict[str, int] = {}

    current_group: str | None = None
    group_order = 0
    record_order = 0

    for child in [node for node in container.children if isinstance(node, Tag)]:
        classes = child.get("class") or []
        if "birim_modul_baslik" in classes:
            current_group = _single_line(child.get_text(" ", strip=True))
            if current_group:
                group_order += 1
            continue

        cards = child.select("div.card")
        if not cards:
            continue

        if current_group is None:
            current_group = "Belirsiz Grup"
            group_order += 1

        for card in cards:
            record_order += 1
            raw_card_text = _single_line(card.get_text(" ", strip=True))
            name_line = _li_text(card, "li.adsoyad")
            title_from_name, person_name = split_academic_title_and_name(name_line)
            card_role_text = _li_text(card, "li.unvan") or None
            management_role, title_from_role = _role_from_group_and_card(current_group, card_role_text)
            academic_title = title_from_name or title_from_role

            if target.source_page_type == "BirimAkademikPersonel" and not _looks_like_management_role(management_role):
                ignored.append(
                    IgnoredNonManagementRecord(
                        source_url=source_url,
                        source_page_type=target.source_page_type,
                        target_unit_name=target.target_unit_name,
                        raw_text=raw_card_text,
                        evidence_text=raw_card_text,
                        reason="BirimAkademikPersonel kartında açık yönetim rolü sinyali yok.",
                        group_title=current_group,
                        record_order=record_order,
                    )
                )
                continue

            phone = _normalize_phone(_li_text(card, "li.dahili"))
            email = _extract_email(_li_text(card, "li.mail"))
            blog = card.select_one("li.blog a[href]")
            image = card.select_one("img[src]")
            profile_url = urljoin(source_url, blog.get("href")) if blog else None
            image_url = urljoin(source_url, image.get("src")) if image else None
            full_display_name = " ".join(part for part in (academic_title, person_name) if part) or person_name
            parse_status, issues, review_reason = _record_status(
                source_url=source_url,
                target_unit_name=target.target_unit_name,
                management_role=management_role,
                person_name=person_name,
                email=email,
                phone=phone,
            )
            role_key = normalize_for_match(management_role)
            person_key = _stable_person_key(person_name, email, profile_url, raw_card_text)
            dedup_key = "|".join([
                normalize_for_match(source_url),
                normalize_for_match(target.target_unit_name),
                role_key,
                person_key,
            ])

            record = SubunitManagementRecord(
                source_url=source_url,
                source_page_type=target.source_page_type,
                target_unit_name=target.target_unit_name,
                parent_unit_name=target.parent_unit_name,
                department_or_program_name=target.department_or_program_name,
                scope_type=SCOPE_TYPE,
                management_role=management_role,
                management_role_key=role_key,
                academic_title=academic_title,
                person_name=person_name,
                person_name_normalized=normalize_for_match(person_name),
                full_display_name=full_display_name,
                email=email,
                phone=phone,
                office_location=None,
                profile_url=profile_url,
                image_url=image_url,
                raw_text=raw_card_text,
                evidence_html_selector=_evidence_selector(group_order, record_order),
                evidence_text=raw_card_text,
                scraped_at=fetched_at,
                source_checksum=source_checksum,
                parse_status=parse_status,
                parse_confidence=_status_confidence(parse_status),
                needs_review_reason=review_reason,
                validation_issues=issues,
                stable_person_key=person_key,
                dedup_key=dedup_key,
                snapshot_id=snapshot_id,
                source_birim_id=target.birim_id,
                group_title=current_group,
                group_order=group_order,
                record_order=record_order,
            )
            if dedup_key in seen_dedup_orders:
                suppressed_duplicates.append(
                    SuppressedDuplicateRecord(
                        source_url=source_url,
                        source_page_type=target.source_page_type,
                        target_unit_name=target.target_unit_name,
                        management_role=management_role,
                        person_name=person_name,
                        dedup_key=dedup_key,
                        kept_record_order=seen_dedup_orders[dedup_key],
                        duplicate_record_order=record_order,
                        raw_text=raw_card_text,
                    )
                )
                continue
            seen_dedup_orders[dedup_key] = record_order
            records.append(record)

    if not records and not ignored:
        page_status = "empty"
    elif any(record.parse_status == "needs_review" for record in records):
        page_status = "needs_review"
    elif any(record.parse_status == "partial" for record in records):
        page_status = "partial"
    else:
        page_status = "valid"

    page = SubunitManagementPageRecord(
        snapshot_id=snapshot_id,
        scrape_run_id=scrape_run_id,
        source_url=source_url,
        source_page_type=target.source_page_type,
        target_unit_name=target.target_unit_name,
        parent_unit_name=target.parent_unit_name,
        department_or_program_name=target.department_or_program_name,
        scope_type=SCOPE_TYPE,
        source_birim_id=target.birim_id,
        http_status=http_status,
        source_checksum=source_checksum,
        fetched_at=fetched_at,
        parse_status=page_status,
        record_count=len(records),
        ignored_non_management_count=len(ignored),
        raw_text=raw_text,
        raw_html=html or "",
    )
    return page, records, ignored, suppressed_duplicates


def _record_report_payload(record: SubunitManagementRecord, reason: str | None = None) -> dict[str, Any]:
    payload = {
        "target_unit_name": record.target_unit_name,
        "department_or_program_name": record.department_or_program_name,
        "management_role": record.management_role,
        "academic_title": record.academic_title,
        "person_name": record.person_name,
        "full_display_name": record.full_display_name,
        "email": record.email,
        "phone": record.phone,
        "source_url": record.source_url,
        "source_page_type": record.source_page_type,
        "parse_status": record.parse_status,
        "validation_issues": record.validation_issues,
        "needs_review_reason": record.needs_review_reason,
        "evidence_html_selector": record.evidence_html_selector,
        "evidence_text": record.evidence_text,
        "record_order": record.record_order,
    }
    if reason:
        payload["candidate_rejection_reason"] = reason
    return payload


def _role_groups(records: list[SubunitManagementRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SubunitManagementRecord]] = {}
    for record in records:
        grouped.setdefault(record.management_role or "needs_review", []).append(record)
    return [
        {
            "management_role": role,
            "count": len(items),
            "sample_person": items[0].full_display_name or items[0].person_name,
            "source_url": items[0].source_url,
        }
        for role, items in sorted(grouped.items(), key=lambda item: item[0])
    ]


def build_validation_report(report: SubunitManagementScrapeReport) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    record_status_counts: dict[str, int] = {}
    missing_email = []
    missing_phone = []
    missing_required = []
    needs_review = []
    duplicate_candidates: dict[str, list[SubunitManagementRecord]] = {}
    page_summaries = []
    candidate_records = db_candidate_records(report.records)
    candidate_keys = {record.dedup_key for record in candidate_records}
    excluded_records = excluded_out_of_scope_records(report.records)

    for page in report.pages:
        status_counts[page.parse_status] = status_counts.get(page.parse_status, 0) + 1
        page_records = [record for record in report.records if record.snapshot_id == page.snapshot_id]
        page_candidates = [record for record in page_records if record.dedup_key in candidate_keys]
        page_excluded = [
            record for record in page_records
            if record.parse_status in VALID_STATUSES and record.dedup_key not in candidate_keys
        ]
        page_summary = {
            "source_url": page.source_url,
            "source_page_type": page.source_page_type,
            "target_unit_name": page.target_unit_name,
            "parse_status": page.parse_status,
            "record_count": len(page_records),
            "db_candidate_count": len(page_candidates),
            "excluded_out_of_scope_count": len(page_excluded),
            "valid_count": sum(1 for item in page_records if item.parse_status == "valid"),
            "partial_count": sum(1 for item in page_records if item.parse_status == "partial"),
            "valid_db_candidate_count": sum(1 for item in page_candidates if item.parse_status == "valid"),
            "partial_db_candidate_count": sum(1 for item in page_candidates if item.parse_status == "partial"),
            "needs_review_count": sum(1 for item in page_records if item.parse_status == "needs_review"),
            "ignored_non_management_count": page.ignored_non_management_count,
        }
        page.validation_report = page_summary
        page_summaries.append(page_summary)

    for record in report.records:
        record_status_counts[record.parse_status] = record_status_counts.get(record.parse_status, 0) + 1
        duplicate_candidates.setdefault(record.dedup_key, []).append(record)
        payload = {
            "target_unit_name": record.target_unit_name,
            "department_or_program_name": record.department_or_program_name,
            "management_role": record.management_role,
            "person_name": record.person_name,
            "email": record.email,
            "phone": record.phone,
            "source_url": record.source_url,
            "parse_status": record.parse_status,
            "validation_issues": record.validation_issues,
            "needs_review_reason": record.needs_review_reason,
            "evidence_html_selector": record.evidence_html_selector,
            "evidence_text": record.evidence_text,
        }
        if not record.email:
            missing_email.append(payload)
        if not record.phone or record.phone == "0000":
            missing_phone.append(payload)
        if any(
            issue in record.validation_issues
            for issue in ("missing_source_url", "missing_target_unit_name", "missing_management_role", "missing_person_name")
        ):
            missing_required.append(payload)
        if record.parse_status == "needs_review":
            needs_review.append(payload)

    duplicates = [
        {
            "dedup_key": key,
            "count": len(items),
            "records": [
                {
                    "target_unit_name": item.target_unit_name,
                    "management_role": item.management_role,
                    "person_name": item.person_name,
                    "source_url": item.source_url,
                    "record_order": item.record_order,
                }
                for item in items
            ],
        }
        for key, items in duplicate_candidates.items()
        if len(items) > 1
    ]

    write_blockers = []
    if any(page.parse_status == "failed" for page in report.pages):
        write_blockers.append("failed_page")
    if duplicates:
        write_blockers.append("duplicate_records")

    candidate_count = len(candidate_records)
    valid_db_candidate_count = sum(1 for record in candidate_records if record.parse_status == "valid")
    partial_db_candidate_count = sum(1 for record in candidate_records if record.parse_status == "partial")
    partial_blocked_records = [
        _record_report_payload(record, db_candidate_rejection_reason(record))
        for record in report.records
        if record.parse_status == "partial" and not _partial_issues_are_warnings(record)
    ]
    write_ready = candidate_count > 0 and not write_blockers
    return {
        "processed_url_count": len(report.pages),
        "target_url_count": report.target_url_count,
        "total_found": len(report.records),
        "management_record_count": len(report.records),
        "db_candidate_count": candidate_count,
        "excluded_out_of_scope_count": len(excluded_records),
        "valid_db_candidate_count": valid_db_candidate_count,
        "partial_db_candidate_count": partial_db_candidate_count,
        "valid_count": record_status_counts.get("valid", 0),
        "partial_count": record_status_counts.get("partial", 0),
        "needs_review_count": record_status_counts.get("needs_review", 0),
        "empty_count": status_counts.get("empty", 0),
        "failed_count": status_counts.get("failed", 0),
        "ignored_non_management_count": len(report.ignored_non_management_records),
        "duplicate_suppressed_count": len(report.duplicate_suppressed_records),
        "page_status_counts": status_counts,
        "record_status_counts": record_status_counts,
        "page_summaries": page_summaries,
        "missing_email_records": missing_email,
        "missing_phone_records": missing_phone,
        "missing_required_records": missing_required,
        "partial_blocked_records": partial_blocked_records,
        "duplicate_records": duplicates,
        "needs_review_records": needs_review,
        "role_groups": _role_groups(report.records),
        "db_candidate_role_groups": _role_groups(candidate_records),
        "excluded_out_of_scope_role_groups": _role_groups(excluded_records),
        "db_candidate_records": [_record_report_payload(record) for record in candidate_records],
        "excluded_out_of_scope_records": [
            _record_report_payload(record, db_candidate_rejection_reason(record))
            for record in excluded_records
        ],
        "ignored_non_management_records": [asdict(item) for item in report.ignored_non_management_records],
        "duplicate_suppressed_records": [asdict(item) for item in report.duplicate_suppressed_records],
        "write_ready": write_ready,
        "db_write_ready": write_ready,
        "db_write_blockers": write_blockers,
        "db_write_note": (
            "Dry-run raporudur; DB yazımı yapılmadı. Yalnız db_candidate_records yazılabilir. "
            "needs_review ve excluded_out_of_scope kayıtları yazılmamalıdır."
        ),
        "errors": report.errors,
    }


def build_markdown_report(report: SubunitManagementScrapeReport) -> str:
    validation = report.validation_report
    lines = [
        "# GİBTÜ Alt Birim Yönetim Dry-Run Raporu",
        "",
        f"- Scrape run: `{report.scrape_run_id}`",
        f"- Başlangıç: `{report.started_at}`",
        f"- Bitiş: `{report.finished_at}`",
        f"- DB yazımı: yapılmadı",
        f"- İşlenen URL: {validation.get('processed_url_count')}/{validation.get('target_url_count')}",
        f"- Total found: {validation.get('total_found')}",
        f"- DB candidate: {validation.get('db_candidate_count')}",
        f"- Excluded out-of-scope: {validation.get('excluded_out_of_scope_count')}",
        f"- Valid: {validation.get('valid_count')}",
        f"- Partial: {validation.get('partial_count')}",
        f"- Valid DB candidate: {validation.get('valid_db_candidate_count')}",
        f"- Partial DB candidate: {validation.get('partial_db_candidate_count')}",
        f"- Needs review: {validation.get('needs_review_count')}",
        f"- Empty: {validation.get('empty_count')}",
        f"- Failed: {validation.get('failed_count')}",
        f"- Ignored non-management: {validation.get('ignored_non_management_count')}",
        f"- Duplicate suppressed: {validation.get('duplicate_suppressed_count')}",
        f"- Duplicate: {len(validation.get('duplicate_records') or [])}",
        f"- Write ready: {'Evet' if validation.get('write_ready') else 'Hayır'}",
    ]

    blockers = validation.get("db_write_blockers") or []
    if blockers:
        lines.append(f"- DB write engelleri: {', '.join(blockers)}")

    lines.extend(["", "## URL Özeti", ""])
    for item in validation.get("page_summaries") or []:
        lines.append(
            "- "
            f"{item['target_unit_name']} | {item['source_page_type']} | "
            f"status={item['parse_status']} | total={item['record_count']} | "
            f"db_candidate={item['db_candidate_count']} | "
            f"excluded={item['excluded_out_of_scope_count']} | "
            f"valid_candidate={item['valid_db_candidate_count']} | "
            f"partial_candidate={item['partial_db_candidate_count']} | "
            f"needs_review={item['needs_review_count']} | "
            f"ignored={item['ignored_non_management_count']}"
        )

    lines.extend(["", "## DB Adayı Örnek Kayıtlar", ""])
    for record in (validation.get("db_candidate_records") or [])[:8]:
        lines.append(
            "- "
            f"Birim: {record.get('target_unit_name')} | Görev: {record.get('management_role')} | "
            f"Ad Soyad: {record.get('full_display_name') or record.get('person_name')} | "
            f"Status: {record.get('parse_status')} | Kaynak: {record.get('source_url')}"
        )

    excluded_records = validation.get("excluded_out_of_scope_records") or []
    lines.extend(["", "## Excluded Out-of-Scope", ""])
    if not excluded_records:
        lines.append("- excluded_out_of_scope kayıt yok.")
    else:
        for record in excluded_records[:30]:
            lines.append(
                "- "
                f"Birim: {record.get('target_unit_name')} | Görev: {record.get('management_role')} | "
                f"Ad Soyad: {record.get('full_display_name') or record.get('person_name')} | "
                f"reason={record.get('candidate_rejection_reason')} | Kaynak: {record.get('source_url')}"
            )

    review_records = validation.get("needs_review_records") or []
    lines.extend(["", "## Manuel Kontrol Gerektiren Kayıtlar", ""])
    if not review_records:
        lines.append("- needs_review kayıt yok.")
    else:
        for record in review_records[:20]:
            lines.append(
                "- "
                f"{record.get('target_unit_name')} | {record.get('management_role')} | "
                f"{record.get('person_name')} | reason={record.get('needs_review_reason')}"
            )

    ignored = validation.get("ignored_non_management_records") or []
    lines.extend(["", "## Ignored Non-Management", ""])
    if not ignored:
        lines.append("- ignored_non_management kayıt yok.")
    else:
        for item in ignored[:20]:
            lines.append(
                "- "
                f"{item.get('target_unit_name')} | group={item.get('group_title')} | "
                f"reason={item.get('reason')}"
            )

    suppressed = validation.get("duplicate_suppressed_records") or []
    lines.extend(["", "## Duplicate Suppressed", ""])
    if not suppressed:
        lines.append("- duplicate_suppressed kayıt yok.")
    else:
        for item in suppressed[:20]:
            lines.append(
                "- "
                f"{item.get('target_unit_name')} | {item.get('management_role')} | "
                f"{item.get('person_name')} | kept={item.get('kept_record_order')} | "
                f"duplicate={item.get('duplicate_record_order')}"
            )

    return "\n".join(lines) + "\n"


class SubunitManagementScraper:
    """Allowlist bölüm/program yönetim sayfalarını DB-first rapora dönüştürür."""

    def __init__(
        self,
        targets: tuple[SubunitManagementTarget, ...] = DEFAULT_TARGETS,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
    ) -> None:
        self.targets = targets
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; UniChatSubunitManagementScraper/1.0; +https://www.gibtu.edu.tr)",
        })
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self._last_request_at = 0.0

    def scrape(
        self,
        dry_run: bool = True,
        write_db: bool = False,
        report_json: str | Path | None = None,
        validation_report_json: str | Path | None = None,
        import_summary_json: str | Path | None = None,
    ) -> SubunitManagementScrapeReport:
        started_at = utc_now_iso()
        scrape_run_id = f"{SCRAPER_NAME}:{_sha256_text(f'{SCRAPER_NAME}:{started_at}')[:16]}"
        report = SubunitManagementScrapeReport(
            scrape_run_id=scrape_run_id,
            started_at=started_at,
            target_url_count=len(self.targets),
        )

        for target in self.targets:
            source_url = target.source_url
            try:
                html, status_code = self._fetch(source_url)
                fetched_at = utc_now_iso()
                if html is None:
                    report.errors.append(f"Kaynak alınamadı: {source_url} (status={status_code})")
                    page = SubunitManagementPageRecord(
                        snapshot_id=_sha256_text(f"{scrape_run_id}:{source_url}:{status_code}")[:24],
                        scrape_run_id=scrape_run_id,
                        source_url=source_url,
                        source_page_type=target.source_page_type,
                        target_unit_name=target.target_unit_name,
                        parent_unit_name=target.parent_unit_name,
                        department_or_program_name=target.department_or_program_name,
                        scope_type=SCOPE_TYPE,
                        source_birim_id=target.birim_id,
                        http_status=status_code,
                        source_checksum=_sha256_text(f"{source_url}:{status_code}:fetch_failed"),
                        fetched_at=fetched_at,
                        parse_status="failed",
                        record_count=0,
                        ignored_non_management_count=0,
                        raw_text="",
                        raw_html="",
                    )
                    report.pages.append(page)
                    continue

                page, records, ignored, suppressed_duplicates = parse_subunit_management_page(
                    html=html,
                    target=target,
                    source_url=source_url,
                    scrape_run_id=scrape_run_id,
                    http_status=status_code,
                    fetched_at=fetched_at,
                )
                report.pages.append(page)
                report.records.extend(records)
                report.ignored_non_management_records.extend(ignored)
                report.duplicate_suppressed_records.extend(suppressed_duplicates)
            except Exception as exc:  # noqa: BLE001 - raporlayıp diğer allowlist URL'lerine devam et
                logger.exception("Alt birim yönetim kaynağı işlenemedi: %s", source_url)
                report.errors.append(f"{source_url}: {exc}")

        report.finished_at = utc_now_iso()
        report.validation_report = build_validation_report(report)
        report.success = not report.errors and report.validation_report.get("failed_count", 0) == 0

        if write_db and not dry_run:
            report.import_summary = self.write_report_to_database(report)
        else:
            report.import_summary = {
                "dry_run": True,
                "write_db": bool(write_db),
                "pages": len(report.pages),
                "total_found": report.validation_report.get("total_found", len(report.records)),
                "records": len(report.records),
                "db_candidate_records": report.validation_report.get("db_candidate_count", 0),
                "excluded_out_of_scope_records": report.validation_report.get("excluded_out_of_scope_count", 0),
                "valid_records": report.validation_report.get("valid_count", 0),
                "partial_records": report.validation_report.get("partial_count", 0),
                "valid_db_candidate_records": report.validation_report.get("valid_db_candidate_count", 0),
                "partial_db_candidate_records": report.validation_report.get("partial_db_candidate_count", 0),
                "needs_review_records": report.validation_report.get("needs_review_count", 0),
                "ignored_non_management_records": report.validation_report.get("ignored_non_management_count", 0),
                "duplicate_suppressed_records": report.validation_report.get("duplicate_suppressed_count", 0),
                "note": "DB yazımı yapılmadı.",
            }

        self._write_json(report_json, report.to_dict())
        self._write_json(validation_report_json, report.validation_report)
        self._write_json(import_summary_json, report.import_summary)
        return report

    def write_report_to_database(self, report: SubunitManagementScrapeReport) -> dict[str, Any]:
        from app.repositories.subunit_management_repository import SubunitManagementRepository

        repo = SubunitManagementRepository()
        missing_tables = repo.missing_required_tables()
        if missing_tables:
            raise RuntimeError(
                "Subunit management DB tabloları mevcut değil; yazım durduruldu. "
                "Önce database/init.sql içindeki subunit_management_* şemasını onaylı migration ile uygulayın. "
                f"Eksik tablolar: {', '.join(missing_tables)}"
            )

        candidate_records = db_candidate_records(report.records)
        repo.upsert_scrape_run({
            "scrape_run_id": report.scrape_run_id,
            "scraper_name": report.scraper_name,
            "metadata_version": report.metadata_version,
            "scope_type": report.scope_type,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "status": "success" if report.success else "partial",
            "validation_status": "valid" if report.validation_report.get("db_write_ready") else "needs_review",
            "target_url_count": report.target_url_count,
            "processed_url_count": len(report.pages),
            "record_count": len(candidate_records),
            "valid_count": report.validation_report.get("valid_db_candidate_count", 0),
            "partial_count": report.validation_report.get("partial_db_candidate_count", 0),
            "needs_review_count": report.validation_report.get("needs_review_count", 0),
            "ignored_non_management_count": report.validation_report.get("ignored_non_management_count", 0),
            "summary": report.validation_report,
        })

        target_ids: dict[str, str] = {}
        for target in self.targets:
            target_ids[target.source_url] = repo.upsert_target({
                "target_unit_name": target.target_unit_name,
                "target_unit_name_normalized": normalize_for_match(target.target_unit_name),
                "parent_unit_name": target.parent_unit_name,
                "department_or_program_name": target.department_or_program_name,
                "department_or_program_name_normalized": normalize_for_match(target.department_or_program_name),
                "unit_type": target.unit_type,
                "scope_type": SCOPE_TYPE,
                "source_url": target.source_url,
                "source_page_type": target.source_page_type,
                "source_birim_id": target.birim_id,
                "aliases": list(target.aliases),
                "last_checked_at": report.finished_at,
            })
            repo.upsert_aliases(
                target_id=target_ids[target.source_url],
                canonical_name=target.target_unit_name,
                aliases=[
                    target.target_unit_name,
                    target.department_or_program_name,
                    *(target.aliases or ()),
                ],
                source_url=target.source_url,
            )

        counts = {
            "dry_run": False,
            "scrape_run_id": report.scrape_run_id,
            "targets": len(target_ids),
            "pages": 0,
            "records_upserted": 0,
            "records_skipped_needs_review": 0,
            "records_skipped_out_of_scope": report.validation_report.get("excluded_out_of_scope_count", 0),
            "records_deactivated": 0,
            "parse_status_counts": {},
        }

        for page in report.pages:
            target_id = target_ids.get(page.source_url)
            repo.upsert_page(asdict(page), target_id)
            counts["pages"] += 1
            status_counts = counts["parse_status_counts"]
            status_counts[page.parse_status] = status_counts.get(page.parse_status, 0) + 1

        seen_record_ids_by_source: dict[str, list[str]] = {}
        counts["records_skipped_needs_review"] = report.validation_report.get("needs_review_count", 0)
        for record in candidate_records:
            target_id = target_ids.get(record.source_url)
            if not target_id:
                continue
            record_id = repo.upsert_record(asdict(record), target_id)
            seen_record_ids_by_source.setdefault(record.source_url, []).append(record_id)
            counts["records_upserted"] += 1

        ok_sources = {
            page.source_url
            for page in report.pages
            if page.parse_status in {"valid", "partial"}
        }
        for source_url in ok_sources:
            counts["records_deactivated"] += repo.deactivate_records_not_seen(
                source_url=source_url,
                seen_record_ids=seen_record_ids_by_source.get(source_url, []),
            )

        return counts

    def _fetch(self, url: str) -> tuple[str | None, int | None]:
        if not is_allowed_subunit_management_url(url):
            raise ValueError(f"Alt birim yönetim allowlist dışında URL reddedildi: {url}")

        for attempt in range(1, MAX_RETRIES + 1):
            self._rate_limit()
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request_at = time.time()
                status_code = int(getattr(response, "status_code", 200))
                if status_code >= 500 or status_code in {408, 429}:
                    raise requests.RequestException(f"Geçici HTTP hata: {status_code}")
                if 400 <= status_code < 500:
                    return None, status_code
                response.raise_for_status()
                return _decode_response(response), status_code
            except requests.RequestException as exc:
                logger.warning("Alt birim yönetim kaynağı alınamadı (%d/%d): %s - %s", attempt, MAX_RETRIES, url, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(self.retry_delay_seconds * attempt)
        return None, None

    def _rate_limit(self) -> None:
        if not self._last_request_at:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    @staticmethod
    def _write_json(path_value: str | Path | None, payload: dict[str, Any]) -> None:
        if not path_value:
            return
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="GİBTÜ bölüm/program alt birim yönetim dry-run scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret")
    parser.add_argument("--write-db", action="store_true", help="Ayrı subunit management tablolarına yaz")
    parser.add_argument("--report-json", default=None, help="Tam raporu JSON dosyasına yaz")
    parser.add_argument("--validation-report-json", default=None, help="Validation raporunu JSON dosyasına yaz")
    parser.add_argument("--import-summary-json", default=None, help="Import summary dosyasını yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = SubunitManagementScraper()
    report = scraper.scrape(
        dry_run=args.dry_run or not args.write_db,
        write_db=args.write_db,
        report_json=args.report_json,
        validation_report_json=args.validation_report_json,
        import_summary_json=args.import_summary_json,
    )
    logger.info("Alt birim yönetim scrape raporu: %s", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
