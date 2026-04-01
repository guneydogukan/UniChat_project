"""
UniChat Backend — Document Models
Belge metadata yapıları, Pydantic şema doğrulamaları ve kategoriler.
"""

from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


# ── Kategoriler (Projeye Özel 19 Başlık) ──
CATEGORIES = Literal[
    "genel_bilgi",
    "kampus",
    "egitim",
    "bolumler",
    "lisansustu",
    "ogrenci_isleri",
    "erasmus",
    "topluluklar",
    "spor",
    "ulasim",
    "yemekhane",
    "kutuphane",
    "etkinlikler",
    "akademik_kadro",
    "dijital_hizmetler",
    "duyurular",
    "aday_ogrenci",
    "mezunlar",
    "yonlendirme"
]

# ── Belge Türleri (doc_kind) ──
DOC_KINDS = Literal[
    "yonetmelik",
    "yonerge",
    "duyuru",
    "haber",
    "tanitim",
    "rehber",
    "iletisim",
    "form",
    "mufradat",
    "ders_plani",
    "yonetim",
    "rapor",
    "menu_haritasi",
    "takvim",
    "genel"
]

SOURCE_TYPES = Literal["pdf", "web", "manual"]


class DocumentMetadata(BaseModel):
    """Her belge (Document) için metadata şeması."""

    model_config = ConfigDict(extra="allow")  # İlerde eklenebilecek eklere izin ver
    
    # ── Zorunlu Alanlar ──
    category: CATEGORIES = Field(..., description="19 ana kategoriden biri.")
    source_url: str = Field(..., description="Kaynak URL veya dosya yolu.")
    source_type: SOURCE_TYPES = Field(..., description="Verinin nasıl alındığı.")
    source_id: str = Field(..., description="İçerikten bağımsız sabit kaynak kimliği (örn: egitim_yon_md_24).")
    last_updated: str = Field(..., description="Tarih, ISO 8601 formatında.")
    title: str = Field(..., description="Belge başlığı.")
    doc_kind: DOC_KINDS = Field(default="genel", description="Belgenin türü.")

    # ── Opsiyonel / Chunk Bilgileri ──
    subcategory: Optional[str] = Field(None, description="Opsiyonel alt kategori.")
    department: Optional[str] = Field(None, description="İlgili bölüm/fakülte adı.")
    language: str = Field(default="tr", description="Belgenin dili.")
    
    parent_doc_id: Optional[str] = Field(None, description="Parçalanan orijinal belgenin source_id'si.")
    chunk_index: Optional[int] = Field(None, description="Parçalanan belgenin chunk sırası.")
    
    # ── Yönlendirme Alanları ──
    contact_unit: Optional[str] = Field(None, description="Soru üzerine yönlendirme yapılacak birim adı.")
    contact_info: Optional[str] = Field(None, description="Yönlendirme için e-posta, tel veya ofis no.")
