"""MDBF öğrenci işleri workflow ve form scraper'ı.

Bu modül yalnızca MDBF iş akışları ve MDBF birim formları sayfalarını işler.
Çıktı hem relational DB'ye hem de isteğe bağlı Haystack ingestion'a uygundur.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from haystack import Document

from app.config import get_settings

logger = logging.getLogger(__name__)

METADATA_VERSION = "mdbf_workflows.v1"
UNIT_CODE = "MDBF"
UNIT_NAME = "Mühendislik ve Doğa Bilimleri Fakültesi"
UNIT_TYPE = "fakülte"
WORKFLOW_SOURCE_URL = "https://www.gibtu.edu.tr/mdbf/icerik/30935/is-akis-surecleri"
FORM_SOURCE_URL = "https://www.gibtu.edu.tr/BirimForm.aspx?id=15"
USER_AGENT = "UniChatBot/1.0 (+workflow-form-scraper)"


@dataclass(frozen=True)
class WorkflowTarget:
    title: str
    process_key: str


WORKFLOW_TARGETS: tuple[WorkflowTarget, ...] = (
    WorkflowTarget("Ders Kayıt İş Akış Şeması", "course_registration"),
    WorkflowTarget("Ders Programı İş Akış Şeması", "course_schedule"),
    WorkflowTarget("Ders Muafiyet İş Akış Şeması", "course_exemption"),
    WorkflowTarget("Mazeret Sınavı İş Akış Şeması", "excuse_exam"),
    WorkflowTarget("Mazeretli Kayıt Yenileme İş Akış Şeması", "late_registration"),
    WorkflowTarget("Öğrenci Disiplin İşlemleri İş Akış Şeması", "disciplinary_process"),
    WorkflowTarget("Öğrenci Kayıt Dondurma İşlemleri İş Akış Şeması", "freeze_registration"),
    WorkflowTarget("Öğrenci Kontenjanları Belirleme İşlemleri İş Akış Şeması", "quota_determination"),
    WorkflowTarget("Sınavlara İtiraz İşlemleri İş Akış Şeması", "exam_appeal"),
)

TARGET_BY_NORMALIZED_TITLE = {
    " ".join(_target.title.casefold().split()): _target
    for _target in WORKFLOW_TARGETS
}

PROCESS_FORM_RULES: dict[str, tuple[str, ...]] = {
    "course_exemption": (
        "Ders Muafiyet Başvuru Formu",
        "Ders Muafiyet Değerlendirme Formu",
    ),
    "late_registration": ("Mazeret Ders Kayıt Formu",),
    "freeze_registration": ("Kayıt Dondurma Başvuru Formu",),
    "exam_appeal": ("Sınav Kağıdına İtiraz ( Maddi Hata ) Formu",),
}

WORKFLOW_ACTION_VERBS = (
    "hazırlan",
    "teslim",
    "kayıt altına",
    "değerlendirme",
    "sunum",
    "hazırlanması",
    "bildirilmesi",
    "uygun hale",
    "uygulanması",
    "işlenmesi",
    "arşivlenmesi",
    "belirlenmesi",
    "ilan",
    "yapılır",
    "yapılır.",
    "yapıl",
    "alınması",
    "oluşturulması",
)

DOCUMENT_HINTS = (
    "yönetmeliği",
    "formu",
    "dilekçesi",
    "dilekçe",
    "kararı",
    "takvimi",
    "tutanağı",
    "belgesi",
)

FOOTER_MARKERS = (
    "HAZIRLAYAN",
    "KONTROL EDEN",
    "ONAYLAYAN",
    "Kalite Geliştirme",
)


def normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        normalized = normalized.replace(src, dst)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_response(response: requests.Response) -> str:
    if not response.encoding or response.encoding.upper() in {"ISO-8859-1", "ASCII"}:
        detected = response.apparent_encoding
        if detected:
            response.encoding = detected
        else:
            response.encoding = "utf-8"
    return response.text


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class MdbfWorkflowFormsScraper:
    """MDBF workflow/form kaynaklarını parse eden scraper."""

    def __init__(
        self,
        workflow_url: str = WORKFLOW_SOURCE_URL,
        form_url: str = FORM_SOURCE_URL,
        session: requests.Session | None = None,
        timeout: int = 30,
    ) -> None:
        self.workflow_url = workflow_url
        self.form_url = form_url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def run(
        self,
        use_ai: bool = True,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
    ) -> dict[str, Any]:
        started_at = utc_now()
        if use_ai and not self.ollama_available(ollama_url):
            logger.warning("Ollama erişilebilir değil; workflow extraction deterministik fallback ile sürecek.")
            use_ai = False

        workflow_html = self.fetch_text(self.workflow_url)
        form_html = self.fetch_text(self.form_url)

        workflow_links = self.parse_workflow_links(workflow_html)
        forms = self.parse_forms(form_html, check_downloads=True)
        form_lookup = {normalize_for_match(form["form_name"]): form for form in forms}

        workflows: list[dict[str, Any]] = []
        for workflow in workflow_links:
            pdf_bytes, status_code = self.fetch_bytes(workflow["pdf_url"])
            checksum = _sha256_bytes(pdf_bytes)
            extraction = self.extract_workflow_pdf(
                workflow=workflow,
                pdf_bytes=pdf_bytes,
                use_ai=use_ai,
                ollama_url=ollama_url,
                ollama_model=ollama_model,
            )
            mapped_forms = self.map_forms_to_workflow(workflow["process_key"], form_lookup)
            needs_review = bool(extraction.get("needs_review"))
            workflows.append({
                **workflow,
                **extraction,
                "unit_code": UNIT_CODE,
                "unit_name": UNIT_NAME,
                "unit_type": UNIT_TYPE,
                "source_page_url": self.workflow_url,
                "pdf_http_status": status_code,
                "pdf_checksum": checksum,
                "pdf_size_bytes": len(pdf_bytes),
                "fetched_at": utc_now(),
                "mapped_form_names": [form["form_name"] for form in mapped_forms],
                "needs_review": needs_review,
            })

        mapping_count = sum(len(workflow["mapped_form_names"]) for workflow in workflows)
        report = self.build_validation_report(workflows, forms, mapping_count)
        return {
            "scrape_run": {
                "scrape_run_id": f"mdbf-workflows-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "scraper_name": "mdbf_workflow_forms_scraper",
                "metadata_version": METADATA_VERSION,
                "unit_code": UNIT_CODE,
                "source_workflows_url": self.workflow_url,
                "source_forms_url": self.form_url,
                "started_at": started_at,
                "finished_at": utc_now(),
                "status": "success" if len(workflows) == len(WORKFLOW_TARGETS) else "needs_review",
                "workflow_count": len(workflows),
                "form_count": len(forms),
                "mapping_count": mapping_count,
                "validation_report": report,
            },
            "workflows": workflows,
            "forms": forms,
            "validation_report": report,
            "rag_documents": self.to_documents(workflows, forms),
        }

    def fetch_text(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return _decode_response(response)

    def fetch_bytes(self, url: str) -> tuple[bytes, int]:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content, response.status_code

    @staticmethod
    def ollama_available(ollama_url: str | None = None) -> bool:
        settings = get_settings()
        base_url = (ollama_url or settings.OLLAMA_URL).rstrip("/")
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def parse_workflow_links(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        content_node = soup.select_one("form#aspnetForm") or soup
        text = _clean_text(content_node.get_text(" ", strip=True))
        content_text = self._workflow_content_text(text)
        all_names = re.findall(r"-\s*(.*?)\s+için\s+Tıklayınız", content_text)
        pdf_links = [
            urljoin(self.workflow_url, link.get("href", ""))
            for link in content_node.find_all("a", href=True)
            if ".pdf" in link.get("href", "").lower()
        ]

        if len(all_names) < len(WORKFLOW_TARGETS):
            raise ValueError("İş akışı sayfasında beklenen workflow başlıkları parse edilemedi.")

        matched: list[dict[str, Any]] = []
        for name, pdf_url in zip(all_names, pdf_links[:len(all_names)]):
            normalized_name = " ".join(name.casefold().split())
            target = TARGET_BY_NORMALIZED_TITLE.get(normalized_name)
            if not target:
                continue
            matched.append({
                "title": target.title,
                "normalized_title": normalize_for_match(target.title),
                "process_key": target.process_key,
                "pdf_url": pdf_url,
            })

        found_keys = {item["process_key"] for item in matched}
        missing = [target.title for target in WORKFLOW_TARGETS if target.process_key not in found_keys]
        if missing:
            raise ValueError(f"Eksik MDBF öğrenci workflow başlığı: {', '.join(missing)}")
        return matched

    @staticmethod
    def _workflow_content_text(text: str) -> str:
        start = text.find("PERSONEL İŞLERİ İŞ AKIŞ ŞEMALARI")
        end = text.find("MENÜ", start if start >= 0 else 0)
        if start >= 0 and end > start:
            return text[start:end]
        return text

    def parse_forms(self, html: str, check_downloads: bool = True) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        forms: list[dict[str, Any]] = []
        seen: set[str] = set()
        fetched_at = utc_now()
        for link in soup.find_all("a", href=True):
            raw_href = link.get("href", "").strip()
            if not raw_href.lower().startswith("medya/birim/dosya/"):
                continue
            download_url = urljoin(self.form_url, raw_href)
            if download_url in seen:
                continue
            seen.add(download_url)
            form_name = _clean_text(link.get_text(" ", strip=True))
            file_extension = Path(download_url.split("?", 1)[0]).suffix.lstrip(".").lower()
            http_status = None
            checksum = None
            if check_downloads:
                content, http_status = self.fetch_bytes(download_url)
                checksum = _sha256_bytes(content)
            forms.append({
                "unit_code": UNIT_CODE,
                "unit_name": UNIT_NAME,
                "unit_type": UNIT_TYPE,
                "process_key": self.infer_form_process_key(form_name),
                "form_name": form_name,
                "normalized_form_name": normalize_for_match(form_name),
                "download_url": download_url,
                "file_extension": file_extension,
                "http_status": http_status,
                "checksum": checksum,
                "fetched_at": fetched_at,
                "source_page_url": self.form_url,
                "is_active": True,
                "needs_review": False,
            })
        return forms

    @staticmethod
    def infer_form_process_key(form_name: str) -> str | None:
        normalized = normalize_for_match(form_name)
        if "muafiyet" in normalized:
            return "course_exemption"
        if "mazeret ders kayit" in normalized:
            return "late_registration"
        if "kayit dondurma" in normalized:
            return "freeze_registration"
        if "sinav kagidina itiraz" in normalized or "maddi hata" in normalized:
            return "exam_appeal"
        return None

    @staticmethod
    def map_forms_to_workflow(process_key: str, form_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        for form_name in PROCESS_FORM_RULES.get(process_key, ()):
            form = form_lookup.get(normalize_for_match(form_name))
            if form:
                mapped.append(form)
        return mapped

    def extract_workflow_pdf(
        self,
        workflow: dict[str, Any],
        pdf_bytes: bytes,
        use_ai: bool,
        ollama_url: str | None,
        ollama_model: str | None,
    ) -> dict[str, Any]:
        raw_text = self.extract_pdf_text(pdf_bytes)
        deterministic = self.extract_workflow_from_text(workflow["title"], raw_text)
        layout_result = self.extract_with_pymupdf_layout(
            title=workflow["title"],
            pdf_bytes=pdf_bytes,
            raw_text=raw_text,
        )
        base_result = layout_result or deterministic
        if not use_ai:
            return base_result

        ai_result = self.extract_with_ollama_vision(
            title=workflow["title"],
            pdf_bytes=pdf_bytes,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )
        if not ai_result:
            base_result["extraction_method"] = f"{base_result['extraction_method']}_ai_unavailable"
            return base_result

        merged = {**base_result, **ai_result}
        merged["raw_text"] = raw_text
        if base_result.get("steps"):
            merged["steps"] = base_result["steps"]
            merged["first_action_for_student"] = base_result.get("first_action_for_student") or merged.get("first_action_for_student")
            merged["final_outcome"] = base_result.get("final_outcome") or merged.get("final_outcome")
            merged["related_documents"] = base_result.get("related_documents") or merged.get("related_documents") or []
            merged["decision_points"] = base_result.get("decision_points") or merged.get("decision_points") or []
        merged["confidence_score"] = max(
            float(base_result.get("confidence_score") or 0),
            float(ai_result.get("confidence_score") or 0),
        )
        merged["needs_review"] = bool(base_result.get("needs_review"))
        merged["extraction_method"] = f"{ai_result.get('extraction_method', 'ollama_vision')}+{base_result.get('extraction_method', 'deterministic')}"
        return merged

    @staticmethod
    def extract_pdf_text(pdf_bytes: bytes) -> str:
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - requirements içinde var
            raise RuntimeError("pdfplumber yüklü değil.") from exc

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    text_parts.append(text.strip())
        return "\n".join(text_parts).strip()

    @staticmethod
    def extract_workflow_from_text(title: str, raw_text: str) -> dict[str, Any]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        body_lines: list[str] = []
        for line in lines:
            if any(marker in line for marker in FOOTER_MARKERS):
                break
            body_lines.append(line)

        steps: list[dict[str, Any]] = []
        related_documents: list[str] = []
        for line in body_lines:
            lower = line.casefold()
            if any(hint in lower for hint in DOCUMENT_HINTS):
                related_documents.append(line)
            if not _looks_like_action_line(line):
                continue
            steps.append({
                "step_order": len(steps) + 1,
                "actor": _detect_actor(line),
                "action_text": line,
                "next_step_order": len(steps) + 2,
                "needs_review": False,
            })

        if steps:
            steps[-1]["next_step_order"] = None

        related_documents = _dedupe_preserve_order(related_documents)
        first_action = steps[0]["action_text"] if steps else ""
        final_outcome = steps[-1]["action_text"] if steps else ""
        confidence = 0.88 if len(steps) >= 4 else 0.58
        summary = (
            f"{title}, öğrencinin başvuru/işlem adımlarının ilgili MDBF birimleri "
            f"tarafından değerlendirilip sonuçlandırıldığı resmi iş akışıdır."
        )
        if first_action and final_outcome:
            summary = f"{title} süreci '{first_action}' adımıyla başlar ve '{final_outcome}' adımıyla tamamlanır."

        return {
            "workflow_summary": summary,
            "first_action_for_student": first_action,
            "final_outcome": final_outcome,
            "steps": steps,
            "related_documents": related_documents,
            "decision_points": [],
            "confidence_score": confidence,
            "needs_review": confidence < 0.75,
            "extraction_method": "deterministic",
            "raw_text": raw_text,
        }

    @staticmethod
    def extract_with_pymupdf_layout(title: str, pdf_bytes: bytes, raw_text: str) -> dict[str, Any] | None:
        try:
            import fitz
        except ImportError:
            return None

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count == 0:
                return None
            page = doc.load_page(0)
            width = float(page.rect.width)
            height = float(page.rect.height)
            blocks = []
            for block in page.get_text("blocks"):
                x0, y0, x1, y1, text, *_ = block
                clean = _clean_text(text)
                if not clean:
                    continue
                if y0 < height * 0.17 or y0 > height * 0.82:
                    continue
                lower = clean.casefold()
                if any(marker.casefold() in lower for marker in FOOTER_MARKERS):
                    continue
                blocks.append({
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                    "text": clean,
                })

            action_blocks = [
                block for block in blocks
                if block["x0"] <= width * 0.48
                and not _is_flow_terminal(block["text"])
                and not _is_document_only_text(block["text"])
                and not _is_non_action_text(block["text"])
            ]
            action_blocks.sort(key=lambda item: (item["y0"], item["x0"]))

            grouped_actions: list[dict[str, Any]] = []
            for block in action_blocks:
                if grouped_actions and block["y0"] - grouped_actions[-1]["y1"] <= 18:
                    grouped_actions[-1]["text"] = f"{grouped_actions[-1]['text']} {block['text']}"
                    grouped_actions[-1]["y1"] = max(grouped_actions[-1]["y1"], block["y1"])
                    grouped_actions[-1]["x1"] = max(grouped_actions[-1]["x1"], block["x1"])
                    continue
                grouped_actions.append(dict(block))

            steps: list[dict[str, Any]] = []
            for action in grouped_actions:
                text = _normalize_step_text(action["text"])
                if len(text) < 12:
                    continue
                actor = _nearest_actor_for_action(action, blocks, width)
                steps.append({
                    "step_order": len(steps) + 1,
                    "actor": actor,
                    "action_text": text,
                    "next_step_order": len(steps) + 2,
                    "needs_review": False,
                })
            if steps:
                steps[-1]["next_step_order"] = None

            decision_points = _extract_layout_decisions(blocks)
            related_documents = _extract_layout_documents(blocks, width)
            first_action = steps[0]["action_text"] if steps else ""
            final_outcome = steps[-1]["action_text"] if steps else ""
            confidence = 0.93 if len(steps) >= 4 else 0.72 if len(steps) >= 2 else 0.45
            summary = (
                f"{title} süreci '{first_action}' adımıyla başlar ve '{final_outcome}' adımıyla tamamlanır."
                if first_action and final_outcome
                else f"{title} için PyMuPDF layout extraction sınırlı adım çıkardı."
            )
            return {
                "workflow_summary": summary,
                "first_action_for_student": first_action,
                "final_outcome": final_outcome,
                "steps": steps,
                "related_documents": related_documents,
                "decision_points": decision_points,
                "confidence_score": confidence,
                "needs_review": confidence < 0.75,
                "extraction_method": "pymupdf_layout",
                "raw_text": raw_text,
            }
        except Exception as exc:  # noqa: BLE001 - diğer extraction yolları çalışsın
            logger.warning("PyMuPDF layout extraction başarısız: %s", exc)
            return None

    @staticmethod
    def extract_with_ollama_vision(
        title: str,
        pdf_bytes: bytes,
        ollama_url: str | None,
        ollama_model: str | None,
    ) -> dict[str, Any] | None:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF yüklü değil; Ollama vision extraction atlandı.")
            return None

        settings = get_settings()
        base_url = (ollama_url or settings.OLLAMA_URL).rstrip("/")
        model = ollama_model or settings.OLLAMA_MODEL
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
            prompt = (
                "Bu MDBF iş akış şemasını JSON olarak çıkar. "
                f"Başlık: {title}. Alanlar: workflow_summary, first_action_for_student, "
                "final_outcome, steps[{step_order, actor, action_text, next_step_order, needs_review}], "
                "related_documents[], decision_points[], confidence_score, needs_review. "
                "Yalnız geçerli JSON döndür."
            )
            response = requests.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                    "format": "json",
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("response") or ""
            parsed = json.loads(content)
            return _coerce_ai_result(parsed)
        except Exception as exc:  # noqa: BLE001 - deterministic fallback şart
            logger.warning("Ollama vision extraction başarısız: %s", exc)
            return None

    @staticmethod
    def build_validation_report(
        workflows: list[dict[str, Any]],
        forms: list[dict[str, Any]],
        mapping_count: int,
    ) -> dict[str, Any]:
        workflow_status = [
            {
                "process_key": workflow["process_key"],
                "title": workflow["title"],
                "pdf_url": workflow["pdf_url"],
                "http_status": workflow.get("pdf_http_status"),
                "checksum": workflow.get("pdf_checksum"),
                "confidence_score": workflow.get("confidence_score"),
                "needs_review": workflow.get("needs_review"),
            }
            for workflow in workflows
        ]
        form_status = [
            {
                "form_name": form["form_name"],
                "download_url": form["download_url"],
                "http_status": form.get("http_status"),
                "checksum": form.get("checksum"),
                "process_key": form.get("process_key"),
            }
            for form in forms
        ]
        needs_review = [
            workflow["process_key"]
            for workflow in workflows
            if workflow.get("needs_review")
        ]
        return {
            "unit_code": UNIT_CODE,
            "workflow_found_count": len(workflows),
            "workflow_expected_count": len(WORKFLOW_TARGETS),
            "form_found_count": len(forms),
            "mapping_count": mapping_count,
            "mapping_success_rate": mapping_count / len(WORKFLOW_TARGETS) if WORKFLOW_TARGETS else 0,
            "workflows": workflow_status,
            "forms": form_status,
            "needs_review": needs_review,
        }

    @staticmethod
    def to_documents(workflows: list[dict[str, Any]], forms: list[dict[str, Any]]) -> list[Document]:
        now = utc_now()
        documents: list[Document] = []
        for workflow in workflows:
            form_lines = [
                f"- {form_name}"
                for form_name in workflow.get("mapped_form_names", [])
            ]
            steps = workflow.get("steps") or []
            step_lines = [
                f"{step['step_order']}. {step.get('action_text', '')}"
                for step in steps
            ]
            content = "\n".join([
                workflow.get("workflow_summary") or workflow["title"],
                "",
                "Süreç adımları:",
                *step_lines,
                "",
                "İlgili formlar:",
                *(form_lines or ["- Resmi kaynakta bu süreç için doğrudan form bulunmadı."]),
                "",
                f"Kaynak PDF: {workflow['pdf_url']}",
            ]).strip()
            documents.append(Document(
                content=content,
                meta={
                    "category": "ogrenci_isleri",
                    "subcategory": workflow["process_key"],
                    "source_url": workflow["pdf_url"],
                    "source_public_url": workflow["pdf_url"],
                    "source_type": "pdf",
                    "source_id": f"mdbf_workflow:{workflow['process_key']}",
                    "last_updated": now,
                    "title": workflow["title"],
                    "doc_kind": "workflow",
                    "language": "tr",
                    "department": UNIT_NAME,
                    "unit_code": UNIT_CODE,
                    "unit_name": UNIT_NAME,
                    "unit_type": UNIT_TYPE,
                    "process_key": workflow["process_key"],
                    "contact_unit": "MDBF Öğrenci İşleri",
                    "contact_info": "mdbf@gibtu.edu.tr",
                    "metadata_version": METADATA_VERSION,
                },
            ))

        for form in forms:
            documents.append(Document(
                content=f"{form['form_name']} indirme bağlantısı: {form['download_url']}",
                meta={
                    "category": "ogrenci_isleri",
                    "subcategory": form.get("process_key") or "unit_form",
                    "source_url": form["download_url"],
                    "source_public_url": form["download_url"],
                    "source_type": "pdf" if form["file_extension"] == "pdf" else "web",
                    "source_id": f"mdbf_form:{form['normalized_form_name']}",
                    "last_updated": now,
                    "title": form["form_name"],
                    "doc_kind": "form",
                    "language": "tr",
                    "department": UNIT_NAME,
                    "unit_code": UNIT_CODE,
                    "unit_name": UNIT_NAME,
                    "unit_type": UNIT_TYPE,
                    "process_key": form.get("process_key"),
                    "contact_unit": "MDBF Öğrenci İşleri",
                    "contact_info": "mdbf@gibtu.edu.tr",
                    "metadata_version": METADATA_VERSION,
                },
            ))
        return documents


def _looks_like_action_line(line: str) -> bool:
    lower = line.casefold()
    if len(line) < 18:
        return False
    if any(marker.casefold() in lower for marker in FOOTER_MARKERS):
        return False
    if "doküman kodu" in lower or "sayfa" in lower or "iş akış adımları" in lower:
        return False
    if lower.startswith(("gaziantep", "mühendislik ve doğa", "başla")):
        return False
    return line.endswith(".") or any(verb in lower for verb in WORKFLOW_ACTION_VERBS)


def _is_flow_terminal(text: str) -> bool:
    normalized = normalize_for_match(text)
    return normalized in {"basla", "baslama", "bitis", "bitiş"} or normalized.startswith("dokuman kodu")


def _is_document_only_text(text: str) -> bool:
    normalized = normalize_for_match(text)
    if any(token in normalized for token in (
        "gibtu on lisans",
        "yonetmeligi",
        "yonetim kurulu karari",
        "sinav takvimi",
        "ilgili dokuman",
    )):
        return True
    if normalized in {"uygun", "uygun gorulmedi", "evet", "hayir"}:
        return True
    return False


def _is_non_action_text(text: str) -> bool:
    normalized = normalize_for_match(text)
    if any(token in normalized for token in (
        "is akis adimlari",
        "is akisi adimlari",
        "sorumlu ilgili dokumanlar",
        "birim kalite",
        "kalite gelistirme",
        "akreditasyon",
        "koordinatorlugu",
        "fakultesi dekanligi",
        "hazirlayan",
        "kontrol eden",
        "onaylayan",
    )):
        return True
    return False


def _normalize_step_text(text: str) -> str:
    text = re.sub(r"\bSorumlu:\s*[^.]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text


def _nearest_actor_for_action(action: dict[str, Any], blocks: list[dict[str, Any]], width: float) -> str | None:
    y_mid = (action["y0"] + action["y1"]) / 2
    candidates = []
    for block in blocks:
        if block["x0"] <= width * 0.45:
            continue
        if block["x0"] >= width * 0.68 and _is_document_only_text(block["text"]):
            continue
        distance = abs(((block["y0"] + block["y1"]) / 2) - y_mid)
        if distance <= 34:
            candidates.append((distance, block["text"]))
    if not candidates:
        return _detect_actor(action["text"])
    candidates.sort(key=lambda item: item[0])
    actor_text = candidates[0][1]
    return _detect_actor(actor_text) or actor_text


def _extract_layout_decisions(blocks: list[dict[str, Any]]) -> list[str]:
    decisions: list[str] = []
    for block in blocks:
        normalized = normalize_for_match(block["text"])
        if normalized in {"uygun", "uygun goruldu", "uygun gorulmedi", "evet", "hayir"}:
            decisions.append(block["text"])
    return _dedupe_preserve_order(decisions)


def _extract_layout_documents(blocks: list[dict[str, Any]], width: float) -> list[str]:
    documents: list[str] = []
    for block in blocks:
        if block["x0"] < width * 0.60:
            continue
        lower = block["text"].casefold()
        if any(hint in lower for hint in DOCUMENT_HINTS):
            documents.append(block["text"])
    return _dedupe_preserve_order(documents)


def _detect_actor(line: str) -> str | None:
    lower = line.casefold()
    actor_rules = (
        ("Öğrenci İşleri Daire Başkanlığı", "öğrenci işleri"),
        ("MDBF Sekreterliği", "sekreter"),
        ("Bölüm Başkanlığı", "bölüm"),
        ("Öğrenci", "öğrenci"),
        ("Fakülte Yönetim Kurulu", "yönetim kurulu"),
    )
    for actor, needle in actor_rules:
        if needle in lower:
            return actor
    return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = normalize_for_match(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _coerce_ai_result(parsed: dict[str, Any]) -> dict[str, Any]:
    steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
    clean_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        action_text = str(step.get("action_text") or "").strip()
        if not action_text:
            continue
        clean_steps.append({
            "step_order": int(step.get("step_order") or index),
            "actor": step.get("actor"),
            "action_text": action_text,
            "next_step_order": step.get("next_step_order"),
            "needs_review": bool(step.get("needs_review", False)),
        })

    confidence = parsed.get("confidence_score", 0.7)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.7

    return {
        "workflow_summary": str(parsed.get("workflow_summary") or "").strip(),
        "first_action_for_student": str(parsed.get("first_action_for_student") or "").strip(),
        "final_outcome": str(parsed.get("final_outcome") or "").strip(),
        "steps": clean_steps,
        "related_documents": parsed.get("related_documents") if isinstance(parsed.get("related_documents"), list) else [],
        "decision_points": parsed.get("decision_points") if isinstance(parsed.get("decision_points"), list) else [],
        "confidence_score": max(0.0, min(1.0, confidence)),
        "needs_review": bool(parsed.get("needs_review", confidence < 0.75)),
    }
