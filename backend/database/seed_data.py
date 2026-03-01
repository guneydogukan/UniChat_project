import os
import sys

from dotenv import load_dotenv
from haystack import Document
from haystack.components.embedders import SentenceTransformersDocumentEmbedder
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack.utils import Secret


# .env dosyasını yükle
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")


def seed():
    """Örnek GİBTÜ verilerini vektörleştirip veritabanına kaydeder."""
    try:
        # PgvectorDocumentStore bağlantısı

        document_store = PgvectorDocumentStore(
        connection_string=Secret.from_env_var("DATABASE_URL"),
        table_name="haystack_docs",
        embedding_dimension=768,
        recreate_table=True,
        keyword_index_name="unichat_keyword_index",

        )

        # Örnek belgeler
        documents = [
            Document(
                content="GİBTÜ Ön Lisans ve Lisans Eğitim-Öğretim Yönetmeliği Madde 24: "
                        "Öğrenciler, danışmanlarının onayı ile her yarıyılda en fazla 45 AKTS "
                        "kredilik ders alabilirler."
            ),
            Document(
                content="GİBTÜ Yemekhane kuralları: Öğrenciler yemekhane rezervasyonlarını "
                        "bir gün önceden akıllı kartlarına para yükleyerek sistem üzerinden "
                        "yapmalıdır."
            ),
            Document(
                content="GİBTÜ Bilgisayar Mühendisliği Bölümü bitirme projesi teslim tarihi "
                        "her yılın Mayıs ayının son haftasıdır."
            ),
        ]

        # Embedder — 768 boyutlu vektör üretir
        embedder = SentenceTransformersDocumentEmbedder(
            model="sentence-transformers/all-mpnet-base-v2"
        )
        embedder.warm_up()
        result = embedder.run(documents=documents)
        embedded_docs = result["documents"]

        # Veritabanına yaz
        document_store.write_documents(embedded_docs)

        print("✅ Örnek GİBTÜ verileri vektörleştirilip veritabanına kaydedildi!")

    except Exception as e:
        print(f"\033[91m❌ Hata oluştu: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    seed()
