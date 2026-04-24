"""Check existing personnel + SKS data in DB."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

# Existing personnel docs
cur.execute("SELECT DISTINCT meta->>'department' FROM haystack_docs WHERE meta->>'doc_kind'='personel' ORDER BY 1")
depts = [r[0] for r in cur.fetchall()]
print(f"=== Personel verisi olan birimler ({len(depts)}) ===")
for d in depts:
    print(f"  - {d}")

# Check SKS (BirimID=8)
cur.execute("SELECT COUNT(*) FROM haystack_docs WHERE meta->>'department' ILIKE '%sks%' OR meta->>'department' ILIKE '%Saglik Kultur%' OR meta->>'department' ILIKE '%saglik_kultur%'")
sks = cur.fetchone()[0]
print(f"\nSKS chunk: {sks}")

# All categories
cur.execute("SELECT meta->>'category', COUNT(*) FROM haystack_docs GROUP BY 1 ORDER BY 2 DESC")
print("\n=== Kategori Dagilimi ===")
for r in cur.fetchall():
    print(f"  {r[0]:30s} {r[1]:>5}")

# All birim IDs that have been scraped
cur.execute("SELECT DISTINCT meta->>'birim_id' FROM haystack_docs WHERE meta->>'birim_id' IS NOT NULL ORDER BY 1")
bids = [r[0] for r in cur.fetchall()]
print(f"\n=== Scrape edilen BirimID'ler ({len(bids)}) ===")
print(f"  {', '.join(bids)}")

cur.close(); conn.close()
