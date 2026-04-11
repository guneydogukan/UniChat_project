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


# ── Strateji: Semantic (Başlık + Paragraf Bazlı) ──

def _split_semantic(doc: Document) -> List[Document]:
    """
    3.2.7.4-D: Anlamsal bölme stratejisi.

    Öncelik sırası:
      1. H1/H2/H3 başlık sınırlarına göre bölme
      2. Paragraf (\\n\\n) sınırlarına göre bölme
      3. Max chunk boyutu aşılırsa kelime bazlı fallback

    Her chunk'a heading_context metadata'sı eklenir.
    """
    content = doc.content
    if not content:
        return [doc]

    # Başlıkları tespit et (## veya ### ile başlayan satırlar)
    heading_pattern = re.compile(r'^(#{1,4})\s+(.+)', re.MULTILINE)
    headings = list(heading_pattern.finditer(content))

    # Heading varsa heading-based böl
    if len(headings) >= 2:
        return _split_by_headings_with_context(doc, content, headings)

    # Heading yoksa paragraf bazlı böl
    return _split_by_paragraphs(doc, content)


def _split_by_headings_with_context(
    doc: Document, content: str, headings: list
) -> List[Document]:
    """
    Heading'lere göre böler, her chunk'a heading_context ekler.
    """
    chunks = []
    current_heading_context = ""

    # Heading'den önce giriş paragrafı
    if headings[0].start() > 0:
        intro = content[:headings[0].start()].strip()
        if intro and len(intro) >= CHUNK_MIN_CHARS:
            chunk_doc = Document(
                content=intro,
                meta={**(doc.meta.copy() if doc.meta else {}), "heading_context": "Giriş"},
            )
            chunks.append(chunk_doc)

    for i, match in enumerate(headings):
        heading_level = len(match.group(1))
        heading_text = match.group(2).strip()
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        section = content[start:end].strip()

        if not section:
            continue

        # Heading context oluştur
        if heading_level <= 2:
            current_heading_context = heading_text
        else:
            current_heading_context = f"{current_heading_context} > {heading_text}" if current_heading_context else heading_text

        # Çok uzun section'ları paragraf bazlı alt-böl
        if len(section) > CHUNK_MAX_CHARS * 1.5:
            sub_chunks = _split_by_paragraphs(
                Document(content=section, meta=doc.meta.copy() if doc.meta else {}),
                section,
                heading_context=current_heading_context,
            )
            chunks.extend(sub_chunks)
        else:
            chunk_meta = doc.meta.copy() if doc.meta else {}
            chunk_meta["heading_context"] = current_heading_context
            chunks.append(Document(content=section, meta=chunk_meta))

    return chunks if chunks else _default_splitter.run([doc])["documents"]


def _split_by_paragraphs(
    doc: Document, content: str, heading_context: str = ""
) -> List[Document]:
    """
    Paragraf (\\n\\n) sınırlarına göre böler.
    Max chunk'a ulaşınca yeni chunk başlatır.
    Context overlap: önceki chunk'ın son cümlesi sonraki chunk'ın başına eklenir.
    """
    paragraphs = re.split(r'\n\s*\n', content)
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Mevcut chunk + yeni paragraf max'ı aşar mı?
        if current_chunk and len(current_chunk) + len(para) + 2 > CHUNK_MAX_CHARS:
            # Mevcut chunk'ı kaydet
            chunk_meta = doc.meta.copy() if doc.meta else {}
            if heading_context:
                chunk_meta["heading_context"] = heading_context
            chunks.append(Document(content=current_chunk.strip(), meta=chunk_meta))

            # Context overlap: önceki chunk'ın son cümlesini al
            overlap = _get_last_sentence(current_chunk)
            current_chunk = overlap + "\n\n" + para if overlap else para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    # Son chunk
    if current_chunk.strip():
        chunk_meta = doc.meta.copy() if doc.meta else {}
        if heading_context:
            chunk_meta["heading_context"] = heading_context
        chunks.append(Document(content=current_chunk.strip(), meta=chunk_meta))

    # Çok uzun kalan chunk'ları word splitter ile böl
    final_chunks = []
    for chunk in chunks:
        if len(chunk.content) > CHUNK_MAX_CHARS * 2:
            sub = _default_splitter.run([chunk])["documents"]
            final_chunks.extend(sub)
        else:
            final_chunks.append(chunk)

    return final_chunks if final_chunks else _default_splitter.run([doc])["documents"]


def _get_last_sentence(text: str) -> str:
    """Metnin son cümlesini döndürür (context overlap için)."""
    sentences = re.split(r'[.!?]\s+', text.strip())
    if sentences and len(sentences) > 1:
        last = sentences[-1].strip()
        if len(last) > 10:
            return last[:200]  # Max 200 kar overlap
    return ""


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
            # genel ve diğer tüm türler — semantic (başlık+paragraf) bölme (3.2.7.4-D)
            doc_chunks = _split_semantic(doc)

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
