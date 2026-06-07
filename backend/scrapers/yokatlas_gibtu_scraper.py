"""
GİBTÜ YÖK Atlas yapılandırılmış veri scraper'ı.

Bu modül YÖK Atlas güncel tercih kılavuzu API'sinden yalnızca kullanıcı
tarafından baz alınan GİBTÜ program listesini çeker, ham JSON snapshot saklar,
normalizasyon yapar ve kalite/uyum validasyonu raporu üretir.

Güvenlik notu: CAPTCHA, anti-bot veya erişim engeli bypass edilmez. 403 gibi
kalıcı erişim hatalarında çalışma durdurulur ve rapora hata olarak yazılır.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - testlerde fake client kullanılabilir
    requests = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

BASE_URL = "https://yokatlas.yok.gov.tr"
API_BASE_URL = f"{BASE_URL}/api"
SEARCH_PATH = "/tercih-kilavuz/search"
UNIVERSITIES_PATH = "/tercih-kilavuz/universiteler"

SCRAPER_NAME = "yokatlas_gibtu_scraper"
METADATA_VERSION = "yokatlas.gibtu.v1"
UNIVERSITY_NAME = "GAZİANTEP İSLAM BİLİM VE TEKNOLOJİ ÜNİVERSİTESİ"
EXPECTED_UNIVERSITY_ID = 384577

LEVEL_LISANS = "lisans"
LEVEL_ONLISANS = "onlisans"
BIRIM_TURU_ID_BY_LEVEL = {
    LEVEL_LISANS: 46,
    LEVEL_ONLISANS: 47,
}
LEVEL_BY_BIRIM_TURU_ID = {
    46: LEVEL_LISANS,
    47: LEVEL_ONLISANS,
}

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRIES = 3
DEFAULT_RATE_LIMIT_SECONDS = 1.0
DEFAULT_PAGE_SIZE = 100

YOKATLAS_USER_AGENT = (
    "Mozilla/5.0 (compatible; UniChatYOKAtlasScraper/1.0; "
    "+https://github.com/unichat-project; educational-data-quality)"
)

NET_FIELDS = (
    "tytTrkNet",
    "tytSosNet",
    "tytMatNet",
    "tytFenNet",
    "aytMatNet",
    "aytFizNet",
    "aytKimNet",
    "aytBioNet",
    "aytTdeNet",
    "aytTrh1Net",
    "aytCog1Net",
    "aytTrh2Net",
    "aytCog2Net",
    "aytFelNet",
    "aytDinNet",
    "ydtYdilNet",
)

QUOTA_FIELDS = {
    "general": ("kontenjan", "gkY"),
    "school_first": ("kontenjanObs", "obkY"),
    "earthquake": ("kontenjanDep", "dprmY"),
    "women_34_plus": ("kontenjanY34", "y34Y"),
    "martyr_veteran": ("kontenjanSgy", "sgyY"),
}


@dataclass(frozen=True)
class ProgramAllowlistEntry:
    academic_unit: str
    program_name: str
    level: str

    @property
    def birim_turu_id(self) -> int:
        return BIRIM_TURU_ID_BY_LEVEL[self.level]

    @property
    def key(self) -> tuple[str, str, int]:
        return (
            normalize_for_match(self.academic_unit),
            normalize_for_match(self.program_name),
            self.birim_turu_id,
        )


PROGRAM_ALLOWLIST: tuple[ProgramAllowlistEntry, ...] = (
    ProgramAllowlistEntry("Tıp Fakültesi", "Tıp", LEVEL_LISANS),
    ProgramAllowlistEntry("Mühendislik ve Doğa Bilimleri Fakültesi", "Bilgisayar Mühendisliği", LEVEL_LISANS),
    ProgramAllowlistEntry("Mühendislik ve Doğa Bilimleri Fakültesi", "Elektrik-Elektronik Mühendisliği", LEVEL_LISANS),
    ProgramAllowlistEntry("Mühendislik ve Doğa Bilimleri Fakültesi", "Endüstri Mühendisliği (İngilizce)", LEVEL_LISANS),
    ProgramAllowlistEntry("Sağlık Bilimleri Fakültesi", "Ebelik", LEVEL_LISANS),
    ProgramAllowlistEntry("Sağlık Bilimleri Fakültesi", "Fizyoterapi ve Rehabilitasyon", LEVEL_LISANS),
    ProgramAllowlistEntry("Sağlık Bilimleri Fakültesi", "Hemşirelik", LEVEL_LISANS),
    ProgramAllowlistEntry("Güzel Sanatlar Tasarım ve Mimarlık Fakültesi", "Gastronomi ve Mutfak Sanatları", LEVEL_LISANS),
    ProgramAllowlistEntry("İlahiyat Fakültesi", "İlahiyat", LEVEL_LISANS),
    ProgramAllowlistEntry("İlahiyat Fakültesi", "İlahiyat (M.T.O.K.)", LEVEL_LISANS),
    ProgramAllowlistEntry("İlahiyat Fakültesi", "İlahiyat (Arapça)", LEVEL_LISANS),
    ProgramAllowlistEntry("İlahiyat Fakültesi", "İlahiyat (Arapça) (M.T.O.K.)", LEVEL_LISANS),
    ProgramAllowlistEntry("İktisadi, İdari ve Sosyal Bilimler Fakültesi", "Arapça Mütercim ve Tercümanlık", LEVEL_LISANS),
    ProgramAllowlistEntry("İktisadi, İdari ve Sosyal Bilimler Fakültesi", "İngilizce Mütercim ve Tercümanlık", LEVEL_LISANS),
    ProgramAllowlistEntry("Sağlık Hizmetleri Meslek Yüksekokulu", "Ameliyathane Hizmetleri", LEVEL_ONLISANS),
    ProgramAllowlistEntry("Sağlık Hizmetleri Meslek Yüksekokulu", "Tıbbi Laboratuvar Teknikleri", LEVEL_ONLISANS),
    ProgramAllowlistEntry("Sağlık Hizmetleri Meslek Yüksekokulu", "İlk ve Acil Yardım", LEVEL_ONLISANS),
    ProgramAllowlistEntry("Teknik Bilimler Meslek Yüksekokulu", "Bilgisayar Programcılığı", LEVEL_ONLISANS),
    ProgramAllowlistEntry("Teknik Bilimler Meslek Yüksekokulu", "Makine", LEVEL_ONLISANS),
)


@dataclass
class SnapshotRecord:
    snapshot_id: str
    snapshot_type: str
    source_url: str
    method: str
    request_body: dict[str, Any] | None
    response_hash: str
    fetched_at: str
    path: str | None = None
    response_payload: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_type": self.snapshot_type,
            "source_url": self.source_url,
            "method": self.method,
            "request_body": self.request_body,
            "response_hash": self.response_hash,
            "fetched_at": self.fetched_at,
            "path": self.path,
            "response_payload": self.response_payload,
        }


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    program_key: str | None = None
    program_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "program_key": self.program_key,
            "program_code": self.program_code,
        }


@dataclass
class YokatlasScrapeReport:
    success: bool
    run_id: str
    started_at: str
    finished_at: str = ""
    dry_run: bool = False
    university_id: int | None = None
    data_year: int | None = None
    expected_program_count: int = len(PROGRAM_ALLOWLIST)
    allowlist_limit: int | None = None
    rate_limit_seconds: float | None = None
    catalog_counts: dict[str, int] = field(default_factory=dict)
    matched_program_count: int = 0
    normalized_program_count: int = 0
    snapshot_count: int = 0
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    programs: list[dict[str, Any]] = field(default_factory=list)
    missing_programs: list[dict[str, Any]] = field(default_factory=list)
    unexpected_programs: list[dict[str, Any]] = field(default_factory=list)
    manual_check_samples: list[dict[str, Any]] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dry_run": self.dry_run,
            "scraper_name": SCRAPER_NAME,
            "metadata_version": METADATA_VERSION,
            "university_id": self.university_id,
            "university_name": UNIVERSITY_NAME,
            "data_year": self.data_year,
            "expected_program_count": self.expected_program_count,
            "allowlist_limit": self.allowlist_limit,
            "rate_limit_seconds": self.rate_limit_seconds,
            "catalog_counts": self.catalog_counts,
            "matched_program_count": self.matched_program_count,
            "normalized_program_count": self.normalized_program_count,
            "snapshot_count": self.snapshot_count,
            "snapshots": self.snapshots,
            "programs": self.programs,
            "missing_programs": self.missing_programs,
            "unexpected_programs": self.unexpected_programs,
            "manual_check_samples": self.manual_check_samples,
            "validation_results": self.validation_results,
            "errors": self.errors,
        }


class YokatlasHttpError(RuntimeError):
    """YÖK Atlas HTTP isteği kalıcı veya geçici olarak başarısız olduğunda atılır."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_for_match(value: str | None) -> str:
    """Türkçe karakterleri bozmadan karşılaştırma anahtarı üretir."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text or text in {"---", "-", "0", "Dolmadı", "Yeni açıldı"}:
        return None
    text = text.replace(".", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _to_decimal(value: Any) -> str | None:
    """Decimal değerleri JSON uyumlu ve hassas string olarak döndürür."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        if Decimal(str(value)) == 0:
            return None
        return str(Decimal(str(value)).normalize())

    text = str(value).strip()
    if not text or text in {"---", "-", "0", "Dolmadı", "Yeni açıldı"}:
        return None
    text = text.replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        decimal_value = Decimal(text)
    except InvalidOperation:
        return None
    if decimal_value == 0:
        return None
    return str(decimal_value.normalize())


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
    return None


def _program_key_from_row(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        normalize_for_match(row.get("fymkAdi")),
        normalize_for_match(row.get("birimAdi")),
        int(row.get("birimTuruId") or 0),
    )


def _program_key_label(row: dict[str, Any]) -> str:
    return f"{row.get('fymkAdi', '')} / {row.get('birimAdi', '')} / {row.get('birimTuruId', '')}"


def _source_detail_url(kilavuz_kodu: int | None) -> str:
    if not kilavuz_kodu:
        return f"{BASE_URL}/detay/"
    return f"{BASE_URL}/detay/{kilavuz_kodu}"


def select_allowlist(limit: int | None = None) -> tuple[ProgramAllowlistEntry, ...]:
    """Smoke test için allowlist'i lisans/önlisans dengesini koruyarak daraltır."""
    if limit is None or limit >= len(PROGRAM_ALLOWLIST):
        return PROGRAM_ALLOWLIST
    if limit <= 0:
        raise ValueError("limit pozitif bir sayı olmalıdır.")
    if limit == 1:
        return PROGRAM_ALLOWLIST[:1]

    lisans = [entry for entry in PROGRAM_ALLOWLIST if entry.level == LEVEL_LISANS]
    onlisans = [entry for entry in PROGRAM_ALLOWLIST if entry.level == LEVEL_ONLISANS]
    selected: list[ProgramAllowlistEntry] = []
    selected.extend(lisans[:1])
    selected.extend(onlisans[:1])
    remaining = [
        entry for entry in PROGRAM_ALLOWLIST
        if entry not in selected
    ]
    selected.extend(remaining[: max(0, limit - len(selected))])
    return tuple(selected[:limit])


def build_manual_check_samples(programs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Final manuel kontrol listesi için temsilî program özetleri üretir."""
    sample_names = {
        "Tıp",
        "Endüstri Mühendisliği (İngilizce)",
        "İlahiyat (Arapça) (M.T.O.K.)",
        "İlk ve Acil Yardım",
        "Makine",
    }
    samples: list[dict[str, Any]] = []
    for program in programs:
        program_info = program.get("program", {})
        raw_name = program_info.get("program_name_raw")
        if raw_name not in sample_names:
            continue
        academic_unit = program.get("academic_unit", {})
        year = program.get("program_year", {})
        education = program.get("education", {})
        quota = program.get("quota_statistics", {}).get("general", {})
        admission = program.get("admission_statistics", {})
        samples.append({
            "academic_unit": academic_unit.get("name"),
            "program_name": raw_name,
            "program_code": program_info.get("program_code"),
            "program_level": program_info.get("level"),
            "data_year": year.get("data_year"),
            "score_type": education.get("score_type"),
            "language": education.get("language"),
            "general_quota": quota.get("quota"),
            "general_placed": quota.get("placed"),
            "base_score": admission.get("base_score"),
            "base_rank": admission.get("base_rank"),
            "condition_count": len(program.get("conditions") or []),
            "source_url": year.get("source_url"),
        })
    return samples


class YokatlasHttpClient:
    """YÖK Atlas API için kontrollü HTTP istemcisi."""

    def __init__(
        self,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
        session: Any | None = None,
    ) -> None:
        if requests is None and session is None:
            raise RuntimeError("requests paketi yok; YÖK Atlas HTTP istemcisi başlatılamadı.")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_seconds = rate_limit_seconds
        self.session = session or requests.Session()  # type: ignore[union-attr]
        self._last_request_at = 0.0
        if hasattr(self.session, "headers"):
            self.session.headers.update({
                "User-Agent": YOKATLAS_USER_AGENT,
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            })

    def get_json(self, path: str) -> Any:
        return self._request_json("GET", self._url(path), None)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request_json("POST", self._url(path), payload)

    @staticmethod
    def _url(path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{API_BASE_URL}{path}"
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "yokatlas.yok.gov.tr":
            raise ValueError(f"YÖK Atlas kapsamı dışında URL reddedildi: {url}")
        return url

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                logger.info("YÖK Atlas %s isteği (%d/%d): %s", method, attempt, self.max_retries, url)
                if method == "GET":
                    response = self.session.get(url, timeout=self.timeout_seconds)
                else:
                    response = self.session.post(url, json=payload, timeout=self.timeout_seconds)
                self._last_request_at = time.time()

                status_code = int(getattr(response, "status_code", 200))
                if status_code >= 500 or status_code in {408, 429}:
                    raise YokatlasHttpError(f"Geçici HTTP hatası {status_code}: {url}")
                if 400 <= status_code < 500:
                    raise YokatlasHttpError(f"Kalıcı HTTP hatası {status_code}: {url}")

                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                return response.json()
            except YokatlasHttpError as exc:
                last_error = exc
                if "Kalıcı HTTP" in str(exc):
                    raise
            except Exception as exc:  # noqa: BLE001 - retry raporu için
                last_error = exc

            if attempt < self.max_retries:
                time.sleep(min(30.0, 2.0 * attempt))

        raise YokatlasHttpError(f"YÖK Atlas isteği başarısız: {url} ({last_error})")

    def _rate_limit(self) -> None:
        if not self._last_request_at:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)


class RawSnapshotStore:
    """Ham API yanıtlarını UTF-8 JSON snapshot olarak saklar."""

    def __init__(self, output_dir: str | Path | None, run_id: str) -> None:
        self.output_dir = Path(output_dir) if output_dir else None
        self.run_id = run_id
        self.records: list[SnapshotRecord] = []

    def store_json(
        self,
        snapshot_type: str,
        source_url: str,
        method: str,
        request_body: dict[str, Any] | None,
        response_payload: Any,
        fetched_at: str | None = None,
    ) -> SnapshotRecord:
        fetched_at = fetched_at or utc_now_iso()
        response_json = _stable_json(response_payload)
        request_json = _stable_json(request_body or {})
        response_hash = _sha256_text(response_json)
        snapshot_id = _sha256_text(f"{method}:{source_url}:{request_json}:{response_hash}")[:24]

        path: str | None = None
        if self.output_dir:
            snapshot_dir = self.output_dir / "snapshots" / self.run_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{snapshot_type}_{snapshot_id}.json"
            snapshot_path = snapshot_dir / file_name
            payload = {
                "snapshot_id": snapshot_id,
                "snapshot_type": snapshot_type,
                "source_url": source_url,
                "method": method,
                "request_body": request_body,
                "response_hash": response_hash,
                "fetched_at": fetched_at,
                "response_payload": response_payload,
            }
            snapshot_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            path = str(snapshot_path)

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            source_url=source_url,
            method=method,
            request_body=request_body,
            response_hash=response_hash,
            fetched_at=fetched_at,
            path=path,
            response_payload=response_payload,
        )
        self.records.append(record)
        return record


class UniversityResolver:
    def __init__(self, client: Any, snapshot_store: RawSnapshotStore) -> None:
        self.client = client
        self.snapshot_store = snapshot_store

    def resolve(self, expected_name: str = UNIVERSITY_NAME) -> tuple[int | None, SnapshotRecord]:
        response_payload = self.client.get_json(UNIVERSITIES_PATH)
        snapshot = self.snapshot_store.store_json(
            snapshot_type="universities",
            source_url=f"{API_BASE_URL}{UNIVERSITIES_PATH}",
            method="GET",
            request_body=None,
            response_payload=response_payload,
        )

        for item in response_payload or []:
            if normalize_for_match(item.get("universiteAdi")) == normalize_for_match(expected_name):
                return _to_int(item.get("universiteId")), snapshot
        return None, snapshot


class ProgramCatalogCrawler:
    def __init__(self, client: Any, snapshot_store: RawSnapshotStore) -> None:
        self.client = client
        self.snapshot_store = snapshot_store

    def crawl(self, university_id: int, level: str) -> tuple[list[dict[str, Any]], dict[str, Any], SnapshotRecord]:
        birim_turu_id = BIRIM_TURU_ID_BY_LEVEL[level]
        payload = {
            "filters": {
                "universiteId": [university_id],
                "birimTuruId": birim_turu_id,
            },
            "page": 0,
            "size": DEFAULT_PAGE_SIZE,
            "sortBy": "programKodu",
            "sortDirection": "ASC",
        }
        response_payload = self.client.post_json(SEARCH_PATH, payload)
        snapshot = self.snapshot_store.store_json(
            snapshot_type=f"catalog_{level}",
            source_url=f"{API_BASE_URL}{SEARCH_PATH}",
            method="POST",
            request_body=payload,
            response_payload=response_payload,
        )
        content = list(response_payload.get("content") or [])
        return content, response_payload, snapshot


class ProgramDetailCrawler:
    def __init__(self, client: Any, snapshot_store: RawSnapshotStore) -> None:
        self.client = client
        self.snapshot_store = snapshot_store

    def crawl(self, kilavuz_kodu: int) -> tuple[dict[str, Any] | None, dict[str, Any], SnapshotRecord]:
        payload = {
            "filters": {
                "kilavuzKodu": kilavuz_kodu,
            },
            "page": 0,
            "size": 10,
            "sortBy": "programKodu",
            "sortDirection": "ASC",
        }
        response_payload = self.client.post_json(SEARCH_PATH, payload)
        snapshot = self.snapshot_store.store_json(
            snapshot_type=f"detail_{kilavuz_kodu}",
            source_url=f"{API_BASE_URL}{SEARCH_PATH}",
            method="POST",
            request_body=payload,
            response_payload=response_payload,
        )
        content = list(response_payload.get("content") or [])
        return (content[0] if content else None), response_payload, snapshot


@dataclass
class AllowlistValidationResult:
    matched_rows: list[dict[str, Any]]
    missing_entries: list[ProgramAllowlistEntry]
    unexpected_rows: list[dict[str, Any]]
    issues: list[ValidationIssue]


class ProgramAllowlistValidator:
    def __init__(self, allowlist: tuple[ProgramAllowlistEntry, ...] = PROGRAM_ALLOWLIST) -> None:
        self.allowlist = allowlist
        self.expected_by_key = {entry.key: entry for entry in allowlist}
        self.known_scope_keys = {entry.key for entry in PROGRAM_ALLOWLIST}

    def validate(self, catalog_rows: list[dict[str, Any]]) -> AllowlistValidationResult:
        rows_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
        unexpected_rows: list[dict[str, Any]] = []
        issues: list[ValidationIssue] = []

        for row in catalog_rows:
            key = _program_key_from_row(row)
            if key in self.expected_by_key:
                rows_by_key[key] = row
                expected = self.expected_by_key[key]
                expected_level = expected.level
                actual_level = LEVEL_BY_BIRIM_TURU_ID.get(int(row.get("birimTuruId") or 0), "bilinmiyor")
                if actual_level != expected_level:
                    issues.append(ValidationIssue(
                        severity="critical",
                        code="level_mismatch",
                        message=f"Program düzeyi beklenenle uyuşmuyor: beklenen={expected_level}, gelen={actual_level}",
                        program_key=_program_key_label(row),
                        program_code=_to_int(row.get("kilavuzKodu")),
                    ))
            elif key in self.known_scope_keys:
                continue
            else:
                unexpected_rows.append(row)
                issues.append(ValidationIssue(
                    severity="warning",
                    code="unexpected_program",
                    message="API'de baz listede olmayan GİBTÜ programı döndü.",
                    program_key=_program_key_label(row),
                    program_code=_to_int(row.get("kilavuzKodu")),
                ))

        missing_entries = [
            entry for entry in self.allowlist
            if entry.key not in rows_by_key
        ]
        for entry in missing_entries:
            issues.append(ValidationIssue(
                severity="critical",
                code="missing_allowlisted_program",
                message="Baz listedeki program API katalogunda bulunamadı.",
                program_key=f"{entry.academic_unit} / {entry.program_name} / {entry.birim_turu_id}",
            ))

        matched_rows = [
            rows_by_key[entry.key]
            for entry in self.allowlist
            if entry.key in rows_by_key
        ]
        return AllowlistValidationResult(
            matched_rows=matched_rows,
            missing_entries=missing_entries,
            unexpected_rows=unexpected_rows,
            issues=issues,
        )


class DataNormalizer:
    """YÖK Atlas raw JSON satırını izlenebilir normalize kayda dönüştürür."""

    LANGUAGE_HINTS = {"İngilizce", "Arapça", "Türkçe"}
    VARIANT_HINTS = {"M.T.O.K."}

    def normalize_program(
        self,
        row: dict[str, Any],
        catalog_snapshot_id: str | None,
        detail_snapshot_id: str | None,
    ) -> dict[str, Any]:
        program_name_raw = str(row.get("birimAdi") or "").strip()
        name_parts = self._split_program_name(program_name_raw, row)
        kilavuz_kodu = _to_int(row.get("kilavuzKodu"))
        birim_turu_id = _to_int(row.get("birimTuruId"))
        data_year = _to_int(row.get("yil"))
        base_score = _to_decimal(row.get("minPuan"))
        base_rank = _to_int(row.get("basariSirasi"))

        normalized = {
            "university": {
                "source_university_id": _to_int(row.get("universiteId")),
                "name": row.get("universiteAdi"),
                "type": row.get("universiteTuru"),
                "city": row.get("uniIlAdi") or row.get("ilAdi"),
                "city_code": _to_int(row.get("uniIlKodu") or row.get("ilKodu")),
            },
            "academic_unit": {
                "source_unit_id": _to_int(row.get("fymkId")),
                "name": row.get("fymkAdi"),
                "city": row.get("fymkIlAdi"),
                "district": row.get("fymkIlceAdi"),
            },
            "program": {
                "program_code": kilavuz_kodu,
                "program_name_raw": program_name_raw,
                "program_name_clean": name_parts["clean_name"],
                "program_language_from_name": name_parts["language_from_name"],
                "program_variant": name_parts["variant"],
                "source_program_id": _to_int(row.get("birimId")),
                "program_group_id": _to_int(row.get("birimGrupId")),
                "program_group_name": row.get("birimGrupAdi"),
                "level": LEVEL_BY_BIRIM_TURU_ID.get(birim_turu_id or 0),
                "source_level_id": birim_turu_id,
                "source_level_name": row.get("birimTuruAdi"),
                "duration_years": _to_int(row.get("ogrenimSuresi")),
                "is_active": True,
                "old_program_code": _to_int(row.get("eskiKilavuzKodu")),
                "old_program_id": _to_int(row.get("eskiBirimId")),
            },
            "program_year": {
                "data_year": data_year,
                "exam": str(row.get("sinav") or "").strip() or None,
                "term": str(row.get("donem") or "").strip() or None,
                "table_type": str(row.get("tabloTuru") or "").strip() or None,
                "source_url": _source_detail_url(kilavuz_kodu),
                "catalog_snapshot_id": catalog_snapshot_id,
                "detail_snapshot_id": detail_snapshot_id,
            },
            "education": {
                "score_type": row.get("puanTuru"),
                "education_mode_id": _to_int(row.get("ogrenimTuruId")),
                "education_mode": row.get("ogrenimTuruAdi"),
                "language_id": _to_int(row.get("ogrenimDiliId")),
                "language": row.get("ogrenimDiliAdi") or name_parts["language_from_name"],
                "funding_id": _to_int(row.get("bursOraniId")),
                "funding_type": row.get("bursOraniAdi") or self._funding_from_id(row.get("bursOraniId")),
                "tuition_fee": _to_decimal(row.get("ucret")),
            },
            "quota_statistics": self._normalize_quotas(row),
            "admission_statistics": {
                "base_score": base_score,
                "base_rank": base_rank,
                "last_admitted_score": base_score,
                "last_admitted_rank": base_rank,
                "min_rank_condition": _to_int(row.get("minBasariSirasi")),
                "min_rank_condition_text": row.get("minBasariSirasiKosul"),
                "fill_status": "filled" if base_score and base_rank else "not_filled_or_new",
            },
            "score_statistics": {
                "historical": self._normalize_historical_scores(row),
            },
            "last_admitted_nets": {
                "status": self._net_status(row),
                "fields": {field_name: _to_decimal(row.get(field_name)) for field_name in NET_FIELDS},
                "null_reason": "YÖK Atlas API yanıtında net alanları boş; ayrı panel/endpoint keşfi sırasında doğrulanmalı.",
            },
            "average_nets": {
                "status": "not_discovered",
                "fields": {},
                "null_reason": "Yerleşenlerin ortalama netleri için doğrulanmış endpoint/panel henüz yok.",
            },
            "conditions": self._normalize_conditions(row),
            "source": {
                "source_url": _source_detail_url(kilavuz_kodu),
                "catalog_snapshot_id": catalog_snapshot_id,
                "detail_snapshot_id": detail_snapshot_id,
                "scraper_name": SCRAPER_NAME,
                "metadata_version": METADATA_VERSION,
            },
        }
        return normalized

    def _split_program_name(self, program_name: str, row: dict[str, Any]) -> dict[str, str | None]:
        clean_name = program_name
        language_from_name: str | None = None
        variant: str | None = row.get("birimEkTuru")

        suffixes: list[str] = []
        while True:
            match = re.search(r"\(([^()]*)\)\s*$", clean_name)
            if not match:
                break
            suffixes.insert(0, match.group(1).strip())
            clean_name = clean_name[:match.start()].strip()

        for suffix in suffixes:
            if suffix in self.LANGUAGE_HINTS:
                language_from_name = suffix
            elif suffix in self.VARIANT_HINTS:
                variant = suffix
            elif "%30" in suffix or "İngilizce" in suffix or "Arapça" in suffix:
                language_from_name = suffix
            elif not variant:
                variant = suffix

        return {
            "clean_name": clean_name or program_name,
            "language_from_name": language_from_name,
            "variant": variant,
        }

    @staticmethod
    def _funding_from_id(value: Any) -> str | None:
        mapping = {
            0: "Ücretsiz",
            154: "Ücretli",
            155: "%25 İndirimli",
            156: "%50 İndirimli",
            158: "Burslu",
        }
        return mapping.get(_to_int(value) or 0)

    @staticmethod
    def _normalize_quotas(row: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for category, (quota_key, placed_key) in QUOTA_FIELDS.items():
            placed_value = row.get(placed_key)
            if category == "women_34_plus" and placed_value is None:
                placed_value = row.get("y34")
            result[category] = {
                "quota": _to_int(row.get(quota_key)) or 0,
                "placed": _to_int(placed_value) or 0,
            }
        result["total_quota_known"] = sum(item["quota"] for item in result.values() if isinstance(item, dict))
        result["total_placed_known"] = sum(item["placed"] for item in result.values() if isinstance(item, dict))
        return result

    @staticmethod
    def _normalize_historical_scores(row: dict[str, Any]) -> list[dict[str, Any]]:
        historical: list[dict[str, Any]] = []
        for offset in range(1, 6):
            has_any = any(key in row for key in (f"gk{offset}", f"minPuan{offset}", f"basariSirasi{offset}"))
            if not has_any:
                continue
            historical.append({
                "year_offset": offset,
                "general_quota": _to_int(row.get(f"gk{offset}")),
                "base_score": _to_decimal(row.get(f"minPuan{offset}")),
                "base_rank": _to_int(row.get(f"basariSirasi{offset}")),
            })
        return historical

    @staticmethod
    def _normalize_conditions(row: dict[str, Any]) -> list[dict[str, str]]:
        conditions: list[dict[str, str]] = []
        for item in row.get("kosulList") or []:
            if not isinstance(item, dict):
                continue
            for code, text in item.items():
                conditions.append({
                    "condition_code": str(code),
                    "condition_text": str(text).replace("\r\n", "\n").replace("\r", "\n").strip(),
                })
        return conditions

    @staticmethod
    def _net_status(row: dict[str, Any]) -> str:
        values = [_to_decimal(row.get(field_name)) for field_name in NET_FIELDS]
        return "available" if any(values) else "not_available"


class ValidationEngine:
    def validate(
        self,
        normalized_programs: list[dict[str, Any]],
        allowlist_result: AllowlistValidationResult,
        snapshots_by_program_code: dict[int, dict[str, str | None]],
    ) -> list[ValidationIssue]:
        issues = list(allowlist_result.issues)
        issues.extend(self._validate_program_codes(normalized_programs))
        issues.extend(self._validate_program_records(normalized_programs, snapshots_by_program_code))
        return issues

    @staticmethod
    def _validate_program_codes(normalized_programs: list[dict[str, Any]]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen: dict[tuple[int, int], dict[str, Any]] = {}
        for program in normalized_programs:
            code = program["program"].get("program_code")
            year = program["program_year"].get("data_year")
            if code is None or year is None:
                issues.append(ValidationIssue(
                    severity="critical",
                    code="missing_program_code_or_year",
                    message="Program kodu veya veri yılı boş.",
                    program_code=code,
                ))
                continue
            key = (int(code), int(year))
            if key in seen:
                issues.append(ValidationIssue(
                    severity="critical",
                    code="duplicate_program_code_year",
                    message=f"Aynı yıl içinde duplicate program kodu tespit edildi: {code}/{year}",
                    program_code=int(code),
                ))
            seen[key] = program
        return issues

    @staticmethod
    def _validate_program_records(
        normalized_programs: list[dict[str, Any]],
        snapshots_by_program_code: dict[int, dict[str, str | None]],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        expected_score_types = {"SAY", "SÖZ", "EA", "DİL", "TYT"}

        for program in normalized_programs:
            program_data = program["program"]
            year_data = program["program_year"]
            education = program["education"]
            admission = program["admission_statistics"]
            conditions = program["conditions"]
            code = program_data.get("program_code")
            label = f"{program['academic_unit'].get('name')} / {program_data.get('program_name_raw')}"

            snapshot_info = snapshots_by_program_code.get(int(code or 0), {})
            if not snapshot_info.get("catalog_snapshot_id") or not snapshot_info.get("detail_snapshot_id"):
                issues.append(ValidationIssue(
                    severity="critical",
                    code="missing_raw_snapshot",
                    message="Programın katalog veya detay ham snapshot kaydı eksik.",
                    program_key=label,
                    program_code=code,
                ))

            if not year_data.get("source_url"):
                issues.append(ValidationIssue(
                    severity="critical",
                    code="missing_source_url",
                    message="Program yıl kaydında kaynak URL boş.",
                    program_key=label,
                    program_code=code,
                ))

            if year_data.get("data_year") is None:
                issues.append(ValidationIssue(
                    severity="critical",
                    code="missing_data_year",
                    message="Veri yılı boş.",
                    program_key=label,
                    program_code=code,
                ))

            score_type = education.get("score_type")
            if score_type not in expected_score_types:
                issues.append(ValidationIssue(
                    severity="warning",
                    code="unexpected_score_type",
                    message=f"Puan türü beklenen sözlükte yok: {score_type}",
                    program_key=label,
                    program_code=code,
                ))

            if admission.get("fill_status") == "not_filled_or_new":
                issues.append(ValidationIssue(
                    severity="info",
                    code="missing_base_score_or_rank",
                    message="Program yeni açılmış/dolmamış olabilir; taban puan veya başarı sırası boş.",
                    program_key=label,
                    program_code=code,
                ))

            condition_codes_raw = program.get("_raw_condition_codes")
            if condition_codes_raw and not conditions:
                issues.append(ValidationIssue(
                    severity="warning",
                    code="condition_text_missing",
                    message="Koşul kodu var ama koşul açıklaması parse edilemedi.",
                    program_key=label,
                    program_code=code,
                ))

            if program["last_admitted_nets"].get("status") == "not_available":
                issues.append(ValidationIssue(
                    severity="warning",
                    code="nets_not_available",
                    message="Son yerleşen netleri/ortalama netler API yanıtında yok; panel keşfi sırasında doğrulanmalı.",
                    program_key=label,
                    program_code=code,
                ))

        return issues


class YokatlasGibtuScraper:
    """GİBTÜ baz program allowlist'i için uçtan uca YÖK Atlas pipeline."""

    def __init__(
        self,
        client: Any | None = None,
        output_dir: str | Path | None = None,
        allowlist: tuple[ProgramAllowlistEntry, ...] = PROGRAM_ALLOWLIST,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    ) -> None:
        self.client = client or YokatlasHttpClient(rate_limit_seconds=rate_limit_seconds)
        self.output_dir = Path(output_dir) if output_dir else None
        self.allowlist = allowlist
        self.rate_limit_seconds = rate_limit_seconds

    def scrape(
        self,
        report_json: str | Path | None = None,
        fetch_details: bool = True,
        dry_run: bool = True,
        allowlist_limit: int | None = None,
    ) -> YokatlasScrapeReport:
        started_at = utc_now_iso()
        run_id = f"{SCRAPER_NAME}:{started_at}"
        snapshot_store = RawSnapshotStore(self.output_dir, run_id=_sha256_text(run_id)[:16])
        report = YokatlasScrapeReport(success=False, run_id=run_id, started_at=started_at)
        report.dry_run = dry_run
        report.expected_program_count = len(self.allowlist)
        report.allowlist_limit = allowlist_limit
        report.rate_limit_seconds = self.rate_limit_seconds

        try:
            university_id, _university_snapshot = UniversityResolver(self.client, snapshot_store).resolve()
            report.university_id = university_id
            if university_id != EXPECTED_UNIVERSITY_ID:
                report.errors.append(
                    f"Üniversite kimliği beklenenle uyuşmuyor: beklenen={EXPECTED_UNIVERSITY_ID}, gelen={university_id}"
                )
                self._finish_report(report, snapshot_store, report_json)
                return report

            catalog_crawler = ProgramCatalogCrawler(self.client, snapshot_store)
            all_catalog_rows: list[dict[str, Any]] = []
            catalog_snapshot_by_level: dict[str, str] = {}
            catalog_meta_by_level: dict[str, dict[str, Any]] = {}

            for level in (LEVEL_LISANS, LEVEL_ONLISANS):
                rows, meta, snapshot = catalog_crawler.crawl(university_id, level)
                all_catalog_rows.extend(rows)
                catalog_snapshot_by_level[level] = snapshot.snapshot_id
                catalog_meta_by_level[level] = meta
                report.catalog_counts[level] = len(rows)
                report.data_year = report.data_year or _to_int(meta.get("yil"))

            allowlist_result = ProgramAllowlistValidator(self.allowlist).validate(all_catalog_rows)
            matched_rows = allowlist_result.matched_rows
            report.matched_program_count = len(matched_rows)
            report.missing_programs = [
                {
                    "academic_unit": entry.academic_unit,
                    "program_name": entry.program_name,
                    "program_level": entry.level,
                    "source_level_id": entry.birim_turu_id,
                }
                for entry in allowlist_result.missing_entries
            ]
            report.unexpected_programs = [
                {
                    "academic_unit": row.get("fymkAdi"),
                    "program_name": row.get("birimAdi"),
                    "program_code": _to_int(row.get("kilavuzKodu")),
                    "program_level": LEVEL_BY_BIRIM_TURU_ID.get(_to_int(row.get("birimTuruId")) or 0),
                    "source_level_id": _to_int(row.get("birimTuruId")),
                }
                for row in allowlist_result.unexpected_rows
            ]

            normalizer = DataNormalizer()
            detail_crawler = ProgramDetailCrawler(self.client, snapshot_store)
            normalized_programs: list[dict[str, Any]] = []
            snapshots_by_program_code: dict[int, dict[str, str | None]] = {}

            for catalog_row in matched_rows:
                program_code = _to_int(catalog_row.get("kilavuzKodu"))
                if program_code is None:
                    continue
                level = LEVEL_BY_BIRIM_TURU_ID.get(int(catalog_row.get("birimTuruId") or 0), "")
                catalog_snapshot_id = catalog_snapshot_by_level.get(level)
                detail_row = catalog_row
                detail_snapshot_id: str | None = None

                if fetch_details:
                    fetched_detail_row, _detail_meta, detail_snapshot = detail_crawler.crawl(program_code)
                    detail_snapshot_id = detail_snapshot.snapshot_id
                    if fetched_detail_row:
                        detail_row = fetched_detail_row

                snapshots_by_program_code[program_code] = {
                    "catalog_snapshot_id": catalog_snapshot_id,
                    "detail_snapshot_id": detail_snapshot_id,
                }
                normalized = normalizer.normalize_program(
                    detail_row,
                    catalog_snapshot_id=catalog_snapshot_id,
                    detail_snapshot_id=detail_snapshot_id,
                )
                if detail_row.get("kosul"):
                    normalized["_raw_condition_codes"] = str(detail_row.get("kosul"))
                normalized_programs.append(normalized)

            issues = ValidationEngine().validate(
                normalized_programs,
                allowlist_result,
                snapshots_by_program_code,
            )
            report.programs = [
                {key: value for key, value in program.items() if key != "_raw_condition_codes"}
                for program in normalized_programs
            ]
            report.normalized_program_count = len(report.programs)
            report.manual_check_samples = build_manual_check_samples(report.programs)
            report.validation_results = [issue.to_dict() for issue in issues]
            report.success = not any(issue.severity == "critical" for issue in issues)
            return self._finish_report(report, snapshot_store, report_json)
        except Exception as exc:  # noqa: BLE001 - kullanıcı raporu için
            logger.exception("YÖK Atlas GİBTÜ scraper hatası")
            report.errors.append(str(exc))
            return self._finish_report(report, snapshot_store, report_json)

    @staticmethod
    def _finish_report(
        report: YokatlasScrapeReport,
        snapshot_store: RawSnapshotStore,
        report_json: str | Path | None,
    ) -> YokatlasScrapeReport:
        report.finished_at = utc_now_iso()
        report.snapshot_count = len(snapshot_store.records)
        report.snapshots = [record.to_dict() for record in snapshot_store.records]
        if report.errors:
            report.success = False
        if report_json:
            path = Path(report_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return report


__all__ = [
    "API_BASE_URL",
    "BASE_URL",
    "BIRIM_TURU_ID_BY_LEVEL",
    "EXPECTED_UNIVERSITY_ID",
    "LEVEL_LISANS",
    "LEVEL_ONLISANS",
    "METADATA_VERSION",
    "PROGRAM_ALLOWLIST",
    "ProgramAllowlistEntry",
    "ProgramAllowlistValidator",
    "RawSnapshotStore",
    "SCRAPER_NAME",
    "UNIVERSITY_NAME",
    "ValidationEngine",
    "ValidationIssue",
    "YokatlasGibtuScraper",
    "YokatlasHttpClient",
    "YokatlasHttpError",
    "YokatlasScrapeReport",
    "_to_decimal",
    "_to_int",
    "build_manual_check_samples",
    "normalize_for_match",
    "select_allowlist",
]
