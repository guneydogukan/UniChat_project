"""
UniChat Backend — Yapıya Duyarlı Belge Parçalama
doc_kind'a göre farklı strateji uygular.

Stratejiler:
  - yonetmelik/yonerge : Madde bazlı bölme
  - tanitim/rehber     : Markdown başlık hiyerarşisine göre bölme
  - duyuru/haber       : Kısa ise bölünmez, uzunsa paragraf bazlı
  - iletisim/form      : Bölünmez (tek chunk)
  - mufradat/ders_plani: Varsayılan (tablo parser Faz 2.4 ile gelecek)
  - genel (varsayılan) : Kelime bazlı — Haystack DocumentSplitter
"""

import logging
import re
from typing import List

from haystack import Document
from haystack.components.preprocessors import DocumentSplitter

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Config'den sabitler ──
_settings = get_settings()
CHUNK_MAX_CHARS: int = _settings.CHUNK_MAX_CHARS      # 1200
CHUNK_OVERLAP_CHARS: int = _settings.CHUNK_OVERLAP_CHARS  # 200
CHUNK_MIN_CHARS: int = _settings.CHUNK_MIN_CHARS      # 80

# Haystack Default Splitter (Kelime bazlı, overlap ile)
_default_splitter = DocumentSplitter(
    split_by="word",
    split_length=200,      # Yaklaşık 200 kelime ≈ ~1200 karakter
    split_overlap=40,      # Yaklaşık 40 kelime overlap
)


# ── Strateji: Yönetmelik / Yönerge ──

def _split_yonetmelik(doc: Document) -> List[Document]:
    """
    Yönetmelik / Yönerge parçalayıcı:
    Madde bazlı bölmeye çalışır. "Madde X -" veya "MADDE X-" gibi yapıları arar.
    Başarısız olursa varsayılan parçalayıcıya döner.
    """
    content = doc.content

    # "Madde 1 -" veya "MADDE 1." gibi başlangıçları bulur
    pattern = re.compile(r'(?i)(?=madde\s+\d+[\s\.\-])')
    parts = pattern.split(content)

    # Eğer hiç parçalanamadıysa (sadece 1 parça varsa) veya çok az parça çıkmışsa
    if len(parts) <= 2:
        return _default_splitter.run([doc])["documents"]

    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Eğer bir parça hala çok uzunsa, onu kendi içinde default çeviriciyle kes
        if len(part) > CHUNK_MAX_CHARS * 1.5:
            temp_doc = Document(content=part, meta=doc.meta.copy() if doc.meta else {})
            sub_chunks = _default_splitter.run([temp_doc])["documents"]
            chunks.extend(sub_chunks)
        else:
            chunks.append(Document(content=part, meta=doc.meta.copy() if doc.meta else {}))

    return chunks


# ── Strateji: Tanıtım / Rehber (Başlık Hiyerarşisi) ──

def _split_heading_based(doc: Document) -> List[Document]:
    """
    Markdown heading'lere (# ## ###) göre bölme.
    Her heading'den bir sonrakine kadar olan blok ayrı chunk olur.
    Heading yoksa veya çok az varsa varsayılan parçalayıcıya döner.
    """
    content = doc.content

    # Markdown heading tespiti: satır başında # varsa
    pattern = re.compile(r'^(#{1,4})\s+', re.MULTILINE)
    matches = list(pattern.finditer(content))

    # Heading yoksa veya çok az ise default'a düş
    if len(matches) < 2:
        return _default_splitter.run([doc])["documents"]

    chunks = []

    # Heading'den önce bir giriş paragrafı varsa onu da ekle
    if matches[0].start() > 0:
        intro = content[:matches[0].start()].strip()
        if intro:
            chunks.append(Document(
                content=intro,
                meta=doc.meta.copy() if doc.meta else {}
            ))

    # Her heading bloğunu ayrı chunk yap
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section = content[start:end].strip()

        if not section:
            continue

        # Çok uzun section'ları alt parçalara böl
        if len(section) > CHUNK_MAX_CHARS * 1.5:
            temp_doc = Document(content=section, meta=doc.meta.copy() if doc.meta else {})
            sub_chunks = _default_splitter.run([temp_doc])["documents"]
            chunks.extend(sub_chunks)
        else:
            chunks.append(Document(
                content=section,
                meta=doc.meta.copy() if doc.meta else {}
            ))

    return chunks if chunks else _default_splitter.run([doc])["documents"]


# ── Strateji: Duyuru / Haber ──

def _split_news(doc: Document) -> List[Document]:
    """
    Kısa içerik → bölünmez (tek chunk).
    Uzun içerik → varsayılan parçalayıcı (paragraf/kelime bazlı).
    """
    content = doc.content
    if len(content) <= CHUNK_MAX_CHARS:
        # Kısa — bölme
        return [doc]
    else:
        # Uzun — default parçalayıcıya gönder
        return _default_splitter.run([doc])["documents"]


# ── Kısa Chunk Birleştirme ──

def _merge_short_chunks(chunks: List[Document]) -> List[Document]:
    """
    CHUNK_MIN_CHARS'tan kısa chunk'ları bir sonraki (veya önceki) chunk ile birleştirir.
    Böylece anlamsız kısa parçalar önlenir.
    """
    if not chunks or len(chunks) <= 1:
        return chunks

    merged = []
    carry = ""

    for chunk in chunks:
        text = chunk.content.strip()

        if carry:
            text = carry + "\n" + text
            carry = ""

        if len(text) < CHUNK_MIN_CHARS:
            # Çok kısa — bir sonraki chunk'a taşı
            carry = text
        else:
            merged.append(Document(
                content=text,
                meta=chunk.meta.copy() if chunk.meta else {}
            ))

    # Son taşınan parça kaldıysa son chunk'a ekle
    if carry:
        if merged:
            last = merged[-1]
            merged[-1] = Document(
                content=last.content + "\n" + carry,
                meta=last.meta.copy() if last.meta else {}
            )
        else:
            # Tüm belge çok kısa — olduğu gibi bırak
            merged.append(Document(
                content=carry,
                meta=chunks[0].meta.copy() if chunks[0].meta else {}
            ))

    return merged


# ── Ana Giriş Noktası ──

def split_documents(documents: List[Document]) -> List[Document]:
    """
    Belge listesini `doc_kind`'a göre parçalara ayırır (chunking).

    Args:
        documents: Parçalanacak belgeler.

    Returns:
        Parçalanmış belge listesi.
    """
    all_chunks = []

    for doc in documents:
        # doc_kind okuma
        doc_kind = doc.meta.get("doc_kind", "genel") if doc.meta else "genel"

        # Orijinal source_id (parent_doc_id olacak)
        source_id = doc.meta.get("source_id", "") if doc.meta else ""

        doc_chunks = []

        # 1. Strateji Seçimi
        if doc_kind in ("yonetmelik", "yonerge"):
            doc_chunks = _split_yonetmelik(doc)

        elif doc_kind in ("iletisim", "form"):
            # Bölünmez — tek chunk
            doc_chunks = [doc]

        elif doc_kind in ("tanitim", "rehber"):
            # Başlık hiyerarşisine göre böl
            doc_chunks = _split_heading_based(doc)

        elif doc_kind in ("duyuru", "haber"):
            # Kısa ise bölünmez, uzunsa paragraf bazlı
            doc_chunks = _split_news(doc)

        elif doc_kind in ("mufradat", "ders_plani"):
            # TODO: Tablo/ders bazlı strateji — Faz 2.4 PDF parser ile gelecek
            doc_chunks = _default_splitter.run([doc])["documents"]

        else:
            # genel ve diğer tüm türler — varsayılan
            doc_chunks = _default_splitter.run([doc])["documents"]

        # 1.5 Kısa chunk birleştirme (bölünmez dışında)
        if doc_kind not in ("iletisim", "form") and len(doc_chunks) > 1:
            doc_chunks = _merge_short_chunks(doc_chunks)

        # 2. Metadata Aktarımı (parent_doc_id ve chunk_index)
        for i, chunk in enumerate(doc_chunks):
            if chunk.meta is None:
                chunk.meta = doc.meta.copy() if doc.meta else {}

            if source_id:
                chunk.meta["parent_doc_id"] = source_id

            chunk.meta["chunk_index"] = i
            all_chunks.append(chunk)

    logger.info("Splitter tamamlandı: %d belge -> %d chunk", len(documents), len(all_chunks))
    return all_chunks
