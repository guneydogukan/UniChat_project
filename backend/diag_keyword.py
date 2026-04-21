"""Keyword index and BM25 diagnosis"""
import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('../.env')
import psycopg2

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# 1) Keyword index check
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'haystack_docs' AND indexname ILIKE '%%keyword%%'")
rows = cur.fetchall()
print("=== KEYWORD INDEXES ===")
for r in rows:
    print(f"  {r[0]}: {r[1][:250]}")
if not rows:
    print("  ❌ NO KEYWORD INDEX FOUND!")

# 2) All indexes on table
cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'haystack_docs'")
print("\n=== ALL INDEXES ===")
for r in cur.fetchall():
    print(f"  {r[0]}")

# 3) Table columns
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='haystack_docs' ORDER BY ordinal_position")
print("\n=== TABLE COLUMNS ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# 4) Manual keyword search test
try:
    cur.execute("""
        SELECT meta->>'title' as title, 
               ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', %s)) as rank
        FROM haystack_docs
        WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)
        ORDER BY rank DESC LIMIT 5
    """, ('transkript', 'transkript'))
    print("\n=== MANUAL KEYWORD: 'transkript' ===")
    for r in cur.fetchall():
        print(f"  rank={r[1]:.4f} {r[0][:60]}")
except Exception as e:
    print(f"\n=== MANUAL KEYWORD FAILED: {e}")

# 5) Check if Haystack PgvectorKeywordRetriever looks for a specific column
try:
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE content ILIKE %s", ('%transkript%',))
    print(f"\n=== ILIKE 'transkript': {cur.fetchone()[0]} rows (working, not same as BM25)")
except Exception as e:
    print(f"ILIKE check failed: {e}")

# 6) Test PgvectorKeywordRetriever directly
print("\n=== PgvectorKeywordRetriever DIRECT TEST ===")
from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import PgvectorKeywordRetriever

ds = PgvectorDocumentStore(
    connection_string=Secret.from_env_var("DATABASE_URL"),
    table_name="haystack_docs",
    embedding_dimension=768,
    keyword_index_name="unichat_keyword_index",
)

kr = PgvectorKeywordRetriever(document_store=ds, top_k=5)

# Run keyword retrieval
for query in ["transkript", "fakülte", "duyuru", "sınav yönetmeliği"]:
    result = kr.run(query=query)
    docs = result.get("documents", [])
    print(f"\n  Query: '{query}' → {len(docs)} results")
    for i, d in enumerate(docs[:3]):
        t = (d.meta.get("title","?") if d.meta else "?")[:50]
        print(f"    [{i}] score={d.score:.4f if d.score else '?'} {t}")

conn.close()
