"""
BM25 Turkish Config Tam Fayda Analizi — Salt Okunur
====================================================
Rapordaki 5. adim: language='turkish' ile tum cok kelimeli sorgularin
ne kadar sonuc dondurdugunu olcer. Ek olarak websearch_to_tsquery (OR)
ve phraseto_tsquery alternatifleri de test edilir.
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

DB_URL = os.environ["DATABASE_URL"]
out = []

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

# Test sorguları
multi_queries = [
    "hangi fakülteler var",
    "transkript almak istiyorum",
    "son duyurular neler",
    "sınav yönetmeliği ne diyor",
    "hemşirelik mi ebelik mi",
]

# ════════════════════════════════════════════════════════════════
# BOLUM 1: plainto_tsquery — 3 config karsilastirmasi (AND)
# ════════════════════════════════════════════════════════════════
log("=" * 100)
log("BOLUM 1: plainto_tsquery (AND) — english / simple / turkish")
log("=" * 100)

log(f"\n{'Sorgu':<42} {'eng':>5} {'sim':>5} {'tur':>5}  tsquery (turkish)")
log("-" * 100)

for q in multi_queries:
    e = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)", (q,))[0]['c']
    s = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)", (q,))[0]['c']
    t = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,))[0]['c']
    tsq = db("SELECT plainto_tsquery('turkish', %s)::text as v", (q,))[0]['v']
    marker = " <-- turkish kazandi" if t > max(e, s) else (" <-- hepsi basarisiz" if max(e, s, t) == 0 else "")
    log(f"  {q:<40} {e:>5} {s:>5} {t:>5}  {tsq}{marker}")

# ════════════════════════════════════════════════════════════════
# BOLUM 2: turkish plainto_tsquery — Detayli sonuc incelemeleri
# ════════════════════════════════════════════════════════════════
log()
log("=" * 100)
log("BOLUM 2: turkish plainto_tsquery — Detayli sonuc incelemeleri")
log("=" * 100)

for q in multi_queries:
    cnt = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,)
    )[0]['c']
    log(f"\n  Sorgu: \"{q}\" --> {cnt} sonuc {'(BASARISIZ)' if cnt == 0 else ''}")
    
    # tsquery'nin token analizi
    tsq = db("SELECT plainto_tsquery('turkish', %s)::text as v", (q,))[0]['v']
    log(f"  tsquery: {tsq}")
    
    # Her token'in tek basina kac sonuc dondurdugunu goster
    tokens = [t.strip().strip("'") for t in tsq.replace("&", " ").split("'") if t.strip() and len(t.strip()) > 1 and t.strip() != "&"]
    tokens = [t for t in tokens if t and len(t) > 0]
    for tok in tokens:
        try:
            tok_cnt = db(
                "SELECT COUNT(*) as c FROM haystack_docs "
                "WHERE to_tsvector('turkish', content) @@ to_tsquery('turkish', %s)", (tok,)
            )[0]['c']
            log(f"    token '{tok}' tek basina: {tok_cnt} eslesme")
        except Exception as ex:
            log(f"    token '{tok}' hata: {ex}")
    
    if cnt > 0:
        rows = db(
            "SELECT meta->>'title' as title, meta->>'category' as cat, "
            "ts_rank(to_tsvector('turkish', content), plainto_tsquery('turkish', %s)) as rank "
            "FROM haystack_docs "
            "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s) "
            "ORDER BY rank DESC LIMIT 5", (q, q)
        )
        for r in rows:
            log(f"    rank={float(r['rank']):.4f} [{r['cat']}] {(r['title'] or '?')[:60]}")

# ════════════════════════════════════════════════════════════════
# BOLUM 3: websearch_to_tsquery (OR destekli) — turkish config
# ════════════════════════════════════════════════════════════════
log()
log("=" * 100)
log("BOLUM 3: websearch_to_tsquery (OR destekli) — turkish config")
log("  websearch_to_tsquery kelimeler arasi OR kullanabilir, daha esnek.")
log("=" * 100)

# websearch_to_tsquery varsayilan olarak OR kullanir (kelimeler arasi bosluk = AND ama
# "or" kelimesi ile OR yapilabilir). Ama aslinda varsayilani AND'dir.
# Gercek avantaj: "-" ile exclude, "" ile phrase arama destegi.
# OR icin kelimeler arasina "or" eklememiz gerekir.

log(f"\n{'Sorgu':<42} {'AND(plain)':>10} {'AND(web)':>10}  websearch tsquery")
log("-" * 100)

for q in multi_queries:
    plain_cnt = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,)
    )[0]['c']
    
    web_cnt = db(
        "SELECT COUNT(*) as c FROM haystack_docs "
        "WHERE to_tsvector('turkish', content) @@ websearch_to_tsquery('turkish', %s)", (q,)
    )[0]['c']
    
    web_tsq = db("SELECT websearch_to_tsquery('turkish', %s)::text as v", (q,))[0]['v']
    
    log(f"  {q:<40} {plain_cnt:>10} {web_cnt:>10}  {web_tsq}")

# ════════════════════════════════════════════════════════════════
# BOLUM 4: OR semantigi ile manuel test — turkish config
# Kelimeleri | (OR) ile birlestirerek test
# ════════════════════════════════════════════════════════════════
log()
log("=" * 100)
log("BOLUM 4: Manuel OR semantigi — turkish config")
log("  Kelimeleri | ile birlestirip to_tsquery kullanarak OR araması")
log("=" * 100)

for q in multi_queries:
    # Kelimeleri ayir, turkish stemmer'dan gecir ve OR ile birlestir
    words = q.split()
    # Oncelikle her kelimenin tsvector'daki karsiligini bul
    stemmed = []
    for w in words:
        tv = db("SELECT to_tsvector('turkish', %s)::text as v", (w,))[0]['v']
        # tsvector formatindan token'i cikar: 'token':1 -> token
        if tv and "'" in tv:
            token = tv.split("'")[1]
            stemmed.append(token)
    
    if stemmed:
        or_query = " | ".join(f"'{s}'" for s in stemmed)
        try:
            or_cnt = db(
                "SELECT COUNT(*) as c FROM haystack_docs "
                "WHERE to_tsvector('turkish', content) @@ to_tsquery('turkish', %s)", (or_query,)
            )[0]['c']
            
            log(f"\n  Sorgu: \"{q}\"")
            log(f"  OR tsquery: {or_query}")
            log(f"  Sonuc: {or_cnt} eslesme {'(BASARISIZ)' if or_cnt == 0 else ''}")
            
            if or_cnt > 0:
                rows = db(
                    "SELECT meta->>'title' as title, meta->>'category' as cat, "
                    "ts_rank(to_tsvector('turkish', content), to_tsquery('turkish', %s)) as rank "
                    "FROM haystack_docs "
                    "WHERE to_tsvector('turkish', content) @@ to_tsquery('turkish', %s) "
                    "ORDER BY rank DESC LIMIT 5", (or_query, or_query)
                )
                for r in rows:
                    log(f"    rank={float(r['rank']):.4f} [{r['cat']}] {(r['title'] or '?')[:60]}")
        except Exception as ex:
            log(f"  OR sorgu hatasi: {ex}")
    else:
        log(f"\n  Sorgu: \"{q}\" --> stemmed token bulunamadi")

# ════════════════════════════════════════════════════════════════
# BOLUM 5: Stopword temizleme + AND — turkish config
# Turkce stopword'leri cikarip sadece anlamli kelimeleri AND ile arama
# ════════════════════════════════════════════════════════════════
log()
log("=" * 100)
log("BOLUM 5: Stopword temizleme + AND — turkish config")
log("  Turkce yaygın kelimeleri cikarip sadece anlamli terimleri AND ile arama")
log("=" * 100)

turkish_stopwords = {
    "hangi", "var", "mi", "mu", "ne", "neler", "nedir", "nasıl",
    "almak", "istiyorum", "son", "diyor", "bir", "bu", "şu", "o",
    "ve", "veya", "ile", "için", "de", "da", "den", "dan", "mı",
    "olan", "olarak", "gibi"
}

for q in multi_queries:
    words = q.split()
    meaningful = [w for w in words if w.lower() not in turkish_stopwords]
    
    log(f"\n  Sorgu: \"{q}\"")
    log(f"  Temizlenmis: \"{' '.join(meaningful)}\" (cikarilan: {[w for w in words if w.lower() in turkish_stopwords]})")
    
    if meaningful:
        clean_q = " ".join(meaningful)
        
        # AND ile arama (plainto_tsquery)
        and_cnt = db(
            "SELECT COUNT(*) as c FROM haystack_docs "
            "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (clean_q,)
        )[0]['c']
        and_tsq = db("SELECT plainto_tsquery('turkish', %s)::text as v", (clean_q,))[0]['v']
        
        log(f"  AND sonuc: {and_cnt} eslesme | tsquery: {and_tsq}")
        
        if and_cnt > 0:
            rows = db(
                "SELECT meta->>'title' as title, meta->>'category' as cat, "
                "ts_rank(to_tsvector('turkish', content), plainto_tsquery('turkish', %s)) as rank "
                "FROM haystack_docs "
                "WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s) "
                "ORDER BY rank DESC LIMIT 5", (clean_q, clean_q)
            )
            for r in rows:
                log(f"    rank={float(r['rank']):.4f} [{r['cat']}] {(r['title'] or '?')[:60]}")
    else:
        log(f"  Tum kelimeler stopword — sorgu bos kaldi!")

# ════════════════════════════════════════════════════════════════
# BOLUM 6: OZET KARSILASTIRMA TABLOSU
# ════════════════════════════════════════════════════════════════
log()
log("=" * 100)
log("BOLUM 6: OZET KARSILASTIRMA TABLOSU — Tum Stratejiler")
log("=" * 100)

log(f"\n{'Sorgu':<35} {'eng+AND':>8} {'tur+AND':>8} {'tur+OR':>8} {'tur+SW':>8}")
log("-" * 75)

for q in multi_queries:
    # 1) english + plainto (mevcut durum)
    eng_and = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)", (q,))[0]['c']
    
    # 2) turkish + plainto (sadece dil degisikligi)
    tur_and = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (q,))[0]['c']
    
    # 3) turkish + OR (tum kelimeler OR)
    words = q.split()
    stemmed = []
    for w in words:
        tv = db("SELECT to_tsvector('turkish', %s)::text as v", (w,))[0]['v']
        if tv and "'" in tv:
            stemmed.append(tv.split("'")[1])
    if stemmed:
        or_q = " | ".join(f"'{s}'" for s in stemmed)
        try:
            tur_or = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ to_tsquery('turkish', %s)", (or_q,))[0]['c']
        except:
            tur_or = -1
    else:
        tur_or = 0
    
    # 4) turkish + stopword temizleme + AND
    meaningful = [w for w in words if w.lower() not in turkish_stopwords]
    if meaningful:
        clean = " ".join(meaningful)
        tur_sw = db("SELECT COUNT(*) as c FROM haystack_docs WHERE to_tsvector('turkish', content) @@ plainto_tsquery('turkish', %s)", (clean,))[0]['c']
    else:
        tur_sw = 0
    
    log(f"  {q:<33} {eng_and:>8} {tur_and:>8} {tur_or:>8} {tur_sw:>8}")

log(f"\n  eng+AND = Mevcut durum (english config, plainto_tsquery AND)")
log(f"  tur+AND = Sadece language='turkish' degisikligi")
log(f"  tur+OR  = turkish config + tum kelimeler OR ile aranir")
log(f"  tur+SW  = turkish config + Turkce stopword temizleme + AND")

# KAYDET
report_path = os.path.join(os.path.dirname(__file__), "bm25_turkish_benefit_output.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
log(f"\n{'=' * 100}")
log(f"Rapor: {report_path}")
