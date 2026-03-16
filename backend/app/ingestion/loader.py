"""
UniChat Backend — Ingestion Loader
Tüm veri girişi bu modülden geçer: JSON, PDF, scraper çıktısı.

Giriş noktaları:
    load_json_file()     — JSON dosyasından belge yükleme
    load_pdf_file()      — Tek PDF dosyası yükleme
    load_pdf_directory() — Dizindeki tüm PDF'leri toplu yükleme
    ingest_documents()   — Hazır Document listesini pipeline'a gönderme
"""

import hashlib
import json
import logging
import os
from pathlib import Path

from haystack import Document
from haystack.components.embedders import SentenceTransformersDocumentEmbedder
from haystack.document_stores.types import DuplicatePolicy
from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

from app.config import get_settings
from app.ingestion.validators import validate_documents

logger = logging.getLogger(__name__)


# ── Document Store (singleton) ──

_document_store: PgvectorDocumentStore | None = None
_embedder: SentenceTransformersDocumentEmbedder | None = None


def _get_document_store() -> PgvectorDocumentStore:
    """Config'den PgvectorDocumentStore döndürür (singleton)."""
    global _document_store
    if _document_store is None:
        settings = get_settings()
        _document_store = PgvectorDocumentStore(
            connection_string=Secret.from_env_var("DATABASE_URL"),
            table_name=settings.HAYSTACK_TABLE_NAME,
            embedding_dimension=settings.EMBEDDING_DIMENSION,
            keyword_index_name="unichat_keyword_index",
        )
    return _document_store


def _get_embedder() -> SentenceTransformersDocumentEmbedder:
    """Config'den embedder döndürür (singleton, warm_up yapılmış)."""
    global _embedder
    if _embedder is None:
        settings = get_settings()
        _embedder = SentenceTransformersDocumentEmbedder(
            model=settings.EMBEDDING_MODEL
        )
        _embedder.warm_up()
    return _embedder


def _generate_doc_id(content: str) -> str:
    """İçerikten SHA-256 hash ile deterministik ID üretir."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ── Ana Motor ──

def ingest_documents(
    documents: list[Document],
    policy: DuplicatePolicy = DuplicatePolicy.SKIP,
    dry_run: bool = False,
) -> int:
    """
    Belge listesini doğrula → ID ata → embed → veritabanına yaz.

    Bu, tüm veri girişinin geçtiği ortak pipeline motoru.

    Args:
        documents: Haystack Document listesi.
        policy: Duplicate politikası (SKIP veya OVERWRITE).
        dry_run: True ise veritabanına yazmadan rapor ver.

    Returns:
        Yazılan belge sayısı.
    """
    if not documents:
        logger.warning("Boş belge listesi, işlem atlanıyor.")
        return 0

    logger.info("Ingestion başlıyor: %d belge, policy=%s, dry_run=%s",
                len(documents), policy.name, dry_run)

    # 1. Doğrulama
    valid_docs = validate_documents(documents)
    if not valid_docs:
        logger.warning("Doğrulamadan geçen belge yok, işlem sonlandırılıyor.")
        return 0

    # 2. ID ataması (SHA-256)
    for doc in valid_docs:
        if not doc.id:
            doc.id = _generate_doc_id(doc.content)

    # 3. Dry-run modu
    if dry_run:
        logger.info("DRY-RUN: %d belge yüklenecek (veritabanına yazılmadı).", len(valid_docs))
        for i, doc in enumerate(valid_docs):
            meta_summary = {k: v for k, v in (doc.meta or {}).items()
                           if k in ("category", "doc_kind", "title")}
            logger.info("  [%d] id=%s... | %d karakter | meta=%s",
                        i, doc.id[:12], len(doc.content), meta_summary)
        return len(valid_docs)

    # 4. Embedding
    logger.info("Embedding yapılıyor (%d belge)...", len(valid_docs))
    embedder = _get_embedder()
    result = embedder.run(documents=valid_docs)
    embedded_docs = result["documents"]

    # 5. Veritabanına yazma
    store = _get_document_store()
    written = store.write_documents(embedded_docs, policy=policy)
    logger.info("✅ Ingestion tamamlandı: %d belge yazıldı (policy=%s).",
                written, policy.name)

    return written


# ── JSON Giriş Noktası ──

def load_json_file(path: str, dry_run: bool = False) -> int:
    """
    JSON dosyasından belge yükler ve pipeline'a gönderir.

    JSON formatı:
    [
        {
            "content": "Belge metni...",
            "meta": {
                "category": "egitim",
                "title": "Ders Kaydı",
                ...
            }
        },
        ...
    ]

    Args:
        path: JSON dosyasının yolu.
        dry_run: True ise veritabanına yazmadan rapor ver.

    Returns:
        Yazılan belge sayısı.
    """
    path = os.path.abspath(path)
    logger.info("JSON dosyası yükleniyor: %s", path)

    if not os.path.exists(path):
        logger.error("Dosya bulunamadı: %s", path)
        raise FileNotFoundError(f"JSON dosyası bulunamadı: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"JSON dosyası bir liste (array) olmalı, {type(data).__name__} geldi.")

    documents = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("JSON öğesi #%d dict değil, atlanıyor.", i)
            continue

        content = item.get("content", "")
        meta = item.get("meta", {})

        if not content:
            logger.warning("JSON öğesi #%d boş içerik, atlanıyor.", i)
            continue

        documents.append(Document(content=content, meta=meta))

    logger.info("JSON'dan %d belge okundu.", len(documents))
    return ingest_documents(documents, dry_run=dry_run)


# ── PDF Giriş Noktaları ──

def load_pdf_file(
    path: str,
    category: str = "genel",
    doc_kind: str = "genel",
    dry_run: bool = False,
    **meta,
) -> int:
    """
    Tek PDF dosyasını parse edip pipeline'a gönderir.

    Args:
        path: PDF dosyasının yolu.
        category: Belge kategorisi.
        doc_kind: Belge türü (yonetmelik, duyuru vb.)
        dry_run: True ise veritabanına yazmadan rapor ver.
        **meta: Ek metadata alanları.

    Returns:
        Yazılan belge sayısı.
    """
    from app.ingestion.pdf_parser import parse_pdf

    path = os.path.abspath(path)
    logger.info("PDF yükleniyor: %s (category=%s, doc_kind=%s)", path, category, doc_kind)

    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF dosyası bulunamadı: {path}")

    documents = parse_pdf(path, doc_kind=doc_kind, **meta)

    # Ortak metadata ekle
    for doc in documents:
        if doc.meta is None:
            doc.meta = {}
        doc.meta.setdefault("category", category)
        doc.meta.setdefault("doc_kind", doc_kind)
        doc.meta.setdefault("source_type", "pdf")
        doc.meta.update(meta)

    return ingest_documents(documents, dry_run=dry_run)


def load_pdf_directory(
    directory: str,
    category: str = "genel",
    doc_kind: str = "genel",
    dry_run: bool = False,
    **meta,
) -> int:
    """
    Dizindeki tüm PDF'leri toplu olarak yükler.

    Args:
        directory: PDF dosyalarının bulunduğu dizin.
        category: Tüm PDF'lere uygulanacak kategori.
        doc_kind: Tüm PDF'lere uygulanacak belge türü.
        dry_run: True ise veritabanına yazmadan rapor ver.
        **meta: Ek metadata alanları.

    Returns:
        Toplam yazılan belge sayısı.
    """
    directory = os.path.abspath(directory)
    logger.info("PDF dizini taranıyor: %s", directory)

    if not os.path.isdir(directory):
        raise NotADirectoryError(f"Dizin bulunamadı: {directory}")

    pdf_files = sorted(Path(directory).glob("*.pdf"))
    if not pdf_files:
        logger.warning("Dizinde PDF dosyası bulunamadı: %s", directory)
        return 0

    logger.info("%d PDF dosyası bulundu.", len(pdf_files))

    total_written = 0
    for pdf_path in pdf_files:
        try:
            written = load_pdf_file(
                str(pdf_path),
                category=category,
                doc_kind=doc_kind,
                dry_run=dry_run,
                **meta,
            )
            total_written += written
            logger.info("  ✅ %s → %d belge", pdf_path.name, written)
        except NotImplementedError:
            logger.warning("  ⏭️ %s → PDF parser henüz uygulanmadı, atlanıyor.", pdf_path.name)
        except Exception as e:
            logger.error("  ❌ %s → Hata: %s", pdf_path.name, e)

    logger.info("PDF dizin yüklemesi tamamlandı: toplam %d belge.", total_written)
    return total_written
