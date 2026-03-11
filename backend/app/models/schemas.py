"""
UniChat Backend — Pydantic Şemaları
API request/response modelleri.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Chat isteği modeli."""
    message: str = Field(..., min_length=1, max_length=2000, description="Kullanıcı mesajı")


class SourceDocument(BaseModel):
    """Yanıtta referans gösterilen belge kaynağı."""
    content: str = Field(..., description="Belge içeriği (kısaltılmış)")
    source_url: str | None = Field(None, description="Kaynak URL")
    category: str | None = Field(None, description="Belge kategorisi")


class ChatResponse(BaseModel):
    """Chat yanıtı modeli."""
    response: str = Field(..., description="Bot yanıtı")
    sources: list[SourceDocument] = Field(default_factory=list, description="Kaynak belgeler")
    session_id: str | None = Field(None, description="Oturum ID")


class HealthResponse(BaseModel):
    """Sistem sağlık durumu."""
    status: str = Field(..., description="Genel durum")
    database: str = Field(..., description="Veritabanı bağlantı durumu")
    ollama: str = Field(..., description="Ollama model durumu")
    embedding: str = Field(..., description="Embedding model durumu")
