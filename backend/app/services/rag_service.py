"""
UniChat Backend — RAG Pipeline Servisi
Hybrid search: PgvectorEmbeddingRetriever (vektör) + PgvectorKeywordRetriever (BM25)
DocumentJoiner ile reciprocal_rank_fusion stratejisi uygulanır.
"""

import logging
from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.builders import PromptBuilder
from haystack.components.joiners import DocumentJoiner
from haystack.utils import Secret
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import (
    PgvectorEmbeddingRetriever,
    PgvectorKeywordRetriever,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Türkçe Stopword Listesi ──
# BM25 keyword aramasında plainto_tsquery AND semantiği kullanılır.
# Doğal dil sorgularındaki düşük bilgi taşıyan kelimeler (soru edatları,
# fiiller, bağlaçlar) AND koşuluna eklenince eşleşme sıfıra düşer.
# Bu liste, sorgu keyword_retriever'a gönderilmeden önce temizlenir.
TURKISH_STOPWORDS: frozenset[str] = frozenset({
    # Soru edatları ve zamirleri
    "hangi", "ne", "neler", "nedir", "nasıl", "nerede", "nereye", "nereden",
    "kim", "kime", "kimin", "neden", "niçin", "niye", "kaç", "kadar",
    # Soru ekleri
    "mi", "mı", "mu", "mü",
    # Yaygın fiiller ve yardımcı fiiller
    "var", "yok", "olan", "olarak", "olmak", "olur", "olabilir",
    "almak", "istiyorum", "istiyoruz", "ister", "istiyor",
    "diyor", "eder", "yapar", "verir", "gelir", "gider",
    # Zaman ve sıralama
    "son", "ilk", "en", "bir", "birçok",
    # Bağlaçlar ve edatlar
    "ve", "veya", "ile", "için", "gibi", "kadar", "ama", "fakat",
    # Hal ekleri ve işaret zamirleri
    "de", "da", "den", "dan", "bu", "şu", "o",
})

# ── Prompt Şablonu ──
PROMPT_TEMPLATE = """Sen GİBTÜ (Gaziantep İslam Bilim ve Teknoloji Üniversitesi) resmi yapay zeka asistanı UniChat'sin.

KESİN KURALLAR:
1. YALNIZCA aşağıdaki "Belgeler" bölümündeki bilgilere dayanarak cevap ver. Belgeler dışından kesinlikle bilgi ekleme, tahmin yapma veya uydurma.
2. Belgede cevap yoksa veya yetersizse şunu söyle: "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için [ilgili birimi belirt] birimine başvurmanızı öneriyorum." ve varsa birimin iletişim bilgisini veya web adresini ekle.
3. Her zaman Türkçe yanıt ver. Kullanıcı başka dilde yazsa bile Türkçe cevapla.
4. Yanıtını markdown formatında yaz: başlıklar, maddeler, kalın metin ve bağlantılar kullan.
5. Yanıtın açık, sade ve anlaşılır olsun. Uzun paragraflar yerine maddeli listeler tercih et.
6. Kullanıcıyı doğru birime yönlendir: hangi sorunun hangi birime (öğrenci işleri, bölüm sekreterliği, Erasmus ofisi, kütüphane vb.) ait olduğunu belirt.
7. Üniversite dışı konularda (siyaset, din, kişisel tavsiye vb.) cevap verme; kibarca üniversite konularıyla sınırlı olduğunu belirt.
8. Yanıtın sonunda, kullanıcının bu konuyla ilgili başvurabileceği birimi, telefon/e-posta bilgisini veya resmî web sayfası adresini belirt. Bu bilgi belgede varsa doğrudan kullan; yoksa en uygun birimi öner.

Belgeler:
{% for doc in documents %}
---
[{{ doc.meta.category | default("bilinmiyor") }}] {{ doc.meta.title | default("") }}
Kaynak: {{ doc.meta.source_url | default("belirtilmemiş") }}
{% if doc.meta.contact_unit %}İlgili birim: {{ doc.meta.contact_unit }}{% endif %}
{% if doc.meta.contact_info %}İletişim: {{ doc.meta.contact_info }}{% endif %}

{{ doc.content }}
{% endfor %}

Soru: {{ question }}"""


class RagService:
    """RAG pipeline yönetim servisi — Hybrid Search (BM25 + vektör)."""

    def __init__(self):
        self._settings = get_settings()
        self._pipeline: Pipeline | None = None
        self._document_store: PgvectorDocumentStore | None = None

    def build_pipeline(self) -> None:
        """Hybrid search RAG pipeline'ını oluşturur ve bileşenleri bağlar.

        Pipeline akışı:
          text_embedder → vector_retriever ──┐
                                              ├→ joiner → prompt_builder → llm
          keyword_retriever ─────────────────┘
        """
        logger.info("Hybrid Search RAG pipeline oluşturuluyor...")

        # ── Document Store ──
        self._document_store = PgvectorDocumentStore(
            connection_string=Secret.from_env_var("DATABASE_URL"),
            table_name=self._settings.HAYSTACK_TABLE_NAME,
            embedding_dimension=self._settings.EMBEDDING_DIMENSION,
            language="turkish",
            keyword_index_name="unichat_keyword_index",
        )

        # ── Bileşenler ──
        text_embedder = SentenceTransformersTextEmbedder(
            model=self._settings.EMBEDDING_MODEL,
            prefix=self._settings.EMBEDDING_QUERY_PREFIX,
        )

        vector_retriever = PgvectorEmbeddingRetriever(
            document_store=self._document_store,
            top_k=self._settings.RETRIEVER_VECTOR_TOP_K,
        )

        keyword_retriever = PgvectorKeywordRetriever(
            document_store=self._document_store,
            top_k=self._settings.RETRIEVER_KEYWORD_TOP_K,
        )

        # reciprocal_rank_fusion: vektör + BM25 sonuçlarını birleştirir ve yeniden sıralar
        joiner = DocumentJoiner(
            join_mode="reciprocal_rank_fusion",
        )

        prompt_builder = PromptBuilder(
            template=PROMPT_TEMPLATE,
            required_variables=["documents", "question"],
        )

        llm = OllamaGenerator(
            model=self._settings.OLLAMA_MODEL,
            url=self._settings.OLLAMA_URL,
        )

        # ── Pipeline oluştur ──
        self._pipeline = Pipeline()
        self._pipeline.add_component("text_embedder", text_embedder)
        self._pipeline.add_component("vector_retriever", vector_retriever)
        self._pipeline.add_component("keyword_retriever", keyword_retriever)
        self._pipeline.add_component("joiner", joiner)
        self._pipeline.add_component("prompt_builder", prompt_builder)
        self._pipeline.add_component("llm", llm)

        # ── Bağlantılar ──
        # Vektör kolu
        self._pipeline.connect("text_embedder.embedding", "vector_retriever.query_embedding")
        self._pipeline.connect("vector_retriever.documents", "joiner.documents")
        # Keyword kolu (aynı soru metni doğrudan keyword_retriever'a gider)
        self._pipeline.connect("keyword_retriever.documents", "joiner.documents")
        # Joiner → Prompt → LLM
        self._pipeline.connect("joiner.documents", "prompt_builder.documents")
        self._pipeline.connect("prompt_builder", "llm")

        # Embedding modelini önceden yükle
        text_embedder.warm_up()

        logger.info(
            "✅ Hybrid Search RAG pipeline hazır "
            "(vector_top_k=%d, keyword_top_k=%d, join=reciprocal_rank_fusion).",
            self._settings.RETRIEVER_VECTOR_TOP_K,
            self._settings.RETRIEVER_KEYWORD_TOP_K,
        )

    @staticmethod
    def _clean_keyword_query(text: str) -> str:
        """Türkçe stopword'leri çıkararak keyword araması için sorguyu temizler.

        plainto_tsquery tüm kelimeleri AND ile birleştirir. Doğal dil
        sorgularındaki 'hangi', 'var', 'mi' gibi kelimeler AND koşuluna
        dahil olunca eşleşme sıfıra düşer. Bu metod yalnızca anlamlı
        terimleri bırakır.
        """
        words = text.split()
        meaningful = [w for w in words if w.lower() not in TURKISH_STOPWORDS]
        cleaned = " ".join(meaningful) if meaningful else text
        return cleaned

    def query(self, question: str) -> dict:
        """Kullanıcı sorusunu Hybrid Search RAG pipeline'dan geçirir.

        Returns:
            dict: {"response": str, "sources": list[dict]}
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline henüz oluşturulmadı. build_pipeline() çağrılmalı.")

        logger.info("📩 Gelen soru: %s", question)

        # Keyword retriever için Türkçe stopword temizliği uygula
        keyword_query = self._clean_keyword_query(question)
        if keyword_query != question:
            logger.info("🔤 Keyword sorgusu temizlendi: '%s' → '%s'", question, keyword_query)

        result = self._pipeline.run(
            data={
                "text_embedder": {"text": question},
                "keyword_retriever": {"query": keyword_query},
                "prompt_builder": {"question": question},
            },
            include_outputs_from={"joiner"},
        )

        logger.info("Pipeline tamamlandı. Anahtarlar: %s", list(result.keys()))

        # Yanıtı al
        replies = result.get("llm", {}).get("replies")
        if not replies:
            logger.warning("Pipeline sonucu boş döndü. result: %s", result)
            return {"response": None, "sources": []}

        response_text = replies[0]
        logger.info("Yanıt alındı (%d karakter)", len(response_text))

        # Joiner çıktısından kaynak belgelerini al (birleştirilmiş ve yeniden sıralanmış)
        sources = []
        joined_docs = result.get("joiner", {}).get("documents", [])
        for doc in joined_docs:
            source = {
                "content": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                "source_url": doc.meta.get("source_url") if doc.meta else None,
                "category": doc.meta.get("category") if doc.meta else None,
                "title": doc.meta.get("title") if doc.meta else None,
                "doc_kind": doc.meta.get("doc_kind") if doc.meta else None,
            }
            sources.append(source)

        return {"response": response_text, "sources": sources}

    @property
    def document_store(self) -> PgvectorDocumentStore | None:
        """Document store'a erişim."""
        return self._document_store


# Singleton instance
rag_service = RagService()
