"""MDBF öğrenci işleri workflow/form DB-first yanıt servisi."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.repositories.workflow_repository import WorkflowRepository
from scrapers.mdbf_workflow_forms_scraper import FORM_SOURCE_URL, UNIT_CODE, UNIT_NAME, normalize_for_match

logger = logging.getLogger(__name__)

FORM_INTENT_RE = re.compile(
    r"\b(form|dilekce|dilekçe|belge|indir|nerede|ornek|örnek|link|baglanti|bağlantı|dosya|pdf)\w*\b",
    re.IGNORECASE,
)
WORKFLOW_INTENT_RE = re.compile(
    r"\b("
    r"nasil|nasıl|surec|süreç|isler|işler|isliyor|işliyor|ne yap|adim|adım|"
    r"basvuru|başvuru|kacird|kaçırd|itiraz et|neye gore|neye göre|belirlen|"
    r"onay|yurutul|yürütül|sorusturma|soruşturma"
    r")\w*",
    re.IGNORECASE,
)
DATE_INTENT_RE = re.compile(
    r"\b("
    r"ne\s+zaman|hangi\s+tarih|tarih\w*|takvim|"
    r"basvuru\s+tarih\w*|başvuru\s+tarih\w*|bitiyor|biter|son\s+gun|son\s+gün|"
    r"kaç\s+gün|kac\s+gun|geçti\s+mi|gecti\s+mi"
    r")\b",
    re.IGNORECASE,
)
DIRECT_FORM_ONLY_RE = re.compile(
    r"\b("
    r"sadece\s+(?:link|baglanti|form|belge|dosya)|"
    r"yalnizca\s+(?:link|baglanti|form|belge|dosya)|"
    r"yalnızca\s+(?:link|bağlantı|form|belge|dosya)|"
    r"dogrudan|doğrudan|direkt|linkini|baglantisini|bağlantısını|indirme\s+linki"
    r")\b",
    re.IGNORECASE,
)
OTHER_UNIT_RE = re.compile(
    r"\b("
    r"ilahiyat|tip|tıp|sbf|saglik bilimleri|sağlık bilimleri|shmyo|tbmyo|"
    r"iisbf|iibf|gsmf|guzel sanatlar|güzel sanatlar|ydyo|lisansustu|lisansüstü"
    r")\b",
    re.IGNORECASE,
)

MDBF_RE = re.compile(r"\b(mdbf|muhendislik|mühendislik|doga bilimleri|doğa bilimleri)\b", re.IGNORECASE)

FORM_ALIAS_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("intern", "uygulamali"), ("staj", "intern", "intorn", "uygulamali muhendislik")),
    (("sinav", "itiraz"), ("not itiraz", "notuma itiraz", "notuna itiraz", "maddi hata")),
    (("mazeret", "ders", "kayit"), ("mazeretli kayit", "mazeret ders kayit", "ders kaydini kacird")),
    (("kayit", "dondurma"), ("kayit dondur", "kaydimi dondur")),
    (("tek", "ders"), ("tek ders", "tek ders dilekce")),
    (("yaz", "okulu"), ("yaz okulu",)),
)

GENERIC_PETITION_RE = re.compile(
    r"\b("
    r"genel\s+amacli(?:\s+\w+){0,3}\s+dilekce|genel\s+amaçlı(?:\s+\w+){0,3}\s+dilekçe|"
    r"genel\s+dilekce|genel\s+dilekçe|"
    r"ogrenci\s+islerine\s+.*dilekce|öğrenci\s+işlerine\s+.*dilekçe"
    r")\b",
    re.IGNORECASE,
)

FORM_INDEX_RE = re.compile(
    r"\b("
    r"birim\s+form\w*|form\s+listesi|formlar\w*|"
    r"formlara\s+nereden|formlara\s+nasil|formlara\s+nasıl|"
    r"form\s+sayfa\w*|form\s+link\w*"
    r")\b",
    re.IGNORECASE,
)

COURSE_EXEMPTION_ALIAS_RE = re.compile(
    r"\b("
    r"ders\s+saydir\w*|ders\s+saydır\w*|saydir\w*|saydır\w*|"
    r"baska\s+okuldan\s+ders|başka\s+okuldan\s+ders|"
    r"baska\s+universiteden\s+aldigim\s+ders|başka\s+üniversiteden\s+aldığım\s+ders|"
    r"onceden\s+aldigim\s+ders|önceden\s+aldığım\s+ders|"
    r"daha\s+once\s+aldigim\s+ders|daha\s+önce\s+aldığım\s+ders|"
    r"intibak|kredi\s+transferi"
    r")\b",
    re.IGNORECASE,
)

EXAM_APPEAL_ALIAS_RE = re.compile(
    r"\b("
    r"kagid\w*\s+tekrar\s+okut\w*|kağıd\w*\s+tekrar\s+okut\w*|"
    r"kagit\w*\s+tekrar\s+okut\w*|kağıt\w*\s+tekrar\s+okut\w*|"
    r"tekrar\s+okut\w*|tekrar\s+degerlendir\w*|tekrar\s+değerlendir\w*|"
    r"sinav\s+kagid\w*\s+incelen\w*|sınav\s+kağıd\w*\s+incelen\w*|"
    r"kagid\w*\s+incelen\w*|kağıd\w*\s+incelen\w*|"
    r"notum\s+yanlis|notum\s+yanlış|notum\s+dusuk|notum\s+düşük|"
    r"not\s+duzelt\w*|not\s+düzelt\w*|kagit\s+kontrol|kağıt\s+kontrol|"
    r"maddi\s+hata"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkflowRouteDecision:
    normalized_query: str
    process_key: str | None
    form_intent: bool
    workflow_intent: bool
    direct_form_only: bool
    date_intent: bool
    preempt_calendar: bool


class WorkflowService:
    """MDBF workflow ve form sorularını relational DB üzerinden yanıtlar."""

    def __init__(self, repository: WorkflowRepository | None = None) -> None:
        self._repository = repository or WorkflowRepository()

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        if self._has_conflicting_unit(question):
            return None

        route = self._classify_route(question)

        if route.process_key:
            return self._answer_process_query(
                process_key=route.process_key,
                form_intent=route.form_intent,
                workflow_intent=route.workflow_intent,
                direct_form_only=route.direct_form_only,
                date_intent=route.date_intent,
                normalized_query=route.normalized_query,
            )

        if route.form_intent:
            return self._answer_direct_form_query(route.normalized_query)

        return None

    def should_preempt_calendar(self, question: str) -> bool:
        if self._has_conflicting_unit(question):
            return False
        return self._classify_route(question).preempt_calendar

    @staticmethod
    def _has_conflicting_unit(question: str) -> bool:
        return bool(OTHER_UNIT_RE.search(question) and not MDBF_RE.search(question))

    @classmethod
    def _classify_route(cls, question: str) -> WorkflowRouteDecision:
        normalized = normalize_for_match(question)
        process_key = cls._classify_process(normalized)
        form_intent = bool(FORM_INTENT_RE.search(question) or FORM_INTENT_RE.search(normalized))
        workflow_intent = bool(WORKFLOW_INTENT_RE.search(question) or WORKFLOW_INTENT_RE.search(normalized))
        direct_form_only = form_intent and bool(DIRECT_FORM_ONLY_RE.search(question) or DIRECT_FORM_ONLY_RE.search(normalized))
        date_intent = bool(DATE_INTENT_RE.search(question) or DATE_INTENT_RE.search(normalized))
        route = WorkflowRouteDecision(
            normalized_query=normalized,
            process_key=process_key,
            form_intent=form_intent,
            workflow_intent=workflow_intent,
            direct_form_only=direct_form_only,
            date_intent=date_intent,
            preempt_calendar=False,
        )
        return WorkflowRouteDecision(
            normalized_query=route.normalized_query,
            process_key=route.process_key,
            form_intent=route.form_intent,
            workflow_intent=route.workflow_intent,
            direct_form_only=route.direct_form_only,
            date_intent=route.date_intent,
            preempt_calendar=bool(
                route.process_key
                and not cls._is_pure_calendar_query(route)
                and not route.date_intent
                and (route.workflow_intent or route.form_intent or MDBF_RE.search(question))
            ),
        )

    @staticmethod
    def _is_pure_calendar_query(route: WorkflowRouteDecision) -> bool:
        return route.date_intent

    def _answer_process_query(
        self,
        process_key: str,
        form_intent: bool,
        workflow_intent: bool,
        direct_form_only: bool,
        date_intent: bool,
        normalized_query: str,
    ) -> dict[str, Any] | None:
        try:
            workflow = self._repository.get_workflow_by_process(process_key, UNIT_CODE)
        except Exception as exc:  # noqa: BLE001 - DB-first servis RAG'e uydurtmasın
            logger.warning("Workflow DB yanıtı üretilemedi: %s", exc, exc_info=True)
            return self._response(
                "MDBF öğrenci işleri workflow/form verisi için ana kaynak ÜniChat DB'dir. Şu anda DB kaydı okunamadığı için tahmini yanıt üretilmedi.",
                [],
                "db_unavailable",
                process_key,
                normalized_query,
            )

        if not workflow:
            return None

        if date_intent:
            response = self._format_date_not_found_response(workflow)
            return self._response(
                response,
                self._sources_from_workflow(workflow),
                "workflow_date_query",
                process_key,
                normalized_query,
            )

        if direct_form_only or (
            form_intent and not workflow_intent and not self._should_include_workflow_with_form(normalized_query)
        ):
            response = self._format_form_only_response(workflow)
        else:
            response = self._format_workflow_response(workflow)

        return self._response(
            response,
            self._sources_from_workflow(workflow),
            "workflow_form_query" if form_intent else "workflow_query",
            process_key,
            normalized_query,
        )

    def _answer_direct_form_query(self, normalized_query: str) -> dict[str, Any] | None:
        try:
            forms = self._repository.list_forms(UNIT_CODE)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow form DB yanıtı üretilemedi: %s", exc, exc_info=True)
            return None

        if self._is_form_index_query(normalized_query):
            return self._response(
                (
                    "MDBF birim formlarına şu resmi bağlantıdan ulaşabilirsiniz: "
                    f"[MDBF Birim Formları]({FORM_SOURCE_URL})."
                ),
                [self._source_from_form_index()],
                "form_index_query",
                None,
                normalized_query,
            )

        form = self._resolve_form(normalized_query, forms)
        if not form:
            if self._is_generic_petition_query(normalized_query):
                return self._response(
                    (
                        "MDBF resmi birim form listesinde **genel amaçlı dilekçe formu** bulunmuyor. "
                        "Resmi kaynakta yer alan dilekçe/form adları spesifik başlıklardır; bu nedenle genel dilekçe linki üretemem.\n\n"
                        f"Kaynak: [MDBF Birim Formları]({FORM_SOURCE_URL})."
                    ),
                    [self._source_from_form_index()],
                    "form_query_no_match",
                    None,
                    normalized_query,
                )
            return None
        response = (
            f"MDBF **{form['form_name']}** belgesine şu bağlantıdan ulaşabilirsiniz: "
            f"[İndirme Linki]({form['download_url']})."
        )
        return self._response(
            response,
            [self._source_from_form(form)],
            "form_query",
            form.get("process_key"),
            normalized_query,
        )

    @staticmethod
    def _should_include_workflow_with_form(normalized_query: str) -> bool:
        return any(token in normalized_query for token in ("icin", "basvuru", "olmak", "ne yap"))

    @staticmethod
    def _format_form_only_response(workflow: dict[str, Any]) -> str:
        forms = workflow.get("forms") or []
        if forms:
            links = ", ".join(f"[{form['form_name']}]({form['download_url']})" for form in forms)
            return f"MDBF **{workflow['title']}** ile ilişkili form(lar): {links}."

        source = workflow.get("pdf_url")
        response = (
            f"MDBF **{workflow['title']}** için resmi kaynakta doğrudan bir form bağlantısı bulunmuyor."
        )
        if workflow.get("process_key") == "excuse_exam":
            response += " Resmi MDBF form listesinde **Mazeret Sınavı Formu** yer almıyor."
        response += f"\n\nKaynak: [MDBF İş Akış Şeması]({source})."
        return response

    @staticmethod
    def _format_date_not_found_response(workflow: dict[str, Any]) -> str:
        response = (
            f"MDBF **{workflow['title']}** için iş akışı/form kaynağında net başvuru tarihi bulunmuyor. "
            "Resmi kaynakta doğrulanmış tarih olmadığı için tahmini tarih veremem."
        )
        forms = workflow.get("forms") or []
        if forms:
            links = ", ".join(f"[{form['form_name']}]({form['download_url']})" for form in forms)
            response += f"\n\nİlgili resmi form: {links}."
        elif workflow.get("process_key") == "excuse_exam":
            response += "\n\nResmi MDBF form listesinde doğrudan **Mazeret Sınavı Formu** bulunmuyor."
        response += f"\n\nKaynak: [MDBF İş Akış Şeması]({workflow['pdf_url']})."
        return response

    @staticmethod
    def _format_workflow_response(workflow: dict[str, Any]) -> str:
        first_action = workflow.get("first_action_for_student") or "resmi iş akışındaki ilk başvuru adımı"
        lines = [
            f"Konu, MDBF **{workflow['title']}** kapsamına giriyor.",
            f"İlk işlem: {first_action}",
        ]

        steps = workflow.get("steps") or []
        if steps:
            lines.append("\n**Süreç adımları:**")
            for step in steps[:8]:
                actor = f" ({step['actor']})" if step.get("actor") else ""
                lines.append(f"- {step['step_order']}. {step['action_text']}{actor}")

        forms = workflow.get("forms") or []
        if forms:
            links = ", ".join(f"[{form['form_name']}]({form['download_url']})" for form in forms)
            lines.append(f"\nİlgili formu buradan indirebilirsiniz: {links}.")
        elif workflow.get("process_key") == "excuse_exam":
            lines.append("\nResmi MDBF form sayfasında doğrudan **Mazeret Sınavı Formu** bulunmuyor; iş akışı mazeret dilekçesi ve eklerinden bahsediyor.")

        lines.append(f"\nKaynak: [MDBF İş Akış Şeması]({workflow['pdf_url']}).")
        return "\n".join(lines)

    @staticmethod
    def _sources_from_workflow(workflow: dict[str, Any]) -> list[dict[str, Any]]:
        sources = [
            {
                "content": workflow.get("workflow_summary") or workflow.get("title"),
                "source_url": workflow.get("pdf_url"),
                "source_public_url": workflow.get("pdf_url"),
                "category": "ogrenci_isleri",
                "title": workflow.get("title"),
                "doc_kind": "workflow",
            }
        ]
        for form in workflow.get("forms") or []:
            sources.append(WorkflowService._source_from_form(form))
        return sources

    @staticmethod
    def _source_from_form(form: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": f"{form.get('form_name')} indirme bağlantısı.",
            "source_url": form.get("download_url"),
            "source_public_url": form.get("download_url"),
            "category": "ogrenci_isleri",
            "title": form.get("form_name"),
            "doc_kind": "form",
        }

    @staticmethod
    def _source_from_form_index() -> dict[str, Any]:
        return {
            "content": "MDBF resmi birim formları listesi.",
            "source_url": FORM_SOURCE_URL,
            "source_public_url": FORM_SOURCE_URL,
            "category": "ogrenci_isleri",
            "title": "MDBF Birim Formları",
            "doc_kind": "form_index",
        }

    @staticmethod
    def _is_generic_petition_query(normalized_query: str) -> bool:
        return bool(GENERIC_PETITION_RE.search(normalized_query))

    @staticmethod
    def _is_form_index_query(normalized_query: str) -> bool:
        return bool(FORM_INDEX_RE.search(normalized_query) and "mdbf" in normalized_query)

    @staticmethod
    def _resolve_form(normalized_query: str, forms: list[dict[str, Any]]) -> dict[str, Any] | None:
        scored: list[tuple[int, dict[str, Any]]] = []
        query_tokens = set(normalized_query.split())
        for form in forms:
            normalized_name = normalize_for_match(form.get("form_name") or "")
            if not normalized_name:
                continue
            score = 0
            if normalized_name in normalized_query or normalized_query in normalized_name:
                score += 80
            overlap = query_tokens.intersection(normalized_name.split())
            score += len(overlap) * 12
            if "form" in normalized_name and "form" in query_tokens:
                score += 8
            score += WorkflowService._form_alias_score(normalized_query, normalized_name)
            if score >= 24:
                scored.append((score, form))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _form_alias_score(normalized_query: str, normalized_name: str) -> int:
        score = 0
        for name_needles, query_aliases in FORM_ALIAS_RULES:
            if not all(needle in normalized_name for needle in name_needles):
                continue
            if any(alias in normalized_query for alias in query_aliases):
                score += 45
        return score

    @staticmethod
    def _is_exam_appeal_query(normalized: str) -> bool:
        if EXAM_APPEAL_ALIAS_RE.search(normalized):
            return True
        if "itiraz" not in normalized and "maddi hata" not in normalized:
            return False
        return any(token in normalized for token in ("sinav", "not", "final", "vize", "butunleme"))

    @staticmethod
    def _classify_process(normalized: str) -> str | None:
        if WorkflowService._is_exam_appeal_query(normalized):
            return "exam_appeal"
        if "mazeret" in normalized and "sinav" in normalized:
            return "excuse_exam"
        if "kayit dondur" in normalized:
            return "freeze_registration"
        if "disiplin" in normalized:
            return "disciplinary_process"
        if "kontenjan" in normalized:
            if any(
                token in normalized
                for token in (
                    "belirlen",
                    "belirleme",
                    "surec",
                    "adim",
                    "nasil",
                    "isliyor",
                    "isler",
                    "onay",
                    "kim",
                )
            ):
                return "quota_determination"
            return None
        if "muaf" in normalized or COURSE_EXEMPTION_ALIAS_RE.search(normalized):
            return "course_exemption"
        if "ders program" in normalized:
            return "course_schedule"
        if (
            "mazeretli kayit" in normalized
            or "mazeret ders kayit" in normalized
            or "mazeret ders kaydi" in normalized
            or "kayit yenile" in normalized
            or ("ders kay" in normalized and any(token in normalized for token in ("kacir", "gec", "mazeret")))
        ):
            return "late_registration"
        if "ders kay" in normalized:
            return "course_registration"
        return None

    @staticmethod
    def _response(
        response: str,
        sources: list[dict[str, Any]],
        intent: str,
        process_key: str | None,
        normalized_query: str,
    ) -> dict[str, Any]:
        return {
            "response": response,
            "sources": sources,
            "metadata": {
                "db_first": True,
                "service": "workflow_service",
                "intent": intent,
                "unit_code": UNIT_CODE,
                "unit_name": UNIT_NAME,
                "process_key": process_key,
                "normalized_query": normalized_query,
                "rag_fallback_used": False,
            },
        }


@lru_cache()
def get_workflow_service() -> WorkflowService:
    return WorkflowService()


__all__ = ["WorkflowService", "get_workflow_service"]
