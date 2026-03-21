"""Quick test to get the full traceback from the RAG pipeline."""
import os
import sys
import traceback

sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:gizlisifre@localhost:5433/postgres")

from app.services.rag_service import rag_service

try:
    rag_service.build_pipeline()
    print("PIPELINE OK")
except Exception:
    traceback.print_exc()
    sys.exit(1)

try:
    result = rag_service.query("Yemekhane kurallari nelerdir")
    print("RESPONSE:", result["response"][:200] if result["response"] else "NONE")
    print("SOURCES:", len(result["sources"]))
except Exception:
    print("QUERY ERROR:")
    traceback.print_exc()
    sys.exit(1)
