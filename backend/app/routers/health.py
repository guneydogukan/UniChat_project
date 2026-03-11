"""
UniChat Backend — Health Router
Sistem sağlık durumu kontrolü.
"""

import logging
import psycopg2
import requests
from fastapi import APIRouter

from app.models.schemas import HealthResponse
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Sistem bileşenlerinin durumunu kontrol eder."""
    settings = get_settings()

    # Veritabanı kontrolü
    db_status = "disconnected"
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.close()
        db_status = "connected"
    except Exception as e:
        logger.warning(f"DB bağlantı hatası: {e}")

    # Ollama kontrolü
    ollama_status = "disconnected"
    try:
        resp = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            if any(settings.OLLAMA_MODEL in m for m in models):
                ollama_status = f"connected ({settings.OLLAMA_MODEL})"
            else:
                ollama_status = f"connected (model '{settings.OLLAMA_MODEL}' bulunamadı)"
        else:
            ollama_status = f"error (HTTP {resp.status_code})"
    except Exception as e:
        logger.warning(f"Ollama bağlantı hatası: {e}")

    # Embedding durumu (pipeline oluşturulduysa hazır)
    from app.services.rag_service import rag_service
    embedding_status = "ready" if rag_service.document_store is not None else "not initialized"

    # Genel durum
    overall = "healthy" if db_status == "connected" and "connected" in ollama_status else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        ollama=ollama_status,
        embedding=embedding_status,
    )
