# UniChat — Kapsamlı Uygulama Planı

## Genel Bakış

Bu plan, analiz raporunda belirlenen sorunları çözmek ve projeyi [project_context.md](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/doc/project_context.md)'deki vizyona taşımak için adım adım bir yol haritası sunar. Fazlar birbirine bağımlıdır — önceki faz tamamlanmadan sonrakine geçilmez.

---

## Faz 0: Mimari Refactoring (Temel — Öncelikli)

> [!IMPORTANT]
> Bu faz **tüm diğer fazların temelidir**. Mevcut monolitik yapı düzgün ayrılmadan yeni özellik eklemek teknik borcu katlar.

### 0.1 Backend Katmanlı Mimari

#### [NEW] [config.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/config.py)
- Pydantic `BaseSettings` ile merkezi konfigürasyon
- `DATABASE_URL`, `OLLAMA_URL`, `OLLAMA_MODEL`, `EMBEDDING_MODEL`, `CORS_ORIGINS`, `LOG_LEVEL` gibi tüm ayarları tek noktadan yönetme
- [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env) dosyasından otomatik okuma

#### [NEW] [models/schemas.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/models/schemas.py)
- [ChatRequest](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/main.py#84-86) — mesaj gönderme isteği
- `ChatResponse` — yanıt + kaynak bilgileri
- `SourceDocument` — belge kaynağı (URL, başlık, kategori)
- `HealthResponse` — sistem durumu

#### [NEW] [services/rag_service.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/services/rag_service.py)
- RAG pipeline oluşturma ve yönetimi
- `RagService` sınıfı: pipeline build, warm-up, query
- `PgvectorDocumentStore`, `Embedder`, `Retriever`, `PromptBuilder`, `OllamaGenerator` bileşenlerinin kapsüllenmesi
- Prompt template'inin bu serviste merkezi olarak yönetilmesi

#### [NEW] [services/chat_service.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/services/chat_service.py)
- Chat log kaydetme işlevi (`chat_logs` tablosuna)
- Session yönetimi için temel altyapı
- PII filtreleme (TC kimlik, öğrenci no vb. temizleme)

#### [NEW] [routers/chat.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/routers/chat.py)
- `POST /api/chat` endpoint'i
- Request doğrulama, servis çağrısı, response dönüşü
- Hata yönetimi

#### [NEW] [routers/health.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/routers/health.py)
- `GET /api/health` — sistem durumu kontrolü (DB, Ollama, Embedding bağlantı durumları)

#### [MODIFY] [main.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/main.py)
- Mevcut monolitik yapı kaldırılır
- `app` oluşturma, middleware ekleme, router'ları dahil etme
- `lifespan` event ile model warm-up
- Python `logging` modülüne geçiş (`print()` yerine)

#### [NEW] [app/__init__.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/app/__init__.py)
- Boş `__init__.py` dosyaları (paket tanımlama)

---

### 0.2 Frontend Bileşen Ayrımı

#### [NEW] [components/Header.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/Header.jsx)
- Logo, başlık, çevrimiçi durumu, dark mode toggle

#### [NEW] [components/ChatArea.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/ChatArea.jsx)
- Mesaj listesi container, otomatik scroll

#### [NEW] [components/MessageBubble.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/MessageBubble.jsx)
- Kullanıcı/bot mesaj baloncuğu, bot ikonu

#### [NEW] [components/InputBar.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/InputBar.jsx)
- Mesaj giriş formu, gönder butonu, disabled state

#### [NEW] [components/WelcomeScreen.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/WelcomeScreen.jsx)
- Karşılama ekranı, hızlı soru kartları

#### [NEW] [components/LoadingIndicator.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/components/LoadingIndicator.jsx)
- Yazıyor animasyonu (bouncing dots)

#### [NEW] [hooks/useChat.js](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/hooks/useChat.js)
- `messages`, `input`, `isLoading` state yönetimi
- [handleSend](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/frontend/src/App.jsx#31-59), [handleSubmit](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/frontend/src/App.jsx#60-64) fonksiyonları
- Tüm chat logic'inin [App.jsx](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/frontend/src/App.jsx)'ten ayrılması

#### [NEW] [services/api.js](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/services/api.js)
- Axios instance oluşturma
- `VITE_API_URL` ortam değişkeninden base URL okuma
- `sendMessage(text)` fonksiyonu

#### [MODIFY] [App.jsx](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/src/App.jsx)
- 221 satırlık monolitik yapıdan ~30 satırlık orchestrator bileşene dönüşüm
- `useChat` hook + bileşen composition

#### [NEW] [.env](file:///c:/Users/ASUS/Masaüstü/unichat_proje/frontend/.env)
- `VITE_API_URL=http://127.0.0.1:8000` — ortam bazlı API URL

---

### 0.3 Veritabanı Şema Tutarsızlığı Düzeltmesi

#### [MODIFY] [init_db.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/database/init_db.py)
- `knowledge_base` tablosu kaldırılır (Haystack kendi `haystack_docs` tablosunu yönetir)
- `chat_logs` tablosu korunur ve genişletilir (`source_documents JSONB` alanı eklenir)
- `department_feeds` tablosu korunur (Faz 2'de kullanılacak)
- [init.sql](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/database/init.sql) dosyasına temel extension kurulumu yazılır

#### [MODIFY] [init.sql](file:///c:/Users/ASUS/Masaüstü/unichat_proje/database/init.sql)
- `CREATE EXTENSION IF NOT EXISTS vector;` komutu eklenir

---

### 0.4 Güvenlik Düzeltmeleri

#### [MODIFY] [main.py](file:///c:/Users/ASUS/Masaüstü/unichat_proje/backend/main.py) *(0.1 ile birleşik)*
- CORS `allow_origins` → config'den okunan belirli origin'ler
- [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env)'deki parola güçlendirme notu

#### [MODIFY] [.env](file:///c:/Users/ASUS/Masaüstü/unichat_proje/.env)
- `CORS_ORIGINS`, `LOG_LEVEL`, `OLLAMA_URL`, `OLLAMA_MODEL` eklenir
- Parola güçlendirme tavsiyeleri (kullanıcıya bırakılır)

---

## Faz 1: Çekirdek İyileştirmeler

### 1.1 Chat Log Kaydetme
- `chat_service.py`'de her soru-cevap çiftini `chat_logs` tablosuna kaydetme
- Session ID üretme (UUID)
- PII filtreleme fonksiyonu (regex ile TC kimlik numarası vb.)

### 1.2 Kaynak Gösterme
- `rag_service.py`'de retriever'dan dönen belgelerin metadata'sını yanıta ekleme
- `ChatResponse` modeline `sources: list[SourceDocument]` alanı ekleme
- Frontend'de yanıtın altında kaynak kartları gösterme

### 1.3 Prompt İyileştirme (Guardrails)
- Prompt template'ine "Belgede yoksa tahmin yapma" kuralı güçlendirme
- Türkçe yanıt zorunluluğu ekleme
- Birime yönlendirme talimatı ekleme

### 1.4 Markdown Rendering (Frontend)
- `react-markdown` ve `remark-gfm` ekleme
- `MessageBubble` bileşeninde markdown rendering

### 1.5 Retriever İnce Ayar
- `top_k` parametresi ekleme (varsayılan 5)
- Config'den yönetilebilir hale getirme

---

## Faz 2: Veri Toplama ve Zenginleştirme

### 2.1 Web Scraping Altyapısı
- `scrapers/` klasörü oluşturma
- BeautifulSoup / Trafilatura ile üniversite sitesinden veri toplama
- Scrape edilen verilerin Document formatına dönüştürülmesi

### 2.2 PDF Parsing
- PyPDF2 / pdfplumber ile yönetmelik ve yönerge PDF'lerinin parse edilmesi
- Chunk'lara ayırma ve embedding

### 2.3 Delta Güncelleme
- SHA-256 hash ile değişiklik tespiti
- Upsert mekanizması

---

## Verification Plan

### Faz 0 Doğrulama

#### Otomatik Testler
1. **Backend başlatma testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from app.config import settings; print(settings.DATABASE_URL)"
   ```
   Beklenen: [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env)'den okunan DATABASE_URL değeri

2. **Import testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\backend
   python -c "from app.routers.chat import router; print('Router OK')"
   python -c "from app.services.rag_service import RagService; print('Service OK')"
   ```
   Beklenen: Her ikisinde de `OK` mesajı

3. **Frontend build testi:**
   ```powershell
   cd c:\Users\ASUS\Masaüstü\unichat_proje\frontend
   npm run build
   ```
   Beklenen: Build hatasız tamamlanır

### Manuel Doğrulama (Kullanıcı Tarafından)

> [!IMPORTANT]
> Aşağıdaki testler, Docker (PostgreSQL) ve Ollama'nın çalışır durumda olmasını gerektirir.

4. **Uçtan uca test:**
   - Backend'i başlat: `cd backend && python -m uvicorn app.main:app --reload --port 8000`
   - Frontend'i başlat: `cd frontend && npm run dev`
   - Tarayıcıda `http://localhost:5173` aç
   - Hızlı soru kartlarından birine tıkla
   - Yanıt geldiğini doğrula
   - Dark mode geçişinin çalıştığını doğrula

5. **Health endpoint testi:**
   - Tarayıcıda `http://localhost:8000/api/health` aç
   - JSON yanıt döndüğünü doğrula

6. **Bileşen ayrımı görsel kontrolü:**
   - Frontend'in önceki ile aynı göründüğünü doğrula (pixel-perfect olmasa da fonksiyonel eşdeğerlik)
