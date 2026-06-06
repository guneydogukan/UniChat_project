"""
UniChat — Hedefli Akademik Takvim Scraper

Bu modül genel crawler değildir. Yalnızca GİBTÜ ana akademik takvim
sayfasını ve bu sayfanın içerik alanında doğrudan verilen akademik takvim
kaynaklarını işler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pdfplumber
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

import scrapers._encoding_fix  # noqa: F401 — Windows stdout UTF-8

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gibtu.edu.tr"
ACADEMIC_CALENDAR_URL = f"{BASE_URL}/akademiktakvim"
ALLOWED_HOSTS = {"www.gibtu.edu.tr", "gibtu.edu.tr"}
SCRAPER_NAME = "academic_calendar_scraper"
METADATA_VERSION = "academic_calendar.v1"
UNIVERSITY_NAME = "Gaziantep İslam Bilim ve Teknoloji Üniversitesi"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 0.8

CACHE_FILE = Path(__file__).resolve().parent / ".academic_calendar_sources.json"

ACADEMIC_CONTEXT_RE = re.compile(
    r"\b(akademik\s*takvim|öğrenci\s*dökümanları|ogrenci\s*dokumanlari)\b",
    re.IGNORECASE,
)

ACADEMIC_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2})\b")
DATE_SEPARATOR_RE = re.compile(r"\s+")

TURKISH_MONTHS: dict[str, int] = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}

MONTH_NAMES_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}

DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?P<d1>\d{1,2})\s*[-–—]\s*(?P<d2>\d{1,2})\s+"
        r"(?P<m2>ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
        r"\s+(?P<y2>\d{2,4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<d1>\d{1,2})\s+"
        r"(?P<m1>ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
        r"\s*[-–—]\s*(?P<d2>\d{1,2})\s+"
        r"(?P<m2>ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
        r"\s+(?P<y2>\d{2,4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<d1>\d{1,2})\s+"
        r"(?P<m1>ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
        r"\s+(?P<y1>\d{2,4})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<d1>\d{1,2})[./](?P<m1>\d{1,2})[./](?P<y1>\d{2,4})"
        r"(?:\s*[-–—]\s*(?P<d2>\d{1,2})[./](?P<m2>\d{1,2})[./](?P<y2>\d{2,4}))?\b"
    ),
)

EVENT_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("course_registration", ("ders kaydı", "ders kayıt", "ders seçimi", "ders secimi")),
    ("registration", ("kayıt yenileme", "kayit yenileme", "kesin kayıt", "kesin kayit")),
    ("add_drop", ("ekle", "bırak", "birak", "çıkarma", "cikarma")),
    ("semester_start", ("derslerin başlaması", "ders başlangıcı", "ders baslangici", "derslerin baslamasi")),
    ("semester_end", ("derslerin sona ermesi", "derslerin bitişi", "ders bitişi", "ders bitisi")),
    ("midterm", ("ara sınav", "ara sinav", "vize")),
    ("final_exam", ("yarıyıl sonu sınav", "yariyil sonu sinav", "yıl sonu sınav", "yil sonu sinav", "final")),
    ("makeup_exam", ("bütünleme", "butunleme", "büt", "but")),
    ("single_course_exam", ("tek ders",)),
    ("graduation", ("mezun", "diploma")),
    ("application", ("başvuru", "basvuru", "müracaat", "muracaat")),
    ("holiday", ("resmi tatil", "bayram", "tatil")),
    ("orientation", ("oryantasyon", "uyum")),
)

TERM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("güz yarıyılı", ("güz", "guz", "güz yarıyılı", "guz yariyili")),
    ("bahar yarıyılı", ("bahar", "bahar yarıyılı", "bahar yariyili")),
    ("yaz dönemi", ("yaz okulu", "yaz dönemi", "yaz donemi")),
)

SOURCE_TYPE_PDF = "pdf"
SOURCE_TYPE_WEB = "web"
PARSE_STATUS_PARSED = "parsed"
PARSE_STATUS_NEEDS_REVIEW = "needs_review"
HOLIDAY_SECTION_TYPE = "resmi_tatil"


@dataclass
class CalendarSource:
    source_url: str
    source_type: str
    source_title: str = "Akademik Takvim"
    html_context: str = ""
    academic_year: str | None = None
    calendar_type: str = "genel/önlisans-lisans"
    unit: str = "Genel"
    education_level: str = "onlisans_lisans"
    source_hash: str = ""


@dataclass
class AcademicCalendarEvent:
    academic_year: str | None
    calendar_type: str
    unit: str
    education_level: str
    term: str | None
    event_title: str
    event_category: str
    start_date: str | None
    end_date: str | None
    original_date_text: str
    source_page_url: str
    source_file_url: str | None
    source_type: str
    page_number: int | None
    row_index: int | None
    file_hash: str
    content_hash: str
    parse_status: str
    confidence_score: float
    is_active: bool
    is_superseded: bool
    last_checked_at: str
    parsed_at: str
    section_title: str | None = None
    section_type: str | None = None
    section_note: str | None = None
    note: str | None = None
    merged_from_rows: list[dict[str, Any]] = field(default_factory=list)
    parse_status_reason: str | None = None


@dataclass
class HolidaySectionContext:
    active: bool = False
    section_title: str | None = None
    section_note: str | None = None
    last_event: AcademicCalendarEvent | None = None


@dataclass
class AcademicCalendarScrapeReport:
    success: bool = False
    dry_run: bool = False
    source_page_url: str = ACADEMIC_CALENDAR_URL
    checked_at: str = ""
    sources_discovered: int = 0
    sources_processed: int = 0
    sources_unchanged: int = 0
    events_created: int = 0
    review_events: int = 0
    chunks_written: int = 0
    holiday_events: int = 0
    ready_for_db: bool | None = None
    holiday_event_examples: list[dict[str, Any]] = field(default_factory=list)
    merged_rows: list[dict[str, Any]] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _single_line(text: str | None) -> str:
    return " ".join(_clean_text(text).split())


def _normalize_for_match(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return value


def _slug(value: str, max_len: int = 80) -> str:
    value = _normalize_for_match(value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "event")[:max_len].strip("-")


def _normalize_url(url: str, base_url: str = ACADEMIC_CALENDAR_URL) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None

    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in ALLOWED_HOSTS:
        return None
    return absolute


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _extract_academic_year(text: str) -> str | None:
    match = ACADEMIC_YEAR_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _infer_source_metadata(source_url: str, context: str) -> dict[str, str | None]:
    combined = f"{context} {urlparse(source_url).path}".replace("_", " ")
    normalized = _normalize_for_match(combined)
    exclusion_context = "haric" in normalized or "hariç" in combined.casefold()

    calendar_type = "genel/önlisans-lisans"
    unit = "Genel"
    education_level = "onlisans_lisans"

    if ("tip" in normalized or "tıp" in combined.casefold()) and not exclusion_context:
        calendar_type = "tıp fakültesi"
        unit = "Tıp Fakültesi"
        education_level = "lisans"
    elif ("lisansustu" in normalized or "enstitu" in normalized) and not exclusion_context:
        calendar_type = "lisansüstü"
        unit = "Lisansüstü Eğitim Enstitüsü"
        education_level = "lisansustu"
    elif "tomer" in normalized or "tömer" in combined.casefold():
        calendar_type = "tömer"
        unit = "Türkçe Öğretimi Uygulama ve Araştırma Merkezi"
        education_level = "dil_egitimi"
    elif ("yabanci diller" in normalized or "hazirlik" in normalized) and not exclusion_context:
        calendar_type = "yabancı diller/hazırlık"
        unit = "Yabancı Diller Yüksekokulu"
        education_level = "hazirlik"
    elif "onlisans" in normalized and "lisans" in normalized:
        calendar_type = "genel/önlisans-lisans"
        education_level = "onlisans_lisans"

    return {
        "academic_year": _extract_academic_year(combined),
        "calendar_type": calendar_type,
        "unit": unit,
        "education_level": education_level,
    }


def _infer_term(text: str, fallback: str | None = None) -> str | None:
    normalized = _normalize_for_match(text)
    for term, needles in TERM_RULES:
        if any(_normalize_for_match(needle) in normalized for needle in needles):
            return term
    return fallback


def _classify_event(title: str) -> str:
    normalized = _normalize_for_match(title)
    for category, needles in EVENT_CATEGORY_RULES:
        if any(_normalize_for_match(needle) in normalized for needle in needles):
            return category
    return "other"


def _year_to_int(value: str | None) -> int | None:
    if not value:
        return None
    year = int(value)
    if year < 100:
        return 2000 + year
    return year


def _parse_month(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        month = int(value)
        return month if 1 <= month <= 12 else None
    return TURKISH_MONTHS.get(value.casefold())


def _safe_date(year: int | None, month: int | None, day: str | None) -> date | None:
    if year is None or month is None or day is None:
        return None
    try:
        return date(year, month, int(day))
    except ValueError:
        return None


def _extract_date_ranges(text: str) -> list[tuple[str, str, str]]:
    """Metindeki desteklenen Türkçe/numerik tarihleri ISO aralıklarına çevirir."""
    if not text:
        return []

    normalized_text = _single_line(text)
    ranges: list[tuple[str, str, str]] = []
    seen_spans: set[tuple[int, int]] = set()

    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(normalized_text):
            span = match.span()
            if any(not (span[1] <= old[0] or span[0] >= old[1]) for old in seen_spans):
                continue

            groups = match.groupdict()
            y2 = _year_to_int(groups.get("y2"))
            y1 = _year_to_int(groups.get("y1")) or y2
            m2 = _parse_month(groups.get("m2")) or _parse_month(groups.get("m1"))
            m1 = _parse_month(groups.get("m1")) or m2
            d1 = groups.get("d1")
            d2 = groups.get("d2") or d1

            start = _safe_date(y1, m1, d1)
            end = _safe_date(y2 or y1, m2, d2)
            if not start or not end:
                continue
            if end < start:
                start, end = end, start

            seen_spans.add(span)
            original = DATE_SEPARATOR_RE.sub(" ", match.group(0).strip())
            ranges.append((start.isoformat(), end.isoformat(), original))

    return ranges


def parse_date_range(text: str) -> tuple[str | None, str | None, str]:
    ranges = _extract_date_ranges(text)
    if not ranges:
        return None, None, ""
    start, end, original = ranges[0]
    return start, end, original


def _format_iso_date(iso_value: str | None) -> str:
    if not iso_value:
        return ""
    try:
        parsed = date.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    return f"{parsed.day} {MONTH_NAMES_TR[parsed.month]} {parsed.year}"


def _format_date_range(start_date: str | None, end_date: str | None, original: str = "") -> str:
    if original:
        return original
    if not start_date:
        return "tarihi parse incelemesi gerektiriyor"
    if not end_date or end_date == start_date:
        return _format_iso_date(start_date)
    return f"{_format_iso_date(start_date)} - {_format_iso_date(end_date)}"


def _header_term_for_column(header_cells: list[str], column_index: int) -> str | None:
    if not header_cells:
        return None
    candidates = []
    if column_index < len(header_cells):
        candidates.append(header_cells[column_index])
    if column_index > 0 and column_index - 1 < len(header_cells):
        candidates.append(header_cells[column_index - 1])
    for candidate in candidates:
        term = _infer_term(candidate)
        if term:
            return term
    return None


def _is_header_like(cells: list[str]) -> bool:
    combined = _normalize_for_match(" ".join(cells))
    header_terms = ("tarih", "faaliyet", "etkinlik", "guz", "bahar", "yariyil", "donem")
    has_header_word = any(term in combined for term in header_terms)
    has_date = any(_extract_date_ranges(cell) for cell in cells)
    return has_header_word and not has_date


def _clean_event_title(text: str) -> str:
    text = _single_line(text)
    for _, _, original in _extract_date_ranges(text):
        text = text.replace(original, " ")
    text = re.sub(r"\b(güz|bahar|yaz)\s+(yarıyılı|yariyili|dönemi|donemi)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(tarih|faaliyet|etkinlik|açıklama|aciklama)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;|")
    return text


def _is_placeholder_cell(text: str) -> bool:
    return not text or text.strip() in {"-", "–", "—"}


def _is_review_worthy_row(text: str) -> bool:
    normalized = _normalize_for_match(text)
    if len(normalized) < 12:
        return False
    if ACADEMIC_YEAR_RE.fullmatch(text.strip()):
        return False
    if any(term in normalized for term in ("akademik takvim", "gaziantep islam", "universitesi")):
        return False
    event_needles = [
        "kayit", "ders", "sinav", "vize", "final", "butunleme", "basvuru",
        "mezun", "yariyil", "donem", "tatil", "bayram", "oryantasyon",
    ]
    return any(needle in normalized for needle in event_needles)


def _is_holiday_section_header(text: str) -> bool:
    normalized = _normalize_for_match(text)
    return "resmi tatil gunleri" in normalized


def _is_note_row(text: str) -> bool:
    return bool(re.match(r"^\s*not\s*:", _normalize_for_match(text)))


def _clean_note_text(text: str) -> str:
    return re.sub(r"^\s*not\s*:\s*", "", _single_line(text), flags=re.IGNORECASE).strip()


def _is_arife_title(title: str) -> bool:
    return "arife" in _normalize_for_match(title)


def _is_weekday_fragment(text: str) -> bool:
    return _normalize_for_match(text) in {
        "pazartesi",
        "sali",
        "carsamba",
        "persembe",
        "cuma",
        "cumartesi",
        "pazar",
    }


def _is_official_holiday_title(title: str) -> bool:
    normalized = _normalize_for_match(title)
    needles = (
        "bayram",
        "tatil",
        "arife",
        "yilbasi",
        "cumhuriyet",
        "ulusal egemenlik",
        "cocuk",
        "emek",
        "dayanisma",
        "ataturk",
        "genclik",
        "spor",
        "demokrasi",
        "milli birlik",
        "zafer",
    )
    return any(needle in normalized for needle in needles)


def _normalize_official_holiday_title(title: str) -> str:
    normalized = _normalize_for_match(title)
    if all(needle in normalized for needle in ("ataturk", "genclik", "spor bayrami")):
        return "Atatürk’ü Anma, Gençlik ve Spor Bayramı"
    return title


def _is_probable_holiday_continuation(text: str, previous_title: str | None) -> bool:
    row_text = _clean_event_title(text)
    normalized = _normalize_for_match(row_text)
    if not normalized or _extract_date_ranges(row_text):
        return False
    if _is_weekday_fragment(row_text):
        return False
    if _is_holiday_section_header(row_text) or _is_note_row(row_text):
        return False

    previous_normalized = _normalize_for_match(previous_title or "")
    known_fragments = {"spor bayrami"}
    if normalized in known_fragments:
        return True
    return bool(previous_normalized.endswith(" ve") and len(normalized) <= 60)


def _holiday_event_title_from_row(cells: list[str], parsed_date_indexes: set[int]) -> str:
    title_cells = [
        cell
        for index, cell in enumerate(cells)
        if index not in parsed_date_indexes and not _is_placeholder_cell(cell)
    ]
    title = _clean_event_title(" ".join(title_cells))
    if title:
        return title
    return _clean_event_title(" ".join(cells))


class AcademicCalendarScraper:
    """GİBTÜ akademik takvim sayfasından event bazlı Document üretir."""

    def __init__(
        self,
        url: str = ACADEMIC_CALENDAR_URL,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        cache_file: Path = CACHE_FILE,
    ) -> None:
        self.url = url
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0; +https://www.gibtu.edu.tr)"})
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.rate_limit_seconds = rate_limit_seconds
        self.cache_file = cache_file
        self._last_request_at = 0.0
        self._holiday_parse_audit: dict[str, list[dict[str, Any]]] = {
            "merged_rows": [],
            "skipped_rows": [],
        }
        self._assert_allowed_url(self.url)

    def scrape(
        self,
        dry_run: bool = False,
        force: bool = False,
        skip_unchanged: bool = True,
        report_json: str | Path | None = None,
    ) -> AcademicCalendarScrapeReport:
        """Fetch → discover → parse → version/supersede → ingest akışını çalıştırır."""
        checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        report = AcademicCalendarScrapeReport(dry_run=dry_run, checked_at=checked_at)
        self._holiday_parse_audit = {"merged_rows": [], "skipped_rows": []}

        try:
            html = self.fetch_text(self.url)
            sources = self.discover_calendar_sources(html)
            report.sources_discovered = len(sources)
            report.source_urls = [source.source_url for source in sources]
        except Exception as exc:  # noqa: BLE001 - rapora açık hata
            report.errors.append(f"Ana akademik takvim sayfası alınamadı: {exc}")
            self._maybe_write_report(report, report_json)
            return report

        if not sources:
            report.errors.append("Ana URL'de doğrudan akademik takvim kaynağı bulunamadı.")
            logger.warning(report.errors[-1])
            self._maybe_write_report(report, report_json)
            return report

        all_documents: list[Document] = []
        processed_hashes: dict[str, str] = {}

        for source in sources:
            try:
                documents, source_hash = self._process_source(source, checked_at=checked_at)
                source.source_hash = source_hash
                processed_hashes[source.source_url] = source_hash

                if (
                    skip_unchanged
                    and not dry_run
                    and not force
                    and self._source_unchanged(source.source_url, source_hash)
                ):
                    report.sources_unchanged += 1
                    logger.info("Akademik takvim kaynağı değişmemiş, atlandı: %s", source.source_url)
                    continue

                report.sources_processed += 1
                report.events_created += len(documents)
                report.review_events += sum(
                    1 for doc in documents
                    if (doc.meta or {}).get("parse_status") == PARSE_STATUS_NEEDS_REVIEW
                )
                all_documents.extend(documents)
            except Exception as exc:  # noqa: BLE001 - diğer kaynaklar işlenmeye devam eder
                logger.error("Akademik takvim kaynağı işlenemedi: %s — %s", source.source_url, exc, exc_info=True)
                report.errors.append(f"{source.source_url}: {exc}")

        if not all_documents:
            report.success = report.sources_unchanged > 0 and not report.errors
            self._populate_report_details(report, all_documents)
            self._update_cache(processed_hashes)
            self._maybe_write_report(report, report_json)
            return report

        self._populate_report_details(report, all_documents)
        if dry_run:
            report.chunks_written = len(all_documents)
            report.success = True
            self._maybe_write_report(report, report_json)
            return report

        try:
            for source in sources:
                if source.source_hash and processed_hashes.get(source.source_url) == source.source_hash:
                    self._supersede_previous_source(source.source_url, source.source_hash)

            report.chunks_written = self._ingest(all_documents)
            self._cleanup_stale_current_source_events(all_documents)
            report.success = report.chunks_written > 0
            self._update_cache(processed_hashes)
        except Exception as exc:  # noqa: BLE001 - rapora açık hata
            report.errors.append(f"Ingestion hatası: {exc}")
            report.success = False

        self._maybe_write_report(report, report_json)
        return report

    def fetch_text(self, url: str) -> str:
        raw, content_type = self.fetch_bytes(url)
        encoding = self._encoding_from_content_type(content_type)
        candidates = [encoding, "utf-8", "windows-1254", "iso-8859-9"]
        for candidate in [item for item in candidates if item]:
            try:
                return raw.decode(candidate)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def fetch_bytes(self, url: str) -> tuple[bytes, str]:
        self._assert_allowed_url(url)
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                self._assert_allowed_url(response.url)
                self._last_request_at = time.time()
                return response.content, response.headers.get("content-type", "")
            except Exception as exc:  # noqa: BLE001 - retry raporu
                last_error = exc
                logger.warning("Akademik takvim fetch hatası (%d/%d): %s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * attempt)
        raise RuntimeError(f"Kaynak alınamadı: {last_error}")

    def discover_calendar_sources(self, html_text: str) -> list[CalendarSource]:
        """Ana sayfa içerik bloğundaki doğrudan akademik takvim kaynaklarını bulur."""
        soup = BeautifulSoup(html_text, "html.parser")
        content_root = (
            soup.select_one("div.page_body")
            or soup.select_one("div.card-content")
            or soup.find("body")
            or soup
        )

        for selector in ["nav", "header", "footer", "script", "style", "noscript", ".side-nav"]:
            for element in content_root.select(selector):
                element.decompose()

        sources: list[CalendarSource] = []
        seen: set[str] = set()

        def add_source(raw_url: str | None, node: Tag, source_type: str | None = None) -> None:
            normalized_url = _normalize_url(raw_url or "", self.url)
            if not normalized_url or normalized_url in seen:
                return
            context = self._node_context(node)
            is_pdf = _is_pdf_url(normalized_url)
            if not is_pdf and not ACADEMIC_CONTEXT_RE.search(context):
                return
            if "adobe.com" in normalized_url.lower():
                return

            inferred = _infer_source_metadata(normalized_url, context)
            title = self._source_title_from_context(context, normalized_url)
            sources.append(
                CalendarSource(
                    source_url=normalized_url,
                    source_type=source_type or (SOURCE_TYPE_PDF if is_pdf else SOURCE_TYPE_WEB),
                    source_title=title,
                    html_context=context,
                    academic_year=inferred["academic_year"],
                    calendar_type=str(inferred["calendar_type"]),
                    unit=str(inferred["unit"]),
                    education_level=str(inferred["education_level"]),
                )
            )
            seen.add(normalized_url)

        for node in content_root.select("object[data], iframe[src], embed[src]"):
            add_source(node.get("data") or node.get("src"), node)

        for node in content_root.select("a[href]"):
            add_source(node.get("href"), node)

        if self._content_has_calendar_table_or_text(content_root):
            inferred = _infer_source_metadata(self.url, content_root.get_text(" ", strip=True))
            sources.append(
                CalendarSource(
                    source_url=self.url,
                    source_type=SOURCE_TYPE_WEB,
                    source_title="Akademik Takvim",
                    html_context=_single_line(content_root.get_text(" ", strip=True)),
                    academic_year=inferred["academic_year"],
                    calendar_type=str(inferred["calendar_type"]),
                    unit=str(inferred["unit"]),
                    education_level=str(inferred["education_level"]),
                )
            )

        return sources

    def _process_source(self, source: CalendarSource, checked_at: str) -> tuple[list[Document], str]:
        if source.source_type == SOURCE_TYPE_PDF or _is_pdf_url(source.source_url):
            raw, _ = self.fetch_bytes(source.source_url)
            source_hash = _sha256_bytes(raw)
            events = self.parse_pdf_events(source, raw, source_hash, checked_at)
        else:
            html_text = self.fetch_text(source.source_url)
            source_hash = _sha256_text(html_text)
            events = self.parse_html_events(source, html_text, source_hash, checked_at)

        documents = [self.event_to_document(event) for event in events]
        return documents, source_hash

    def _populate_report_details(self, report: AcademicCalendarScrapeReport, documents: list[Document]) -> None:
        holiday_docs = [
            doc for doc in documents
            if (doc.meta or {}).get("event_category") == "holiday"
            or (doc.meta or {}).get("section_type") == HOLIDAY_SECTION_TYPE
        ]
        review_docs = [
            doc for doc in documents
            if (doc.meta or {}).get("parse_status") == PARSE_STATUS_NEEDS_REVIEW
        ]
        report.holiday_events = len(holiday_docs)
        report.review_events = len(review_docs)
        report.ready_for_db = bool(documents) and not review_docs and not report.errors
        report.merged_rows = list(self._holiday_parse_audit.get("merged_rows", []))
        report.skipped_rows = list(self._holiday_parse_audit.get("skipped_rows", []))
        example_docs = list(holiday_docs[:8])
        seen_example_ids = {id(doc) for doc in example_docs}
        for doc in holiday_docs:
            if (doc.meta or {}).get("merged_from_rows") and id(doc) not in seen_example_ids:
                example_docs.append(doc)
                seen_example_ids.add(id(doc))
        report.holiday_event_examples = [
            {
                "event_title": doc.meta.get("event_title"),
                "start_date": doc.meta.get("start_date"),
                "end_date": doc.meta.get("end_date"),
                "original_date_text": doc.meta.get("original_date_text"),
                "section_title": doc.meta.get("section_title"),
                "note": doc.meta.get("note"),
                "merged_from_rows": doc.meta.get("merged_from_rows"),
                "page_number": doc.meta.get("page_number"),
                "row_index": doc.meta.get("row_index"),
                "parse_status": doc.meta.get("parse_status"),
            }
            for doc in example_docs
        ]

    def _audit_holiday_row(
        self,
        row_type: str,
        text: str,
        page_number: int | None,
        row_index: int | None,
        section_title: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row_info: dict[str, Any] = {
            "row_type": row_type,
            "text": _single_line(text),
            "page_number": page_number,
            "row_index": row_index,
            "section_title": section_title,
        }
        if extra:
            row_info.update(extra)
        bucket = "merged_rows" if row_type == "merged_continuation" else "skipped_rows"
        self._holiday_parse_audit.setdefault(bucket, []).append(row_info)

    def _handle_holiday_control_row(
        self,
        cells: list[str],
        context: HolidaySectionContext | None,
        page_number: int | None,
        row_index: int | None,
    ) -> bool:
        if context is None:
            return False

        row_text = _single_line(" ".join(cells))
        if _is_holiday_section_header(row_text):
            context.active = True
            context.section_title = row_text
            context.last_event = None
            self._audit_holiday_row("section_header", row_text, page_number, row_index, context.section_title)
            return True

        if context.active and _is_note_row(row_text):
            context.section_note = _clean_note_text(row_text) or row_text
            self._audit_holiday_row(
                "section_note",
                row_text,
                page_number,
                row_index,
                context.section_title,
                {"note": context.section_note},
            )
            return True

        return False

    @staticmethod
    def _refresh_event_content_hash(event: AcademicCalendarEvent) -> None:
        content_hash_seed = "|".join(
            [
                event.academic_year or "",
                event.calendar_type,
                event.unit,
                event.term or "",
                event.event_title,
                event.event_category,
                event.start_date or "",
                event.end_date or "",
                event.original_date_text,
                event.file_hash,
                event.section_title or "",
                event.section_type or "",
                event.section_note or "",
                event.note or "",
            ]
        )
        event.content_hash = _sha256_text(content_hash_seed)

    def _apply_holiday_section_note(
        self,
        events: list[AcademicCalendarEvent],
        context: HolidaySectionContext,
    ) -> None:
        if not context.section_note:
            return
        for event in events:
            if event.section_type != HOLIDAY_SECTION_TYPE:
                continue
            event.section_note = context.section_note
            if _is_arife_title(event.event_title):
                event.note = context.section_note
            self._refresh_event_content_hash(event)

    def parse_pdf_events(
        self,
        source: CalendarSource,
        pdf_bytes: bytes,
        file_hash: str,
        checked_at: str,
    ) -> list[AcademicCalendarEvent]:
        events: list[AcademicCalendarEvent] = []
        parsed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        inherited_term: str | None = None
        header_cells: list[str] = []
        first_text_chunks: list[str] = []
        holiday_context = HolidaySectionContext()

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text(layout=True) or page.extract_text() or ""
                if page_number <= 2 and page_text:
                    first_text_chunks.append(page_text[:2500])

                table_count_before = len(events)
                for table in self._extract_tables_from_page(page):
                    for row_index, row in enumerate(table, start=1):
                        cells = [_single_line(str(cell or "")) for cell in row]
                        if not any(cells):
                            continue

                        row_term = _infer_term(" ".join(cells), inherited_term)
                        if row_term:
                            inherited_term = row_term

                        if self._handle_holiday_control_row(cells, holiday_context, page_number, row_index):
                            continue

                        if _is_header_like(cells):
                            header_cells = self._merge_header_cells(header_cells, cells)
                            continue

                        events.extend(
                            self._events_from_row(
                                cells=cells,
                                source=source,
                                file_hash=file_hash,
                                checked_at=checked_at,
                                parsed_at=parsed_at,
                                page_number=page_number,
                                row_index=row_index,
                                inherited_term=inherited_term,
                                header_cells=header_cells,
                                parser_confidence=0.86,
                                holiday_context=holiday_context,
                            )
                        )

                if len(events) == table_count_before and page_text:
                    events.extend(
                        self._events_from_text(
                            text=page_text,
                            source=source,
                            file_hash=file_hash,
                            checked_at=checked_at,
                            parsed_at=parsed_at,
                            page_number=page_number,
                            inherited_term=inherited_term,
                            holiday_context=holiday_context,
                        )
                    )

        self._apply_holiday_section_note(events, holiday_context)
        combined_text = "\n".join(first_text_chunks)
        detected_year = _extract_academic_year(combined_text)
        inferred_from_pdf = _infer_source_metadata(source.source_url, combined_text)
        if detected_year:
            for event in events:
                if not event.academic_year:
                    event.academic_year = detected_year
        if (
            source.calendar_type == "genel/önlisans-lisans"
            and inferred_from_pdf["calendar_type"] != "genel/önlisans-lisans"
        ):
            for event in events:
                event.calendar_type = str(inferred_from_pdf["calendar_type"])
                event.unit = str(inferred_from_pdf["unit"])
                event.education_level = str(inferred_from_pdf["education_level"])

        return self._dedupe_events(events)

    def parse_html_events(
        self,
        source: CalendarSource,
        html_text: str,
        source_hash: str,
        checked_at: str,
    ) -> list[AcademicCalendarEvent]:
        soup = BeautifulSoup(html_text, "html.parser")
        root = soup.select_one("div.page_body") or soup.find("body") or soup
        for selector in ["nav", "header", "footer", "script", "style", "noscript"]:
            for element in root.select(selector):
                element.decompose()

        parsed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        events: list[AcademicCalendarEvent] = []
        inherited_term: str | None = None
        header_cells: list[str] = []
        holiday_context = HolidaySectionContext()

        for table_index, table in enumerate(root.select("table"), start=1):
            for row_index, tr in enumerate(table.select("tr"), start=1):
                cells = [_single_line(cell.get_text(" ", strip=True)) for cell in tr.select("th, td")]
                if not any(cells):
                    continue
                row_term = _infer_term(" ".join(cells), inherited_term)
                if row_term:
                    inherited_term = row_term
                if self._handle_holiday_control_row(cells, holiday_context, None, (table_index * 1000) + row_index):
                    continue
                if _is_header_like(cells):
                    header_cells = self._merge_header_cells(header_cells, cells)
                    continue
                events.extend(
                    self._events_from_row(
                        cells=cells,
                        source=source,
                        file_hash=source_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        page_number=None,
                        row_index=(table_index * 1000) + row_index,
                        inherited_term=inherited_term,
                        header_cells=header_cells,
                        parser_confidence=0.82,
                        holiday_context=holiday_context,
                    )
                )

        if not events:
            events.extend(
                self._events_from_text(
                    text=root.get_text("\n", strip=True),
                    source=source,
                    file_hash=source_hash,
                    checked_at=checked_at,
                    parsed_at=parsed_at,
                    page_number=None,
                    inherited_term=inherited_term,
                    holiday_context=holiday_context,
                )
            )

        self._apply_holiday_section_note(events, holiday_context)
        return self._dedupe_events(events)

    def event_to_document(self, event: AcademicCalendarEvent) -> Document:
        content = self._event_representation(event)
        event.content_hash = _sha256_text(content)
        source_key = event.source_file_url or event.source_page_url
        source_hash_part = event.file_hash[:16] if event.file_hash else _sha256_text(source_key)[:16]
        event_key = _slug(
            "|".join(
                [
                    event.academic_year or "",
                    event.calendar_type,
                    event.term or "",
                    event.event_title,
                    event.original_date_text,
                    str(event.page_number or ""),
                    str(event.row_index or ""),
                ]
            ),
            max_len=140,
        )
        location_key = f"p{event.page_number or 0}r{event.row_index or 0}"
        source_id = f"academic_calendar/{source_hash_part}/{event_key}/{location_key}/{event.content_hash[:12]}"

        meta = {
            "metadata_version": METADATA_VERSION,
            "category": "academic_calendar",
            "doc_kind": "academic_calendar_event",
            "source_url": event.source_file_url or event.source_page_url,
            "source_public_url": event.source_file_url or event.source_page_url,
            "source_type": event.source_type,
            "source_id": source_id,
            "last_updated": event.last_checked_at,
            "title": event.event_title,
            "language": "tr",
            "scraper_name": SCRAPER_NAME,
            "university": UNIVERSITY_NAME,
            "official_source": True,
            "is_official": True,
            **asdict(event),
        }
        return Document(id=_sha256_text(source_id), content=content, meta=meta)

    def _holiday_events_from_row(
        self,
        cells: list[str],
        parsed_date_cells: list[tuple[int, str, tuple[str | None, str | None, str]]],
        combined: str,
        source: CalendarSource,
        file_hash: str,
        checked_at: str,
        parsed_at: str,
        academic_year: str | None,
        page_number: int | None,
        row_index: int | None,
        parser_confidence: float,
        holiday_context: HolidaySectionContext,
    ) -> list[AcademicCalendarEvent] | None:
        if not holiday_context.active:
            return None

        if parsed_date_cells:
            date_index, _date_cell, parsed = parsed_date_cells[0]
            title = _normalize_official_holiday_title(_holiday_event_title_from_row(cells, {date_index}))
            if not _is_official_holiday_title(title):
                return None
            start, end, original = parsed
            event = self._make_event(
                source=source,
                file_hash=file_hash,
                checked_at=checked_at,
                parsed_at=parsed_at,
                academic_year=academic_year,
                term=None,
                event_title=title or "Resmî tatil",
                start_date=start,
                end_date=end,
                original_date_text=original,
                source_type=source.source_type,
                page_number=page_number,
                row_index=row_index,
                parse_status=PARSE_STATUS_PARSED,
                confidence_score=parser_confidence,
                event_category_override="holiday",
                section_title=holiday_context.section_title,
                section_type=HOLIDAY_SECTION_TYPE,
                section_note=holiday_context.section_note,
                note=holiday_context.section_note if _is_arife_title(title) else None,
            )
            holiday_context.last_event = event
            return [event]

        ranges = _extract_date_ranges(combined)
        if ranges:
            start, end, original = ranges[0]
            title = _normalize_official_holiday_title(_clean_event_title(combined))
            if not _is_official_holiday_title(title):
                return None
            event = self._make_event(
                source=source,
                file_hash=file_hash,
                checked_at=checked_at,
                parsed_at=parsed_at,
                academic_year=academic_year,
                term=None,
                event_title=title or "Resmî tatil",
                start_date=start,
                end_date=end,
                original_date_text=original,
                source_type=source.source_type,
                page_number=page_number,
                row_index=row_index,
                parse_status=PARSE_STATUS_PARSED,
                confidence_score=round(parser_confidence - 0.03, 2),
                event_category_override="holiday",
                section_title=holiday_context.section_title,
                section_type=HOLIDAY_SECTION_TYPE,
                section_note=holiday_context.section_note,
                note=holiday_context.section_note if _is_arife_title(title) else None,
            )
            holiday_context.last_event = event
            return [event]

        row_text = _clean_event_title(combined)
        if (
            holiday_context.last_event
            and _is_probable_holiday_continuation(row_text, holiday_context.last_event.event_title)
        ):
            previous_title = holiday_context.last_event.event_title
            holiday_context.last_event.event_title = _normalize_official_holiday_title(
                _single_line(f"{previous_title} {row_text}")
            )
            holiday_context.last_event.merged_from_rows.append(
                {
                    "text": row_text,
                    "page_number": page_number,
                    "row_index": row_index,
                }
            )
            self._refresh_event_content_hash(holiday_context.last_event)
            self._audit_holiday_row(
                "merged_continuation",
                row_text,
                page_number,
                row_index,
                holiday_context.section_title,
                {
                    "merged_into_title": holiday_context.last_event.event_title,
                    "previous_title": previous_title,
                },
            )
            return []

        if _is_review_worthy_row(row_text) and _is_official_holiday_title(row_text):
            return [
                self._make_event(
                    source=source,
                    file_hash=file_hash,
                    checked_at=checked_at,
                    parsed_at=parsed_at,
                    academic_year=academic_year,
                    term=None,
                    event_title=row_text,
                    start_date=None,
                    end_date=None,
                    original_date_text="",
                    source_type=source.source_type,
                    page_number=page_number,
                    row_index=row_index,
                    parse_status=PARSE_STATUS_NEEDS_REVIEW,
                    confidence_score=0.35,
                    event_category_override="holiday",
                    section_title=holiday_context.section_title,
                    section_type=HOLIDAY_SECTION_TYPE,
                    section_note=holiday_context.section_note,
                    parse_status_reason="Tarihsiz resmî tatil satırı güvenle birleştirilemedi.",
                )
            ]
        if _is_review_worthy_row(row_text):
            return None

        return []

    def _events_from_row(
        self,
        cells: list[str],
        source: CalendarSource,
        file_hash: str,
        checked_at: str,
        parsed_at: str,
        page_number: int | None,
        row_index: int | None,
        inherited_term: str | None,
        header_cells: list[str],
        parser_confidence: float,
        holiday_context: HolidaySectionContext | None = None,
    ) -> list[AcademicCalendarEvent]:
        date_cells = [(index, cell, parse_date_range(cell)) for index, cell in enumerate(cells)]
        parsed_date_cells = [
            (index, cell, parsed)
            for index, cell, parsed in date_cells
            if parsed[0] and parsed[1]
        ]

        combined = " ".join(cells)
        inferred_year = _extract_academic_year(combined) or source.academic_year

        if self._handle_holiday_control_row(cells, holiday_context, page_number, row_index):
            return []

        if holiday_context and holiday_context.active:
            holiday_events = self._holiday_events_from_row(
                cells=cells,
                parsed_date_cells=parsed_date_cells,
                combined=combined,
                source=source,
                file_hash=file_hash,
                checked_at=checked_at,
                parsed_at=parsed_at,
                academic_year=inferred_year,
                page_number=page_number,
                row_index=row_index,
                parser_confidence=parser_confidence,
                holiday_context=holiday_context,
            )
            if holiday_events is not None:
                return holiday_events

        if not parsed_date_cells:
            ranges = _extract_date_ranges(combined)
            if ranges:
                start, end, original = ranges[0]
                title = _clean_event_title(combined)
                return [
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=inferred_year,
                        term=_infer_term(combined, inherited_term),
                        event_title=title or "Akademik takvim etkinliği",
                        start_date=start,
                        end_date=end,
                        original_date_text=original,
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_PARSED,
                        confidence_score=round(parser_confidence - 0.08, 2),
                    )
                ]

            row_text = _clean_event_title(combined)
            if _is_review_worthy_row(row_text):
                return [
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=inferred_year,
                        term=_infer_term(combined, inherited_term),
                        event_title=row_text,
                        start_date=None,
                        end_date=None,
                        original_date_text="",
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_NEEDS_REVIEW,
                        confidence_score=0.35,
                    )
                ]
            return []

        title_parts = [
            cell
            for index, cell in enumerate(cells)
            if index not in {date_index for date_index, _, _ in parsed_date_cells}
            and not _is_placeholder_cell(cell)
        ]
        title = _clean_event_title(" ".join(title_parts)) or _clean_event_title(combined)

        paired_events = self._paired_range_events_from_row(
            parsed_date_cells=parsed_date_cells,
            cells=cells,
            title=title,
            source=source,
            file_hash=file_hash,
            checked_at=checked_at,
            parsed_at=parsed_at,
            academic_year=inferred_year,
            page_number=page_number,
            row_index=row_index,
            inherited_term=inherited_term,
            header_cells=header_cells,
            parser_confidence=parser_confidence,
        )
        if paired_events is not None:
            return paired_events

        events: list[AcademicCalendarEvent] = []

        for date_index, cell, parsed in parsed_date_cells:
            start, end, original = parsed
            term = (
                _infer_term(cell)
                or _header_term_for_column(header_cells, date_index)
                or _infer_term(combined, inherited_term)
            )
            events.append(
                self._make_event(
                    source=source,
                    file_hash=file_hash,
                    checked_at=checked_at,
                    parsed_at=parsed_at,
                    academic_year=inferred_year,
                    term=term,
                    event_title=title or "Akademik takvim etkinliği",
                    start_date=start,
                    end_date=end,
                    original_date_text=original,
                    source_type=source.source_type,
                    page_number=page_number,
                    row_index=row_index,
                    parse_status=PARSE_STATUS_PARSED,
                    confidence_score=parser_confidence,
                )
            )

        return events

    def _paired_range_events_from_row(
        self,
        parsed_date_cells: list[tuple[int, str, tuple[str | None, str | None, str]]],
        cells: list[str],
        title: str,
        source: CalendarSource,
        file_hash: str,
        checked_at: str,
        parsed_at: str,
        academic_year: str | None,
        page_number: int | None,
        row_index: int | None,
        inherited_term: str | None,
        header_cells: list[str],
        parser_confidence: float,
    ) -> list[AcademicCalendarEvent] | None:
        """Başlangıç/bitiş sütun çiftlerini tek event aralığına dönüştürür."""
        if len(parsed_date_cells) < 2:
            return None

        events: list[AcademicCalendarEvent] = []
        used: set[int] = set()
        parsed_by_index = {index: (cell, parsed) for index, cell, parsed in parsed_date_cells}
        has_pair = False

        for index, cell, parsed in parsed_date_cells:
            if index in used:
                continue

            next_item = parsed_by_index.get(index + 1)
            term = _header_term_for_column(header_cells, index) or _infer_term(cell, inherited_term)
            next_term = _header_term_for_column(header_cells, index + 1) if next_item else None
            if next_item and term and next_term == term:
                next_cell, next_parsed = next_item
                start = parsed[0]
                end = next_parsed[1] or next_parsed[0]
                original = f"{parsed[2]} - {next_parsed[2]}".strip(" -")
                events.append(
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=academic_year,
                        term=term,
                        event_title=title or "Akademik takvim etkinliği",
                        start_date=start,
                        end_date=end,
                        original_date_text=original,
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_PARSED,
                        confidence_score=parser_confidence,
                    )
                )
                used.update({index, index + 1})
                has_pair = True
                continue

            if index not in used:
                start, end, original = parsed
                events.append(
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=academic_year,
                        term=term or _infer_term(" ".join(cells), inherited_term),
                        event_title=title or "Akademik takvim etkinliği",
                        start_date=start,
                        end_date=end,
                        original_date_text=original,
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_PARSED,
                        confidence_score=parser_confidence,
                    )
                )
                used.add(index)

        return events if has_pair else None

    def _events_from_text(
        self,
        text: str,
        source: CalendarSource,
        file_hash: str,
        checked_at: str,
        parsed_at: str,
        page_number: int | None,
        inherited_term: str | None,
        holiday_context: HolidaySectionContext | None = None,
    ) -> list[AcademicCalendarEvent]:
        events: list[AcademicCalendarEvent] = []
        current_term = inherited_term
        lines = [_single_line(line) for line in text.splitlines()]
        row_index = 0

        for line in lines:
            if not line:
                continue
            row_index += 1
            line_term = _infer_term(line, current_term)
            if line_term:
                current_term = line_term

            if self._handle_holiday_control_row([line], holiday_context, page_number, row_index):
                continue

            if holiday_context and holiday_context.active:
                parsed = parse_date_range(line)
                parsed_date_cells = [(0, line, parsed)] if parsed[0] and parsed[1] else []
                holiday_events = self._holiday_events_from_row(
                    cells=[line],
                    parsed_date_cells=parsed_date_cells,
                    combined=line,
                    source=source,
                    file_hash=file_hash,
                    checked_at=checked_at,
                    parsed_at=parsed_at,
                    academic_year=_extract_academic_year(line) or source.academic_year,
                    page_number=page_number,
                    row_index=row_index,
                    parser_confidence=0.68,
                    holiday_context=holiday_context,
                )
                if holiday_events is not None:
                    events.extend(holiday_events)
                    continue

            ranges = _extract_date_ranges(line)
            if ranges:
                start, end, original = ranges[0]
                title = _clean_event_title(line)
                if not title or len(title) < 3:
                    continue
                events.append(
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=_extract_academic_year(line) or source.academic_year,
                        term=line_term,
                        event_title=title,
                        start_date=start,
                        end_date=end,
                        original_date_text=original,
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_PARSED,
                        confidence_score=0.68,
                    )
                )
                continue

            row_text = _clean_event_title(line)
            if _is_review_worthy_row(row_text):
                events.append(
                    self._make_event(
                        source=source,
                        file_hash=file_hash,
                        checked_at=checked_at,
                        parsed_at=parsed_at,
                        academic_year=_extract_academic_year(line) or source.academic_year,
                        term=line_term,
                        event_title=row_text,
                        start_date=None,
                        end_date=None,
                        original_date_text="",
                        source_type=source.source_type,
                        page_number=page_number,
                        row_index=row_index,
                        parse_status=PARSE_STATUS_NEEDS_REVIEW,
                        confidence_score=0.3,
                    )
                )

        return events

    def _make_event(
        self,
        source: CalendarSource,
        file_hash: str,
        checked_at: str,
        parsed_at: str,
        academic_year: str | None,
        term: str | None,
        event_title: str,
        start_date: str | None,
        end_date: str | None,
        original_date_text: str,
        source_type: str,
        page_number: int | None,
        row_index: int | None,
        parse_status: str,
        confidence_score: float,
        event_category_override: str | None = None,
        section_title: str | None = None,
        section_type: str | None = None,
        section_note: str | None = None,
        note: str | None = None,
        merged_from_rows: list[dict[str, Any]] | None = None,
        parse_status_reason: str | None = None,
    ) -> AcademicCalendarEvent:
        event_category = event_category_override or _classify_event(event_title)
        content_hash_seed = "|".join(
            [
                academic_year or "",
                source.calendar_type,
                source.unit,
                term or "",
                event_title,
                event_category,
                start_date or "",
                end_date or "",
                original_date_text,
                file_hash,
                section_title or "",
                section_type or "",
                section_note or "",
                note or "",
            ]
        )
        return AcademicCalendarEvent(
            academic_year=academic_year,
            calendar_type=source.calendar_type,
            unit=source.unit,
            education_level=source.education_level,
            term=term,
            event_title=event_title,
            event_category=event_category,
            start_date=start_date,
            end_date=end_date,
            original_date_text=original_date_text,
            source_page_url=ACADEMIC_CALENDAR_URL,
            source_file_url=source.source_url if source.source_type == SOURCE_TYPE_PDF or _is_pdf_url(source.source_url) else None,
            source_type=SOURCE_TYPE_PDF if source.source_type == SOURCE_TYPE_PDF or _is_pdf_url(source.source_url) else SOURCE_TYPE_WEB,
            page_number=page_number,
            row_index=row_index,
            file_hash=file_hash,
            content_hash=_sha256_text(content_hash_seed),
            parse_status=parse_status,
            confidence_score=max(0.0, min(confidence_score, 1.0)),
            is_active=True,
            is_superseded=False,
            last_checked_at=checked_at,
            parsed_at=parsed_at,
            section_title=section_title,
            section_type=section_type,
            section_note=section_note,
            note=note,
            merged_from_rows=merged_from_rows or [],
            parse_status_reason=parse_status_reason,
        )

    def _event_representation(self, event: AcademicCalendarEvent) -> str:
        year = event.academic_year or "akademik yılı kaynakta açıkça belirlenmeyen"
        term = f"{event.term} " if event.term else ""
        date_text = _format_date_range(event.start_date, event.end_date, event.original_date_text)
        if event.parse_status == PARSE_STATUS_NEEDS_REVIEW:
            return (
                f"{year} {event.calendar_type} akademik takviminde {term}{event.event_title} "
                "satırı parse incelemesi gerektiriyor; tarih kesin veri olarak kullanılmamalıdır."
            )
        if event.event_category == "holiday" or event.section_type == HOLIDAY_SECTION_TYPE:
            note_text = ""
            if event.note:
                note = event.note.strip()
                if note and note[-1] not in ".!?":
                    note = f"{note}."
                note_text = f" Not: {note}"
            if event.start_date and (not event.end_date or event.end_date == event.start_date):
                return (
                    f"{year} akademik takviminde {date_text} {event.event_title} "
                    f"resmî tatildir.{note_text}"
                )
            return (
                f"{year} akademik takviminde {event.event_title} {date_text} "
                f"tarihleri arasında resmî tatildir.{note_text}"
            )
        return (
            f"{year} {event.calendar_type} akademik takvimine göre "
            f"{term}{event.event_title} {date_text} tarihleri arasındadır."
        )

    def _extract_tables_from_page(self, page: Any) -> list[list[list[Any]]]:
        settings_candidates = [
            {
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "intersection_tolerance": 5,
            },
            {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "intersection_tolerance": 5,
            },
        ]
        for settings in settings_candidates:
            try:
                tables = page.extract_tables(table_settings=settings) or []
                if tables:
                    return tables
            except Exception as exc:  # noqa: BLE001 - fallback denenir
                logger.debug("PDF tablo çıkarımı fallback gerektirdi: %s", exc)
        return []

    @staticmethod
    def _merge_header_cells(previous: list[str], current: list[str]) -> list[str]:
        """Çok satırlı tablo başlıklarını kolon bazında birleştirir."""
        max_len = max(len(previous), len(current))
        merged: list[str] = []
        for index in range(max_len):
            prev = previous[index] if index < len(previous) else ""
            curr = current[index] if index < len(current) else ""
            if prev and curr:
                merged.append(f"{prev} {curr}")
            else:
                merged.append(prev or curr)
        return merged

    def _dedupe_events(self, events: list[AcademicCalendarEvent]) -> list[AcademicCalendarEvent]:
        unique: list[AcademicCalendarEvent] = []
        seen: set[str] = set()
        for event in events:
            key = "|".join(
                [
                    event.academic_year or "",
                    event.calendar_type,
                    event.term or "",
                    event.event_title.casefold(),
                    event.start_date or "",
                    event.end_date or "",
                    event.original_date_text.casefold(),
                    str(event.page_number or ""),
                    str(event.row_index or ""),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(event)
        return unique

    def _content_has_calendar_table_or_text(self, root: Tag) -> bool:
        text = root.get_text(" ", strip=True)
        if not ACADEMIC_CONTEXT_RE.search(text):
            return False
        if root.select("table"):
            return True
        return bool(_extract_date_ranges(text) and _is_review_worthy_row(text))

    def _node_context(self, node: Tag) -> str:
        parts: list[str] = []
        for current in [node, node.parent, node.parent.parent if node.parent else None]:
            if isinstance(current, Tag):
                parts.append(current.get_text(" ", strip=True))
                for attr in ("title", "alt", "aria-label", "data", "src", "href"):
                    value = current.get(attr)
                    if value:
                        parts.append(str(value))
        return _single_line(" ".join(parts))

    def _source_title_from_context(self, context: str, source_url: str) -> str:
        year = _extract_academic_year(context)
        if year:
            return f"{year} Akademik Takvim"
        filename = Path(urlparse(source_url).path).stem.replace("_", " ").replace("-", " ")
        return _single_line(filename).title() if filename else "Akademik Takvim"

    def _source_unchanged(self, source_url: str, source_hash: str) -> bool:
        cache = self._read_cache()
        cache_matches = cache.get(source_url) == source_hash
        if not cache_matches:
            return False

        try:
            from app.config import get_settings
            import psycopg2

            database_url = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM haystack_docs
                WHERE meta->>'doc_kind' = 'academic_calendar_event'
                  AND meta->>'file_hash' = %s
                  AND coalesce(meta->>'is_active', 'true') = 'true'
                """,
                (source_hash,),
            )
            count = int(cur.fetchone()[0])
            cur.close()
            conn.close()
            return count > 0
        except Exception as exc:  # noqa: BLE001 - DB yoksa cache sinyaliyle yetinilir
            logger.warning("Akademik takvim değişiklik DB kontrolü yapılamadı, cache kullanılacak: %s", exc)
            return cache_matches

    def _supersede_previous_source(self, source_url: str, new_hash: str) -> None:
        try:
            from app.config import get_settings
            import psycopg2

            database_url = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE haystack_docs
                SET meta = jsonb_set(
                    jsonb_set(meta, '{is_active}', 'false'::jsonb, true),
                    '{is_superseded}', 'true'::jsonb, true
                )
                WHERE meta->>'doc_kind' = 'academic_calendar_event'
                  AND coalesce(meta->>'source_file_url', meta->>'source_page_url', meta->>'source_url') = %s
                  AND coalesce(meta->>'file_hash', '') <> %s
                  AND coalesce(meta->>'is_active', 'true') = 'true'
                """,
                (source_url, new_hash),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as exc:  # noqa: BLE001 - yeni ingestion engellenmesin
            logger.warning("Eski akademik takvim kayıtları supersede edilemedi: %s", exc)

    def _cleanup_stale_current_source_events(self, documents: list[Document]) -> None:
        """Aynı kaynak/hash için artık üretilmeyen eski event chunk'larını temizler."""
        source_ids = sorted({str(doc.meta.get("source_id")) for doc in documents if doc.meta and doc.meta.get("source_id")})
        source_urls = sorted({
            str(doc.meta.get("source_file_url") or doc.meta.get("source_page_url") or doc.meta.get("source_url"))
            for doc in documents
            if doc.meta and (doc.meta.get("source_file_url") or doc.meta.get("source_page_url") or doc.meta.get("source_url"))
        })
        file_hashes = sorted({str(doc.meta.get("file_hash")) for doc in documents if doc.meta and doc.meta.get("file_hash")})

        if not source_ids or not source_urls or not file_hashes:
            return

        try:
            from app.config import get_settings
            import psycopg2

            database_url = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM haystack_docs
                WHERE meta->>'doc_kind' = 'academic_calendar_event'
                  AND meta->>'file_hash' = ANY(%s)
                  AND coalesce(meta->>'source_file_url', meta->>'source_page_url', meta->>'source_url') = ANY(%s)
                  AND NOT (meta->>'source_id' = ANY(%s))
                """,
                (file_hashes, source_urls, source_ids),
            )
            deleted = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            if deleted:
                logger.info("Akademik takvim stale cleanup: %d eski event chunk silindi.", deleted)
        except Exception as exc:  # noqa: BLE001 - ingestion sonucu korunur, rapora loglanır
            logger.warning("Akademik takvim stale cleanup çalıştırılamadı: %s", exc)

    def _read_cache(self) -> dict[str, str]:
        if not self.cache_file.exists():
            return {}
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return {str(key): str(value) for key, value in data.items()}
        except Exception:
            return {}

    def _update_cache(self, source_hashes: dict[str, str]) -> None:
        if not source_hashes:
            return
        cache = self._read_cache()
        cache.update(source_hashes)
        self.cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if self._last_request_at and elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    @staticmethod
    def _encoding_from_content_type(content_type: str) -> str | None:
        match = re.search(r"charset=([\w.-]+)", content_type or "", re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _assert_allowed_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Geçersiz URL şeması: {url}")
        if parsed.netloc.lower() not in ALLOWED_HOSTS:
            raise ValueError(f"Akademik takvim kapsamı dışında URL reddedildi: {url}")

    @staticmethod
    def _maybe_write_report(report: AcademicCalendarScrapeReport, report_json: str | Path | None) -> None:
        if not report_json:
            return
        path = Path(report_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _ingest(documents: list[Document]) -> int:
        from app.ingestion.loader import ingest_documents
        from haystack.document_stores.types import DuplicatePolicy

        return ingest_documents(documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="GİBTÜ hedefli akademik takvim scraper")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan parse raporu üret")
    parser.add_argument("--force", action="store_true", help="Hash kontrolünü atlayıp yeniden işle")
    parser.add_argument("--report-json", default=None, help="Raporu JSON dosyasına yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scraper = AcademicCalendarScraper()
    report = scraper.scrape(
        dry_run=args.dry_run,
        force=args.force,
        report_json=args.report_json,
    )
    logger.info("Akademik takvim scrape raporu: %s", json.dumps(report.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
