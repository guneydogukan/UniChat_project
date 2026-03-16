# UniChat — Geliştirme Görev Takibi (v4)

> **Son Güncelleme:** 16 Mart 2026

---

## Faz 0: Mimari Refactoring ✅
- [x] Uygulama planı oluştur ve onay al
- [x] Backend katmanlı yapıya geçir (routers, services, models, config)
- [x] Frontend bileşenlerini ayır (components, hooks, services)
- [x] DB şema tutarsızlığını çöz
- [x] Güvenlik düzeltmeleri (CORS, .env)
- [x] Konfigürasyon yönetimi (Pydantic Settings)
- [x] Proper logging altyapısı

## Faz 1: Çekirdek İyileştirmeler ✅
- [x] Chat log kaydetme özelliği
- [x] Kaynak gösterme (metadata + URL)
- [x] Prompt iyileştirme (guardrails)
- [x] Markdown rendering (frontend)
- [x] Hata yönetimi iyileştirme

---

## Faz 2: Uçtan Uca Doğrulama + Veri Besleme Altyapısı
- [x] **2.0** Uçtan uca doğrulama + stabilizasyon
  - [x] Docker konteyner çalışıyor mu
  - [x] `init_db.py` → tablolar oluştur
  - [x] `seed_data.py` → mevcut 3 veriyi yükle
  - [x] Backend başlat → `/api/health` test
  - [x] Frontend → soru sor → yanıt al
  - [x] `pip freeze > requirements-lock.txt`
- [x] **2.1** İki kanallı ingestion pipeline
  - [x] `app/ingestion/` modülü oluştur (loader, validators)
  - [x] `load_json_file()` — JSON'dan belge yükleme
  - [x] `load_pdf_file()` — tek PDF yükleme
  - [x] `load_pdf_directory()` — dizindeki tüm PDF'leri toplu yükleme
  - [x] `ingest_documents()` — scraper çıktısını yükleme
  - [x] `seed_data.py` → ingestion wrapper'a dönüştür
  - [x] Haystack `DuplicatePolicy` ile native duplicate yönetimi
- [ ] **2.2** Metadata modeli
  - [ ] `document_models.py` — 19 kategori + doc_kind tanımları
  - [ ] `source_id` — içerikten bağımsız sabit kaynak kimliği (güncelleme akışı için)
  - [ ] `parent_doc_id` = orijinal belgenin source_id'si + `chunk_index`
  - [ ] `contact_unit` + `contact_info` (yönlendirme)
  - [ ] JSON şema doğrulama (`_schema.json`)
- [ ] **2.3** Yapıya duyarlı splitter
  - [ ] `app/ingestion/splitter.py` — doc_kind'a göre farklı strateji
  - [ ] CHUNK_MAX_CHARS=1200 (~300 token, model güvenli sınır)
  - [ ] Her chunk'a parent_doc_id + chunk_index metadata aktar
  - [ ] Haystack `DocumentSplitter` entegrasyonu (genel belgeler)
- [ ] **2.4** PDF + toplu belge içe aktarma altyapısı
  - [ ] `app/ingestion/pdf_parser.py` (pdfplumber)
  - [ ] Madde bazlı bölme (yönetmelik PDF'leri için)
  - [ ] Sayfa bazlı hata toleransı (bozuk tablo tüm PDF'i durdurmasın)
  - [ ] Dizin tarama (tüm PDF'leri tek komutla işleme)
  - [ ] `data/pdfs/` alt dizin yapısı oluştur
  - [ ] `pdfplumber` dependency ekle
- [ ] **2.5** Hybrid search (BM25 + vektör)
  - [ ] `PgvectorKeywordRetriever` (PostgreSQL native FTS)
  - [ ] PostgreSQL FTS Türkçe dil entegrasyonu (stemming için)
  - [ ] `DocumentJoiner` (reciprocal_rank_fusion)
  - [ ] Config: RETRIEVER_VECTOR_TOP_K=5, KEYWORD_TOP_K=3
- [ ] **2.6** Prompt template güncelleme
  - [ ] Metadata (kategori, kaynak, birim) template'e ekle
  - [ ] Yönlendirme talimatı (kural 8)
  - [ ] Token bütçesi doğrula (~2050 / 8K)
- [ ] **2.7** Test verisi
  - [ ] `data/_test_seed.json` (5-10 test belgesi)
  - [ ] `data/_schema.json`
  - [ ] Ingestion pipeline ile test yükle ve doğrula
- [ ] **2.8** Config güncellemeleri
  - [ ] Chunking, retriever, DATA_DIR parametreleri

## Faz 3: Gerçek Üniversite Verisi Toplama ve Yükleme
- [ ] **3.1** P0 — Çekirdek veriler (📄 Toplu PDF birincil)
  - [ ] 📄 Yönetmelik/yönerge PDF'lerini `data/pdfs/yonetmelikler/` altına topla
  - [ ] `load_pdf_directory()` ile toplu yükleme
  - [ ] Madde bazlı otomatik bölünme doğrulama
  - [ ] contact_unit yönlendirme testi
  - [ ] P0 yanıt kalitesi + halüsinasyon + hybrid search testi
- [ ] **3.2** P1 — Günlük yaşam (başlangıç scraping)
  - [ ] **3.2.0** Basit scraper kurulumu
    - [ ] `base_scraper.py` (fetch + parse + to_documents)
    - [ ] `utils.py` (HTML temizleme)
  - [ ] 🌐 İlk fakülte scraping (keşif → scrape döngüsü)
  - [ ] 🌐 Yemekhane, kütüphane, ulaşım sayfaları scraping
  - [ ] P1 yanıt kalitesi testi
- [ ] **3.3** P2 — Spesifik kitle
  - [ ] 🌐+📄 Kampüs, lisansüstü, Erasmus, dijital hizmetler
- [ ] **3.4** P3 — Destekleyici
  - [ ] 🌐 Topluluklar, spor, etkinlikler, kadro scraping
- [ ] **3.5** P4 — Dinamik veriler
  - [ ] 🌐 Duyurular, aday öğrenci, mezunlar, yönlendirme (iletişim sayfaları) scraping
- [ ] **3.6** Veri kalitesi doğrulama (genel)
  - [ ] Kaynak dağılımı raporu (PDF vs web vs manuel oranı)
  - [ ] Yönlendirme ve hybrid search testleri
  - [ ] Kategori bazlı kapsam kontrolü

## Faz 4: Scraping Olgunlaştırma ve Periyodik Güncelleme
- [ ] **4.1** Scraping altyapısı olgunlaştırma
  - [ ] `discovery.py` — yapısal keşif (site haritası, menü tarama)
  - [ ] `quality_checker.py` — scrape sonrası otomatik kalite raporu
  - [ ] `department_scraper.py` gelişmiş versiyon (menü-alt menü tarama)
- [ ] **4.2** İleri scraper'lar
  - [ ] `announcement_scraper.py` (duyuru arşiv, son 15 sayfa sınırı)
  - [ ] `menu_scraper.py` (yemekhane menü)
  - [ ] `staff_scraper.py` (akademik kadro listeleri)
- [ ] **4.3** Kapsam genişletme + entegrasyon
  - [ ] Kalan fakülteler/birimler için scraping tamamlama
  - [ ] PDF/DOC link tespiti → pdf_parser yönlendirme
  - [ ] `DuplicatePolicy.OVERWRITE` ile delta güncelleme doğrulama
  - [ ] Chunk güncelleme (parent_doc_id filtresiyle eski chunk sil)
- [ ] **4.4** APScheduler zamanlama
  - [ ] Duyurular: 6 saatte bir
  - [ ] Yemekhane: günde 1
  - [ ] Bölümler: haftada 1
  - [ ] Tam indeks: ayda 1
  - [ ] `replace_existing=True` + PID kontrolü

## Faz 5: İleri Özellikler
- [ ] **5.1** Konuşma geçmişi (session)
- [ ] **5.2** Rate limiting (slowapi)
- [ ] **5.3** Admin paneli (FastAPI + basit HTML/JS)
- [ ] **5.4** Çok dilli destek (altyapı)
- [ ] **5.5** Performans (async wrapper, embedding cache)
