**WEB SCRAPER — Yapısal Keşif + Kontrollü Scrape Yaklaşımı**

Scraping’e doğrudan başlama. Önce üniversite web yapısını analiz et ve fakülte → bölüm → alt menü → detay sayfa mimarisini çıkar. Amaç, site bilgi mimarisini anlayarak gereksiz, tekrarlı veya alakasız crawl işlemlerini önlemek ve scraping’i kontrollü yürütmektir.

**Çalışma sırası:**

1.  Önce bir fakülteyi tamamen keşfet: ana sayfa, bölüm sayfaları, ortak menüler, alt menüler, arşiv yapıları ve belge bağlantıları haritalandırılsın.
    
2.  Sonra o fakülteyi scrape et.
    
3.  Ardından kalite kontrol ve raporlama yap.
    
4.  Ancak bundan sonra sonraki fakülteye geç.
    

**Her fakültede bölüm bazlı ilerle:**

*   Her bölüm sayfasında header, sidebar, footer ve içerik içi menüler ayrı ayrı incelensin.
    
*   Tekrarlayan navigasyon linkleri normalize edilip deduplicate edilsin.
    
*   Özellikle şu sayfa türleri hedeflensin: hakkımızda, iletişim, yönetim, akademik personel (liste ve detay), program, müfredat, ders planı, ders içerikleri, öğrenci menüleri, staj, mezuniyet, yönetmelikler, formlar, takvim, duyuru, haber, etkinlik.
    
*   PDF, DOC/DOCX, XLS/XLSX gibi belge linkleri de ayrıca tespit edilip kaynak türü olarak kaydedilsin.
    

**Arşiv ve sayfalama kuralları:**

*   Duyuru, haber ve etkinlik arşivlerinde sayfalama varsa yalnızca en güncel son 15 sayfa taransın.
    
*   Bu sayfalardaki tüm detay sayfaları scrape edilsin.
    
*   Eski arşivlere sınırsız şekilde inilmesin.
    

**İçerik çıkarma kuralı:**

*   Veritabanına kaydedilen `content`, tarayıcıdan alınan gerçek sayfa metni (`innerText`) olmalı.
    
*   Özet, placeholder, boilerplate veya uydurma açıklamalar kesinlikle kabul edilmez.
    
*   “Content contains…”, “Page contains headers…”, “yakında”, “under construction” gibi ifadeler içerik olarak kaydedilmemeli; bunlar kalite problemi olarak işaretlenmeli.
    
*   Ancak iletişim sayfası, kısa duyuru, tek satırlık resmi ilan gibi doğal olarak kısa sayfalar hata sayılmamalı; yalnızca boş veya placeholder ise sorun kabul edilmeli.
    

**Teknik kontrol kuralları:**

*   Crawl yalnızca izin verilen üniversite alan adları ve ilgili alt yollar içinde kalsın.
    
*   URL normalization, canonicalization ve duplicate kontrolü zorunlu olsun.
    
*   Timeout, retry, redirect ve hata türleri kaydedilsin.
    
*   Her sayfa için `source_url`, `title`, `faculty`, `department`, `doc_kind`, `breadcrumb`, `extracted_at` ve içerik uzunluğu metadata olarak tutulmalı.
    

**Kalite kontrol raporu zorunlu olsun:**

*   metadata doluluk oranı
    
*   chunk kapsama oranı
    
*   placeholder / boş içerik oranı
    
*   doc\_kind dağılımı
    
*   keşfedilen URL sayısı
    
*   scrape edilen URL sayısı
    
*   atlanan / duplicate URL sayısı
    
*   başarısız URL listesi
    
*   her başarısız URL için hata nedeni
    

**Amaç:**  
Körlemesine tüm siteyi taramak değil; önce üniversitenin yapısını anlayıp, sonra yüksek değerli ve gerçek içerik taşıyan sayfaları kontrollü, izlenebilir ve raporlanabilir biçimde toplamak.