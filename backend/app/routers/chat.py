"""
UniChat Backend — Chat Router
/api/chat endpoint'i.
"""

import logging
from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse, SourceDocument
from app.services.rag_service import rag_service
from app.services.chat_service import save_chat_log, generate_session_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Kullanıcı mesajını RAG pipeline'dan geçirir ve yanıt döner.
    """
    try:
        logger.info(f"📩 Gelen soru: {request.message}")

        # RAG pipeline çalıştır
        result = rag_service.query(request.message)

        if result["response"] is None:
            raise HTTPException(
                status_code=502,
                detail="Model boş yanıt döndürdü. Lütfen tekrar deneyiniz."
            )

        # Kaynak belgeleri dönüştür
        sources = [
            SourceDocument(
                content=s["content"],
                source_url=s.get("source_url"),
                category=s.get("category"),
            )
            for s in result["sources"]
        ]

        # Session oluştur ve chat log kaydet
        session_id = generate_session_id()
        save_chat_log(
            session_id=session_id,
            user_query=request.message,
            bot_response=result["response"],
            source_documents=result["sources"],
        )

        return ChatResponse(
            response=result["response"],
            sources=sources,
            session_id=session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Pipeline hatası: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Bir hata oluştu. Lütfen daha sonra tekrar deneyiniz."
        )
