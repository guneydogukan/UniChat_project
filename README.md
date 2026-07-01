<div align="center">

# 🎓 UniChat

**Gaziantep İslam Bilim ve Teknoloji Üniversitesi (GİBTÜ) Yapay Zeka Asistanı**

Öğrencilerin, aday öğrencilerin, akademik/idari personelin ve ziyaretçilerin üniversiteye dair doğru bilgiye doğal dil üzerinden hızlı ve kaynaklı biçimde ulaşmasını sağlayan akıllı sohbet asistanı.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PgVector-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

</div>

---

## 📋 İçindekiler

- [Nasıl Çalışır](#-nasıl-çalışır)
- [Özellikler](#-özellikler)
- [Teknoloji Yığını](#-teknoloji-yığını)
- [Mimari](#-mimari)
- [Proje Yapısı](#-proje-yapısı)
- [Gereksinimler](#-gereksinimler)
- [Kurulum](#-kurulum)
- [Hızlı Kontrol](#-hızlı-kontrol)
- [Veri Hazırlama](#-veri-hazırlama)
- [Scheduler ve Güncellemeler](#-scheduler-ve-güncellemeler)
- [API Referansı](#-api-referansı)
- [Test](#-test)
- [Veritabanı Senaryoları](#-veritabanı-senaryoları)
- [Güvenlik ve Doğruluk](#-güvenlik-ve-doğruluk)
- [Geliştirme Notları](#-geliştirme-notları)
- [Yol Haritası](#-yol-haritası)

---

## 🧠 Nasıl Çalışır

UniChat klasik bir sohbet botu gibi yalnızca LLM yanıtına güvenmez. **İki aşamalı hibrit mimari** kullanır:

1. **DB-First Servisler** — Yemekhane menüsü, derslik konumları, akademik takvim, bölüm duyuruları, personel bilgileri ve program kataloğu gibi kesinlik gerektiren konularda doğrudan yapılandırılmış veritabanı tablolarından yanıt üretir.

2. **Hibrit RAG Pipeline** — DB servisleri yanıt üretemediğinde Haystack tabanlı hibrit arama (vektör + keyword) devreye girer ve Ollama LLM yalnızca getirilen kaynaklara dayanarak yanıt oluşturur.

---

## ✨ Özellikler

| Kategori | Detay |
| --- | --- |
| 🗣️ Doğal dil | Türkçe odaklı üniversite asistanı |
| 🔍 Hibrit RAG | Haystack 2.x ile vektör + keyword/full-text arama |
| 🤖 Yerel LLM | Ollama üzerinden `gemma3:4b-it-qat`, dış API gerektirmez |
| 🧬 Embedding | `intfloat/multilingual-e5-base` çok dilli embedding |
| 📎 Kaynak gösterme | URL, kategori ve metadata ile kaynak referansları |
| 🛡️ Guardrail | Kapsam dışı sorularda reddetme davranışı |
| ✅ Doğrulama | Yanıtlardaki URL, e-posta, telefon ve tarih kontrolü |
| 📄 Ingestion | PDF, JSON ve scraper çıktıları için ortak yükleme hattı |
| 🕷️ Scraping | Harita güdümlü canlı web scraping altyapısı |
| ⏰ Scheduler | APScheduler ile periyodik veri güncelleme |
| 📝 Loglama | Chat kayıtları ve kişisel veri filtreleme |

---

## 🛠️ Teknoloji Yığını

| Katman | Teknolojiler |
| --- | --- |
| **Frontend** | React 18 · Vite · TailwindCSS · Axios · react-markdown · lucide-react |
| **Backend** | Python · FastAPI · Uvicorn · Pydantic Settings |
| **Yapay Zeka** | Haystack 2.x · Ollama · Sentence Transformers · PgVector retriever'ları |
| **Veritabanı** | PostgreSQL · PgVector · JSONB · GIN indexleri |
| **Veri Toplama** | BeautifulSoup4 · lxml · requests · pdfplumber · PyMuPDF |
| **Zamanlama** | APScheduler |
| **Test** | unittest (unit · integration · regression · e2e) |

---

## 🏗️ Mimari

```mermaid
flowchart LR
    U["👤 Kullanıcı"] --> F["⚛️ React/Vite Frontend"]
    F --> A["⚡ FastAPI API"]
    A --> D["🗄️ DB-first Servisler"]
    D --> P["🐘 PostgreSQL + PgVector"]
    A --> R["🔍 Haystack Hibrit RAG"]
    R --> P
    R --> O["🤖 Ollama LLM"]
    A --> V["✅ Yanıt Doğrulama"]
    V --> F
    S["🕷️ Scraper + PDF Ingestion"] --> P
```

---

## 📁 Proje Yapısı

```
unichat_proje/
├── backend/
│   ├── app/
│   │   ├── ingestion/        # JSON, PDF ve scraper çıktısı yükleme hattı
│   │   ├── models/           # Pydantic ve belge modelleri
│   │   ├── repositories/     # Veritabanı erişim katmanı
│   │   ├── routers/          # FastAPI endpointleri
│   │   └── services/         # RAG, DB-first cevap servisleri ve doğrulama
│   ├── scrapers/             # GİBTÜ veri toplama ve güncelleme modülleri
│   ├── tests/                # Unit, integration, regression ve e2e testleri
│   ├── data/                 # Test verileri ve yerel veri çıktıları
│   ├── requirements.txt      # Python bağımlılıkları
│   ├── requirements-lock.txt # Sabitlenmiş bağımlılık sürümleri
│   └── main.py               # FastAPI uygulama girişi
├── frontend/
│   ├── src/
│   │   ├── components/       # Chat arayüz bileşenleri
│   │   ├── hooks/            # useChat state yönetimi
│   │   └── services/         # Axios API katmanı
│   ├── .env.example          # Frontend ortam değişkenleri şablonu
│   └── package.json
├── database/                 # PostgreSQL/PgVector şemaları ve seed SQL dosyaları
├── docker-compose.yml        # PostgreSQL + PgVector servisi
├── .env.example              # Backend ortam değişkenleri şablonu
└── README.md
```

---

## 📌 Gereksinimler

### Yazılım

| Araç | Sürüm | İndirme |
| --- | --- | --- |
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| Docker | — | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Ollama | — | [ollama.com](https://ollama.com/download) |
| Git | — | [git-scm.com](https://git-scm.com/downloads) |

### Donanım (Önerilen Minimumlar)

| Kaynak | Minimum | Önerilen |
| --- | --- | --- |
| RAM | 8 GB | 16 GB |
| Disk | ~5 GB boş | ~10 GB boş |
| GPU | Zorunlu değil | CUDA destekli (LLM hızlandırma) |

> **Not:** `gemma3:4b-it-qat` modeli **~3 GB**, `intfloat/multilingual-e5-base` embedding modeli **~1 GB** disk alanı kullanır. Her ikisi de ilk çalıştırmada otomatik indirilir.

### Platform Notu

Kurulum komutları **Windows (PowerShell)** için yazılmıştır.

<details>
<summary>🐧 Linux / macOS eşdeğer komutlar</summary>

| İşlem | PowerShell (Windows) | Bash (Linux/macOS) |
| --- | --- | --- |
| Dosya kopyalama | `Copy-Item .env.example .env` | `cp .env.example .env` |
| Venv aktivasyonu | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| HTTP istek testi | `Invoke-RestMethod <url>` | `curl <url>` |

</details>

---

## 🚀 Kurulum

### 1 · Projeyi Klonlama ve Ortam Değişkenleri

```powershell
git clone <repo-url> unichat_proje
cd unichat_proje
```

Backend ve frontend ortam dosyalarını oluşturun:

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env
```

Oluşan `.env` dosyası varsayılan yerel geliştirme değerlerini içerir. Gerekiyorsa düzenleyin:

```env
DATABASE_URL=postgresql://postgres:gizlisifre@localhost:5433/postgres
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b-it-qat
EMBEDDING_MODEL=intfloat/multilingual-e5-base
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
LOG_LEVEL=INFO
```

> Frontend ortam dosyası (`frontend/.env`) backend API adresini belirler. Varsayılan: `VITE_API_URL=http://127.0.0.1:8000`

### 2 · PostgreSQL + PgVector

Proje kök dizininde:

```powershell
docker compose up -d
```

`ankane/pgvector` imajıyla PostgreSQL veritabanını **5433** portunda başlatır.

### 3 · Ollama Kurulumu ve Model İndirme

[ollama.com/download](https://ollama.com/download) adresinden Ollama'yı indirip yükleyin.

Ollama servisinin çalıştığından emin olun:

```powershell
ollama serve
```

> Ollama Desktop uygulaması kullanıyorsanız servis zaten arka planda çalışıyor olabilir.

LLM modelini indirin (~3 GB):

```powershell
ollama pull gemma3:4b-it-qat
```

### 4 · Backend Kurulumu

Proje kök dizininde:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

<details>
<summary>📌 Deterministik kurulum (sürüm kilidi)</summary>

Bağımlılık sürümlerini sabitlemek için:

```powershell
python -m pip install -r backend\requirements-lock.txt
```

</details>

### 5 · Veritabanı Şeması ve Test Verisi

`backend/` dizinine geçerek şemayı oluşturun ve test verilerini yükleyin:

```powershell
cd backend
python database\init_db.py
python database\seed_data.py
```

### 6 · Backend API

Aynı terminalde, `backend/` dizinindeyken:

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> **İlk başlatmada** embedding modeli (`intfloat/multilingual-e5-base`, ~1 GB) otomatik indirilir ve `~/.cache/huggingface/` altına kaydedilir. İnternet hızına bağlı olarak birkaç dakika sürebilir.

### 7 · Frontend

**Ayrı bir terminal** açarak proje kök dizininden:

```powershell
cd frontend
npm install
npm run dev
```

### 8 · Erişim

| Servis | Adres |
| --- | --- |
| 🖥️ Frontend | http://localhost:5173 |
| ⚡ Backend API | http://127.0.0.1:8000 |
| 📘 Swagger Docs | http://127.0.0.1:8000/docs |

---

## ✅ Hızlı Kontrol

Kurulumu doğrulamak için:

```powershell
# Sağlık kontrolü
Invoke-RestMethod http://127.0.0.1:8000/api/health

# Chat testi
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/chat `
  -ContentType "application/json" `
  -Body '{"message":"GİBTÜ hakkında kısa bilgi verir misin?"}'
```

---

## 📦 Veri Hazırlama

`backend/` dizininde çalıştırın:

```powershell
# Test verisi yükleme
python database\seed_data.py

# PDF ön kontrol (dry-run)
python load_all_pdfs.py --dry-run

# PDF yükleme
python load_all_pdfs.py
```

PDF dosyaları `backend/data/pdfs/` altındaki kategori klasörlerinden okunur. Bu dizin `.gitignore` ile dışarıda bırakılmıştır.

---

## ⏰ Scheduler ve Güncellemeler

Scheduler, GİBTÜ web sitesinden periyodik veri toplama görevlerini yönetir. `backend/` dizininde çalıştırın:

```powershell
# Zamanlanmış görevleri listele
python -m scrapers.scheduler --list

# Scheduler'ı sürekli çalışır modda başlat
python -m scrapers.scheduler --start

# Belirli bir görevi elle çalıştır
python -m scrapers.scheduler --run-now <görev_adı>
```

**Kullanılabilir görevler:**

| Görev adı | Periyot | Açıklama |
| --- | --- | --- |
| `yemek` | Günde 1 (07:00) | Yemekhane menüsünü günceller |
| `duyuru` | Günde 1 (08:00) | Genel duyuruları günceller |
| `bolum_duyuru` | Haftada 1 (Pzt 08:30) | Bölüm duyurularını staging'e alır |
| `akademik_takvim` | Yılda 1 (1 Eylül) | Eğitim-öğretim yılı takvimi |
| `yonetim` | Dönem başı (Şub/Eyl) | Birim yönetim kadrolarını günceller |
| `idari_personel` | Dönem başı (Şub/Eyl) | İdari kadroyu günceller |
| `kadro` | Dönem başı (Şub/Eyl) | Akademik kadroyu günceller |
| `aday_ogrenci` | Dönem başı (Şub/Eyl) | Aday öğrenci portal verilerini günceller |
| `full_reindex` | Ayda 1 (ayın 1'i) | Tüm belge embedding'lerini yeniden oluşturur |

---

## 📡 API Referansı

| Method | Endpoint | Açıklama |
| --- | --- | --- |
| `POST` | `/api/chat` | Kullanıcı mesajını işler, kaynaklı yanıt döndürür |
| `GET` | `/api/health` | PostgreSQL, Ollama ve embedding durumunu kontrol eder |
| `GET` | `/api/yemek-menu` | Tarih veya tarih aralığı için yemekhane menüsü |
| `GET` | `/api/admin/department-announcements/status` | Bölüm duyurusu veri durumu |
| `POST` | `/api/admin/department-announcements/scrape` | Bölüm duyurularını staging'e alır |
| `GET` | `/api/admin/department-announcements/staging` | Staging duyuru kayıtlarını listeler |
| `POST` | `/api/admin/department-announcements/staging/{id}/approve` | Staging duyurusunu onaylar |
| `POST` | `/api/admin/department-announcements/staging/{id}/reject` | Staging duyurusunu reddeder |
| `POST` | `/api/admin/department-announcements/runs/{run_id}/approve` | Scrape run toplu onay |

> Detaylı API dokümantasyonu için: http://127.0.0.1:8000/docs

---

## 🧪 Test

### Backend

Proje kök dizininde, venv aktifken:

```powershell
# Tüm testleri çalıştır
python -m unittest discover -s backend\tests -p "test_*.py"

# Belirli test modülleri
python -m unittest backend.tests.unit.test_department_announcement_feature
```

> Bazı testler çalışan PostgreSQL, Ollama veya canlı veri kaynaklarına ihtiyaç duyar.

### Frontend

```powershell
cd frontend
npm run lint
npm run build
```

---

## 🗄️ Veritabanı Senaryoları

| Senaryo | Açıklama | Komutlar |
| --- | --- | --- |
| **Boş kurulum** | Şema + küçük test verisi | `init_db.py` → `seed_data.py` |
| **Demo kurulum** | Hazır demo dump ile restore | `pg_restore` ile `.dump` yükleme |
| **Güncel veri** | Scraper ve PDF ile veri toplama | `load_all_pdfs.py` + scheduler |

### Hızlı Başlangıç (Boş Kurulum)

```powershell
docker compose up -d

cd backend
python database\init_db.py
python database\seed_data.py
python -m uvicorn main:app --reload --port 8000
```

<details>
<summary>📥 Demo dump ile restore</summary>

Tam veriyle deneme için demo dump dosyasını (GitHub Releases veya harici link üzerinden) indirip proje köküne yerleştirin:

```powershell
$env:PGPASSWORD="gizlisifre"

pg_restore `
  --host localhost `
  --port 5433 `
  --username postgres `
  --dbname postgres `
  --clean `
  --if-exists `
  --no-owner `
  --no-acl `
  database\unichat_demo.dump
```

</details>

---

## 🔒 Güvenlik ve Doğruluk

- Yalnızca GİBTÜ ve üniversite bağlamındaki sorulara yanıt verir
- RAG yanıtları getirilen kaynak belgelerle sınırlandırılır
- Yanıtlardaki URL, telefon, e-posta ve tarih bilgileri kaynaklarla doğrulanır
- Kaynakta olmayan bilgi için tahmin üretmez, kullanıcıyı ilgili birime yönlendirir
- Chat log kayıtlarında kişisel veri filtreleme uygulanır
- LLM entegrasyonu tamamen yerel (Ollama); dış API zorunluluğu yoktur

---

## 📝 Geliştirme Notları

- `.env`, `.venv`, `node_modules/`, yerel PDF'ler ve scraper çıktıları `.gitignore` ile dışarıda bırakılır
- `doc/gibtu/` altındaki HTML dosyaları scraper'ların canlı siteyi hedefli taramasını sağlayan blueprint dosyalarıdır
- Yeni veri kaynakları eklenirken mevcut `app/ingestion/` hattı ve repository/service yapısı kullanılmalıdır
- Kesin cevap gerektiren alanlarda LLM yerine DB-first servis yaklaşımı tercih edilmelidir

---

## 🗺️ Yol Haritası

- [ ] Oturum bazlı konuşma geçmişi
- [ ] Rate limiting
- [ ] Admin paneli
- [ ] Çok dilli yanıt altyapısı
- [ ] Embedding cache ve performans iyileştirmeleri
- [ ] Ek birimler için yeni blueprint ve scraper kapsamı
