import os
import uvicorn
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.builders import PromptBuilder
from haystack.utils import Secret
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever

# .env dosyasını yükle
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")

# ── FastAPI uygulaması ──
app = FastAPI(title="UniChat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Document Store ──
document_store = PgvectorDocumentStore(
    connection_string=Secret.from_env_var("DATABASE_URL"),
    table_name="haystack_docs",
    embedding_dimension=768,
)

# ── Prompt Şablonu ──
prompt_template = """Sen GİBTÜ asistanı UniChat'sin. Lütfen sadece aşağıdaki belgelere dayanarak soruyu cevapla.
Eğer belgelerde cevap yoksa, "Maalesef bu konuda bilgim yok" de.

Belgeler:
{% for doc in documents %}{{ doc.content }}
{% endfor %}

Soru: {{ question }}"""

# ── Bileşenler ──
text_embedder = SentenceTransformersTextEmbedder(
    model="sentence-transformers/all-mpnet-base-v2"
)

retriever = PgvectorEmbeddingRetriever(
    document_store=document_store,
)

prompt_builder = PromptBuilder(
    template=prompt_template,
    required_variables=["documents", "question"],
)

llm = OllamaGenerator(
    model="gemma3:4b-it-qat",
    url="http://localhost:11434",
)

# ── RAG Pipeline ──
rag_pipeline = Pipeline()
rag_pipeline.add_component("text_embedder", text_embedder)
rag_pipeline.add_component("retriever", retriever)
rag_pipeline.add_component("prompt_builder", prompt_builder)
rag_pipeline.add_component("llm", llm)

rag_pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
rag_pipeline.connect("retriever.documents", "prompt_builder.documents")
rag_pipeline.connect("prompt_builder", "llm")

# Modeli önceden yükle
text_embedder.warm_up()


# ── Request Modeli ──
class ChatRequest(BaseModel):
    message: str


# ── Endpoint ──
@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        print(f"\n📩 Gelen soru: {request.message}")

        print("1️⃣  Pipeline çalıştırılıyor...")
        result = rag_pipeline.run(
            {
                "text_embedder": {"text": request.message},
                "prompt_builder": {"question": request.message},
            }
        )
        print(f"2️⃣  Pipeline tamamlandı. Anahtarlar: {list(result.keys())}")

        replies = result.get("llm", {}).get("replies")
        if not replies:
            print("⚠️ Pipeline sonucu boş döndü. result:", result)
            raise HTTPException(status_code=502, detail="Model boş yanıt döndürdü.")

        print(f"3️⃣  Yanıt alındı ({len(replies[0])} karakter)")
        return {"response": replies[0]}
    except HTTPException:
        raise
    except Exception as e:
        print("❌ Pipeline hatası:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)