"""Aday öğrenci sayfası #ogrenim bölümü için dar kapsamlı dry-run çıkarımı."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scrapers._encoding_fix  # noqa: F401
from app.repositories.program_catalog_repository import ProgramCatalogRepository
from app.services.program_catalog_service import ProgramCatalogService
from scrapers.program_catalog_scraper import normalize_for_match, normalize_program_name


SOURCE_URL = "https://adayogrenci.gibtu.edu.tr/#ogrenim"
FETCH_URL = "https://adayogrenci.gibtu.edu.tr/Default.aspx"
SCRAPER_NAME = "candidate_ogrenim_extractor"
METADATA_VERSION = "candidate_ogrenim.v1"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "reports" / "candidate_ogrenim"
DETAIL_TEXT_MIN_LENGTH = 80

DB_FIRST_EXAMPLE_QUESTIONS = (
    "Fizyoterapi var mı?",
    "Hukuk var mı?",
    "Aday öğrenci sayfasında ön lisans programları neler?",
    "Mütercim Tercümanlık İngilizce var mı?",
    "SHMYO programları neler?",
)


SECTION_LEVELS = (
    ("yukseklisans_listesi", "graduate", "Lisansüstü"),
    ("lisans_listesi", "undergraduate", "Lisans"),
    ("onlisans_listesi", "associate", "Ön lisans"),
)


UNIT_ALIASES = {
    "saglik hizmetleri myo": "Sağlık Hizmetleri Meslek Yüksekokulu",
    "teknik bilimler myo": "Teknik Bilimler Meslek Yüksekokulu",
    "yabanci diller y o": "Yabancı Diller Yüksekokulu",
}


PROGRAM_ALIAS_SUGGESTIONS = {
    "bilgisayar muhendisligi": ["BM", "bilgisayar müh", "bilgisayar muh"],
    "elektrik elektronik muhendisligi": ["EEM", "elektrik elektronik", "elektrik-elektronik"],
    "endustri muhendisligi": ["endüstri müh", "endustri muh"],
    "insaat muhendisligi": ["inşaat müh", "insaat muh"],
    "ebelik": ["ebelik"],
    "hemsirelik": ["hemşirelik", "hemsirelik"],
    "gastronomi ve mutfak sanatlari": ["gastronomi"],
    "bilgisayar programciligi": ["bilgisayar program", "BP"],
    "tibbi laboratuvar teknikleri": ["tıbbi lab", "tibbi lab", "TLT"],
    "ilk ve acil yardim": ["ilk acil", "paramedik"],
    "yasli bakimi": ["yaşlı bakımı", "yasli bakimi"],
}


@dataclass
class CandidateOgrenimRecord:
    record_id: str
    raw_visible_name: str
    program_name: str
    normalized_name: str
    parent_unit: str | None
    normalized_parent_unit: str | None
    education_level: str
    education_label: str
    education_language: str | None
    duration: str | None
    program_type: str
    description: str | None
    program_card_link: str | None
    source_url: str
    detail_url: str | None = None
    detail_http_status: int | None = None
    detail_processed: bool = False
    detail_snapshot_path: str | None = None
    description_missing: bool = True
    source_label: str = "candidate_page_source"
    is_authoritative_active_program: bool = False
    aliases: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_text(value: Any) -> str:
    text = " ".join(str(value or "").replace("\xa0", " ").split())
    return text.strip(" \t\r\n-|")


def parse_name_duration(raw_name: str) -> tuple[str, str | None]:
    text = clean_text(raw_name)
    if "|" not in text:
        return text, None
    name, duration = text.rsplit("|", 1)
    return clean_text(name), clean_text(duration) or None


def infer_language(name: str) -> str | None:
    normalized = normalize_for_match(name)
    if "arapca" in normalized:
        return "Arapça"
    if "ingilizce" in normalized:
        return "İngilizce"
    if "turkce" in normalized:
        return "Türkçe"
    return None


def infer_unit_type(unit_name: str | None) -> str | None:
    normalized = normalize_for_match(unit_name)
    if not normalized:
        return None
    if "myo" in normalized or "meslek yuksekokulu" in normalized:
        return "vocational_school"
    if "fakulte" in normalized:
        return "faculty"
    if "yuksekokul" in normalized or normalized.endswith("y o"):
        return "school"
    if "enstitu" in normalized:
        return "institute"
    return None


def canonical_unit_name(unit_name: str | None) -> str | None:
    if not unit_name:
        return None
    cleaned = clean_text(unit_name)
    normalized = normalize_for_match(cleaned)
    return UNIT_ALIASES.get(normalized, cleaned)


def program_type_for(level: str, parent_unit: str | None, has_child_programs: bool) -> str:
    unit_type = infer_unit_type(parent_unit)
    if level == "associate":
        return "candidate_listed_associate_program"
    if level == "graduate":
        return "graduate_candidate"
    if level == "undergraduate" and not has_child_programs and unit_type == "faculty":
        return "candidate_undergraduate_faculty_card"
    if unit_type == "school":
        return "candidate_listed_school_program"
    if unit_type == "faculty" and has_child_programs:
        return "candidate_listed_undergraduate_program"
    return "candidate_listed_program_or_unit_card"


def alias_suggestions(program_name: str) -> list[str]:
    normalized = normalize_program_name(program_name)
    aliases = set(PROGRAM_ALIAS_SUGGESTIONS.get(normalized, []))
    language = infer_language(program_name)
    language_alias = {
        "Arapça": "arapça",
        "İngilizce": "ingilizce",
        "Türkçe": "türkçe",
    }.get(language or "")
    if language and "mutercim tercumanlik" in normalized:
        aliases.add(f"{language_alias} mütercim tercümanlık")
        aliases.add(f"{language_alias} tercümanlık")
    if language and "islami ilimler" in normalized:
        aliases.add(f"islami ilimler {language_alias}")
    aliases.add(program_name)
    return sorted(alias for alias in aliases if alias)


def missing_fields_for(record: CandidateOgrenimRecord) -> list[str]:
    missing = []
    if not record.parent_unit:
        missing.append("parent_unit")
    if not record.education_language:
        missing.append("education_language")
    if not record.duration:
        missing.append("duration")
    if not record.description:
        missing.append("description")
    if not record.program_card_link:
        missing.append("program_card_link")
    return missing


def fetch_url(url: str, timeout: int) -> tuple[str, int]:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "UniChatCandidateOgrenimExtractor/1.0"},
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text, int(response.status_code)


def fetch_html(timeout: int) -> tuple[str, int]:
    return fetch_url(FETCH_URL, timeout)


def extract_records(html: str) -> tuple[str, list[CandidateOgrenimRecord], list[dict[str, Any]], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    ogrenim = soup.select_one("#ogrenim")
    if not ogrenim:
        return "", [], [], ["#ogrenim bölümü bulunamadı."]

    records: list[CandidateOgrenimRecord] = []
    duplicates: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: dict[str, CandidateOgrenimRecord] = {}

    for section_class, level, label in SECTION_LEVELS:
        section = ogrenim.select_one(f"section.{section_class}")
        if not section:
            warnings.append(f"{section_class} bölümü bulunamadı.")
            continue
        for card in section.select(".faculty-card"):
            raw_title = clean_text(card.select_one(".faculty-card-title").get_text(" ", strip=True) if card.select_one(".faculty-card-title") else "")
            if not raw_title:
                warnings.append(f"{section_class} içinde başlıksız kart atlandı.")
                continue
            card_name, card_duration = parse_name_duration(raw_title)
            parent_unit = canonical_unit_name(card_name)
            child_items = card.select(".faculty-card-list li")
            child_records = []
            for item in child_items:
                link = item.find("a", href=True)
                raw_child = clean_text(item.get_text(" ", strip=True))
                if not raw_child:
                    continue
                child_name, child_duration = parse_name_duration(raw_child)
                child_records.append((raw_child, child_name, child_duration, link))

            if child_records:
                for raw_child, child_name, child_duration, link in child_records:
                    records.append(build_record(
                        raw_visible_name=raw_child,
                        program_name=child_name,
                        parent_unit=parent_unit,
                        level=level,
                        label=label,
                        duration=child_duration or card_duration,
                        link=link,
                        has_child_programs=True,
                    ))
            else:
                records.append(build_record(
                    raw_visible_name=raw_title,
                    program_name=card_name,
                    parent_unit=None if level == "graduate" else parent_unit,
                    level=level,
                    label=label,
                    duration=card_duration,
                    link=card.find("a", href=True),
                    has_child_programs=False,
                ))

    unique_records: list[CandidateOgrenimRecord] = []
    for record in records:
        key = "|".join([
            record.normalized_name,
            record.education_level,
            record.normalized_parent_unit or "",
        ])
        if key in seen:
            duplicates.append({
                "canonical_key": key,
                "kept": seen[key].raw_visible_name,
                "duplicate": record.raw_visible_name,
            })
            continue
        seen[key] = record
        unique_records.append(record)

    return str(ogrenim), unique_records, duplicates, warnings


def build_record(
    raw_visible_name: str,
    program_name: str,
    parent_unit: str | None,
    level: str,
    label: str,
    duration: str | None,
    link: Tag | None,
    has_child_programs: bool,
) -> CandidateOgrenimRecord:
    normalized_name = normalize_program_name(program_name)
    normalized_parent = normalize_for_match(parent_unit) if parent_unit else None
    link_url = urljoin(FETCH_URL, str(link.get("href"))) if link else None
    record = CandidateOgrenimRecord(
        record_id=sha256_text("|".join([normalized_name, level, normalized_parent or ""]))[:16],
        raw_visible_name=raw_visible_name,
        program_name=program_name,
        normalized_name=normalized_name,
        parent_unit=parent_unit,
        normalized_parent_unit=normalized_parent,
        education_level=level,
        education_label=label,
        education_language=infer_language(program_name),
        duration=duration,
        program_type=program_type_for(level, parent_unit, has_child_programs),
        description=None,
        program_card_link=link_url,
        detail_url=link_url,
        source_url=SOURCE_URL,
        aliases=alias_suggestions(program_name),
    )
    if raw_visible_name.count("(") != raw_visible_name.count(")"):
        record.parse_warnings.append("Parantez dengesi bozuk veya ad kırpılmış olabilir.")
    record.missing_fields = missing_fields_for(record)
    return record


def strip_noise_nodes(soup: BeautifulSoup) -> None:
    noise_selectors = [
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
        ".social",
        ".menu",
        ".navbar",
        ".topbar",
        ".footer",
        ".header",
        ".copyright",
        ".collapsible",
        "#manset",
        ".manset",
        ".duyuru_title_field",
        "[id*='Duyuru']",
        "[id*='Haber']",
        "[id*='Manset']",
        "[class*='duyuru']",
        "[class*='haber']",
        "[class*='manset']",
    ]
    for selector in noise_selectors:
        for node in soup.select(selector):
            node.decompose()


def normalize_detail_text(text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    cleaned_lines = [line for line in lines if line]
    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text)
    return clean_text(text)


def extract_detail_description(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    strip_noise_nodes(soup)
    selectors = [
        "div.birim_safya_body_detay",
        "div.birim_sayfa_body_detay",
        "div.birim_sayfa_detay",
        "div.sayfa_detay",
        "div.sayfa-icerik-detay",
        "div.icerik-detay",
        "[id*='lbl_sayfa_icerik']",
        "[id*='lbl_icerik_metin']",
        "[id*='lbl_metin']",
        "[id*='lbl_tanitim']",
        "[id*='lbl_hakkimizda']",
        ".sayfa_icerik_detay",
        ".sayfa-icerik",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_detail_text(node.get_text("\n", strip=True))
        if len(text) >= DETAIL_TEXT_MIN_LENGTH:
            return text
    return None


def description_is_relevant_to_record(text: str, record: CandidateOgrenimRecord) -> bool:
    normalized_text = normalize_for_match(text)
    base_program_name = re.sub(r"\([^)]*\)", "", record.program_name)
    normalized_program = normalize_for_match(base_program_name)
    normalized_parent = normalize_for_match(record.parent_unit)
    candidates = [normalized_program, normalized_parent]
    return any(candidate and len(candidate) >= 5 and candidate in normalized_text for candidate in candidates)


def update_record_missing_fields(record: CandidateOgrenimRecord) -> None:
    record.description_missing = not bool(record.description)
    record.missing_fields = missing_fields_for(record)


def enrich_records_with_detail_pages(
    records: list[CandidateOgrenimRecord],
    output_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    details_dir = output_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    unique_urls = []
    seen_urls = set()
    for record in records:
        if not record.detail_url or record.detail_url in seen_urls:
            continue
        seen_urls.add(record.detail_url)
        unique_urls.append(record.detail_url)

    detail_results: dict[str, dict[str, Any]] = {}
    for url in unique_urls:
        result: dict[str, Any] = {
            "url": url,
            "processed": False,
            "http_status": None,
            "snapshot_path": None,
            "description_found": False,
            "error": None,
        }
        try:
            html, status_code = fetch_url(url, timeout)
            detail_snapshot_id = sha256_text(html)[:24]
            detail_path = details_dir / f"candidate_ogrenim_detail_{detail_snapshot_id}.html"
            detail_path.write_text(html, encoding="utf-8")
            description = extract_detail_description(html)
            result.update({
                "processed": True,
                "http_status": status_code,
                "snapshot_path": str(detail_path),
                "description": description,
                "description_found": bool(description),
            })
        except requests.RequestException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        detail_results[url] = result

    for record in records:
        if not record.detail_url:
            update_record_missing_fields(record)
            continue
        detail = detail_results.get(record.detail_url)
        if not detail:
            update_record_missing_fields(record)
            continue
        record.detail_processed = bool(detail.get("processed"))
        record.detail_http_status = detail.get("http_status")
        record.detail_snapshot_path = detail.get("snapshot_path")
        if detail.get("description") and description_is_relevant_to_record(str(detail["description"]), record):
            record.description = str(detail["description"])
        elif detail.get("error"):
            record.parse_warnings.append(f"Detay sayfası alınamadı: {detail['error']}")
        update_record_missing_fields(record)

    return {
        "detail_link_record_count": sum(1 for record in records if record.detail_url),
        "detail_unique_url_count": len(unique_urls),
        "detail_processed_record_count": sum(
            1 for record in records if record.detail_url and record.detail_processed
        ),
        "detail_processed_unique_url_count": sum(
            1 for result in detail_results.values() if result.get("processed")
        ),
        "detail_results": [
            {
                "url": result["url"],
                "processed": result["processed"],
                "http_status": result["http_status"],
                "description_found": result["description_found"],
                "error": result["error"],
            }
            for result in detail_results.values()
        ],
    }


def build_report(output_dir: Path, timeout: int) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html, status_code = fetch_html(timeout)
    snapshot_id = sha256_text(html)[:24]
    raw_path = output_dir / f"candidate_ogrenim_raw_{snapshot_id}.html"
    raw_path.write_text(html, encoding="utf-8")

    section_html, records, duplicates, warnings = extract_records(html)
    section_path = output_dir / f"candidate_ogrenim_section_{snapshot_id}.html"
    section_path.write_text(section_html, encoding="utf-8")
    detail_summary = enrich_records_with_detail_pages(records, output_dir, timeout)

    missing_summary: dict[str, int] = {}
    parse_warnings = []
    for record in records:
        for field_name in record.missing_fields:
            missing_summary[field_name] = missing_summary.get(field_name, 0) + 1
        for warning in record.parse_warnings:
            parse_warnings.append({"record": record.raw_visible_name, "warning": warning})

    report = {
        "success": bool(records),
        "dry_run": True,
        "db_write_requested": False,
        "db_write_executed": False,
        "production_db_write_attempted": False,
        "scraper_name": SCRAPER_NAME,
        "metadata_version": METADATA_VERSION,
        "source_url": SOURCE_URL,
        "fetch_url": FETCH_URL,
        "http_status": status_code,
        "fetched_at": utc_now(),
        "snapshot_id": snapshot_id,
        "raw_snapshot_path": str(raw_path),
        "section_snapshot_path": str(section_path),
        "record_count": len(records),
        "detail_link_record_count": detail_summary["detail_link_record_count"],
        "detail_unique_url_count": detail_summary["detail_unique_url_count"],
        "detail_processed_record_count": detail_summary["detail_processed_record_count"],
        "detail_processed_unique_url_count": detail_summary["detail_processed_unique_url_count"],
        "description_found_count": sum(1 for record in records if record.description),
        "description_missing_count": sum(1 for record in records if record.description_missing),
        "duplicates": duplicates,
        "duplicate_count": len(duplicates),
        "missing_summary": missing_summary,
        "parse_warnings": parse_warnings,
        "detail_results": detail_summary["detail_results"],
        "warnings": warnings,
        "records": [asdict(record) for record in records],
        "chatbot_examples": build_chatbot_examples(records),
    }
    (output_dir / "candidate_ogrenim_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def load_report_for_db_write(output_dir: Path) -> dict[str, Any]:
    report_path = output_dir / "candidate_ogrenim_report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"DB write için önce dry-run raporu üretilmeli: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def build_db_first_example_answers(repository: ProgramCatalogRepository) -> list[dict[str, Any]]:
    service = ProgramCatalogService(repository)
    examples = []
    for question in DB_FIRST_EXAMPLE_QUESTIONS:
        answer = service.answer_chat_query(question)
        examples.append({
            "question": question,
            "passed": bool(
                answer
                and answer.get("metadata", {}).get("db_first") is True
                and answer.get("metadata", {}).get("rag_fallback_used") is False
                and "Aday öğrenci Öğrenim sayfas" in answer.get("response", "")
            ),
            "intent": answer.get("metadata", {}).get("intent") if answer else None,
            "response": answer.get("response") if answer else None,
        })
    return examples


def write_db_from_existing_report(output_dir: Path) -> dict[str, Any]:
    report = load_report_for_db_write(output_dir)
    repository = ProgramCatalogRepository()
    target = repository.database_target_summary()
    print(f"DB hedefi: {target.get('masked_url')}")
    import_summary = repository.import_candidate_ogrenim_report(report)
    examples = build_db_first_example_answers(repository)
    import_summary["chatbot_db_first_examples"] = examples
    import_summary["chatbot_db_first_examples_passed"] = sum(1 for item in examples if item.get("passed"))
    import_summary_path = output_dir / "candidate_ogrenim_import_summary.json"
    import_summary_path.write_text(
        json.dumps(import_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return import_summary


def build_chatbot_examples(records: list[CandidateOgrenimRecord]) -> list[dict[str, str]]:
    by_level: dict[str, list[CandidateOgrenimRecord]] = {}
    for record in records:
        by_level.setdefault(record.education_level, []).append(record)
    examples = []
    if by_level.get("undergraduate"):
        examples.append({
            "question": "Aday öğrenci sayfasında lisans programları neler?",
            "answer": "Aday öğrenci sayfasının Öğrenim bölümünde listelenen lisans kayıtları kaynak etiketiyle gösterilmelidir; bu tek başına kesin aktif program doğrulaması değildir.",
        })
    if by_level.get("associate"):
        examples.append({
            "question": "Aday öğrenci sayfasında ön lisans programları neler?",
            "answer": "Bu kaynakta ön lisans kayıtları MYO kartları altında listelenir; sayfada olmayan programlar için yoktur denmez.",
        })
    examples.append({
        "question": "Fizyoterapi var mı?",
        "answer": "Aday öğrenci Öğrenim bölümünde görünen kayıtlar içinde Fizyoterapi ayrı kaynak kaydı olarak listelenir; Fizyoterapi ve Rehabilitasyon ile otomatik birleştirilmez.",
    })
    return examples


def main() -> int:
    parser = argparse.ArgumentParser(description="Aday öğrenci #ogrenim dar kapsamlı dry-run çıkarımı")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Rapor klasörü")
    parser.add_argument("--timeout", type=int, default=15, help="Tek URL timeout saniyesi")
    parser.add_argument("--write-db", action="store_true", help="Mevcut candidate_ogrenim_report.json dosyasını DB'ye upsert et")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.write_db:
        import_summary = write_db_from_existing_report(output_dir)
        print("Aday öğrenci #ogrenim DB import tamamlandı")
        print(f"Yazılan kayıt: {import_summary['records_written']}")
        print(f"Yeni/Güncellenen: {import_summary['records_inserted']}/{import_summary['records_updated']}")
        print(f"Duplicate: {import_summary['duplicate_count']}")
        print(f"Description missing: {import_summary['description_missing_count']}/{import_summary['description_missing_expected']}")
        print(f"DB toplam candidate_page_ogrenim: {import_summary['candidate_page_ogrenim_total']}")
        print(f"DB write executed: {import_summary['db_write_executed']}")
        print(f"Rapor: {output_dir / 'candidate_ogrenim_import_summary.json'}")
        return 0

    report = build_report(output_dir, timeout=max(1, min(args.timeout, 30)))
    print("Aday öğrenci #ogrenim dry-run tamamlandı")
    print(f"Kaynak URL: {report['source_url']}")
    print(f"Kayıt sayısı: {report['record_count']}")
    print(f"Detay linki işlenen kayıt: {report['detail_processed_record_count']}/{report['detail_link_record_count']}")
    print(f"Açıklama bulunan/bulunmayan: {report['description_found_count']}/{report['description_missing_count']}")
    print(f"Duplicate: {report['duplicate_count']}")
    print(f"Parse warning: {len(report['parse_warnings'])}")
    print(f"DB write executed: {report['db_write_executed']}")
    print(f"Rapor: {output_dir / 'candidate_ogrenim_report.json'}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
