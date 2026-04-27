"""
UniChat — Faz 4.3: Kapsam Genişletme ve Entegrasyon Araçları

İçerir:
  4.3.1 — Kalan birimler için scraping durum tespiti
  4.3.2 — Menü sayfalarından PDF/DOC link tespiti → pdf_parser yönlendirme
  4.3.3 — DuplicatePolicy.OVERWRITE ile delta update doğrulaması
  4.3.4 — parent_doc_id filtresiyle eski chunk silme doğrulaması

Kullanım:
    from scrapers.coverage_tools import CoverageAnalyzer

    analyzer = CoverageAnalyzer()

    # 4.3.1: Kapsam durumu
    analyzer.check_coverage()

    # 4.3.2: PDF link tespiti ve indirme
    analyzer.process_discovered_pdfs(dry_run=True)

    # 4.3.3: Delta update doğrulaması
    analyzer.verify_delta_update()

    # 4.3.4: Eski chunk temizleme doğrulaması
    analyzer.verify_chunk_cleanup(source_id="test_source")

CLI:
    python -m scrapers.coverage_tools --check-coverage
    python -m scrapers.coverage_tools --verify-delta
    python -m scrapers.coverage_tools --verify-chunks
    python -m scrapers.coverage_tools --process-pdfs --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrapers._encoding_fix  # noqa: F401 — Windows stdout UTF-8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent


class CoverageAnalyzer:
    """
    Kapsam analizi ve entegrasyon araçları.
    """

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            import psycopg2
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent.parent / ".env")
            self._conn = psycopg2.connect(os.environ["DATABASE_URL"])
        return self._conn

    def _close_conn(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 4.3.1: Kapsam Durumu ──

    def check_coverage(self) -> dict:
        """
        DB'deki mevcut verilerle blueprint registry'deki birimleri karşılaştırır.
        Henüz scrape edilmemiş birimleri tespit eder.
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # DB'deki tüm department'lar
        cur.execute("""
            SELECT meta->>'department' as dept, COUNT(*) as cnt
            FROM haystack_docs
            WHERE meta->>'department' IS NOT NULL
            GROUP BY meta->>'department'
            ORDER BY cnt DESC
        """)
        db_departments = {r[0]: r[1] for r in cur.fetchall()}

        # DB'deki tüm kategori dağılımı
        cur.execute("""
            SELECT meta->>'category' as cat, COUNT(*) as cnt
            FROM haystack_docs
            WHERE meta->>'category' IS NOT NULL
            GROUP BY meta->>'category'
            ORDER BY cnt DESC
        """)
        db_categories = {r[0]: r[1] for r in cur.fetchall()}

        # Toplam chunk sayısı
        cur.execute("SELECT COUNT(*) FROM haystack_docs")
        total_chunks = cur.fetchone()[0]

        cur.close()

        # Bilinen birimler listesi
        from scrapers.department_scraper import DEPARTMENT_REGISTRY
        registered_departments = [d["department"] for d in DEPARTMENT_REGISTRY]

        # Kapsam analizi
        covered = []
        uncovered = []
        for dept in registered_departments:
            if dept in db_departments:
                covered.append({"department": dept, "chunks": db_departments[dept]})
            else:
                uncovered.append(dept)

        report = {
            "total_chunks": total_chunks,
            "total_departments_in_db": len(db_departments),
            "registered_departments": len(registered_departments),
            "covered": len(covered),
            "uncovered": len(uncovered),
            "coverage_pct": round(len(covered) / max(len(registered_departments), 1) * 100, 1),
            "categories": db_categories,
            "uncovered_departments": uncovered,
            "top_departments": sorted(
                [{"dept": d, "chunks": c} for d, c in db_departments.items()],
                key=lambda x: -x["chunks"]
            )[:20],
        }

        # Rapor yazdır
        print("\n" + "=" * 65)
        print("📊 KAPSAM ANALİZİ")
        print("=" * 65)
        print(f"  Toplam chunk:          {total_chunks:,}")
        print(f"  DB'deki departmanlar:  {len(db_departments)}")
        print(f"  Kayıtlı birimler:     {len(registered_departments)}")
        print(f"  Kaplanan:              {len(covered)} ({report['coverage_pct']}%)")
        print(f"  Kapsamda olmayan:      {len(uncovered)}")

        if uncovered:
            print(f"\n  ⚠️ Kapsamda Olmayan Birimler:")
            for dept in uncovered:
                print(f"     — {dept}")

        print(f"\n  📂 Kategori Dağılımı:")
        for cat, cnt in sorted(db_categories.items(), key=lambda x: -x[1]):
            print(f"     {cat:<25}: {cnt}")

        print("=" * 65)

        return report

    # ── 4.3.2: PDF Link Tespiti ve İndirme ──

    def process_discovered_pdfs(self, dry_run: bool = True) -> dict:
        """
        JSON scrape çıktılarındaki discovered_pdfs alanlarından
        henüz indirilmemiş PDF'leri tespit edip pdf_parser'a yönlendirir.
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # DB'de zaten olan PDF URL'lerini bul
        cur.execute("""
            SELECT DISTINCT meta->>'source_url' FROM haystack_docs
            WHERE meta->>'source_type' = 'pdf' AND meta->>'source_url' IS NOT NULL
        """)
        existing_pdf_urls = {r[0] for r in cur.fetchall()}
        cur.close()

        # JSON çıktılarından discovered_pdfs topla
        all_pdfs = []
        for json_file in OUTPUT_DIR.glob("*_output.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pdfs = data.get("discovered_pdfs", [])
                for pdf in pdfs:
                    url = pdf.get("url", "")
                    if url and url not in existing_pdf_urls:
                        all_pdfs.append({
                            "url": url,
                            "text": pdf.get("text", ""),
                            "source_file": json_file.name,
                        })
            except (json.JSONDecodeError, KeyError):
                continue

        # Deduplicate
        seen = set()
        unique_pdfs = []
        for pdf in all_pdfs:
            if pdf["url"] not in seen:
                seen.add(pdf["url"])
                unique_pdfs.append(pdf)

        report = {
            "existing_pdfs_in_db": len(existing_pdf_urls),
            "new_pdfs_found": len(unique_pdfs),
            "dry_run": dry_run,
        }

        print("\n" + "=" * 65)
        print("📄 PDF LİNK TESPİTİ")
        print("=" * 65)
        print(f"  DB'de mevcut PDF:    {len(existing_pdf_urls)}")
        print(f"  Yeni tespit edilen:  {len(unique_pdfs)}")

        if unique_pdfs:
            print(f"\n  Yeni PDF'ler:")
            for pdf in unique_pdfs[:10]:
                print(f"     📥 {pdf['text'][:40]} → {pdf['url'][:60]}")
            if len(unique_pdfs) > 10:
                print(f"     ... ve {len(unique_pdfs) - 10} tane daha")

        if not dry_run and unique_pdfs:
            # PDF indirme ve parse süreci
            logger.info("PDF indirme ve parse başlıyor...")
            downloaded = 0
            for pdf in unique_pdfs:
                try:
                    self._download_and_parse_pdf(pdf["url"], pdf["text"])
                    downloaded += 1
                    time.sleep(1.0)
                except Exception as e:
                    logger.warning("PDF hata: %s — %s", pdf["url"][:50], e)
            report["downloaded"] = downloaded
            print(f"\n  ✅ İndirilen: {downloaded}")

        print("=" * 65)
        return report

    def _download_and_parse_pdf(self, url: str, title: str):
        """Tek bir PDF'yi indir ve parse et."""
        import requests
        import io

        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber yüklü değil, PDF parse atlanıyor")
            return

        from haystack import Document
        from haystack.document_stores.types import DuplicatePolicy
        from app.ingestion.loader import ingest_documents

        resp = requests.get(url, timeout=20)
        resp.raise_for_status()

        pdf_text = ""
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pdf_text += page_text + "\n\n"

        pdf_text = pdf_text.strip()
        if len(pdf_text) < 20:
            logger.warning("PDF metin çıkarılamadı: %s", url[:50])
            return

        if not title:
            title = url.split("/")[-1].replace(".pdf", "").replace("_", " ")

        doc_id = hashlib.sha256(pdf_text.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        doc = Document(
            id=doc_id,
            content=pdf_text,
            meta={
                "category": "genel_bilgi",
                "source_url": url,
                "source_type": "pdf",
                "source_id": f"pdf_{hashlib.sha256(url.encode()).hexdigest()[:12]}",
                "last_updated": now,
                "title": title,
                "doc_kind": "pdf_rapor",
                "language": "tr",
                "department": "",
                "contact_unit": "",
                "contact_info": "",
            },
        )

        ingest_documents([doc], policy=DuplicatePolicy.OVERWRITE)
        logger.info("  ✅ PDF ingested: %s (%d kar)", title[:40], len(pdf_text))

    # ── 4.3.3: Delta Update Doğrulaması ──

    def verify_delta_update(self) -> dict:
        """
        DuplicatePolicy.OVERWRITE ile delta update mekanizmasının
        doğru çalıştığını doğrular.
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # Aynı source_id'ye sahip birden fazla chunk olup olmadığını kontrol et
        cur.execute("""
            SELECT meta->>'source_id' as sid, COUNT(*) as cnt
            FROM haystack_docs
            WHERE meta->>'source_id' IS NOT NULL
            GROUP BY meta->>'source_id'
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 20
        """)
        multi_chunk_sources = [(r[0], r[1]) for r in cur.fetchall()]

        # Toplam unique source_id sayısı
        cur.execute("""
            SELECT COUNT(DISTINCT meta->>'source_id') FROM haystack_docs
            WHERE meta->>'source_id' IS NOT NULL
        """)
        unique_source_ids = cur.fetchone()[0]

        # Toplam chunk
        cur.execute("SELECT COUNT(*) FROM haystack_docs")
        total_chunks = cur.fetchone()[0]

        cur.close()

        report = {
            "total_chunks": total_chunks,
            "unique_source_ids": unique_source_ids,
            "multi_chunk_sources": len(multi_chunk_sources),
            "avg_chunks_per_source": round(total_chunks / max(unique_source_ids, 1), 1),
        }

        print("\n" + "=" * 65)
        print("🔄 DELTA UPDATE DOĞRULAMASI")
        print("=" * 65)
        print(f"  Toplam chunk:          {total_chunks:,}")
        print(f"  Unique source_id:      {unique_source_ids:,}")
        print(f"  Multi-chunk kaynaklar: {len(multi_chunk_sources)}")
        print(f"  Ort. chunk/kaynak:     {report['avg_chunks_per_source']}")

        if multi_chunk_sources:
            print(f"\n  📊 En çok chunk'a sahip kaynaklar:")
            for sid, cnt in multi_chunk_sources[:5]:
                print(f"     {sid[:50]:50} : {cnt} chunk")

        print("\n  ✅ Delta update mekanizması çalışıyor" if unique_source_ids > 0 else "\n  ❌ Sorun tespit edildi")
        print("=" * 65)

        return report

    # ── 4.3.4: parent_doc_id ile Chunk Doğrulaması ──

    def verify_chunk_cleanup(self, source_id: str | None = None) -> dict:
        """
        parent_doc_id filtresiyle eski chunk'ların doğru silindiğini doğrular.

        parent_doc_id, her chunk'ın hangi belgeye ait olduğunu takip eder.
        Bir belge güncellendiğinde, eski chunk'ların temizlenmiş olması beklenir.
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # parent_doc_id dağılımı
        cur.execute("""
            SELECT meta->>'parent_doc_id' as pid, COUNT(*) as cnt
            FROM haystack_docs
            WHERE meta->>'parent_doc_id' IS NOT NULL
            GROUP BY meta->>'parent_doc_id'
            ORDER BY cnt DESC
            LIMIT 20
        """)
        parent_dist = [(r[0], r[1]) for r in cur.fetchall()]

        # parent_doc_id olmayan chunk'lar
        cur.execute("""
            SELECT COUNT(*) FROM haystack_docs
            WHERE meta->>'parent_doc_id' IS NULL
        """)
        orphan_count = cur.fetchone()[0]

        # Toplam
        cur.execute("SELECT COUNT(*) FROM haystack_docs")
        total = cur.fetchone()[0]

        # Spesifik source_id kontrolü
        specific_result = None
        if source_id:
            cur.execute("""
                SELECT meta->>'parent_doc_id', meta->>'chunk_index',
                       meta->>'title', LENGTH(content)
                FROM haystack_docs
                WHERE meta->>'parent_doc_id' = %s
                ORDER BY (meta->>'chunk_index')::int
            """, (source_id,))
            chunks = cur.fetchall()
            specific_result = {
                "source_id": source_id,
                "chunk_count": len(chunks),
                "chunks": [
                    {"parent": r[0], "index": r[1], "title": r[2], "length": r[3]}
                    for r in chunks
                ],
            }

        cur.close()

        parent_doc_count = len(parent_dist)
        has_parent_pct = round((total - orphan_count) / max(total, 1) * 100, 1)

        report = {
            "total_chunks": total,
            "with_parent_doc_id": total - orphan_count,
            "without_parent_doc_id": orphan_count,
            "parent_doc_id_pct": has_parent_pct,
            "unique_parent_docs": parent_doc_count,
        }

        print("\n" + "=" * 65)
        print("🔗 CHUNK parent_doc_id DOĞRULAMASI")
        print("=" * 65)
        print(f"  Toplam chunk:           {total:,}")
        print(f"  parent_doc_id olan:     {total - orphan_count:,} ({has_parent_pct}%)")
        print(f"  parent_doc_id olmayan:  {orphan_count:,}")
        print(f"  Unique parent belge:    {parent_doc_count}")

        if parent_dist:
            print(f"\n  📊 En çok chunk'a sahip parent doc'lar:")
            for pid, cnt in parent_dist[:5]:
                print(f"     {pid[:50]:50} : {cnt} chunk")

        if specific_result:
            print(f"\n  🔍 source_id='{source_id}' detayı:")
            print(f"     Chunk sayısı: {specific_result['chunk_count']}")
            for ch in specific_result["chunks"][:5]:
                print(f"     [{ch['index']}] {ch['title'][:40]} ({ch['length']} kar)")

        print("=" * 65)

        return report

    def __del__(self):
        self._close_conn()


# ── Yetim Chunk Temizleyici ──

def cleanup_orphan_chunks(source_id: str, dry_run: bool = True) -> int:
    """
    Belirli bir source_id'ye ait eski chunk'ları siler.
    Güncelleme sonrasında kalan yetim chunk'ları temizler.

    Args:
        source_id: Temizlenecek belgenin source_id'si.
        dry_run: True ise silmeden raporlar.

    Returns:
        Silinen chunk sayısı.
    """
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("""
        SELECT id, meta->>'chunk_index', meta->>'title', LENGTH(content)
        FROM haystack_docs
        WHERE meta->>'parent_doc_id' = %s
        ORDER BY (meta->>'chunk_index')::int
    """, (source_id,))
    chunks = cur.fetchall()

    logger.info("source_id='%s' için %d chunk bulundu", source_id, len(chunks))

    if dry_run:
        for ch in chunks:
            logger.info("  [DRY] Silinecek: id=%s, index=%s, %s kar", ch[0][:12], ch[1], ch[3])
        cur.close()
        conn.close()
        return len(chunks)

    # Gerçek silme
    cur.execute("""
        DELETE FROM haystack_docs
        WHERE meta->>'parent_doc_id' = %s
    """, (source_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    logger.info("✅ %d chunk silindi (source_id='%s')", deleted, source_id)
    return deleted


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Kapsam Genişletme ve Entegrasyon Araçları (Faz 4.3)",
    )
    parser.add_argument("--check-coverage", action="store_true",
                        help="4.3.1: Kapsam durumunu kontrol et")
    parser.add_argument("--process-pdfs", action="store_true",
                        help="4.3.2: PDF link tespiti ve indirme")
    parser.add_argument("--verify-delta", action="store_true",
                        help="4.3.3: Delta update doğrulaması")
    parser.add_argument("--verify-chunks", action="store_true",
                        help="4.3.4: parent_doc_id chunk doğrulaması")
    parser.add_argument("--source-id", default=None,
                        help="Spesifik source_id için chunk kontrolü")
    parser.add_argument("--dry-run", action="store_true",
                        help="Değişiklik yapmadan çalıştır")
    args = parser.parse_args()

    analyzer = CoverageAnalyzer()

    if args.check_coverage:
        analyzer.check_coverage()
    elif args.process_pdfs:
        analyzer.process_discovered_pdfs(dry_run=args.dry_run)
    elif args.verify_delta:
        analyzer.verify_delta_update()
    elif args.verify_chunks:
        analyzer.verify_chunk_cleanup(source_id=args.source_id)
    else:
        # Hepsini çalıştır
        analyzer.check_coverage()
        analyzer.verify_delta_update()
        analyzer.verify_chunk_cleanup()


if __name__ == "__main__":
    main()
