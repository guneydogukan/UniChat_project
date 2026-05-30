"""
GİBTÜ aday öğrenci portalı için hedefli scraper.

Bu modül yalnızca https://adayogrenci.gibtu.edu.tr/ sayfasını işler.
Alt sayfa veya dış bağlantı takibi yapmaz; çıkan bilgileri mevcut
Haystack Document + ingestion sözleşmesine uygun üretir.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lxml import html as lxml_html

try:  # Test ortamında Haystack olmayabilir; üretimde gerçek sınıf kullanılır.
    from haystack import Document
except ImportError:  # pragma: no cover - sadece hafif yerel doğrulama için
    @dataclass
    class Document:  # type: ignore[no-redef]
        content: str
        meta: dict[str, Any]
        id: str | None = None

try:
    import requests
except ImportError:  # pragma: no cover - urllib fallback kullanılır
    requests = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

BASE_URL = "https://adayogrenci.gibtu.edu.tr/"
SOURCE_DOMAIN = "adayogrenci.gibtu.edu.tr"
SCRAPER_NAME = "candidate_portal_scraper"
METADATA_VERSION = "candidate.v1"
UNIVERSITY_NAME = "Gaziantep İslam Bilim ve Teknoloji Üniversitesi"
DEFAULT_DEPARTMENT = "Aday Öğrenci Portalı"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RATE_LIMIT_SECONDS = 1.0

ENCODING_FALLBACKS = ("utf-8", "windows-1254", "iso-8859-9")

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>\"]+")
PHONE_RE = re.compile(r"(?:\+?90\s*)?(?:0?\(?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{2}[\s.-]*\d{2}")

REQUIRED_METADATA_FIELDS = (
    "metadata_version",
    "category",
    "subcategory",
    "sub_category",
    "source_url",
    "source_public_url",
    "source_type",
    "source_id",
    "source_anchor",
    "last_updated",
    "last_fetched_at",
    "load_batch_id",
    "title",
    "doc_kind",
    "language",
    "department",
    "is_official",
    "scraper_name",
    "content_hash",
    "dedup_key",
    "university",
    "parent_doc_id",
    "chunk_index",
)

EXPECTED_DOC_KINDS = (
    "candidate_faq",
    "candidate_opportunity",
    "candidate_program",
    "candidate_transportation",
    "candidate_housing",
    "candidate_library",
    "candidate_exchange",
    "candidate_career",
    "candidate_contact",
)

EXPECTED_SOURCE_ANCHORS = (
    "sss",
    "olanaklar",
    "ogrenim",
    "gibtu",
    "kutuphane",
    "erasmus",
    "cbiko",
    "ogrencibasarisi",
    "konaklama",
    "gaziantep",
    "iletisim-bilgileri",
)

OLD_CANDIDATE_DOC_KINDS = (
    "tanitim",
    "sss",
    "rehber",
    "genel",
    "iletisim",
    "program_listesi",
)


def _has_class(class_name: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {class_name} ')"


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _element_text(element: Any) -> str:
    return _normalize_text("\n".join(str(t) for t in element.xpath(".//text()")))


def _direct_text(element: Any) -> str:
    return _normalize_text("\n".join(str(t) for t in element.xpath("./text()")))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str, max_len: int = 80) -> str:
    value = value.lower()
    replacements = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "â": "a",
        "î": "i",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "belge")[:max_len].strip("-")


def _parse_duration(title: str) -> tuple[str, str | None]:
    if "|" not in title:
        return title.strip(), None
    name, duration = title.rsplit("|", 1)
    return name.strip(), duration.strip()


def _decode_bytes(raw: bytes, content_type: str = "") -> tuple[str, str]:
    """Sayfanın hatalı UTF-8 bildirimi için güvenli encoding fallback uygular."""
    candidates: list[str] = []
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.IGNORECASE)
    if match:
        candidates.append(match.group(1))
    candidates.extend(ENCODING_FALLBACKS)

    seen: set[str] = set()
    for encoding in candidates:
        encoding = encoding.lower()
        if encoding in seen:
            continue
        seen.add(encoding)
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _extract_contact_info(text: str) -> str:
    found: list[str] = []
    for regex in (EMAIL_RE, PHONE_RE, URL_RE):
        for match in regex.findall(text):
            value = match.strip().rstrip(".,;")
            if value and value not in found:
                found.append(value)
    return " | ".join(found)


def _doc_kind_distribution(documents: list[Document]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for doc in documents:
        doc_kind = (doc.meta or {}).get("doc_kind", "bilinmiyor")
        distribution[doc_kind] = distribution.get(doc_kind, 0) + 1
    return distribution


@dataclass
class CandidatePortalReport:
    success: bool
    dry_run: bool
    source_url: str = BASE_URL
    fetched_at: str = ""
    encoding: str = ""
    documents_created: int = 0
    chunks_written: int = 0
    cleanup_deleted: int = 0
    cleanup_error: str | None = None
    faq_count: int = 0
    opportunity_count: int = 0
    program_card_count: int = 0
    program_document_count: int = 0
    section_count: int = 0
    doc_kind_distribution: dict[str, int] = field(default_factory=dict)
    sample_metadata: list[dict[str, Any]] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "dry_run": self.dry_run,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "encoding": self.encoding,
            "documents_created": self.documents_created,
            "chunks_written": self.chunks_written,
            "cleanup_deleted": self.cleanup_deleted,
            "cleanup_error": self.cleanup_error,
            "faq_count": self.faq_count,
            "opportunity_count": self.opportunity_count,
            "program_card_count": self.program_card_count,
            "program_document_count": self.program_document_count,
            "section_count": self.section_count,
            "doc_kind_distribution": self.doc_kind_distribution,
            "sample_metadata": self.sample_metadata,
            "data_quality": self.data_quality,
            "errors": self.errors,
        }


class CandidatePortalScraper:
    """Tek sayfalık aday öğrenci portalını RAG için kaliteli Document'lara böler."""

    SECTION_CONFIGS = (
        {
            "anchor": "gibtu",
            "title": "Gaziantep İslam Bilim ve Teknoloji Üniversitesi Tanıtımı",
            "doc_kind": "candidate_opportunity",
            "sub_category": "universite_tanitimi",
        },
        {
            "anchor": "kutuphane",
            "title": "Aday Öğrenci Kütüphane Olanakları",
            "doc_kind": "candidate_library",
            "sub_category": "kutuphane",
        },
        {
            "anchor": "erasmus",
            "title": "Aday Öğrenci Erasmus ve Uluslararası Değişim Programları",
            "doc_kind": "candidate_exchange",
            "sub_category": "erasmus_degisim",
        },
        {
            "anchor": "cbiko",
            "title": "Aday Öğrenci Kariyer Hizmetleri",
            "doc_kind": "candidate_career",
            "sub_category": "kariyer",
        },
        {
            "anchor": "ogrencibasarisi",
            "title": "Aday Öğrenci Akademik Başarı Bilgisi",
            "doc_kind": "candidate_opportunity",
            "sub_category": "akademik_basari",
        },
        {
            "anchor": "konaklama",
            "title": "Aday Öğrenci Konaklama Seçenekleri",
            "doc_kind": "candidate_housing",
            "sub_category": "konaklama",
        },
        {
            "anchor": "gaziantep",
            "title": "Aday Öğrenci İçin Gaziantep Şehir Tanıtımı",
            "doc_kind": "candidate_opportunity",
            "sub_category": "gaziantep",
        },
        {
            "anchor": "iletisim-bilgileri",
            "title": "Aday Öğrenci Portalı İletişim Bilgileri",
            "doc_kind": "candidate_contact",
            "sub_category": "iletisim",
        },
    )

    PROGRAM_LEVELS = (
        ("yukseklisans_listesi", "lisansustu", "Lisansüstü Programlarımız"),
        ("lisans_listesi", "lisans", "Lisans Programlarımız"),
        ("onlisans_listesi", "onlisans", "Önlisans Programlarımız"),
    )

    def __init__(
        self,
        url: str = BASE_URL,
        session: Any | None = None,
        timeout: int = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        retry_delay_seconds: int = RETRY_DELAY_SECONDS,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
    ) -> None:
        self.url = url
        self.session = session
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_at = 0.0
        self._fetched_at = ""

    def fetch_html(self) -> tuple[str, str]:
        """Portal HTML'ini tek URL'den çeker; başka link takip etmez."""
        self._assert_allowed_url(self.url)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                logger.info("Aday öğrenci portalı çekiliyor (%d/%d): %s", attempt, self.max_retries, self.url)
                raw, content_type = self._fetch_bytes(self.url)
                self._last_request_at = time.time()
                return _decode_bytes(raw, content_type)
            except Exception as exc:  # noqa: BLE001 - retry raporu için yakalanır
                last_error = exc
                logger.warning("Aday portal fetch hatası (%d/%d): %s", attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * attempt)

        raise RuntimeError(f"Aday öğrenci portalına erişilemedi: {last_error}")

    def parse_documents(self, html_text: str, fetched_at: str | None = None) -> tuple[list[Document], dict[str, int]]:
        """HTML metninden aday öğrenci Document listesini üretir."""
        self._fetched_at = fetched_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        root = lxml_html.fromstring(html_text)

        documents: list[Document] = []
        documents.extend(self._extract_faq_documents(root))
        documents.extend(self._extract_opportunity_documents(root))
        program_docs, program_card_count = self._extract_program_documents(root)
        documents.extend(program_docs)
        documents.extend(self._extract_section_documents(root))

        stats = {
            "faq_count": sum(1 for d in documents if d.meta.get("doc_kind") == "candidate_faq"),
            "opportunity_count": sum(1 for d in documents if d.meta.get("source_anchor") == "olanaklar"),
            "program_card_count": program_card_count,
            "program_document_count": len(program_docs),
            "section_count": sum(1 for d in documents if d.meta.get("source_anchor") not in {"sss", "olanaklar", "ogrenim"}),
        }

        return documents, stats

    def scrape(
        self,
        dry_run: bool = False,
        cleanup: bool = True,
        report_json: str | Path | None = None,
    ) -> CandidatePortalReport:
        """Fetch → parse → scoped cleanup → ingest akışını çalıştırır."""
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        report = CandidatePortalReport(success=False, dry_run=dry_run, fetched_at=fetched_at)

        try:
            html_text, encoding = self.fetch_html()
            report.encoding = encoding
            documents, stats = self.parse_documents(html_text, fetched_at=fetched_at)
        except Exception as exc:  # noqa: BLE001 - kullanıcıya açık rapor
            report.errors.append(str(exc))
            self._maybe_write_report(report, report_json)
            return report

        report.documents_created = len(documents)
        report.faq_count = stats["faq_count"]
        report.opportunity_count = stats["opportunity_count"]
        report.program_card_count = stats["program_card_count"]
        report.program_document_count = stats["program_document_count"]
        report.section_count = stats["section_count"]
        report.doc_kind_distribution = _doc_kind_distribution(documents)
        report.sample_metadata = [self._sample_meta(doc.meta) for doc in documents[:3]]

        if not documents:
            report.errors.append("Aday öğrenci portalından geçerli document üretilemedi.")
            self._maybe_write_report(report, report_json)
            return report

        if cleanup:
            deleted, cleanup_error = self.cleanup_existing_chunks(dry_run=dry_run)
            report.cleanup_deleted = deleted
            report.cleanup_error = cleanup_error
            if cleanup_error and not dry_run:
                report.errors.append(f"Cleanup hatası: {cleanup_error}")
                self._maybe_write_report(report, report_json)
                return report

        if dry_run:
            report.chunks_written = len(documents)
            report.success = True
            self._maybe_write_report(report, report_json)
            return report

        try:
            report.chunks_written = self._ingest(documents)
            report.data_quality = self.validate_loaded_data(
                expected_chunks=report.chunks_written,
                expected_load_batch_id=f"{SCRAPER_NAME}:{fetched_at}",
                require_exact_count=cleanup,
            )
            report.success = bool(report.data_quality.get("success"))
            if not report.success:
                failures = report.data_quality.get("failures") or []
                report.errors.append(
                    "Veri kalite kontrolü başarısız: "
                    + ("; ".join(failures) if failures else "detay yok")
                )
        except Exception as exc:  # noqa: BLE001 - production log + rapor
            report.errors.append(f"Ingestion hatası: {exc}")

        self._maybe_write_report(report, report_json)
        return report

    @staticmethod
    def cleanup_existing_chunks(dry_run: bool = True) -> tuple[int, str | None]:
        """Yalnızca aday portalına ait eski chunk'ları sayar veya temizler."""
        try:
            try:
                from dotenv import load_dotenv

                load_dotenv(Path(__file__).resolve().parents[2] / ".env")
            except ImportError:
                pass

            import psycopg2

            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                return 0, "DATABASE_URL tanımlı değil; cleanup atlandı."

            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            where_sql = """
                meta->>'category' = %s
                AND (
                    meta->>'scraper_name' = %s
                    OR lower(coalesce(meta->>'source_url', '')) = %s
                    OR lower(coalesce(meta->>'source_url', '')) LIKE %s
                    OR lower(coalesce(meta->>'source_url', '')) LIKE %s
                    OR lower(coalesce(meta->>'source_url', '')) LIKE %s
                    OR lower(coalesce(meta->>'source_public_url', '')) = %s
                    OR lower(coalesce(meta->>'source_public_url', '')) LIKE %s
                    OR lower(coalesce(meta->>'source_public_url', '')) LIKE %s
                    OR lower(coalesce(meta->>'source_public_url', '')) LIKE %s
                )
            """
            base_without_slash = BASE_URL.rstrip("/").lower()
            params = (
                "aday_ogrenci",
                SCRAPER_NAME,
                base_without_slash,
                f"{base_without_slash}/%",
                f"{base_without_slash}#%",
                "https://www.gibtu.edu.tr/adayogrenci%",
                base_without_slash,
                f"{base_without_slash}/%",
                f"{base_without_slash}#%",
                "https://www.gibtu.edu.tr/adayogrenci%",
            )

            cur.execute(f"SELECT COUNT(*) FROM haystack_docs WHERE {where_sql}", params)
            count = int(cur.fetchone()[0])

            if not dry_run and count:
                cur.execute(f"DELETE FROM haystack_docs WHERE {where_sql}", params)
                conn.commit()

            cur.close()
            conn.close()
            return count, None
        except Exception as exc:  # noqa: BLE001 - cleanup ana akışı bozmasın
            return 0, str(exc)

    @staticmethod
    def validate_loaded_data(
        expected_chunks: int,
        expected_load_batch_id: str,
        require_exact_count: bool = True,
    ) -> dict[str, Any]:
        """Reload sonrası DB'deki aday portalı verisinin production kalite kapısını çalıştırır."""
        try:
            try:
                from dotenv import load_dotenv

                load_dotenv(Path(__file__).resolve().parents[2] / ".env")
            except ImportError:
                pass

            import psycopg2

            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                return {
                    "success": False,
                    "failures": ["DATABASE_URL tanımlı değil; veri kalite kontrolü yapılamadı."],
                }

            conn = psycopg2.connect(database_url)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_chunks,
                    COUNT(DISTINCT id) AS distinct_ids,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks,
                    COUNT(*) FILTER (WHERE meta->>'metadata_version' = %s) AS metadata_version_chunks,
                    COUNT(*) FILTER (WHERE meta->>'scraper_name' = %s) AS scraper_chunks,
                    COUNT(*) FILTER (WHERE meta->>'load_batch_id' = %s) AS load_batch_chunks,
                    COUNT(*) FILTER (WHERE meta->>'language' = 'tr') AS tr_language_chunks,
                    COUNT(*) FILTER (WHERE meta->>'is_official' = 'true') AS official_chunks,
                    COUNT(*) FILTER (WHERE meta->>'doc_kind' = ANY(%s)) AS old_doc_kind_chunks,
                    COUNT(*) FILTER (
                        WHERE lower(coalesce(meta->>'source_url', '')) LIKE 'https://www.gibtu.edu.tr/adayogrenci%%'
                           OR lower(coalesce(meta->>'source_public_url', '')) LIKE 'https://www.gibtu.edu.tr/adayogrenci%%'
                    ) AS legacy_source_chunks
                FROM haystack_docs
                WHERE meta->>'category' = 'aday_ogrenci'
                """,
                (
                    METADATA_VERSION,
                    SCRAPER_NAME,
                    expected_load_batch_id,
                    list(OLD_CANDIDATE_DOC_KINDS),
                ),
            )
            summary_columns = [desc[0] for desc in cur.description]
            summary = dict(zip(summary_columns, cur.fetchone()))

            metadata_coverage: dict[str, int] = {}
            for field_name in REQUIRED_METADATA_FIELDS:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM haystack_docs
                    WHERE meta->>'category' = 'aday_ogrenci'
                      AND coalesce(meta->>%s, '') != ''
                    """,
                    (field_name,),
                )
                metadata_coverage[field_name] = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT meta->>'doc_kind' AS doc_kind, COUNT(*) AS count
                FROM haystack_docs
                WHERE meta->>'category' = 'aday_ogrenci'
                GROUP BY 1
                ORDER BY 1
                """
            )
            doc_kind_distribution = {str(row[0]): int(row[1]) for row in cur.fetchall()}

            cur.execute(
                """
                SELECT meta->>'source_anchor' AS source_anchor, COUNT(*) AS count
                FROM haystack_docs
                WHERE meta->>'category' = 'aday_ogrenci'
                GROUP BY 1
                ORDER BY 1
                """
            )
            source_anchor_distribution = {str(row[0]): int(row[1]) for row in cur.fetchall()}

            cur.execute(
                """
                SELECT meta->>'load_batch_id' AS load_batch_id, COUNT(*) AS count
                FROM haystack_docs
                WHERE meta->>'category' = 'aday_ogrenci'
                GROUP BY 1
                ORDER BY 2 DESC
                """
            )
            load_batch_distribution = {
                str(row[0]) if row[0] is not None else "NULL": int(row[1])
                for row in cur.fetchall()
            }

            cur.close()
            conn.close()

            return CandidatePortalScraper._build_data_quality_report(
                summary=summary,
                metadata_coverage=metadata_coverage,
                doc_kind_distribution=doc_kind_distribution,
                source_anchor_distribution=source_anchor_distribution,
                load_batch_distribution=load_batch_distribution,
                expected_chunks=expected_chunks,
                expected_load_batch_id=expected_load_batch_id,
                require_exact_count=require_exact_count,
            )
        except Exception as exc:  # noqa: BLE001 - rapora açık kalite hatası yazılır
            return {
                "success": False,
                "failures": [f"Veri kalite kontrolü çalıştırılamadı: {exc}"],
            }

    @staticmethod
    def _build_data_quality_report(
        summary: dict[str, Any],
        metadata_coverage: dict[str, int],
        doc_kind_distribution: dict[str, int],
        source_anchor_distribution: dict[str, int],
        load_batch_distribution: dict[str, int],
        expected_chunks: int,
        expected_load_batch_id: str,
        require_exact_count: bool = True,
    ) -> dict[str, Any]:
        total_chunks = int(summary.get("total_chunks") or 0)
        failures: list[str] = []

        if total_chunks <= 0:
            failures.append("aday_ogrenci kategorisinde kayıt yok")

        if require_exact_count and total_chunks != expected_chunks:
            failures.append(f"chunk sayısı beklenenden farklı: DB={total_chunks}, beklenen={expected_chunks}")

        if int(summary.get("distinct_ids") or 0) != total_chunks:
            failures.append("tekrarlı document id tespit edildi")

        if int(summary.get("embedded_chunks") or 0) != total_chunks:
            failures.append("embedding eksik aday chunk var")

        if int(summary.get("metadata_version_chunks") or 0) != total_chunks:
            failures.append(f"{METADATA_VERSION} metadata_version eksik chunk var")

        if int(summary.get("scraper_chunks") or 0) != total_chunks:
            failures.append(f"{SCRAPER_NAME} scraper_name eksik chunk var")

        if int(summary.get("load_batch_chunks") or 0) != total_chunks:
            failures.append(f"beklenen load_batch_id dışında chunk var: {expected_load_batch_id}")

        if int(summary.get("tr_language_chunks") or 0) != total_chunks:
            failures.append("language=tr olmayan aday chunk var")

        if int(summary.get("official_chunks") or 0) != total_chunks:
            failures.append("is_official=true olmayan aday chunk var")

        if int(summary.get("old_doc_kind_chunks") or 0) > 0:
            failures.append("eski aday doc_kind kalıntısı var")

        if int(summary.get("legacy_source_chunks") or 0) > 0:
            failures.append("eski www.gibtu.edu.tr/adayogrenci kaynak kalıntısı var")

        missing_metadata_fields = [
            field_name
            for field_name, filled_count in metadata_coverage.items()
            if int(filled_count) != total_chunks
        ]
        if missing_metadata_fields:
            failures.append("metadata doluluğu eksik: " + ", ".join(missing_metadata_fields))

        present_doc_kinds = set(doc_kind_distribution)
        missing_doc_kinds = [
            doc_kind for doc_kind in EXPECTED_DOC_KINDS
            if doc_kind not in present_doc_kinds
        ]
        if missing_doc_kinds:
            failures.append("eksik candidate doc_kind: " + ", ".join(missing_doc_kinds))

        present_source_anchors = set(source_anchor_distribution)
        missing_source_anchors = [
            anchor for anchor in EXPECTED_SOURCE_ANCHORS
            if anchor not in present_source_anchors
        ]
        if missing_source_anchors:
            failures.append("eksik source_anchor: " + ", ".join(missing_source_anchors))

        return {
            "success": not failures,
            "failures": failures,
            "expected_chunks": expected_chunks,
            "require_exact_count": require_exact_count,
            "summary": summary,
            "metadata_coverage": metadata_coverage,
            "missing_metadata_fields": missing_metadata_fields,
            "doc_kind_distribution": doc_kind_distribution,
            "missing_doc_kinds": missing_doc_kinds,
            "source_anchor_distribution": source_anchor_distribution,
            "missing_source_anchors": missing_source_anchors,
            "load_batch_distribution": load_batch_distribution,
            "expected_load_batch_id": expected_load_batch_id,
        }

    def _extract_faq_documents(self, root: Any) -> list[Document]:
        documents: list[Document] = []
        faq_items = root.xpath(
            f"//ul[{_has_class('collapsible')} and {_has_class('popout')}]/li"
        )
        for item in faq_items:
            headers = item.xpath(f".//div[{_has_class('collapsible-header')}]")
            bodies = item.xpath(f".//div[{_has_class('collapsible-body')}]")
            if not headers or not bodies:
                continue

            question = _direct_text(headers[0]) or _element_text(headers[0])
            answer = _element_text(bodies[0])
            if not question or len(answer) < 20:
                continue

            content = (
                "Başlık: Aday Öğrenci Sıkça Sorulan Soru\n\n"
                f"Soru: {question}\n\n"
                f"Cevap: {answer}"
            )
            documents.append(
                self._make_document(
                    key=f"sss/{_slug(question)}",
                    title=f"Aday Öğrenci SSS: {question}",
                    content=content,
                    doc_kind="candidate_faq",
                    source_anchor="sss",
                    sub_category="sikca_sorulan_sorular",
                    extra_meta={"question": question},
                )
            )
        return documents

    def _extract_opportunity_documents(self, root: Any) -> list[Document]:
        documents: list[Document] = []
        slides = root.xpath(f"//div[{_has_class('slayt')}]")
        for slide in slides:
            title_nodes = slide.xpath(f".//*[{_has_class('slayt_baslik')}]")
            text_nodes = slide.xpath(f".//*[{_has_class('slayt_metin')}]")
            title = _element_text(title_nodes[0]) if title_nodes else ""
            text = _element_text(text_nodes[0]) if text_nodes else ""
            if not title or len(text) < 20:
                continue

            doc_kind, sub_category = self._classify_opportunity(title, text)
            content = f"Başlık: {title}\n\n{text}"
            documents.append(
                self._make_document(
                    key=f"olanak/{_slug(title)}",
                    title=f"Aday Öğrenci Olanakları: {title}",
                    content=content,
                    doc_kind=doc_kind,
                    source_anchor="olanaklar",
                    sub_category=sub_category,
                )
            )
        return documents

    def _extract_program_documents(self, root: Any) -> tuple[list[Document], int]:
        documents: list[Document] = []
        total_cards = 0

        for section_class, level, title in self.PROGRAM_LEVELS:
            sections = root.xpath(f"//section[{_has_class(section_class)}]")
            if not sections:
                continue

            programs: list[dict[str, Any]] = []
            for card in sections[0].xpath(f".//div[{_has_class('faculty-card')}]"):
                title_nodes = card.xpath(f".//*[{_has_class('faculty-card-title')}]")
                raw_title = _element_text(title_nodes[0]) if title_nodes else ""
                if not raw_title:
                    continue
                name, duration = _parse_duration(raw_title)
                child_programs = [
                    _element_text(li)
                    for li in card.xpath(f".//*[{_has_class('faculty-card-list')}]//li")
                ]
                child_programs = [item for item in child_programs if item]
                programs.append({
                    "name": name,
                    "duration": duration,
                    "programs": child_programs,
                })

            if not programs:
                continue

            total_cards += len(programs)
            content = self._format_program_content(title, level, programs)
            documents.append(
                self._make_document(
                    key=f"ogrenim/{level}",
                    title=f"Aday Öğrenci {title}",
                    content=content,
                    doc_kind="candidate_program",
                    source_anchor="ogrenim",
                    sub_category=level,
                    extra_meta={"program_level": level, "programs": programs},
                )
            )

        return documents, total_cards

    def _extract_section_documents(self, root: Any) -> list[Document]:
        documents: list[Document] = []
        for config in self.SECTION_CONFIGS:
            anchor = config["anchor"]
            nodes = root.xpath(f"//*[@id='{anchor}']")
            if not nodes:
                continue
            text = _element_text(nodes[0])
            if len(text) < 50:
                continue

            title = str(config["title"])
            content = f"Başlık: {title}\n\n{text}"
            extra_meta: dict[str, Any] = {}
            if config["doc_kind"] == "candidate_contact":
                extra_meta["contact_info"] = _extract_contact_info(text)

            documents.append(
                self._make_document(
                    key=f"{anchor}/{_slug(title)}",
                    title=title,
                    content=content,
                    doc_kind=str(config["doc_kind"]),
                    source_anchor=anchor,
                    sub_category=str(config["sub_category"]),
                    extra_meta=extra_meta,
                )
            )
        return documents

    def _make_document(
        self,
        key: str,
        title: str,
        content: str,
        doc_kind: str,
        source_anchor: str,
        sub_category: str,
        extra_meta: dict[str, Any] | None = None,
    ) -> Document:
        source_id = f"candidate_portal/{key}"
        source_url = f"{BASE_URL}#{source_anchor}" if source_anchor else BASE_URL
        content_hash = _sha256(content)
        dedup_key = source_id

        meta: dict[str, Any] = {
            "metadata_version": METADATA_VERSION,
            "category": "aday_ogrenci",
            "subcategory": sub_category,
            "sub_category": sub_category,
            "source_url": source_url,
            "source_public_url": source_url,
            "source_type": "web",
            "source_id": source_id,
            "source_anchor": source_anchor,
            "last_updated": self._fetched_at,
            "last_fetched_at": self._fetched_at,
            "load_batch_id": f"{SCRAPER_NAME}:{self._fetched_at}",
            "title": title,
            "doc_kind": doc_kind,
            "language": "tr",
            "department": DEFAULT_DEPARTMENT,
            "is_official": True,
            "scraper_name": SCRAPER_NAME,
            "content_hash": content_hash,
            "dedup_key": dedup_key,
            "university": UNIVERSITY_NAME,
        }

        if extra_meta:
            for key_name, value in extra_meta.items():
                if value:
                    meta[key_name] = value

        return Document(id=_sha256(dedup_key), content=content, meta=meta)

    def _fetch_bytes(self, url: str) -> tuple[bytes, str]:
        if self.session is not None:
            response = self.session.get(url, timeout=self.timeout)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            self._assert_allowed_url(getattr(response, "url", url))
            raw = getattr(response, "content", None)
            if raw is None:
                text = getattr(response, "text", "")
                raw = str(text).encode(getattr(response, "encoding", "utf-8") or "utf-8")
            headers = getattr(response, "headers", {}) or {}
            return bytes(raw), str(headers.get("content-type", headers.get("Content-Type", "")))

        if requests is not None:
            response = requests.get(  # type: ignore[union-attr]
                url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0)"},
                allow_redirects=True,
            )
            response.raise_for_status()
            self._assert_allowed_url(response.url)
            return response.content, response.headers.get("content-type", "")

        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; UniChatBot/1.0)"})
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - domain yukarıda sınırlandı
            final_url = getattr(response, "url", url)
            self._assert_allowed_url(final_url)
            content_type = response.headers.get("content-type", "")
            return response.read(), content_type

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if self._last_request_at and elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    @staticmethod
    def _assert_allowed_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Geçersiz URL şeması: {url}")
        if parsed.netloc.lower() != SOURCE_DOMAIN:
            raise ValueError(f"Aday portal kapsamı dışında URL reddedildi: {url}")

    @staticmethod
    def _classify_opportunity(title: str, text: str) -> tuple[str, str]:
        title_lower = title.lower()
        combined = f"{title} {text}".lower()
        if "ulaş" in title_lower or "otobüs" in title_lower or "minibüs" in title_lower:
            return "candidate_transportation", "ulasim"
        if "kulüp" in combined or "topluluk" in combined:
            return "candidate_opportunity", "ogrenci_kulupleri"
        if "yemekhane" in combined or "kafeterya" in combined:
            return "candidate_opportunity", "yemekhane_kafeterya"
        if "spor" in combined:
            return "candidate_opportunity", "spor"
        if "sağlık" in combined:
            return "candidate_opportunity", "saglik"
        if "kültür" in combined or "sanat" in combined:
            return "candidate_opportunity", "kultur_sanat"
        if "fiziki" in combined or "tesis" in combined:
            return "candidate_opportunity", "fiziki_imkanlar"
        return "candidate_opportunity", "kampus_olanaklari"

    @staticmethod
    def _format_program_content(title: str, level: str, programs: list[dict[str, Any]]) -> str:
        lines = [
            f"Başlık: {title}",
            f"Program seviyesi: {level}",
            "",
            "Programlar:",
        ]
        for program in programs:
            name = program["name"]
            duration = program.get("duration")
            heading = f"- {name}"
            if duration:
                heading += f" | {duration}"
            lines.append(heading)
            for child in program.get("programs", []):
                lines.append(f"  - {child}")
        return "\n".join(lines)

    @staticmethod
    def _sample_meta(meta: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "title",
            "doc_kind",
            "source_url",
            "source_anchor",
            "source_id",
            "content_hash",
            "dedup_key",
            "scraper_name",
            "metadata_version",
            "load_batch_id",
        )
        return {field_name: meta.get(field_name) for field_name in fields if meta.get(field_name) is not None}

    @staticmethod
    def _maybe_write_report(report: CandidatePortalReport, report_json: str | Path | None) -> None:
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


__all__ = [
    "BASE_URL",
    "METADATA_VERSION",
    "SCRAPER_NAME",
    "CandidatePortalReport",
    "CandidatePortalScraper",
    "_decode_bytes",
]
