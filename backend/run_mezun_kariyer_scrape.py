"""
Gorev 3.5 P4 — Mezun / Kariyer Merkezi Sayfalari (KAGIAM, BirimID=41)

Kesif raporundan bilinen BirimID=41 uzerinden standart ASPX alt sayfalari
canli scrape eder.

Guvenlik kurallari:
  - SABİT HEDEFLER: Sadece kesif raporundaki ASPX URL'leri (BirimID=41)
  - MAX DEPTH = 1: Sayfa icindeki linklere gidilmez
  - TIMEOUT: Her istek icin 15s timeout, 3 deneme
  - Hata yakalama: try-catch ile yanit vermeyen sayfalar atlanir

Kullanim:
    python run_mezun_kariyer_scrape.py              # scrape + ingest
    python run_mezun_kariyer_scrape.py --dry-run     # test (DB'ye yazmaz)
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

BASE_URL = "https://www.gibtu.edu.tr"
OUTPUT_DIR = Path(__file__).resolve().parent / "scrapers"
RATE_LIMIT = 1.5
USER_AGENT = "Mozilla/5.0 (compatible; UniChatBot/1.0)"
TIMEOUT = 15
BIRIM_ID = 41
BIRIM_SLUG = "kagiam"
BIRIM_ADI = "Kariyer Geliştirme Uygulama ve Araştırma Merkezi (KAGİAM)"

# Sabit hedef URL'ler — kesif raporundan (BirimID=41)
# MAX DEPTH = 1: her URL'nin sadece kendi icerigi cekilir
TARGET_URLS = [
    {"url": f"{BASE_URL}/Birim.aspx?id={BIRIM_ID}", "doc_kind": "tanitim", "title_hint": "KAGİAM Ana Sayfa"},
    {"url": f"{BASE_URL}/BirimYonetim.aspx?id={BIRIM_ID}", "doc_kind": "yonetim", "title_hint": "KAGİAM Yönetim"},
    {"url": f"{BASE_URL}/BirimMisyon.aspx?id={BIRIM_ID}", "doc_kind": "tanitim", "title_hint": "KAGİAM Misyon"},
    {"url": f"{BASE_URL}/BirimVizyon.aspx?id={BIRIM_ID}", "doc_kind": "tanitim", "title_hint": "KAGİAM Vizyon"},
    {"url": f"{BASE_URL}/BirimTarihce.aspx?id={BIRIM_ID}", "doc_kind": "tanitim", "title_hint": "KAGİAM Tarihçe"},
    {"url": f"{BASE_URL}/BirimHakkimizda.aspx?id={BIRIM_ID}", "doc_kind": "tanitim", "title_hint": "KAGİAM Hakkımızda"},
    {"url": f"{BASE_URL}/BirimIletisim.aspx?id={BIRIM_ID}", "doc_kind": "iletisim", "title_hint": "KAGİAM İletişim"},
    {"url": f"{BASE_URL}/BirimForm.aspx?id={BIRIM_ID}", "doc_kind": "form", "title_hint": "KAGİAM Formlar"},
    {"url": f"{BASE_URL}/BirimAkademikPersonel.aspx?id={BIRIM_ID}", "doc_kind": "personel", "title_hint": "KAGİAM Akademik Personel"},
    {"url": f"{BASE_URL}/BirimIdariPersonel.aspx?id={BIRIM_ID}", "doc_kind": "personel", "title_hint": "KAGİAM İdari Personel"},
    {"url": f"{BASE_URL}/BirimDuyuruArsivi.aspx?id={BIRIM_ID}&k=duyuru&p=1", "doc_kind": "duyuru", "title_hint": "KAGİAM Duyurular"},
    {"url": f"{BASE_URL}/{BIRIM_SLUG}", "doc_kind": "tanitim", "title_hint": "KAGİAM Portal"},
]


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


def _extract_title(html_text: str, fallback: str = "") -> str:
    """Sayfadan baslik cikar (5 kademeli fallback)."""
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. span.sayfa_baslik
    el = soup.select_one("span.sayfa_baslik")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)

    # 2. div.card-panel > span
    el = soup.select_one("div.card-panel span")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)

    # 3. h1
    el = soup.find("h1")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)

    # 4. h2
    el = soup.find("h2")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)

    # 5. title tag
    el = soup.find("title")
    if el:
        t = el.get_text(strip=True)
        t = re.sub(r"\s*[-–]\s*G[İi]BT[ÜU].*$", "", t)
        if t:
            return t

    return fallback


def _clean_text(html_text: str) -> str:
    """Boilerplate-free temiz metin cikar."""
    soup = BeautifulSoup(html_text, "html.parser")

    # Boilerplate kaldir
    for sel in ["nav", "footer", "header", "script", "style", "noscript",
                ".side-nav", ".birim-menu", "#birim-menu-slide",
                ".breadcrumb", ".footer", ".ust-menu", "iframe"]:
        for el in soup.select(sel):
            el.decompose()

    # Ana icerik bolgesi
    body = (soup.find("div", class_="birim_safya_body_detay") or
            soup.find("div", class_="page_body") or
            soup.find("section", class_="birim_safya_body") or
            soup.find("div", class_="container") or
            soup.find("body"))

    if not body:
        return ""

    text = body.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 2]
    return "\n".join(lines)


def run_all(dry_run: bool = False):
    """Tum hedef URL'leri canli scrape et + ingest."""
    logger.info("=" * 65)
    logger.info("GOREV 3.5 P4 — Mezun / Kariyer Merkezi (KAGIAM, BirimID=%d)", BIRIM_ID)
    logger.info("Hedef URL sayisi: %d", len(TARGET_URLS))
    logger.info("=" * 65)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    all_documents = []
    ok_count = 0
    skip_count = 0
    err_count = 0

    for i, target in enumerate(TARGET_URLS):
        url = target["url"]
        doc_kind = target["doc_kind"]
        title_hint = target["title_hint"]

        logger.info(f"\n  [{i+1}/{len(TARGET_URLS)}] {url}")

        try:
            html = _fetch(url, session)
            if not html:
                err_count += 1
                continue

            content = _clean_text(html)
            if len(content) < 30:
                logger.warning(f"    Cok kisa icerik ({len(content)} kar), atlaniyor")
                skip_count += 1
                continue

            # Baslik cikar
            page_title = _extract_title(html, fallback=title_hint)

            # Source ID
            safe_slug = re.sub(r'[^a-z0-9]', '_', page_title.lower()[:40])
            source_id = f"kagiam_{safe_slug}"

            doc = Document(
                id=_doc_id(f"{url}_{content[:200]}"),
                content=content[:30000],
                meta={
                    "category": "kariyer",
                    "source_url": url,
                    "source_type": "web",
                    "source_id": source_id,
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "title": page_title,
                    "doc_kind": doc_kind,
                    "department": BIRIM_ADI,
                    "contact_unit": "KAGİAM",
                },
            )
            all_documents.append(doc)
            ok_count += 1
            logger.info(f"    OK: {page_title} ({len(content)} kar, doc_kind={doc_kind})")

            time.sleep(RATE_LIMIT)

        except Exception as e:
            logger.error(f"    Hata: {e}")
            err_count += 1

    # ── Sonuc Raporu ──
    logger.info("\n" + "=" * 65)
    logger.info("SONUC RAPORU")
    logger.info("=" * 65)
    logger.info("  Basarili: %d | Atlanan: %d | Hata: %d", ok_count, skip_count, err_count)
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

    check("docs >= 3", len(all_documents) >= 3, f"got {len(all_documents)}")
    check("err_count <= 5", err_count <= 5, f"got {err_count}")

    # Metadata doluluk
    required = ["category", "source_url", "source_type", "title", "doc_kind", "department"]
    all_ok = all(all(d.meta.get(f) for f in required) for d in all_documents) if all_documents else False
    check("metadata doluluk 100%", all_ok)

    # category=kariyer
    cats = set(d.meta.get("category") for d in all_documents)
    check("category=kariyer", "kariyer" in cats)

    passed = sum(1 for c in checks if c)
    failed = sum(1 for c in checks if not c)
    success = failed == 0

    logger.info(f"\n  DOGRULAMA: {passed} PASS / {failed} FAIL")

    # ── Ozet JSON ──
    summary = {
        "task": "3.5_P4_mezun_kariyer",
        "description": f"Mezun/Kariyer Merkezi (KAGIAM) Canli Scrape — BirimID={BIRIM_ID}",
        "target_urls": len(TARGET_URLS),
        "documents_created": len(all_documents),
        "ok": ok_count,
        "skip": skip_count,
        "errors": err_count,
        "chunks_written": chunks,
        "doc_kinds": doc_kinds,
        "success": success,
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = OUTPUT_DIR / "mezun_kariyer_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"\nOzet rapor: {summary_path}")

    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description="Mezun/Kariyer Merkezi (KAGIAM) Scrape")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazmadan test calistirmasi")
    args = parser.parse_args()

    return run_all(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
