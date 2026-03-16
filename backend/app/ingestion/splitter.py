"""
UniChat Backend — Yapıya Duyarlı Belge Parçalama
doc_kind'a göre farklı strateji uygular. 
"""

import logging
import re
from typing import List

from haystack import Document
from haystack.components.preprocessors import DocumentSplitter

logger = logging.getLogger(__name__)

# ── Sabitler ──
CHUNK_MAX_CHARS = 1200     # ~300 token (all-mpnet-base-v2 için güvenli sınır)
CHUNK_OVERLAP_CHARS = 200  # Bağlam koruma için örtüşme
CHUNK_MIN_CHARS = 80       # Çok kısa chunk'ları önleme (henüz birleştirme yok ama referans)

# Haystack Default Splitter (Cümle bazlı, overlap ile)
_default_splitter = DocumentSplitter(
    split_by="word",
    split_length=200,      # Yaklaşık 200 kelime = ~1200 karakter
    split_overlap=40,      # Yaklaşık 40 kelime overlap
)


def _split_yonetmelik(doc: Document) -> List[Document]:
    """
    Yönetmelik / Yönerge parçalayıcı:
    Madde bazlı bölmeye çalışır. "Madde X -" veya "MADDE X-" gibi yapıları arar.
    Başarısız olursa varsayılan parçalayıcıya döner.
    """
    content = doc.content
    
    # Basit "Madde X" tespiti
    # 'Madde 1 -' veya 'MADDE 1.' gibi başlangıçları bulur
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
            # Bölünmez
            doc_chunks = [doc]
            
        elif doc_kind in ("duyuru", "haber", "tanitim", "rehber", "mufradat", "ders_plani", "genel"):
            # Genel parçalayıcıya gönder
            doc_chunks = _default_splitter.run([doc])["documents"]
        else:
            # Fallback
            doc_chunks = _default_splitter.run([doc])["documents"]
            
        # 2. Metadata Aktarımı (parent_doc_id ve chunk_index)
        for i, chunk in enumerate(doc_chunks):
            # chunk.meta = doc.meta.copy() (Haystack bunu kendi içinde yapıyor olabilir ama garantileyelim)
            if chunk.meta is None:
                chunk.meta = doc.meta.copy() if doc.meta else {}
                
            if source_id:
                chunk.meta["parent_doc_id"] = source_id
            
            chunk.meta["chunk_index"] = i
            all_chunks.append(chunk)

    logger.info("Splitter tamamlandı: %d belge -> %d chunk", len(documents), len(all_chunks))
    return all_chunks
