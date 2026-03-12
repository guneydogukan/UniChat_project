"""
UniChat Backend — Chat Servisi
Chat log kaydetme ve oturum yönetimi.
"""

import json
import logging
import uuid
import re
import psycopg2
from datetime import datetime

from app.config import get_settings

logger = logging.getLogger(__name__)

# PII filtreleme pattern'leri
PII_PATTERNS = [
    (re.compile(r"\b\d{11}\b"), "[TC_KİMLİK_FİLTRELENDİ]"),          # TC Kimlik No
    (re.compile(r"\b\d{8,10}\b"), "[ÖĞRENCİ_NO_FİLTRELENDİ]"),       # Öğrenci numarası
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[E_POSTA_FİLTRELENDİ]"),  # E-posta
]


def filter_pii(text: str) -> str:
    """Kişisel verileri (PII) metinden filtreler."""
    filtered = text
    for pattern, replacement in PII_PATTERNS:
        filtered = pattern.sub(replacement, filtered)
    return filtered


def generate_session_id() -> str:
    """Yeni bir oturum ID'si üretir."""
    return str(uuid.uuid4())


def save_chat_log(
    session_id: str,
    user_query: str,
    bot_response: str,
    source_documents: list[dict] | None = None,
) -> None:
    """
    Soru-cevap çiftini chat_logs tablosuna kaydeder.
    Kullanıcı sorgusundan PII bilgileri filtrelenir.
    """
    settings = get_settings()

    # PII filtreleme — logda kişisel veri tutulmaz
    filtered_query = filter_pii(user_query)

    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO chat_logs (session_id, user_query, bot_response, source_documents)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                session_id,
                filtered_query,
                bot_response,
                json.dumps(source_documents, ensure_ascii=False) if source_documents else None,
            ),
        )

        cur.close()
        conn.close()
        logger.debug(f"Chat log kaydedildi. Session: {session_id}")

    except Exception as e:
        # Chat log kaydetme hatası, kullanıcı deneyimini etkilememeli
        logger.error(f"Chat log kaydetme hatası: {e}")
