"""
BM25 Kök Neden Doğrulama — v3 (Kesin Kanıt)
=============================================
Önceki çalıştırmadan bilinen:
  - english, simple config: çok kelimeli sorgular → 0 sonuç
  - tek kelimeli sorgular → çalışıyor
  - PostgreSQL'de 'turkish' config mevcut ama kullanılmıyor

Bu script kesin kök nedeni ortaya koyar:
  1) Neden çok kelimeli sorgu sıfır? (AND semantics + stemming)
  2) 'turkish' config fark yaratır mı?
  3) Pipeline'da keyword bacağı gerçekten 0 mı?
  4) Haystack'in language parametresi nedir?
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

DB_URL = os.environ["DATABASE_URL"]
out = []
def log(msg=""):
    out.append(msg)
    print(msg)

def db(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close(); conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ════════════════════════════════════════════════════════════
# 1) ÜÇ CONFIG KARŞILAŞTIRMASI: english vs simple vs turkish
#    Hem tsvector (içerik indeksleme) hem tsquery (sorgu) tarafı
# ════════════════════════════════════════════════════════════
log("=" * 90)
log("1) STEMMER KARŞILAŞTIRMASI: english / simple / turkish")
log("=" * 90)

words = ["fakülte", "fakülteler", "yönetmelik", "yönetmeliği", "duyuru", "duyurular",
         "hemşirelik", "öğrenci", "öğrencilerin", "sınav", "sınavdan", "transkript"]

log(f"\n{'Kelime':<22} {'english':<24} {'simple':<24} {'turkish':<24}")
log("-" * 94)
for w in words:
    e = db("SELECT to_tsvector('english', %s)::text as v", (w,))[0]['v']
    s = db("SELECT to_tsvector('simple', %s)::text as v", (w,))[0]['v']
    t = db("SELECT to_tsvector('turkish', %s)::text as v", (w,))[0]['v']
    log(f"  {w:<20} {e:<22} {s:<22} {t:<22}")

# ════════════════════════════════════════════════════════════
# 2) NEDEN ÇOK KELİMELİ SORGULAR SIFIR DÖNÜYOR?
#    plainto_tsquery AND semantiği + token uyumsuzluğu analizi
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("2) ÇOK KELİMELİ SORGU ANALİZİ: Neden 0 sonuç?")
log("=" * 90)

test_q = "hangi fakülteler var"
log(f"\nÖrnek sorgu: \"{test_q}\"")
log()

for cfg in ['english', 'simple', 'turkish']:
    tsq = db(f"SELECT plainto_tsquery('{cfg}', %s)::text as v", (test_q,))[0]['v']
    log(f"  {cfg:>8} tsquery: {tsq}")
    # Her bir token'ı ayrı ayrı test et
    tokens = [t.strip().strip("'") for t in tsq.replace("&","").split("'") if t.strip() and t.strip() != "&"]
    # Temizle
    tokens = [t for t in tokens if t and len(t) > 1]
    log(f"           Tokenlar: {tokens}")
    for tok in tokens:
        cnt = db(
            f"SELECT COUNT(*) as c FROM haystack_docs "
            f"WHERE to_tsvector('{cfg}', content) @@ to_tsquery('{cfg}', %s)",
            (tok,)
        )[0]['c']
        log(f"           '{tok}' tek başına: {cnt} eşleşme")
    # Tam sorgu
    full_cnt = db(
        f"SELECT COUNT(*) as c FROM haystack_docs "
        f"WHERE to_tsvector('{cfg}', content) @@ plainto_tsquery('{cfg}', %s)",
        (test_q,)
    )[0]['c']
    log(f"           Tam sorgu (AND): {full_cnt} eşleşme {'✅' if full_cnt > 0 else '❌'}")
    log()

# İkinci örnek: daha teknik bir sorgu
test_q2 = "sınav yönetmeliği ne diyor"
log(f"Örnek sorgu: \"{test_q2}\"")
for cfg in ['english', 'simple', 'turkish']:
    tsq = db(f"SELECT plainto_tsquery('{cfg}', %s)::text as v", (test_q2,))[0]['v']
    full_cnt = db(
        f"SELECT COUNT(*) as c FROM haystack_docs "
        f"WHERE to_tsvector('{cfg}', content) @@ plainto_tsquery('{cfg}', %s)",
        (test_q2,)
    )[0]['c']
    log(f"  {cfg:>8} tsquery: {tsq:<50} → {full_cnt} eşleşme {'✅' if full_cnt > 0 else '❌'}")

# ════════════════════════════════════════════════════════════
# 3) TÜM SORGULARI 3 CONFIG İLE TEST ET
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("3) KAPSAMLI SORGU TESTİ: english / simple / turkish")
log("=" * 90)

queries = [
    # Çok kelimeli Türkçe
    ("hangi fakülteler var", "çok-kelime"),
    ("transkript almak istiyorum", "çok-kelime"),
    ("son duyurular neler", "çok-kelime"),
    ("sınav yönetmeliği ne diyor", "çok-kelime"),
    ("hemşirelik mi ebelik mi", "çok-kelime"),
    ("öğrenci kulüplerine nasıl üye olabilirim", "çok-kelime"),
    # Tek kelime
    ("transkript", "tek-kelime"),
    ("duyuru", "tek-kelime"),
    ("erasmus", "tek-kelime"),
    ("fakülte", "tek-kelime"),
    ("yönetmelik", "tek-kelime"),
    ("hemşirelik", "tek-kelime"),
]

log(f"\n{'Sorgu':<46} {'Tip':<12} {'eng':>5} {'sim':>5} {'tur':>5}")
log("-" * 78)
for q, tip in queries:
    e = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)", (q,))[0]['c']
    s = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)", (q,))[0]['c']
    t = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,))[0]['c']
    best = max(e, s, t)
    marker = ""
    if tip == "çok-kelime" and best > 0:
        winner = "eng" if e == best else ("sim" if s == best else "tur")
        marker = f"  ← {winner} kazandı"
    elif tip == "çok-kelime" and best == 0:
        marker = "  ← hepsi başarısız"
    log(f"  {q:<44} {tip:<10} {e:>5} {s:>5} {t:>5}{marker}")

# ════════════════════════════════════════════════════════════
# 4) HAYSTACK LANGUAGE PARAMETRESİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("4) HAYSTACK PgvectorDocumentStore LANGUAGE PARAMETRESİ")
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
log(f"  (Varsayılan: 'english'. Haystack bu değeri hem index oluştururken")
log(f"   hem de keyword sorgularda to_tsvector/plainto_tsquery içinde kullanır.)")

# ════════════════════════════════════════════════════════════
# 5) PİPELİNE SEVİYESİ: Vector vs Keyword (düzeltilmiş format)
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("5) FULL PİPELİNE: Vector vs Keyword bacağı")
log("=" * 90)

from app.services.rag_service import RagService
service = RagService()
service.build_pipeline()

pipe_queries = [
    "hangi fakülteler var",
    "transkript almak istiyorum",
    "son duyurular neler",
    "hemşirelik mi ebelik mi",
    "erasmus",      # kontrol: tek kelime
    "duyuru",       # kontrol: tek kelime
]

for q in pipe_queries:
    result = service._pipeline.run(
        data={
            "text_embedder": {"text": q},
            "keyword_retriever": {"query": q},
            "prompt_builder": {"question": q},
        },
        include_outputs_from={"joiner", "vector_retriever", "keyword_retriever"},
    )
    j = result.get("joiner", {}).get("documents", [])
    v = result.get("vector_retriever", {}).get("documents", [])
    k = result.get("keyword_retriever", {}).get("documents", [])
    overlap = len({d.id for d in v} & {d.id for d in k})

    log(f"\n  \"{q}\"")
    log(f"    Vector={len(v)} | Keyword={len(k)} | Joiner={len(j)} | Overlap={overlap}")
    if k:
        for i, d in enumerate(k[:2]):
            t = (d.meta.get("title","?") if d.meta else "?")[:40]
            sc = round(d.score, 3) if d.score else "?"
            log(f"    KW[{i}] s={sc} {t}")
    else:
        log(f"    ❌ Keyword bacağı: 0 sonuç")

# ════════════════════════════════════════════════════════════
# 6) 'turkish' CONFIG İLE HİPOTETİK FAYDA ANALİZİ
#    (sadece DB sorgusu — pipeline değiştirilmiyor)
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("6) HİPOTETİK: 'turkish' config kullanılsaydı ne olurdu?")
log("=" * 90)

for q, tip in queries:
    if tip != "çok-kelime":
        continue
    cnt = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,)
    )[0]['c']
    if cnt > 0:
        # İlk 3 sonucu göster
        rows = db(
            "SELECT meta->>'title' as title, meta->>'category' as cat, "
            "ts_rank(to_tsvector('turkish', content), plainto_tsquery('turkish', %s)) as rank "
            "FROM haystack_docs "
            "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s) "
            "ORDER BY rank DESC LIMIT 3", (q, q)
        )
        log(f"\n  \"{q}\" → {cnt} sonuç ✅")
        for r in rows:
            log(f"    rank={r['rank']:.4f} [{r['cat']}] {(r['title'] or '?')[:50]}")
    else:
        log(f"\n  \"{q}\" → 0 sonuç ❌ (turkish de çözmüyor)")

# KAYDET
report_path = os.path.join(os.path.dirname(__file__), "bm25_validation_output.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
log(f"\n{'='*90}")
log(f"Rapor: {report_path}")
