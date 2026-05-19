"""
UniChat — Academic year ve kaynak metadata migration.

Varsayılan mod dry-run'dır; veritabanına yazmak için --apply kullanılmalıdır.

Eklenen metadata alanları:
    academic_year      — yalnızca açık akademik yıl aralığı (örn: 2025-2026)
    document_year      — tek yıllı rapor/doküman yılı (örn: 2024)
    source_public_url  — kullanıcıya gösterilecek HTTP/HTTPS kaynak URL'si
    source_file_path   — yerel PDF yolunun açık karşılığı
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse


BACKEND_DIR = Path(__file__).resolve().parent
SCRAPERS_DIR = BACKEND_DIR / "scrapers"
DEFAULT_SOURCE_MANIFESTS = [
    SCRAPERS_DIR / "raporlar_output.json",
    SCRAPERS_DIR / "mevzuat_output.json",
]

YEAR_RANGE_RE = re.compile(r"\b(20\d{2})\s*(?:-|–|—|/)\s*(20\d{2})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")

ACADEMIC_CONTEXT_KEYWORDS = (
    "akademik",
    "eğitim öğretim",
    "egitim ogretim",
    "öğretim yılı",
    "ogretim yili",
    "güz",
    "guz",
    "bahar",
    "dönem",
    "donem",
    "müfredat",
    "mufredat",
    "ders",
)

REPORT_DOC_KINDS = {"rapor", "pdf_rapor"}
REPORT_KEYWORDS = (
    "rapor",
    "faaliyet",
    "değerlendirme",
    "degerlendirme",
)

TR_TRANSLATION = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
})

logger = logging.getLogger("metadata_migration")


@dataclass
class SourceLookup:
    """Yerel PDF dosya adlarından public URL eşlemesi."""

    by_key: dict[str, str] = field(default_factory=dict)
    ambiguous_keys: dict[str, set[str]] = field(default_factory=dict)

    def match(self, source_url: str) -> str | None:
        filename = _basename(source_url)
        keys = {
            _normalize_key(filename),
            _normalize_key(Path(filename).stem),
        }
        for key in keys:
            if key and key in self.by_key:
                return self.by_key[key]
        return None


@dataclass
class MigrationStats:
    total: int = 0
    changed: int = 0
    academic_year_set: int = 0
    document_year_set: int = 0
    http_source_url: int = 0
    local_pdf_source_url: int = 0
    source_public_url_resolved: int = 0
    source_public_url_unresolved: int = 0
    missing_source_url: int = 0


def _is_http_url(value: str | None) -> bool:
    return bool(value and value.strip().lower().startswith(("http://", "https://")))


def _basename(value: str) -> str:
    return re.split(r"[\\/]", value.strip())[-1]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("i̇", "i")
    normalized = normalized.translate(TR_TRANSLATION)
    return normalized


def _normalize_key(value: str | None) -> str:
    if not value:
        return ""
    normalized = _normalize_text(value)
    normalized = re.sub(r"\.pdf$", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_academic_year(value: str) -> str | None:
    """YYYY-YYYY, YYYY / YYYY ve YYYY – YYYY biçimlerini YYYY-YYYY yapar."""
    match = YEAR_RANGE_RE.search(value or "")
    if not match:
        return None

    start, end = match.group(1), match.group(2)
    if int(end) - int(start) != 1:
        return None
    return f"{start}-{end}"


def _has_academic_context(value: str) -> bool:
    normalized = _normalize_text(value)
    return any(keyword in normalized for keyword in ACADEMIC_CONTEXT_KEYWORDS)


def _extract_academic_year_with_context(value: str) -> str | None:
    if not value:
        return None

    for match in YEAR_RANGE_RE.finditer(value):
        normalized_year = normalize_academic_year(match.group(0))
        if not normalized_year:
            continue

        start = max(0, match.start() - 80)
        end = min(len(value), match.end() + 80)
        if _has_academic_context(value[start:end]):
            return normalized_year

    return None


def _single_years_excluding_ranges(value: str) -> list[str]:
    if not value:
        return []

    range_spans = [match.span() for match in YEAR_RANGE_RE.finditer(value)]
    years: list[str] = []
    for match in YEAR_RE.finditer(value):
        if any(start <= match.start() < end for start, end in range_spans):
            continue
        years.append(match.group(1))
    return years


def _single_document_year(value: str) -> str | None:
    years = sorted(set(_single_years_excluding_ranges(value)))
    if len(years) == 1:
        return years[0]
    return None


def infer_year_metadata(meta: dict, content: str) -> tuple[str | None, str | None]:
    """Metadata ve içerikten academic_year/document_year çıkarır."""
    title = str(meta.get("title") or "")
    source_url = str(meta.get("source_url") or "")
    filename = _basename(source_url)
    doc_kind = str(meta.get("doc_kind") or "")

    academic_year = (
        _extract_academic_year_with_context(title)
        or _extract_academic_year_with_context(filename)
        or _extract_academic_year_with_context(content[:2500])
    )

    report_text = f"{title} {filename}"
    report_text_norm = _normalize_text(report_text)
    report_like = doc_kind in REPORT_DOC_KINDS or any(
        keyword in report_text_norm for keyword in REPORT_KEYWORDS
    )
    document_year = None
    if report_like and not academic_year:
        document_year = _single_document_year(title) or _single_document_year(filename)

    return academic_year, document_year


def _resolve_pdf_url(url: str) -> str:
    parsed = urlparse(url)
    if "PdfViewer.aspx" not in parsed.path:
        return url

    file_param = parse_qs(parsed.query).get("file", [None])[0]
    if not file_param:
        return url

    viewer_base = url.split("PdfViewer.aspx")[0]
    return urljoin(viewer_base, file_param)


def _candidate_keys_for_pdf_link(link: dict) -> set[str]:
    keys: set[str] = set()
    text = str(link.get("text") or "")
    filename = str(link.get("filename") or "")
    url = str(link.get("url") or "")
    resolved_url = str(link.get("resolved_url") or "") or _resolve_pdf_url(url)

    candidates = [
        text,
        f"{text}.pdf" if text else "",
        filename,
        _basename(urlparse(url).path),
        _basename(urlparse(resolved_url).path),
    ]
    for candidate in candidates:
        key = _normalize_key(candidate)
        if key:
            keys.add(key)
    return keys


def build_source_lookup(manifest_paths: list[Path]) -> SourceLookup:
    raw: dict[str, set[str]] = {}

    for path in manifest_paths:
        if not path.exists():
            logger.warning("Kaynak manifest bulunamadı, atlanıyor: %s", path)
            continue

        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        for link in payload.get("pdf_links", []):
            url = str(link.get("resolved_url") or "") or _resolve_pdf_url(str(link.get("url") or ""))
            if not _is_http_url(url):
                continue

            for key in _candidate_keys_for_pdf_link(link):
                raw.setdefault(key, set()).add(url)

    lookup = SourceLookup()
    for key, urls in raw.items():
        if len(urls) == 1:
            lookup.by_key[key] = next(iter(urls))
        else:
            lookup.ambiguous_keys[key] = urls

    return lookup


def build_updated_meta(
    meta: dict | None,
    content: str,
    source_lookup: SourceLookup,
    recompute_years: bool = False,
) -> dict:
    updated = dict(meta or {})

    academic_year, document_year = infer_year_metadata(updated, content or "")
    if recompute_years or not updated.get("academic_year"):
        updated["academic_year"] = academic_year
    if recompute_years or not updated.get("document_year"):
        updated["document_year"] = document_year

    source_url = str(updated.get("source_url") or "").strip()
    current_public_url = updated.get("source_public_url")

    if _is_http_url(source_url):
        updated["source_public_url"] = current_public_url if _is_http_url(current_public_url) else source_url
    elif source_url:
        updated["source_file_path"] = updated.get("source_file_path") or source_url
        resolved_public_url = source_lookup.match(source_url)
        updated["source_public_url"] = (
            current_public_url if _is_http_url(current_public_url) else resolved_public_url
        )
        updated["source_public_url_status"] = (
            "resolved" if updated.get("source_public_url") else "unresolved_local_pdf"
        )
    else:
        updated["source_public_url"] = current_public_url if _is_http_url(current_public_url) else None

    return updated


def _connect(database_url: str):
    import psycopg2

    return psycopg2.connect(database_url)


def _load_rows(conn, table_name: str) -> list[tuple[str, str, dict | None]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT id, content, meta FROM {table_name} ORDER BY id")
        return cur.fetchall()


def _collect_stats(rows: list[tuple[str, str, dict | None]], updated_rows: list[tuple[str, dict]]) -> MigrationStats:
    updated_by_id = dict(updated_rows)
    stats = MigrationStats(total=len(rows), changed=len(updated_rows))

    for doc_id, _content, meta in rows:
        new_meta = updated_by_id.get(doc_id, meta or {})
        source_url = str((meta or {}).get("source_url") or "").strip()

        if new_meta.get("academic_year"):
            stats.academic_year_set += 1
        if new_meta.get("document_year"):
            stats.document_year_set += 1
        if not source_url:
            stats.missing_source_url += 1
        elif _is_http_url(source_url):
            stats.http_source_url += 1
        else:
            stats.local_pdf_source_url += 1
            if new_meta.get("source_public_url"):
                stats.source_public_url_resolved += 1
            else:
                stats.source_public_url_unresolved += 1

    return stats


def _print_report(
    stats: MigrationStats,
    rows: list[tuple[str, str, dict | None]],
    updated_rows: list[tuple[str, dict]],
    report_limit: int,
) -> None:
    logger.info("Toplam chunk: %d", stats.total)
    logger.info("Değişecek chunk: %d", stats.changed)
    logger.info("academic_year dolu olacak: %d", stats.academic_year_set)
    logger.info("document_year dolu olacak: %d", stats.document_year_set)
    logger.info("HTTP source_url: %d", stats.http_source_url)
    logger.info("Yerel PDF source_url: %d", stats.local_pdf_source_url)
    logger.info("source_public_url çözülen yerel PDF chunk: %d", stats.source_public_url_resolved)
    logger.info("source_public_url çözülemeyen yerel PDF chunk: %d", stats.source_public_url_unresolved)
    logger.info("source_url eksik/boş chunk: %d", stats.missing_source_url)

    updated_by_id = dict(updated_rows)
    missing = [
        (doc_id, content, meta or {})
        for doc_id, content, meta in rows
        if not str((meta or {}).get("source_url") or "").strip()
    ]
    if missing:
        logger.info("source_url eksik örnekler:")
        for doc_id, content, meta in missing[:report_limit]:
            snippet = re.sub(r"\s+", " ", content or "")[:140]
            logger.info("  id=%s | meta=%s | %s", doc_id, meta, snippet)

    unresolved = []
    for doc_id, content, meta in rows:
        old_meta = meta or {}
        source_url = str(old_meta.get("source_url") or "").strip()
        if not source_url or _is_http_url(source_url):
            continue
        new_meta = updated_by_id.get(doc_id, old_meta)
        if not new_meta.get("source_public_url"):
            unresolved.append((doc_id, source_url, content))

    if unresolved:
        logger.info("source_public_url çözülemeyen yerel PDF örnekleri:")
        for doc_id, source_url, content in unresolved[:report_limit]:
            snippet = re.sub(r"\s+", " ", content or "")[:100]
            logger.info("  id=%s | %s | %s", doc_id, _basename(source_url), snippet)


def migrate(args: argparse.Namespace) -> int:
    manifest_paths = [Path(p) for p in args.manifest]
    source_lookup = build_source_lookup(manifest_paths)
    logger.info(
        "Public PDF eşleme anahtarı: %d tekil, %d belirsiz",
        len(source_lookup.by_key),
        len(source_lookup.ambiguous_keys),
    )

    conn = _connect(args.database_url)
    try:
        rows = _load_rows(conn, args.table)
        updated_rows: list[tuple[str, dict]] = []

        for doc_id, content, meta in rows:
            new_meta = build_updated_meta(
                meta,
                content or "",
                source_lookup,
                recompute_years=args.recompute_years,
            )
            if new_meta != (meta or {}):
                updated_rows.append((doc_id, new_meta))

        stats = _collect_stats(rows, updated_rows)
        _print_report(stats, rows, updated_rows, args.report_limit)

        if not args.apply:
            logger.info("DRY-RUN: Veritabanı değiştirilmedi. Yazmak için --apply kullanın.")
            return 0

        from psycopg2.extras import Json, execute_batch

        with conn.cursor() as cur:
            execute_batch(
                cur,
                f"UPDATE {args.table} SET meta = %s WHERE id = %s",
                [(Json(meta), doc_id) for doc_id, meta in updated_rows],
                page_size=args.batch_size,
            )
        conn.commit()
        logger.info("Migration uygulandı: %d chunk güncellendi.", len(updated_rows))
        return 0
    finally:
        conn.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR.parent / ".env")

    parser = argparse.ArgumentParser(
        description="academic_year/document_year/source_public_url metadata migration"
    )
    parser.add_argument("--apply", action="store_true", help="Dry-run yerine veritabanına yaz.")
    parser.add_argument(
        "--recompute-years",
        action="store_true",
        help="Mevcut academic_year/document_year değerlerini yeniden hesapla.",
    )
    parser.add_argument("--table", default="haystack_docs", help="Haystack tablo adı.")
    parser.add_argument("--batch-size", type=int, default=500, help="UPDATE batch boyutu.")
    parser.add_argument("--report-limit", type=int, default=12, help="Rapor örnek sayısı.")
    parser.add_argument(
        "--manifest",
        action="append",
        default=[str(path) for path in DEFAULT_SOURCE_MANIFESTS],
        help="PDF link manifest JSON yolu. Birden fazla kez verilebilir.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL bağlantı adresi. Varsayılan .env içindeki DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error("DATABASE_URL bulunamadı. .env veya --database-url ile belirtin.")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args(argv or sys.argv[1:])
    return migrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
