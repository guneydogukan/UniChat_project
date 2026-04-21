"""
UniChat — Bulgu Doğrulama Scripti v2
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2

DB_URL = os.environ["DATABASE_URL"]

def db_query(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

output = []
def log(msg):
    output.append(msg)
    print(msg)

# ═══════════════════════════════════════════════
# 1: Fakülte listesi chunk
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 1: 'Fakülte listesi' içeren chunk var mı?")
log("="*80)

rows = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, meta->>'doc_kind' as dk, "
    "meta->>'department' as dept, LEFT(content, 200) as preview, LENGTH(content) as len "
    "FROM haystack_docs WHERE content ILIKE %s ORDER BY LENGTH(content) DESC LIMIT 15",
    ('%fakülte%',)
)
log(f"'fakülte' içeren chunk: {len(rows)}")
for r in rows[:8]:
    log(f"  [{r['cat']}/{r['dk']}] {(r['title'] or '?')[:55]} dept={( r['dept'] or '?')[:25]} ({r['len']} kar)")

# Birden fazla fakülte adını aynı anda içeren
rows2 = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, LEFT(content, 300) as preview "
    "FROM haystack_docs WHERE content ILIKE %s AND content ILIKE %s LIMIT 10",
    ('%ilahiyat%', '%mühendislik%')
)
log(f"\nHem 'ilahiyat' hem 'mühendislik' geçen chunk: {len(rows2)}")
for r in rows2[:5]:
    log(f"  [{r['cat']}] {(r['title'] or '?')[:55]}")
    log(f"    {r['preview'][:150].replace(chr(10),' ')}...")

rows3 = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, meta->>'source_url' as url, LEFT(content, 200) as preview "
    "FROM haystack_docs WHERE meta->>'title' ILIKE %s OR meta->>'source_url' ILIKE %s OR "
    "meta->>'title' ILIKE %s OR meta->>'source_url' ILIKE %s LIMIT 10",
    ('%akademik birim%', '%akademikbirim%', '%birim rehber%', '%birimrehber%')
)
log(f"\n'akademik birim'/'birim rehber' sayfaları: {len(rows3)}")
for r in rows3[:5]:
    log(f"  [{r['cat']}] {(r['title'] or '?')[:55]} — {(r['url'] or '?')[:70]}")
    log(f"    {r['preview'][:150].replace(chr(10),' ')}...")

# ═══════════════════════════════════════════════
# 2: Transkript → Öğrenci İşleri yönlendirmesi
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 2: 'transkript' verisi")
log("="*80)

rows_t = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, meta->>'doc_kind' as dk, "
    "meta->>'department' as dept, LEFT(content, 150) as preview "
    "FROM haystack_docs WHERE content ILIKE %s LIMIT 15",
    ('%transkript%',)
)
log(f"'transkript' içeren chunk: {len(rows_t)}")
for r in rows_t[:8]:
    log(f"  [{r['cat']}/{r['dk']}] {(r['title'] or '?')[:45]} dept={( r['dept'] or '?')[:25]}")

# ═══════════════════════════════════════════════
# 3: Hemşirelik vs Ebelik karşılaştırma
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 3: Hemşirelik + Ebelik aynı chunk")
log("="*80)

rows_he = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, LEFT(content, 200) as preview "
    "FROM haystack_docs WHERE content ILIKE %s AND content ILIKE %s LIMIT 10",
    ('%hemşirelik%', '%ebelik%')
)
log(f"Hem 'hemşirelik' hem 'ebelik' geçen chunk: {len(rows_he)}")
for b in ["hemşirelik", "ebelik"]:
    cnt = db_query("SELECT COUNT(*) as c FROM haystack_docs WHERE content ILIKE %s", (f'%{b}%',))
    log(f"  '{b}' geçen chunk: {cnt[0]['c']}")

# ═══════════════════════════════════════════════
# 4: Guardrail analizi
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 4: Prompt guardrail kuralları")
log("="*80)

from app.services.rag_service import PROMPT_TEMPLATE
for i, line in enumerate(PROMPT_TEMPLATE.split("\n")):
    if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.")):
        log(f"  Kural: {line.strip()}")

log("\nÇELİŞKİ ANALİZİ:")
log("  - Kural 2: 'Belgede cevap yoksa ... [ilgili birimi belirt] birimine başvurun' → HER durumda birim öneriyor")
log("  - Kural 7: 'Üniversite dışı konularda cevap verme; kibarca sınırlı olduğunu belirt' → birim önerme kuralı yok")
log("  - Kural 8: 'Yanıtın sonunda başvurabileceği birimi belirt' → kapsam dışı sorular için de tetikleniyor")
log("  SONUÇ: Kural 2 ve 8, Kural 7 ile çelişiyor. LLM kapsam dışı sorularda bile Kural 2/8'e uyuyor.")

# ═══════════════════════════════════════════════
# 5: Duyuru chunk'ları
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 5: Duyuru verisi")
log("="*80)

cnt_duyuru = db_query("SELECT COUNT(*) as c FROM haystack_docs WHERE meta->>'doc_kind' = %s", ('duyuru',))
log(f"doc_kind='duyuru' toplam chunk: {cnt_duyuru[0]['c']}")

rows_d = db_query(
    "SELECT meta->>'title' as title, meta->>'department' as dept, LEFT(content, 120) as preview "
    "FROM haystack_docs WHERE meta->>'doc_kind' = %s ORDER BY RANDOM() LIMIT 5", ('duyuru',)
)
for r in rows_d:
    log(f"  [{(r['dept'] or '?')[:20]}] {(r['title'] or '?')[:60]}")
    log(f"    {r['preview'][:100].replace(chr(10),' ')}...")

# ═══════════════════════════════════════════════
# 6: Akademik takvim
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 6: 'Akademik takvim' verisi")
log("="*80)

rows_at = db_query(
    "SELECT meta->>'title' as title, meta->>'category' as cat, meta->>'source_url' as url, LEFT(content, 200) as preview "
    "FROM haystack_docs WHERE content ILIKE %s OR meta->>'title' ILIKE %s LIMIT 10",
    ('%akademik takvim%', '%akademik takvim%')
)
log(f"'akademik takvim' chunk: {len(rows_at)}")
for r in rows_at[:5]:
    log(f"  [{r['cat']}] {(r['title'] or '?')[:55]} — {(r['url'] or '?')[:70]}")
    log(f"    {r['preview'][:140].replace(chr(10),' ')}...")

# ═══════════════════════════════════════════════
# 7: contact_unit doluluk
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 7: contact_unit metadata doluluk")
log("="*80)

total = db_query("SELECT COUNT(*) as c FROM haystack_docs", ())[0]['c']
with_cu = db_query("SELECT COUNT(*) as c FROM haystack_docs WHERE meta->>'contact_unit' IS NOT NULL AND meta->>'contact_unit' != ''", ())[0]['c']
log(f"Toplam chunk: {total}")
log(f"contact_unit dolu: {with_cu} ({with_cu/total*100:.1f}%)")

# ═══════════════════════════════════════════════
# 8: Duplicates & garbled
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 8: Tekrarlı ve bozuk içerik")
log("="*80)

dups = db_query(
    "SELECT LEFT(content, 80) as preview, COUNT(*) as cnt FROM haystack_docs "
    "GROUP BY content HAVING COUNT(*) > 1 ORDER BY cnt DESC LIMIT 10", ()
)
log(f"Tekrarlı içerik grupları: {len(dups)}")
for d in dups:
    p = d['preview'].replace('\n',' ').replace('\r','')
    is_garbled = any(ord(c) > 127 and not any(ord(c) in range(0xC0, 0x200) for _ in [0]) for c in p[:30] if not c.isascii())
    log(f"  [{d['cnt']}x] {'⚠️GARBLED ' if len([c for c in p if ord(c)>900]) > 3 else ''}{p[:90]}...")

# ═══════════════════════════════════════════════
# 9: Department chunk dağılımı
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 9: Departman chunk dengesizliği")
log("="*80)

dept_dist = db_query(
    "SELECT meta->>'department' as dept, COUNT(*) as cnt FROM haystack_docs "
    "WHERE meta->>'department' IS NOT NULL GROUP BY dept ORDER BY cnt DESC LIMIT 25", ()
)
max_cnt = dept_dist[0]['cnt'] if dept_dist else 1
for d in dept_dist:
    bar = "█" * int(d['cnt'] / max_cnt * 30)
    log(f"  {(d['dept'] or '?')[:38]:38s} {d['cnt']:4d} {bar}")

# ═══════════════════════════════════════════════
# 10: SHMYO programları
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 10: SHMYO programları içeren chunk")
log("="*80)

for prog in ["ameliyathane", "fizyoterapi", "tıbbi lab", "yaşlı bakım", "ilk ve acil"]:
    cnt = db_query("SELECT COUNT(*) as c FROM haystack_docs WHERE content ILIKE %s", (f'%{prog}%',))
    log(f"  '{prog}' chunk: {cnt[0]['c']}")

# Aynı chunk'ta birden fazla program geçen
rows_sh = db_query(
    "SELECT meta->>'title' as title, LEFT(content, 250) as preview FROM haystack_docs "
    "WHERE content ILIKE %s AND content ILIKE %s AND content ILIKE %s LIMIT 5",
    ('%ameliyathane%', '%fizyoterapi%', '%tıbbi lab%')
)
log(f"\n3+ program aynı anda geçen chunk: {len(rows_sh)}")
for r in rows_sh[:3]:
    log(f"  {(r['title'] or '?')[:60]}")
    log(f"    {r['preview'][:200].replace(chr(10),' ')}...")

# ═══════════════════════════════════════════════
# 11: Gerçek retrieval — pipeline testi
# ═══════════════════════════════════════════════
log("\n" + "="*80)
log("DOĞRULAMA 11: Pipeline retrieval doğrulama (8 kritik sorgu)")
log("="*80)

from app.services.rag_service import RagService
service = RagService()
service.build_pipeline()

test_queries = [
    ("GİBTÜ'de hangi fakülteler var?", "fakülte listesi"),
    ("Transkript almak istiyorum, nereye başvurmam lazım?", "yönlendirme"),
    ("Hemşirelik mi ebelik mi?", "karşılaştırma"),
    ("Türkiye'nin başkenti neresidir?", "kapsam dışı"),
    ("Öğrenci kulüplerine nasıl üye olabilirim?", "topluluklar"),
    ("Son duyurular neler?", "duyurular"),
    ("Sınav yönetmeliği ne diyor?", "mevzuat"),
    ("Sağlık Hizmetleri MYO'da hangi programlar var?", "shmyo"),
]

for question, label in test_queries:
    log(f"\n--- [{label}] {question} ---")
    result = service._pipeline.run(
        data={
            "text_embedder": {"text": question},
            "keyword_retriever": {"query": question},
            "prompt_builder": {"question": question},
        },
        include_outputs_from={"joiner", "vector_retriever", "keyword_retriever"},
    )

    joined = result.get("joiner", {}).get("documents", [])
    vec_docs = result.get("vector_retriever", {}).get("documents", [])
    kw_docs = result.get("keyword_retriever", {}).get("documents", [])
    log(f"  Joiner: {len(joined)} | Vector: {len(vec_docs)} | Keyword: {len(kw_docs)} | Overlap: {len({d.id for d in vec_docs} & {d.id for d in kw_docs})}")

    for i, d in enumerate(joined[:5]):
        t = (d.meta.get("title","?") if d.meta else "?")[:45]
        c = (d.meta.get("category","?") if d.meta else "?")
        dk = (d.meta.get("doc_kind","?") if d.meta else "?")
        dp = (d.meta.get("department","?") if d.meta else "?")[:22]
        sc = f"{d.score:.4f}" if d.score else "?"
        log(f"    [{i}] s={sc} [{c}/{dk}] dept={dp} — {t}")

    cats = list(set(d.meta.get("category") for d in joined if d.meta))
    log(f"  Categories: {cats}")

# SAVE
report_path = os.path.join(os.path.dirname(__file__), "..", "doc", "verify_findings_output.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(output))
log(f"\n📄 Rapor: {report_path}")
