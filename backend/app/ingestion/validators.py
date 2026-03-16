"""
UniChat Backend — Ingestion Validators
Belge doğrulama: boş içerik, minimum uzunluk, placeholder tespiti.
"""

import logging
import re

from haystack import Document

from app.models.document_models import DocumentMetadata

logger = logging.getLogger(__name__)

# ── Sabitler ──
MIN_CONTENT_LENGTH = 50

PLACEHOLDER_PATTERNS = [
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"under\s+construction", re.IGNORECASE),
    re.compile(r"yakında\s+eklenecek", re.IGNORECASE),
    re.compile(r"içerik\s+hazırlanıyor", re.IGNORECASE),
    re.compile(r"bu\s+sayfa\s+yapım\s+aşamasında", re.IGNORECASE),
    re.compile(r"content\s+coming\s+soon", re.IGNORECASE),
]


def _is_placeholder(text: str) -> bool:
    """Placeholder içerik tespiti."""
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            return True
    return False


def validate_documents(documents: list[Document]) -> list[Document]:
    """
    Belge listesini doğrular. Geçersiz belgeleri filtreler ve loglar.

    Kurallar:
    - content boş veya None → reddet
    - len(content) < MIN_CONTENT_LENGTH → reddet
      (doc_kind == "iletisim" veya "form" ise istisna)
    - Placeholder içerik → reddet

    Returns:
        Geçerli belgeler listesi.
    """
    valid = []
    rejected_count = 0

    for i, doc in enumerate(documents):
        # Boş içerik kontrolü
        if not doc.content or not doc.content.strip():
            logger.warning("Belge #%d reddedildi: Boş içerik.", i)
            rejected_count += 1
            continue

        content = doc.content.strip()

        # Minimum uzunluk kontrolü (iletişim/form istisna)
        doc_kind = doc.meta.get("doc_kind", "") if doc.meta else ""
        if len(content) < MIN_CONTENT_LENGTH and doc_kind not in ("iletisim", "form"):
            logger.warning(
                "Belge #%d reddedildi: Çok kısa (%d karakter, min=%d). İlk 30 karakter: '%s'",
                i, len(content), MIN_CONTENT_LENGTH, content[:30],
            )
            rejected_count += 1
            continue

        # Placeholder tespiti
        if _is_placeholder(content):
            logger.warning(
                "Belge #%d reddedildi: Placeholder içerik tespit edildi. İlk 50 karakter: '%s'",
                i, content[:50],
            )
            rejected_count += 1
            continue

        # Metadata Doğrulama (Pydantic ile)
        try:
            # Metadata alanlarını DocumentMetadata yapısında doğrula
            # Eksik zorunlu alanlar veya yanlış tipler hata fırlatır
            if doc.meta is None:
                doc.meta = {}
            # Eğer eksik alanlar varsa (henüz seed datadan vs.) exception yakalanacak.
            # Geliştirme aşamasında strict mod için açabiliriz. Ama default seed veya scraping düzgün çalışana kadar 
            # kritik alanlar uyarılabilir.  Ancak Faz 2.2 kapsamında şemaya sadık kalarak validate edilmeli.
            DocumentMetadata(**doc.meta)
            valid.append(doc)
        except Exception as e:
            logger.warning("Belge #%d reddedildi: Metadata geçersiz. Hata: %s", i, getattr(e, "errors", lambda: str(e))())
            rejected_count += 1
            continue

    total = len(documents)
    logger.info(
        "Doğrulama tamamlandı: %d/%d belge geçerli, %d reddedildi.",
        len(valid), total, rejected_count,
    )
    return valid
