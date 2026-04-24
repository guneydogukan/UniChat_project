"""Quick verification of 3.4 ingestion results."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM haystack_docs")
print(f"Toplam chunk: {cur.fetchone()[0]}")

# Spor category
cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'category' = 'spor'")
print(f"Spor kategori: {cur.fetchone()[0]}")

# Personel doc_kind
cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'doc_kind' = 'personel'")
print(f"Personel doc_kind: {cur.fetchone()[0]}")

# Distinct departments with personel
cur.execute("SELECT COUNT(DISTINCT meta->>'department') FROM haystack_docs WHERE meta->>'doc_kind' = 'personel'")
print(f"Personel birim sayisi: {cur.fetchone()[0]}")

# Metadata check for new spor records
cur.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN meta->>'title' IS NOT NULL AND meta->>'title' != '' THEN 1 ELSE 0 END) as titled,
           SUM(CASE WHEN meta->>'source_url' IS NOT NULL AND meta->>'source_url' != '' THEN 1 ELSE 0 END) as url_ok
    FROM haystack_docs WHERE meta->>'category' = 'spor'
""")
r = cur.fetchone()
pct = f"{r[1]/r[0]*100:.0f}%" if r[0] > 0 else "N/A"
print(f"Spor metadata: title {r[1]}/{r[0]} ({pct}), url {r[2]}/{r[0]}")

cur.close(); conn.close()
