# UniChat

UniChat, Gaziantep İslam Bilim ve Teknoloji Üniversitesi (GİBTÜ) için geliştirilmiş yapay zeka destekli bir üniversite asistanıdır. Amaç; öğrencilerin, aday öğrencilerin, akademik/idari personelin ve ziyaretçilerin üniversiteye dair doğru bilgiye doğal dil üzerinden hızlı, kaynaklı ve yönlendirici biçimde ulaşmasını sağlamaktır.

Sistem klasik bir sohbet botu gibi yalnızca LLM yanıtına güvenmez. Yemekhane, derslik konumları, akademik takvim, bölüm duyuruları, akademik/idari personel, program kataloğu, YÖK Atlas verileri ve iş akışları gibi kesinlik gerektiren konularda önce yapılandırılmış veritabanı servislerini kullanır. Bu servisler cevap üretemediğinde Haystack tabanlı hibrit RAG pipeline devreye girer.

## Özellikler

- Türkçe odaklı doğal dil üniversite asistanı
- FastAPI tabanlı backend API
- React, Vite ve TailwindCSS ile chat arayüzü
- PostgreSQL + PgVector üzerinde belge ve embedding saklama
- Haystack 2.x ile hibrit RAG: vektör arama + keyword/full-text arama
- Ollama üzerinden yerel LLM kullanımı
- E5 tabanlı çok dilli embedding altyapısı
- Kaynak URL, kategori ve metadata ile kaynak gösterme
- Kapsam dışı sorular için guardrail ve reddetme davranışı
- Yanıt sonrası URL, e-posta, telefon ve tarih doğrulama
- PDF, JSON ve scraper çıktıları için ortak ingestion hattı
- Harita güdümlü canlı scraping altyapısı
- Periyodik güncelleme için APScheduler tabanlı scheduler
- Chat loglama ve kişisel veri filtreleme yaklaşımı

## Teknoloji Yığını

| Katman | Teknolojiler |
| --- | --- |
| Frontend | React 18, Vite, TailwindCSS, Axios, react-markdown, remark-gfm, lucide-react |
| Backend | Python, FastAPI, Uvicorn, Pydantic Settings |
| Yapay zeka | Haystack, Ollama, Sentence Transformers, Pgvector retriever'ları |
| Veritabanı | PostgreSQL, PgVector, JSONB, GIN indexleri |
| Veri toplama | BeautifulSoup4, lxml, requests, pdfplumber, PyMuPDF |
| Zamanlama | APScheduler |
| Test | unittest tabanlı unit, integration, regression ve e2e testleri |

## Mimari

```mermaid
flowchart LR
    U["Kullanıcı"] --> F["React/Vite frontend"]
    F --> A["FastAPI API"]
    A --> D["DB-first servisler"]
    D --> P["PostgreSQL + PgVector"]
    A --> R["Haystack hibrit RAG"]
    R --> P
    R --> O["Ollama LLM"]
    A --> V["Yanıt doğrulama"]
    V --> F
    S["Scraper + PDF ingestion"] --> P
```

Backend, kullanıcı sorusunu önce deterministik servislerden geçirir. Örneğin "Bugün yemekte ne var?", "Z-114 nerede?", "Bilgisayar mühendisliği duyurusu var mı?" gibi sorular doğrudan yapılandırılmış tablolardan cevaplanır. Genel bilgi gerektiren sorularda ise PgVector document store üzerinden hibrit arama yapılır ve Ollama modeli yalnızca getirilen kaynaklara dayanarak yanıt üretir.

## Proje Yapısı

```text
unichat_proje/
├── backend/
│   ├── app/
│   │   ├── ingestion/       # JSON, PDF ve scraper çıktısı yükleme hattı
│   │   ├── models/          # Pydantic ve belge modelleri
│   │   ├── repositories/    # Veritabanı erişim katmanı
│   │   ├── routers/         # FastAPI endpointleri
│   │   └── services/        # RAG, DB-first cevap servisleri ve doğrulama
│   ├── scrapers/            # GİBTÜ veri toplama ve güncelleme modülleri
│   ├── tests/               # Unit, integration, regression ve e2e testleri
│   ├── data/                # Test verileri ve yerel veri çıktıları
│   └── main.py              # FastAPI uygulama girişi
├── frontend/
│   ├── src/
│   │   ├── components/      # Chat arayüz bileşenleri
│   │   ├── hooks/           # useChat state yönetimi
│   │   └── services/        # Axios API katmanı
│   └── package.json
├── database/                # PostgreSQL/PgVector şemaları ve seed SQL dosyaları
├── doc/                     # Geliştirme raporları ve blueprint dokümanları
├── docker-compose.yml       # PostgreSQL + PgVector servisi
└── .env.example
```

## Gereksinimler

- Python 3.10+
- Node.js 18+
- Docker veya Docker Desktop
- Ollama
- Git

İlk embedding modeli indirmesi ve bazı scraper işlemleri internet bağlantısı gerektirebilir. LLM yanıt üretimi için varsayılan model `gemma3:4b-it-qat` olarak ayarlanmıştır.

## Kurulum

Projeyi klonladıktan sonra kök dizinde `.env.example` dosyasını `.env` olarak kopyalayın:

```powershell
Copy-Item .env.example .env
```

Örnek yerel `.env` içeriği:

```env
DATABASE_URL=postgresql://postgres:gizlisifre@localhost:5433/postgres
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b-it-qat
EMBEDDING_MODEL=intfloat/multilingual-e5-base
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]
LOG_LEVEL=INFO
```

PostgreSQL + PgVector servisini başlatın:

```powershell
docker compose up -d
```

Ollama modelini hazırlayın:

```powershell
ollama pull gemma3:4b-it-qat
```

Backend bağımlılıklarını kurun:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

Veritabanı şemasını oluşturun:

```powershell
cd backend
python database\init_db.py
```

Backend API'yi çalıştırın:

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Ayrı bir terminalde frontend bağımlılıklarını kurup arayüzü başlatın:

```powershell
cd frontend
npm install
npm run dev
```

Frontend varsayılan olarak `http://localhost:5173`, backend ise `http://127.0.0.1:8000` üzerinde çalışır.

## Hızlı Kontrol

Backend sağlık kontrolü:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Chat endpoint testi:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/chat `
  -ContentType "application/json" `
  -Body '{"message":"GİBTÜ hakkında kısa bilgi verir misin?"}'
```

## Veri Hazırlama

Test verilerini yüklemek için:

```powershell
cd backend
python database\seed_data.py
```

PDF belgelerini veritabanına yüklemeden önce kontrol etmek için:

```powershell
cd backend
python load_all_pdfs.py --dry-run
```

Gerçek PDF yüklemesi için:

```powershell
cd backend
python load_all_pdfs.py
```

PDF dosyaları `backend/data/pdfs/` altındaki kategori klasörlerinden okunur. Bu dizin `.gitignore` içinde yer aldığı için büyük ve yerel belge kaynakları GitHub'a eklenmez.

## Veritabanı Verileri ve Demo Snapshot

Bu proje GitHub üzerinde paylaşılırken en güvenli yaklaşım, repoda **kod + şema + küçük test verisi** bulundurmak; büyük veya gerçek veritabanı yedeklerini ayrı bir demo snapshot olarak paylaşmaktır.

Repo içinde tutulması uygun olanlar:

- `database/init.sql` ve diğer şema/seed SQL dosyaları
- `backend/database/init_db.py`
- `backend/data/_test_seed.json`
- `.env.example`
- `docker-compose.yml`

Repo içinde tutulmaması gerekenler:

- Gerçek kullanıcı mesajları veya `chat_logs` içeren DB dump dosyaları
- Üretim veya kişisel çalışma yedekleri
- `.env` dosyası
- Yerel PDF arşivleri
- Büyük scraper raporları, geçici checkpoint dosyaları ve model cache'leri

Projeyi kullanmak isteyen biri için üç yol vardır:

| Senaryo | Kullanım |
| --- | --- |
| Boş kurulum | `init_db.py` ile şema kurulur, ardından küçük test verisi yüklenir |
| Demo kurulum | Sanitized demo dump ayrıca indirilip `pg_restore` ile yüklenir |
| Güncel veri toplama | Kullanıcı kendi PDF'lerini ve scraper akışını çalıştırarak DB'yi yeniden üretir |

### Boş Şema + Test Verisi

GitHub'dan klonlayan biri en hızlı şekilde şu akışla sistemi ayağa kaldırabilir:

```powershell
docker compose up -d

cd backend
python database\init_db.py
python database\seed_data.py
python -m uvicorn main:app --reload --port 8000
```

Bu yöntem küçük test verisiyle API'nin, embedding hattının ve frontend bağlantısının doğrulanması için yeterlidir.

### Demo Dump Restore

Tam veriyle deneme yapılacaksa dump dosyası repoya commitlenmek yerine GitHub Releases, Google Drive, OneDrive veya benzeri ayrı bir bağlantı üzerinden paylaşılmalıdır. Dosya örneğin `database\unichat_demo.dump` adıyla proje köküne indirilebilir.

Restore komutu:

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

Restore sonrası kontrol:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### Demo Dump Hazırlama

Demo dump paylaşılacaksa önce kişisel veya hassas veri içermeyen ayrı bir kopya DB hazırlanmalıdır. Özellikle `chat_logs`, geçici staging kayıtları, yerel test çıktıları ve kişisel notlar kontrol edilmeden paylaşılmamalıdır.

Örnek sanitized dump üretimi:

```powershell
$env:PGPASSWORD="gizlisifre"

pg_dump `
  --host localhost `
  --port 5433 `
  --username postgres `
  --format custom `
  --no-owner `
  --no-acl `
  --exclude-table-data=chat_logs `
  --exclude-table-data=department_announcement_staging `
  --exclude-table-data=department_announcement_scrape_runs `
  --file database\unichat_demo.dump `
  postgres
```

> Not: `database/unichat_pre_e5_backup.dump` gibi yerel yedekler proje geliştirme sürecinde faydalı olabilir; ancak public GitHub reposunda resmi demo snapshot olarak paylaşılmadan önce mutlaka içerik ve kişisel veri kontrolünden geçirilmelidir.

## Scheduler ve Güncellemeler

Zamanlanmış görevleri listelemek için:

```powershell
cd backend
python -m scrapers.scheduler --list
```

Belirli bir güncelleme işini elle çalıştırmak için:

```powershell
cd backend
python -m scrapers.scheduler --run-now yemek
python -m scrapers.scheduler --run-now duyuru
python -m scrapers.scheduler --run-now bolum_duyuru
```

Scheduler'ı sürekli çalıştırmak için:

```powershell
cd backend
python -m scrapers.scheduler --start
```

## API Uçları

| Method | Endpoint | Açıklama |
| --- | --- | --- |
| `POST` | `/api/chat` | Kullanıcı mesajını işler ve kaynaklı bot yanıtı döndürür |
| `GET` | `/api/health` | PostgreSQL, Ollama ve embedding/document store durumunu kontrol eder |
| `GET` | `/api/yemek-menu` | Tek tarih veya tarih aralığı için yemekhane menüsü döndürür |
| `GET` | `/api/admin/department-announcements/status` | Bölüm duyurusu veri durumunu raporlar |
| `POST` | `/api/admin/department-announcements/scrape` | Mühendislik bölüm duyurularını staging'e alır |
| `GET` | `/api/admin/department-announcements/staging` | Staging duyuru kayıtlarını listeler |
| `POST` | `/api/admin/department-announcements/staging/{staging_id}/approve` | Tek staging duyurusunu onaylar |
| `POST` | `/api/admin/department-announcements/staging/{staging_id}/reject` | Tek staging duyurusunu reddeder |
| `POST` | `/api/admin/department-announcements/runs/{run_id}/approve` | Aynı scrape run içindeki kayıtları toplu onaylar |

## Test

Backend testlerinden örnek bir doğrulama:

```powershell
python -m unittest backend.tests.unit.test_department_announcement_feature backend.tests.unit.test_classroom_location_service
```

Tüm unittest testlerini keşfetmek için:

```powershell
python -m unittest discover -s backend\tests -p "test_*.py"
```

Frontend tarafında lint ve üretim build kontrolü:

```powershell
cd frontend
npm run lint
npm run build
```

Bazı backend testleri PostgreSQL, Ollama veya canlı veri kaynaklarına ihtiyaç duyabilir. Bu nedenle testleri çalıştırmadan önce `.env`, Docker ve Ollama durumunu kontrol etmek gerekir.

## GitHub Yayınlama Kontrol Listesi

Public repo veya teslim reposu oluşturmadan önce şu kontroller yapılmalıdır:

- `.env` dosyası commitlenmemiş olmalı, yalnızca `.env.example` paylaşılmalıdır.
- `.venv`, `node_modules`, `pgdata`, model cache'leri ve build çıktıları repoya eklenmemelidir.
- Yerel PDF arşivleri `backend/data/pdfs/` altında kalmalı ve repoya eklenmemelidir.
- DB dump, backup ve geçici rapor dosyaları public repoya konmamalıdır.
- Paylaşılacak DB verisi gerekiyorsa sanitized demo dump GitHub Release veya harici indirme linki olarak verilmelidir.
- `chat_logs` ve kişisel veri içerebilecek tablolar dump içine alınmamalıdır.
- Proje açık kaynak olarak yayınlanacaksa uygun bir `LICENSE` dosyası eklenmelidir.
- README'deki kurulum komutları temiz bir klonda tekrar denenmelidir.

DB yedeklerini yanlışlıkla commit etmemek için `.gitignore` içinde şu kuralların bulunması önerilir:

```gitignore
database/*.dump
database/*backup*
*.backup
```

Daha önce yanlışlıkla takip edilen bir yerel dump varsa, dosyayı diskten silmeden Git takibinden çıkarmak için:

```powershell
git rm --cached database\unichat_pre_e5_backup.dump
```

## Güvenlik ve Doğruluk Yaklaşımı

- UniChat yalnızca GİBTÜ ve üniversite bağlamındaki sorulara yanıt vermek üzere sınırlandırılmıştır.
- RAG yanıtları getirilen kaynak belgelerle sınırlandırılır.
- Yanıtlardaki URL, telefon, e-posta ve tarih bilgileri kaynaklarla doğrulanır.
- Kaynakta olmayan bilgi için tahmin üretmek yerine kullanıcı ilgili birime yönlendirilir.
- Chat log kayıtlarında kişisel veri riskini azaltmak için filtreleme yaklaşımı uygulanır.
- Varsayılan LLM entegrasyonu yerel Ollama üzerinden çalışır; dış API zorunluluğu yoktur.

## Geliştirme Notları

- `.env`, `.venv`, `node_modules/`, yerel PDF belgeleri ve bazı scraper çıktıları `.gitignore` ile dışarıda bırakılır.
- `doc/gibtu/` altındaki HTML dosyaları veri kaynağı değil, scraper'ların canlı siteyi hedefli taramasını sağlayan blueprint/harita dosyalarıdır.
- Backend tarafında yeni veri kaynakları eklenirken mümkünse mevcut `app/ingestion/` hattı ve repository/service yapısı kullanılmalıdır.
- Kesin cevap gerektiren alanlarda LLM yerine DB-first servis yaklaşımı tercih edilmelidir.

## Yol Haritası

Projede tamamlanan çekirdek yapı üzerine ileride şu geliştirmeler planlanabilir:

- Oturum bazlı konuşma geçmişi
- Rate limiting
- Basit admin paneli
- Çok dilli yanıt altyapısı
- Embedding cache ve performans iyileştirmeleri
- Ek birimler için yeni blueprint ve scraper kapsamı
