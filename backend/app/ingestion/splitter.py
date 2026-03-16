"""
UniChat Backend — Yapıya Duyarlı Belge Parçalama
doc_kind'a göre farklı strateji. Faz 2.3'te uygulanacak.
"""

from haystack import Document


def split_document(doc: Document) -> list[Document]:
    """
    Belgeyi yapısına göre parçalara ayırır.

    Args:
        doc: Parçalanacak belge.

    Returns:
        Parçalanmış belge listesi.

    Raises:
        NotImplementedError: Faz 2.3'te uygulanacak.
    """
    raise NotImplementedError(
        "Splitter henüz uygulanmadı. Faz 2.3'te uygulanacak."
    )
