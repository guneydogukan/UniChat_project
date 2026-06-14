"""
GİBTÜ BirimYonetim.aspx sayfaları için izole DB-first scraper.

Bu modül genel crawler değildir. Yalnızca aşağıdaki allowlist'teki resmi
BirimYonetim.aspx sayfalarını işler ve yönetim bilgisini normalize kayıtlara
ayırır. PBS/blog profil linkleri sadece kaynak sayfada göründüğü kadarıyla
kaydedilir; ek profil fetch'i yapılmaz.
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
SCRAPER_NAME = "unit_management_scraper"
METADATA_VERSION = "unit_management.v1"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 1.0

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


@dataclass(frozen=True)
class UnitManagementTarget:
    unit_name: str
    unit_type: str
    source_url: str
    birim_id: int
    aliases: tuple[str, ...] = ()


DEFAULT_TARGET_UNITS: tuple[UnitManagementTarget, ...] = (
    UnitManagementTarget(
        "İlahiyat Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=11",
        11,
        ("if", "İ.F.", "ilahiyat", "ilahiyat fak", "ilahiyat fakültesi"),
    ),
    UnitManagementTarget(
        "Mühendislik ve Doğa Bilimleri Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=15",
        15,
        (
            "mdbf",
            "M.D.B.F.",
            "mdb",
            "M.D.B.",
            "MDB Fak",
            "müh doğa bil",
            "mühendislik",
            "mühendislik fak",
            "mühendislik fakültesi",
            "mühendislik doğa bilimleri",
            "mühendislik doğa bilimleri fak",
            "mühendislik ve doğa bilimleri",
            "mühendislik ve doğa bilimleri fak",
            "doğa bilimleri",
        ),
    ),
    UnitManagementTarget(
        "Sağlık Bilimleri Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=21",
        21,
        ("sbf", "S.B.F.", "sağlık bilimleri", "sağlık bilimleri fak", "sağlık bilimleri fakültesi"),
    ),
    UnitManagementTarget(
        "Tıp Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=20",
        20,
        ("tf", "T.F.", "tıp", "tip", "tıp fak", "tip fak", "tıp fakültesi", "tip fakultesi"),
    ),
    UnitManagementTarget(
        "İktisadi İdari ve Sosyal Bilimler Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=22",
        22,
        (
            "iisbf",
            "İ.İ.S.B.F.",
            "iibf",
            "İ.İ.B.F.",
            "İİSBF fak",
            "İİBF fak",
            "iktisadi",
            "iktisadi idari",
            "iktisadi ve idari",
            "iktisadi ve idari bilimler",
            "iktisadi idari sosyal bilimler",
            "iktisadi idari ve sosyal bilimler",
            "idari sosyal bilimler",
            "sosyal bilimler fakültesi",
        ),
    ),
    UnitManagementTarget(
        "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=24",
        24,
        (
            "gstm",
            "G.S.T.M.",
            "gstmf",
            "G.S.T.M.F.",
            "gsmf",
            "G.S.M.F.",
            "gsf",
            "G.S.F.",
            "güzel sanatlar",
            "güzel sanatlar fak",
            "güzel sanatlar fakültesi",
            "güzel sanatlar tasarım",
            "güzel sanatlar tasarım mimarlık",
            "sanat tasarım",
            "tasarım",
            "tasarım fakültesi",
            "tasarım mimarlık",
            "mimarlık",
            "mimarlık fakültesi",
        ),
    ),
    UnitManagementTarget(
        "Sağlık Hizmetleri Meslek Yüksekokulu",
        "vocational_school",
        "https://www.gibtu.edu.tr/birimyonetim.aspx?id=31",
        31,
        (
            "shmyo",
            "S.H.M.Y.O.",
            "SH MYO",
            "sağlık myo",
            "sağlık hizmetleri",
            "sağlık hizmetleri myo",
            "sağlık hizmetleri meslek yüksekokulu",
        ),
    ),
    UnitManagementTarget(
        "Teknik Bilimler Meslek Yüksekokulu",
        "vocational_school",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=36",
        36,
        (
            "tbmyo",
            "T.B.M.Y.O.",
            "TB MYO",
            "teknik myo",
            "teknik bilimler",
            "teknik bilimler myo",
            "teknik bilimler meslek yüksekokulu",
        ),
    ),
    UnitManagementTarget(
        "Yabancı Diller Yüksekokulu",
        "school",
        "https://www.gibtu.edu.tr/BirimYonetim.aspx?id=34",
        34,
        (
            "ydyo",
            "Y.D.Y.O.",
            "YD YO",
            "yabancı dil",
            "yabancı diller",
            "yabancı diller yo",
            "yabancı diller y.o.",
            "yabancı diller yüksekokulu",
        ),
    ),
)

ALLOWED_BIRIM_IDS: frozenset[int] = frozenset(target.birim_id for target in DEFAULT_TARGET_UNITS)
TARGET_BY_ID: dict[int, UnitManagementTarget] = {target.birim_id: target for target in DEFAULT_TARGET_UNITS}


@dataclass
class UnitManagementGroupRecord:
    unit_name: str
    unit_type: str
    source_url: str
    snapshot_id: str
    group_title: str
    group_key: str
    group_order: int


@dataclass
class UnitManagementMemberRecord:
    unit_name: str
    unit_type: str
    source_url: str
    snapshot_id: str
    group_title: str
    group_key: str
    group_order: int
    member_order: int
    page_order: int
    full_name: str | None
    full_name_normalized: str
    academic_title: str | None
    role: str | None
    phone_extension: str | None
    email: str | None
    profile_url: str | None
    raw_text: str
    scrape_time: str
    content_hash: str
    parse_status: str
    stable_member_key: str
    validation_issues: list[str] = field(default_factory=list)


@dataclass
class ManagementSnapshotRecord:
    snapshot_id: str
    scrape_run_id: str
    unit_name: str
    unit_type: str
    source_url: str
    http_status: int | None
    content_hash: str
    fetched_at: str
    parse_status: str
    group_count: int
    member_count: int
    raw_text: str
    raw_html: str
    validation_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnitManagementScrapeReport:
    success: bool = False
    scrape_run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    target_url_count: int = 0
    snapshots: list[ManagementSnapshotRecord] = field(default_factory=list)
    groups: list[UnitManagementGroupRecord] = field(default_factory=list)
    members: list[UnitManagementMemberRecord] = field(default_factory=list)
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
        if re.search(pattern, normalized, re.IGNORECASE):
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


def _header_charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _decode_response(response: requests.Response) -> str:
    """Header charset → apparent_encoding → response.encoding → utf-8 sırasıyla güvenli decode eder."""
    content = getattr(response, "content", None)
    if not content:
        return getattr(response, "text", "") or ""

    candidates = [
        _header_charset(response.headers.get("Content-Type") if hasattr(response, "headers") else None),
        getattr(response, "apparent_encoding", None),
        getattr(response, "encoding", None),
        "utf-8",
        "iso-8859-9",
    ]
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def _target_from_url(url: str) -> UnitManagementTarget | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme != "https":
        return None
    if host not in {"www.gibtu.edu.tr", "gibtu.edu.tr"}:
        return None
    if Path(parsed.path.lower()).name != "birimyonetim.aspx":
        return None
    query = parse_qs(parsed.query)
    if set(query) != {"id"}:
        return None
    values = query.get("id") or []
    if len(values) != 1 or not values[0].isdigit():
        return None
    birim_id = int(values[0])
    if birim_id not in ALLOWED_BIRIM_IDS:
        return None
    return TARGET_BY_ID[birim_id]


def is_allowed_management_url(url: str) -> bool:
    """Bu modülün fetch edebileceği URL kapsamını denetler."""
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


def _stable_member_key(name: str | None, email: str | None, profile_url: str | None, raw_text: str | None = None) -> str:
    if profile_url:
        return f"profile:{profile_url.strip().lower()}"
    if email:
        return f"email:{email.strip().lower()}"
    if name:
        return f"name:{normalize_for_match(name)}"
    return f"unknown:{_sha256_text(raw_text or '')[:12]}"


def _member_parse_status(full_name: str | None, role: str | None, email: str | None, phone: str | None) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not full_name:
        issues.append("missing_name")
    if not role:
        issues.append("missing_role")
    if not email:
        issues.append("missing_email")
    if not phone or phone == "0000":
        issues.append("missing_or_invalid_phone")

    if "missing_name" in issues or "missing_role" in issues:
        return "needs_review", issues
    if issues:
        return "partial", issues
    return "ok", issues


def parse_management_page(
    html: str,
    target: UnitManagementTarget,
    source_url: str,
    scrape_run_id: str,
    http_status: int | None = 200,
    fetched_at: str | None = None,
) -> tuple[ManagementSnapshotRecord, list[UnitManagementGroupRecord], list[UnitManagementMemberRecord]]:
    """BirimYonetim HTML'ini grup ve kişi kayıtlarına ayrıştırır."""
    fetched_at = fetched_at or utc_now_iso()
    content_hash = _sha256_text(html or f"{source_url}:{http_status}")
    snapshot_id = _sha256_text(f"{scrape_run_id}:{source_url}:{content_hash}")[:24]

    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)
    raw_text = "\n".join(
        line for line in (_single_line(line) for line in root.get_text("\n", strip=True).splitlines()) if line
    )

    container = root.select_one("div.personel_listesi") or root
    groups: list[UnitManagementGroupRecord] = []
    members: list[UnitManagementMemberRecord] = []
    group_by_order: dict[int, UnitManagementGroupRecord] = {}

    current_group: UnitManagementGroupRecord | None = None
    group_order = 0
    page_order = 0
    member_order_by_group: dict[int, int] = {}

    for child in [node for node in container.children if isinstance(node, Tag)]:
        classes = child.get("class") or []
        if "birim_modul_baslik" in classes:
            group_title = _single_line(child.get_text(" ", strip=True))
            if not group_title:
                current_group = None
                continue
            group_order += 1
            current_group = UnitManagementGroupRecord(
                unit_name=target.unit_name,
                unit_type=target.unit_type,
                source_url=source_url,
                snapshot_id=snapshot_id,
                group_title=group_title,
                group_key=normalize_for_match(group_title),
                group_order=group_order,
            )
            groups.append(current_group)
            group_by_order[group_order] = current_group
            member_order_by_group[group_order] = 0
            continue

        cards = child.select("div.card")
        if not cards:
            continue

        if current_group is None:
            group_order += 1
            current_group = UnitManagementGroupRecord(
                unit_name=target.unit_name,
                unit_type=target.unit_type,
                source_url=source_url,
                snapshot_id=snapshot_id,
                group_title="Belirsiz Grup",
                group_key="belirsiz grup",
                group_order=group_order,
            )
            groups.append(current_group)
            group_by_order[group_order] = current_group
            member_order_by_group[group_order] = 0

        for card in cards:
            page_order += 1
            member_order_by_group[current_group.group_order] += 1
            member_order = member_order_by_group[current_group.group_order]
            raw_card_text = _single_line(card.get_text(" ", strip=True))
            academic_title, full_name = split_academic_title_and_name(_li_text(card, "li.adsoyad"))
            role = _li_text(card, "li.unvan") or None
            phone = _normalize_phone(_li_text(card, "li.dahili"))
            email = _extract_email(_li_text(card, "li.mail"))
            blog = card.select_one("li.blog a[href]")
            profile_url = urljoin(source_url, blog.get("href")) if blog else None
            parse_status, issues = _member_parse_status(full_name, role, email, phone)

            members.append(
                UnitManagementMemberRecord(
                    unit_name=target.unit_name,
                    unit_type=target.unit_type,
                    source_url=source_url,
                    snapshot_id=snapshot_id,
                    group_title=current_group.group_title,
                    group_key=current_group.group_key,
                    group_order=current_group.group_order,
                    member_order=member_order,
                    page_order=page_order,
                    full_name=full_name,
                    full_name_normalized=normalize_for_match(full_name),
                    academic_title=academic_title,
                    role=role,
                    phone_extension=phone,
                    email=email,
                    profile_url=profile_url,
                    raw_text=raw_card_text,
                    scrape_time=fetched_at,
                    content_hash=_sha256_text(raw_card_text),
                    parse_status=parse_status,
                    stable_member_key=_stable_member_key(full_name, email, profile_url, raw_card_text),
                    validation_issues=issues,
                )
            )

    if not groups or not members:
        parse_status = "needs_review"
    elif any(member.parse_status == "needs_review" for member in members):
        parse_status = "partial"
    else:
        parse_status = "ok"

    snapshot = ManagementSnapshotRecord(
        snapshot_id=snapshot_id,
        scrape_run_id=scrape_run_id,
        unit_name=target.unit_name,
        unit_type=target.unit_type,
        source_url=source_url,
        http_status=http_status,
        content_hash=content_hash,
        fetched_at=fetched_at,
        parse_status=parse_status,
        group_count=len(group_by_order),
        member_count=len(members),
        raw_text=raw_text,
        raw_html=html or "",
    )
    return snapshot, groups, members


def build_validation_report(report: UnitManagementScrapeReport) -> dict[str, Any]:
    empty_urls = [
        snapshot.source_url
        for snapshot in report.snapshots
        if snapshot.group_count == 0 or snapshot.member_count == 0 or snapshot.parse_status == "needs_review"
    ]

    missing_email = []
    missing_role = []
    missing_phone = []
    needs_review = []
    duplicate_candidates: dict[str, list[UnitManagementMemberRecord]] = {}

    for member in report.members:
        key = f"{member.unit_name}|{member.group_key}|{member.stable_member_key}"
        duplicate_candidates.setdefault(key, []).append(member)
        payload = {
            "unit_name": member.unit_name,
            "group_title": member.group_title,
            "full_name": member.full_name,
            "role": member.role,
            "source_url": member.source_url,
            "page_order": member.page_order,
            "parse_status": member.parse_status,
            "validation_issues": member.validation_issues,
        }
        if not member.email:
            missing_email.append(payload)
        if not member.role:
            missing_role.append(payload)
        if not member.phone_extension or member.phone_extension == "0000":
            missing_phone.append(payload)
        if member.parse_status == "needs_review":
            needs_review.append(payload)

    duplicates = [
        {
            "dedup_key": key,
            "count": len(items),
            "records": [
                {
                    "unit_name": item.unit_name,
                    "group_title": item.group_title,
                    "full_name": item.full_name,
                    "role": item.role,
                    "source_url": item.source_url,
                    "page_order": item.page_order,
                }
                for item in items
            ],
        }
        for key, items in duplicate_candidates.items()
        if len(items) > 1
    ]

    parse_status_counts: dict[str, int] = {}
    for snapshot in report.snapshots:
        parse_status_counts[snapshot.parse_status] = parse_status_counts.get(snapshot.parse_status, 0) + 1

    return {
        "processed_url_count": len(report.snapshots),
        "target_url_count": report.target_url_count,
        "group_count": len(report.groups),
        "member_count": len(report.members),
        "empty_urls": empty_urls,
        "missing_email_records": missing_email,
        "missing_role_records": missing_role,
        "missing_phone_records": missing_phone,
        "duplicate_records": duplicates,
        "needs_review_records": needs_review,
        "parse_status_counts": parse_status_counts,
        "errors": report.errors,
    }


class UnitManagementScraper:
    """Allowlist BirimYonetim sayfalarını DB-first rapora dönüştüren scraper."""

    def __init__(
        self,
        target_units: tuple[UnitManagementTarget, ...] = DEFAULT_TARGET_UNITS,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
    ) -> None:
        self.target_units = target_units
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; UniChatUnitManagementScraper/1.0; +https://www.gibtu.edu.tr)",
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
    ) -> UnitManagementScrapeReport:
        started_at = utc_now_iso()
        scrape_run_id = f"{SCRAPER_NAME}:{_sha256_text(f'{SCRAPER_NAME}:{started_at}')[:16]}"
        report = UnitManagementScrapeReport(
            scrape_run_id=scrape_run_id,
            started_at=started_at,
            target_url_count=len(self.target_units),
        )

        for target in self.target_units:
            source_url = target.source_url
            try:
                html, status_code = self._fetch(source_url)
                fetched_at = utc_now_iso()
                if html is None:
                    report.errors.append(f"Kaynak alınamadı: {source_url} (status={status_code})")
                    snapshot = ManagementSnapshotRecord(
                        snapshot_id=_sha256_text(f"{scrape_run_id}:{source_url}:{status_code}")[:24],
                        scrape_run_id=scrape_run_id,
                        unit_name=target.unit_name,
                        unit_type=target.unit_type,
                        source_url=source_url,
                        http_status=status_code,
                        content_hash=_sha256_text(f"{source_url}:{status_code}:fetch_failed"),
                        fetched_at=fetched_at,
                        parse_status="needs_review",
                        group_count=0,
                        member_count=0,
                        raw_text="",
                        raw_html="",
                    )
                    report.snapshots.append(snapshot)
                    continue

                snapshot, groups, members = parse_management_page(
                    html=html,
                    target=target,
                    source_url=source_url,
                    scrape_run_id=scrape_run_id,
                    http_status=status_code,
                    fetched_at=fetched_at,
                )
                report.snapshots.append(snapshot)
                report.groups.extend(groups)
                report.members.extend(members)
            except Exception as exc:  # noqa: BLE001 - raporlayıp diğer allowlist URL'lerine devam et
                logger.exception("Birim yönetim kaynağı işlenemedi: %s", source_url)
                report.errors.append(f"{source_url}: {exc}")

        report.finished_at = utc_now_iso()
        report.validation_report = build_validation_report(report)
        for snapshot in report.snapshots:
            snapshot.validation_report = {
                "unit_name": snapshot.unit_name,
                "parse_status": snapshot.parse_status,
                "group_count": snapshot.group_count,
                "member_count": snapshot.member_count,
            }
        report.success = not report.errors and all(
            snapshot.parse_status in {"ok", "partial"} for snapshot in report.snapshots
        )

        if write_db and not dry_run:
            report.import_summary = self.write_report_to_database(report)
        else:
            report.import_summary = {
                "dry_run": True,
                "write_db": bool(write_db),
                "snapshots": len(report.snapshots),
                "groups": len(report.groups),
                "members": len(report.members),
                "note": "DB yazımı yapılmadı.",
            }

        self._write_json(report_json, report.to_dict())
        self._write_json(validation_report_json, report.validation_report)
        self._write_json(import_summary_json, report.import_summary)
        return report

    def write_report_to_database(self, report: UnitManagementScrapeReport) -> dict[str, Any]:
        from app.repositories.unit_management_repository import UnitManagementRepository

        repo = UnitManagementRepository()
        repo.ensure_schema()
        repo.upsert_scrape_run({
            "scrape_run_id": report.scrape_run_id,
            "scraper_name": report.scraper_name,
            "metadata_version": report.metadata_version,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "status": "success" if report.success else "partial",
            "validation_status": "valid" if report.success else "needs_review",
            "target_url_count": report.target_url_count,
            "processed_url_count": len(report.snapshots),
            "group_count": len(report.groups),
            "member_count": len(report.members),
            "needs_review_count": len(report.validation_report.get("needs_review_records") or []),
            "summary": report.validation_report,
        })

        unit_ids: dict[str, str] = {}
        for target in self.target_units:
            unit_ids[target.unit_name] = repo.upsert_unit({
                "unit_name": target.unit_name,
                "unit_name_normalized": normalize_for_match(target.unit_name),
                "unit_type": target.unit_type,
                "source_url": target.source_url,
                "source_birim_id": target.birim_id,
                "aliases": list(target.aliases),
                "last_checked_at": report.finished_at,
            })

        counts = {
            "dry_run": False,
            "scrape_run_id": report.scrape_run_id,
            "units": len(unit_ids),
            "snapshots": 0,
            "groups": 0,
            "members_upserted": 0,
            "members_deactivated": 0,
            "parse_status_counts": {},
        }

        group_ids: dict[tuple[str, str, int], str] = {}
        for snapshot in report.snapshots:
            unit_id = unit_ids.get(snapshot.unit_name)
            if not unit_id:
                continue
            repo.upsert_snapshot(asdict(snapshot), unit_id)
            counts["snapshots"] += 1
            status_counts = counts["parse_status_counts"]
            status_counts[snapshot.parse_status] = status_counts.get(snapshot.parse_status, 0) + 1

        for group in report.groups:
            unit_id = unit_ids.get(group.unit_name)
            if not unit_id:
                continue
            group_id = repo.upsert_group(asdict(group), unit_id)
            group_ids[(group.unit_name, group.group_key, group.group_order)] = group_id
            counts["groups"] += 1

        seen_member_ids_by_unit_source: dict[tuple[str, str], list[str]] = {}
        for member in report.members:
            unit_id = unit_ids.get(member.unit_name)
            group_id = group_ids.get((member.unit_name, member.group_key, member.group_order))
            if not unit_id or not group_id:
                continue
            member_id = repo.upsert_member(asdict(member), unit_id, group_id)
            seen_member_ids_by_unit_source.setdefault((unit_id, member.source_url), []).append(member_id)
            counts["members_upserted"] += 1

        ok_sources = {
            (unit_ids.get(snapshot.unit_name), snapshot.source_url)
            for snapshot in report.snapshots
            if snapshot.parse_status == "ok" and unit_ids.get(snapshot.unit_name)
        }
        for unit_id, source_url in ok_sources:
            seen_ids = seen_member_ids_by_unit_source.get((unit_id, source_url), [])
            counts["members_deactivated"] += repo.deactivate_members_not_seen(unit_id, source_url, seen_ids)

        return counts

    def _fetch(self, url: str) -> tuple[str | None, int | None]:
        if not is_allowed_management_url(url):
            raise ValueError(f"Birim yönetim allowlist dışında URL reddedildi: {url}")

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
                logger.warning("Birim yönetim kaynağı alınamadı (%d/%d): %s - %s", attempt, MAX_RETRIES, url, exc)
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
    parser = argparse.ArgumentParser(description="GİBTÜ BirimYonetim DB-first scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret")
    parser.add_argument("--write-db", action="store_true", help="Structured DB tablolarına yaz")
    parser.add_argument("--report-json", default=None, help="Tam raporu JSON dosyasına yaz")
    parser.add_argument("--validation-report-json", default=None, help="Validation raporunu JSON dosyasına yaz")
    parser.add_argument("--import-summary-json", default=None, help="Import summary dosyasını yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = UnitManagementScraper()
    report = scraper.scrape(
        dry_run=args.dry_run or not args.write_db,
        write_db=args.write_db,
        report_json=args.report_json,
        validation_report_json=args.validation_report_json,
        import_summary_json=args.import_summary_json,
    )
    logger.info("Birim yönetim scrape raporu: %s", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
