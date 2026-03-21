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
from app.routers import chat, health
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
    app.include_router(health.router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)