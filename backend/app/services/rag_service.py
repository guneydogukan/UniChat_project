"""
UniChat Backend — RAG Pipeline Servisi
Haystack RAG pipeline'ının oluşturulması, yönetimi ve sorgu işleme.
"""

import logging
from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.builders import PromptBuilder
from haystack.utils import Secret
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Prompt Şablonu ──
PROMPT_TEMPLATE = """Sen GİBTÜ (Gebze İleri Teknoloji Üniversitesi) resmi yapay zeka asistanı UniChat'sin.

KESİN KURALLAR:
1. YALNIZCA aşağıdaki "Belgeler" bölümündeki bilgilere dayanarak cevap ver. Belgeler dışından kesinlikle bilgi ekleme, tahmin yapma veya uydurma.
2. Belgede cevap yoksa veya yetersizse şunu söyle: "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için [ilgili birimi belirt] birimine başvurmanızı öneriyorum." ve varsa birimin iletişim bilgisini veya web adresini ekle.
3. Her zaman Türkçe yanıt ver. Kullanıcı başka dilde yazsa bile Türkçe cevapla.
4. Yanıtını markdown formatında yaz: başlıklar, maddeler, kalın metin ve bağlantılar kullan.
5. Yanıtın açık, sade ve anlaşılır olsun. Uzun paragraflar yerine maddeli listeler tercih et.
6. Kullanıcıyı doğru birime yönlendir: hangi sorunun hangi birime (öğrenci işleri, bölüm sekreterliği, Erasmus ofisi, kütüphane vb.) ait olduğunu belirt.
7. Üniversite dışı konularda (siyaset, din, kişisel tavsiye vb.) cevap verme; kibarca üniversite konularıyla sınırlı olduğunu belirt.

Belgeler:
{% for doc in documents %}
---
{{ doc.content }}
{% endfor %}

Soru: {{ question }}"""


class RagService:
    """RAG pipeline yönetim servisi."""

    def __init__(self):
        self._settings = get_settings()
        self._pipeline: Pipeline | None = None
        self._document_store: PgvectorDocumentStore | None = None

    def build_pipeline(self) -> None:
        """RAG pipeline'ı oluşturur ve bileşenleri bağlar."""
        logger.info("RAG pipeline oluşturuluyor...")

        # Document Store
        self._document_store = PgvectorDocumentStore(
            connection_string=Secret.from_env_var("DATABASE_URL"),
            table_name=self._settings.HAYSTACK_TABLE_NAME,
            embedding_dimension=self._settings.EMBEDDING_DIMENSION,
            keyword_index_name="unichat_keyword_index",
        )

        # Bileşenler
        text_embedder = SentenceTransformersTextEmbedder(
            model=self._settings.EMBEDDING_MODEL
        )

        retriever = PgvectorEmbeddingRetriever(
            document_store=self._document_store,
            top_k=self._settings.RETRIEVER_TOP_K,
        )

        prompt_builder = PromptBuilder(
            template=PROMPT_TEMPLATE,
            required_variables=["documents", "question"],
        )

        llm = OllamaGenerator(
            model=self._settings.OLLAMA_MODEL,
            url=self._settings.OLLAMA_URL,
        )

        # Pipeline oluştur ve bağla
        self._pipeline = Pipeline()
        self._pipeline.add_component("text_embedder", text_embedder)
        self._pipeline.add_component("retriever", retriever)
        self._pipeline.add_component("prompt_builder", prompt_builder)
        self._pipeline.add_component("llm", llm)

        self._pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        self._pipeline.connect("retriever.documents", "prompt_builder.documents")
        self._pipeline.connect("prompt_builder", "llm")

        # Modeli önceden yükle
        text_embedder.warm_up()

        logger.info("✅ RAG pipeline başarıyla oluşturuldu.")

    def query(self, question: str) -> dict:
        """
        Kullanıcı sorusunu RAG pipeline'dan geçirir.

        Returns:
            dict: {"response": str, "sources": list[dict]}
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline henüz oluşturulmadı. build_pipeline() çağrılmalı.")

        logger.info(f"📩 Gelen soru: {question}")

        result = self._pipeline.run({
            "text_embedder": {"text": question},
            "prompt_builder": {"question": question},
        })

        logger.info(f"Pipeline tamamlandı. Anahtarlar: {list(result.keys())}")

        # Yanıtı al
        replies = result.get("llm", {}).get("replies")
        if not replies:
            logger.warning("Pipeline sonucu boş döndü. result: %s", result)
            return {"response": None, "sources": []}

        response_text = replies[0]
        logger.info(f"Yanıt alındı ({len(response_text)} karakter)")

        # Kaynak belgelerini çıkar
        sources = []
        retrieved_docs = result.get("retriever", {}).get("documents", [])
        for doc in retrieved_docs:
            source = {
                "content": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                "source_url": doc.meta.get("source_url") if doc.meta else None,
                "category": doc.meta.get("category") if doc.meta else None,
            }
            sources.append(source)

        return {"response": response_text, "sources": sources}

    @property
    def document_store(self) -> PgvectorDocumentStore | None:
        """Document store'a erişim."""
        return self._document_store


# Singleton instance
rag_service = RagService()
