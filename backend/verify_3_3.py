"""Quick verification of 3.3 ingestion results."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

db = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM haystack_docs")
print(f"Toplam chunk: {cur.fetchone()[0]}")

for cat in ["lisansustu", "dijital_hizmetler", "erasmus"]:
    cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'category' = %s", (cat,))
    cnt = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM haystack_docs
        WHERE meta->>'category' = %s AND meta->>'title' IS NOT NULL AND meta->>'title' != ''
    """, (cat,))
    titled = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM haystack_docs
        WHERE meta->>'category' = %s AND meta->>'source_url' IS NOT NULL AND meta->>'source_url' != ''
    """, (cat,))
    url_ok = cur.fetchone()[0]
    pct = f"{titled/cnt*100:.0f}%" if cnt > 0 else "N/A"
    print(f"  {cat:25s} {cnt:>5} chunk | title: {titled}/{cnt} ({pct}) | url: {url_ok}/{cnt}")

cur.close(); conn.close()
