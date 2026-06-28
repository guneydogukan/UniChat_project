"""
UniChat Backend — Ana Uygulama
FastAPI uygulamasının oluşturulması ve yapılandırılması.
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.repositories.department_announcement_repository import (
    classify_department_announcement_db_error,
    ensure_department_announcement_schema,
)
from app.routers import chat, department_announcements, food_menu, health
from app.services.rag_service import rag_service


def setup_logging() -> None:
    """Loglama yapılandırması."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü: başlangıçta pipeline'ı oluşturur."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("🚀 UniChat API başlatılıyor...")

    try:
        ensure_department_announcement_schema(settings.DATABASE_URL, connect_timeout=3)
    except Exception as e:  # noqa: BLE001 - duyuru DB hazırlığı API açılışını kırmamalı
        error_type = classify_department_announcement_db_error(e)
        logger.warning("Duyuru tabloları doğrulanamadı/oluşturulamadı (%s): %s", error_type, e)

    # RAG pipeline'ı oluştur ve modeli yükle
    try:
        rag_service.build_pipeline()
        logger.info("✅ RAG pipeline hazır.")
    except Exception as e:
        logger.error(f"❌ Pipeline oluşturma hatası: {e}", exc_info=True)

    yield

    logger.info("🛑 UniChat API kapatılıyor...")


def create_app() -> FastAPI:
    """FastAPI uygulamasını oluşturur."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Router'ları dahil et
    app.include_router(chat.router)
    app.include_router(department_announcements.router)
    app.include_router(food_menu.router)
    app.include_router(health.router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
