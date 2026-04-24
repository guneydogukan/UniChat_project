"""GIN index yeniden oluşturma: english → turkish"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
cur = conn.cursor()

# 1) Mevcut index
cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'unichat_keyword_index'")
old = cur.fetchone()
print(f"MEVCUT INDEX: {old[0] if old else 'YOK'}")

# 2) Drop
print("DROP INDEX...")
cur.execute("DROP INDEX IF EXISTS unichat_keyword_index")
print("  Silindi.")

# 3) Create with turkish
print("CREATE INDEX (turkish)...")
cur.execute("CREATE INDEX unichat_keyword_index ON public.haystack_docs USING GIN (to_tsvector('turkish', content))")
print("  Olusturuldu.")

# 4) Dogrula
cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'unichat_keyword_index'")
new = cur.fetchone()
print(f"YENI INDEX: {new[0] if new else 'HATA!'}")

cur.close()
conn.close()
print("TAMAM.")
