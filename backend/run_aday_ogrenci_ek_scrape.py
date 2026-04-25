"""
Gorev 3.5 P4 — Aday Ogrenci Ek Sayfalari

Blueprint'lerden (doc/gibtu/Aday Ogrenci Portali/) tum metin verilerini
parse eder + canli portaldan (adayogrenci.gibtu.edu.tr) tamamlayici verileri ceker.

Guvenlik kurallari:
  - SABİT HEDEFLER: Sadece docs'taki blueprint URL'leri + adayogrenci subdomain
  - MAX DEPTH = 1: Sayfa icindeki linklere gidilmez
  - TIMEOUT: Her istek icin 15s timeout, 3 deneme
  - Hata yakalama: try-catch ile yanit vermeyen sayfalar atlanir

Kullanim:
    python run_aday_ogrenci_ek_scrape.py              # scrape + ingest
    python run_aday_ogrenci_ek_scrape.py --dry-run     # test (DB'ye yazmaz)
"""
import sys
import json
import hashlib
import time
import logging
import re
import argparse
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.ingestion.loader import ingest_documents, DuplicatePolicy
from haystack import Document

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://adayogrenci.gibtu.edu.tr"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"
BLUEPRINT_DIR = Path(__file__).resolve().parent.parent / "doc" / "gibtu" / "Aday Öğrenci Portalı"
RATE_LIMIT = 1.5
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0)"
TIMEOUT = 15  # seconds


def _doc_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fetch(url: str, session: requests.Session) -> str | None:
    """Canli fetch with retry + timeout + encoding fallback."""
    for attempt in range(1, 4):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if e.response is not None and 400 <= e.response.status_code < 500:
                logger.warning(f"  HTTP {status} (kalici hata): {url}")
                return None
            logger.warning(f"  HTTP {status} deneme {attempt}/3: {url}")
        except requests.exceptions.Timeout:
            logger.warning(f"  TIMEOUT deneme {attempt}/3: {url}")
        except Exception as e:
            logger.warning(f"  Hata deneme {attempt}/3: {e}")
        if attempt < 3:
            time.sleep(2 * attempt)
    return None


def _clean_html_text(html_str: str) -> str:
    """HTML string'inden temiz metin cikar."""
    soup = BeautifulSoup(html_str, "html.parser")
    # Boilerplate temizle
    for sel in ["nav", "footer", "header", "script", "style", "noscript",
                ".side-nav", ".breadcrumb"]:
        for el in soup.select(sel):
            el.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 2]
    return "\n".join(lines)


# ── Blueprint Parse Fonksiyonlari ──

def parse_sss(html_path: Path) -> list[Document]:
    """SSS.html blueprint'inden soru-cevap cikar."""
    logger.info("  SSS parse ediliyor: %s", html_path.name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    documents = []
    items = soup.select("ul.collapsible.popout > li")
    for item in items:
        header = item.select_one("div.collapsible-header")
        body = item.select_one("div.collapsible-body")
        if not header or not body:
            continue
        question = header.get_text(strip=True).replace("+", "").strip()
        answer = body.get_text(separator="\n", strip=True)
        if len(answer) < 20:
            continue
        content = f"Soru: {question}\n\nCevap: {answer}"
        doc = Document(
            id=_doc_id(content),
            content=content,
            meta={
                "category": "aday_ogrenci",
                "source_url": "https://adayogrenci.gibtu.edu.tr/#sss",
                "source_type": "web",
                "source_id": f"aday_sss_{_doc_id(question)[:8]}",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": f"Aday Öğrenci SSS: {question[:80]}",
                "doc_kind": "sss",
                "department": "Aday Öğrenci Portalı",
                "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
            },
        )
        documents.append(doc)

    logger.info("    %d SSS belgesi olusturuldu", len(documents))
    return documents


def parse_olanaklar(html_path: Path) -> list[Document]:
    """Olanaklar.html blueprint'inden kampus olanaklari cikar."""
    logger.info("  Olanaklar parse ediliyor: %s", html_path.name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    documents = []

    # Slider kartlari
    slides = soup.select("div.slayt")
    for slide in slides:
        title_el = slide.select_one("div.slayt_baslik span")
        text_el = slide.select_one("div.slayt_metin span")
        if not title_el or not text_el:
            continue
        title = title_el.get_text(strip=True)
        text = text_el.get_text(separator="\n", strip=True)
        if len(text) < 20:
            continue
        content = f"{title}\n\n{text}"
        doc = Document(
            id=_doc_id(content),
            content=content,
            meta={
                "category": "aday_ogrenci",
                "source_url": "https://adayogrenci.gibtu.edu.tr/#olanak",
                "source_type": "web",
                "source_id": f"aday_olanak_{_doc_id(title)[:8]}",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "title": f"Kampüs Olanakları: {title}",
                "doc_kind": "tanitim",
                "department": "Aday Öğrenci Portalı",
                "contact_unit": "Sağlık Kültür ve Spor Daire Başkanlığı",
            },
        )
        documents.append(doc)

    # Kutuphane ve Erasmus paralax bolumu
    for section_id in ["kutuphane", "erasmus"]:
        section = soup.find(id=section_id)
        if section:
            text = section.get_text(separator="\n", strip=True)
            if len(text) > 50:
                title_map = {
                    "kutuphane": "Kütüphane Olanakları",
                    "erasmus": "Erasmus+ ve Uluslararası Değişim Programları",
                }
                doc = Document(
                    id=_doc_id(text),
                    content=text,
                    meta={
                        "category": "aday_ogrenci",
                        "source_url": f"https://adayogrenci.gibtu.edu.tr/#{section_id}",
                        "source_type": "web",
                        "source_id": f"aday_{section_id}_{_doc_id(text)[:8]}",
                        "last_updated": datetime.now().strftime("%Y-%m-%d"),
                        "title": title_map.get(section_id, section_id.title()),
                        "doc_kind": "tanitim",
                        "department": "Aday Öğrenci Portalı",
                        "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
                    },
                )
                documents.append(doc)

    logger.info("    %d olanak belgesi olusturuldu", len(documents))
    return documents


def parse_ogrenim(html_path: Path) -> Document:
    """Ogrenim.html'den program listesini cikar."""
    logger.info("  Öğrenim parse ediliyor: %s", html_path.name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    programs = []
    # Lisansustu
    section = soup.select_one("section.yukseklisans_listesi")
    if section:
        for card in section.select("div.faculty-card"):
            title_el = card.select_one("div.faculty-card-title h3 span")
            if title_el:
                programs.append(f"Lisansüstü: {title_el.get_text(strip=True)}")

    # Lisans
    section = soup.select_one("section.lisans_listesi")
    if section:
        for card in section.select("div.faculty-card"):
            title_el = card.select_one("div.faculty-card-title h3 span")
            if title_el:
                fac_name = title_el.get_text(strip=True)
                sub_programs = []
                for li in card.select("div.faculty-card-list ul li a span"):
                    sub_programs.append(li.get_text(strip=True))
                if sub_programs:
                    programs.append(f"Lisans: {fac_name} → {', '.join(sub_programs)}")
                else:
                    programs.append(f"Lisans: {fac_name}")

    # Onlisans
    section = soup.select_one("section.onlisans_listesi")
    if section:
        for card in section.select("div.faculty-card"):
            title_el = card.select_one("div.faculty-card-title h3 span")
            if title_el:
                myo_name = title_el.get_text(strip=True)
                sub_programs = []
                for li in card.select("div.faculty-card-list ul li a span"):
                    sub_programs.append(li.get_text(strip=True))
                if sub_programs:
                    programs.append(f"Önlisans: {myo_name} → {', '.join(sub_programs)}")
                else:
                    programs.append(f"Önlisans: {myo_name}")

    content = "GİBTÜ Akademik Programlar Listesi (Aday Öğrenci Portalı)\n\n" + "\n".join(programs)
    logger.info("    %d program tespit edildi", len(programs))

    return Document(
        id=_doc_id(content),
        content=content,
        meta={
            "category": "aday_ogrenci",
            "source_url": "https://adayogrenci.gibtu.edu.tr/#ogrenim",
            "source_type": "web",
            "source_id": "aday_ogrenim_program_listesi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GİBTÜ Akademik Programlar (Lisansüstü, Lisans, Önlisans)",
            "doc_kind": "program_listesi",
            "department": "Aday Öğrenci Portalı",
            "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
        },
    )


def parse_simple_blueprint(html_path: Path, section_title: str, section_anchor: str,
                           doc_kind: str, contact_unit: str = "Öğrenci İşleri Daire Başkanlığı") -> Document | None:
    """Basit HTML blueprint'inden tek Document cikar."""
    logger.info("  %s parse ediliyor: %s", section_title, html_path.name)
    html = html_path.read_text(encoding="utf-8")
    text = _clean_html_text(html)

    if len(text) < 30:
        logger.warning("    Cok kisa icerik (%d kar), atlaniyor", len(text))
        return None

    return Document(
        id=_doc_id(text),
        content=text,
        meta={
            "category": "aday_ogrenci",
            "source_url": f"https://adayogrenci.gibtu.edu.tr/#{section_anchor}",
            "source_type": "web",
            "source_id": f"aday_{section_anchor}_{_doc_id(text)[:8]}",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": section_title,
            "doc_kind": doc_kind,
            "department": "Aday Öğrenci Portalı",
            "contact_unit": contact_unit,
        },
    )


def parse_iletisim(html_path: Path) -> Document | None:
    """Iletisim_Bilgileri.html'den iletisim bilgilerini cikar."""
    logger.info("  İletişim parse ediliyor: %s", html_path.name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    contacts = []

    for block in soup.select("div.adres-bilgisi"):
        title_el = block.select_one("h5")
        title = title_el.get_text(strip=True) if title_el else ""

        items = []
        for div in block.select("div.col"):
            text = div.get_text(strip=True)
            if text and len(text) > 3:
                items.append(text)

        if title or items:
            contacts.append(f"{title}\n" + "\n".join(items))

    # Sosyal medya
    socials = []
    for a_tag in soup.select("div.sosyal_aglar a"):
        href = a_tag.get("href", "")
        if href:
            socials.append(href)

    content = "Aday Öğrenci Portalı İletişim Bilgileri\n\n"
    content += "\n\n".join(contacts)
    if socials:
        content += "\n\nSosyal Medya:\n" + "\n".join(socials)

    if len(content) < 50:
        return None

    return Document(
        id=_doc_id(content),
        content=content,
        meta={
            "category": "aday_ogrenci",
            "source_url": "https://adayogrenci.gibtu.edu.tr/#iletisim-bilgileri",
            "source_type": "web",
            "source_id": "aday_iletisim_bilgileri",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GİBTÜ Aday Öğrenci İletişim Bilgileri",
            "doc_kind": "iletisim",
            "department": "Aday Öğrenci Portalı",
            "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
        },
    )


def parse_cbiko(html_path: Path) -> Document | None:
    """cbiko.html'den kariyer merkezi bilgilerini cikar."""
    logger.info("  CBİKO parse ediliyor: %s", html_path.name)
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    sections = []
    for card in soup.select("div.card"):
        title_el = card.select_one("div.card-title span")
        content_el = card.select_one("div.card-content span")
        if title_el and content_el:
            title = title_el.get_text(strip=True)
            text = content_el.get_text(separator="\n", strip=True)
            if len(text) > 20:
                sections.append(f"{title}\n{text}")

    if not sections:
        return None

    content = "CBİKO — Cumhurbaşkanlığı İnsan Kaynakları Ofisi Kariyer Merkezi\n\n"
    content += "\n\n".join(sections)

    return Document(
        id=_doc_id(content),
        content=content,
        meta={
            "category": "aday_ogrenci",
            "source_url": "https://adayogrenci.gibtu.edu.tr/#cbiko",
            "source_type": "web",
            "source_id": "aday_cbiko_kariyer_merkezi",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "CBİKO Kariyer Merkezi — Kariyer Hizmetleri ve Eğitim Fırsatları",
            "doc_kind": "rehber",
            "department": "Aday Öğrenci Portalı",
            "contact_unit": "Kariyer Geliştirme Uygulama ve Araştırma Merkezi (KAGİAM)",
        },
    )


# ── Canli Scrape ──

def scrape_portal_live(session: requests.Session) -> Document | None:
    """adayogrenci.gibtu.edu.tr canli portalindan tam icerik cek."""
    logger.info("\n  Canli portal scrape: %s", BASE_URL)
    html = _fetch(BASE_URL, session)
    if not html:
        logger.warning("  Portal fetch basarisiz!")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Boilerplate temizle
    for sel in ["nav", "script", "style", "noscript", "iframe",
                ".side-nav", "#mobile-navbar"]:
        for el in soup.select(sel):
            el.decompose()

    body = soup.find("body")
    if not body:
        return None

    text = body.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 3]
    content = "\n".join(lines)

    if len(content) < 100:
        logger.warning("  Portal icerigi cok kisa (%d kar)", len(content))
        return None

    return Document(
        id=_doc_id(content),
        content=content[:50000],  # max 50K karakter
        meta={
            "category": "aday_ogrenci",
            "source_url": BASE_URL,
            "source_type": "web",
            "source_id": "aday_portal_canli_tam",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "title": "GİBTÜ Aday Öğrenci Portalı (Tam İçerik)",
            "doc_kind": "tanitim",
            "department": "Aday Öğrenci Portalı",
            "contact_unit": "Öğrenci İşleri Daire Başkanlığı",
        },
    )


# ── Ana Islem ──

def run_all(dry_run: bool = False):
    """Tum blueprint'leri parse et + canli scrape + ingest."""
    logger.info("=" * 65)
    logger.info("GOREV 3.5 P4 — Aday Ogrenci Ek Sayfalari")
    logger.info("=" * 65)

    all_documents = []

    # 1. SSS
    sss_path = BLUEPRINT_DIR / "SSS.html"
    if sss_path.exists():
        all_documents.extend(parse_sss(sss_path))

    # 2. Olanaklar
    olanaklar_path = BLUEPRINT_DIR / "Olanaklar.html"
    if olanaklar_path.exists():
        all_documents.extend(parse_olanaklar(olanaklar_path))

    # 3. Ogrenim (program listesi)
    ogrenim_path = BLUEPRINT_DIR / "Öğrenim.html"
    if ogrenim_path.exists():
        doc = parse_ogrenim(ogrenim_path)
        if doc:
            all_documents.append(doc)

    # 4. Gaziantep
    gaziantep_path = BLUEPRINT_DIR / "Gaziantep.html"
    if gaziantep_path.exists():
        doc = parse_simple_blueprint(gaziantep_path, "Gaziantep Şehir Tanıtımı", "gaziantep", "tanitim")
        if doc:
            all_documents.append(doc)

    # 5. CBİKO (Kariyer Merkezi)
    cbiko_path = BLUEPRINT_DIR / "cbiko.html"
    if cbiko_path.exists():
        doc = parse_cbiko(cbiko_path)
        if doc:
            all_documents.append(doc)

    # 6. Konaklama
    konaklama_path = BLUEPRINT_DIR / "Konaklama.html"
    if konaklama_path.exists():
        doc = parse_simple_blueprint(konaklama_path, "Öğrenci Konaklama Seçenekleri (KYK Yurdu)", "konaklama",
                                     "rehber", "Sağlık Kültür ve Spor Daire Başkanlığı")
        if doc:
            all_documents.append(doc)

    # 7. Ogrenci Basarisi
    basari_path = BLUEPRINT_DIR / "Öğrenci_başarısı.html"
    if basari_path.exists():
        doc = parse_simple_blueprint(basari_path, "Öğrencinin Akademik Başarısı Nasıl Belirlenir?",
                                     "ogrencibasarisi", "rehber")
        if doc:
            all_documents.append(doc)

    # 8. Iletisim
    iletisim_path = BLUEPRINT_DIR / "İletişim_Bilgileri.html"
    if iletisim_path.exists():
        doc = parse_iletisim(iletisim_path)
        if doc:
            all_documents.append(doc)

    # 9. Canli portal scrape
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        live_doc = scrape_portal_live(session)
        if live_doc:
            all_documents.append(live_doc)
    except Exception as e:
        logger.error("  Canli portal scrape hatasi: %s", e)

    # ── Sonuc Raporu ──
    logger.info("\n" + "=" * 65)
    logger.info("SONUC RAPORU")
    logger.info("=" * 65)
    logger.info("  Toplam Document: %d", len(all_documents))

    doc_kinds = {}
    for d in all_documents:
        k = d.meta.get("doc_kind", "?")
        doc_kinds[k] = doc_kinds.get(k, 0) + 1
    logger.info("  doc_kind dagilimi: %s", doc_kinds)

    # ── Ingest ──
    chunks = 0
    if all_documents:
        if dry_run:
            logger.info("  DRY-RUN: %d document, DB'ye yazilmadi.", len(all_documents))
            chunks = len(all_documents)
        else:
            chunks = ingest_documents(all_documents, policy=DuplicatePolicy.OVERWRITE, dry_run=False)
            logger.info("  DB'ye yazilan chunk: %d", chunks)

    # ── Dogrulama ──
    checks = []
    def check(label, cond, detail=""):
        checks.append(cond)
        status = "PASS" if cond else "FAIL"
        msg = f"  [{status}] {label}"
        if not cond and detail:
            msg += f" -- {detail}"
        logger.info(msg)

    check("docs >= 5", len(all_documents) >= 5, f"got {len(all_documents)}")
    check("SSS belgesi var", doc_kinds.get("sss", 0) > 0)
    check("tanitim belgesi var", doc_kinds.get("tanitim", 0) > 0)
    check("program_listesi var", doc_kinds.get("program_listesi", 0) > 0)

    # Metadata doluluk
    required = ["category", "source_url", "source_type", "title", "doc_kind", "department"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents)
    check("metadata doluluk 100%", all_ok)

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    success = failed == 0

    logger.info(f"\n  DOGRULAMA: {passed} PASS / {failed} FAIL")

    # ── Ozet JSON ──
    summary = {
        "task": "3.5_P4_aday_ogrenci_ek",
        "description": "Aday Ogrenci Ek Sayfalari — Blueprint + Canli Scrape",
        "documents_created": len(all_documents),
        "chunks_written": chunks,
        "doc_kinds": doc_kinds,
        "success": success,
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = OUTPUT_DIR / "aday_ogrenci_ek_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"\nOzet rapor: {summary_path}")

    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description="Aday Ogrenci Ek Sayfalari Scrape")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan test calistirmasi")
    args = parser.parse_args()

    return run_all(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
