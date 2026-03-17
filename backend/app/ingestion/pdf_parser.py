"""
UniChat Backend — PDF Parser
pdfplumber ile PDF → metin dönüşümü.

Özellikler:
  - Sayfa bazlı metin çıkarma (tablo desteği dahil)
  - Yönetmelik PDF'leri için madde bazlı bölme
  - Sayfa bazlı hata toleransı (bozuk sayfa tüm PDF'i durdurmaz)
  - Dizin tarama (recursive glob)
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pdfplumber
from haystack import Document

logger = logging.getLogger(__name__)


# ── Yardımcı Fonksiyonlar ──

def _title_from_filename(path: str) -> str:
    """Dosya adından okunabilir başlık üretir.

    Örn: 'egitim_yonetmeligi.pdf' → 'Egitim Yonetmeligi'
    """
    stem = Path(path).stem                       # 'egitim_yonetmeligi'
    return stem.replace("_", " ").replace("-", " ").title()


def _source_id_from_filename(path: str) -> str:
    """Dosya adından sabit source_id üretir.

    Örn: 'Eğitim Yönetmeliği.pdf' → 'egitim_yonetmeligi_pdf'
    """
    stem = Path(path).stem.lower()
    # Türkçe karakterleri ASCII'ye dönüştür
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    slug = stem.translate(tr_map)
    slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
    return f"{slug}_pdf"


def _file_last_modified(path: str) -> str:
    """Dosya son değişiklik tarihini ISO 8601 formatında döndürür."""
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except OSError:
        return datetime.now().strftime("%Y-%m-%d")


def _split_by_article(text: str) -> List[Tuple[str, str]]:
    """Yönetmelik metnini madde bazlı böler.

    "Madde 1 –", "MADDE 2 -", "Madde 12/A -" gibi kalıpları tanır.
    Her madde (başlık, içerik) tuple'ı olarak döner.

    Returns:
        Liste boşsa, madde tespit edilemedi demektir.
    """
    # Madde başlangıcını yakalayan regex
    pattern = re.compile(
        r'(?i)(madde\s+\d+(?:/[A-Za-zÇçĞğİıÖöŞşÜü]+)?\s*[\-–—\.])',
        re.UNICODE,
    )

    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return []

    articles: List[Tuple[str, str]] = []

    # Madde öncesi giriş bölümü (varsa)
    preamble = text[: matches[0].start()].strip()
    if preamble and len(preamble) > 30:
        articles.append(("Giriş", preamble))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        article_text = text[start:end].strip()

        # Başlığı ilk satırdan çıkar
        first_line = article_text.split("\n", 1)[0].strip()
        articles.append((first_line, article_text))

    return articles


# ── Ana Parse Fonksiyonları ──

def parse_pdf(
    path: str,
    doc_kind: str = "genel",
    **meta,
) -> List[Document]:
    """Tek PDF dosyasını parse edip Document listesine dönüştürür.

    Args:
        path: PDF dosyasının yolu.
        doc_kind: Belge türü (yonetmelik, duyuru, tanitim vb.)
        **meta: Ek metadata alanları.

    Returns:
        Document listesi.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF dosyası bulunamadı: {path}")

    title = meta.pop("title", None) or _title_from_filename(path)
    source_id = meta.pop("source_id", None) or _source_id_from_filename(path)
    last_updated = meta.pop("last_updated", None) or _file_last_modified(path)
    logger.info("PDF parse ediliyor: %s (doc_kind=%s)", path, doc_kind)

    # ── Sayfa bazlı metin çıkarma ──
    pages_text: List[str] = []
    failed_pages: List[int] = []

    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            logger.info("  PDF toplam sayfa: %d", total_pages)

            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                    if text.strip():
                        pages_text.append(text)
                    else:
                        logger.debug("  Sayfa %d: boş metin, atlanıyor.", page_num)
                except Exception as e:
                    failed_pages.append(page_num)
                    logger.warning(
                        "  ⚠️ Sayfa %d okunamadı: %s — atlanıyor.", page_num, e
                    )
    except Exception as e:
        logger.error("PDF dosyası açılamadı: %s — Hata: %s", path, e)
        return []

    if failed_pages:
        logger.warning(
            "  %d sayfa okunamadı (sayfa no: %s), geri kalanı işlendi.",
            len(failed_pages),
            failed_pages,
        )

    if not pages_text:
        logger.warning("PDF'den metin çıkarılamadı: %s", path)
        return []

    full_text = "\n\n".join(pages_text)

    # ── Madde bazlı bölme (yonetmelik / yonerge) ──
    if doc_kind in ("yonetmelik", "yonerge"):
        articles = _split_by_article(full_text)
        if articles:
            logger.info("  %d madde tespit edildi.", len(articles))
            documents = []
            for i, (article_title, article_content) in enumerate(articles):
                doc_meta = {
                    "title": f"{title} — {article_title}",
                    "doc_kind": doc_kind,
                    "source_type": "pdf",
                    "source_url": path,
                    "source_id": f"{source_id}_madde_{i}",
                    "last_updated": last_updated,
                    "page_count": total_pages,
                    **meta,
                }
                documents.append(
                    Document(content=article_content, meta=doc_meta)
                )
            return documents
        else:
            logger.info("  Madde kalıbı bulunamadı, tek belge olarak devam.")

    # ── Tek belge olarak dön ──
    doc_meta = {
        "title": title,
        "doc_kind": doc_kind,
        "source_type": "pdf",
        "source_url": path,
        "source_id": source_id,
        "last_updated": last_updated,
        "page_count": total_pages,
        **meta,
    }
    return [Document(content=full_text, meta=doc_meta)]


def parse_pdf_directory(
    directory: str,
    doc_kind: str = "genel",
    **meta,
) -> List[Document]:
    """Dizindeki tüm PDF'leri (alt dizinler dahil) parse eder.

    Args:
        directory: PDF dizininin yolu.
        doc_kind: Tüm PDF'lere uygulanacak belge türü.
        **meta: Ortak metadata.

    Returns:
        Tüm PDF'lerden elde edilen Document listesi.
    """
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        raise NotADirectoryError(f"Dizin bulunamadı: {directory}")

    pdf_files = sorted(Path(directory).rglob("*.pdf"))
    if not pdf_files:
        logger.warning("Dizinde PDF dosyası bulunamadı: %s", directory)
        return []

    logger.info("%d PDF dosyası bulundu (alt dizinler dahil).", len(pdf_files))

    all_documents: List[Document] = []
    for pdf_path in pdf_files:
        try:
            docs = parse_pdf(str(pdf_path), doc_kind=doc_kind, **meta)
            all_documents.extend(docs)
            logger.info("  ✅ %s → %d belge", pdf_path.name, len(docs))
        except Exception as e:
            logger.error("  ❌ %s → Hata: %s — atlanıyor.", pdf_path.name, e)

    logger.info(
        "Dizin parse tamamlandı: %d PDF → %d belge.",
        len(pdf_files),
        len(all_documents),
    )
    return all_documents
