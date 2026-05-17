"""
UniChat — Latency Diagnostic Tool
Cold start ve warm response olcumlerini yapar.

Kullanim:
    python latency_diag.py
"""

import os
import sys
import time
import logging
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:gizlisifre@localhost:5433/postgres")

# Suppress verbose logging, only show latency lines
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    stream=sys.stderr,
)
# Enable latency logging from rag_service
logging.getLogger("app.services.rag_service").setLevel(logging.INFO)

# Use a handler with utf-8
for handler in logging.root.handlers:
    if hasattr(handler, 'stream'):
        handler.stream = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from app.services.rag_service import RagService

QUERIES = [
    "Bilgisayar muhendisligi bolumunde kac ogretim uyesi var?",
    "Erasmus programina nasil basvurabilirim?",
    "GIBTU'de hangi fakulteler var?",
    "Devamsizlik siniri nedir?",
]


def main():
    print("=" * 70)
    print("UniChat Latency Diagnostic")
    print("=" * 70)

    # Cold start: pipeline build
    t0 = time.perf_counter()
    rag = RagService()
    rag.build_pipeline()
    cold_build = time.perf_counter() - t0
    print(f"\nPipeline build (cold start): {cold_build:.2f}s")

    # Cold query
    print(f"\n{'_' * 50}")
    print("Cold query (ilk sorgu):")
    t0 = time.perf_counter()
    result = rag.query(QUERIES[0])
    cold_query = time.perf_counter() - t0
    resp_len = len(result.get("response") or "")
    src_count = len(result.get("sources", []))
    print(f"  Sure: {cold_query:.2f}s | Yanit: {resp_len} kar | Kaynak: {src_count}")

    # Warm queries
    print(f"\n{'_' * 50}")
    print("Warm queries:")
    warm_times = []
    for i, q in enumerate(QUERIES[1:], 1):
        t0 = time.perf_counter()
        result = rag.query(q)
        elapsed = time.perf_counter() - t0
        warm_times.append(elapsed)
        resp_len = len(result.get("response") or "")
        src_count = len(result.get("sources", []))
        print(f"  [{i}] {elapsed:.2f}s | Yanit: {resp_len} kar | Kaynak: {src_count} | {q[:50]}")

    avg_warm = sum(warm_times) / len(warm_times) if warm_times else 0

    # Summary
    print(f"\n{'=' * 70}")
    print("OZET")
    print(f"{'=' * 70}")
    print(f"  Pipeline build:     {cold_build:.2f}s")
    print(f"  Cold query:         {cold_query:.2f}s")
    print(f"  Warm query avg:     {avg_warm:.2f}s")
    print(f"  Warm query min:     {min(warm_times):.2f}s")
    print(f"  Warm query max:     {max(warm_times):.2f}s")
    print(f"\n  Darbogaz analizi:")
    if avg_warm > 15:
        print(f"  [!] Warm avg {avg_warm:.1f}s > 15s -- LLM generation darbogaz")
        print(f"  [i] Oneri: Ollama num_ctx azaltma, model preload, veya GPU kontrol")
    elif avg_warm > 10:
        print(f"  [!] Warm avg {avg_warm:.1f}s > 10s -- orta duzey, LLM hala baskin")
    else:
        print(f"  [OK] Warm avg {avg_warm:.1f}s -- kabul edilebilir")
    print()


if __name__ == "__main__":
    main()
