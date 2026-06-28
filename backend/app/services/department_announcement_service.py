"""
Mühendislik bölüm duyuruları için DB-first servis katmanı.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any

from app.repositories.department_announcement_repository import (
    DepartmentAnnouncementRepository,
    REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES,
    classify_department_announcement_db_error,
)
from app.services.department_announcement_intent import (
    DepartmentAnnouncementQuery,
    extract_department_announcement_request,
    infer_department_announcement_tags,
    normalize_department_announcement_text,
)
from scrapers.department_announcement_scraper import (
    DEFAULT_DEPARTMENT_ANNOUNCEMENT_SOURCES,
    DepartmentAnnouncementScraper,
    ScrapedDepartmentAnnouncement,
)

logger = logging.getLogger(__name__)


class DepartmentAnnouncementService:
    """Scrape→staging→approval ve chat sorgu akışını yönetir."""

    def __init__(
        self,
        repository: DepartmentAnnouncementRepository | None = None,
        scraper_factory=None,
    ) -> None:
        self._repository = repository or DepartmentAnnouncementRepository()
        self._scraper_factory = scraper_factory or DepartmentAnnouncementScraper

    def scrape_to_staging(self) -> dict[str, Any]:
        """Aktif kaynakları scrape eder ve sadece staging tablosuna yazar."""
        scrape_run_id = self._new_run_id()
        sources = self._load_sources_for_scrape()
        self._repository.create_scrape_run(
            scrape_run_id,
            source_count=len(sources),
            config={
                "mode": "weekly_staging",
                "production_write": False,
                "source_unit_ids": [source["unit_id"] for source in sources],
            },
        )

        scraper = self._scraper_factory(sources=sources)
        scrape_result = scraper.scrape()

        staged_count = 0
        duplicate_count = 0
        valid_count = 0
        invalid_count = 0
        staged_rows: list[dict[str, Any]] = []

        for announcement in scrape_result.announcements:
            validation_issues = self._validate_announcement(announcement)
            validation_status = "valid" if not validation_issues else "invalid"
            if validation_status == "valid":
                valid_count += 1
            else:
                invalid_count += 1

            existing = self._repository.find_production_by_detail_url(announcement.detail_url)
            if existing and existing.get("content_hash") == announcement.content_hash:
                duplicate_count += 1
                continue

            intent_tags = infer_department_announcement_tags(
                f"{announcement.title}\n{announcement.content}"
            )
            search_text = self._search_text(announcement, intent_tags)
            source_id = next(
                (
                    str(source.get("id"))
                    for source in sources
                    if int(source["unit_id"]) == announcement.unit_id and source.get("id")
                ),
                None,
            )
            row = self._repository.stage_announcement(
                scrape_run_id=scrape_run_id,
                source_id=source_id,
                announcement=announcement.to_repository_dict(),
                validation_status=validation_status,
                validation_issues=validation_issues,
                search_text=search_text,
                intent_tags=intent_tags,
            )
            staged_rows.append(row)
            staged_count += 1

        status = "success" if scrape_result.error_count == 0 else "success_with_errors"
        if not scrape_result.announcements:
            status = "failed"
        validation_status = "valid" if invalid_count == 0 and scrape_result.error_count == 0 else "needs_review"
        run = self._repository.update_scrape_run(
            scrape_run_id,
            status=status,
            validation_status=validation_status,
            fetched_count=len(scrape_result.announcements),
            staged_count=staged_count,
            duplicate_count=duplicate_count,
            error_count=scrape_result.error_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            summary={
                "listing_count": scrape_result.listing_count,
                "detail_count": scrape_result.detail_count,
                "errors": scrape_result.errors[:20],
                "duration_seconds": scrape_result.duration_seconds,
            },
        )

        return {
            "success": status != "failed",
            "scrape_run_id": scrape_run_id,
            "run": run,
            "sources": len(sources),
            "fetched": len(scrape_result.announcements),
            "staged": staged_count,
            "duplicates": duplicate_count,
            "valid": valid_count,
            "invalid": invalid_count,
            "errors": scrape_result.errors,
            "staging": staged_rows,
        }

    def list_staging(
        self,
        *,
        status: str | None = None,
        scrape_run_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        rows = self._repository.list_staging(status=status, scrape_run_id=scrape_run_id, limit=limit)
        return {"count": len(rows), "items": rows}

    def approve_staging(
        self,
        staging_id: str,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        return self._repository.approve_staging(
            staging_id,
            reviewed_by=reviewed_by,
            review_note=review_note,
        )

    def reject_staging(
        self,
        staging_id: str,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        return self._repository.reject_staging(
            staging_id,
            reviewed_by=reviewed_by,
            review_note=review_note,
        )

    def approve_run(
        self,
        scrape_run_id: str,
        *,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        rows = self._repository.list_staging(
            status="pending",
            scrape_run_id=scrape_run_id,
            limit=1000,
        )
        approved = []
        skipped = []
        for row in rows:
            if row.get("validation_status") != "valid":
                skipped.append({"id": row.get("id"), "reason": "validation_not_valid"})
                continue
            try:
                approved.append(
                    self.approve_staging(
                        str(row["id"]),
                        reviewed_by=reviewed_by,
                        review_note=review_note,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - toplu onay raporu için
                skipped.append({"id": row.get("id"), "reason": str(exc)})
        return {
            "scrape_run_id": scrape_run_id,
            "approved_count": len(approved),
            "skipped_count": len(skipped),
            "approved": approved,
            "skipped": skipped,
        }

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        request = extract_department_announcement_request(question)
        if not request.is_announcement_query:
            return None

        try:
            records = self._repository.search_announcements(
                department_codes=request.department_codes or None,
                limit=150,
            )
        except Exception as exc:  # noqa: BLE001 - DB-first servis tahmini fallback üretmesin
            error_type = classify_department_announcement_db_error(exc)
            logger.warning("Bölüm duyuru DB sorgusu başarısız (%s): %s", error_type, exc)
            return self._db_unavailable_response(request, error_type)

        matches = self._rank_records(records, request)
        if not matches:
            return self._not_found_response(request)

        limit = 5 if request.is_latest_query else 3
        selected = [record for _, record in matches[:limit]]
        return {
            "response": self._format_chat_response(selected),
            "sources": [self._source_from_record(record) for record in selected],
            "metadata": {
                "service": "department_announcement_service",
                "intent": "latest_department_announcements" if request.is_latest_query else "department_announcement_query",
                "rag_fallback_used": False,
            },
        }

    def get_status(self) -> dict[str, Any]:
        try:
            status = self._repository.get_status()
        except Exception as exc:  # noqa: BLE001 - admin status hata detayını tipe indirger
            error_type = classify_department_announcement_db_error(exc)
            logger.warning("Bölüm duyuru status bilgisi okunamadı (%s): %s", error_type, exc)
            return {
                "schema_ready": False,
                "missing_tables": list(REQUIRED_DEPARTMENT_ANNOUNCEMENT_TABLES),
                "active_source_count": 0,
                "production_count": 0,
                "pending_staging_count": 0,
                "last_scrape_run": None,
                "data_state": "unavailable",
                "last_error_type": error_type,
            }

        production_count = int(status.get("production_count") or 0)
        pending_count = int(status.get("pending_staging_count") or 0)
        if not status.get("schema_ready"):
            data_state = "schema_missing"
            last_error_type = "schema_missing"
        elif production_count > 0:
            data_state = "ready"
            last_error_type = None
        elif pending_count > 0:
            data_state = "approval_pending"
            last_error_type = "no_approved_data"
        else:
            data_state = "no_approved_data"
            last_error_type = "no_approved_data"

        return {
            **status,
            "data_state": data_state,
            "last_error_type": last_error_type,
        }

    def _load_sources_for_scrape(self) -> list[dict[str, Any]]:
        sources = self._repository.get_active_sources()
        if sources:
            return sources
        return [dict(source) for source in DEFAULT_DEPARTMENT_ANNOUNCEMENT_SOURCES]

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"department_announcements_{stamp}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _validate_announcement(announcement: ScrapedDepartmentAnnouncement) -> list[str]:
        issues: list[str] = []
        if not announcement.title.strip():
            issues.append("missing_title")
        if not announcement.detail_url.strip():
            issues.append("missing_detail_url")
        if not announcement.announcement_date:
            issues.append("missing_or_unparsed_date")
        if len((announcement.content or "").strip()) < DepartmentAnnouncementScraper.MIN_CONTENT_LENGTH:
            issues.append("content_too_short")
        if not announcement.content_hash:
            issues.append("missing_content_hash")
        return issues

    @staticmethod
    def _search_text(announcement: ScrapedDepartmentAnnouncement, intent_tags: list[str]) -> str:
        value = " ".join(
            [
                announcement.department_name,
                announcement.title,
                announcement.content,
                " ".join(intent_tags),
            ]
        )
        return normalize_department_announcement_text(value)

    def _rank_records(
        self,
        records: list[dict[str, Any]],
        request: DepartmentAnnouncementQuery,
    ) -> list[tuple[int, dict[str, Any]]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for record in records:
            score = self._score_record(record, request)
            min_score = 35 if request.topic_tags else 20
            if score >= min_score:
                scored.append((score, record))
        if request.is_latest_query:
            return sorted(scored, key=lambda item: str(item[1].get("announcement_date") or ""), reverse=True)
        return sorted(scored, key=lambda item: (item[0], str(item[1].get("announcement_date") or "")), reverse=True)

    @staticmethod
    def _score_record(record: dict[str, Any], request: DepartmentAnnouncementQuery) -> int:
        score = 0
        department_code = str(record.get("department_code") or "")
        if request.department_codes:
            if department_code in request.department_codes:
                score += 35
            else:
                score -= 20

        record_tags = _record_intent_tags(record)
        requested_tags = set(request.topic_tags or [])
        if requested_tags:
            overlap = record_tags & requested_tags
            if not overlap:
                return -1000
            score += len(overlap) * 55

        title_norm = normalize_department_announcement_text(str(record.get("title") or ""))
        content_norm = normalize_department_announcement_text(str(record.get("content") or ""))
        search_norm = str(record.get("search_text") or "")
        for term in request.query_terms:
            if term in title_norm:
                score += 8
            elif term in search_norm:
                score += 4
            elif term in content_norm:
                score += 2

        if request.has_announcement_signal:
            score += 8
        if request.is_latest_query:
            score += 8
        if record.get("announcement_date"):
            score += 2
        return score

    @staticmethod
    def _not_found_response(request: DepartmentAnnouncementQuery) -> dict[str, Any]:
        department_text = _department_scope_text(request.department_codes)
        topic_text = _topic_scope_text(request.topic_tags)
        if request.is_latest_query and request.department_codes:
            response = (
                f"{department_text} için onaylı bölüm duyurusu kaydı bulunamadı. "
                "Yalnızca production'a onaylanmış duyuru kayıtları yanıtlanır; tahmini RAG cevabı üretilmedi."
            )
        else:
            response = (
                f"{department_text}{topic_text} için onaylı bölüm duyurusu bulunamadı. "
                "Duyuru staging'de bekliyor veya henüz production'a onaylanmamış olabilir. "
                "Tahmini RAG cevabı üretilmedi."
            )
        return {
            "response": response,
            "sources": [],
            "metadata": {
                "service": "department_announcement_service",
                "intent": "department_announcement_not_found",
                "rag_fallback_used": False,
            },
        }

    @staticmethod
    def _db_unavailable_response(
        request: DepartmentAnnouncementQuery,
        error_type: str = "query_failed",
    ) -> dict[str, Any]:
        if error_type == "schema_missing":
            message = (
                f"{_department_scope_text(request.department_codes)} duyuru veritabanı şeması henüz hazır değil. "
                "Bu konu için tahmini RAG cevabı üretilmedi; lütfen sistem yöneticisinin duyuru tablolarını doğrulamasını bekleyin."
            )
        elif error_type == "db_connection_error":
            message = (
                f"{_department_scope_text(request.department_codes)} duyuru veritabanına şu anda bağlanılamıyor. "
                "Bu konu için tahmini RAG cevabı üretilmedi; lütfen daha sonra tekrar deneyin."
            )
        else:
            message = (
                f"{_department_scope_text(request.department_codes)} duyuru veritabanı şu anda okunamadı. "
                "Bu konu için tahmini RAG cevabı üretilmedi; lütfen daha sonra tekrar deneyin."
            )
        return {
            "response": message,
            "sources": [],
            "metadata": {
                "service": "department_announcement_service",
                "intent": error_type,
                "error_type": error_type,
                "rag_fallback_used": False,
            },
        }

    @staticmethod
    def _format_chat_response(records: list[dict[str, Any]]) -> str:
        if len(records) == 1:
            record = records[0]
            date_text = _display_date(record.get("announcement_date"))
            snippet = _snippet(str(record.get("content") or ""))
            return (
                f"{record.get('department_name')} duyurularında ilgili kayıt bulundu:\n\n"
                f"**{record.get('title')}**"
                f"{f' ({date_text})' if date_text else ''}\n\n"
                f"{snippet}\n\n"
                f"Kaynak: {record.get('detail_url')}"
            ).strip()

        lines = ["İlgili bölüm duyuruları:"]
        for record in records:
            date_text = _display_date(record.get("announcement_date"))
            date_part = f" — {date_text}" if date_text else ""
            lines.append(
                f"- **{record.get('title')}** ({record.get('department_name')}){date_part}\n"
                f"  Kaynak: {record.get('detail_url')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _source_from_record(record: dict[str, Any]) -> dict[str, Any]:
        content = str(record.get("content") or "")
        return {
            "content": content[:200] + "..." if len(content) > 200 else content,
            "source_url": record.get("detail_url"),
            "source_public_url": record.get("detail_url"),
            "category": "duyurular",
            "title": record.get("title"),
            "doc_kind": "department_announcement",
        }


def _display_date(value: Any) -> str:
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    months = {
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
    return f"{parsed.day} {months[parsed.month]} {parsed.year}"


def _snippet(content: str, max_chars: int = 600) -> str:
    cleaned = " ".join(line.strip() for line in content.splitlines() if line.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


DEPARTMENT_DISPLAY_NAMES = {
    "bilgisayar_muhendisligi": "Bilgisayar Mühendisliği",
    "elektrik_elektronik_muhendisligi": "Elektrik-Elektronik Mühendisliği",
    "endustri_muhendisligi": "Endüstri Mühendisliği",
}

TOPIC_DISPLAY_NAMES = {
    "summer_school": "yaz okulu",
    "course_schedule": "ders programı",
    "midterm_exam": "ara sınav/vize",
    "final_exam": "final sınav takvimi",
    "makeup_exam": "bütünleme sınav takvimi",
    "internship": "staj",
    "project_exhibition": "proje sergisi",
    "excuse_exam": "mazeret sınav takvimi",
}


def _department_scope_text(department_codes: list[str]) -> str:
    if not department_codes:
        return "Mühendislik bölümleri"
    names = [DEPARTMENT_DISPLAY_NAMES.get(code, code) for code in department_codes]
    return ", ".join(names)


def _topic_scope_text(topic_tags: list[str]) -> str:
    if not topic_tags:
        return ""
    names = [TOPIC_DISPLAY_NAMES.get(tag, tag) for tag in topic_tags]
    return f" {', '.join(names)} duyurusu"


def _record_intent_tags(record: dict[str, Any]) -> set[str]:
    tags = set(record.get("intent_tags") or [])
    inferred = infer_department_announcement_tags(
        "\n".join(
            [
                str(record.get("title") or ""),
                str(record.get("content") or ""),
                str(record.get("search_text") or ""),
            ]
        )
    )
    tags.update(inferred)
    return tags


@lru_cache()
def get_department_announcement_service() -> DepartmentAnnouncementService:
    return DepartmentAnnouncementService()
