"""
UniChat Backend — Merkezi Konfigürasyon
Tüm ayarlar .env dosyasından okunur ve Pydantic Settings ile yönetilir.
"""

import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from functools import lru_cache

# .env dosyasını os.environ'a yükle
# Haystack'in Secret.from_env_var() fonksiyonu os.environ'dan okur
_env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(_env_path)


class Settings(BaseSettings):
    """Uygulama konfigürasyonu."""

    # Veritabanı
    DATABASE_URL: str = "postgresql://postgres:gizlisifre@localhost:5433/postgres"

    # Ollama LLM
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma3:4b-it-qat"

    # Embedding
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-base"
    EMBEDDING_DIMENSION: int = 768
    # E5 modelleri prefix gerektirir (query ↔ passage asimetrik arama)
    EMBEDDING_QUERY_PREFIX: str = "query: "
    EMBEDDING_PASSAGE_PREFIX: str = "passage: "

    # Haystack Document Store
    HAYSTACK_TABLE_NAME: str = "haystack_docs"

    # Retriever
    RETRIEVER_VECTOR_TOP_K: int = 5    # Vektör araması (PgvectorEmbeddingRetriever)
    RETRIEVER_KEYWORD_TOP_K: int = 3   # BM25 kelime araması (PgvectorKeywordRetriever)

    # Chunking (yapıya duyarlı strateji parametreleri)
    CHUNK_MAX_CHARS: int = 1200        # ~300 token (multilingual-e5-base 512 token sınırına güvenli mesafe)
    CHUNK_OVERLAP_CHARS: int = 200     # Bağlam koruma
    CHUNK_MIN_CHARS: int = 40          # Bundan kısa parçalar birleştirilir

    # Veri yükleme
    DATA_DIR: str = "data"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Loglama
    LOG_LEVEL: str = "INFO"

    # Uygulama
    APP_TITLE: str = "UniChat API"
    APP_VERSION: str = "1.0.0"

    model_config = {
        "env_file": os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance döndürür."""
    return Settings()
