"""
GİBTÜ mühendislik bölümleri duyuru scraper'ı.

Bu modül sadece allowlist edilen BirimDuyuru.aspx kaynaklarını ve bu
sayfalardaki BirimIcerik.aspx detay linklerini işler. Haberler, duyuru arşivi
ve site geneli taranmaz.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.gibtu.edu.tr"
ALLOWED_HOST = "www.gibtu.edu.tr"
USER_AGENT = "Mozilla/5.0 (compatible; UniChatDepartmentAnnouncementBot/1.0)"
SCRAPER_NAME = "department_announcement_scraper"

DEFAULT_DEPARTMENT_ANNOUNCEMENT_SOURCES: tuple[dict[str, object], ...] = (
    {
        "unit_id": 18,
        "department_code": "bilgisayar_muhendisligi",
        "department_name": "Bilgisayar Mühendisliği",
        "source_url": f"{BASE_URL}/BirimDuyuru.aspx?id=18",
        "is_active": True,
    },
    {
        "unit_id": 16,
        "department_code": "elektrik_elektronik_muhendisligi",
        "department_name": "Elektrik-Elektronik Mühendisliği",
        "source_url": f"{BASE_URL}/BirimDuyuru.aspx?id=16",
        "is_active": True,
    },
    {
        "unit_id": 19,
        "department_code": "endustri_muhendisligi",
        "department_name": "Endüstri Mühendisliği",
        "source_url": f"{BASE_URL}/BirimDuyuru.aspx?id=19",
        "is_active": True,
    },
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepartmentAnnouncementSource:
    unit_id: int
    department_code: str
    department_name: str
    source_url: str
    source_id: str | None = None


@dataclass(frozen=True)
class ListedDepartmentAnnouncement:
    unit_id: int
    department_code: str
    department_name: str
    title: str
    list_date_text: str | None
    detail_url: str
    source_url: str


@dataclass
class ScrapedDepartmentAnnouncement:
    unit_id: int
    department_code: str
    department_name: str
    title: str
    announcement_date: date | None
    published_at: datetime | None
    detail_url: str
    content: str
    attachments: list[dict[str, str]]
    content_hash: str
    raw_data: dict[str, object] = field(default_factory=dict)

    def to_repository_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "department_code": self.department_code,
            "department_name": self.department_name,
            "title": self.title,
            "announcement_date": self.announcement_date.isoformat() if self.announcement_date else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "detail_url": self.detail_url,
            "content": self.content,
            "attachments": self.attachments,
            "content_hash": self.content_hash,
            "raw_data": self.raw_data,
        }


@dataclass
class DepartmentAnnouncementScrapeResult:
    success: bool
    announcements: list[ScrapedDepartmentAnnouncement] = field(default_factory=list)
    source_count: int = 0
    listing_count: int = 0
    detail_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def source_from_dict(value: dict[str, object]) -> DepartmentAnnouncementSource:
    source_id = value.get("id") or value.get("source_id")
    return DepartmentAnnouncementSource(
        unit_id=int(value["unit_id"]),
        department_code=str(value["department_code"]),
        department_name=str(value["department_name"]),
        source_url=str(value["source_url"]),
        source_id=str(source_id) if source_id else None,
    )


def parse_department_announcement_date(value: str | None) -> tuple[date | None, datetime | None]:
    """GİBTÜ tarih metnini date ve varsa datetime değerine çevirir."""
    if not value:
        return None, None

    cleaned = re.sub(r"\s+", " ", value.strip())
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.date(), parsed if "%H" in fmt else None
        except ValueError:
            continue
    return None, None


def _stable_hash(*parts: object) -> str:
    joined = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _clean_text_from_element(element) -> str:
    if element is None:
        return ""
    for unwanted in element.select("script, style, noscript"):
        unwanted.decompose()
    text = element.get_text(separator="\n", strip=True)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _is_allowed_gibtu_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == ALLOWED_HOST


def _query_unit_id(url: str) -> int | None:
    try:
        values = parse_qs(urlsplit(url).query).get("id") or []
        return int(values[0]) if values else None
    except (TypeError, ValueError):
        return None


class DepartmentAnnouncementScraper:
    """Allowlist tabanlı bölüm duyurusu scraper'ı."""

    MIN_CONTENT_LENGTH = 5

    def __init__(
        self,
        sources: list[DepartmentAnnouncementSource | dict[str, object]] | None = None,
        session: requests.Session | None = None,
        timeout_seconds: int = 20,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        raw_sources = sources or [dict(item) for item in DEFAULT_DEPARTMENT_ANNOUNCEMENT_SOURCES]
        self.sources = [
            item if isinstance(item, DepartmentAnnouncementSource) else source_from_dict(item)
            for item in raw_sources
        ]
        self._session = session
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT})
        return self._session

    @staticmethod
    def _apply_response_encoding(response) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        if "iso-8859-9" in content_type or urlsplit(getattr(response, "url", "")).netloc.lower() == ALLOWED_HOST:
            response.encoding = "iso-8859-9"
            return
        if not getattr(response, "encoding", None) or response.encoding.upper() == "ISO-8859-1":
            response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"

    def fetch_page(self, url: str) -> str:
        if not _is_allowed_gibtu_url(url):
            raise ValueError(f"İzin verilmeyen URL: {url}")

        session = self._get_session()
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
                response.raise_for_status()
                final_url = getattr(response, "url", url)
                if not _is_allowed_gibtu_url(final_url):
                    raise ValueError(f"İzin verilmeyen yönlendirme: {final_url}")
                self._apply_response_encoding(response)
                return response.text
            except Exception as exc:  # noqa: BLE001 - retry ve raporlama için geniş tutulur
                last_error = exc
                if attempt < 3:
                    time.sleep(self.retry_delay_seconds * attempt)
        raise RuntimeError(f"Sayfa alınamadı: {url} ({last_error})")

    def parse_listing_html(
        self,
        html: str,
        source: DepartmentAnnouncementSource,
    ) -> list[ListedDepartmentAnnouncement]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table.duyuru_listele")
        if table is None:
            return []

        listed: list[ListedDepartmentAnnouncement] = []
        seen_urls: set[str] = set()
        for row in table.select("tr"):
            link = row.select_one("a[href*='BirimIcerik.aspx']")
            if link is None:
                continue

            detail_url = urljoin(source.source_url, link.get("href", ""))
            if not self._is_allowed_detail_url(detail_url, source.unit_id):
                continue
            if detail_url in seen_urls:
                continue

            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            title = link.get_text(" ", strip=True) or (cells[0] if cells else "")
            list_date_text = cells[1] if len(cells) > 1 else None
            if not title:
                continue

            seen_urls.add(detail_url)
            listed.append(
                ListedDepartmentAnnouncement(
                    unit_id=source.unit_id,
                    department_code=source.department_code,
                    department_name=source.department_name,
                    title=title,
                    list_date_text=list_date_text,
                    detail_url=detail_url,
                    source_url=source.source_url,
                )
            )
        return listed

    def parse_detail_html(
        self,
        html: str,
        listed: ListedDepartmentAnnouncement,
    ) -> ScrapedDepartmentAnnouncement:
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.select_one(".icerik_baslik") or soup.select_one("span[id$='lbl_baslik']")
        detail_el = soup.select_one(".icerik_detay")
        date_el = soup.select_one(".icerik_tarih span[id$='lbl_tarih']") or soup.select_one("span[id$='lbl_tarih']")

        title = (title_el.get_text(" ", strip=True) if title_el else "") or listed.title
        detail_date_text = date_el.get_text(" ", strip=True) if date_el else None
        announcement_date, published_at = parse_department_announcement_date(detail_date_text or listed.list_date_text)
        content = _clean_text_from_element(detail_el)
        attachments = self._extract_attachments(detail_el, listed.detail_url)

        content_hash = _stable_hash(
            listed.detail_url,
            title,
            announcement_date.isoformat() if announcement_date else "",
            content,
            attachments,
        )

        return ScrapedDepartmentAnnouncement(
            unit_id=listed.unit_id,
            department_code=listed.department_code,
            department_name=listed.department_name,
            title=title,
            announcement_date=announcement_date,
            published_at=published_at,
            detail_url=listed.detail_url,
            content=content,
            attachments=attachments,
            content_hash=content_hash,
            raw_data={
                "list_title": listed.title,
                "list_date_text": listed.list_date_text,
                "detail_date_text": detail_date_text,
                "source_url": listed.source_url,
            },
        )

    def scrape(self) -> DepartmentAnnouncementScrapeResult:
        started = time.time()
        result = DepartmentAnnouncementScrapeResult(success=False, source_count=len(self.sources))

        for source in self.sources:
            try:
                if not self._is_allowed_source_url(source.source_url, source.unit_id):
                    raise ValueError(f"İzin verilmeyen kaynak URL: {source.source_url}")

                listing_html = self.fetch_page(source.source_url)
                listed_items = self.parse_listing_html(listing_html, source)
                result.listing_count += len(listed_items)

                for listed in listed_items:
                    try:
                        detail_html = self.fetch_page(listed.detail_url)
                        announcement = self.parse_detail_html(detail_html, listed)
                        result.announcements.append(announcement)
                        result.detail_count += 1
                    except Exception as exc:  # noqa: BLE001
                        result.error_count += 1
                        result.errors.append(f"{listed.detail_url}: {exc}")
                        logger.warning("Duyuru detay scrape hatası: %s", exc)
            except Exception as exc:  # noqa: BLE001
                result.error_count += 1
                result.errors.append(f"{source.source_url}: {exc}")
                logger.warning("Duyuru kaynak scrape hatası: %s", exc)

        result.duration_seconds = round(time.time() - started, 2)
        result.success = bool(result.announcements) and result.error_count == 0
        return result

    @staticmethod
    def _is_allowed_source_url(url: str, unit_id: int) -> bool:
        parsed = urlsplit(url)
        if not _is_allowed_gibtu_url(url):
            return False
        return parsed.path.lower().endswith("/birimduyuru.aspx") and _query_unit_id(url) == unit_id

    @staticmethod
    def _is_allowed_detail_url(url: str, unit_id: int) -> bool:
        parsed = urlsplit(url)
        if not _is_allowed_gibtu_url(url):
            return False
        query = parse_qs(parsed.query)
        return (
            parsed.path.lower().endswith("/birimicerik.aspx")
            and _query_unit_id(url) == unit_id
            and bool(query.get("icid"))
        )

    @staticmethod
    def _extract_attachments(detail_el, base_url: str) -> list[dict[str, str]]:
        if detail_el is None:
            return []

        attachments: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in detail_el.select("a[href]"):
            href = urljoin(base_url, link.get("href", ""))
            if not _is_allowed_gibtu_url(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            path = urlsplit(href).path
            extension = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
            attachments.append(
                {
                    "text": link.get_text(" ", strip=True),
                    "url": href,
                    "file_extension": extension,
                }
            )
        return attachments


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
