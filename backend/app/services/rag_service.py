"""
UniChat Backend — RAG Pipeline Servisi
Hybrid search: PgvectorEmbeddingRetriever (vektör) + PgvectorKeywordRetriever (BM25)
DocumentJoiner ile reciprocal_rank_fusion stratejisi uygulanır.

Savunma katmanları:
    1. Intent Classifier  — kapsam dışı sorguları pipeline öncesi reddeder
    2. Query Preprocessing — typo/abbreviation/comparison/routing
    3. Prompt Güçlendirme  — pozitif kısıtlamalar ile LLM davranışını yönlendirir
    4. Response Validator  — LLM çıktısındaki uydurma URL/telefon/e-posta'yı temizler
    5. Source Dedup        — URL + title + content bazlı kaynak tekrarını engeller
"""

import hashlib
import logging
import time
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
from app.services.intent_classifier import classify_intent, REJECTION_RESPONSE
from app.services.response_validator import validate_response
from app.services.query_preprocessor import preprocess_query

logger = logging.getLogger(__name__)

# ── Türkçe Stopword Listesi ──
TURKISH_STOPWORDS: frozenset[str] = frozenset({
    "hangi", "ne", "neler", "nedir", "nasıl", "nerede", "nereye", "nereden",
    "kim", "kime", "kimin", "neden", "niçin", "niye", "kaç", "kadar",
    "mi", "mı", "mu", "mü",
    "var", "yok", "olan", "olarak", "olmak", "olur", "olabilir",
    "almak", "istiyorum", "istiyoruz", "ister", "istiyor",
    "diyor", "eder", "yapar", "verir", "gelir", "gider",
    "son", "ilk", "en", "bir", "birçok",
    "ve", "veya", "ile", "için", "gibi", "kadar", "ama", "fakat",
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
7. Üniversite dışı konularda (siyaset, din, kişisel tavsiye, programlama kodu yazma vb.) cevap verme; kibarca üniversite konularıyla sınırlı olduğunu belirt.
8. Yanıtın sonunda, kullanıcının bu konuyla ilgili başvurabileceği birimi, telefon/e-posta bilgisini veya resmî web sayfası adresini belirt. Bu bilgi belgede varsa doğrudan kullan; yoksa en uygun birimi öner.

YANITINDA KESİNLİKLE BULUNMAMASI GEREKENLER:
- Belgede açıkça yazılı OLMAYAN telefon numarası, e-posta adresi veya URL. Sadece belgelerde geçen iletişim bilgilerini kullan.
- Belgede olmayan bir URL tahmin etme veya oluşturma. URL bilgisi yoksa "Detaylı bilgi için www.gibtu.edu.tr adresini ziyaret ediniz" yaz.
- Programlama kodu (Python, JavaScript, SQL vb.). Kullanıcı kod isterse kibarca reddet.
- Üniversite ile ilgisi olmayan genel bilgiler (coğrafya, tarih, bilim, siyaset).

Belgeler:
{% for doc in documents %}
---
[{{ doc.meta.category | default("bilinmiyor") }}] {{ doc.meta.title | default("") }}
Kaynak: {{ doc.meta.source_url | default("belirtilmemiş") }}
{% if doc.meta.contact_unit %}İlgili birim: {{ doc.meta.contact_unit }}{% endif %}
{% if doc.meta.contact_info %}İletişim: {{ doc.meta.contact_info }}{% endif %}
{% if doc.meta.last_updated %}Son güncelleme: {{ doc.meta.last_updated }}{% endif %}

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

        joiner = DocumentJoiner(join_mode="reciprocal_rank_fusion")

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
        self._pipeline.connect("text_embedder.embedding", "vector_retriever.query_embedding")
        self._pipeline.connect("vector_retriever.documents", "joiner.documents")
        self._pipeline.connect("keyword_retriever.documents", "joiner.documents")
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
        """Türkçe stopword'leri çıkararak keyword araması için sorguyu temizler."""
        words = text.split()
        meaningful = [w for w in words if w.lower() not in TURKISH_STOPWORDS]
        cleaned = " ".join(meaningful) if meaningful else text
        return cleaned

    def query(self, question: str) -> dict:
        """Kullanıcı sorusunu Hybrid Search RAG pipeline'dan geçirir.

        Savunma katmanları:
            1. Intent Classifier  — kapsam dışı → sabit reddetme yanıtı
            2. Query Preprocessing — typo/abbreviation/comparison/routing
            3. Pipeline (retrieval + LLM)
            4. Response Validator  — uydurma URL/telefon/e-posta temizliği
            5. Source Dedup        — URL + title + content bazlı dedup
            6. Routing Correction  — eksik birim yönlendirmesi

        Returns:
            dict: {"response": str, "sources": list[dict]}
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline henüz oluşturulmadı. build_pipeline() çağrılmalı.")

        t_total = time.perf_counter()
        logger.info("📩 Gelen soru: %s", question)

        # ── Katman 1: Intent Classifier ──
        t0 = time.perf_counter()
        intent = classify_intent(question)
        t_intent = time.perf_counter() - t0

        if intent == "OUT_OF_SCOPE":
            logger.info("🚫 Kapsam dışı sorgu reddedildi: %s", question[:80])
            logger.info(
                "⏱️ [latency] intent=%.3fs total=%.3fs (rejected)",
                t_intent, time.perf_counter() - t_total,
            )
            return {"response": REJECTION_RESPONSE, "sources": []}

        # ── Katman 2: Query Preprocessing ──
        t0 = time.perf_counter()
        pp = preprocess_query(question)
        t_preprocess = time.perf_counter() - t0

        if pp.corrections:
            logger.info("🔧 Sorgu ön-işleme: %s", ", ".join(pp.corrections))

        keyword_query = self._clean_keyword_query(pp.keyword_query)
        if keyword_query != pp.keyword_query:
            logger.info("🔤 Keyword sorgusu temizlendi: '%s' → '%s'", pp.keyword_query, keyword_query)

        vector_top_k = self._settings.RETRIEVER_VECTOR_TOP_K + pp.boost_top_k
        keyword_top_k = self._settings.RETRIEVER_KEYWORD_TOP_K + pp.boost_top_k

        # ── Katman 3: Pipeline ──
        prompt_question = question
        if pp.routing_hint:
            prompt_question = f"{question}\n\n[Sistem notu: Bu konu için yetkili birim: {pp.routing_hint}]"

        t0 = time.perf_counter()
        result = self._pipeline.run(
            data={
                "text_embedder": {"text": pp.vector_query},
                "keyword_retriever": {"query": keyword_query, "top_k": keyword_top_k},
                "vector_retriever": {"top_k": vector_top_k},
                "prompt_builder": {"question": prompt_question},
            },
            include_outputs_from={"joiner"},
        )
        t_pipeline = time.perf_counter() - t0

        # Yanıtı al
        replies = result.get("llm", {}).get("replies")
        if not replies:
            logger.warning("Pipeline sonucu boş döndü.")
            return {"response": None, "sources": []}

        response_text = replies[0]
        logger.info("Yanıt alındı (%d karakter)", len(response_text))

        # Joiner çıktısından kaynak belgelerini al
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

        # ── Katman 4: Response Validator ──
        t0 = time.perf_counter()
        response_text = validate_response(response_text, sources)
        t_validator = time.perf_counter() - t0

        # ── Katman 5: Source Dedup ──
        t0 = time.perf_counter()
        sources_before = len(sources)
        sources = self._dedup_sources(sources)
        t_dedup = time.perf_counter() - t0

        # ── Katman 6: Routing Correction ──
        if pp.routing_hint:
            response_text = self._apply_routing_correction(
                response_text, pp.routing_hint,
            )

        t_total_elapsed = time.perf_counter() - t_total

        # ── Latency Summary ──
        logger.info(
            "⏱️ [latency] intent=%.3fs preprocess=%.3fs pipeline=%.3fs "
            "validator=%.3fs dedup=%.3fs total=%.3fs "
            "sources=%d→%d",
            t_intent, t_preprocess, t_pipeline,
            t_validator, t_dedup, t_total_elapsed,
            sources_before, len(sources),
        )

        return {"response": response_text, "sources": sources}

    @staticmethod
    def _dedup_sources(sources: list[dict]) -> list[dict]:
        """Kaynak belgelerden tekrarlananları kaldırır.

        Dedup sinyalleri (öncelik sırasıyla):
            1. Aynı normalized URL → ilk chunk'ı tut, diğerlerini at
            2. Aynı content hash → birebir aynı içerik
            3. URL yok ama aynı title → ilkini tut
        """
        unique: list[dict] = []
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        seen_titles: set[str] = set()

        for src in sources:
            raw_url = (src.get("source_url") or "").strip().rstrip("/").lower()
            norm_url = raw_url.replace("https://", "http://")

            raw_title = (src.get("title") or "").strip().lower()

            content_hash = hashlib.md5(
                (src.get("content") or "").encode()
            ).hexdigest()

            # Kural 1: Aynı URL zaten eklendiyse atla
            if norm_url and norm_url in seen_urls:
                continue

            # Kural 2: Birebir aynı içerik zaten eklendiyse atla
            if content_hash in seen_hashes:
                continue

            # Kural 3: URL yoksa ve aynı title zaten eklendiyse atla
            if not norm_url and raw_title and raw_title in seen_titles:
                continue

            if norm_url:
                seen_urls.add(norm_url)
            seen_hashes.add(content_hash)
            if raw_title:
                seen_titles.add(raw_title)
            unique.append(src)

        if len(unique) < len(sources):
            logger.info(
                "🔄 Source dedup: %d → %d kaynak belge",
                len(sources), len(unique),
            )
        return unique

    @staticmethod
    def _apply_routing_correction(response: str, expected_unit: str) -> str:
        """Yanıtta beklenen birim geçmiyorsa yönlendirme notu ekler."""
        response_lower = response.lower()
        expected_lower = expected_unit.lower()

        unit_keywords = expected_lower.split()
        check_phrase = " ".join(unit_keywords[:2]) if len(unit_keywords) >= 2 else expected_lower
        if check_phrase in response_lower:
            return response

        correction_note = (
            f"\n\n> **📌 Yönlendirme:** Bu konuda yetkili birim "
            f"**{expected_unit.title()}**'dır. Detaylı bilgi için "
            f"bu birime başvurmanızı öneriyoruz."
        )
        logger.info(
            "🏢 Routing correction: '%s' birim yanıtta eksik, not eklendi",
            expected_unit,
        )
        return response + correction_note

    @property
    def document_store(self) -> PgvectorDocumentStore | None:
        """Document store'a erişim."""
        return self._document_store


# Singleton instance
rag_service = RagService()
