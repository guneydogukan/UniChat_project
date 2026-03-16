"""
UniChat Backend — PDF Parser
PDF → metin dönüşümü. Faz 2.4'te uygulanacak.
"""

from haystack import Document


def parse_pdf(path: str, doc_kind: str = "genel", **meta) -> list[Document]:
    """
    Tek PDF dosyasını parse edip Document listesine dönüştürür.

    Args:
        path: PDF dosyasının yolu.
        doc_kind: Belge türü (yonetmelik, duyuru, tanitim vb.)
        **meta: Ek metadata alanları.

    Returns:
        Document listesi.

    Raises:
        NotImplementedError: Faz 2.4'te uygulanacak.
    """
    raise NotImplementedError(
        "PDF parser henüz uygulanmadı. Faz 2.4'te pdfplumber ile uygulanacak."
    )
