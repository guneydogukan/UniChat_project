# 🎓 UniChat Projesi — Kapsamlı Analiz ve Mimari Değerlendirme Raporu

> **Tarih:** 11 Mart 2026  
> **Durum:** Proje Faz 1 (Çekirdek RAG Mimarisi) — Prototip aşamasında

---

## 1. Proje Özeti

UniChat, GİBTÜ üniversitesi için geliştirilmekte olan **RAG (Retrieval-Augmented Generation)** tabanlı bir yapay zeka chatbot projesidir. Kullanıcılar doğal dilde sorular sorar; sistem, üniversite belgelerinden semantik arama yaparak yanıt üretir.

**Mevcut Durum:** Temel çalışan bir prototip mevcuttur. Backend RAG pipeline'ı kurulu, frontend chat arayüzü fonksiyonel, ancak proje erken aşamadadır ve [project_context.md](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/doc/project_context.md)'de tanımlanan kapsamlı vizyonun çok küçük bir kısmı gerçekleştirilmiştir.

---

## 2. Klasör Mimarisi

```
unichat_proje/
├── .env                          # Ortam değişkenleri (DB bağlantısı)
├── .gitignore                    # Git ayarları
├── docker-compose.yml            # PostgreSQL+PgVector konteyneri
├── backend/
│   ├── main.py                   # FastAPI + RAG pipeline (tek dosya)
│   ├── requirements.txt          # Python bağımlılıkları
│   ├── test_ai.py                # Basit Ollama bağlantı testi
│   └── database/
│       ├── init_db.py            # DB tablo oluşturma
│       └── seed_data.py          # Örnek veri yükleme
├── frontend/
│   ├── index.html                # HTML giriş noktası
│   ├── package.json              # React 18 + Vite + TailwindCSS
│   ├── tailwind.config.js        # Tailwind konfigürasyonu
│   ├── vite.config.js            # Vite konfigürasyonu
│   ├── public/                   # unichat.svg, vite.svg
│   └── src/
│       ├── main.jsx              # React entry point
│       ├── App.jsx               # Tüm UI (tek monolitik bileşen)
│       ├── App.css               # Poppins font import
│       ├── index.css             # Tailwind direktifleri
│       └── assets/               # react.svg
├── database/
│   └── init.sql                  # BOŞ dosya
└── doc/
    └── project_context.md        # Proje vizyonu ve kapsamı (355 satır)
```

---

## 3. Teknoloji Yığını

| Katman | Teknoloji | Versiyon / Detay |
|--------|-----------|------------------|
| **Frontend** | React + Vite | React 18.3, Vite 5.4 |
| **Stil** | TailwindCSS | v3.4, class-based dark mode |
| **HTTP İstemci** | Axios | v1.13 |
| **İkonlar** | Lucide React | v0.575 |
| **Backend** | FastAPI + Uvicorn | Python |
| **AI Framework** | Haystack 2.x | RAG pipeline orkestrasyon |
| **LLM** | Ollama → Gemma3 4B (QAT) | Yerel çalışan model |
| **Embedding** | sentence-transformers/all-mpnet-base-v2 | 768 boyut |
| **Veritabanı** | PostgreSQL + PgVector | Docker konteyner (port 5433) |
| **ORM/DB Erişim** | psycopg2-binary + SQLAlchemy | Doğrudan SQL + Haystack entegrasyonu |
| **Konteynerizasyon** | Docker Compose | pgvector image |

---

## 4. Veri Akışı (RAG Pipeline)

```mermaid
graph LR
    A["👤 Kullanıcı"] -->|Soru| B["React Frontend<br/>(App.jsx)"]
    B -->|POST /api/chat| C["FastAPI Backend<br/>(main.py)"]
    C --> D["SentenceTransformers<br/>Text Embedder"]
    D -->|768-dim vektör| E["PgVector<br/>Embedding Retriever"]
    E -->|İlgili belgeler| F["Prompt Builder<br/>(Jinja2 Template)"]
    F -->|Zenginleştirilmiş prompt| G["Ollama Generator<br/>(Gemma3 4B)"]
    G -->|Yanıt| C
    C -->|JSON response| B
    B -->|Görüntüle| A

    style A fill:#4CAF50,color:#fff
    style G fill:#FF5722,color:#fff
    style E fill:#2196F3,color:#fff
```

**Pipeline Adımları:**
1. Kullanıcı sorusu React frontend'den `POST /api/chat` endpoint'ine gönderilir
2. `SentenceTransformersTextEmbedder` soruyu 768 boyutlu vektöre dönüştürür
3. `PgvectorEmbeddingRetriever` veritabanında en yakın belgeleri getirir
4. `PromptBuilder` belgeleri ve soruyu birleştirip LLM prompt'u oluşturur
5. `OllamaGenerator` (Gemma3 4B) nihai yanıtı üretir
6. Yanıt JSON olarak frontend'e döner

---

## 5. Güçlü Yönler ✅

| # | Güçlü Yön | Açıklama |
|---|-----------|----------|
| 1 | **Tamamen yerel mimari** | Tüm AI işlemleri lokalde çalışır — KVKK uyumlu, API maliyeti sıfır, veri gizliliği korunur |
| 2 | **Modern teknoloji seçimi** | Haystack 2.x, FastAPI, React 18, Vite — endüstri standardı ve performanslı araçlar |
| 3 | **RAG mimarisi** | Halüsinasyon riski azaltılmış, belge tabanlı yanıt üretimi |
| 4 | **Docker ile izole veritabanı** | PgVector konteyneri ile tutarlı ve taşınabilir veritabanı ortamı |
| 5 | **Dark mode desteği** | Frontend'de class-based dark/light tema geçişi mevcut |
| 6 | **Kapsamlı proje vizyonu** | [project_context.md](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/doc/project_context.md)'de 19 başlıklı detaylı bir kapsam tanımı yapılmış |
| 7 | **Modüler pipeline yapısı** | Haystack bileşenleri takılıp çıkarılabilir mimaride tasarlanmış |
| 8 | **Hızlı sorular (Quick Questions)** | Frontend'de kullanıcıyı yönlendirici örnek soru kartları mevcut |

---

## 6. Zayıf Yönler ve Riskli Noktalar ⚠️

### 6.1 Mimari ve Yapısal Sorunlar

> [!CAUTION]
> **Monolitik Backend**: Tüm backend mantığı tek bir [main.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/main.py) dosyasında (119 satır). Router, servis, model ve konfigürasyon katmanları ayrılmamış.

> [!CAUTION]
> **Monolitik Frontend**: Tüm UI tek bir [App.jsx](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/frontend/src/App.jsx) dosyasında (221 satır). Header, ChatArea, MessageBubble, InputBar gibi bileşenler ayrılmamış.

| # | Sorun | Etki | Öncelik |
|---|-------|------|---------|
| 1 | Backend tek dosyada monolitik | Bakım zorluğu, test edilemezlik | 🔴 Yüksek |
| 2 | Frontend tek bileşende monolitik | Bakım zorluğu, yeniden kullanılabilirlik yok | 🔴 Yüksek |
| 3 | Router/servis/model katmanları yok | Separation of Concerns ihlali | 🔴 Yüksek |
| 4 | Error handling yetersiz (frontend) | Kullanıcıya anlamlı hata mesajı verilmiyor | 🟡 Orta |
| 5 | Ortam değişkenleri frontend'de hardcoded | API URL `http://127.0.0.1:8000` sabit | 🟡 Orta |

### 6.2 Güvenlik Riskleri

> [!WARNING]
> **Kritik güvenlik açıkları mevcut — üretim öncesi mutlaka düzeltilmeli.**

| # | Risk | Detay | Öncelik |
|---|------|-------|---------|
| 1 | **CORS `allow_origins=["*"]`** | Tüm origin'lere izin verilmiş — XSS ve CSRF riski | 🔴 Kritik |
| 2 | **DB şifresi açık metin** | [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env)'de `gizlisifre`, docker-compose'da da hardcoded | 🔴 Kritik |
| 3 | **Kimlik doğrulama yok** | API endpoint'e herhangi biri erişebilir | 🔴 Kritik |
| 4 | **Rate limiting yok** | DDoS ve abuse riski | 🟡 Orta |
| 5 | **Input validation minimum** | Sadece boş string kontrolü — injection riski | 🟡 Orta |
| 6 | **Chat logları kaydedilmiyor** | `chat_logs` tablosu mevcut ama kullanılmıyor | 🟡 Orta |

### 6.3 Veri ve İçerik Sorunları

| # | Sorun | Detay | Öncelik |
|---|-------|-------|---------|
| 1 | **Sadece 3 örnek belge** | [seed_data.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/seed_data.py)'de yalnızca 3 kısa metin mevcut | 🔴 Kritik |
| 2 | **[init.sql](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/database/init.sql) boş** | Docker başlatma SQL dosyası tamamen boş | 🟡 Orta |
| 3 | **DB şema tutarsızlığı** | [init_db.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/init_db.py) 3 tablo oluşturur (`knowledge_base`, `chat_logs`, `department_feeds`), ancak Haystack kendi `haystack_docs` tablosunu kullanır — tablolar birbiriyle konuşmuyor | 🔴 Yüksek |
| 4 | **Kaynak gösterme yok** | Proje dokümanında zorunlu tutulmasına rağmen, yanıtlarda kaynak URL'si ve metadata gösterilmiyor | 🟡 Orta |
| 5 | **Web scraping altyapısı yok** | Faz 2'de planlanan dinamik veri toplama henüz yok | 🟡 Beklenen |

### 6.4 Performans ve Ölçeklenebilirlik

| # | Sorun | Detay |
|---|-------|-------|
| 1 | Pipeline senkron çalışıyor | `rag_pipeline.run()` blocking — eş zamanlı isteklerde darboğaz |
| 2 | Model warm-up startup'ta | Uygulama başlangıcında model yüklenir — cold start süresi uzun |
| 3 | Top-k retriever ayarı yok | Varsayılan sayıda belge getiriliyor, ince ayar yapılmamış |
| 4 | Embedding cache yok | Aynı soru tekrar sorulduğunda tekrar embed ediliyor |

### 6.5 Eksik Özellikler (Proje Vizyonuna Göre)

| # | Eksik Özellik | Proje Dokümanındaki Referans |
|---|---------------|------------------------------|
| 1 | Konuşma geçmişi (session) | Chat logları tablosu var ama kullanılmıyor |
| 2 | Çoklu veri kaynağı entegrasyonu | Faz 2 — web scraping, RSS, API |
| 3 | Kaynak gösterme ve metadata | Guardrails bölümünde zorunlu tutulan |
| 4 | Akıllı yönlendirme (birim aktarımı) | Kapsam 19'da tanımlanan |
| 5 | Çok dilli destek | Vizyon belgesinde belirtilen |
| 6 | Kullanıcı kimlik doğrulama | Güvenlik gereksinimleri |
| 7 | Admin paneli / veri yönetimi | İçerik yönetimi için gerekli |
| 8 | Markdown/bağlantı render | Bot yanıtları düz metin olarak gösteriliyor |

---

## 7. Kod Kalitesi Değerlendirmesi

### Backend ([main.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/main.py))
- ✅ Haystack pipeline'ı doğru bağlanmış
- ✅ CORS middleware eklenmiş
- ✅ Hata yakalama ve loglama mevcut (temel)
- ❌ Tüm mantık tek dosyada
- ❌ Async endpoint ama pipeline senkron çalışıyor
- ❌ Konfigürasyon yönetimi yok (hardcoded model isimleri, URL'ler)
- ❌ Loglama `print()` ile yapılıyor — proper logging yok

### Backend ([init_db.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/init_db.py) + [seed_data.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/seed_data.py))
- ✅ Veritabanı şeması düşünülmüş (knowledge_base, chat_logs, department_feeds)
- ❌ [init_db.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/init_db.py) tabloları ile [main.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/main.py) pipeline'ı farklı tablolar kullanıyor
- ❌ [seed_data.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/seed_data.py)'de `recreate_table=True` — her çalıştırmada tablo sıfırlanır
- ❌ Gerçek üniversite verisi yok, yalnızca 3 örnek cümle

### Frontend ([App.jsx](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/frontend/src/App.jsx))
- ✅ Temiz ve modern UI tasarımı
- ✅ Dark mode toggle çalışıyor
- ✅ Loading animasyonu mevcut
- ✅ Quick questions özelliği iyi düşünülmüş
- ❌ Tüm UI tek bileşende
- ❌ API URL hardcoded
- ❌ Mesaj geçmişi kalıcı değil (sayfa yenilemede kaybolur)
- ❌ Markdown rendering yok
- ❌ Erişilebilirlik (a11y) eksik

### Konfigürasyon
- ✅ [.gitignore](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.gitignore) düzgün ayarlanmış
- ✅ Docker Compose düzgün çalışıyor
- ❌ [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env) dosyasında sadece DATABASE_URL var
- ❌ [requirements.txt](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/requirements.txt)'de versiyon sabitlemesi yok (pip freeze yapılmamış)

---

## 8. Kritik Bulgular ve Öncelikli Aksiyonlar

### 🔴 Acil (Geliştirmeye Başlamadan Önce)

1. **Backend mimarisini katmanlı yapıya geçir** — `routers/`, `services/`, `models/`, `config/` klasörleri oluştur
2. **Frontend bileşenlerini ayır** — `components/` altında modüler yapı kur
3. **DB şema tutarsızlığını çöz** — [init_db.py](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/backend/database/init_db.py) tabloları ile Haystack tablosunu uyumlu hale getir
4. **Güvenlik düzeltmeleri** — CORS kısıtla, [.env](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/.env) şifrelerini güçlendir

### 🟡 Yüksek Öncelik (Faz 1 Kapanışı İçin)

5. **Gerçek üniversite verileri ile seed** — PDF/web'den veri toplayıp veritabanına yükle
6. **Chat log kaydetme** — `chat_logs` tablosunu aktif kullan
7. **Kaynak gösterme** — Yanıtlarda belge kaynağı göster
8. **Konfigürasyon yönetimi** — Pydantic Settings ile merkezi config
9. **Proper logging** — `print()` yerine Python `logging` modülü

### 🟢 Orta Öncelik (Faz 2+ İçin)

10. **Web scraping pipeline** — Üniversite sitesinden veri toplama
11. **Konuşma geçmişi** — Session bazlı chat hafızası
12. **Rate limiting** — API koruma
13. **Markdown rendering** — Frontend'de zengin metin gösterimi
14. **Admin paneli** — Veri yönetimi ve izleme

---

## 9. Önerilen Hedef Mimari

```
unichat_proje/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app oluşturma
│   │   ├── config.py            # Pydantic Settings
│   │   ├── routers/
│   │   │   ├── chat.py          # /api/chat endpoint
│   │   │   └── health.py        # /api/health endpoint
│   │   ├── services/
│   │   │   ├── rag_service.py   # RAG pipeline yönetimi
│   │   │   └── chat_service.py  # Chat log kaydetme
│   │   ├── models/
│   │   │   ├── schemas.py       # Pydantic request/response
│   │   │   └── database.py      # DB modelleri
│   │   └── middleware/
│   │       └── rate_limiter.py  # Rate limiting
│   ├── database/
│   │   ├── init_db.py
│   │   └── seed_data.py
│   ├── scrapers/                # Faz 2 — veri toplama
│   ├── tests/                   # Test dosyaları
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── Header.jsx
│       │   ├── ChatArea.jsx
│       │   ├── MessageBubble.jsx
│       │   ├── InputBar.jsx
│       │   ├── QuickQuestions.jsx
│       │   └── WelcomeScreen.jsx
│       ├── hooks/
│       │   └── useChat.js       # Chat logic hook
│       ├── services/
│       │   └── api.js           # Axios config
│       ├── App.jsx
│       └── main.jsx
├── docker-compose.yml
└── .env
```

---

## 10. Sonuç

UniChat projesi **doğru teknoloji seçimleri** (yerel LLM, RAG, Haystack, FastAPI) üzerine kurulu, ancak şu an **erken prototip** aşamasındadır. [project_context.md](file:///c:/Users/ASUS/Masa%C3%BCst%C3%BC/unichat_proje/doc/project_context.md)'de tanımlanan kapsamlı vizyon ile mevcut kod arasında önemli bir boşluk bulunmaktadır.

**Sonraki adım:** Bu analize dayanarak, projenin fazlarına uygun bir **detaylı uygulama planı** hazırlamak ve adım adım geliştirmeye geçmek. 

> [!IMPORTANT]
> Geliştirmeye başlamadan önce bu analizi incelemenizi ve önceliklendirme / kapsam konusunda geri bildiriminizi bekliyorum.
