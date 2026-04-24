"""
BM25 Fix Dogrulama Testi
========================
Degisiklikler uygulandiktan sonra keyword retrieval'in calismini dogrular.
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

DB_URL = os.environ["DATABASE_URL"]

def db(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ═══════════════════════════════════════════════
# 1) GIN INDEX DOGRULAMA
# ═══════════════════════════════════════════════
print("=" * 80)
print("1) GIN INDEX DOGRULAMA")
print("=" * 80)
rows = db("SELECT indexdef FROM pg_indexes WHERE indexname = 'unichat_keyword_index'")
if rows:
    idx = rows[0]['indexdef']
    is_turkish = "'turkish'" in idx
    print(f"  Index: {idx}")
    print(f"  Turkish config: {'EVET' if is_turkish else 'HAYIR -- HATA!'}")
else:
    print("  INDEX BULUNAMADI!")

# ═══════════════════════════════════════════════
# 2) HAYSTACK LANGUAGE PARAMETRESI
# ═══════════════════════════════════════════════
print()
print("=" * 80)
print("2) HAYSTACK LANGUAGE PARAMETRESI")
print("=" * 80)
from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

ds = PgvectorDocumentStore(
    connection_string=Secret.from_env_var("DATABASE_URL"),
    table_name="haystack_docs",
    embedding_dimension=768,
    language="turkish",
    keyword_index_name="unichat_keyword_index",
)
print(f"  ds.language = \"{ds.language}\"")
print(f"  Beklenen: 'turkish' --> {'DOGRU' if ds.language == 'turkish' else 'YANLIS!'}")

# ═══════════════════════════════════════════════
# 3) STOPWORD ON-ISLEME DOGRULAMA
# ═══════════════════════════════════════════════
print()
print("=" * 80)
print("3) STOPWORD ON-ISLEME DOGRULAMA")
print("=" * 80)
from app.services.rag_service import RagService

test_pairs = [
    ("hangi fakülteler var", "fakülteler"),
    ("transkript almak istiyorum", "transkript"),
    ("son duyurular neler", "duyurular"),
    ("sınav yönetmeliği ne diyor", "sınav yönetmeliği"),
    ("hemşirelik mi ebelik mi", "hemşirelik ebelik"),
]

for original, expected in test_pairs:
    cleaned = RagService._clean_keyword_query(original)
    ok = cleaned == expected
    print(f"  \"{original}\"")
    print(f"    --> \"{cleaned}\" {'DOGRU' if ok else f'BEKLENEN: \"{expected}\" -- YANLIS!'}")
    print()

# ═══════════════════════════════════════════════
# 4) DB SEVIYESI SORGU TESTI (turkish + temizlenmis)
# ═══════════════════════════════════════════════
print("=" * 80)
print("4) DB SEVIYESI SORGU TESTI — turkish config + temizlenmis sorgu")
print("=" * 80)

multi_queries = [
    "hangi fakülteler var",
    "transkript almak istiyorum",
    "son duyurular neler",
    "sınav yönetmeliği ne diyor",
    "hemşirelik mi ebelik mi",
]

print(f"\n{'Sorgu':<40} {'Eski(eng)':>10} {'Yeni(tur+SW)':>12}")
print("-" * 68)

for q in multi_queries:
    # Eski: english, ham sorgu
    old = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)", (q,)
    )[0]['c']
    
    # Yeni: turkish, temizlenmis sorgu
    cleaned = RagService._clean_keyword_query(q)
    new = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (cleaned,)
    )[0]['c']
    
    marker = "DUZELTILDI" if old == 0 and new > 0 else ("ZATEN CALISIYOR" if old > 0 else "HALA SORUNLU!")
    print(f"  {q:<38} {old:>10} {new:>12}  {marker}")

# ═══════════════════════════════════════════════
# 5) FULL PIPELINE TESTI
# ═══════════════════════════════════════════════
print()
print("=" * 80)
print("5) FULL PIPELINE TESTI — Keyword bacagi artik calisiyor mu?")
print("=" * 80)

service = RagService()
service.build_pipeline()

for q in multi_queries + ["transkript", "erasmus"]:
    # Keyword query temizle
    kw_query = RagService._clean_keyword_query(q)
    
    result = service._pipeline.run(
        data={
            "text_embedder": {"text": q},
            "keyword_retriever": {"query": kw_query},
            "prompt_builder": {"question": q},
        },
        include_outputs_from={"joiner", "vector_retriever", "keyword_retriever"},
    )
    v = result.get("vector_retriever", {}).get("documents", [])
    k = result.get("keyword_retriever", {}).get("documents", [])
    j = result.get("joiner", {}).get("documents", [])
    overlap = len({d.id for d in v} & {d.id for d in k})
    
    kw_info = f"Keyword={len(k)}" + (" DUZELTILDI!" if len(k) > 0 and " " in q else "")
    print(f"\n  \"{q}\"" + (f" --> kw:\"{kw_query}\"" if kw_query != q else ""))
    print(f"    Vector={len(v)} | {kw_info} | Joiner={len(j)} | Overlap={overlap}")
    if k:
        for i, d in enumerate(k[:2]):
            t = (d.meta.get("title", "?") if d.meta else "?")[:50]
            sc = round(d.score, 4) if d.score else "?"
            print(f"    KW[{i}] s={sc} {t}")

print()
print("=" * 80)
print("DOGRULAMA TAMAMLANDI")
print("=" * 80)
