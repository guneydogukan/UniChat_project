"""
GİBTÜ idari birim/personel sayfaları için izole DB-first scraper.

Bu modül genel crawler değildir. Yalnızca DEFAULT_TARGETS allowlist'indeki
resmi BirimIdariBirimler.aspx / birimidaripersonel.aspx kaynaklarını işler.
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
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 - Windows stdout UTF-8

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
SCRAPER_NAME = "administrative_staff_scraper"
METADATA_VERSION = "administrative_staff.v1"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 1.0

PAGE_TYPE_IDARI_BIRIMLER = "birimidaribirimler"
PAGE_TYPE_IDARI_PERSONEL = "birimidaripersonel"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?90\s*)?0?\s*\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}")


@dataclass(frozen=True)
class AdministrativeTarget:
    parent_unit_name: str
    parent_unit_type: str
    source_url: str
    website_unit_id: int
    page_type: str
    aliases: tuple[str, ...] = ()


DEFAULT_TARGETS: tuple[AdministrativeTarget, ...] = (
    AdministrativeTarget(
        "İlahiyat Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=11",
        11,
        PAGE_TYPE_IDARI_BIRIMLER,
        ("if", "i f", "ilahiyat", "ilahiyat fak", "ilahiyat fakültesi", "ilahiyat fakultesi"),
    ),
    AdministrativeTarget(
        "Mühendislik ve Doğa Bilimleri Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=15",
        15,
        PAGE_TYPE_IDARI_BIRIMLER,
        (
            "mdbf",
            "m d b f",
            "mdb",
            "m d b",
            "mühendislik",
            "muhendislik",
            "mühendislik fakültesi",
            "muhendislik fakultesi",
            "mühendislik ve doğa bilimleri",
            "muhendislik ve doga bilimleri",
            "doğa bilimleri",
            "doga bilimleri",
        ),
    ),
    AdministrativeTarget(
        "Sağlık Bilimleri Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=21",
        21,
        PAGE_TYPE_IDARI_BIRIMLER,
        ("sbf", "s b f", "sağlık bilimleri", "saglik bilimleri", "sağlık bilimleri fakültesi"),
    ),
    AdministrativeTarget(
        "Tıp Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/BirimIdariBirimler.aspx?id=20",
        20,
        PAGE_TYPE_IDARI_BIRIMLER,
        ("tf", "t f", "tıp", "tip", "tıp fakültesi", "tip fakultesi"),
    ),
    AdministrativeTarget(
        "İktisadi İdari ve Sosyal Bilimler Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=22",
        22,
        PAGE_TYPE_IDARI_PERSONEL,
        (
            "iisbf",
            "i i s b f",
            "iibf",
            "i i b f",
            "iktisadi",
            "iktisadi idari",
            "iktisadi ve idari",
            "iktisadi idari sosyal bilimler",
            "iktisadi idari ve sosyal bilimler",
            "sosyal bilimler fakültesi",
        ),
    ),
    AdministrativeTarget(
        "Güzel Sanatlar Tasarım ve Mimarlık Fakültesi",
        "faculty",
        "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=24",
        24,
        PAGE_TYPE_IDARI_BIRIMLER,
        (
            "gsmf",
            "g s m f",
            "gstmf",
            "g s t m f",
            "güzel sanatlar",
            "guzel sanatlar",
            "güzel sanatlar fakültesi",
            "guzel sanatlar fakultesi",
            "tasarım mimarlık",
            "tasarim mimarlik",
            "mimarlık",
            "mimarlik",
        ),
    ),
    AdministrativeTarget(
        "Sağlık Hizmetleri Meslek Yüksekokulu",
        "vocational_school",
        "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=31",
        31,
        PAGE_TYPE_IDARI_BIRIMLER,
        (
            "shmyo",
            "s h m y o",
            "sh myo",
            "sağlık hizmetleri",
            "saglik hizmetleri",
            "sağlık hizmetleri myo",
            "saglik hizmetleri myo",
            "sağlık myo",
            "saglik myo",
        ),
    ),
    AdministrativeTarget(
        "Teknik Bilimler Meslek Yüksekokulu",
        "vocational_school",
        "https://www.gibtu.edu.tr/birimidaribirimler.aspx?id=36",
        36,
        PAGE_TYPE_IDARI_BIRIMLER,
        (
            "tbmyo",
            "t b m y o",
            "tb myo",
            "teknik bilimler",
            "teknik bilimler myo",
            "teknik myo",
        ),
    ),
    AdministrativeTarget(
        "Yabancı Diller Yüksekokulu",
        "school",
        "https://www.gibtu.edu.tr/birimidaripersonel.aspx?id=34",
        34,
        PAGE_TYPE_IDARI_PERSONEL,
        (
            "ydyo",
            "y d y o",
            "yd yo",
            "yabancı dil",
            "yabanci dil",
            "yabancı diller",
            "yabanci diller",
            "yabancı diller yüksekokulu",
        ),
    ),
)

TARGET_BY_ID: dict[int, AdministrativeTarget] = {target.website_unit_id: target for target in DEFAULT_TARGETS}
ALLOWED_WEBSITE_UNIT_IDS: frozenset[int] = frozenset(TARGET_BY_ID)


@dataclass
class AdministrativeSourcePageRecord:
    snapshot_id: str
    scrape_run_id: str
    parent_unit_name: str
    parent_unit_type: str
    website_unit_id: int
    source_url: str
    normalized_source_url: str
    page_type: str
    http_status: int | None
    source_hash: str
    fetched_at: str
    parse_status: str
    administrative_unit_count: int
    staff_count: int
    raw_text: str
    raw_html: str
    validation_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdministrativeUnitRecord:
    parent_unit_name: str
    parent_unit_type: str
    website_unit_id: int
    source_url: str
    normalized_source_url: str
    page_type: str
    snapshot_id: str
    administrative_unit_name: str
    administrative_unit_key: str
    aliases: list[str]
    description: str | None
    order_index: int
    raw_text: str
    normalized_text: str
    search_text: str
    source_hash: str
    last_seen_at: str


@dataclass
class AdministrativeStaffRecord:
    parent_unit_name: str
    parent_unit_type: str
    website_unit_id: int
    source_url: str
    normalized_source_url: str
    page_type: str
    snapshot_id: str
    administrative_unit_name: str
    administrative_unit_key: str
    stable_staff_key: str
    person_name: str | None
    person_name_normalized: str
    title_or_role: str | None
    email: str | None
    phone: str | None
    internal_extension: str | None
    office_location: str | None
    description: str | None
    order_index: int
    raw_text: str
    normalized_text: str
    search_text: str
    aliases: list[str]
    source_hash: str
    last_seen_at: str
    parse_status: str
    validation_issues: list[str] = field(default_factory=list)


@dataclass
class AdministrativeScrapeReport:
    success: bool = False
    scrape_run_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    target_url_count: int = 0
    source_pages: list[AdministrativeSourcePageRecord] = field(default_factory=list)
    administrative_units: list[AdministrativeUnitRecord] = field(default_factory=list)
    staff: list[AdministrativeStaffRecord] = field(default_factory=list)
    validation_report: dict[str, Any] = field(default_factory=dict)
    import_summary: dict[str, Any] = field(default_factory=dict)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    manual_check_samples: list[dict[str, Any]] = field(default_factory=list)
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


def normalize_source_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))


def _header_charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def _decode_response(response: requests.Response) -> str:
    """ASP.NET sayfaları için mojibake puanlamalı güvenli decode."""
    content = getattr(response, "content", None)
    if not content:
        return getattr(response, "text", "") or ""

    candidates = [
        _header_charset(response.headers.get("Content-Type") if hasattr(response, "headers") else None),
        "iso-8859-9",
        "windows-1254",
        getattr(response, "apparent_encoding", None),
        getattr(response, "encoding", None),
        "utf-8",
    ]
    best: tuple[int, str] | None = None
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
        score = (
            text.count("\ufffd") * 10
            + text.count("Ã") * 4
            + text.count("Ä") * 4
            + text.count("Å") * 4
        )
        if best is None or score < best[0]:
            best = (score, text)
    return best[1] if best else content.decode("utf-8", errors="replace")


def _page_type_from_path(path: str) -> str | None:
    filename = Path(path.lower()).name
    if filename == "birimidaribirimler.aspx":
        return PAGE_TYPE_IDARI_BIRIMLER
    if filename == "birimidaripersonel.aspx":
        return PAGE_TYPE_IDARI_PERSONEL
    return None


def _target_from_url(url: str) -> AdministrativeTarget | None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    if parsed.netloc.lower() not in {"www.gibtu.edu.tr", "gibtu.edu.tr"}:
        return None
    page_type = _page_type_from_path(parsed.path)
    if page_type is None:
        return None
    query = parse_qs(parsed.query)
    if set(query) != {"id"}:
        return None
    values = query.get("id") or []
    if len(values) != 1 or not values[0].isdigit():
        return None
    website_unit_id = int(values[0])
    target = TARGET_BY_ID.get(website_unit_id)
    if target is None or target.page_type != page_type:
        return None
    return target


def is_allowed_administrative_url(url: str) -> bool:
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
        "ul.side-nav",
        "span.birim-menu",
        "span#birim-menu-slide",
    ):
        for node in root.select(selector):
            node.decompose()


def _text_without_icons(node: Tag | None) -> str:
    if not node:
        return ""
    clone = BeautifulSoup(str(node), "lxml")
    for icon in clone.select("i.material-icons"):
        icon.decompose()
    return _single_line(clone.get_text(" ", strip=True))


def _card_text(card: Tag, selector: str) -> str:
    return _text_without_icons(card.select_one(selector))


def _extract_email(value: str | None) -> str | None:
    match = EMAIL_RE.search(value or "")
    return match.group(0).lower() if match else None


def _extract_internal_extension(value: str | None) -> str | None:
    text = _single_line(value)
    if not text:
        return None
    digits = re.sub(r"\D+", "", text)
    if not digits or digits == "0000":
        return None
    return digits


def _extract_phone(value: str | None) -> str | None:
    text = _single_line(value)
    if not text:
        return None
    match = PHONE_RE.search(text)
    if not match:
        return None
    digits = re.sub(r"\D+", "", match.group(0))
    if len(digits) < 10:
        return None
    return digits


def _stable_staff_key(person_name: str | None, email: str | None, raw_text: str | None = None) -> str:
    if email:
        return f"email:{email.strip().lower()}"
    if person_name:
        return f"name:{normalize_for_match(person_name)}"
    return f"unknown:{_sha256_text(raw_text or '')[:12]}"


def _staff_parse_status(
    person_name: str | None,
    title_or_role: str | None,
    email: str | None,
    internal_extension: str | None,
    raw_phone_text: str | None,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not person_name:
        issues.append("missing_person_name")
    if not title_or_role:
        issues.append("missing_title_or_role")
    if not email:
        issues.append("missing_email")
    if not internal_extension:
        issues.append("missing_or_invalid_internal_extension")
    if _single_line(raw_phone_text) == "0000":
        issues.append("placeholder_internal_extension_0000")

    if "missing_person_name" in issues or "missing_title_or_role" in issues:
        return "needs_review", issues
    if issues:
        return "partial", issues
    return "ok", issues


def _unit_aliases(target: AdministrativeTarget, administrative_unit_name: str) -> list[str]:
    aliases = {administrative_unit_name, normalize_for_match(administrative_unit_name)}
    normalized = normalize_for_match(administrative_unit_name)
    if "sekreter" in normalized:
        aliases.update({"sekreterlik", "sekreter", "fakülte sekreterliği", "yüksekokul sekreterliği"})
    if "ogrenci" in normalized:
        aliases.update({"öğrenci işleri", "ogrenci isleri", "öğrenci iş", "ogrenci is"})
    if "mali" in normalized:
        aliases.update({"mali işler", "mali isler", "tahakkuk"})
    if "personel" in normalized:
        aliases.update({"personel işleri", "personel isleri"})
    if "idari" in normalized:
        aliases.update({"idari personel", "idari birim"})
    aliases.update(target.aliases)
    return sorted(alias for alias in aliases if alias)


def _build_search_text(*parts: Any) -> str:
    visible = " ".join(str(part) for part in parts if part)
    return normalize_for_match(visible)


def _make_unit_record(
    target: AdministrativeTarget,
    source_url: str,
    snapshot_id: str,
    unit_name: str,
    order_index: int,
    raw_text: str,
    fetched_at: str,
) -> AdministrativeUnitRecord:
    unit_name = _single_line(unit_name) or "İdari Personel"
    aliases = _unit_aliases(target, unit_name)
    normalized_text = normalize_for_match(" ".join([target.parent_unit_name, unit_name, raw_text]))
    search_text = _build_search_text(target.parent_unit_name, unit_name, " ".join(aliases), raw_text)
    return AdministrativeUnitRecord(
        parent_unit_name=target.parent_unit_name,
        parent_unit_type=target.parent_unit_type,
        website_unit_id=target.website_unit_id,
        source_url=source_url,
        normalized_source_url=normalize_source_url(source_url),
        page_type=target.page_type,
        snapshot_id=snapshot_id,
        administrative_unit_name=unit_name,
        administrative_unit_key=normalize_for_match(unit_name),
        aliases=aliases,
        description=None,
        order_index=order_index,
        raw_text=_single_line(raw_text or unit_name),
        normalized_text=normalized_text,
        search_text=search_text,
        source_hash=_sha256_text(raw_text or unit_name),
        last_seen_at=fetched_at,
    )


def _make_staff_record(
    card: Tag,
    target: AdministrativeTarget,
    source_url: str,
    snapshot_id: str,
    administrative_unit_name: str,
    order_index: int,
    fetched_at: str,
) -> AdministrativeStaffRecord:
    raw_text = _single_line(card.get_text(" ", strip=True))
    person_name = _card_text(card, "li.adsoyad") or None
    title_or_role = _card_text(card, "li.unvan") or None
    raw_phone_text = _card_text(card, "li.dahili")
    email = _extract_email(_card_text(card, "li.mail"))
    internal_extension = _extract_internal_extension(raw_phone_text)
    phone = _extract_phone(raw_phone_text)
    parse_status, issues = _staff_parse_status(
        person_name=person_name,
        title_or_role=title_or_role,
        email=email,
        internal_extension=internal_extension,
        raw_phone_text=raw_phone_text,
    )

    aliases = []
    if person_name:
        aliases.append(person_name)
        aliases.append(normalize_for_match(person_name))

    unit_key = normalize_for_match(administrative_unit_name)
    search_text = _build_search_text(
        target.parent_unit_name,
        administrative_unit_name,
        person_name,
        title_or_role,
        email,
        internal_extension,
        raw_text,
    )

    return AdministrativeStaffRecord(
        parent_unit_name=target.parent_unit_name,
        parent_unit_type=target.parent_unit_type,
        website_unit_id=target.website_unit_id,
        source_url=source_url,
        normalized_source_url=normalize_source_url(source_url),
        page_type=target.page_type,
        snapshot_id=snapshot_id,
        administrative_unit_name=administrative_unit_name,
        administrative_unit_key=unit_key,
        stable_staff_key=_stable_staff_key(person_name, email, raw_text),
        person_name=person_name,
        person_name_normalized=normalize_for_match(person_name),
        title_or_role=title_or_role,
        email=email,
        phone=phone,
        internal_extension=internal_extension,
        office_location=None,
        description=None,
        order_index=order_index,
        raw_text=raw_text,
        normalized_text=normalize_for_match(raw_text),
        search_text=search_text,
        aliases=aliases,
        source_hash=_sha256_text(raw_text),
        last_seen_at=fetched_at,
        parse_status=parse_status,
        validation_issues=issues,
    )


def _raw_text_from_root(root: Tag) -> str:
    lines = [
        _single_line(line)
        for line in root.get_text("\n", strip=True).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def _parse_administrative_units_page(
    root: Tag,
    target: AdministrativeTarget,
    source_url: str,
    snapshot_id: str,
    fetched_at: str,
) -> tuple[list[AdministrativeUnitRecord], list[AdministrativeStaffRecord]]:
    units: list[AdministrativeUnitRecord] = []
    staff: list[AdministrativeStaffRecord] = []
    unit_order = 0
    staff_order = 0
    container = root.select_one("div.personel_listesi") or root

    for item in container.select("ul.collapsible > li"):
        header = item.select_one("div.collapsible-header")
        unit_name = _text_without_icons(header)
        unit_name = re.sub(r"\bkeyboard_arrow_right\b", "", unit_name).strip() or "İdari Personel"
        unit_order += 1
        body = item.select_one("div.collapsible-body") or item
        unit_raw_text = _single_line(body.get_text(" ", strip=True)) or unit_name
        units.append(_make_unit_record(target, source_url, snapshot_id, unit_name, unit_order, unit_raw_text, fetched_at))
        for card in body.select("div.card"):
            staff_order += 1
            staff.append(_make_staff_record(card, target, source_url, snapshot_id, unit_name, staff_order, fetched_at))

    if staff or units:
        return units, staff

    cards = container.select("div.card")
    if cards:
        unit_order += 1
        units.append(_make_unit_record(target, source_url, snapshot_id, "İdari Personel", unit_order, "", fetched_at))
        for card in cards:
            staff_order += 1
            staff.append(_make_staff_record(card, target, source_url, snapshot_id, "İdari Personel", staff_order, fetched_at))
    return units, staff


def _parse_administrative_personnel_page(
    root: Tag,
    target: AdministrativeTarget,
    source_url: str,
    snapshot_id: str,
    fetched_at: str,
) -> tuple[list[AdministrativeUnitRecord], list[AdministrativeStaffRecord]]:
    units: list[AdministrativeUnitRecord] = []
    staff: list[AdministrativeStaffRecord] = []
    unit_order = 0
    staff_order = 0
    current_unit_name = "İdari Personel"
    container = root.select_one("div.personel_listesi") or root
    seen_units: set[str] = set()

    def ensure_unit(unit_name: str, raw_text: str = "") -> None:
        nonlocal unit_order
        key = normalize_for_match(unit_name)
        if key in seen_units:
            return
        seen_units.add(key)
        unit_order += 1
        units.append(_make_unit_record(target, source_url, snapshot_id, unit_name, unit_order, raw_text, fetched_at))

    for child in container.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class") or []
        if "birim_modul_baslik" in classes:
            current_unit_name = _single_line(child.get_text(" ", strip=True)) or current_unit_name
            ensure_unit(current_unit_name, current_unit_name)
            continue
        for card in child.select("div.card"):
            ensure_unit(current_unit_name, current_unit_name)
            staff_order += 1
            staff.append(_make_staff_record(card, target, source_url, snapshot_id, current_unit_name, staff_order, fetched_at))

    if staff and not units:
        ensure_unit("İdari Personel", "")
    return units, staff


def parse_administrative_page(
    html: str,
    target: AdministrativeTarget,
    source_url: str,
    scrape_run_id: str,
    http_status: int | None = 200,
    fetched_at: str | None = None,
) -> tuple[AdministrativeSourcePageRecord, list[AdministrativeUnitRecord], list[AdministrativeStaffRecord]]:
    fetched_at = fetched_at or utc_now_iso()
    source_hash = _sha256_text(html or f"{source_url}:{http_status}")
    snapshot_id = _sha256_text(f"{scrape_run_id}:{source_url}:{source_hash}")[:24]

    soup = BeautifulSoup(html or "", "lxml")
    root = _main_content(soup)
    _clean_soup(root)
    raw_text = _raw_text_from_root(root)

    if target.page_type == PAGE_TYPE_IDARI_PERSONEL:
        units, staff = _parse_administrative_personnel_page(root, target, source_url, snapshot_id, fetched_at)
    else:
        units, staff = _parse_administrative_units_page(root, target, source_url, snapshot_id, fetched_at)

    if not units:
        parse_status = "needs_review"
    elif any(item.parse_status == "needs_review" for item in staff):
        parse_status = "partial"
    elif any(item.parse_status == "partial" for item in staff):
        parse_status = "partial"
    else:
        parse_status = "ok"

    page = AdministrativeSourcePageRecord(
        snapshot_id=snapshot_id,
        scrape_run_id=scrape_run_id,
        parent_unit_name=target.parent_unit_name,
        parent_unit_type=target.parent_unit_type,
        website_unit_id=target.website_unit_id,
        source_url=source_url,
        normalized_source_url=normalize_source_url(source_url),
        page_type=target.page_type,
        http_status=http_status,
        source_hash=source_hash,
        fetched_at=fetched_at,
        parse_status=parse_status,
        administrative_unit_count=len(units),
        staff_count=len(staff),
        raw_text=raw_text,
        raw_html=html or "",
    )
    return page, units, staff


def build_validation_report(report: AdministrativeScrapeReport) -> dict[str, Any]:
    missing_name = []
    missing_role = []
    missing_email = []
    missing_internal_extension = []
    needs_review = []
    duplicate_candidates: dict[str, list[AdministrativeStaffRecord]] = {}
    url_summaries = []

    for page in report.source_pages:
        page_staff = [item for item in report.staff if item.snapshot_id == page.snapshot_id]
        page_units = [item for item in report.administrative_units if item.snapshot_id == page.snapshot_id]
        page_warnings = [
            issue
            for item in page_staff
            for issue in item.validation_issues
        ]
        url_summaries.append({
            "source_url": page.source_url,
            "parent_unit_name": page.parent_unit_name,
            "page_type": page.page_type,
            "administrative_unit_count": len(page_units),
            "staff_count": len(page_staff),
            "parse_status": page.parse_status,
            "warning_count": len(page_warnings),
        })
        page.validation_report = url_summaries[-1]

    for item in report.staff:
        key = f"{item.website_unit_id}|{item.administrative_unit_key}|{item.stable_staff_key}"
        duplicate_candidates.setdefault(key, []).append(item)
        payload = {
            "parent_unit_name": item.parent_unit_name,
            "administrative_unit_name": item.administrative_unit_name,
            "person_name": item.person_name,
            "title_or_role": item.title_or_role,
            "source_url": item.source_url,
            "order_index": item.order_index,
            "validation_issues": item.validation_issues,
        }
        if not item.person_name:
            missing_name.append(payload)
        if not item.title_or_role:
            missing_role.append(payload)
        if not item.email:
            missing_email.append(payload)
        if not item.internal_extension:
            missing_internal_extension.append(payload)
        if item.parse_status == "needs_review":
            needs_review.append(payload)

    duplicates = [
        {
            "dedup_key": key,
            "count": len(items),
            "records": [
                {
                    "parent_unit_name": item.parent_unit_name,
                    "administrative_unit_name": item.administrative_unit_name,
                    "person_name": item.person_name,
                    "email": item.email,
                    "source_url": item.source_url,
                    "order_index": item.order_index,
                }
                for item in items
            ],
        }
        for key, items in duplicate_candidates.items()
        if len(items) > 1
    ]

    parse_status_counts: dict[str, int] = {}
    for page in report.source_pages:
        parse_status_counts[page.parse_status] = parse_status_counts.get(page.parse_status, 0) + 1

    warning_count = (
        len(missing_name)
        + len(missing_role)
        + len(missing_email)
        + len(missing_internal_extension)
        + len(duplicates)
    )

    return {
        "processed_url_count": len(report.source_pages),
        "target_url_count": report.target_url_count,
        "administrative_unit_count": len(report.administrative_units),
        "staff_count": len(report.staff),
        "unique_email_count": len({item.email for item in report.staff if item.email}),
        "url_summaries": url_summaries,
        "missing_name_records": missing_name,
        "missing_role_records": missing_role,
        "missing_email_records": missing_email,
        "missing_internal_extension_records": missing_internal_extension,
        "duplicate_records": duplicates,
        "needs_review_records": needs_review,
        "parse_status_counts": parse_status_counts,
        "warning_count": warning_count,
        "critical_count": len(report.errors) + sum(1 for page in report.source_pages if page.parse_status == "needs_review"),
        "errors": report.errors,
    }


class AdministrativeStaffScraper:
    """Allowlist idari birim/personel sayfalarını DB-first rapora dönüştürür."""

    def __init__(
        self,
        targets: tuple[AdministrativeTarget, ...] = DEFAULT_TARGETS,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
    ) -> None:
        self.targets = targets
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; UniChatAdministrativeStaffScraper/1.0; +https://www.gibtu.edu.tr)",
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
        diff_summary_json: str | Path | None = None,
    ) -> AdministrativeScrapeReport:
        started_at = utc_now_iso()
        scrape_run_id = f"{SCRAPER_NAME}:{_sha256_text(f'{SCRAPER_NAME}:{started_at}')[:16]}"
        report = AdministrativeScrapeReport(
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
                    page = AdministrativeSourcePageRecord(
                        snapshot_id=_sha256_text(f"{scrape_run_id}:{source_url}:{status_code}")[:24],
                        scrape_run_id=scrape_run_id,
                        parent_unit_name=target.parent_unit_name,
                        parent_unit_type=target.parent_unit_type,
                        website_unit_id=target.website_unit_id,
                        source_url=source_url,
                        normalized_source_url=normalize_source_url(source_url),
                        page_type=target.page_type,
                        http_status=status_code,
                        source_hash=_sha256_text(f"{source_url}:{status_code}:fetch_failed"),
                        fetched_at=fetched_at,
                        parse_status="needs_review",
                        administrative_unit_count=0,
                        staff_count=0,
                        raw_text="",
                        raw_html="",
                    )
                    report.source_pages.append(page)
                    continue

                page, units, staff = parse_administrative_page(
                    html=html,
                    target=target,
                    source_url=source_url,
                    scrape_run_id=scrape_run_id,
                    http_status=status_code,
                    fetched_at=fetched_at,
                )
                report.source_pages.append(page)
                report.administrative_units.extend(units)
                report.staff.extend(staff)
            except Exception as exc:  # noqa: BLE001 - raporlayıp diğer allowlist kaynaklarına devam et
                logger.exception("İdari personel kaynağı işlenemedi: %s", source_url)
                report.errors.append(f"{source_url}: {exc}")

        report.finished_at = utc_now_iso()
        report.validation_report = build_validation_report(report)
        report.manual_check_samples = self._manual_check_samples(report)
        report.success = not report.errors and all(
            page.parse_status in {"ok", "partial"} for page in report.source_pages
        )

        if write_db and not dry_run:
            if report.validation_report.get("critical_count", 0) > 0:
                report.import_summary = {
                    "dry_run": False,
                    "write_db": False,
                    "skipped": True,
                    "reason": "Critical validation hatası nedeniyle DB yazımı yapılmadı.",
                    "critical_count": report.validation_report.get("critical_count", 0),
                }
            else:
                report.import_summary = self.write_report_to_database(report)
                report.diff_summary = report.import_summary.get("diff_summary") or {}
        else:
            report.import_summary = {
                "dry_run": True,
                "write_db": bool(write_db),
                "source_pages": len(report.source_pages),
                "administrative_units": len(report.administrative_units),
                "staff": len(report.staff),
                "note": "DB yazımı yapılmadı.",
            }
            report.diff_summary = {"dry_run": True, "note": "DB karşılaştırması yapılmadı."}

        self._write_json(report_json, report.to_dict())
        self._write_json(validation_report_json, report.validation_report)
        self._write_json(import_summary_json, report.import_summary)
        self._write_json(diff_summary_json, report.diff_summary)
        return report

    def write_report_to_database(self, report: AdministrativeScrapeReport) -> dict[str, Any]:
        from app.repositories.administrative_repository import AdministrativeRepository

        repo = AdministrativeRepository()
        repo.ensure_schema()
        existing_keys = repo.get_active_staff_keys()

        repo.upsert_scrape_run({
            "scrape_run_id": report.scrape_run_id,
            "scraper_name": report.scraper_name,
            "metadata_version": report.metadata_version,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "status": "success" if report.success else "partial",
            "validation_status": "valid" if report.success else "needs_review",
            "target_url_count": report.target_url_count,
            "processed_url_count": len(report.source_pages),
            "administrative_unit_count": len(report.administrative_units),
            "staff_count": len(report.staff),
            "warning_count": int(report.validation_report.get("warning_count") or 0),
            "critical_count": int(report.validation_report.get("critical_count") or 0),
            "summary": report.validation_report,
            "diff_summary": {},
        })

        counts = {
            "dry_run": False,
            "scrape_run_id": report.scrape_run_id,
            "source_pages": 0,
            "administrative_units": 0,
            "staff_upserted": 0,
            "staff_deactivated": 0,
            "aliases_upserted": 0,
            "parse_status_counts": {},
        }

        for page in report.source_pages:
            repo.upsert_source_page(asdict(page))
            counts["source_pages"] += 1
            status_counts = counts["parse_status_counts"]
            status_counts[page.parse_status] = status_counts.get(page.parse_status, 0) + 1

        unit_ids: dict[tuple[int, str, str], str] = {}
        for unit in report.administrative_units:
            unit_id = repo.upsert_administrative_unit(asdict(unit))
            unit_ids[(unit.website_unit_id, unit.normalized_source_url, unit.administrative_unit_key)] = unit_id
            counts["administrative_units"] += 1

        seen_staff_ids_by_source: dict[tuple[int, str], list[str]] = {}
        current_keys: dict[tuple[int, str], set[str]] = {}
        for staff in report.staff:
            unit_id = unit_ids.get((staff.website_unit_id, staff.normalized_source_url, staff.administrative_unit_key))
            if not unit_id:
                continue
            staff_id = repo.upsert_administrative_staff(asdict(staff), unit_id)
            seen_staff_ids_by_source.setdefault((staff.website_unit_id, staff.normalized_source_url), []).append(staff_id)
            diff_key = f"{staff.administrative_unit_key}|{staff.stable_staff_key}"
            current_keys.setdefault((staff.website_unit_id, staff.normalized_source_url), set()).add(diff_key)
            counts["staff_upserted"] += 1

        for target in self.targets:
            counts["aliases_upserted"] += repo.upsert_aliases(
                canonical_name=target.parent_unit_name,
                canonical_type="parent_unit",
                aliases=[target.parent_unit_name, *target.aliases],
                website_unit_id=target.website_unit_id,
                source_url=target.source_url,
            )

        ok_sources = {
            (page.website_unit_id, page.normalized_source_url)
            for page in report.source_pages
            if page.parse_status in {"ok", "partial"}
        }
        for website_unit_id, normalized_source_url in ok_sources:
            seen_ids = seen_staff_ids_by_source.get((website_unit_id, normalized_source_url), [])
            counts["staff_deactivated"] += repo.deactivate_staff_not_seen(
                website_unit_id=website_unit_id,
                normalized_source_url=normalized_source_url,
                seen_staff_ids=seen_ids,
            )

        diff_summary = self._build_diff_summary(existing_keys, current_keys)
        counts["diff_summary"] = diff_summary
        repo.update_scrape_run_diff(report.scrape_run_id, diff_summary)
        return counts

    def _fetch(self, url: str) -> tuple[str | None, int | None]:
        if not is_allowed_administrative_url(url):
            raise ValueError(f"İdari personel allowlist dışında URL reddedildi: {url}")

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
                logger.warning("İdari personel kaynağı alınamadı (%d/%d): %s - %s", attempt, MAX_RETRIES, url, exc)
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
    def _manual_check_samples(report: AdministrativeScrapeReport) -> list[dict[str, Any]]:
        samples = []
        for item in report.staff[:5]:
            samples.append({
                "parent_unit_name": item.parent_unit_name,
                "administrative_unit_name": item.administrative_unit_name,
                "person_name": item.person_name,
                "title_or_role": item.title_or_role,
                "internal_extension": item.internal_extension,
                "email": item.email,
                "source_url": item.source_url,
            })
        return samples

    @staticmethod
    def _build_diff_summary(
        existing_keys: dict[tuple[int, str], set[str]],
        current_keys: dict[tuple[int, str], set[str]],
    ) -> dict[str, Any]:
        all_sources = sorted(set(existing_keys) | set(current_keys))
        by_source = []
        total_new = 0
        total_missing = 0
        total_unchanged = 0
        for source_key in all_sources:
            before = existing_keys.get(source_key, set())
            after = current_keys.get(source_key, set())
            new_count = len(after - before)
            missing_count = len(before - after)
            unchanged_count = len(before & after)
            total_new += new_count
            total_missing += missing_count
            total_unchanged += unchanged_count
            by_source.append({
                "website_unit_id": source_key[0],
                "normalized_source_url": source_key[1],
                "new_count": new_count,
                "missing_count": missing_count,
                "unchanged_count": unchanged_count,
            })
        return {
            "new_count": total_new,
            "missing_count": total_missing,
            "unchanged_count": total_unchanged,
            "by_source": by_source,
        }

    @staticmethod
    def _write_json(path_value: str | Path | None, payload: dict[str, Any]) -> None:
        if not path_value:
            return
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="GİBTÜ idari birim/personel DB-first scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan rapor üret")
    parser.add_argument("--write-db", action="store_true", help="Structured DB tablolarına yaz")
    parser.add_argument("--report-json", default=None, help="Tam raporu JSON dosyasına yaz")
    parser.add_argument("--validation-report-json", default=None, help="Validation raporunu JSON dosyasına yaz")
    parser.add_argument("--import-summary-json", default=None, help="Import summary dosyasını yaz")
    parser.add_argument("--diff-summary-json", default=None, help="Diff summary dosyasını yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = AdministrativeStaffScraper()
    report = scraper.scrape(
        dry_run=args.dry_run or not args.write_db,
        write_db=args.write_db,
        report_json=args.report_json,
        validation_report_json=args.validation_report_json,
        import_summary_json=args.import_summary_json,
        diff_summary_json=args.diff_summary_json,
    )
    logger.info("İdari personel scrape raporu: %s", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
