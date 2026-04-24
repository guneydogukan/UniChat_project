"""
BM25 Salt Okunur Doğrulama — Veritabanı Yapılandırması + Stemmer + Pipeline Testi
Bu script HİÇBİR değişiklik yapmaz, sadece okur ve raporlar.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

DB_URL = os.environ["DATABASE_URL"]
out = []

import io, sys as _sys
_sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace')

def log(msg=""):
    out.append(str(msg))
    print(msg)

def db(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ════════════════════════════════════════════════════════════
# BÖLÜM 1: VERİTABANI YAPILANDIRMASI
# ════════════════════════════════════════════════════════════
log("=" * 90)
log("BÖLÜM 1: VERİTABANI YAPILANDIRMASI")
log("=" * 90)

# 1a) Tüm indexler
log("\n--- Tüm Indexler (haystack_docs) ---")
rows = db("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'haystack_docs'")
for r in rows:
    log(f"  {r['indexname']}")
    log(f"    {r['indexdef']}")

# 1b) GIN index detayı
log("\n--- GIN Index (Keyword) ---")
rows = db("SELECT indexdef FROM pg_indexes WHERE indexname = 'unichat_keyword_index'")
if rows:
    log(f"  BULUNDU: {rows[0]['indexdef']}")
else:
    log("  ❌ 'unichat_keyword_index' BULUNAMADI!")

# 1c) Mevcut TS configs
log("\n--- PostgreSQL Text Search Konfigürasyonları ---")
rows = db("SELECT cfgname FROM pg_ts_config ORDER BY cfgname")
for r in rows:
    log(f"  {r['cfgname']}")

# 1d) Turkish dict varlığı
log("\n--- 'turkish' config detayı ---")
rows = db("SELECT cfgname FROM pg_ts_config WHERE cfgname = 'turkish'")
if rows:
    log("  ✅ 'turkish' config PostgreSQL'de mevcut")
else:
    log("  ❌ 'turkish' config YOK!")

# 1e) Toplam doküman sayısı
total = db("SELECT COUNT(*) as c FROM haystack_docs")[0]['c']
log(f"\n--- Toplam Doküman: {total} ---")

# ════════════════════════════════════════════════════════════
# BÖLÜM 2: STEMMER KARŞILAŞTIRMASI
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 2: STEMMER KARŞILAŞTIRMASI (english / simple / turkish)")
log("=" * 90)

words = ["fakülte", "fakülteler", "yönetmelik", "yönetmeliği", "duyuru", "duyurular",
         "hemşirelik", "öğrenci", "öğrencilerin", "sınav", "sınavdan", "transkript",
         "hangi", "var", "almak", "istiyorum", "neler"]

log(f"\n{'Kelime':<22} {'english':<28} {'simple':<28} {'turkish':<28}")
log("-" * 106)
for w in words:
    e = db("SELECT to_tsvector('english', %s)::text as v", (w,))[0]['v']
    s = db("SELECT to_tsvector('simple', %s)::text as v", (w,))[0]['v']
    t = db("SELECT to_tsvector('turkish', %s)::text as v", (w,))[0]['v']
    log(f"  {w:<20} {e:<26} {s:<26} {t:<26}")

# ════════════════════════════════════════════════════════════
# BÖLÜM 3: ÇOK KELİMELİ SORGU ANALİZİ — NEDEN 0 SONUÇ?
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 3: ÇOK KELİMELİ SORGU ANALİZİ (AND semantiği + token eşleşme)")
log("=" * 90)

multi_queries = [
    "hangi fakülteler var",
    "transkript almak istiyorum",
    "son duyurular neler",
    "sınav yönetmeliği ne diyor",
    "hemşirelik mi ebelik mi",
]

for test_q in multi_queries:
    log(f"\n  ── Sorgu: \"{test_q}\" ──")
    for cfg in ['english', 'simple', 'turkish']:
        tsq = db("SELECT plainto_tsquery(%s, %s)::text as v", (cfg, test_q))[0]['v']
        
        # Tam sorgu eşleşmesi
        full_cnt = db(
            "SELECT COUNT(*) as c FROM haystack_docs "
            "WHERE to_tsvector(%s, content) @@ plainto_tsquery(%s, %s)",
            (cfg, cfg, test_q)
        )[0]['c']
        
        marker = '✅' if full_cnt > 0 else '❌'
        log(f"    {cfg:>8} tsquery: {tsq:<55} → {full_cnt:>3} eşleşme {marker}")

# ════════════════════════════════════════════════════════════
# BÖLÜM 4: TEK KELİMELİK KONTROL SORGULARI
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 4: TEK KELİMELİK KONTROL SORGULARI")
log("=" * 90)

single_queries = ["transkript", "duyuru", "erasmus", "fakülte", "yönetmelik", "hemşirelik", "exam", "student"]

log(f"\n{'Sorgu':<20} {'english':>8} {'simple':>8} {'turkish':>8}")
log("-" * 48)
for q in single_queries:
    e = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)", (q,))[0]['c']
    s = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)", (q,))[0]['c']
    t = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,))[0]['c']
    log(f"  {q:<18} {e:>8} {s:>8} {t:>8}")

# ════════════════════════════════════════════════════════════
# BÖLÜM 5: HAYSTACK DOCUMENT STORE LANGUAGE PARAMETRESİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 5: HAYSTACK PgvectorDocumentStore LANGUAGE PARAMETRESİ")
log("=" * 90)

from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

ds = PgvectorDocumentStore(
    connection_string=Secret.from_env_var("DATABASE_URL"),
    table_name="haystack_docs",
    embedding_dimension=768,
    keyword_index_name="unichat_keyword_index",
)

log(f"  ds.language = \"{ds.language}\"")
log(f"  (Varsayılan 'english'. Constructor'a language= parametresi verilmediği için 'english' kullanılıyor.)")

# Rag service'deki konfigürasyon
log(f"\n  rag_service.py'deki PgvectorDocumentStore init:")
log(f"    - language parametresi: VERİLMEMİŞ (varsayılan 'english' kullanılıyor)")
log(f"    - keyword_index_name: 'unichat_keyword_index'")

# ════════════════════════════════════════════════════════════
# BÖLÜM 6: FULL PİPELİNE TESTİ (Vector vs Keyword)
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 6: FULL PİPELİNE TESTİ — Vector vs Keyword bacağı")
log("=" * 90)

from app.services.rag_service import RagService
service = RagService()
service.build_pipeline()

pipe_queries = [
    ("hangi fakülteler var", "çok-kelime"),
    ("transkript almak istiyorum", "çok-kelime"),
    ("son duyurular neler", "çok-kelime"),
    ("sınav yönetmeliği ne diyor", "çok-kelime"),
    ("hemşirelik mi ebelik mi", "çok-kelime"),
    ("transkript", "tek-kelime"),
    ("duyuru", "tek-kelime"),
    ("erasmus", "tek-kelime"),
]

for q, tip in pipe_queries:
    result = service._pipeline.run(
        data={
            "text_embedder": {"text": q},
            "keyword_retriever": {"query": q},
            "prompt_builder": {"question": q},
        },
        include_outputs_from={"joiner", "vector_retriever", "keyword_retriever"},
    )
    v = result.get("vector_retriever", {}).get("documents", [])
    k = result.get("keyword_retriever", {}).get("documents", [])
    j = result.get("joiner", {}).get("documents", [])
    overlap = len({d.id for d in v} & {d.id for d in k})

    log(f"\n  [{tip}] \"{q}\"")
    log(f"    Vector={len(v)} | Keyword={len(k)} | Joiner={len(j)} | Overlap={overlap}")
    if k:
        for i, d in enumerate(k[:2]):
            t = (d.meta.get("title", "?") if d.meta else "?")[:40]
            sc = round(d.score, 4) if d.score else "?"
            log(f"    KW[{i}] s={sc} {t}")
    else:
        log(f"    ❌ Keyword bacağı: 0 sonuç")

# ════════════════════════════════════════════════════════════
# BÖLÜM 7: 'turkish' CONFIG HİPOTETİK FAYDA ANALİZİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("BÖLÜM 7: HİPOTETİK — 'turkish' config kullanılsaydı ne olurdu?")
log("=" * 90)

for q in multi_queries:
    cnt = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,)
    )[0]['c']
    if cnt > 0:
        rows = db(
            "SELECT meta->>'title' as title, meta->>'category' as cat, "
            "ts_rank(to_tsvector('turkish', content), plainto_tsquery('turkish', %s)) as rank "
            "FROM haystack_docs "
            "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s) "
            "ORDER BY rank DESC LIMIT 3", (q, q)
        )
        log(f"\n  \"{q}\" → {cnt} sonuç ✅")
        for r in rows:
            log(f"    rank={float(r['rank']):.4f} [{r['cat']}] {(r['title'] or '?')[:50]}")
    else:
        log(f"\n  \"{q}\" → 0 sonuç ❌")

# KAYDET
report_path = os.path.join(os.path.dirname(__file__), "bm25_diag_readonly_output.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
log(f"\n{'=' * 90}")
log(f"Rapor: {report_path}")
