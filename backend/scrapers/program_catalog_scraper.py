"""
GİBTÜ bölüm/program katalog scraper'ı.

Bu modül genel crawler değildir. Yalnızca verilen seed kaynaklardan akademik
birim -> bölüm/program kapsamını tamamlamaya çalışır ve dry-run kalite raporu
üretir. Aday öğrenci sayfası destekleyici kaynak kabul edilir; tek başına aktif
program kanıtı sayılmaz.
"""

from __future__ import annotations

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
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401

logger = logging.getLogger(__name__)

SCRAPER_NAME = "program_catalog_scraper"
METADATA_VERSION = "program_catalog.v1"

GIBTU_BASE_URL = "https://www.gibtu.edu.tr"
ACADEMIC_UNITS_URL = f"{GIBTU_BASE_URL}/akademikbirim"
CANDIDATE_URL = "https://adayogrenci.gibtu.edu.tr/Default.aspx"
YOKATLAS_BASE_URL = "https://yokatlas.yok.gov.tr"

REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
RATE_LIMIT_SECONDS = 0.5
MAX_GIBTU_PAGES = 150
MAX_CANDIDATE_POOL = 300

UNIT_TYPES = ("faculty", "school", "vocational_school", "institute")
EDUCATION_UNDERGRADUATE = "undergraduate"
EDUCATION_ASSOCIATE = "associate"
EDUCATION_GRADUATE = "graduate"
EDUCATION_UNKNOWN = "unknown"

SOURCE_PRIORITY = {
    "official_gibtu": 10,
    "yokatlas": 20,
    "candidate": 30,
}

REJECT_TERMS = (
    "haber",
    "duyuru",
    "etkinlik",
    "ihale",
    "kalite",
    "yönetim",
    "yonetim",
    "personel",
    "akademik personel",
    "idari personel",
    "iletişim",
    "iletisim",
    "galeri",
    "fotoğraf",
    "fotograf",
    "video",
    "arşiv",
    "arsiv",
    "mevzuat",
    "kurul",
    "komisyon",
    "danışman",
    "danisman",
    "rektörlük",
    "rektorluk",
    "sekreterlik",
)

ACADEMIC_TERMS = (
    "akademik birim",
    "fakülte",
    "fakulte",
    "yüksekokul",
    "yuksekokul",
    "meslek yüksekokulu",
    "meslek yuksekokulu",
    "enstitü",
    "enstitu",
    "bölüm",
    "bolum",
    "program",
    "lisans",
    "önlisans",
    "onlisans",
)

NON_EXISTENT_PROGRAM_GUARDS = {
    "hukuk",
    "dis hekimligi",
    "diş hekimliği",
    "psikoloji",
}

UNIVERSITY_PREFIX_RE = re.compile(
    r"^\s*(?:GİBTÜ|GIBTU|Gaziantep\s+İslam\s+Bilim\s+ve\s+Teknoloji\s+Üniversitesi)\s*[-–:]\s*",
    re.IGNORECASE,
)

ACADEMIC_SUBUNIT_TERMS = {
    "cerrahi tip bilimleri",
    "dahili tip bilimleri",
    "temel tip bilimleri",
}

STATIC_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "muhendislik ve doga bilimleri fakultesi": (
        "MDBF",
        "Mühendislik",
        "Mühendislik Fakültesi",
        "Mühendislik ve Doğa Bilimleri",
    ),
    "iktisadi idari ve sosyal bilimler fakultesi": (
        "İİSBF",
        "IISBF",
        "İİBF",
        "IIBF",
        "İktisadi İdari ve Sosyal Bilimler",
    ),
    "saglik hizmetleri meslek yuksekokulu": (
        "SHMYO",
        "Sağlık Hizmetleri MYO",
        "Sağlık MYO",
    ),
    "teknik bilimler meslek yuksekokulu": (
        "TBMYO",
        "Teknik Bilimler MYO",
        "Teknik MYO",
    ),
    "yabanci diller yuksekokulu": (
        "YDYO",
        "Yabancı Diller",
        "Yabancı Dil",
        "Yabancı Diller Y. O",
    ),
    "saglik bilimleri fakultesi": (
        "SBF",
        "Sağlık Bilimleri",
    ),
    "guzel sanatlar tasarim ve mimarlik fakultesi": (
        "GSMF",
        "GSTMF",
        "Güzel Sanatlar",
        "Gastronomi Fakültesi",
    ),
}

STATIC_PROGRAM_ALIASES: dict[str, tuple[str, ...]] = {
    "bilgisayar muhendisligi": (
        "BM",
        "bilgisayar müh",
        "bilgisayar muh",
        "bilg müh",
        "bilg muh",
    ),
    "elektrik elektronik muhendisligi": (
        "EEM",
        "EEE",
        "elektrik elektronik",
        "elektrik-elektronik",
    ),
    "endustri muhendisligi": (
        "EM",
        "endüstri",
        "endustri",
        "end müh",
        "end muh",
    ),
    "fizyoterapi ve rehabilitasyon": (
        "FTR",
    ),
    "hemsirelik": ("hemşirelik", "hemsirelik"),
    "ebelik": ("ebelik",),
    "ilahiyat": ("ilahiyat",),
    "gastronomi ve mutfak sanatlari": (
        "gastronomi",
        "gastronomi mutfak",
    ),
    "arapca mutercim ve tercumanlik": (
        "arapça mütercim",
        "arapca mutercim",
        "arapça tercümanlık",
        "arapca tercumanlik",
    ),
    "ingilizce mutercim ve tercumanlik": (
        "ingilizce mütercim",
        "ingilizce mutercim",
        "ing mütercim",
        "ing mutercim",
    ),
    "bilgisayar programciligi": (
        "BP",
        "bilgisayar program",
        "bilgisayar prog",
    ),
    "tibbi laboratuvar teknikleri": (
        "TLT",
        "tıbbi lab",
        "tibbi lab",
        "laboratuvar",
    ),
    "ilk ve acil yardim": (
        "ilk acil",
        "paramedik",
    ),
}


@dataclass
class CatalogUnitRecord:
    unit_name: str
    unit_type: str
    source_url: str | None
    source_type: str
    parent_unit_name: str | None = None
    normalized_unit_name: str = ""
    aliases: list[str] = field(default_factory=list)
    existing_academic_unit_id: str | None = None
    matched_academic_unit_key: str | None = None
    match_status: str = "unknown"
    needs_review: bool = False
    missing_in_current_run: bool = False
    snapshot_id: str | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        self.unit_name = clean_academic_name(self.unit_name)
        if self.parent_unit_name:
            self.parent_unit_name = clean_academic_name(self.parent_unit_name)
        if not self.normalized_unit_name:
            self.normalized_unit_name = normalize_for_match(self.unit_name)


@dataclass
class CatalogProgramRecord:
    program_name: str
    unit_name: str
    education_level: str
    source_url: str | None
    source_type: str
    item_kind: str = "program"
    normalized_program_name: str = ""
    normalized_unit_name: str = ""
    program_code: str | None = None
    yokatlas_url: str | None = None
    official_gibtu_url: str | None = None
    aliases: list[str] = field(default_factory=list)
    match_status: str = "unknown"
    needs_review: bool = False
    missing_in_current_run: bool = False
    snapshot_id: str | None = None
    checksum: str | None = None
    evidence_text: str | None = None

    def __post_init__(self) -> None:
        if not self.normalized_program_name:
            self.normalized_program_name = normalize_program_name(self.program_name)
        if not self.normalized_unit_name:
            self.normalized_unit_name = normalize_for_match(self.unit_name)


@dataclass
class SnapshotRecord:
    snapshot_id: str
    source_url: str
    source_type: str
    http_status: int | None
    checksum: str
    fetched_at: str
    path: str | None = None
    parse_status: str = "unknown"


@dataclass
class QualityIssue:
    severity: str
    issue_code: str
    message: str
    source_url: str | None = None
    entity_type: str | None = None
    entity_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProgramCatalogReport:
    success: bool
    scrape_run_id: str
    started_at: str
    finished_at: str = ""
    scraper_name: str = SCRAPER_NAME
    metadata_version: str = METADATA_VERSION
    dry_run: bool = True
    write_db_requested: bool = False
    production_db_write_attempted: bool = False
    processed_url_count: int = 0
    skipped_url_count: int = 0
    successful_url_count: int = 0
    failed_url_count: int = 0
    not_processed_due_to_limit_count: int = 0
    candidate_pool_count: int = 0
    units: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    quality_issues: list[dict[str, Any]] = field(default_factory=list)
    validation_report: dict[str, Any] = field(default_factory=dict)
    import_summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_for_match(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).casefold()
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_program_name(value: Any) -> str:
    text = normalize_for_match(value)
    text = re.sub(r"\bbolumu\b|\bprogrami\b|\bprogram\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def display_clean_name(value: str) -> str:
    text = " ".join(str(value or "").replace("\xa0", " ").split())
    text = re.sub(r"^\W+|\W+$", "", text)
    return text.strip()


def clean_academic_name(value: str) -> str:
    text = display_clean_name(value)
    previous = None
    while previous != text:
        previous = text
        text = UNIVERSITY_PREFIX_RE.sub("", text).strip()
    return display_clean_name(text)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url or GIBTU_BASE_URL, url)
    parsed = urlparse(absolute)
    scheme = "https"
    host = parsed.netloc.lower()
    if host == "gibtu.edu.tr":
        host = "www.gibtu.edu.tr"
    path = parsed.path or "/"
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() in {"utm_source", "utm_medium", "utm_campaign", "fbclid"}:
            continue
        query_pairs.append((key, value))
    query = urlencode(sorted(query_pairs))
    return urlunparse((scheme, host, path, "", query, "")).rstrip("/")


def infer_unit_type(name: str) -> str | None:
    normalized = normalize_for_match(clean_academic_name(name))
    if normalized in {"fakulteler", "yuksekokullar", "meslek yuksekokullari", "enstituler"}:
        return None
    if "bolumu" in normalized or "programi" in normalized:
        return None
    if len(normalized.split()) > 8:
        return None
    if "meslek yuksekokulu" in normalized or normalized.endswith("myo"):
        return "vocational_school"
    if normalized.endswith("fakultesi") or normalized.endswith("fakulte"):
        return "faculty"
    if normalized.endswith("yuksekokulu") or normalized.endswith("yuksekokul") or normalized.endswith("y o"):
        return "school"
    if normalized.endswith("enstitusu") or normalized.endswith("enstitu"):
        return "institute"
    return None


def education_level_from_unit(unit_name: str, source_level: str | None = None) -> str:
    normalized = normalize_for_match(source_level or "")
    if normalized in {"undergraduate", "lisans"}:
        return EDUCATION_UNDERGRADUATE
    if normalized in {"associate", "onlisans", "on lisans", "önlisans"}:
        return EDUCATION_ASSOCIATE
    if normalized in {"graduate", "lisansustu", "lisans ustu"}:
        return EDUCATION_GRADUATE
    unit_normalized = normalize_for_match(unit_name)
    if "meslek yuksekokulu" in unit_normalized:
        return EDUCATION_ASSOCIATE
    if "fakultesi" in unit_normalized:
        return EDUCATION_UNDERGRADUATE
    if "enstitu" in unit_normalized:
        return EDUCATION_GRADUATE
    return EDUCATION_UNKNOWN


def item_kind_from_unit(unit_name: str) -> str:
    return "program" if education_level_from_unit(unit_name) == EDUCATION_ASSOCIATE else "department"


def item_kind_from_record(unit_name: str, record_name: str) -> str:
    normalized = normalize_program_name(record_name)
    if normalized in ACADEMIC_SUBUNIT_TERMS or "ana bilim dali" in normalized:
        return "academic_department"
    return item_kind_from_unit(unit_name)


def decode_response(response: requests.Response) -> str:
    raw = response.content or b""
    candidates = [
        _charset_from_header(response.headers.get("Content-Type")),
        getattr(response, "apparent_encoding", None),
        "utf-8",
        "windows-1254",
        "iso-8859-9",
        getattr(response, "encoding", None),
    ]
    decoded: list[tuple[int, str]] = []
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        encoding_key = encoding.lower()
        if encoding_key in seen:
            continue
        seen.add(encoding_key)
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        decoded.append((text.count("\ufffd") + text.count("Ã") + text.count("Ä"), text))
    if decoded:
        decoded.sort(key=lambda item: item[0])
        return decoded[0][1]
    return raw.decode("utf-8", errors="replace")


def _charset_from_header(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"charset=([^;\s]+)", value, flags=re.IGNORECASE)
    return match.group(1).strip("\"'") if match else None


def page_title(soup: BeautifulSoup) -> str:
    for selector in ("span.sayfa_baslik", "h1", "h2", "title"):
        node = soup.select_one(selector)
        if node:
            text = display_clean_name(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


class SnapshotStore:
    def __init__(self, output_dir: Path | None, run_id: str) -> None:
        self.output_dir = output_dir
        self.run_id = run_id
        self.records: list[SnapshotRecord] = []

    def store(
        self,
        source_url: str,
        source_type: str,
        content: str,
        http_status: int | None,
        parse_status: str = "ok",
    ) -> SnapshotRecord:
        checksum = sha256_text(content)
        snapshot_id = sha256_text(f"{source_type}:{source_url}:{checksum}")[:24]
        path: str | None = None
        if self.output_dir:
            snapshot_dir = self.output_dir / "snapshots" / self.run_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            suffix = "json" if source_type == "yokatlas" else "html"
            snapshot_path = snapshot_dir / f"{source_type}_{snapshot_id}.{suffix}"
            snapshot_path.write_text(content, encoding="utf-8")
            path = str(snapshot_path)
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            source_url=source_url,
            source_type=source_type,
            http_status=http_status,
            checksum=checksum,
            fetched_at=utc_now_iso(),
            path=path,
            parse_status=parse_status,
        )
        self.records.append(record)
        return record


class ProgramCatalogScraper:
    """Seed tabanlı kontrollü akademik keşif ve karşılaştırma scraper'ı."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        rate_limit_seconds: float = RATE_LIMIT_SECONDS,
        max_gibtu_pages: int = MAX_GIBTU_PAGES,
        max_candidate_pool: int = MAX_CANDIDATE_POOL,
        cached_yokatlas_report: str | Path | None = None,
        use_live_yokatlas: bool = False,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; UniChatProgramCatalogScraper/1.0; +https://www.gibtu.edu.tr)",
        })
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limit_seconds = rate_limit_seconds
        self.max_gibtu_pages = max_gibtu_pages
        self.max_candidate_pool = max_candidate_pool
        self.cached_yokatlas_report = Path(cached_yokatlas_report) if cached_yokatlas_report else (
            Path(__file__).resolve().parent.parent / "data" / "yokatlas" / "gibtu_yokatlas_report.json"
        )
        self.use_live_yokatlas = use_live_yokatlas
        self._last_request_at = 0.0

    def scrape(
        self,
        dry_run: bool = True,
        write_db: bool = False,
        output_dir: str | Path | None = None,
    ) -> ProgramCatalogReport:
        started_at = utc_now_iso()
        run_id = f"{SCRAPER_NAME}:{sha256_text(started_at)[:16]}"
        output_path = Path(output_dir) if output_dir else None
        snapshot_store = SnapshotStore(output_path, sha256_text(run_id)[:16])
        issues: list[QualityIssue] = []

        report = ProgramCatalogReport(
            success=False,
            scrape_run_id=run_id,
            started_at=started_at,
            dry_run=dry_run,
            write_db_requested=write_db,
        )

        official_units, official_records, crawl_stats = self._crawl_official_gibtu(snapshot_store, issues)
        candidate_units, candidate_records = self._parse_candidate_source(snapshot_store, issues)
        yokatlas_records = self._load_yokatlas_records(snapshot_store, issues, output_path)

        combined_units = self._combine_units(official_units, candidate_units, yokatlas_records)
        combined_records = self._compare_records(official_records, candidate_records, yokatlas_records, issues)
        self._attach_aliases(combined_units, combined_records)

        validation = self._build_validation_report(
            combined_units=combined_units,
            combined_records=combined_records,
            issues=issues,
            crawl_stats=crawl_stats,
        )

        report.finished_at = utc_now_iso()
        report.processed_url_count = crawl_stats["processed_url_count"]
        report.skipped_url_count = crawl_stats["skipped_url_count"]
        report.successful_url_count = crawl_stats["successful_url_count"]
        report.failed_url_count = crawl_stats["failed_url_count"]
        report.not_processed_due_to_limit_count = crawl_stats["not_processed_due_to_limit_count"]
        report.candidate_pool_count = crawl_stats["candidate_pool_count"]
        report.units = [asdict(unit) for unit in combined_units]
        report.records = [asdict(record) for record in combined_records]
        report.snapshots = [asdict(snapshot) for snapshot in snapshot_store.records]
        report.quality_issues = [asdict(issue) for issue in issues]
        report.validation_report = validation
        report.success = validation["critical_error_count"] == 0
        report.errors = [issue.message for issue in issues if issue.severity == "critical"]
        report.import_summary = {
            "dry_run": dry_run,
            "write_db_requested": write_db,
            "write_db_executed": False,
            "production_db_write_attempted": False,
            "note": "DB yazımı yapılmadı. --write-db ayrıca açık onay gerektirir.",
        }

        if write_db and not dry_run:
            from app.repositories.program_catalog_repository import ProgramCatalogRepository

            repo = ProgramCatalogRepository()
            report.import_summary = repo.import_report(report.to_dict())

        return report

    def _crawl_official_gibtu(
        self,
        snapshot_store: SnapshotStore,
        issues: list[QualityIssue],
    ) -> tuple[list[CatalogUnitRecord], list[CatalogProgramRecord], dict[str, int]]:
        queue: list[str] = [canonical_url(ACADEMIC_UNITS_URL)]
        visited: set[str] = set()
        queued: set[str] = set(queue)
        skipped: set[str] = set()
        official_units: dict[str, CatalogUnitRecord] = {}
        official_records: dict[tuple[str, str], CatalogProgramRecord] = {}
        processed = successful = failed = 0
        candidate_pool_count = 0
        not_processed_due_to_limit = 0

        while queue and processed < self.max_gibtu_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                html, status_code = self._fetch(url)
            except Exception as exc:  # noqa: BLE001 - fail-fast sayfa bazlı
                failed += 1
                issues.append(QualityIssue("warning", "official_fetch_failed", str(exc), source_url=url))
                continue

            processed += 1
            if not html:
                failed += 1
                issues.append(QualityIssue("warning", "official_empty_page", "Boş veya erişilemeyen GİBTÜ sayfası.", url))
                continue

            successful += 1
            snapshot = snapshot_store.store(url, "official_gibtu", html, status_code)
            soup = BeautifulSoup(html, "html.parser")
            title = page_title(soup)
            page_text = self._main_text(soup)
            is_academic_root = canonical_url(url) == canonical_url(ACADEMIC_UNITS_URL)

            if is_academic_root:
                for unit in self._extract_units(soup, url, snapshot.snapshot_id, snapshot.checksum):
                    key = unit.normalized_unit_name
                    if key not in official_units:
                        official_units[key] = unit
                for record in self._extract_root_site_map_records(
                    soup,
                    official_units,
                    url,
                    snapshot.snapshot_id,
                    snapshot.checksum,
                ):
                    official_records[(record.normalized_unit_name, record.normalized_program_name)] = record

            for link in soup.find_all("a", href=True):
                if candidate_pool_count >= self.max_candidate_pool:
                    break
                href = str(link.get("href") or "")
                link_url = canonical_url(href, url)
                if link_url in visited or link_url in queued:
                    continue
                link_text = display_clean_name(link.get_text(" ", strip=True))
                context = self._link_context(link, title, page_text)
                decision = self.evaluate_url_candidate(link_url, link_text, title, context)
                candidate_pool_count += 1
                if decision["accepted"]:
                    queue.append(link_url)
                    queued.add(link_url)
                else:
                    skipped.add(link_url)

        if queue:
            not_processed_due_to_limit = len(queue)
            for url in queue[:20]:
                issues.append(QualityIssue(
                    "warning",
                    "not_processed_due_to_limit",
                    "GİBTÜ sayfa limiti nedeniyle işlenmedi.",
                    source_url=url,
                ))

        if not official_units:
            issues.append(QualityIssue(
                "critical",
                "official_units_not_found",
                "GİBTÜ akademik birim kaynağından akademik birim çıkarılamadı.",
                source_url=ACADEMIC_UNITS_URL,
            ))

        return list(official_units.values()), list(official_records.values()), {
            "processed_url_count": processed,
            "skipped_url_count": len(skipped),
            "successful_url_count": successful,
            "failed_url_count": failed,
            "not_processed_due_to_limit_count": not_processed_due_to_limit,
            "candidate_pool_count": candidate_pool_count,
        }

    def evaluate_url_candidate(
        self,
        url: str,
        link_text: str,
        page_title_text: str = "",
        context_text: str = "",
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host not in {"www.gibtu.edu.tr", "gibtu.edu.tr", "adayogrenci.gibtu.edu.tr"}:
            return {"accepted": False, "reason": "domain_not_allowed"}

        url_norm = normalize_for_match(url)
        text_norm = normalize_for_match(link_text)
        context_norm = normalize_for_match(context_text)
        combined = " ".join([url_norm, text_norm, context_norm])
        explicit_academic_text = bool(
            infer_unit_type(link_text)
            or "bolumu" in text_norm
            or "programi" in text_norm
            or any(term in text_norm for term in ("fakulte", "yuksekokul", "myo", "enstitu"))
        )
        if any(term in combined for term in (normalize_for_match(item) for item in REJECT_TERMS)):
            if not explicit_academic_text:
                return {"accepted": False, "reason": "reject_context"}

        if url.rstrip("/") == canonical_url(ACADEMIC_UNITS_URL):
            return {"accepted": True, "reason": "seed_academic_units"}

        path_name = Path(parsed.path.lower()).name
        if path_name in {"birim.aspx", "birimakademikbirimler.aspx"}:
            if explicit_academic_text or any(term in context_norm for term in ("site map", "fakulte", "yuksekokul", "myo", "enstitu", "bolum", "program")):
                return {"accepted": True, "reason": "academic_unit_page"}
            return {"accepted": False, "reason": "birim_without_academic_context"}

        if host == "adayogrenci.gibtu.edu.tr":
            if any(term in combined for term in ("program", "bolum", "tanitim", "tercih", "ogrenim", "aday")):
                return {"accepted": True, "reason": "candidate_program_context"}
            return {"accepted": False, "reason": "candidate_unrelated"}

        if any(normalize_for_match(term) in " ".join([text_norm, context_norm]) for term in ACADEMIC_TERMS):
            return {"accepted": True, "reason": "academic_context"}

        return {"accepted": False, "reason": "no_academic_context"}

    def _fetch(self, url: str) -> tuple[str | None, int | None]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
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
                return decode_response(response), status_code
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.0 * attempt)
        raise RuntimeError(f"URL alınamadı: {url} ({last_error})")

    def _rate_limit(self) -> None:
        if not self._last_request_at:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    @staticmethod
    def _main_text(soup: BeautifulSoup) -> str:
        root = soup.select_one("div.birim_safya_body_detay, main, body") or soup
        for selector in (
            "script",
            "style",
            "header",
            "nav",
            "footer",
            "aside",
            ".breadcrumb",
            ".breadcrumbs",
            ".sidebar",
            ".side-nav",
            ".sidenav",
            "ul.collapsible",
        ):
            for node in root.select(selector):
                node.decompose()
        return display_clean_name(root.get_text(" ", strip=True))

    @staticmethod
    def _link_context(link: Tag, title: str, page_text: str) -> str:
        parent = link.find_parent(["li", "div", "section", "article"])
        parent_text = display_clean_name(parent.get_text(" ", strip=True)) if parent else ""
        return parent_text[:300]

    def _current_unit_from_page(
        self,
        title: str,
        url: str,
        units_by_key: dict[str, CatalogUnitRecord],
    ) -> CatalogUnitRecord | None:
        title = clean_academic_name(title)
        title_type = infer_unit_type(title)
        if title_type:
            return CatalogUnitRecord(
                unit_name=title,
                unit_type=title_type,
                source_url=url,
                source_type="official_gibtu",
                aliases=list(STATIC_UNIT_ALIASES.get(normalize_for_match(title), ())),
                matched_academic_unit_key=normalize_for_match(title),
            )
        for unit in units_by_key.values():
            if unit.source_url and canonical_url(unit.source_url) == canonical_url(url):
                return unit
        return None

    @staticmethod
    def _extract_units(
        soup: BeautifulSoup,
        source_url: str,
        snapshot_id: str,
        checksum: str,
    ) -> list[CatalogUnitRecord]:
        units: list[CatalogUnitRecord] = []
        seen: set[str] = set()
        for node in soup.find_all(["a", "h1", "h2", "h3", "span"]):
            text = clean_academic_name(node.get_text(" ", strip=True))
            if not text or len(text) > 120:
                continue
            unit_type = infer_unit_type(text)
            if not unit_type:
                continue
            normalized = normalize_for_match(text)
            if normalized in seen:
                continue
            seen.add(normalized)
            href = node.get("href") if isinstance(node, Tag) else None
            unit_url = canonical_url(str(href), source_url) if href else source_url
            units.append(CatalogUnitRecord(
                unit_name=text,
                unit_type=unit_type,
                source_url=unit_url,
                source_type="official_gibtu",
                aliases=list(STATIC_UNIT_ALIASES.get(normalized, ())),
                matched_academic_unit_key=normalized,
                snapshot_id=snapshot_id,
                checksum=checksum,
                match_status="official",
            ))
        return units

    @staticmethod
    def _extract_root_site_map_records(
        soup: BeautifulSoup,
        units_by_key: dict[str, CatalogUnitRecord],
        source_url: str,
        snapshot_id: str,
        checksum: str,
    ) -> list[CatalogProgramRecord]:
        records: list[CatalogProgramRecord] = []
        seen: set[tuple[str, str]] = set()
        allowed_categories = {
            "fakulteler",
            "meslek yuksekokullari",
            "yuksekokullar",
            "enstituler",
        }

        for category in soup.select("span.site-map-kat-ad"):
            category_name = normalize_for_match(category.get_text(" ", strip=True))
            if category_name not in allowed_categories:
                continue
            category_item = category.find_parent("li")
            if not category_item:
                continue
            unit_list = category_item.find("ul", recursive=False)
            if not unit_list:
                continue
            for unit_item in unit_list.find_all("li", recursive=False):
                unit_link = ProgramCatalogScraper._first_direct_site_map_link(unit_item)
                if not unit_link:
                    continue
                unit_name = clean_academic_name(unit_link.get_text(" ", strip=True))
                unit_type = infer_unit_type(unit_name)
                if not unit_type:
                    continue
                unit_url = canonical_url(str(unit_link.get("href") or ""), source_url)
                unit_key = normalize_for_match(unit_name)
                current_unit = units_by_key.get(unit_key) or CatalogUnitRecord(
                    unit_name=unit_name,
                    unit_type=unit_type,
                    source_url=unit_url,
                    source_type="official_gibtu",
                    aliases=list(STATIC_UNIT_ALIASES.get(unit_key, ())),
                    matched_academic_unit_key=unit_key,
                    snapshot_id=snapshot_id,
                    checksum=checksum,
                    match_status="official",
                )
                units_by_key.setdefault(unit_key, current_unit)

                child_list = unit_item.find("ul", recursive=False)
                if not child_list:
                    continue
                for child_item in child_list.find_all("li", recursive=False):
                    child_link = ProgramCatalogScraper._first_direct_site_map_link(child_item)
                    if not child_link:
                        continue
                    record = ProgramCatalogScraper._record_from_unit_leaf(
                        child_link,
                        current_unit,
                        source_url,
                        snapshot_id,
                        checksum,
                    )
                    if not record:
                        continue
                    key = (record.normalized_unit_name, record.normalized_program_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append(record)
        return records

    @staticmethod
    def _first_direct_site_map_link(node: Tag) -> Tag | None:
        for child in node.children:
            if isinstance(child, Tag) and child.name == "a" and "site-map-link" in (child.get("class") or []):
                return child
        return None

    @staticmethod
    def _record_from_unit_leaf(
        node: Tag,
        current_unit: CatalogUnitRecord,
        source_url: str,
        snapshot_id: str,
        checksum: str,
    ) -> CatalogProgramRecord | None:
        text = display_clean_name(node.get_text(" ", strip=True))
        if not text or len(text) > 100:
            return None
        normalized = normalize_for_match(text)
        if infer_unit_type(text):
            return None
        if any(term in normalized for term in (
            "baskan",
            "yonetim",
            "sekreter",
            "duyuru",
            "haber",
            "kalite",
            "staj",
            "basvuru",
            "is ve islemleri",
            "ogrenci isleri",
            "ogrenci kulubu",
            "arastirma merkezi",
            "uygulama ve arastirma",
        )):
            return None

        unit_level = education_level_from_unit(current_unit.unit_name)
        if unit_level == EDUCATION_ASSOCIATE and "bolumu" in normalized:
            return None
        has_explicit_marker = "bolumu" in normalized or "programi" in normalized
        has_allowed_context = unit_level in {
            EDUCATION_UNDERGRADUATE,
            EDUCATION_ASSOCIATE,
            EDUCATION_GRADUATE,
        }
        if not has_explicit_marker and not has_allowed_context:
            return None

        program_name = re.sub(r"\s+Bölümü$", "", text, flags=re.IGNORECASE)
        program_name = re.sub(r"\s+Programı$", "", program_name, flags=re.IGNORECASE)
        program_norm = normalize_program_name(program_name)
        if not program_norm:
            return None
        record_url = canonical_url(str(node.get("href") or ""), source_url)
        return CatalogProgramRecord(
            program_name=program_name,
            unit_name=current_unit.unit_name,
            education_level=unit_level,
            source_url=record_url,
            source_type="official_gibtu",
            item_kind=item_kind_from_record(current_unit.unit_name, program_name),
            aliases=list(STATIC_PROGRAM_ALIASES.get(program_norm, ())),
            official_gibtu_url=record_url,
            snapshot_id=snapshot_id,
            checksum=checksum,
            evidence_text=text,
        )

    @staticmethod
    def _extract_program_records(
        soup: BeautifulSoup,
        current_unit: CatalogUnitRecord,
        source_url: str,
        snapshot_id: str,
        checksum: str,
    ) -> list[CatalogProgramRecord]:
        if canonical_url(source_url) in {canonical_url(GIBTU_BASE_URL), canonical_url(ACADEMIC_UNITS_URL)}:
            return []
        records: list[CatalogProgramRecord] = []
        seen: set[str] = set()
        for node in soup.find_all(["a", "li", "h2", "h3", "span"]):
            record = ProgramCatalogScraper._record_from_unit_leaf(
                node,
                current_unit,
                source_url,
                snapshot_id,
                checksum,
            )
            if not record:
                continue
            if record.normalized_program_name in seen:
                continue
            seen.add(record.normalized_program_name)
            records.append(record)
        return records

    def _parse_candidate_source(
        self,
        snapshot_store: SnapshotStore,
        issues: list[QualityIssue],
    ) -> tuple[list[CatalogUnitRecord], list[CatalogProgramRecord]]:
        try:
            html, status = self._fetch(CANDIDATE_URL)
        except Exception as exc:  # noqa: BLE001
            issues.append(QualityIssue("warning", "candidate_fetch_failed", str(exc), source_url=CANDIDATE_URL))
            return [], []
        if not html:
            issues.append(QualityIssue("warning", "candidate_empty_page", "Aday öğrenci sayfası boş.", source_url=CANDIDATE_URL))
            return [], []

        snapshot = snapshot_store.store(CANDIDATE_URL, "candidate", html, status)
        soup = BeautifulSoup(html, "html.parser")
        units: dict[str, CatalogUnitRecord] = {}
        records: dict[tuple[str, str], CatalogProgramRecord] = {}
        section_specs = (
            ("yukseklisans_listesi", EDUCATION_GRADUATE),
            ("lisans_listesi", EDUCATION_UNDERGRADUATE),
            ("onlisans_listesi", EDUCATION_ASSOCIATE),
        )

        for section_class, level in section_specs:
            for section in soup.select(f"section.{section_class}"):
                for card in section.select(".faculty-card"):
                    title_node = card.select_one(".faculty-card-title")
                    unit_text = display_clean_name(title_node.get_text(" ", strip=True) if title_node else "")
                    unit_name = clean_academic_name(re.sub(r"\|\s*\d+\s*YIL", "", unit_text, flags=re.IGNORECASE).strip())
                    if not unit_name:
                        continue
                    unit_type = infer_unit_type(unit_name)
                    if not unit_type:
                        continue
                    unit = CatalogUnitRecord(
                        unit_name=unit_name,
                        unit_type=unit_type,
                        source_url=CANDIDATE_URL,
                        source_type="candidate",
                        aliases=list(STATIC_UNIT_ALIASES.get(normalize_for_match(unit_name), ())),
                        match_status="candidate_support",
                        needs_review=True,
                        snapshot_id=snapshot.snapshot_id,
                        checksum=snapshot.checksum,
                    )
                    units.setdefault(unit.normalized_unit_name, unit)
                    child_items = card.select(".faculty-card-list li")
                    if not child_items and level == EDUCATION_GRADUATE:
                        continue
                    for item in child_items:
                        program_name = display_clean_name(item.get_text(" ", strip=True))
                        if not program_name:
                            continue
                        program_norm = normalize_program_name(program_name)
                        records[(unit.normalized_unit_name, program_norm)] = CatalogProgramRecord(
                            program_name=program_name,
                            unit_name=unit_name,
                            education_level=level,
                            source_url=CANDIDATE_URL,
                            source_type="candidate",
                            item_kind="program" if level == EDUCATION_ASSOCIATE else "department",
                            aliases=list(STATIC_PROGRAM_ALIASES.get(program_norm, ())),
                            needs_review=True,
                            snapshot_id=snapshot.snapshot_id,
                            checksum=snapshot.checksum,
                            evidence_text=program_name,
                        )

        return list(units.values()), list(records.values())

    def _load_yokatlas_records(
        self,
        snapshot_store: SnapshotStore,
        issues: list[QualityIssue],
        output_dir: Path | None,
    ) -> list[CatalogProgramRecord]:
        report: dict[str, Any] | None = None
        if self.use_live_yokatlas:
            try:
                from scrapers.yokatlas_gibtu_scraper import YokatlasGibtuScraper

                live_report_path = output_dir / "yokatlas_live_report.json" if output_dir else None
                yok_report = YokatlasGibtuScraper(output_dir=output_dir).scrape(
                    report_json=live_report_path,
                    dry_run=True,
                )
                report = yok_report.to_dict()
            except Exception as exc:  # noqa: BLE001
                issues.append(QualityIssue("warning", "yokatlas_live_failed", str(exc), source_url=YOKATLAS_BASE_URL))

        if report is None:
            if not self.cached_yokatlas_report.exists():
                issues.append(QualityIssue(
                    "critical",
                    "yokatlas_report_missing",
                    "YÖK Atlas cached raporu bulunamadı ve live mod başarılı olmadı.",
                    source_url=str(self.cached_yokatlas_report),
                ))
                return []
            report = json.loads(self.cached_yokatlas_report.read_text(encoding="utf-8"))

        snapshot = snapshot_store.store(
            source_url=str(self.cached_yokatlas_report if not self.use_live_yokatlas else YOKATLAS_BASE_URL),
            source_type="yokatlas",
            content=json.dumps(report, ensure_ascii=False, indent=2),
            http_status=None,
            parse_status="ok",
        )
        records: list[CatalogProgramRecord] = []
        for item in report.get("programs") or []:
            program = item.get("program") or {}
            unit = item.get("academic_unit") or {}
            year = item.get("program_year") or {}
            raw_name = str(program.get("program_name_raw") or "").strip()
            clean_name = str(program.get("program_name_clean") or raw_name).strip()
            unit_name = str(unit.get("name") or "").strip()
            if not raw_name or not unit_name:
                continue
            level = str(program.get("level") or "")
            if normalize_for_match(level) not in {"lisans", "onlisans", "on lisans", "undergraduate", "associate"}:
                continue
            records.append(CatalogProgramRecord(
                program_name=raw_name,
                unit_name=unit_name,
                education_level=education_level_from_unit(unit_name, level),
                source_url=year.get("source_url"),
                source_type="yokatlas",
                item_kind="program" if level == "onlisans" else "department",
                normalized_program_name=normalize_program_name(clean_name),
                program_code=str(program.get("program_code")) if program.get("program_code") is not None else None,
                yokatlas_url=year.get("source_url"),
                aliases=list(STATIC_PROGRAM_ALIASES.get(normalize_program_name(clean_name), ())),
                snapshot_id=snapshot.snapshot_id,
                checksum=snapshot.checksum,
                match_status="yokatlas",
                evidence_text=raw_name,
            ))
        if not records:
            issues.append(QualityIssue("critical", "yokatlas_programs_empty", "YÖK Atlas program envanteri boş."))
        return records

    @staticmethod
    def _combine_units(
        official_units: list[CatalogUnitRecord],
        candidate_units: list[CatalogUnitRecord],
        yokatlas_records: list[CatalogProgramRecord],
    ) -> list[CatalogUnitRecord]:
        units: dict[str, CatalogUnitRecord] = {}
        for unit in official_units:
            unit.match_status = "official"
            unit.needs_review = False
            units[unit.normalized_unit_name] = unit
        official_alias_keys: dict[str, str] = {}
        for unit in units.values():
            alias_values = {unit.unit_name, *unit.aliases, *STATIC_UNIT_ALIASES.get(unit.normalized_unit_name, ())}
            for alias in alias_values:
                alias_key = normalize_for_match(alias)
                if alias_key:
                    official_alias_keys[alias_key] = unit.normalized_unit_name
        for record in yokatlas_records:
            key = record.normalized_unit_name
            alias_key = official_alias_keys.get(key)
            if key in units:
                continue
            if alias_key and alias_key in units:
                units[alias_key].aliases = sorted(set([*units[alias_key].aliases, record.unit_name]))
                continue
            units[key] = CatalogUnitRecord(
                unit_name=record.unit_name,
                unit_type=infer_unit_type(record.unit_name) or ("vocational_school" if record.education_level == EDUCATION_ASSOCIATE else "faculty"),
                source_url=record.yokatlas_url,
                source_type="yokatlas",
                aliases=list(STATIC_UNIT_ALIASES.get(key, ())),
                match_status="yokatlas_only",
                needs_review=True,
                snapshot_id=record.snapshot_id,
                checksum=record.checksum,
            )
        for unit in candidate_units:
            alias_key = official_alias_keys.get(unit.normalized_unit_name)
            if unit.normalized_unit_name in units:
                units[unit.normalized_unit_name].aliases = sorted(set([*units[unit.normalized_unit_name].aliases, unit.unit_name, *unit.aliases]))
                continue
            if alias_key and alias_key in units:
                units[alias_key].aliases = sorted(set([*units[alias_key].aliases, unit.unit_name, *unit.aliases]))
                continue
            unit.match_status = "candidate_only"
            unit.needs_review = True
            units[unit.normalized_unit_name] = unit
        return sorted(units.values(), key=lambda item: (item.unit_type, item.unit_name))

    @staticmethod
    def _compare_records(
        official_records: list[CatalogProgramRecord],
        candidate_records: list[CatalogProgramRecord],
        yokatlas_records: list[CatalogProgramRecord],
        issues: list[QualityIssue],
    ) -> list[CatalogProgramRecord]:
        by_program: dict[str, dict[str, list[CatalogProgramRecord]]] = {}
        for source_name, records in (
            ("official", official_records),
            ("candidate", candidate_records),
            ("yokatlas", yokatlas_records),
        ):
            for record in records:
                by_program.setdefault(record.normalized_program_name, {}).setdefault(source_name, []).append(record)

        combined: list[CatalogProgramRecord] = []
        seen_entity_keys: set[tuple[str, str, str]] = set()
        for program_key, groups in sorted(by_program.items()):
            official = groups.get("official") or []
            candidate = groups.get("candidate") or []
            yokatlas = groups.get("yokatlas") or []
            official_units = {item.normalized_unit_name for item in official}
            yok_units = {item.normalized_unit_name for item in yokatlas}

            if official and yokatlas and official_units.intersection(yok_units):
                primary = ProgramCatalogScraper._merge_primary(official, yokatlas, candidate)
                primary.match_status = "matched"
                primary.needs_review = False
            elif official and yokatlas:
                primary = ProgramCatalogScraper._merge_primary(official, yokatlas, candidate)
                primary.match_status = "conflict"
                primary.needs_review = True
                issues.append(QualityIssue(
                    "warning",
                    "unit_conflict",
                    "GİBTÜ resmi kaynak ile YÖK Atlas program birimi eşleşmiyor.",
                    entity_type="program",
                    entity_name=primary.program_name,
                    details={
                        "official_units": sorted(item.unit_name for item in official),
                        "yokatlas_units": sorted(item.unit_name for item in yokatlas),
                    },
                ))
            elif official:
                primary = official[0]
                primary.match_status = "official_only"
                primary.needs_review = True
            elif yokatlas:
                primary = yokatlas[0]
                primary.match_status = "yokatlas_only"
                primary.needs_review = True
            else:
                primary = candidate[0]
                primary.match_status = "candidate_only"
                primary.needs_review = True

            if candidate and primary.match_status == "candidate_only":
                primary.needs_review = True
            elif candidate:
                primary.aliases = sorted(set([*primary.aliases, *(candidate[0].aliases or [])]))

            entity_key = (primary.normalized_unit_name, primary.normalized_program_name, primary.education_level)
            if entity_key in seen_entity_keys:
                primary.needs_review = True
                primary.match_status = "duplicate"
                issues.append(QualityIssue(
                    "critical",
                    "duplicate_program",
                    "Aynı birim/program/seviye için duplicate kayıt oluştu.",
                    entity_type="program",
                    entity_name=primary.program_name,
                ))
            seen_entity_keys.add(entity_key)
            combined.append(primary)
        return combined

    @staticmethod
    def _merge_primary(
        official: list[CatalogProgramRecord],
        yokatlas: list[CatalogProgramRecord],
        candidate: list[CatalogProgramRecord],
    ) -> CatalogProgramRecord:
        official_record = official[0]
        yok_record = next(
            (item for item in yokatlas if item.normalized_unit_name == official_record.normalized_unit_name),
            yokatlas[0],
        )
        official_record.yokatlas_url = yok_record.yokatlas_url
        official_record.program_code = yok_record.program_code
        official_record.education_level = yok_record.education_level or official_record.education_level
        official_record.aliases = sorted(set([*official_record.aliases, *yok_record.aliases, *((candidate[0].aliases if candidate else []) or [])]))
        return official_record

    @staticmethod
    def _attach_aliases(units: list[CatalogUnitRecord], records: list[CatalogProgramRecord]) -> None:
        for unit in units:
            aliases = set(unit.aliases)
            aliases.add(unit.unit_name)
            normalized = normalize_for_match(unit.unit_name)
            aliases.update(STATIC_UNIT_ALIASES.get(normalized, ()))
            unit.aliases = sorted(alias for alias in aliases if alias)
        for record in records:
            aliases = set(record.aliases)
            aliases.add(record.program_name)
            normalized = record.normalized_program_name
            aliases.update(STATIC_PROGRAM_ALIASES.get(normalized, ()))
            record.aliases = sorted(alias for alias in aliases if alias)

    @staticmethod
    def _build_validation_report(
        combined_units: list[CatalogUnitRecord],
        combined_records: list[CatalogProgramRecord],
        issues: list[QualityIssue],
        crawl_stats: dict[str, int],
    ) -> dict[str, Any]:
        critical_count = sum(1 for issue in issues if issue.severity == "critical")
        duplicate_count = sum(1 for record in combined_records if record.match_status == "duplicate")
        needs_review = [record for record in combined_records if record.needs_review]
        status_counts: dict[str, int] = {}
        for record in combined_records:
            status_counts[record.match_status] = status_counts.get(record.match_status, 0) + 1
        unit_type_counts: dict[str, int] = {}
        for unit in combined_units:
            unit_type_counts[unit.unit_type] = unit_type_counts.get(unit.unit_type, 0) + 1
        alias_count = sum(len(unit.aliases) for unit in combined_units) + sum(len(record.aliases) for record in combined_records)
        schema_validation_success = ProgramCatalogScraper._schema_validation_success(combined_units, combined_records)
        chatbot_smoke = {"success_count": 0, "total": 0, "results": [], "success": False}
        db_write_ready = (
            critical_count == 0
            and duplicate_count == 0
            and schema_validation_success
            and chatbot_smoke["success_count"] >= 10
        )
        return {
            **crawl_stats,
            "academic_unit_count": len(combined_units),
            "faculty_count": unit_type_counts.get("faculty", 0),
            "school_count": unit_type_counts.get("school", 0),
            "vocational_school_count": unit_type_counts.get("vocational_school", 0),
            "institute_count": unit_type_counts.get("institute", 0),
            "department_count": sum(1 for record in combined_records if record.item_kind == "department"),
            "program_count": sum(1 for record in combined_records if record.item_kind == "program"),
            "match_status_counts": status_counts,
            "matched_records": [asdict(item) for item in combined_records if item.match_status == "matched"],
            "official_only_records": [asdict(item) for item in combined_records if item.match_status == "official_only"],
            "yokatlas_only_records": [asdict(item) for item in combined_records if item.match_status == "yokatlas_only"],
            "candidate_only_records": [asdict(item) for item in combined_records if item.match_status == "candidate_only"],
            "conflict_records": [asdict(item) for item in combined_records if item.match_status == "conflict"],
            "needs_review_records": [asdict(item) for item in needs_review],
            "duplicate_records": [asdict(item) for item in combined_records if item.match_status == "duplicate"],
            "alias_count": alias_count,
            "critical_error_count": critical_count,
            "duplicate_count": duplicate_count,
            "schema_validation_success": schema_validation_success,
            "dry_run_report_complete": True,
            "chatbot_db_first_smoke": chatbot_smoke,
            "db_write_ready": db_write_ready,
            "db_write_blockers": ProgramCatalogScraper._db_write_blockers(
                critical_count,
                duplicate_count,
                schema_validation_success,
                chatbot_smoke["success_count"],
            ),
            "production_db_write_attempted": False,
        }

    @staticmethod
    def _schema_validation_success(
        units: list[CatalogUnitRecord],
        records: list[CatalogProgramRecord],
    ) -> bool:
        if not units:
            return False
        for unit in units:
            if not unit.unit_name or unit.unit_type not in UNIT_TYPES:
                return False
        for record in records:
            if not record.program_name or not record.unit_name or not record.education_level:
                return False
        return True

    @staticmethod
    def _db_write_blockers(
        critical_count: int,
        duplicate_count: int,
        schema_ok: bool,
        chatbot_success_count: int,
    ) -> list[str]:
        blockers: list[str] = []
        if critical_count:
            blockers.append("critical_error_count_not_zero")
        if duplicate_count:
            blockers.append("duplicate_count_not_zero")
        if not schema_ok:
            blockers.append("schema_validation_failed")
        if chatbot_success_count < 10:
            blockers.append("chatbot_db_first_smoke_less_than_10")
        return blockers


def build_markdown_report(report: ProgramCatalogReport) -> str:
    validation = report.validation_report
    status_counts = validation.get("match_status_counts") or {}
    lines = [
        "# GİBTÜ Bölüm/Program Katalog Dry-Run Raporu",
        "",
        f"- Scrape run: `{report.scrape_run_id}`",
        f"- Başlangıç: `{report.started_at}`",
        f"- Bitiş: `{report.finished_at}`",
        "- DB yazımı: yapılmadı",
        f"- İşlenen URL: {validation.get('processed_url_count')}",
        f"- Atlanan URL: {validation.get('skipped_url_count')}",
        f"- Başarılı URL: {validation.get('successful_url_count')}",
        f"- Boş/erişilemeyen URL: {validation.get('failed_url_count')}",
        f"- Limit nedeniyle işlenmeyen URL: {validation.get('not_processed_due_to_limit_count')}",
        f"- Akademik birim: {validation.get('academic_unit_count')}",
        f"- Fakülte: {validation.get('faculty_count')}",
        f"- Yüksekokul: {validation.get('school_count')}",
        f"- MYO: {validation.get('vocational_school_count')}",
        f"- Enstitü: {validation.get('institute_count')}",
        f"- Bölüm: {validation.get('department_count')}",
        f"- Program: {validation.get('program_count')}",
        f"- Matched: {status_counts.get('matched', 0)}",
        f"- official_only: {status_counts.get('official_only', 0)}",
        f"- yokatlas_only: {status_counts.get('yokatlas_only', 0)}",
        f"- candidate_only: {status_counts.get('candidate_only', 0)}",
        f"- conflict: {status_counts.get('conflict', 0)}",
        f"- needs_review: {len(validation.get('needs_review_records') or [])}",
        f"- duplicate: {validation.get('duplicate_count')}",
        f"- alias: {validation.get('alias_count')}",
        f"- critical_error: {validation.get('critical_error_count')}",
        f"- Schema validation: {'başarılı' if validation.get('schema_validation_success') else 'başarısız'}",
        f"- DB write ready: {'evet' if validation.get('db_write_ready') else 'hayır'}",
    ]

    blockers = validation.get("db_write_blockers") or []
    if blockers:
        lines.append(f"- DB write engelleri: {', '.join(blockers)}")

    lines.extend(["", "## Needs Review", ""])
    review = validation.get("needs_review_records") or []
    if not review:
        lines.append("- needs_review kayıt yok.")
    else:
        for record in review[:50]:
            lines.append(
                f"- {record.get('program_name')} | {record.get('unit_name')} | "
                f"{record.get('education_level')} | {record.get('match_status')}"
            )

    lines.extend(["", "## Quality Issues", ""])
    if not report.quality_issues:
        lines.append("- Kalite issue yok.")
    else:
        for issue in report.quality_issues[:50]:
            lines.append(f"- [{issue.get('severity')}] {issue.get('issue_code')}: {issue.get('message')}")
    return "\n".join(lines) + "\n"


__all__ = [
    "ACADEMIC_UNITS_URL",
    "CANDIDATE_URL",
    "METADATA_VERSION",
    "ProgramCatalogReport",
    "ProgramCatalogScraper",
    "CatalogProgramRecord",
    "CatalogUnitRecord",
    "QualityIssue",
    "SCRAPER_NAME",
    "STATIC_PROGRAM_ALIASES",
    "STATIC_UNIT_ALIASES",
    "build_markdown_report",
    "canonical_url",
    "education_level_from_unit",
    "infer_unit_type",
    "normalize_for_match",
    "normalize_program_name",
]
