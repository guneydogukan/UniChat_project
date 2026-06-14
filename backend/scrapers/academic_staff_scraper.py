"""
GİBTÜ hedefli akademik veri scraper'ı.

Bu modül genel crawler değildir. Yalnızca akademik birim, akademik personel,
yönetim, iletişim, PBS kişi profili ve YÖK Akademik profil eşleştirme
verileri için kontrollü hedef URL'leri işler. PDF, duyuru, haber, rapor ve
arşiv kaynakları bilinçli olarak kapsam dışıdır.
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
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Tag

try:
    from haystack import Document
except ImportError:  # pragma: no cover - hafif test ortamı için
    @dataclass
    class Document:  # type: ignore[no-redef]
        content: str
        meta: dict[str, Any]
        id: str | None = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 - Windows stdout UTF-8

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
PBS_HOST = "pbs.gibtu.edu.tr"
YOK_AKADEMIK_HOST = "akademik.yok.gov.tr"
SCRAPER_NAME = "academic_staff_scraper"
METADATA_VERSION = "academic_staff.v1"
UNIVERSITY_NAME = "Gaziantep İslam Bilim ve Teknoloji Üniversitesi"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 1.0

ALLOWED_GIBTU_PAGE_NAMES: frozenset[str] = frozenset({
    "birim.aspx",
    "birimakademikbirimler.aspx",
    "birimakademikpersonel.aspx",
    "birimyonetim.aspx",
    "birimiletisim.aspx",
})

RECTORATE_URLS: tuple[str, ...] = (
    f"{BASE_URL}/Rektor",
    f"{BASE_URL}/RektorYardimcilari",
    f"{BASE_URL}/RektorDanismanlari",
    f"{BASE_URL}/Birim.aspx?id=3",
)

TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"prof\.?\s*dr\.?", "Prof. Dr."),
    (r"doç\.?\s*dr\.?|doc\.?\s*dr\.?", "Doç. Dr."),
    (r"dr\.?\s*öğr\.?\s*üyesi|dr\.?\s*ogr\.?\s*uyesi|doktor\s+öğretim\s+üyesi", "Dr. Öğr. Üyesi"),
    (r"öğr\.?\s*gör\.?\s*dr\.?|ogr\.?\s*gor\.?\s*dr\.?", "Öğr. Gör. Dr."),
    (r"öğr\.?\s*gör\.?|ogr\.?\s*gor\.?|öğretim\s+görevlisi", "Öğr. Gör."),
    (r"arş\.?\s*gör\.?\s*dr\.?|araş\.?\s*gör\.?\s*dr\.?|ars\.?\s*gor\.?\s*dr\.?", "Arş. Gör. Dr."),
    (r"arş\.?\s*gör\.?|araş\.?\s*gör\.?|ars\.?\s*gor\.?|araştırma\s+görevlisi", "Arş. Gör."),
)

TITLE_RE = re.compile(
    r"(?P<title>"
    + "|".join(f"(?:{pattern})" for pattern, _ in TITLE_PATTERNS)
    + r")",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")

ROLE_RULES: tuple[tuple[str, str, int], ...] = (
    ("rektor_yardimcisi", "Rektör Yardımcısı", 1),
    ("rektor_danismani", "Rektör Danışmanı", 1),
    ("rektor", "Rektör", 1),
    ("dekan_yardimcisi", "Dekan Yardımcısı", 1),
    ("dekan_vekili", "Dekan Vekili", 1),
    ("dekan", "Dekan", 1),
    ("bolum_baskan_yardimcisi", "Bölüm Başkan Yardımcısı", 1),
    ("bolum_baskani", "Bölüm Başkanı", 1),
    ("mudur_yardimcisi", "Müdür Yardımcısı", 1),
    ("mudur", "Müdür", 1),
    ("koordinator", "Koordinatör", 2),
    ("danisman", "Danışman", 2),
    ("genel_sekreter", "Genel Sekreter", 1),
)


@dataclass(frozen=True)
class TargetUnit:
    unit_name: str
    unit_type: str
    birim_id: int | None = None
    parent_birim_id: int | None = None
    slug: str | None = None
    source_url: str | None = None

    def target_urls(self) -> list[str]:
        if self.birim_id is None:
            return list(RECTORATE_URLS)
        return [
            f"{BASE_URL}/Birim.aspx?id={self.birim_id}",
            f"{BASE_URL}/BirimAkademikBirimler.aspx?id={self.birim_id}",
            f"{BASE_URL}/BirimAkademikPersonel.aspx?id={self.birim_id}",
            f"{BASE_URL}/BirimYonetim.aspx?id={self.birim_id}",
            f"{BASE_URL}/BirimIletisim.aspx?id={self.birim_id}",
        ]


DEFAULT_TARGET_UNITS: tuple[TargetUnit, ...] = (
    TargetUnit("Rektörlük", "rektorluk", slug="rektorluk", source_url=BASE_URL),
    TargetUnit("İlahiyat Fakültesi", "fakulte", 11, slug="ilahiyatfakultesi"),
    TargetUnit("Mühendislik ve Doğa Bilimleri Fakültesi", "fakulte", 15, slug="mdbf"),
    TargetUnit("Elektrik-Elektronik Mühendisliği Bölümü", "bolum", 16, 15, "eemb"),
    TargetUnit("İnşaat Mühendisliği Bölümü", "bolum", 17, 15, "insaat"),
    TargetUnit("Bilgisayar Mühendisliği Bölümü", "bolum", 18, 15, "bmb"),
    TargetUnit("Endüstri Mühendisliği Bölümü", "bolum", 19, 15, "emb"),
    TargetUnit("Tıp Fakültesi", "fakulte", 20, slug="tip"),
    TargetUnit("Sağlık Bilimleri Fakültesi", "fakulte", 21, slug="sbf"),
    TargetUnit("İktisadi İdari ve Sosyal Bilimler Fakültesi", "fakulte", 22, slug="iii"),
    TargetUnit("Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "fakulte", 24, slug="gsmf"),
    TargetUnit("Sağlık Hizmetleri Meslek Yüksekokulu", "myo", 31, slug="shmyo"),
    TargetUnit("Yabancı Diller Yüksekokulu", "yuksekokul", 34, slug="yabancidiller"),
    TargetUnit("Lisansüstü Eğitim Enstitüsü", "enstitu", 35, slug="lisansustu"),
    TargetUnit("Teknik Bilimler Meslek Yüksekokulu", "myo", 36, slug="teknikbilimler"),
)


@dataclass
class UnitRecord:
    unit_name: str
    unit_name_normalized: str
    unit_type: str
    birim_id: int | None = None
    parent_birim_id: int | None = None
    slug: str | None = None
    source_url: str | None = None
    is_active: bool = True
    last_checked_at: str | None = None


@dataclass
class PersonRecord:
    full_name: str
    normalized_name: str
    title: str | None = None
    email: str | None = None
    pbs_profile_url: str | None = None
    source_status: str = "official"
    needs_manual_review: bool = False


@dataclass
class AffiliationRecord:
    person_key: str
    unit_birim_id: int | None
    unit_name_normalized: str
    affiliation_type: str = "academic_staff"
    title: str | None = None
    is_active: bool = True
    source_status: str = "official"
    confidence_status: str = "high"
    confidence_score: float = 0.85
    needs_manual_review: bool = False
    source_url: str | None = None
    evidence_keys: list[str] = field(default_factory=list)
    last_checked_at: str | None = None


@dataclass
class ManagementRoleRecord:
    person_key: str
    unit_birim_id: int | None
    unit_name_normalized: str
    role_name: str
    role_key: str
    source_priority: int = 1
    source_status: str = "official"
    confidence_status: str = "high"
    confidence_score: float = 0.9
    needs_manual_review: bool = False
    source_url: str | None = None
    evidence_keys: list[str] = field(default_factory=list)
    last_checked_at: str | None = None


@dataclass
class ExternalProfileRecord:
    person_key: str
    profile_type: str
    profile_url: str | None = None
    external_id: str | None = None
    match_status: str = "not_resolved"
    confidence_score: float | None = None
    source_url: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)
    last_checked_at: str | None = None


@dataclass
class SourceEvidenceRecord:
    evidence_key: str
    source_url: str
    source_type: str
    source_kind: str
    unit_birim_id: int | None = None
    person_key: str | None = None
    content_hash: str | None = None
    fetched_at: str | None = None
    field_names: list[str] = field(default_factory=list)
    raw_excerpt: str | None = None
    is_accessible: bool = True


@dataclass
class RawSnapshotRecord:
    snapshot_id: str
    scrape_run_id: str
    source_url: str
    source_kind: str
    unit_birim_id: int | None
    http_status: int | None
    content_hash: str
    fetched_at: str
    response_text: str
    parse_status: str
    extracted_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnitStaffSnapshotRecord:
    unit_birim_id: int | None
    unit_name_normalized: str
    source_urls: list[str]
    person_keys: list[str]
    missing_fields: list[str]
    validation_status: str
    last_checked_at: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnitManagementSnapshotRecord:
    unit_birim_id: int | None
    unit_name_normalized: str
    source_urls: list[str]
    role_keys: list[str]
    missing_fields: list[str]
    validation_status: str
    last_checked_at: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AcademicStaffScrapeReport:
    success: bool = False
    scrape_run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    target_unit_count: int = 0
    units: list[UnitRecord] = field(default_factory=list)
    persons: list[PersonRecord] = field(default_factory=list)
    affiliations: list[AffiliationRecord] = field(default_factory=list)
    management_roles: list[ManagementRoleRecord] = field(default_factory=list)
    external_profiles: list[ExternalProfileRecord] = field(default_factory=list)
    source_evidence: list[SourceEvidenceRecord] = field(default_factory=list)
    raw_snapshots: list[RawSnapshotRecord] = field(default_factory=list)
    staff_snapshots: list[UnitStaffSnapshotRecord] = field(default_factory=list)
    management_snapshots: list[UnitManagementSnapshotRecord] = field(default_factory=list)
    answer_documents: list[Document] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["answer_documents"] = [
            {"content": doc.content, "meta": doc.meta, "id": doc.id}
            for doc in self.answer_documents
        ]
        return data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def normalize_person_key(full_name: str, email: str | None = None, pbs_profile_url: str | None = None) -> str:
    if pbs_profile_url:
        return f"pbs:{pbs_profile_url.strip().lower()}"
    if email:
        return f"email:{email.strip().lower()}"
    return f"name:{normalize_for_match(full_name)}"


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_for_match(value)
    for pattern, canonical in TITLE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return canonical
    return " ".join(str(value).split())


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


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
        "script", "style", "noscript", "iframe", "footer", "nav",
        "ul.collapsible", "span.birim-menu", "span#birim-menu-slide",
    ):
        for node in root.select(selector):
            node.decompose()


def is_allowed_academic_url(url: str) -> bool:
    """Bu modülün fetch edebileceği URL kapsamını denetler."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_name = Path(parsed.path.lower()).name

    if host in {"www.gibtu.edu.tr", "gibtu.edu.tr"}:
        if url.rstrip("/") in {item.rstrip("/") for item in RECTORATE_URLS}:
            return True
        if path_name not in ALLOWED_GIBTU_PAGE_NAMES:
            return False
        query = parse_qs(parsed.query)
        return bool(query.get("id", [""])[0])

    if host == PBS_HOST:
        return parsed.scheme in {"http", "https"} and bool(parsed.path.strip("/"))

    if host == YOK_AKADEMIK_HOST:
        return parsed.scheme == "https"

    return False


def source_kind_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if parsed.netloc.lower() == PBS_HOST:
        return "pbs_profile"
    if parsed.netloc.lower() == YOK_AKADEMIK_HOST:
        return "yok_akademik_profile"
    if "birimakademikpersonel.aspx" in path:
        return "unit_staff"
    if "birimyonetim.aspx" in path:
        return "unit_management"
    if "birimakademikbirimler.aspx" in path:
        return "unit_children"
    if "birimiletisim.aspx" in path:
        return "unit_contact"
    if "birim.aspx" in path:
        return "unit_home"
    if "rektor" in path:
        return "rectorate_management"
    return "unknown"


def _extract_title_and_name(text: str) -> tuple[str | None, str | None]:
    text = _single_line(text)
    match = TITLE_RE.search(text)
    if not match:
        return None, None

    title = normalize_title(match.group("title"))
    rest = text[match.end():]
    rest = EMAIL_RE.sub(" ", rest)
    rest = re.split(
        r"\b(Bölüm Başkanı|Bölüm Başkan Yardımcısı|Dekan|Dekan Vekili|Dekan Yardımcısı|"
        r"Rektör|Rektör Yardımcısı|Rektör Danışmanı|Müdür|Müdür Yardımcısı|Koordinatör|Danışman)\b",
        rest,
        flags=re.IGNORECASE,
    )[0]
    rest = re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü'\- ]+", " ", rest)
    words = [word.strip(" -") for word in rest.split() if len(word.strip(" -")) > 1]
    if len(words) < 2:
        return title, None
    return title, " ".join(words[:4]).strip()


def _extract_pbs_links(root: Tag, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for anchor in root.find_all("a", href=True):
        href = urljoin(base_url, anchor.get("href", ""))
        if urlparse(href).netloc.lower() != PBS_HOST:
            continue
        text = _single_line(anchor.get_text(" ", strip=True))
        context = _single_line(anchor.find_parent().get_text(" ", strip=True) if anchor.find_parent() else text)
        links.append((href, context or text))
    return links


def _email_near_text(text: str) -> str | None:
    match = EMAIL_RE.search(text or "")
    return match.group(0).lower() if match else None


def parse_staff_page(html: str, unit: UnitRecord, source_url: str, checked_at: str | None = None) -> list[PersonRecord]:
    """Birim akademik personel sayfasından kişi kayıtları çıkarır."""
    checked_at = checked_at or utc_now_iso()
    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)

    people_by_key: dict[str, PersonRecord] = {}
    text = root.get_text("\n", strip=True)
    lines = [_single_line(line) for line in text.splitlines() if _single_line(line)]
    pbs_links = _extract_pbs_links(root, source_url)

    for href, context in pbs_links:
        title, name = _extract_title_and_name(context)
        if not name:
            continue
        email = _email_near_text(context)
        key = normalize_person_key(name, email, href)
        people_by_key[key] = PersonRecord(
            full_name=name,
            normalized_name=normalize_for_match(name),
            title=title,
            email=email,
            pbs_profile_url=href,
        )

    for line in lines:
        title, name = _extract_title_and_name(line)
        if not name:
            continue
        email = _email_near_text(line)
        pbs_profile_url = None
        for href, context in pbs_links:
            if normalize_for_match(name) in normalize_for_match(context):
                pbs_profile_url = href
                break
        key = normalize_person_key(name, email, pbs_profile_url)
        people_by_key.setdefault(
            key,
            PersonRecord(
                full_name=name,
                normalized_name=normalize_for_match(name),
                title=title,
                email=email,
                pbs_profile_url=pbs_profile_url,
            ),
        )

    return list(people_by_key.values())


def normalize_role(text: str) -> tuple[str, str, int] | None:
    normalized = normalize_for_match(text)
    if "bolum baskan yardimcisi" in normalized:
        return "bolum_baskan_yardimcisi", "Bölüm Başkan Yardımcısı", 1
    if "bolum baskani" in normalized:
        return "bolum_baskani", "Bölüm Başkanı", 1
    if "dekan yardimcisi" in normalized:
        return "dekan_yardimcisi", "Dekan Yardımcısı", 1
    if "dekan vekili" in normalized:
        return "dekan_vekili", "Dekan Vekili", 1
    for key, label, priority in ROLE_RULES:
        if normalize_for_match(label) in normalized:
            return key, label, priority
    return None


def parse_management_page(
    html: str,
    unit: UnitRecord,
    source_url: str,
    checked_at: str | None = None,
) -> tuple[list[PersonRecord], list[ManagementRoleRecord]]:
    """Birim yönetim sayfasından kişi ve rol ilişkilerini çıkarır."""
    checked_at = checked_at or utc_now_iso()
    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)

    people_by_key: dict[str, PersonRecord] = {}
    roles: list[ManagementRoleRecord] = []
    pbs_links = _extract_pbs_links(root, source_url)
    lines = [_single_line(line) for line in root.get_text("\n", strip=True).splitlines()]

    for href, context in pbs_links:
        lines.append(context)

    seen_role_keys: set[str] = set()
    for line in lines:
        if not line:
            continue
        role_info = normalize_role(line)
        if not role_info:
            continue
        role_key, role_name, source_priority = role_info
        title, name = _extract_title_and_name(line)
        if not name:
            continue
        email = _email_near_text(line)
        pbs_profile_url = None
        for href, context in pbs_links:
            if normalize_for_match(name) in normalize_for_match(context):
                pbs_profile_url = href
                break
        person_key = normalize_person_key(name, email, pbs_profile_url)
        people_by_key.setdefault(
            person_key,
            PersonRecord(
                full_name=name,
                normalized_name=normalize_for_match(name),
                title=title,
                email=email,
                pbs_profile_url=pbs_profile_url,
            ),
        )
        unique_role = f"{person_key}:{role_key}:{source_url}"
        if unique_role in seen_role_keys:
            continue
        seen_role_keys.add(unique_role)
        roles.append(
            ManagementRoleRecord(
                person_key=person_key,
                unit_birim_id=unit.birim_id,
                unit_name_normalized=unit.unit_name_normalized,
                role_name=role_name,
                role_key=role_key,
                source_priority=source_priority,
                source_url=source_url,
                last_checked_at=checked_at,
            )
        )

    return list(people_by_key.values()), roles


def parse_pbs_profile(
    html: str,
    person: PersonRecord,
    source_url: str,
    checked_at: str | None = None,
) -> tuple[PersonRecord, list[ExternalProfileRecord]]:
    """PBS profilinden e-posta, unvan ve YÖK ID/URL sinyallerini çıkarır."""
    checked_at = checked_at or utc_now_iso()
    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)
    text = root.get_text("\n", strip=True)

    title = person.title
    title_match = TITLE_RE.search(text)
    if title_match:
        title = normalize_title(title_match.group("title"))

    email = person.email or _email_near_text(text)
    yok_id = None
    yok_id_match = re.search(r"YÖK\s*(?:Araştırmacı|Akademik)?\s*(?:ID|No)[:\s]*([0-9]+)", text, re.IGNORECASE)
    if yok_id_match:
        yok_id = yok_id_match.group(1)

    yok_url = None
    for anchor in root.find_all("a", href=True):
        href = urljoin(source_url, anchor.get("href", ""))
        if urlparse(href).netloc.lower() == YOK_AKADEMIK_HOST:
            yok_url = href
            break

    enriched = PersonRecord(
        full_name=person.full_name,
        normalized_name=person.normalized_name,
        title=title,
        email=email,
        pbs_profile_url=person.pbs_profile_url or source_url,
        source_status="official_pbs",
        needs_manual_review=person.needs_manual_review,
    )
    profiles = [
        ExternalProfileRecord(
            person_key=normalize_person_key(enriched.full_name, enriched.email, enriched.pbs_profile_url),
            profile_type="pbs",
            profile_url=enriched.pbs_profile_url,
            match_status="resolved",
            confidence_score=0.95,
            source_url=source_url,
            last_checked_at=checked_at,
        )
    ]
    profiles.append(
        ExternalProfileRecord(
            person_key=normalize_person_key(enriched.full_name, enriched.email, enriched.pbs_profile_url),
            profile_type="yok_akademik",
            profile_url=yok_url,
            external_id=yok_id,
            match_status="resolved" if yok_url else "not_resolved",
            confidence_score=0.8 if yok_url else None,
            source_url=source_url,
            raw_data={"yok_researcher_id": yok_id} if yok_id else {},
            last_checked_at=checked_at,
        )
    )
    return enriched, profiles


class AcademicStaffScraper:
    """Hedefli akademik kadro/yönetim pipeline'ı."""

    def __init__(
        self,
        target_units: tuple[TargetUnit, ...] = DEFAULT_TARGET_UNITS,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
    ) -> None:
        self.target_units = target_units
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; UniChatAcademicStaffScraper/1.0; +https://www.gibtu.edu.tr)",
        })
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self._last_request_at = 0.0

    def scrape(
        self,
        dry_run: bool = True,
        report_json: str | Path | None = None,
        write_db: bool = False,
    ) -> AcademicStaffScrapeReport:
        started_at = utc_now_iso()
        run_seed = f"{SCRAPER_NAME}:{started_at}"
        scrape_run_id = f"{SCRAPER_NAME}:{_sha256_text(run_seed)[:16]}"
        report = AcademicStaffScrapeReport(
            scrape_run_id=scrape_run_id,
            started_at=started_at,
            target_unit_count=len(self.target_units),
        )

        unit_by_birim_id = {
            target.birim_id: self._unit_record(target, started_at)
            for target in self.target_units
            if target.birim_id is not None
        }
        unit_by_name = {
            normalize_for_match(target.unit_name): self._unit_record(target, started_at)
            for target in self.target_units
        }
        report.units = list({unit.unit_name_normalized: unit for unit in unit_by_name.values()}.values())

        people_by_key: dict[str, PersonRecord] = {}
        pbs_urls: set[str] = set()

        for target in self.target_units:
            unit = self._unit_record(target, started_at)
            staff_people: list[PersonRecord] = []
            unit_roles: list[ManagementRoleRecord] = []
            source_urls: list[str] = []
            management_urls: list[str] = []

            for url in target.target_urls():
                if not is_allowed_academic_url(url):
                    report.validation_results.append({
                        "severity": "warning",
                        "code": "blocked_url",
                        "message": f"Hedef dışı URL reddedildi: {url}",
                    })
                    continue
                source_kind = source_kind_from_url(url)
                html, status_code = self._fetch(url)
                fetched_at = utc_now_iso()
                if html is None:
                    report.errors.append(f"Kaynak alınamadı: {url}")
                    report.raw_snapshots.append(self._snapshot(scrape_run_id, url, source_kind, unit, "", fetched_at, status_code, "fetch_failed"))
                    continue

                report.raw_snapshots.append(
                    self._snapshot(scrape_run_id, url, source_kind, unit, html, fetched_at, status_code, "fetched")
                )
                evidence_key = f"{url}:{_sha256_text(html)[:12]}"
                report.source_evidence.append(
                    SourceEvidenceRecord(
                        evidence_key=evidence_key,
                        source_url=url,
                        source_type="web",
                        source_kind=source_kind,
                        unit_birim_id=unit.birim_id,
                        content_hash=_sha256_text(html),
                        fetched_at=fetched_at,
                        field_names=self._fields_for_source_kind(source_kind),
                        raw_excerpt=_single_line(BeautifulSoup(html, "lxml").get_text(" ", strip=True))[:500],
                    )
                )

                if source_kind == "unit_staff":
                    parsed_people = parse_staff_page(html, unit, url, fetched_at)
                    staff_people.extend(parsed_people)
                    source_urls.append(url)
                    for person in parsed_people:
                        key = normalize_person_key(person.full_name, person.email, person.pbs_profile_url)
                        people_by_key[key] = person
                        if person.pbs_profile_url and is_allowed_academic_url(person.pbs_profile_url):
                            pbs_urls.add(person.pbs_profile_url)
                        report.affiliations.append(
                            AffiliationRecord(
                                person_key=key,
                                unit_birim_id=unit.birim_id,
                                unit_name_normalized=unit.unit_name_normalized,
                                title=person.title,
                                source_url=url,
                                evidence_keys=[evidence_key],
                                last_checked_at=fetched_at,
                            )
                        )
                elif source_kind in {"unit_management", "rectorate_management"}:
                    parsed_people, roles = parse_management_page(html, unit, url, fetched_at)
                    unit_roles.extend(roles)
                    management_urls.append(url)
                    for person in parsed_people:
                        key = normalize_person_key(person.full_name, person.email, person.pbs_profile_url)
                        people_by_key[key] = person
                        if person.pbs_profile_url and is_allowed_academic_url(person.pbs_profile_url):
                            pbs_urls.add(person.pbs_profile_url)
                    for role in roles:
                        role.evidence_keys = [evidence_key]
                        report.management_roles.append(role)

            report.staff_snapshots.append(
                UnitStaffSnapshotRecord(
                    unit_birim_id=unit.birim_id,
                    unit_name_normalized=unit.unit_name_normalized,
                    source_urls=source_urls,
                    person_keys=[
                        normalize_person_key(person.full_name, person.email, person.pbs_profile_url)
                        for person in staff_people
                    ],
                    missing_fields=[] if staff_people or unit.unit_type == "rektorluk" else ["staff"],
                    validation_status="valid" if staff_people or unit.unit_type == "rektorluk" else "empty_source",
                    last_checked_at=started_at,
                )
            )
            report.management_snapshots.append(
                UnitManagementSnapshotRecord(
                    unit_birim_id=unit.birim_id,
                    unit_name_normalized=unit.unit_name_normalized,
                    source_urls=management_urls,
                    role_keys=[f"{role.person_key}:{role.role_key}" for role in unit_roles],
                    missing_fields=[] if unit_roles else ["management_roles"],
                    validation_status="valid" if unit_roles else "needs_review",
                    last_checked_at=started_at,
                )
            )

        self._enrich_from_pbs(report, people_by_key, pbs_urls)
        report.persons = list(people_by_key.values())
        report.answer_documents = self._build_answer_documents(report)
        report.finished_at = utc_now_iso()
        report.success = not report.errors

        if report_json:
            path = Path(report_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        if write_db and not dry_run:
            self.write_report_to_database(report)

        return report

    def write_report_to_database(self, report: AcademicStaffScrapeReport) -> dict[str, int]:
        """Scrape raporunu structured DB tablolarına yazar."""
        from app.repositories.academic_repository import AcademicRepository

        repo = AcademicRepository()
        repo.ensure_schema()
        university_id = repo.upsert_university(last_checked_at=report.finished_at)
        repo.upsert_scrape_run({
            "scrape_run_id": report.scrape_run_id,
            "scraper_name": report.scraper_name,
            "metadata_version": report.metadata_version,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "status": "success" if report.success else "partial",
            "validation_status": "valid" if report.success else "needs_review",
            "target_unit_count": report.target_unit_count,
            "source_count": len(report.source_evidence),
            "person_count": len(report.persons),
            "affiliation_count": len(report.affiliations),
            "management_role_count": len(report.management_roles),
            "candidate_count": sum(1 for p in report.persons if p.source_status == "candidate_from_yok"),
            "summary": {
                "errors": report.errors,
                "validation_results": report.validation_results,
            },
        })

        unit_ids_by_key: dict[str, str] = {}
        unit_ids_by_birim: dict[int, str] = {}
        ordered_units = sorted(report.units, key=lambda item: (item.parent_birim_id is not None, item.unit_name))
        for unit in ordered_units:
            parent_id = unit_ids_by_birim.get(unit.parent_birim_id or -1)
            unit_id = repo.upsert_unit(asdict(unit), university_id, parent_unit_id=parent_id)
            unit_ids_by_key[unit.unit_name_normalized] = unit_id
            if unit.birim_id is not None:
                unit_ids_by_birim[unit.birim_id] = unit_id

        person_ids_by_key: dict[str, str] = {}
        for person in report.persons:
            key = normalize_person_key(person.full_name, person.email, person.pbs_profile_url)
            person_ids_by_key[key] = repo.upsert_person(asdict(person))

        evidence_ids_by_key: dict[str, str] = {}
        for evidence in report.source_evidence:
            unit_id = unit_ids_by_birim.get(evidence.unit_birim_id or -1)
            person_id = person_ids_by_key.get(evidence.person_key or "")
            evidence_payload = asdict(evidence)
            evidence_payload["scrape_run_id"] = report.scrape_run_id
            evidence_ids_by_key[evidence.evidence_key] = repo.insert_evidence(evidence_payload, unit_id, person_id)

        counts = {
            "affiliations": 0,
            "management_roles": 0,
            "external_profiles": 0,
            "raw_snapshots": 0,
            "staff_snapshots": 0,
            "management_snapshots": 0,
        }
        for affiliation in report.affiliations:
            person_id = person_ids_by_key.get(affiliation.person_key)
            unit_id = unit_ids_by_birim.get(affiliation.unit_birim_id or -1) or unit_ids_by_key.get(affiliation.unit_name_normalized)
            if not person_id or not unit_id:
                continue
            payload = asdict(affiliation)
            payload["person_id"] = person_id
            payload["unit_id"] = unit_id
            payload["evidence_ids"] = [evidence_ids_by_key[key] for key in affiliation.evidence_keys if key in evidence_ids_by_key]
            repo.upsert_affiliation(payload)
            counts["affiliations"] += 1

        for role in report.management_roles:
            person_id = person_ids_by_key.get(role.person_key)
            unit_id = unit_ids_by_birim.get(role.unit_birim_id or -1) or unit_ids_by_key.get(role.unit_name_normalized)
            if not person_id or not unit_id:
                continue
            payload = asdict(role)
            payload["person_id"] = person_id
            payload["unit_id"] = unit_id
            payload["evidence_ids"] = [evidence_ids_by_key[key] for key in role.evidence_keys if key in evidence_ids_by_key]
            repo.upsert_management_role(payload)
            counts["management_roles"] += 1

        for profile in report.external_profiles:
            person_id = person_ids_by_key.get(profile.person_key)
            if not person_id:
                continue
            payload = asdict(profile)
            payload["person_id"] = person_id
            repo.upsert_external_profile(payload)
            counts["external_profiles"] += 1

        for snapshot in report.raw_snapshots:
            unit_id = unit_ids_by_birim.get(snapshot.unit_birim_id or -1)
            repo.insert_raw_snapshot(asdict(snapshot), unit_id)
            counts["raw_snapshots"] += 1

        for snapshot in report.staff_snapshots:
            unit_id = unit_ids_by_birim.get(snapshot.unit_birim_id or -1) or unit_ids_by_key.get(snapshot.unit_name_normalized)
            if not unit_id:
                continue
            person_ids = [
                person_ids_by_key[key]
                for key in snapshot.person_keys
                if key in person_ids_by_key
            ]
            payload = asdict(snapshot)
            payload["scrape_run_id"] = report.scrape_run_id
            payload["staff_count"] = len(person_ids)
            payload["person_ids"] = person_ids
            repo.upsert_unit_staff_snapshot(payload, unit_id)
            counts["staff_snapshots"] += 1

        for snapshot in report.management_snapshots:
            unit_id = unit_ids_by_birim.get(snapshot.unit_birim_id or -1) or unit_ids_by_key.get(snapshot.unit_name_normalized)
            if not unit_id:
                continue
            payload = asdict(snapshot)
            payload["scrape_run_id"] = report.scrape_run_id
            payload["role_count"] = len(snapshot.role_keys)
            payload["role_ids"] = snapshot.role_keys
            repo.upsert_unit_management_snapshot(payload, unit_id)
            counts["management_snapshots"] += 1

        if report.answer_documents:
            from app.ingestion.loader import ingest_documents
            from haystack.document_stores.types import DuplicatePolicy

            counts["answer_chunks"] = ingest_documents(report.answer_documents, policy=DuplicatePolicy.OVERWRITE)

        return counts

    def _fetch(self, url: str) -> tuple[str | None, int | None]:
        if not is_allowed_academic_url(url):
            raise ValueError(f"Akademik veri kapsamı dışında URL reddedildi: {url}")

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
                if not response.encoding or response.encoding.upper() in {"ISO-8859-1", "ASCII"}:
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text, status_code
            except requests.RequestException as exc:
                logger.warning("Akademik kaynak alınamadı (%d/%d): %s - %s", attempt, MAX_RETRIES, url, exc)
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
    def _unit_record(target: TargetUnit, checked_at: str) -> UnitRecord:
        source_url = target.source_url or (
            f"{BASE_URL}/Birim.aspx?id={target.birim_id}" if target.birim_id is not None else BASE_URL
        )
        return UnitRecord(
            unit_name=target.unit_name,
            unit_name_normalized=normalize_for_match(target.unit_name),
            unit_type=target.unit_type,
            birim_id=target.birim_id,
            parent_birim_id=target.parent_birim_id,
            slug=target.slug,
            source_url=source_url,
            last_checked_at=checked_at,
        )

    @staticmethod
    def _snapshot(
        scrape_run_id: str,
        url: str,
        source_kind: str,
        unit: UnitRecord,
        html: str,
        fetched_at: str,
        status_code: int | None,
        parse_status: str,
    ) -> RawSnapshotRecord:
        content_hash = _sha256_text(html or f"{url}:{status_code}:{parse_status}")
        snapshot_id = _sha256_text(f"{scrape_run_id}:{url}:{content_hash}")[:24]
        return RawSnapshotRecord(
            snapshot_id=snapshot_id,
            scrape_run_id=scrape_run_id,
            source_url=url,
            source_kind=source_kind,
            unit_birim_id=unit.birim_id,
            http_status=status_code,
            content_hash=content_hash,
            fetched_at=fetched_at,
            response_text=html,
            parse_status=parse_status,
            extracted_fields={"source_kind": source_kind},
        )

    @staticmethod
    def _fields_for_source_kind(source_kind: str) -> list[str]:
        mapping = {
            "unit_staff": ["person.full_name", "person.title", "person.email", "person.pbs_profile_url"],
            "unit_management": ["management_role.role_name", "person.full_name", "person.title"],
            "rectorate_management": ["management_role.role_name", "person.full_name", "person.title"],
            "unit_home": ["unit.unit_name", "unit.unit_type"],
            "unit_children": ["unit.parent_unit", "unit.child_units"],
            "unit_contact": ["unit.contact"],
        }
        return mapping.get(source_kind, [])

    def _enrich_from_pbs(
        self,
        report: AcademicStaffScrapeReport,
        people_by_key: dict[str, PersonRecord],
        pbs_urls: set[str],
    ) -> None:
        for pbs_url in sorted(pbs_urls):
            html, status_code = self._fetch(pbs_url)
            fetched_at = utc_now_iso()
            person = next(
                (p for p in people_by_key.values() if p.pbs_profile_url == pbs_url),
                None,
            )
            if not person:
                continue
            if html is None:
                report.external_profiles.append(
                    ExternalProfileRecord(
                        person_key=normalize_person_key(person.full_name, person.email, person.pbs_profile_url),
                        profile_type="pbs",
                        profile_url=pbs_url,
                        match_status="not_checked",
                        source_url=pbs_url,
                        last_checked_at=fetched_at,
                    )
                )
                continue

            report.raw_snapshots.append(
                self._snapshot(report.scrape_run_id, pbs_url, "pbs_profile", UnitRecord(
                    unit_name="", unit_name_normalized="", unit_type="", last_checked_at=fetched_at
                ), html, fetched_at, status_code, "fetched")
            )
            enriched, profiles = parse_pbs_profile(html, person, pbs_url, fetched_at)
            old_key = normalize_person_key(person.full_name, person.email, person.pbs_profile_url)
            new_key = normalize_person_key(enriched.full_name, enriched.email, enriched.pbs_profile_url)
            people_by_key.pop(old_key, None)
            people_by_key[new_key] = enriched
            for affiliation in report.affiliations:
                if affiliation.person_key == old_key:
                    affiliation.person_key = new_key
                    affiliation.confidence_status = "very_high"
                    affiliation.confidence_score = 0.95
            for role in report.management_roles:
                if role.person_key == old_key:
                    role.person_key = new_key
                    role.confidence_status = "very_high"
                    role.confidence_score = 0.95
            for snapshot in report.staff_snapshots:
                snapshot.person_keys = [
                    new_key if person_key == old_key else person_key
                    for person_key in snapshot.person_keys
                ]
            for snapshot in report.management_snapshots:
                snapshot.role_keys = [
                    role_key.replace(f"{old_key}:", f"{new_key}:", 1)
                    if role_key.startswith(f"{old_key}:")
                    else role_key
                    for role_key in snapshot.role_keys
                ]
            report.external_profiles.extend(profiles)

    @staticmethod
    def _build_answer_documents(report: AcademicStaffScrapeReport) -> list[Document]:
        units = {unit.unit_name_normalized: unit for unit in report.units}
        persons = {
            normalize_person_key(person.full_name, person.email, person.pbs_profile_url): person
            for person in report.persons
        }
        documents: list[Document] = []

        affiliations_by_unit: dict[str, list[AffiliationRecord]] = {}
        for affiliation in report.affiliations:
            affiliations_by_unit.setdefault(affiliation.unit_name_normalized, []).append(affiliation)

        roles_by_unit: dict[str, list[ManagementRoleRecord]] = {}
        for role in report.management_roles:
            roles_by_unit.setdefault(role.unit_name_normalized, []).append(role)

        for unit_key, unit in units.items():
            lines = [f"## {unit.unit_name} akademik veri özeti"]
            staff = affiliations_by_unit.get(unit_key, [])
            if staff:
                lines.append("\nAkademik kadro:")
                for affiliation in sorted(staff, key=lambda item: persons.get(item.person_key, PersonRecord("", "")).full_name):
                    person = persons.get(affiliation.person_key)
                    if not person:
                        continue
                    lines.append(
                        f"- {person.title or affiliation.title or ''} {person.full_name}".strip()
                        + f" | E-posta: {person.email or 'null'}"
                        + f" | PBS: {person.pbs_profile_url or 'null'}"
                        + f" | Güven: {affiliation.confidence_status}"
                    )
            roles = roles_by_unit.get(unit_key, [])
            if roles:
                lines.append("\nYönetim rolleri:")
                for role in sorted(roles, key=lambda item: (item.source_priority, item.role_name)):
                    person = persons.get(role.person_key)
                    if not person:
                        continue
                    lines.append(
                        f"- {role.role_name}: {person.title or ''} {person.full_name}".strip()
                        + f" | Kaynak: {role.source_url or 'null'}"
                        + f" | Güven: {role.confidence_status}"
                    )
            if len(lines) == 1:
                continue
            content = "\n".join(lines)
            source_url = unit.source_url or BASE_URL
            source_id = f"academic_staff_answer/{unit.unit_name_normalized}"
            documents.append(
                Document(
                    id=_sha256_text(source_id),
                    content=content,
                    meta={
                        "metadata_version": METADATA_VERSION,
                        "category": "akademik_kadro",
                        "source_url": source_url,
                        "source_public_url": source_url,
                        "source_type": "web",
                        "source_id": source_id,
                        "last_updated": report.finished_at or utc_now_iso(),
                        "title": f"{unit.unit_name} — Akademik Kadro ve Yönetim Özeti",
                        "doc_kind": "personel",
                        "language": "tr",
                        "department": unit.unit_name,
                        "contact_unit": unit.unit_name,
                        "scraper_name": SCRAPER_NAME,
                    },
                )
            )
        return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="GİBTÜ hedefli akademik kadro/yönetim scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret")
    parser.add_argument("--write-db", action="store_true", help="Structured DB ve RAG answer document yaz")
    parser.add_argument("--report-json", default=None, help="Raporu JSON dosyasına yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = AcademicStaffScraper()
    report = scraper.scrape(
        dry_run=args.dry_run or not args.write_db,
        write_db=args.write_db,
        report_json=args.report_json,
    )
    logger.info("Akademik kadro scrape raporu: %s", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
