"""
UniChat — Akademik Takvim Deterministik Yanıt Servisi

RAG belgeleri içinde event bazlı akademik takvim kayıtları varsa, net tarih
sorularını LLM'e bırakmadan structured metadata üzerinden yanıtlar.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

import psycopg2
from psycopg2 import sql

from app.config import get_settings

logger = logging.getLogger(__name__)

ACADEMIC_QUERY_RE = re.compile(
    r"\b(akademik\s*takvim|ders\s+başlang\w*|ders\s+baslang\w*|okul\s+ne\s+zaman|"
    r"ders\s+kay\w*|ders\s+kayı\w*|kayıt\s+yenile\w*|kayit\s+yenile\w*|vize\w*|ara\s+sınav\w*|"
    r"ara\s+sinav\w*|final\w*|bütünleme\w*|butunleme\w*|büt\w*|tek\s+ders|güz|guz|bahar|"
    r"mazeretli\s+kayıt\w*|mazeretli\s+kayit\w*|kayıt\s+dondur\w*|kayit\s+dondur\w*|"
    r"kayıt\s+başvuru\w*|kayit\s+basvuru\w*|son\s+başvuru|son\s+basvuru|"
    r"kaç\s+gün\s+kaldı|kac\s+gun\s+kaldi|geçti\s+mi|gecti\s+mi)\b",
    re.IGNORECASE,
)

ACADEMIC_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(20\d{2})\b")

EVENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("course_registration", ("ders kaydı", "ders kayit", "ders kayıt", "ders seçimi")),
    ("registration", ("kayıt yenileme", "kayit yenileme", "kesin kayıt")),
    ("add_drop", ("ekle", "bırak", "birak", "çıkarma", "cikarma")),
    ("semester_start", ("ders başlangıcı", "ders baslangici", "okul ne zaman", "derslerin başlaması")),
    ("semester_end", ("ders bitişi", "ders bitisi", "derslerin sona ermesi")),
    ("midterm", ("vize", "ara sınav", "ara sinav")),
    ("final_exam", ("final", "yarıyıl sonu sınav", "yariyil sonu sinav", "yıl sonu sınav", "yil sonu sinav")),
    ("makeup_exam", ("bütünleme", "butunleme", "büt", "but")),
    ("single_course_exam", ("tek ders",)),
    ("graduation", ("mezun",)),
    ("application", ("başvuru", "basvuru")),
)

TERM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("güz yarıyılı", ("güz", "guz")),
    ("bahar yarıyılı", ("bahar",)),
    ("yaz dönemi", ("yaz okulu", "yaz dönemi", "yaz donemi")),
)

CALENDAR_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tıp fakültesi", ("tıp", "tip")),
    ("lisansüstü", ("lisansüstü", "lisansustu", "enstitü", "enstitu")),
    ("tömer", ("tömer", "tomer")),
    ("yabancı diller/hazırlık", ("yabancı diller", "yabanci diller", "hazırlık", "hazirlik")),
)

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


@dataclass
class CalendarEventRecord:
    content: str
    meta: dict[str, Any]


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        value = value.replace(src, dst)
    return value


def _current_academic_year(today: date | None = None) -> str:
    today = today or date.today()
    if today.month >= 9:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _requested_academic_year(query: str) -> str | None:
    match = ACADEMIC_YEAR_RE.search(query)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _requested_event_category(query: str) -> str | None:
    normalized = _normalize(query)
    if "kayit dondur" in normalized:
        return "application"
    if (
        "mazeretli kayit" in normalized
        or ("mazeret" in normalized and ("ders kay" in normalized or "kayit yenile" in normalized))
    ):
        return "course_registration"
    if "kayit" in normalized and "basvuru" in normalized:
        return "registration"
    for category, needles in EVENT_RULES:
        if any(_normalize(needle) in normalized for needle in needles):
            return category
    return None


def _requested_event_variant(query: str) -> str | None:
    normalized = _normalize(query)
    if "kayit dondur" in normalized:
        return "freeze_registration"
    if (
        "mazeretli kayit" in normalized
        or ("mazeret" in normalized and ("ders kay" in normalized or "kayit yenile" in normalized))
    ):
        return "late_course_registration"
    return None


def _requested_term(query: str) -> str | None:
    normalized = _normalize(query)
    for term, needles in TERM_RULES:
        if any(_normalize(needle) in normalized for needle in needles):
            return term
    return None


def _requested_calendar_type(query: str) -> str | None:
    normalized = _normalize(query)
    for calendar_type, needles in CALENDAR_TYPE_RULES:
        if any(_normalize(needle) in normalized for needle in needles):
            return calendar_type
    return None


def _format_iso_date(iso_value: str | None) -> str:
    if not iso_value:
        return ""
    try:
        parsed = date.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    return f"{parsed.day} {MONTH_NAMES_TR[parsed.month]} {parsed.year}"


def _format_event_dates(meta: dict[str, Any]) -> str:
    original = meta.get("original_date_text")
    if original:
        return str(original)
    start_date = meta.get("start_date")
    end_date = meta.get("end_date")
    if not start_date:
        return "tarih bilgisi parse incelemesi gerektiriyor"
    if not end_date or end_date == start_date:
        return _format_iso_date(start_date)
    return f"{_format_iso_date(start_date)} - {_format_iso_date(end_date)}"


def _days_status(meta: dict[str, Any], today: date | None = None) -> str | None:
    today = today or date.today()
    try:
        start = date.fromisoformat(str(meta.get("start_date")))
        end = date.fromisoformat(str(meta.get("end_date") or meta.get("start_date")))
    except (TypeError, ValueError):
        return None

    if today < start:
        return f"Başlamasına { (start - today).days } gün kaldı."
    if start <= today <= end:
        return "Bu tarih aralığı şu anda devam ediyor."
    return f"Bu tarih aralığı geçti; bitişinden { (today - end).days } gün geçti."


def _event_start(meta: dict[str, Any]) -> date:
    try:
        return date.fromisoformat(str(meta.get("start_date")))
    except (TypeError, ValueError):
        return date.max


def _is_secondary_exam_title(title: str) -> bool:
    normalized = _normalize(title)
    return any(term in normalized for term in ("sonuc", "notlarin", "ilan", "duzeltilmesi", "otomasyon"))


def _is_preferred_title(category: str, title: str) -> bool:
    normalized = _normalize(title)
    if category == "course_registration":
        return normalized == "ogrenci ders kayitlari"
    if category == "final_exam":
        return "yariyil sonu" in normalized and "final" in normalized and "sinav" in normalized
    if category == "makeup_exam":
        return "butunleme" in normalized and "sinav" in normalized and not _is_secondary_exam_title(title)
    if category == "midterm":
        return "ara sinav" in normalized or "vize" in normalized
    return True


def _event_text(event: CalendarEventRecord) -> str:
    return _normalize(f"{event.content} {event.meta.get('event_title', '')} {event.meta.get('title', '')}")


def _event_matches_variant(event: CalendarEventRecord, requested_variant: str | None) -> bool:
    if not requested_variant:
        return True
    event_text = _event_text(event)
    if requested_variant == "late_course_registration":
        return "mazeret" in event_text and "ders kay" in event_text
    if requested_variant == "freeze_registration":
        return "kayit dondurma" in event_text or "kayit dondur" in event_text
    return True


def _has_deadline_intent(query: str) -> bool:
    normalized = _normalize(query)
    return any(token in normalized for token in ("bitiyor", "biter", "son gun", "son basvuru", "hangi gun"))


def _deadline_note(question: str, events: list[CalendarEventRecord]) -> str:
    if not _has_deadline_intent(question) or not events:
        return ""

    def end_text(event: CalendarEventRecord) -> str:
        return _format_iso_date(str(event.meta.get("end_date") or event.meta.get("start_date") or ""))

    if len(events) == 1:
        return f"\n\nSon gün: {end_text(events[0])}."

    lines = ["\n\nSon günler:"]
    for event in events:
        title = event.meta.get("event_title") or event.meta.get("title") or "Akademik takvim etkinliği"
        term = f" ({event.meta.get('term')})" if event.meta.get("term") else ""
        lines.append(f"- {title}{term}: {end_text(event)}")
    return "\n".join(lines)


class AcademicCalendarService:
    """Structured akademik takvim event'lerinden deterministik cevap üretir."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def answer_chat_query(self, question: str) -> dict | None:
        if not ACADEMIC_QUERY_RE.search(question):
            return None

        requested_category = _requested_event_category(question)
        if not requested_category:
            return None

        requested_year = _requested_academic_year(question)
        effective_year = requested_year or _current_academic_year()
        requested_type = _requested_calendar_type(question)
        requested_term = _requested_term(question)
        requested_variant = _requested_event_variant(question)

        events = self._load_events()
        if not events:
            return None

        ranked = sorted(
            (
                (self._score_event(event, question, requested_category, effective_year, requested_type, requested_term), event)
                for event in events
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        answer_events = self._select_answer_events(
            ranked=ranked,
            requested_category=requested_category,
            requested_term=requested_term,
            requested_variant=requested_variant,
        )
        if not answer_events:
            return None

        assumption_parts: list[str] = []
        if not requested_year:
            assumption_parts.append(f"Bu bilgi güncel akademik yıl ({effective_year}) için verilmiştir.")
        if not requested_type:
            assumption_parts.append(
                "Genel/önlisans-lisans akademik takvimi esas alınmıştır; Tıp, lisansüstü veya TÖMER takvimlerinde tarihler farklı olabilir."
            )

        primary_event = answer_events[0]
        primary_meta = primary_event.meta
        status_text = ""
        if re.search(r"kaç\s+gün\s+kaldı|kac\s+gun\s+kaldi|geçti\s+mi|gecti\s+mi", question, re.IGNORECASE):
            status_candidate = self._first_upcoming_or_primary(answer_events)
            status = _days_status(status_candidate.meta)
            if status:
                status_text = f"\n\n{status}"

        source_url = primary_meta.get("source_file_url") or primary_meta.get("source_page_url") or primary_meta.get("source_url")
        if len(answer_events) == 1:
            body = self._format_event_line(answer_events[0], bullet=False)
        else:
            lines = ["**Akademik takvimde ilgili tarihler:**"]
            lines.extend(self._format_event_line(event, bullet=True) for event in answer_events)
            body = "\n".join(lines)

        special_note = self._special_scope_note(question, requested_category, answer_events)
        deadline_note = _deadline_note(question, answer_events)
        response = (
            f"{' '.join(assumption_parts)}\n\n"
            f"{body}{status_text}{deadline_note}{special_note}\n\n"
            f"Kaynak: {source_url}"
        ).strip()

        return {
            "response": response,
            "sources": [
                {
                    "content": primary_event.content[:200] + "..." if len(primary_event.content) > 200 else primary_event.content,
                    "source_url": source_url,
                    "source_public_url": source_url,
                    "category": primary_meta.get("category"),
                    "title": primary_meta.get("title"),
                    "doc_kind": primary_meta.get("doc_kind"),
                }
            ],
        }

    def _load_events(self) -> list[CalendarEventRecord]:
        try:
            database_url = os.environ.get("DATABASE_URL") or self._settings.DATABASE_URL
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute(
                sql.SQL(
                    """
                    SELECT content, meta
                    FROM {}
                    WHERE meta->>'doc_kind' = 'academic_calendar_event'
                      AND coalesce(meta->>'is_active', 'true') = 'true'
                      AND coalesce(meta->>'parse_status', '') = 'parsed'
                    """
                ).format(sql.Identifier(self._settings.HAYSTACK_TABLE_NAME))
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [CalendarEventRecord(content=row[0] or "", meta=row[1] or {}) for row in rows]
        except Exception as exc:  # noqa: BLE001 - RAG fallback çalışabilsin
            logger.warning("Akademik takvim deterministic servis DB okuyamadı: %s", exc)
            return []

    def _select_answer_events(
        self,
        ranked: list[tuple[int, CalendarEventRecord]],
        requested_category: str,
        requested_term: str | None,
        requested_variant: str | None = None,
    ) -> list[CalendarEventRecord]:
        eligible = [
            event for score, event in ranked
            if score >= 70 and event.meta.get("event_category") == requested_category
        ]
        if not eligible:
            return []

        if requested_variant:
            variant_events = [event for event in eligible if _event_matches_variant(event, requested_variant)]
            if variant_events:
                eligible = variant_events
                if requested_term:
                    term_events = [event for event in eligible if event.meta.get("term") == requested_term]
                    return (term_events or eligible)[:1]
                unique_by_term: dict[str, CalendarEventRecord] = {}
                for event in sorted(eligible, key=lambda item: (_event_start(item.meta), str(item.meta.get("term") or ""))):
                    term = str(event.meta.get("term") or event.meta.get("event_title") or len(unique_by_term))
                    unique_by_term.setdefault(term, event)
                return list(unique_by_term.values())[:4]

        if requested_term:
            term_events = [event for event in eligible if event.meta.get("term") == requested_term]
            if term_events:
                preferred_term_events = [
                    event for event in term_events
                    if _is_preferred_title(requested_category, str(event.meta.get("event_title") or ""))
                ]
                return (preferred_term_events or term_events)[:1]
            return eligible[:1]

        preferred = [
            event for event in eligible
            if _is_preferred_title(requested_category, str(event.meta.get("event_title") or ""))
        ]
        selected = preferred or eligible[:1]

        unique_by_term: dict[str, CalendarEventRecord] = {}
        for event in sorted(selected, key=lambda item: (_event_start(item.meta), str(item.meta.get("term") or ""))):
            term = str(event.meta.get("term") or event.meta.get("event_title") or len(unique_by_term))
            unique_by_term.setdefault(term, event)

        return list(unique_by_term.values())[:4]

    @staticmethod
    def _first_upcoming_or_primary(events: list[CalendarEventRecord]) -> CalendarEventRecord:
        today = date.today()
        upcoming = [event for event in events if _event_start(event.meta) >= today]
        if upcoming:
            return sorted(upcoming, key=lambda event: _event_start(event.meta))[0]
        return events[0]

    @staticmethod
    def _format_event_line(event: CalendarEventRecord, bullet: bool = False) -> str:
        meta = event.meta
        title = meta.get("event_title") or meta.get("title") or "Akademik takvim etkinliği"
        term = f" ({meta.get('term')})" if meta.get("term") else ""
        date_text = _format_event_dates(meta)
        prefix = "- " if bullet else ""
        return f"{prefix}**{title}{term}:** {date_text}."

    @staticmethod
    def _special_scope_note(
        question: str,
        requested_category: str,
        answer_events: list[CalendarEventRecord],
    ) -> str:
        normalized_question = _normalize(question)
        if "mazeret" not in normalized_question or requested_category not in {"registration", "course_registration"}:
            return ""

        event_text = _normalize(" ".join(
            f"{event.content} {event.meta.get('event_title', '')}"
            for event in answer_events
        ))
        if "mazeret" in event_text:
            return ""
        return "\n\nNot: Akademik takvimde mazeretli kayıt yenileme için ayrı bir tarih satırı bulunmadığından genel kayıt/kayıt yenileme tarihleri gösterilmiştir."

    def _score_event(
        self,
        event: CalendarEventRecord,
        question: str,
        requested_category: str,
        effective_year: str,
        requested_type: str | None,
        requested_term: str | None,
    ) -> int:
        meta = event.meta
        score = 0

        if meta.get("academic_year") == effective_year:
            score += 45
        elif meta.get("academic_year"):
            score -= 30

        if meta.get("event_category") == requested_category:
            score += 55

        calendar_type = str(meta.get("calendar_type") or "")
        if requested_type:
            if requested_type in calendar_type:
                score += 30
            else:
                score -= 20
        elif calendar_type == "genel/önlisans-lisans":
            score += 20

        if requested_term:
            if meta.get("term") == requested_term:
                score += 20
            elif meta.get("term"):
                score -= 5

        normalized_question = _normalize(question)
        normalized_content = _normalize(f"{event.content} {meta.get('event_title', '')}")
        normalized_title = _normalize(str(meta.get("event_title") or ""))

        if requested_category in {"final_exam", "midterm", "makeup_exam"}:
            if "sinav" in normalized_title and not any(
                penalty in normalized_title
                for penalty in ("sonuc", "notlarin", "ilan", "duzeltilmesi", "otomasyon")
            ):
                score += 25
            if any(penalty in normalized_title for penalty in ("sonuc", "notlarin", "ilan", "duzeltilmesi", "otomasyon")):
                score -= 25

        if requested_category == "course_registration":
            if "mazeret" in normalized_question:
                if "mazeret" in normalized_title and "ders kay" in normalized_title:
                    score += 35
                elif normalized_title == "ogrenci ders kayitlari":
                    score -= 20
            elif normalized_title == "ogrenci ders kayitlari":
                score += 25
            elif "danisman" in normalized_title or "mazeret" in normalized_title:
                score -= 10

        if requested_category == "application" and "kayit dondur" in normalized_question:
            if "kayit dondurma" in normalized_title or "kayit dondur" in normalized_title:
                score += 35
            else:
                score -= 15

        for token in normalized_question.split():
            if len(token) >= 4 and token in normalized_content:
                score += 1

        try:
            confidence = float(meta.get("confidence_score") or 0)
        except (TypeError, ValueError):
            confidence = 0
        score += int(confidence * 10)
        return score


@lru_cache()
def get_academic_calendar_service() -> AcademicCalendarService:
    return AcademicCalendarService()
