"""
Gorev 3.3-C — Dijital Hizmetler (OBS/LMS/E-Posta)
UBYS portal bilgileri + dijital hizmet rehber belgeleri olustur ve DB'ye yukle.
"""
import sys, hashlib, json, logging, io
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ingestion.loader import ingest_documents
from haystack import Document
from haystack.document_stores.types import DuplicatePolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CATEGORY = "dijital_hizmetler"
DEPARTMENT = "GIBTU Genel"
CONTACT_UNIT = "Bilgi Islem Daire Baskanligi"
CONTACT_INFO = "bilgiislem@gibtu.edu.tr"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Dijital hizmet rehber belgeleri - her biri ayri bir Document olacak
DIGITAL_SERVICES = [
    {
        "title": "OBS - Ogrenci Bilgi Sistemi Giris Rehberi",
        "doc_kind": "rehber",
        "source_url": "https://ubys.gibtu.edu.tr",
        "content": """GİBTÜ Öğrenci Bilgi Sistemi (OBS/UBYS) Giriş Rehberi

GİBTÜ Öğrenci Bilgi Sistemi (UBYS), öğrencilerin akademik işlemlerini çevrimiçi olarak gerçekleştirebildiği merkezi dijital platformdur.

Erişim Adresi: https://ubys.gibtu.edu.tr

Giriş Bilgileri:
- Kullanıcı Adı: Öğrenci numaranız
- Şifre: İlk girişte TC kimlik numaranız (sonrasında değiştirmeniz önerilir)

OBS Üzerinden Yapılabilen İşlemler:
- Ders kaydı ve ders seçimi
- Transkript görüntüleme ve indirme
- Sınav sonuçlarını görüntüleme
- Ders programı ve akademik takvim takibi
- Öğrenci belgesi alma
- Staj başvuruları
- Danışman bilgilerini görüntüleme
- Harç ve ödeme bilgileri

Öğrenci Bilgi Sistemi Modülleri:
- Eğitim Kataloğu: https://ubys.gibtu.edu.tr/AIS/OutcomeBasedLearning/Home/Index
- ÖSYM Ön Kayıt: Başvuru İşlemleri menüsünden erişilebilir
- Enstitü Başvurusu: Lisansüstü başvurular için
- Uluslararası Öğrenci Başvurusu: Yabancı öğrenci kayıt işlemleri
- Yatay Geçiş Başvurusu: Üniversite içi/dışı yatay geçiş

Sorun Durumunda İletişim:
- Bilgi İşlem Daire Başkanlığı: bilgiislem@gibtu.edu.tr
- Öğrenci İşleri Daire Başkanlığı: ogrenciisleri@gibtu.edu.tr
- Telefon: +90 (342) 909 75 00"""
    },
    {
        "title": "E-Posta Sistemi - Ogrenci ve Personel",
        "doc_kind": "rehber",
        "source_url": "https://mail.gibtu.edu.tr",
        "content": """GİBTÜ E-Posta Sistemi Rehberi

GİBTÜ, tüm öğrenci ve personeline kurumsal e-posta adresi sağlamaktadır.

Öğrenci E-Posta Formatı:
- ad.soyad@ogr.gibtu.edu.tr (veya ogrenci numarasi@ogr.gibtu.edu.tr)
- Giriş: https://mail.gibtu.edu.tr veya Microsoft Outlook üzerinden

Personel E-Posta Formatı:
- ad.soyad@gibtu.edu.tr
- Akademik personel: ad.soyad@gibtu.edu.tr

E-Posta Erişimi:
- Web: https://mail.gibtu.edu.tr (Microsoft 365 / Outlook Web)
- Mobil: Microsoft Outlook uygulaması (iOS/Android)
- Masaüstü: Microsoft Outlook, Thunderbird vb. e-posta istemcileri

İlk Giriş:
- Kullanıcı adı: Tam e-posta adresiniz
- Şifre: İlk kayıt sırasında belirlenen şifre

Sorun Durumunda:
- Şifre sıfırlama: Bilgi İşlem Daire Başkanlığı'na başvurunuz
- İletişim: bilgiislem@gibtu.edu.tr
- Telefon: +90 (342) 909 75 00"""
    },
    {
        "title": "Egitim Katalogu - Bologna Bilgi Sistemi",
        "doc_kind": "rehber",
        "source_url": "https://ubys.gibtu.edu.tr/AIS/OutcomeBasedLearning/Home/Index",
        "content": """GİBTÜ Eğitim Kataloğu (Bologna Bilgi Sistemi)

Eğitim Kataloğu, GİBTÜ'deki tüm akademik programların Bologna sürecine uygun bilgilerini sunan dijital platformdur.

Erişim: https://ubys.gibtu.edu.tr/AIS/OutcomeBasedLearning/Home/Index

Eğitim Kataloğu İçerikleri:
- Program Tanımı: Her akademik programın amaç, hedef ve kazanımları
- Program Çıktıları: TYYÇ (Türkiye Yükseköğretim Yeterlilikler Çerçevesi) uyumlu çıktılar
- Öğretim Planı: Dönemlik ders listeleri, AKTS kredileri, zorunlu/seçmeli ayrımı
- Ders İçerikleri: Her dersin detaylı içerik bilgisi

Üniversitedeki Eğitim Düzeyleri:
- Önlisans
- Lisans
- Yüksek Lisans
- Doktora

Fakülte ve Birimler (Eğitim Kataloğu'nda listelenen):
- Güzel Sanatlar, Tasarım ve Mimarlık Fakültesi
- Lisansüstü Eğitim Enstitüsü
- Mühendislik ve Doğa Bilimleri Fakültesi
- Sağlık Bilimleri Fakültesi
- Sağlık Hizmetleri Meslek Yüksekokulu
- Teknik Bilimler Meslek Yüksekokulu
- Tıp Fakültesi
- Yabancı Diller Yüksekokulu
- İktisadi, İdari ve Sosyal Bilimler Fakültesi
- İlahiyat Fakültesi
- İslami İlimler Fakültesi"""
    },
    {
        "title": "EBYS - Elektronik Belge Yonetim Sistemi",
        "doc_kind": "rehber",
        "source_url": "https://ubys.gibtu.edu.tr/ERMS/Record/ConfirmationPage/Index",
        "content": """GİBTÜ Elektronik Belge Yönetim Sistemi (EBYS)

EBYS, üniversite bünyesindeki tüm resmi yazışma ve belge süreçlerinin dijital ortamda yürütüldüğü platformdur.

Erişim: https://ubys.gibtu.edu.tr üzerinden EBYS modülü

EBYS Hizmetleri:
- Belge Doğrulama: Resmi belgelerin doğruluk kontrolü
  Erişim: https://ubys.gibtu.edu.tr/ERMS/Record/ConfirmationPage/Index
- Kurumsal Süreçler: Resmi yazışma ve onay akışları
- Dijital İmza: Elektronik imza ile belge onaylama

Belge Doğrulama:
GİBTÜ tarafından düzenlenen belgelerin doğruluğunu kontrol etmek için EBYS Belge Doğrulama sayfasını kullanabilirsiniz. Belge üzerindeki doğrulama kodunu girerek belgenin geçerliliğini sorgulayabilirsiniz.

İletişim:
- Bilgi İşlem Daire Başkanlığı: bilgiislem@gibtu.edu.tr"""
    },
    {
        "title": "Basvuru Islemleri Portali",
        "doc_kind": "rehber",
        "source_url": "https://ubys.gibtu.edu.tr/AIS/ApplicationForms/Home/Index",
        "content": """GİBTÜ Başvuru İşlemleri Portalı

GİBTÜ Başvuru İşlemleri Portalı, üniversiteye yapılacak tüm başvuruların çevrimiçi olarak yönetildiği merkezi platformdur.

Erişim: https://ubys.gibtu.edu.tr üzerinden Başvuru İşlemleri menüsü

Mevcut Başvuru Türleri:
1. ÖSYM Ön Kayıt: ÖSYM yerleştirme sonrası kayıt işlemleri
2. Enstitü Başvurusu: Lisansüstü (Yüksek Lisans/Doktora) program başvuruları
3. Uluslararası Öğrenci Başvurusu: Yabancı uyruklu öğrenci kabul başvuruları
4. Yatay Geçiş Başvurusu: Üniversite içi/dışı yatay geçiş işlemleri
5. Yaz Okulu Misafir Öğrenci Başvurusu: Diğer üniversitelerden yaz okulu başvuruları
6. Tezsiz Lisansüstünden Tezliye Yatay Geçiş: Program değişikliği başvuruları
7. Akademik Kadro İlan Başvuru: Akademik personel alım başvuruları
8. YÖS Yabancı Dil Sınavı Başvurusu: Yabancı öğrenci sınav başvuruları
9. Enstitü İçin Uluslararası Öğrenci Başvurusu
10. Tezsiz Yüksek Lisans Başvurusu
11. TÖMER Başvurusu: Türkçe öğretimi merkezi başvuruları
12. Ek Madde 2 Başvurusu
13. Lisans Üstü Af Başvurusu
14. Doktora Yeterlilik Başvurusu
15. Lisans Derecesi İle Doktora Başvurusu

İletişim:
- Öğrenci İşleri Daire Başkanlığı: ogrenciisleri@gibtu.edu.tr
- Lisansüstü Eğitim Enstitüsü: enstitu@gibtu.edu.tr"""
    },
    {
        "title": "Diger Dijital Hizmetler ve Platformlar",
        "doc_kind": "rehber",
        "source_url": "https://www.gibtu.edu.tr",
        "content": """GİBTÜ Diğer Dijital Hizmetler ve Platformlar

Sertifika/Kurs Eğitim Programları:
- GİBTÜ SEM (Sürekli Eğitim Merkezi) üzerinden sertifika ve kurs programlarına başvuru
- Erişim: https://ubys.gibtu.edu.tr/CEM/Application/Participant/Programs

Kurumsal Değerlendirme:
- Kurumsal performans analizi ve istatistikler
- Erişim: https://ubys.gibtu.edu.tr/BIP/BusinessIntelligence/Home/Index

Mezun Yönetim Sistemi:
- Mezun takip ve iletişim platformu
- Mezun Portal: https://ubys.gibtu.edu.tr/GTS/Portal/Home/Index
- Mezun bilgi güncelleme ve kariyer hizmetleri

Etik Kurul:
- Araştırma etiği başvuruları
- Erişim: https://ubys.gibtu.edu.tr/ECM/EthicsCommitteesManagement/MainLogin/MainLogin

Teknoloji Transfer Ofisi (TTO):
- Firma işlemleri ve proje yönetimi
- Erişim: https://ubys.gibtu.edu.tr/TTO/ProjectManagement/KurumIslemleri/FirmaIslem

MERLAB:
- Merkezi Araştırma Laboratuvarı numune işlemleri
- Erişim: https://ubys.gibtu.edu.tr/MLS/Application/Sample/Index

Personel Bilgi Sistemi:
- Akademik kadro ilan ve jüri değerlendirme işlemleri
- Erişim: UBYS üzerinden PBS modülü

E-Devlet Entegrasyonu:
- GİBTÜ hizmetlerine e-Devlet üzerinden de erişilebilir
- Öğrenci belgesi, transkript gibi belgeler e-Devlet'ten alınabilir

Genel İletişim:
- Bilgi İşlem Daire Başkanlığı: bilgiislem@gibtu.edu.tr
- Telefon: +90 (342) 909 75 00
- Web: https://www.gibtu.edu.tr"""
    },
]


def main():
    print("=" * 65)
    print("3.3-C: Dijital Hizmetler Rehber Belgeleri")
    print("=" * 65)

    all_docs = []
    for svc in DIGITAL_SERVICES:
        content = svc["content"].strip()
        doc_id = hashlib.sha256(content.encode("utf-8")).hexdigest()
        meta = {
            "category": CATEGORY,
            "source_url": svc["source_url"],
            "source_type": "manual",
            "source_id": f"gibtu_dijital_{doc_id[:8]}",
            "last_updated": NOW,
            "title": svc["title"],
            "doc_kind": svc["doc_kind"],
            "language": "tr",
            "department": DEPARTMENT,
            "contact_unit": CONTACT_UNIT,
            "contact_info": CONTACT_INFO,
        }
        all_docs.append(Document(id=doc_id, content=content, meta=meta))
        print(f"  + {svc['title']} ({len(content)} kar.)")

    print(f"\nToplam: {len(all_docs)} belge")
    written = ingest_documents(all_docs, policy=DuplicatePolicy.OVERWRITE)
    print(f"DB'ye {written} chunk yazildi")

    summary = {
        "task": "3.3-C", "description": "Dijital Hizmetler Rehber",
        "total_documents": len(all_docs), "total_written": written,
        "services": [s["title"] for s in DIGITAL_SERVICES],
    }
    out = Path(__file__).parent / "scrapers" / "dijital_hizmetler_summary.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Ozet: {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
