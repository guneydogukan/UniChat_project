"""
3.2.21 — P1 Veri Kalitesi Doğrulama (Tüm Birimler)
====================================================
Kapsamlı veri kalitesi doğrulama scripti:
  1. Toplam belge sayısı kontrolü (beklenen vs yüklenen)
  2. Harita kapsam oranı
  3. Metadata doluluk raporu (category, title, doc_kind, source_url)
  4. Kaynak dağılımı (canlı web vs PDF)
  5. doc_kind dağılımı raporu
  6. Menü derinlik raporu
  7. 5 örnek soruyla yanıt kalitesi testi
  8. Hybrid search testi (BM25 + vektör)
  9. Halüsinasyon testi
"""

import os, sys, json, time, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import psycopg2
from datetime import datetime

DB_URL = os.environ["DATABASE_URL"]
REPORT = []

def log(msg=""):
    REPORT.append(msg)
    print(msg)

def db(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close(); conn.close()
    return [dict(zip(cols, r)) for r in rows]

def db_scalar(sql, params=None):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(sql, params)
    val = cur.fetchone()[0]
    cur.close(); conn.close()
    return val

# ════════════════════════════════════════════════════════════
# BEKLENEN VERİ (task.md'den derlendi)
# ════════════════════════════════════════════════════════════
EXPECTED_CHUNKS = {
    "3.2.8.1 İlahiyat": 396,
    "3.2.8.2 MDBF": 151,
    "3.2.8.3 SBF": 591,
    "3.2.8.4 Tıp": 539,
    "3.2.8.5 İİSBF": 337,
    "3.2.8.6 GSMF": 88,
    "3.2.10.1 SHMYO": 614,
    "3.2.10.2 TBMYO": 529,
    "3.2.11.1 YDYO": 325,
    "3.2.12 Daireler": 366,
    "3.2.13 Koordinatörlükler": 461,
    "3.2.14 Genel/İletişim": 56,
    "3.2.15 Öğrenci Hizmetleri": 8,
    "3.2.19 Kulüpler": 119,
    "3.2.20 Duyurular": 407,
}
EXPECTED_TOTAL = sum(EXPECTED_CHUNKS.values())  # ~4987 (scrape chunks only)

REQUIRED_META_FIELDS = ["category", "title", "doc_kind", "source_url"]

# ════════════════════════════════════════════════════════════════
log("=" * 90)
log(f"  3.2.21 — P1 VERİ KALİTESİ DOĞRULAMA (TÜM BİRİMLER)")
log(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("=" * 90)

# ════════════════════════════════════════════════════════════
# 1) TOPLAM BELGE SAYISI KONTROLÜ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("1) TOPLAM BELGE SAYISI KONTROLÜ")
log("=" * 90)

total_chunks = db_scalar("SELECT COUNT(*) FROM haystack_docs")
log(f"\n  DB'deki toplam chunk: {total_chunks}")
log(f"  Beklenen minimum (scrape): ~{EXPECTED_TOTAL}")
log(f"  Fark: {total_chunks - EXPECTED_TOTAL:+d}")

# Kategori bazlı chunk sayıları
cat_rows = db("""
    SELECT meta->>'category' as cat, COUNT(*) as cnt
    FROM haystack_docs
    WHERE meta->>'category' IS NOT NULL
    GROUP BY cat ORDER BY cnt DESC
""")
log(f"\n  Kategori Dağılımı ({len(cat_rows)} kategori):")
log(f"  {'Kategori':<30} {'Chunk':>8}")
log(f"  {'-'*38}")
for r in cat_rows:
    log(f"  {r['cat']:<30} {r['cnt']:>8}")

# Department bazlı
dept_rows = db("""
    SELECT meta->>'department' as dept, COUNT(*) as cnt
    FROM haystack_docs
    WHERE meta->>'department' IS NOT NULL
    GROUP BY dept ORDER BY cnt DESC
""")
log(f"\n  Departman Dağılımı ({len(dept_rows)} departman):")
log(f"  {'Departman':<50} {'Chunk':>8}")
log(f"  {'-'*58}")
for r in dept_rows:
    log(f"  {(r['dept'] or '?'):<50} {r['cnt']:>8}")

# ════════════════════════════════════════════════════════════
# 2) HARİTA KAPSAM ORANI
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("2) HARİTA KAPSAM ORANI")
log("=" * 90)

# Scrape summary dosyalarından beklenen belge sayılarını oku
summary_dir = os.path.join(os.path.dirname(__file__), "scrapers")
summaries = {}
for fname in os.listdir(summary_dir):
    if fname.endswith("_summary.json"):
        fpath = os.path.join(summary_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = fname.replace("_summary.json", "")
            total_docs = 0
            total_valid = 0
            total_failed = 0
            if "birimler" in data:
                for b in data["birimler"]:
                    total_docs += b.get("total_documents", 0)
                    total_valid += b.get("total_valid", 0)
                    total_failed += b.get("total_failed", 0)
            summaries[key] = {
                "task": data.get("task", "?"),
                "total_docs": total_docs,
                "total_valid": total_valid,
                "total_failed": total_failed,
            }
        except Exception as e:
            log(f"  ⚠️ {fname} okunamadı: {e}")

log(f"\n  {'Birim':<30} {'Görev':<12} {'Belge':>6} {'Valid':>6} {'Fail':>6} {'Oran':>8}")
log(f"  {'-'*70}")
grand_docs = grand_valid = grand_fail = 0
for key, s in sorted(summaries.items()):
    ratio = f"{s['total_valid']/s['total_docs']*100:.0f}%" if s['total_docs'] > 0 else "N/A"
    log(f"  {key:<30} {s['task']:<12} {s['total_docs']:>6} {s['total_valid']:>6} {s['total_failed']:>6} {ratio:>8}")
    grand_docs += s['total_docs']
    grand_valid += s['total_valid']
    grand_fail += s['total_failed']

grand_ratio = f"{grand_valid/grand_docs*100:.1f}%" if grand_docs > 0 else "N/A"
log(f"  {'-'*70}")
log(f"  {'TOPLAM':<30} {'':<12} {grand_docs:>6} {grand_valid:>6} {grand_fail:>6} {grand_ratio:>8}")

# ════════════════════════════════════════════════════════════
# 3) METADATA DOLULUK RAPORU
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("3) METADATA DOLULUK RAPORU")
log("=" * 90)

log(f"\n  {'Alan':<20} {'Dolu':>8} {'Boş':>8} {'Oran':>10}")
log(f"  {'-'*48}")
for field in REQUIRED_META_FIELDS:
    filled = db_scalar(f"""
        SELECT COUNT(*) FROM haystack_docs
        WHERE meta->>'{field}' IS NOT NULL AND meta->>'{field}' != ''
    """)
    empty = total_chunks - filled
    ratio = f"{filled/total_chunks*100:.1f}%" if total_chunks > 0 else "0%"
    marker = "✅" if filled/total_chunks >= 0.95 else ("⚠️" if filled/total_chunks >= 0.80 else "❌")
    log(f"  {field:<20} {filled:>8} {empty:>8} {ratio:>10} {marker}")

# Ek metadata alanları
extra_fields = ["department", "contact_unit", "contact_info", "heading_context"]
log(f"\n  Ek Metadata Alanları:")
log(f"  {'Alan':<20} {'Dolu':>8} {'Oran':>10}")
log(f"  {'-'*40}")
for field in extra_fields:
    filled = db_scalar(f"""
        SELECT COUNT(*) FROM haystack_docs
        WHERE meta->>'{field}' IS NOT NULL AND meta->>'{field}' != ''
    """)
    ratio = f"{filled/total_chunks*100:.1f}%" if total_chunks > 0 else "0%"
    log(f"  {field:<20} {filled:>8} {ratio:>10}")

# Embedding doluluk
emb_count = db_scalar("SELECT COUNT(*) FROM haystack_docs WHERE embedding IS NOT NULL")
log(f"\n  Embedding doluluk: {emb_count}/{total_chunks} ({emb_count/total_chunks*100:.1f}%) {'✅' if emb_count == total_chunks else '⚠️'}")

# ════════════════════════════════════════════════════════════
# 4) KAYNAK DAĞILIMI (canlı web vs PDF)
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("4) KAYNAK DAĞILIMI")
log("=" * 90)

pdf_chunks = db_scalar("""
    SELECT COUNT(*) FROM haystack_docs
    WHERE meta->>'source_url' LIKE '%.pdf%'
       OR meta->>'source_type' = 'pdf'
       OR meta->>'doc_kind' = 'pdf_rapor'
""")
web_chunks = total_chunks - pdf_chunks
log(f"\n  Canlı Web: {web_chunks} chunk ({web_chunks/total_chunks*100:.1f}%)")
log(f"  PDF:       {pdf_chunks} chunk ({pdf_chunks/total_chunks*100:.1f}%)")

# İçerik uzunluk istatistikleri
stats = db("""
    SELECT
        AVG(LENGTH(content)) as avg_len,
        MIN(LENGTH(content)) as min_len,
        MAX(LENGTH(content)) as max_len,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY LENGTH(content)) as median_len
    FROM haystack_docs
""")[0]
log(f"\n  İçerik Uzunluk İstatistikleri:")
log(f"    Ortalama: {stats['avg_len']:.0f} karakter")
log(f"    Medyan:   {stats['median_len']:.0f} karakter")
log(f"    Min:      {stats['min_len']} karakter")
log(f"    Max:      {stats['max_len']} karakter")

# Çok kısa / çok uzun chunk'lar
short = db_scalar("SELECT COUNT(*) FROM haystack_docs WHERE LENGTH(content) < 50")
long_c = db_scalar("SELECT COUNT(*) FROM haystack_docs WHERE LENGTH(content) > 5000")
log(f"\n  Çok kısa (<50 kar): {short} chunk {'⚠️' if short > 0 else '✅'}")
log(f"  Çok uzun (>5000 kar): {long_c} chunk")

# Duplicate kontrol
dup_count = db_scalar("""
    SELECT COUNT(*) FROM (
        SELECT content FROM haystack_docs
        GROUP BY content HAVING COUNT(*) > 1
    ) sub
""")
log(f"  Duplicate içerik: {dup_count} unique tekrar {'⚠️' if dup_count > 0 else '✅'}")

# ════════════════════════════════════════════════════════════
# 5) doc_kind DAĞILIMI
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("5) doc_kind DAĞILIMI")
log("=" * 90)

dk_rows = db("""
    SELECT meta->>'doc_kind' as dk, COUNT(*) as cnt
    FROM haystack_docs
    GROUP BY dk ORDER BY cnt DESC
""")
log(f"\n  {'doc_kind':<25} {'Chunk':>8} {'Oran':>10}")
log(f"  {'-'*45}")
for r in dk_rows:
    dk = r['dk'] or '(NULL)'
    ratio = f"{r['cnt']/total_chunks*100:.1f}%"
    log(f"  {dk:<25} {r['cnt']:>8} {ratio:>10}")

# ════════════════════════════════════════════════════════════
# 6) MENÜ DERİNLİK RAPORU
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("6) MENÜ DERİNLİK RAPORU")
log("=" * 90)

# source_url'den derinlik tahmini (/ sayısı)
depth_rows = db("""
    SELECT
        CASE
            WHEN meta->>'source_url' IS NULL OR meta->>'source_url' = '' THEN 'URL yok'
            WHEN meta->>'source_url' LIKE '%BirimIcerik%' THEN 'Derin (BirimIcerik)'
            WHEN meta->>'source_url' LIKE '%Birim%.aspx%' THEN 'Birim sayfası'
            WHEN meta->>'source_url' LIKE '%.pdf%' THEN 'PDF'
            WHEN meta->>'source_url' LIKE '%icerik/%' THEN 'icerik/ slug'
            ELSE 'Diğer'
        END as url_type,
        COUNT(*) as cnt
    FROM haystack_docs
    GROUP BY url_type ORDER BY cnt DESC
""")
log(f"\n  URL Yapısı Dağılımı:")
log(f"  {'URL Tipi':<30} {'Chunk':>8}")
log(f"  {'-'*40}")
for r in depth_rows:
    log(f"  {r['url_type']:<30} {r['cnt']:>8}")

# Menü haritası document'ları
menu_maps = db_scalar("""
    SELECT COUNT(*) FROM haystack_docs
    WHERE meta->>'doc_kind' = 'menu_haritasi'
""")
log(f"\n  Menü haritası belgeleri: {menu_maps}")

# ════════════════════════════════════════════════════════════
# 7) 5 ÖRNEK SORUYLA YANIT KALİTESİ TESTİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("7) YANIT KALİTESİ TESTİ (5 soru — her birim grubundan 1)")
log("=" * 90)

from app.services.rag_service import RagService

service = RagService()
service.build_pipeline()

QUALITY_QUESTIONS = [
    {
        "id": "Q1-Fakülte",
        "question": "GİBTÜ'de hangi fakülteler var?",
        "check_keywords": ["ilahiyat", "mühendislik", "sağlık", "tıp", "iktisadi", "güzel sanat"],
        "group": "Fakülteler (3.2.8)",
    },
    {
        "id": "Q2-MYO",
        "question": "Sağlık Hizmetleri MYO'da hangi programlar var?",
        "check_keywords": ["ameliyathane", "fizyoterapi", "tıbbi lab", "yaşlı bakım", "acil yardım"],
        "group": "MYO (3.2.10)",
    },
    {
        "id": "Q3-Daire",
        "question": "Kütüphane çalışma saatleri ve kuralları nedir?",
        "check_keywords": ["kütüphane"],
        "group": "Daireler (3.2.12)",
    },
    {
        "id": "Q4-Koord",
        "question": "Erasmus programına nasıl başvurabilirim?",
        "check_keywords": ["erasmus", "başvuru"],
        "group": "Koordinatörlükler (3.2.13)",
    },
    {
        "id": "Q5-Duyuru",
        "question": "Son duyurular ve haberler neler?",
        "check_keywords": ["duyuru"],
        "group": "Duyurular (3.2.20)",
    },
]

for tq in QUALITY_QUESTIONS:
    log(f"\n  ── {tq['id']} ({tq['group']}) ──")
    log(f"  Soru: {tq['question']}")
    try:
        start = time.time()
        result = service.query(tq['question'])
        elapsed = time.time() - start
        resp = result.get("response", "") or ""
        sources = result.get("sources", [])
        resp_lower = resp.lower()

        found = [kw for kw in tq['check_keywords'] if kw.lower() in resp_lower]
        missing = [kw for kw in tq['check_keywords'] if kw.lower() not in resp_lower]
        kw_ratio = len(found) / len(tq['check_keywords']) if tq['check_keywords'] else 1.0

        if kw_ratio >= 0.8:
            verdict = "✅ BAŞARILI"
        elif kw_ratio >= 0.5:
            verdict = "⚠️ KISMİ"
        else:
            verdict = "❌ BAŞARISIZ"

        log(f"  Sonuç: {verdict} | Süre: {elapsed:.1f}s | Kaynak: {len(sources)}")
        log(f"  Anahtar kelime: {len(found)}/{len(tq['check_keywords'])} bulundu")
        if missing:
            log(f"  Eksik: {missing}")
        preview = resp[:200].replace("\n", " ")
        log(f"  Yanıt: {preview}...")
        if sources:
            cats = list(set(s.get("category", "?") for s in sources))
            log(f"  Kaynak kategorileri: {cats}")
    except Exception as e:
        log(f"  ❌ HATA: {e}")

# ════════════════════════════════════════════════════════════
# 8) HYBRID SEARCH TESTİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("8) HYBRID SEARCH TESTİ (BM25 + Vektör)")
log("=" * 90)

HYBRID_QUERIES = [
    "fakülte",
    "transkript",
    "erasmus",
    "sınav yönetmeliği",
    "hemşirelik",
    "duyuru",
    "akademik takvim",
    "öğrenci kulüpleri",
]

log(f"\n  {'Sorgu':<30} {'Vec':>5} {'KW':>5} {'Join':>5} {'Overlap':>8}")
log(f"  {'-'*58}")

for q in HYBRID_QUERIES:
    kw_query = RagService._clean_keyword_query(q)
    try:
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
        kw_status = "✅" if len(k) > 0 else "❌"
        log(f"  {q:<30} {len(v):>5} {len(k):>5} {len(j):>5} {overlap:>8} {kw_status}")
    except Exception as e:
        log(f"  {q:<30} HATA: {e}")

# Turkish config doğrulama
log(f"\n  BM25 Config Doğrulama:")
log(f"    ds.language = \"{service._document_store.language}\"")

idx_rows = db("SELECT indexdef FROM pg_indexes WHERE indexname = 'unichat_keyword_index'")
if idx_rows:
    idx = idx_rows[0]['indexdef']
    is_turkish = "'turkish'" in idx
    log(f"    GIN Index: {'turkish ✅' if is_turkish else 'HATALI ❌'}")
else:
    log(f"    GIN Index: BULUNAMADI ❌")

# Stopword temizleme doğrulama
log(f"\n  Stopword Temizleme:")
sw_tests = [
    ("hangi fakülteler var", "fakülteler"),
    ("transkript almak istiyorum", "transkript"),
    ("son duyurular neler", "duyurular"),
]
for original, expected in sw_tests:
    cleaned = RagService._clean_keyword_query(original)
    ok = cleaned == expected
    log(f"    \"{original}\" → \"{cleaned}\" {'✅' if ok else '❌'}")

# ════════════════════════════════════════════════════════════
# 9) HALÜSİNASYON TESTİ
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("9) HALÜSİNASYON TESTİ")
log("=" * 90)

HALLUC_TESTS = [
    {
        "id": "H1",
        "question": "GİBTÜ'nün uzay mühendisliği bölümü var mı?",
        "negative_keywords": ["uzay mühendisliği bölümü bulunmaktadır", "uzay mühendisliği programı mevcuttur"],
        "description": "Olmayan bölüm → bilmediğini belirtmeli",
    },
    {
        "id": "H2",
        "question": "GİBTÜ'nün dünya sıralaması kaçıncı?",
        "negative_keywords": ["dünya sıralamasında", "sırada yer almaktadır"],
        "description": "Belgede olmayan bilgi → uydurmamalı",
    },
    {
        "id": "H3",
        "question": "Türkiye'nin başkenti neresidir?",
        "negative_keywords": [],
        "description": "Kapsam dışı → üniversite dışı konu reddi",
        "check_guardrail": True,
    },
]

for ht in HALLUC_TESTS:
    log(f"\n  ── {ht['id']}: {ht['description']} ──")
    log(f"  Soru: {ht['question']}")
    try:
        start = time.time()
        result = service.query(ht['question'])
        elapsed = time.time() - start
        resp = (result.get("response", "") or "").lower()

        halluc_found = [kw for kw in ht['negative_keywords'] if kw.lower() in resp]

        if halluc_found:
            log(f"  ❌ HALÜSİNASYON TESPİT EDİLDİ: {halluc_found}")
        elif ht.get("check_guardrail"):
            # Kapsam dışı test — üniversite dışı olduğunu belirtmeli
            guardrail_ok = any(w in resp for w in ["üniversite", "unichat", "kapsam", "yardımcı olamam", "bilgi bulunmuyor"])
            log(f"  {'✅ Guardrail çalışıyor' if guardrail_ok else '⚠️ Guardrail yetersiz'}")
        else:
            log(f"  ✅ Halüsinasyon yok")
        log(f"  Süre: {elapsed:.1f}s")
        preview = (result.get("response", "") or "")[:200].replace("\n", " ")
        log(f"  Yanıt: {preview}...")
    except Exception as e:
        log(f"  ❌ HATA: {e}")

# ════════════════════════════════════════════════════════════
# 10) ÖZET PUAN KARTI
# ════════════════════════════════════════════════════════════
log()
log("=" * 90)
log("10) ÖZET PUAN KARTI")
log("=" * 90)

checks = {
    "Toplam chunk >= beklenen": total_chunks >= EXPECTED_TOTAL * 0.95,
    "Kategori sayısı >= 10": len(cat_rows) >= 10,
    f"Embedding doluluk {emb_count}/{total_chunks}": emb_count == total_chunks,
    f"Duplicate < 10": dup_count < 10,
    f"Çok kısa chunk < 20": short < 20,
    f"doc_kind çeşitliliği >= 8": len(dk_rows) >= 8,
    "Menü haritası belgeleri > 0": menu_maps > 0,
}

# Metadata doluluk kontrolleri
for field in REQUIRED_META_FIELDS:
    filled = db_scalar(f"""
        SELECT COUNT(*) FROM haystack_docs
        WHERE meta->>'{field}' IS NOT NULL AND meta->>'{field}' != ''
    """)
    ratio = filled / total_chunks if total_chunks > 0 else 0
    checks[f"{field} >= 90%"] = ratio >= 0.90

pass_count = sum(1 for v in checks.values() if v)
total_checks = len(checks)

log(f"\n  {'Kontrol':<45} {'Sonuç':>10}")
log(f"  {'-'*57}")
for check, passed in checks.items():
    log(f"  {check:<45} {'✅ PASS' if passed else '❌ FAIL':>10}")

log(f"\n  ══════════════════════════════════════════")
log(f"  GENEL SONUÇ: {pass_count}/{total_checks} kontrol başarılı")
log(f"  Başarı oranı: {pass_count/total_checks*100:.0f}%")
if pass_count == total_checks:
    log(f"  🎉 TÜM KONTROLLER BAŞARILI!")
elif pass_count / total_checks >= 0.8:
    log(f"  ⚠️ Küçük sorunlar var, genel durum iyi.")
else:
    log(f"  ❌ Ciddi sorunlar tespit edildi.")
log(f"  ══════════════════════════════════════════")

# RAPORU KAYDET
report_path = os.path.join(os.path.dirname(__file__), "..", "doc", "p1_data_quality_report.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(REPORT))
log(f"\n📄 Rapor kaydedildi: {report_path}")
