# UniChat — Kapsamlı Uygulama Planı (v4)

> **Güncelleme:** 13 Mart 2026  
> **Durum:** Faz 0 ✅ Faz 1 ✅ → Faz 2'ye hazırlanıyor  
> **Referans:** [project_context.md](file:///c:/Users/ASUS/Masaüstü/unichat_proje/doc/project_context.md) — 19 başlıklı proje kapsamı  
> **Scraping yaklaşımı:** [web_scraping_yapisal_kesif_kontrollu_scrape_yaklasimi.md](file:///c:/Users/ASUS/Masaüstü/unichat_proje/doc/web_scraping_yapisal%20_kesif_kontrollu_scrape_yaklasimi.md)

---

## Genel Bakış

Bu plan, projeyi `project_context.md`'deki vizyona taşımak için **veri kalitesi ve verimlilik** odaklı bir yol haritası sunar. Fazlar birbirine bağımlıdır — önceki faz tamamlanmadan sonrakine geçilmez.

### Mevcut Durum Özeti

| Faz | Durum | Açıklama |
|-----|-------|----------|
| Faz 0 — Mimari Refactoring | ✅ Tamamlandı | Backend katmanlı yapı, frontend bileşen ayrımı, config yönetimi, güvenlik |
| Faz 1 — Çekirdek İyileştirmeler | ✅ Tamamlandı | Chat log, kaynak gösterme, prompt guardrails, markdown rendering, hata yönetimi |
| Faz 2 — Uçtan Uca Doğrulama + Veri Altyapısı | 🔄 Sırada | Aşağıda detaylandırılıyor |
| Faz 3 — Gerçek Üniversite Verisi | ⏳ Bekliyor | — |
| Faz 4 — Dinamik Veri (Yapısal Keşif + Kontrollü Scraping) | ⏳ Bekliyor | — |
| Faz 5 — İleri Özellikler | ⏳ Bekliyor | — |

---

## Faz 2: Uçtan Uca Doğrulama + Veri Besleme Altyapısı

> [!IMPORTANT]
> Bu faz **projenin gerçek değer üretmeye başladığı** noktadır. Mimari hazır ama sistem içi boş — gerçek veri yok, uçtan uca çalışma doğrulanmamış.

### 2.0 Ön Koşul: Uçtan Uca Doğrulama ve Stabilizasyon

**Amaç:** Faz 0-1'de yapılan mimari değişikliklerin Docker + Ollama ile birlikte çalıştığını doğrulamak ve bağımlılıkları sabitlemek.

**Adımlar:**
1. Docker konteynerinin (PostgreSQL + PgVector) çalıştığını doğrula
2. `init_db.py` ile tabloları oluştur
3. `seed_data.py` ile mevcut 3 örnek veriyi yükle
4. Backend'i yeni yapıyla başlat: `python -m uvicorn main:app --reload --port 8000`
5. Frontend'i başlat: `npm run dev`
6. Tarayıcıda soru sor ve yanıt al
7. `/api/health` endpoint'inin çalıştığını doğrula
8. **Bağımlılık sabitleme:** `pip freeze > requirements-lock.txt` ile mevcut çalışan versiyonları kaydet

> [!WARNING]
> Bu doğrulama **yapılmadan** Faz 2'nin geri kalanına geçilmemelidir. Faz 0-1'de yapılan import testleri yeterli değil — gerçek çalışma testi şart.

**Başarısızlık durumları:**
| Hata | Kontrol | Çözüm |
|------|---------|-------|
| Docker bağlantı hatası | `docker ps \| findstr unichat_db` | `docker-compose up -d` ile konteyneri başlat |
| Ollama yanıt vermiyor | `curl http://localhost:11434/api/tags` | Ollama servisini başlat, `gemma3:4b-it-qat` modelinin çekildiğini doğrula |
| Embedding modeli inmiyor | İnternet bağlantısı kontrol | İlk çalıştırmada `all-mpnet-base-v2` indiriliyor (~400MB); `~/.cache/huggingface/` altında olup olmadığını kontrol et |
| Pipeline import hatası | Hata mesajını oku | Faz 0 walkthrough'daki import testlerini tekrar çalıştır |

---

### 2.1 Veri Besleme Hattının Birleştirilmesi (Ingestion Pipeline)

> **Gerekçe:** Mevcut `seed_data.py` ile planlanan `loader.py` aynı işi yapıyor. İki ayrı yükleme aracı bakım yükü ve karmaşıklık yaratır. Tek bir ingestion akışı altında birleştirilmelidir.

#### [MODIFY] [seed_data.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/database/seed_data.py)

**Değişiklik:** `seed_data.py` artık doğrudan belge gömmez. Bunun yerine `backend/data/_test_seed.json` dosyasını okuyarak `ingestion` modülünü çağıran ince bir wrapper haline gelir. `recreate_table=True` kaldırılır.

```python
# seed_data.py artık yalnızca şunu yapar:
from app.ingestion.loader import load_json_file
load_json_file("data/_test_seed.json")
```

#### [NEW] [backend/app/ingestion/](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/ingestion/)

**Gerekçe:** `data_loader/` yerine `app/ingestion/` altında konumlanır — böylece `app.config` ve diğer `app.*` modüllerini sorunsuz import edebilir (import path sorunu çözülür).

```
app/ingestion/
├── __init__.py
├── loader.py            # Tüm giriş noktası: JSON, PDF dizin, tek PDF, Document listesi
├── pdf_parser.py         # PDF → metin dönüşümü (pdfplumber)
├── splitter.py           # Belge yapısına duyarlı parçalama
└── validators.py         # Metadata doğrulama, içerik kalite kontrolü
```

**İki ana veri kanalı ve ortak akışı:**

```
┌─────────────────────────────────┐   ┌──────────────────────────────┐
│  Kanal 1: Toplu Belge/PDF      │   │  Kanal 2: Web Scraping       │
│  (kullanıcı sağlar)            │   │  (scraper otomatik toplar)   │
│                                │   │                              │
│  data/pdfs/ dizini             │   │  scrapers/ → Document list   │
│  ├── yonetmelikler/            │   │                              │
│  ├── yonergeler/               │   │                              │
│  ├── fakulte_dokumanlari/      │   │                              │
│  └── diger/                    │   │                              │
└──────────────┬──────────────────┘   └──────────────┬───────────────┘
               │                                      │
               ▼                                      ▼
         pdf_parser.py                          to_documents()
               │                                      │
               └──────────────┬───────────────────────┘
                              ▼
                   validators.py  → metadata doğrulama,
                                    min uzunluk, placeholder reddi
                              ▼
                   splitter.py  → yapıya duyarlı chunk'lama
                              ▼
                   Document(id = SHA-256(content))
                              ▼
                   SentenceTransformersDocumentEmbedder
                              ▼
                   DocumentStore.write_documents()
```

**`loader.py` giriş noktaları:**
```python
# 1. Tek JSON dosyası yükle
load_json_file("data/_test_seed.json")

# 2. Bir dizindeki tüm PDF'leri toplu yükle (kullanıcının sağladığı belgeler)
load_pdf_directory("data/pdfs/yonetmelikler/", category="egitim", doc_kind="yonetmelik")

# 3. Tek PDF yükle
load_pdf_file("data/pdfs/egitim_yonetmeligi.pdf", category="egitim", doc_kind="yonetmelik")

# 4. Scraper'dan gelen Document listesini yükle
ingest_documents(documents, policy=DuplicatePolicy.OVERWRITE)
```

**Haystack native duplicate yönetimi:**
- Her Document'ın `id` alanı, `SHA-256(content)` olarak atanır
- `write_documents(policy=DuplicatePolicy.SKIP)` — aynı hash'li belge zaten varsa atlar (toplu yükleme için)
- `write_documents(policy=DuplicatePolicy.OVERWRITE)` — aynı hash'li belgeyi günceller (scraper güncelleme için)
- **Ayrı bir `hasher.py` veya `delta_updater.py` modülüne gerek yok** — Haystack bunu native olarak yönetir

> [!IMPORTANT]
> Bu yaklaşım, **hem kullanıcının toplu yüklediği belgeleri hem de scraper çıktısını** aynı pipeline'dan geçirir. Tek bir veri giriş hattı, tek bir doğrulama, tek bir chunk'lama, tek bir embedding.

---

### 2.2 Veri Modeli ve Metadata Zenginleştirme

#### [NEW] [backend/app/models/document_models.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/models/document_models.py)

UniChat'in 19 kategorisini desteklemek için **standart metadata şeması** tanımlanacak:

```python
# Her belge (Document) için zorunlu metadata alanları:
{
    "category": str,         # "egitim", "kampus", "yemekhane", "erasmus", vb.
    "subcategory": str,      # "ders_kayit", "sinav", "not_sistemi", vb.
    "source_url": str,       # Kaynak web sayfası URL'si
    "source_type": str,      # "pdf", "web", "manual"
    "source_id": str,        # İçerikten bağımsız sabit kaynak kimliği (güncelleme için)
    "department": str | None, # İlgili bölüm/fakülte
    "last_updated": str,     # ISO 8601 tarih
    "language": str,         # "tr" (gelecekte "en" da olacak)
    "title": str,            # Belge başlığı
    "doc_kind": str,         # "yonetmelik", "duyuru", "tanitim", "iletisim", "form", vb.
    "parent_doc_id": str | None,  # Chunk'lanan belgenin source_id'si
    "chunk_index": int | None,    # Chunk sırası (0, 1, 2...)
    "contact_unit": str | None,   # Yönlendirme: ilgili birim adı
    "contact_info": str | None,   # Yönlendirme: telefon, e-posta, oda no
}
```

> **`source_id` gerekçesi:** Document ID olarak `SHA-256(content)` kullanılıyor — ama içerik değiştiğinde hash de değişir ve eski belge/chunk'lar bulunamaz. `source_id`, içerikten bağımsız sabit bir kimliktir. Örnek: PDF için `"egitim_yonetmeligi_madde_24"`, web sayfası için `"gtu.edu.tr/ogrenci-isleri/transkript"`. Güncelleme sırasında eski chunk'lar `source_id` filtresiyle silinir, yeni chunk'lar eklenir.

> **`parent_doc_id` + `chunk_index` gerekçesi:** Bir kaynak belge chunk'landığında N parça üretilir. `parent_doc_id`, orijinal belgenin `source_id` değerini taşır. Güncelleme: `parent_doc_id == source_id` olan tüm chunk'ları sil → yeni chunk'ları ekle.

> **`contact_unit` + `contact_info` gerekçesi:** Yönlendirme katmanı (Kapsam 19) için. Kullanıcı bir sorun bildirdiğinde, yanıt yalnızca bilgi değil aynı zamanda "bu konuda X birimine başvurun" yönlendirmesi de içermelidir. Bu metadata prompt'a aktarılarak LLM'in yönlendirme yapmasını sağlar.

**Kategoriler tablosu değişmemiştir** (önceki versiyondaki 19 kategori korunur).

---

### 2.3 Yapıya Duyarlı Belge Parçalama (Structure-Aware Splitting)

> **Gerekçe:** Sabit 500 karakter chunk mantığı uygun değil. `all-mpnet-base-v2` max sequence length = **384 token** (Türkçe'de ~1500-1800 karakter). Ayrıca belge türüne göre parçalama stratejisi değişmelidir.

#### [NEW] [backend/app/ingestion/splitter.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/ingestion/splitter.py)

**Parçalama stratejisi belge türüne (`doc_kind`) göre değişir:**

| Belge Türü | Strateji | Gerekçe |
|------------|----------|---------|
| `yonetmelik` | **Madde bazlı** — her madde/fıkra ayrı chunk | Yönetmelik maddeleri bağımsız bilgi birimleri |
| `duyuru`, `haber` | **Bölünmez** — tek chunk (kısa ise), paragraf bazlı (uzunsa) | Duyurular genellikle tek bir bütün haber |
| `tanitim`, `rehber` | **Başlık hiyerarşisi** — markdown heading'lere göre böl | Tanıtım metinleri alt başlıklar altında yapılanmıştır |
| `iletisim`, `form` | **Bölünmez** — tek chunk | İletişim bilgileri parçalanmamalı |
| `mufradat`, `ders_plani` | **Tablo satırı / ders bazlı** | Her ders veya konu ayrı chunk |
| `genel` (varsayılan) | **Paragraf + cümle sınırı** — Haystack `DocumentSplitter` ile | Genel amaçlı metin |

**Teknik parametreler:**
```python
# Embedding model sınırı: all-mpnet-base-v2 max_seq_length = 384 token
# Türkçe'de ~4 karakter ≈ 1 token → güvenli chunk sınırı ≈ 1200 karakter
CHUNK_MAX_CHARS: int = 1200    # Chunk üst sınırı (~300 token)
CHUNK_OVERLAP_CHARS: int = 200  # Bağlam koruma örtüşmesi
CHUNK_MIN_CHARS: int = 80       # Bundan kısa chunk'lar üst chunk ile birleştirilir
```

**Genel belge türü için Haystack native `DocumentSplitter` kullanılır:**
```python
from haystack.components.preprocessors import DocumentSplitter
splitter = DocumentSplitter(
    split_by="sentence",
    split_length=3,            # 3 cümle
    split_overlap=1,           # 1 cümle overlap
)
```

**Her chunk'a aktarılan metadata:**
- Orijinal belgenin tüm metadata'sı kopyalanır
- `parent_doc_id`: orijinal belgenin SHA-256 hash'i
- `chunk_index`: 0, 1, 2...
- `title`: orijinal başlık korunur (her chunk aranabilir olsun)

---

### 2.4 PDF ve Toplu Belge İçe Aktarma Altyapısı

> **Gerekçe:** Sistemin ana veri kanallarından biri, kullanıcının toplu olarak sağlayacağı üniversite belgeleridir (yönetmelikler, yönergeler, fakülte dokümanları, formlar vb.). PDF parsing bu kanalın temel bileşenidir.

#### [NEW] [backend/app/ingestion/pdf_parser.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/ingestion/pdf_parser.py)

**Özellikler:**
- `pdfplumber` ile PDF → metin dönüşümü (tablo desteği dahil)
- Sayfa numarası ve bölüm başlığı metadata olarak korunur
- Çıktı: `loader.py`'nin işleyebileceği standart Document listesi
- Yönetmelik PDF'leri için **madde bazlı bölme**: "Madde X —" kalıplarını tanır ve her maddeyi ayrı belge olarak çıkarır
- **Dizin tarama:** Bir klasördeki tüm PDF'leri tek komutla işleyebilir
- **Hata toleransı:** Bozuk tablo veya okunamayan sayfa tek PDF'in tamamını durdurmaz — sayfa bazlı try-except ile hatalı sayfalar loglanır, geri kalanı işlenmeye devam eder

**Kullanım senaryoları:**
```python
from app.ingestion.loader import load_pdf_file, load_pdf_directory

# Senaryo 1: Kullanıcı tek bir yönetmelik PDF'i yükler
load_pdf_file(
    path="data/pdfs/egitim_yonetmeligi.pdf",
    category="egitim",
    doc_kind="yonetmelik",
    source_url="https://www.gtu.edu.tr/..."
)

# Senaryo 2: Kullanıcı bir klasöre çok sayıda PDF koyar, hepsi toplu işlenir
load_pdf_directory(
    directory="data/pdfs/yonetmelikler/",
    category="egitim",
    doc_kind="yonetmelik"
)
```

**Toplu belge dizin yapısı:**
```
backend/data/pdfs/
├── yonetmelikler/           # Eğitim, öğrenci işleri, lisansüstü yönetmelikleri
├── yonergeler/              # Staj, bitirme projesi, muafiyet yönergeleri
├── fakulte_dokumanlari/     # Fakülte tanıtım, program bilgileri
├── idari_belgeler/          # Burs, harç, kayıt bilgilendirme
└── diger/                   # Sınıflandırılmamış belgeler
```

> [!IMPORTANT]
> Kullanıcı elindeki üniversite PDF/dokümanlarını ilgili alt klasöre koyar → `load_pdf_directory()` ile **tek komutla** hepsi parse → chunk → embed → veritabanına yüklenir. Bu, 19 ayrı JSON dosyası elle yazmaktan çok daha verimlidir.

#### [MODIFY] [requirements.txt](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/requirements.txt)
- `pdfplumber` eklenir

---

### 2.5 Hybrid Search (BM25 + Vektör)

> **Gerekçe:** Salt vektör araması, üniversite terminolojisi (form adları, yönetmelik isimleri, kısaltmalar) için yetersiz kalır. "YÖK", "AKTS", "transkript", "Madde 24" gibi terimler tam eşleşme ile daha iyi bulunur.

#### [MODIFY] [rag_service.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/services/rag_service.py)

**Retriever kararı: PostgreSQL Native Full-Text Search (`PgvectorKeywordRetriever`)**

> **Gerekçe:** Hybrid search için ayrı bir bellek içi doküman deposu (`InMemoryBM25Retriever`) kullanmak veritabanı senkronizasyonu sorunu, çift ingestion ihtiyacı ve gereksiz bellek kullanımı (%100 duplication) doğurur. Kesin çözüm: PostgreSQL'in kendi metin arama yeteneklerini (Full-Text Search) kullanan tek kaynaklı bir strateji. `haystack-pgvector` eklentisi içindeki `PgvectorKeywordRetriever` üzerinden uygulanır.

**Türkçe dil desteği (PostgreSQL Seviyesinde!):**
> [!IMPORTANT]
> PostgreSQL FTS varsayılan olarak `english` yapılandırmasını kurar. Türkçe çekim eklerinin ("yönetmeliği" ↔ "yönetmelik") kusursuz uyuşması için, PgVector tabloları ilklendirilirken veya `document_store` üzerinden dil yapılandırması `turkish` olarak belirtilmelidir (veya ham sorgu kullanılıyorsa `to_tsvector('turkish', content)`). Böylece Türkçe stemming PostgreSQL'in kendi sağlam C eklentileriyle çözülür, uygulama kodunda ek uğraş gerektirmez.

**Hybrid search pipeline:**
```
Kullanıcı sorusu
    ├─→ SentenceTransformersTextEmbedder → PgvectorEmbeddingRetriever (top_k=5)
    └─→ PgvectorKeywordRetriever (top_k=3)
                    ↓                              ↓
              DocumentJoiner (strategy="reciprocal_rank_fusion")
                              ↓
                    PromptBuilder → OllamaGenerator
```

**Pipeline bileşenleri:**
```python
from haystack.components.joiners import DocumentJoiner
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever, PgvectorKeywordRetriever

# ingestion ve arama tek mağazadan (PgvectorDocumentStore) yürütülür
```

**Gerekçe neden FTS (Keyword) kritik:**

| Soru türü | Salt vektör | Hybrid (BM25 + vektör) |
|-----------|-------------|------------------------|
| "AKTS nedir?" | ✅ semantik yakın | ✅✅ tam eşleşme + semantik |
| "Madde 24" | ❌ semantik olarak belirsiz | ✅ BM25 tam eşleşme |
| "transkript nasıl alınır" | ✅ iyi | ✅✅ "transkript" kelimesi doğrudan eşleşir |
| "yemekhane saatleri" | ✅ iyi | ✅✅ daha kesin |

**Config'e eklenen ayar:**
```python
RETRIEVER_VECTOR_TOP_K: int = 5
RETRIEVER_KEYWORD_TOP_K: int = 3
```

---

### 2.6 Prompt Template Güncelleme (Yönlendirme + Metadata)

#### [MODIFY] [rag_service.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/services/rag_service.py)

Prompt template'ine metadata bilgisi ve **yönlendirme talimatı** eklenir:

```
Belgeler:
{% for doc in documents %}
---
[{{ doc.meta.category | default("bilinmiyor") }}] {{ doc.meta.title | default("") }}
Kaynak: {{ doc.meta.source_url | default("belirtilmemiş") }}
{% if doc.meta.contact_unit %}İlgili birim: {{ doc.meta.contact_unit }}{% endif %}
{% if doc.meta.contact_info %}İletişim: {{ doc.meta.contact_info }}{% endif %}

{{ doc.content }}
{% endfor %}
```

**Ek prompt kuralı:**
```
8. Yanıtın sonunda, kullanıcının bu konuyla ilgili başvurabileceği birimi, telefon/e-posta bilgisini veya resmî web sayfası adresini belirt. Bu bilgi belgede varsa doğrudan kullan; yoksa en uygun birimi öner.
```

**Token bütçesi hesabı:**
| Bileşen | Tahmini token |
|---------|---------------|
| Sistem prompt'u (kurallar) | ~300 |
| Belgeler (5 × ~300 token chunk + metadata) | ~1700 |
| Kullanıcı sorusu | ~50 |
| **Toplam giriş** | **~2050** |
| Yanıt için kalan (Gemma3 4B: 8K context) | **~5950** |

Bu bütçe güvenli sınırlar içindedir. `top_k=5` korunabilir.

---

### 2.7 İlk Veri Seti: Altyapı Test Verisi

> **Gerekçe:** Faz 2'de altyapıyı test etmek için ayrı bir test dosyası kullanılır. Gerçek üniversite verileri Faz 3'te hazırlanır. Böylece test verisi ile üretim verisi karışmaz.

#### [NEW] [backend/data/_test_seed.json](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/data/_test_seed.json)

Altyapı testi için **5-10 belge** içeren test dosyası. Farklı kategorilerden örnek içerikler:
- 2 belge: `egitim` (ders kayıt, sınav)
- 2 belge: `yemekhane` (saatler, kurallar) 
- 2 belge: `ogrenci_isleri` (transkript, kayıt)
- 1 belge: `yonlendirme` (contact_unit/contact_info ile)
- 1 belge: `genel_bilgi`

Bu dosya `_` ön ekiyle başlar — üretim verisi değildir, altyapı testi amaçlıdır.

#### [NEW] [backend/data/_schema.json](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/data/_schema.json)

JSON Schema doğrulama dosyası. `loader.py` bu şemaya göre gelen dosyayı doğrular.

#### [NEW] [backend/data/pdfs/](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/data/pdfs/)

PDF kaynak dosyalarının saklanacağı dizin (Faz 3'te kullanılacak).

**Git stratejisi:** `backend/data/` Git'e dahil edilir (proje ve demo amaçlı). PDF dosyaları büyükse `.gitignore`'a eklenir ve ayrı aktarılır.

---

### 2.8 Config Güncellemeleri

#### [MODIFY] [config.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/config.py)

Yeni ayarlar:
```python
# Chunking (yapıya duyarlı — varsayılan "genel" strateji parametreleri)
CHUNK_MAX_CHARS: int = 1200        # ~300 token (all-mpnet-base-v2 sınırına güvenli mesafe)
CHUNK_OVERLAP_CHARS: int = 200     # Bağlam koruma
CHUNK_MIN_CHARS: int = 80          # Bundan kısa parçalar birleştirilir

# Retriever
RETRIEVER_VECTOR_TOP_K: int = 5    # Vektör araması
RETRIEVER_KEYWORD_TOP_K: int = 3   # BM25 kelime araması

# Veri yükleme
DATA_DIR: str = "data"
```

---

## Faz 3: Gerçek Üniversite Verisi Toplama ve Yükleme

> [!IMPORTANT]
> Bu faz, UniChat'in **gerçek sorulara gerçek cevaplar verebilme** yeteneğini kazandığı fazıdır. Veri toplama **toplu PDF/belge içe aktarma** ve **başlangıç düzeyinde scraping** ile yürütülür. Tam otomatik scraping altyapısı (yapısal keşif, zamanlama, kalite raporlama) Faz 4'te olgunlaşır.

### 3.0 Veri Toplama Stratejisi — İki Ana Kanal

**Temel ilke:** Manuel veri hazırlama, ana yöntem değildir. UniChat'in veri kaynakları iki birincil kanaldan beslenir:

| Kanal | Mekanizma | Açıklama |
|-------|-----------|----------|
| 📄 **Toplu Belge/PDF İçe Aktarma** | `load_pdf_directory()` | Kullanıcı, üniversiteye ait PDF/dokümanları (yönetmelikler, yönergeler, tanıtım belgeleri, formlar, ders planları vb.) `data/pdfs/` altına koyar. Ingestion pipeline hepsini toplu olarak parse → chunk → embed → yükler. |
| 🌐 **Web Scraping** | `scrapers/` | Üniversite web sitesinden (ana sayfa, fakülteler, bölümler, birimler, duyurular, etkinlikler, iletişim bilgileri) yapısal keşif + kontrollü scrape ile veri toplanır. |

**Üçüncü kanal (istisnai):**

| Kanal | Mekanizma | Sınırlı Kullanım |
|-------|-----------|------------------|
| ✍️ **Manuel JSON** | `load_json_file()` | **Yalnızca** web'de veya PDF'de bulunmayan son derece spesifik, yerel bilgiler için: (Örn: `2-Kampüs` veya `10-Ulaşım` içinde kalabilen küçük pratik notlar). Hedef: toplam verinin **%1'inden az.** |

### 3.0.1 Her Kategori için Veri Kanalı Haritası

| Kat. | Alan | Birincil Kanal | İkincil | Açıklama |
|------|------|----------------|---------|----------|
| 1 | Genel Bilgi | 🌐 Scraping | 📄 PDF | Ana sayfa, hakkında, tarihçe, yönetim, iletişim → scrape; kurumsal tanıtım broşürleri → PDF |
| 2 | Kampüs | 🌐 Scraping | ✍️ Manuel | Bina/tesis bilgileri web'den; harita ve yerel notlar → istisna |
| 3 | Eğitim | 📄 PDF | 🌐 Scraping | Yönetmelikler → toplu PDF; ders kayıt/sınav bilgileri → scrape |
| 4 | Bölümler | 🌐 Scraping | 📄 PDF | Fakülte/bölüm sayfaları → scrape; program tanıtım PDF'leri → PDF |
| 5 | Lisansüstü | 📄 PDF | 🌐 Scraping | Enstitü yönetmelikleri → PDF; başvuru bilgileri → scrape |
| 6 | Öğrenci İşleri | 📄 PDF | 🌐 Scraping | İlgili yönetmelikler → PDF; işlem adımları web sayfasından → scrape |
| 7 | Erasmus | 🌐 Scraping | 📄 PDF | Uluslararası ofis sayfaları → scrape; anlaşma listeleri → PDF |
| 8 | Topluluklar | 🌐 Scraping | — | SKS / kulüp sayfaları → scrape |
| 9 | Spor | 🌐 Scraping | — | Spor tesisleri sayfaları → scrape |
| 10 | Ulaşım | 🌐 Scraping | ✍️ Manuel | Ulaşım sayfası → scrape; ring/otopark özel bilgi → istisna |
| 11 | Yemekhane | 🌐 Scraping | — | Yemekhane sayfası → scrape; menü → scraper (periyodik) |
| 12 | Kütüphane | 🌐 Scraping | — | Kütüphane sayfası → scrape |
| 13 | Etkinlikler | 🌐 Scraping | — | Duyuru/etkinlik sayfaları → scrape |
| 14 | Akademik Kadro | 🌐 Scraping | — | Personel listeleri → scrape |
| 15 | Dijital Hizmetler | 🌐 Scraping | ✍️ Manuel | OBS, LMS vb. linkleri → scrape; özel kullanım kılavuzları → istisna |
| 16 | Duyurular | 🌐 Scraping | — | Duyuru arşivleri → scrape (periyodik) |
| 17 | Aday Öğrenci | 🌐 Scraping | 📄 PDF | Tanıtım sayfaları → scrape; tercih rehberi → PDF |
| 18 | Mezunlar | 🌐 Scraping | — | Kariyer merkezi → scrape |
| 19 | Yönlendirme | 🌐 Scraping | ✍️ Manuel | İlgili birim iletişim web sayfaları → scrape; eksik kalan nadir durumlar → istisna |

**Özet:** 19 kategoriden **15'i ağırlıklı scraping**, **4'ü ağırlıklı PDF**. Tamamı otomatik/toplu süreçler. Manuel JSON yazımı yalnızca test verisi ve çok nadir pratik notlar için istisnadır.

### 3.0.2 Öncelik Sırası

| Öncelik | Kategoriler | Gerekçe | Ana Kanal |
|---------|-------------|---------|----------|
| 🔴 P0 | 3-Eğitim, 6-Öğrenci İşleri, 1-Genel Bilgi | En sık sorulan | 📄 PDF + 🌐 Scraping |
| 🟡 P1 | 4-Bölümler, 11-Yemekhane, 12-Kütüphane, 10-Ulaşım | Günlük yaşam | 🌐 Scraping |
| 🟢 P2 | 2-Kampüs, 5-Lisansüstü, 7-Erasmus, 15-Dijital | Spesifik kitle | 🌐 + 📄 karışık |
| 🔵 P3 | 8-Topluluklar, 9-Spor, 13-Etkinlik, 14-Kadro | Destek | 🌐 Scraping |
| ⚪ P4 | 16-Duyurular, 17-Aday, 18-Mezun, 19-Yönlendirme | Dinamik | 🌐 Scraping |

---

### 3.1 P0 — Çekirdek Veriler (PDF + Erken Scraping)

> Bu adımda Faz 4'ün scraper altyapısı henüz hazır değil. P0 için **PDF toplu yükleme birincil kanal**, scraping ise P1'de hazırlanacak erken scraper ile tamamlanır.

**3.1.1 Eğitim ve Öğretim Süreçleri (Kategori 3)**
- **Birincil:** 📄 Kullanıcının sağladığı yönetmelik PDF'leri → `load_pdf_directory("data/pdfs/yonetmelikler/")` ile toplu yükleme
- **İçerik:** Eğitim-Öğretim Yönetmeliği, staj yönergesi, muafiyet yönergesi, sınav uygulama yönergesi vb.
- **Otomatik:** `pdf_parser.py` madde bazlı ayırır, her madde ayrı Document olur
- **Hedef:** ~30-80 belge (PDF sayısına göre)
- **Doğrulama:** Her belge için kaynak madde numarası metadata'da mevcut olmalı

**3.1.2 Öğrenci İşleri (Kategori 6)**
- **Birincil:** 📄 İlgili yönetmelik ve yönerge PDF'leri toplu yükleme
- **Tamamlayıcı:** İşlem adımlarını açıklayan web sayfaları (P1'de scraper hazır olunca eklenir)
- **`contact_unit` zorunlu:** Her belge birim yönlendirmesi içermeli
- **Hedef:** ~20-40 belge

**3.1.3 Üniversite Genel Bilgi (Kategori 1)**
- **Birincil:** 📄 Kurumsal tanıtım dokümanları (PDF/broşür)
- **Tamamlayıcı:** Ana sayfa, hakkında, tarihçe → scraper (P1'de eklenir)
- **Hedef:** ~15-25 belge

### 3.2 P1 — Günlük Yaşam Verileri (Başlangıç Scraping)

> Bu adımda **basit, çalışan bir scraper** kurulur ve ilk scraping'ler yapılır. Amaç veri toplamaktır, tam altyapı değil. Yapısal keşif (discovery), kalite raporlama ve zamanlama gibi ileri özellikler Faz 4'te eklenir.

**3.2.0 Basit Scraper Kurulumu**
- Minimum çalışan scraper: `base_scraper.py` (fetch + parse + to_documents) ve `utils.py` (HTML temizleme)
- Hedef: tek bir fakülteyi tarayarak veri toplayabilmek
- Discovery, quality_checker, scheduling **bu adımda yok** — Faz 4'te gelecek

**3.2.1 Fakülteler ve Bölümler (Kategori 4)**
- **Yöntem:** 🌐 Yapısal keşif + kontrollü scrape
- İlk fakülteyi keşfet → scrape → kalite kontrol → sonraki fakülteye geç
- Hedeflen sayfa türleri: hakkında, program, müfredat, ders planı, akademik personel, iletişim, duyurular
- **Ek:** Fakülte tanıtım PDF'leri varsa 📄 toplu yükleme

**3.2.2 Yemekhane (Kategori 11)** — 🌐 Scraping (yemekhane sayfası)

**3.2.3 Kütüphane (Kategori 12)** — 🌐 Scraping (kütüphane sayfası)

**3.2.4 Ulaşım (Kategori 10)** — 🌐 Scraping + ✍️ istisna (ring detayları web'de yoksa)

### 3.3 P2 — Spesifik Kitle Verileri

- Kampüs yapısı (Kategori 2) — 🌐 Scraping + ✍️ istisna (harita notları)
- Lisansüstü (Kategori 5) — 📄 Enstitü yönetmelikleri + 🌐 Scraping (başvuru bilgileri)
- Erasmus (Kategori 7) — 🌐 Scraping (uluslararası ofis sayfaları) + 📄 PDF (anlaşma listeleri)
- Dijital hizmetler (Kategori 15) — 🌐 Scraping + ✍️ istisna (OBS/LMS özel kullanım notları)

### 3.4 P3 — Destekleyici Veriler

- Topluluklar (Kategori 8) — 🌐 Scraping (SKS/kulüp sayfaları)
- Spor (Kategori 9) — 🌐 Scraping
- Etkinlikler (Kategori 13) — 🌐 Scraping (duyuru arşivleri)
- Akademik kadro (Kategori 14) — 🌐 Scraping (personel listeleri)

### 3.5 P4 — Dinamik Veriler (Periyodik Güncelleme Altyapısı)

- Duyurular (Kategori 16) — 🌐 Scraping (son 15 sayfa arşiv sınırı)
- Aday öğrenci (Kategori 17) — 🌐 Scraping + 📄 rehber PDF
- Mezunlar (Kategori 18) — 🌐 Scraping (kariyer merkezi)
- Yönlendirme (Kategori 19) — 🌐 Scraping (birim iletişim sayfaları taranıp otomatik birleştirilir)

### 3.6 Veri Kalitesi Doğrulama

Her öncelik grubu yüklendikten sonra:
1. **Sayısal kontrol:** Beklenen belge sayısı ile yüklenen eşleşiyor mu?
2. **Metadata kontrolü:** Tüm zorunlu alanlar dolu mu? `contact_unit` gerekli yerlerde var mı?
3. **Kaynak dağılımı:** `source_type` bazında belge sayısı — PDF vs web vs manual oranı
4. **Yanıt testi:** O kategoriden 3-5 örnek soru sor, cevap kalitesini değerlendir
5. **Yönlendirme testi:** "Transkript nasıl alınır?" gibi sorularda ilgili birim yanıtta var mı?
6. **Halüsinasyon testi:** Veritabanında olmayan bilgiyi sor → "bilmiyorum" beklenir
7. **Hybrid search testi:** "Madde 24", "AKTS" gibi terimler doğru eşleşiyor mu?

---

## Faz 4: Scraping Olgunlaştırma ve Periyodik Güncelleme

> Faz 3'te basit scraper ile başlangıç verisi toplandı. Bu faz, scraping'i **olgunlaştırır**: yapısal keşif (discovery), kalite raporlama, ileri scraper'lar, kapsam genişletme ve periyodik güncelleme altyapısı eklenir. [Scraping yaklaşım dokümanı](file:///c:/Users/ASUS/Masaüstü/unichat_proje/doc/web_scraping_yapisal%20_kesif_kontrollu_scrape_yaklasimi.md)'ndaki ilkeler tam olarak bu fazda uygulanır.

### 4.1 Scraping Altyapısı Olgunlaştırma

> Faz 3.2.0'da minimum scraper (`base_scraper.py`, `utils.py`) kuruldu. Bu adımda **tam altyapı** oluşturulur.

#### [NEW] Altyapı bileşenleri ve ileri scraper'lar

```
scrapers/    (mevcut base_scraper + utils'e ek olarak)
├── discovery.py               # Yapısal keşif modülü (site haritası, menü tarama)
├── quality_checker.py         # Scrape sonrası otomatik kalite raporu
├── department_scraper.py      # Fakülte/bölüm sayfaları (gelişmiş versiyon)
├── announcement_scraper.py    # Duyuru sayfaları scraper (arşiv sayfalama)
├── menu_scraper.py            # Yemekhane menü scraper
└── staff_scraper.py           # Akademik kadro listeleri scraper
```

### 4.2 Çalışma Akışı: Keşif → Scrape → Doğrula

**Her hedef site/fakülte için 3 aşamalı süreç:**

#### Aşama 1: Yapısal Keşif (`discovery.py`)
- Üniversite web yapısını analiz et: fakülte → bölüm → alt menü → detay sayfa mimarisini çıkar
- Header, sidebar, footer ve içerik menülerini ayrı ayrı incele
- Tekrarlayan navigasyon linklerini normalize edip deduplicate et
- Çıktı: keşfedilen URL'lerin yapılandırılmış listesi + breadcrumb bilgisi

#### Aşama 2: Kontrollü Scrape (`base_scraper.py` + alt sınıflar)
- Yalnızca keşif aşamasında tespit edilen URL'leri tara
- **Kapsam sınırı:** Yalnızca izin verilen üniversite alan adları
- **Arşiv sınırı:** Duyuru/haber/etkinlik arşivlerinde yalnızca en güncel **son 15 sayfa** taranır
- **İçerik çıkarma:** Gerçek sayfa metni (`innerText`) kaydedilir
- **Placeholder reddi:** "Content contains…", "yakında", "under construction" gibi ifadeler içerik olarak kaydedilmez; kalite problemi olarak işaretlenir
- **Kısa içerik istisnası:** İletişim sayfası, tek satırlık resmi ilan gibi doğal olarak kısa sayfalar hata sayılmaz

**`base_scraper.py` yapısı:**
- `fetch(url)`: Sayfa çekme — retry (3 deneme), timeout (30s), rate-limit (1 istek/saniye)
- `parse(html)`: HTML → temiz metin dönüşümü (BeautifulSoup / Trafilatura)
- `to_documents(data)`: Çekilen veri → Haystack Document listesi (metadata dahil)
- `scrape()`: Tam döngü — fetch → parse → validate → ingest pipeline

**Her sayfa için kaydedilen metadata:**
```python
{
    "source_url": str,
    "title": str,
    "faculty": str | None,
    "department": str | None,
    "doc_kind": str,        # "duyuru", "tanitim", "iletisim", "akademik_personel", vb.
    "breadcrumb": str,      # Sayfa yol izleme
    "extracted_at": str,    # ISO 8601 tarih
    "content_length": int,  # İçerik uzunluğu (karakter)
}
```

**PDF / DOC bağlantı tespiti:** Sayfa içinde bulunan `*.pdf`, `*.doc`, `*.docx`, `*.xls` linkleri ayrıca tespit edilip `source_type: "pdf"` olarak kaydedilir ve `pdf_parser.py`'ye yönlendirilir.

#### Aşama 3: Kalite Doğrulama (`quality_checker.py`)

Her scrape çalışmasından sonra otomatik rapor üretilir:

| Metrik | Açıklama |
|--------|----------|
| Keşfedilen URL sayısı | Keşif aşamasında bulunan toplam |
| Scrape edilen URL sayısı | Başarıyla içeriği çekilen |
| Atlanan / duplicate URL | Canonical veya hash eşleşmesiyle atlanan |
| Başarısız URL listesi | Her biri için hata nedeni (timeout, 404, 500…) |
| Metadata doluluk oranı | Zorunlu alanların dolu olma yüzdesi |
| Placeholder / boş içerik oranı | Reddedilen sahte içerik yüzdesi |
| `doc_kind` dağılımı | Tür bazında belge sayısı |
| Chunk kapsama oranı | Chunker'dan geçen / toplam |

### 4.3 Scraper → Ingestion Entegrasyonu

Scraper'lar `app/ingestion/` pipeline'ını kullanır — ayrı bir yükleme mekanizması yoktur:

```python
# department_scraper.py içinde:
from app.ingestion.loader import ingest_documents
documents = self.to_documents(scraped_data)
ingest_documents(documents, policy=DuplicatePolicy.OVERWRITE)
```

**Kaynak güncellendiğinde (delta update):**
1. Scraper yeni içeriği çeker
2. `SHA-256(content)` ile Document ID oluşturulur
3. `write_documents(policy=DuplicatePolicy.OVERWRITE)` → aynı ID'li belge varsa günceller, yoksa ekler
4. Chunk'lanmış belgeler için: `parent_doc_id` filtresiyle eski chunk'lar silinir, yeni chunk'lar eklenir

### 4.4 Zamanlama

#### [NEW] [backend/scheduler.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/scheduler.py)

**Teknoloji kararı: APScheduler** (Celery değil).

> **Gerekçe:** Proje ölçeğinde ek broker altyapısı (Redis/RabbitMQ) gereksiz karmaşıklık. APScheduler in-process çalışır ve yeterlidir.

> **Bilinen risk:** Uvicorn `--reload` modunda APScheduler duplicated job çalıştırabilir. Çözüm: `scheduler.py` içinde `replace_existing=True` ve PID kontrolü.

| Görev | Periyot | Scraper |
|-------|---------|---------|
| Duyuru kontrolü | 6 saatte bir | `announcement_scraper.py` |
| Yemekhane menüsü | Günde 1 (sabah 07:00) | `menu_scraper.py` |
| Bölüm sayfaları | Haftada 1 | `department_scraper.py` |
| Tam yeniden indeks | Ayda 1 | Tüm scraper'lar |

**Hata senaryoları:**
- Hedef site erişilemez → 3 retry, sonra log + atla, bir sonraki döngüde yeniden dene
- Scraper çöker → hata loglanır, diğer görevler etkilenmez
- Kısmi scrape → idempotent `DuplicatePolicy.OVERWRITE` sayesinde güvenli

---

## Faz 5: İleri Özellikler

### 5.1 Konuşma Geçmişi (Session)
- Frontend'de `sessionStorage` ile session ID saklama
- Backend'de session bazlı chat geçmişi sorgulama
- Son N mesajı prompt'a ekleme (bağlam penceresi)

### 5.2 Rate Limiting
- `slowapi` middleware ile IP bazlı rate limiting
- Dakikada max 20 istek
- Config'den yönetilebilir

### 5.3 Admin Paneli (Basit)
- **Mimari karar:** Backend'de FastAPI endpoint'leri + basit HTML/JS sayfası (React'ten bağımsız)
- Belge sayısı ve kategori dağılımı görüntüleme
- Manuel belge ekleme/silme
- Scraper durumu ve son çalışma raporu izleme
- Chat logları görüntüleme

### 5.4 Çok Dilli Destek (Altyapı)
- `language` metadata alanı zaten tanımlandı
- İngilizce belgeler eklenebilir
- Prompt'ta dil algılama ve uygun dilde yanıt

### 5.5 Performans İyileştirmeleri
- Pipeline async wrapper (`asyncio.to_thread`)
- Embedding cache (in-memory LRU)

---

## Verification Plan

### Faz 2 Doğrulama

#### Otomatik Testler

1. **Uçtan uca çalışma testi (Docker + Ollama gerektirir):**
   ```powershell
   docker ps | findstr unichat_db
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -m uvicorn main:app --reload --port 8000

   # Ayrı terminalde:
   curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d "{\"message\": \"Yemekhane kuralları nelerdir?\"}"
   curl http://localhost:8000/api/health
   ```
   **Beklenen:** JSON yanıt + kaynak bilgileri

2. **Ingestion pipeline testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from app.ingestion.loader import load_json_file; load_json_file('data/_test_seed.json', dry_run=True)"
   ```
   **Beklenen:** Dry-run raporu — "X belge yüklenecek" bilgisi

3. **Splitter testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from app.ingestion.splitter import split_document; print('Splitter OK')"
   ```

4. **PDF parser testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from app.ingestion.pdf_parser import parse_pdf; print('PDF Parser OK')"
   ```

5. **Hybrid search import testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from haystack.components.joiners import DocumentJoiner; print('Joiner OK')"
   ```

### Faz 3 Doğrulama

Her öncelik grubunun (P0-P4) yüklenmesinden sonra:

6. **Belge sayısı kontrolü:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "
   from app.services.rag_service import rag_service
   rag_service.build_pipeline()
   count = rag_service.document_store.count_documents()
   print(f'Toplam belge: {count}')
   "
   ```

7. **Yönlendirme testi:** "Transkript nasıl alınır?" → yanıtta birim adı ve iletişim bilgisi var mı?

8. **Hybrid search testi:** "Madde 24" → BM25 doğru yönetmelik maddesini buluyor mu?

### Manuel Doğrulama (Kullanıcı Tarafından)

> [!IMPORTANT]
> Aşağıdaki testler Docker (PostgreSQL + PgVector) ve Ollama'nın çalışır durumda olmasını gerektirir.

9. **Tarayıcıda uçtan uca:** Frontend'de her kategoriden soru sor, yanıt + kaynak + yönlendirme kontrol et

10. **Halüsinasyon testi:** Veritabanında olmayan bilgi sor → "bilgi bulunamadı, X birimine başvurunuz" beklenir

---

## Geliştirme Sırası Özeti

```
Faz 2.0 → Uçtan uca doğrulama + requirements-lock.txt
Faz 2.1 → Ingestion pipeline (iki kanallı: toplu PDF + scraper girişi)
Faz 2.2 → Metadata modeli (parent_doc_id, contact_unit, doc_kind)
Faz 2.3 → Yapıya duyarlı splitter
Faz 2.4 → PDF + toplu belge içe aktarma altyapısı
Faz 2.5 → Hybrid search (BM25 + vektör)
Faz 2.6 → Prompt template (yönlendirme + metadata + token bütçesi)
Faz 2.7 → Test verisi (_test_seed.json) + altyapı doğrulama
Faz 2.8 → Config güncellemeleri
  ↓
Faz 3.1 → P0: Toplu PDF yükleme (yönetmelikler, yönergeler, kurumsal belgeler)
Faz 3.2 → P1: Basit scraper kurulumu + başlangıç scraping (fakülte/bölüm/yemekhane/kütüphane)
Faz 3.3 → P2: Ek scraping + PDF (kampüs, lisansüstü, Erasmus, dijital)
Faz 3.4 → P3: Scraping (topluluklar, spor, etkinlikler, kadro)
Faz 3.5 → P4: Dinamik veriler + birim yönlendirme tablosu (istisna manuel)
Faz 3.6 → Kalite doğrulama (yanıt + yönlendirme + hybrid search + kaynak dağılımı)
  ↓
Faz 4.1 → Scraping olgunlaştırma (discovery, quality_checker, gelişmiş department_scraper)
Faz 4.2 → İleri scraper'lar (duyuru arşiv, menü, kadro)
Faz 4.3 → Kapsam genişletme + scraper → ingestion doğrulama
Faz 4.4 → APScheduler ile periyodik güncelleme
  ↓
Faz 5 → Session, rate limiting, admin paneli, çok dilli, performans
```
