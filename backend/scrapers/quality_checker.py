"""
UniChat — Faz 4.1.1: Scrape Sonrası Otomatik Kalite Raporu

Scrape sonuçlarını (Document listesi veya DB'deki mevcut veriler) analiz ederek
kalite raporu üretir.

Kontroller:
  - Metadata doluluk (category, title, doc_kind, source_url, department, ...)
  - Placeholder içerik tespiti
  - Karakter dağılımı (çok kısa / çok uzun tespiti)
  - doc_kind dağılımı
  - Duplicate tespit (aynı source_url)
  - Boş / eksik başlık tespiti
  - Genel sağlık skoru

Kullanım:
    from scrapers.quality_checker import QualityChecker

    # Document listesi üzerinde
    checker = QualityChecker()
    report = checker.check_documents(documents)
    checker.print_report(report)
    checker.save_report(report, "quality_report.json")

    # DB üzerinde
    report = checker.check_from_db(filters={"category": "bolumler"})

CLI:
    python -m scrapers.quality_checker                         # Tüm DB
    python -m scrapers.quality_checker --category bolumler     # Filtreyle
    python -m scrapers.quality_checker --output report.json    # JSON çıktı
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
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

# Placeholder anahtar kelimeleri
PLACEHOLDER_KEYWORDS = [
    "lorem ipsum", "örnek metin", "içerik eklenecek",
    "yapım aşamasında", "coming soon", "under construction",
    "bu sayfa henüz", "test sayfası", "yakında eklenecek",
    "içerik hazırlanıyor",
]

# Zorunlu metadata alanları
REQUIRED_FIELDS = [
    "category", "source_url", "source_type", "source_id",
    "title", "doc_kind", "department",
]

# Önerilen metadata alanları
RECOMMENDED_FIELDS = [
    "last_updated", "contact_unit", "contact_info", "language",
]


@dataclass
class QualityIssue:
    """Tespit edilen tek bir kalite sorunu."""
    severity: str  # "error", "warning", "info"
    category: str  # "metadata", "content", "duplicate", "placeholder"
    message: str
    doc_index: int | None = None
    source_url: str = ""


@dataclass
class QualityReport:
    """Kalite raporu sonuçları."""
    timestamp: str = ""
    source: str = ""  # "documents" veya "database"
    total_documents: int = 0
    total_chunks: int = 0

    # Metadata doluluk
    metadata_completeness: dict = field(default_factory=dict)

    # İçerik istatistikleri
    char_distribution: dict = field(default_factory=dict)
    total_chars: int = 0
    avg_chars: float = 0.0
    min_chars: int = 0
    max_chars: int = 0

    # doc_kind dağılımı
    doc_kind_distribution: dict = field(default_factory=dict)

    # Kategori dağılımı
    category_distribution: dict = field(default_factory=dict)

    # Department dağılımı
    department_distribution: dict = field(default_factory=dict)

    # Sorunlar
    issues: list[dict] = field(default_factory=list)
    placeholder_count: int = 0
    empty_title_count: int = 0
    duplicate_url_count: int = 0
    too_short_count: int = 0
    too_long_count: int = 0

    # Genel skor
    health_score: float = 0.0  # 0-100
    health_grade: str = ""  # A, B, C, D, F

    def to_dict(self) -> dict:
        return {
            "meta": {
                "timestamp": self.timestamp,
                "source": self.source,
            },
            "summary": {
                "total_documents": self.total_documents,
                "total_chunks": self.total_chunks,
                "total_chars": self.total_chars,
                "avg_chars": round(self.avg_chars, 1),
                "min_chars": self.min_chars,
                "max_chars": self.max_chars,
                "health_score": round(self.health_score, 1),
                "health_grade": self.health_grade,
            },
            "metadata_completeness": self.metadata_completeness,
            "char_distribution": self.char_distribution,
            "doc_kind_distribution": self.doc_kind_distribution,
            "category_distribution": self.category_distribution,
            "department_distribution": self.department_distribution,
            "issues_summary": {
                "placeholder_count": self.placeholder_count,
                "empty_title_count": self.empty_title_count,
                "duplicate_url_count": self.duplicate_url_count,
                "too_short_count": self.too_short_count,
                "too_long_count": self.too_long_count,
                "total_issues": len(self.issues),
            },
            "issues": self.issues[:50],  # İlk 50 sorun
        }


class QualityChecker:
    """
    Scrape sonrası otomatik kalite raporu üretici.

    Document listesi veya DB'deki veriler üzerinde çalışır.
    """

    # İçerik uzunluk eşikleri
    TOO_SHORT_THRESHOLD = 50
    TOO_LONG_THRESHOLD = 100_000
    SHORT_WARN_THRESHOLD = 100

    def check_documents(self, documents, source: str = "documents") -> QualityReport:
        """
        Haystack Document listesini analiz eder.

        Args:
            documents: Haystack Document listesi.
            source: Kaynak açıklaması.

        Returns:
            QualityReport nesnesi.
        """
        report = QualityReport(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source=source,
            total_documents=len(documents),
        )

        if not documents:
            report.health_score = 0
            report.health_grade = "F"
            return report

        issues: list[QualityIssue] = []
        seen_urls: dict[str, int] = {}
        char_lengths: list[int] = []

        for idx, doc in enumerate(documents):
            content = doc.content or ""
            meta = doc.meta or {}
            source_url = meta.get("source_url", "")

            # ── Metadata doluluk ──
            for field_name in REQUIRED_FIELDS:
                val = meta.get(field_name)
                if not val or (isinstance(val, str) and not val.strip()):
                    issues.append(QualityIssue(
                        severity="error",
                        category="metadata",
                        message=f"Zorunlu alan eksik: {field_name}",
                        doc_index=idx,
                        source_url=source_url,
                    ))

            for field_name in RECOMMENDED_FIELDS:
                val = meta.get(field_name)
                if not val or (isinstance(val, str) and not val.strip()):
                    issues.append(QualityIssue(
                        severity="info",
                        category="metadata",
                        message=f"Önerilen alan eksik: {field_name}",
                        doc_index=idx,
                        source_url=source_url,
                    ))

            # ── Başlık kontrolü ──
            title = meta.get("title", "")
            if not title or len(title.strip()) < 3:
                report.empty_title_count += 1
                issues.append(QualityIssue(
                    severity="warning",
                    category="content",
                    message=f"Başlık boş veya çok kısa: '{title}'",
                    doc_index=idx,
                    source_url=source_url,
                ))

            # ── İçerik uzunluk ──
            cl = len(content)
            char_lengths.append(cl)

            if cl < self.TOO_SHORT_THRESHOLD:
                report.too_short_count += 1
                issues.append(QualityIssue(
                    severity="warning",
                    category="content",
                    message=f"İçerik çok kısa: {cl} karakter",
                    doc_index=idx,
                    source_url=source_url,
                ))
            elif cl > self.TOO_LONG_THRESHOLD:
                report.too_long_count += 1
                issues.append(QualityIssue(
                    severity="warning",
                    category="content",
                    message=f"İçerik çok uzun: {cl} karakter",
                    doc_index=idx,
                    source_url=source_url,
                ))

            # ── Placeholder tespiti ──
            content_lower = content.lower()
            for kw in PLACEHOLDER_KEYWORDS:
                if kw in content_lower:
                    report.placeholder_count += 1
                    issues.append(QualityIssue(
                        severity="error",
                        category="placeholder",
                        message=f"Placeholder tespit edildi: '{kw}'",
                        doc_index=idx,
                        source_url=source_url,
                    ))
                    break

            # ── Duplicate URL tespiti ──
            if source_url:
                if source_url in seen_urls:
                    report.duplicate_url_count += 1
                    issues.append(QualityIssue(
                        severity="warning",
                        category="duplicate",
                        message=f"Duplicate URL: ilk: #{seen_urls[source_url]}",
                        doc_index=idx,
                        source_url=source_url,
                    ))
                else:
                    seen_urls[source_url] = idx

            # ── Dağılım sayaçları ──
            doc_kind = meta.get("doc_kind", "?")
            report.doc_kind_distribution[doc_kind] = report.doc_kind_distribution.get(doc_kind, 0) + 1

            category = meta.get("category", "?")
            report.category_distribution[category] = report.category_distribution.get(category, 0) + 1

            department = meta.get("department", "?")
            report.department_distribution[department] = report.department_distribution.get(department, 0) + 1

        # ── Metadata doluluk oranları ──
        all_fields = REQUIRED_FIELDS + RECOMMENDED_FIELDS
        for field_name in all_fields:
            filled = sum(
                1 for d in documents
                if d.meta and d.meta.get(field_name) and str(d.meta.get(field_name, "")).strip()
            )
            total = len(documents)
            report.metadata_completeness[field_name] = {
                "filled": filled,
                "total": total,
                "pct": round(filled / total * 100, 1) if total else 0,
            }

        # ── Karakter dağılımı ──
        if char_lengths:
            report.total_chars = sum(char_lengths)
            report.avg_chars = report.total_chars / len(char_lengths)
            report.min_chars = min(char_lengths)
            report.max_chars = max(char_lengths)

            ranges = {"<50": 0, "50-200": 0, "200-1K": 0, "1K-5K": 0, "5K-50K": 0, ">50K": 0}
            for cl in char_lengths:
                if cl < 50:
                    ranges["<50"] += 1
                elif cl < 200:
                    ranges["50-200"] += 1
                elif cl < 1000:
                    ranges["200-1K"] += 1
                elif cl < 5000:
                    ranges["1K-5K"] += 1
                elif cl < 50000:
                    ranges["5K-50K"] += 1
                else:
                    ranges[">50K"] += 1
            report.char_distribution = ranges

        # ── Issues → dict ──
        report.issues = [
            {
                "severity": iss.severity,
                "category": iss.category,
                "message": iss.message,
                "doc_index": iss.doc_index,
                "source_url": iss.source_url[:80] if iss.source_url else "",
            }
            for iss in issues
        ]

        # ── Sağlık skoru ──
        report.health_score = self._calculate_health_score(report)
        report.health_grade = self._score_to_grade(report.health_score)

        return report

    def check_from_db(
        self,
        filters: dict | None = None,
        limit: int = 10000,
    ) -> QualityReport:
        """
        DB'deki mevcut chunk'ları analiz eder.

        Args:
            filters: Filtre (category, doc_kind, department vb.).
            limit: Maksimum belge sayısı.

        Returns:
            QualityReport nesnesi.
        """
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent.parent / ".env")

        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()

        # SQL oluştur
        where_clauses = []
        params = []

        if filters:
            for key, val in filters.items():
                where_clauses.append(f"meta->>'{key}' = %s")
                params.append(val)

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
        sql = f"""
            SELECT content, meta
            FROM haystack_docs
            WHERE {where_sql}
            ORDER BY id
            LIMIT %s
        """
        params.append(limit)

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Haystack Document oluştur (mock)
        from haystack import Document
        documents = []
        for content, meta in rows:
            if isinstance(meta, str):
                import json as json_mod
                meta = json_mod.loads(meta)
            documents.append(Document(content=content or "", meta=meta or {}))

        report = self.check_documents(documents, source="database")
        report.total_chunks = len(documents)

        filter_desc = ", ".join(f"{k}={v}" for k, v in (filters or {}).items())
        logger.info("DB'den %d chunk okundu (filtre: %s)", len(documents), filter_desc or "yok")

        return report

    def _calculate_health_score(self, report: QualityReport) -> float:
        """Sağlık skorunu hesaplar (0-100)."""
        if report.total_documents == 0:
            return 0.0

        total = report.total_documents
        score = 100.0

        # Zorunlu metadata doluluk cezası (ağırlık: 30%)
        required_pcts = [
            report.metadata_completeness.get(f, {}).get("pct", 0)
            for f in REQUIRED_FIELDS
        ]
        if required_pcts:
            avg_required_pct = sum(required_pcts) / len(required_pcts)
            score -= (100 - avg_required_pct) * 0.30

        # Placeholder cezası (ağırlık: 20%)
        placeholder_pct = (report.placeholder_count / total) * 100
        score -= min(placeholder_pct * 2, 20)

        # Çok kısa içerik cezası (ağırlık: 15%)
        short_pct = (report.too_short_count / total) * 100
        score -= min(short_pct * 1.5, 15)

        # Boş başlık cezası (ağırlık: 10%)
        empty_title_pct = (report.empty_title_count / total) * 100
        score -= min(empty_title_pct * 1, 10)

        # Duplicate cezası (ağırlık: 10%)
        dup_pct = (report.duplicate_url_count / total) * 100
        score -= min(dup_pct * 1, 10)

        return max(0.0, min(100.0, score))

    @staticmethod
    def _score_to_grade(score: float) -> str:
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def print_report(self, report: QualityReport):
        """Raporu terminal'e yazdırır."""
        print()
        print("=" * 65)
        print(f"📊 KALİTE RAPORU — {report.source}")
        print(f"   Zaman: {report.timestamp}")
        print("=" * 65)

        # Genel sağlık
        grade_icon = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(report.health_grade, "⚪")
        print(f"\n  {grade_icon} Sağlık: {report.health_grade} ({report.health_score:.1f}/100)")
        print(f"  📄 Toplam belge:     {report.total_documents}")
        print(f"  📏 Toplam karakter:  {report.total_chars:,}")
        print(f"  📐 Ortalama uzunluk: {report.avg_chars:,.0f} kar/belge")
        print(f"  📐 Min / Max:        {report.min_chars} / {report.max_chars}")

        # Sorun özeti
        print(f"\n  ⚠️  Sorunlar:")
        print(f"     Placeholder:     {report.placeholder_count}")
        print(f"     Boş başlık:      {report.empty_title_count}")
        print(f"     Duplicate URL:   {report.duplicate_url_count}")
        print(f"     Çok kısa (<50):  {report.too_short_count}")
        print(f"     Çok uzun (>100K): {report.too_long_count}")

        # Metadata doluluk
        print(f"\n  📝 Metadata Doluluk:")
        for field_name, info in report.metadata_completeness.items():
            pct = info["pct"]
            icon = "✅" if pct == 100 else "⚠️" if pct >= 80 else "❌"
            print(f"     {icon} {field_name:<18}: {info['filled']}/{info['total']} ({pct}%)")

        # Karakter dağılımı
        if report.char_distribution:
            print(f"\n  📊 Karakter Dağılımı:")
            for rng, cnt in report.char_distribution.items():
                bar = "█" * min(cnt, 30)
                print(f"     {rng:>8}: {cnt:>4} {bar}")

        # doc_kind dağılımı
        if report.doc_kind_distribution:
            print(f"\n  🏷️  doc_kind Dağılımı:")
            for kind, count in sorted(report.doc_kind_distribution.items(), key=lambda x: -x[1]):
                print(f"     {kind:<20}: {count}")

        # Kategori dağılımı
        if report.category_distribution:
            print(f"\n  📂 Kategori Dağılımı:")
            for cat, count in sorted(report.category_distribution.items(), key=lambda x: -x[1]):
                print(f"     {cat:<20}: {count}")

        print("\n" + "=" * 65)

    def save_report(self, report: QualityReport, path: str):
        """Raporu JSON dosyasına kaydeder."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("Kalite raporu kaydedildi: %s", path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniChat Scrape Kalite Raporu (Faz 4.1.1)",
    )
    parser.add_argument("--category", default=None, help="Kategori filtresi")
    parser.add_argument("--doc-kind", default=None, help="doc_kind filtresi")
    parser.add_argument("--department", default=None, help="Department filtresi")
    parser.add_argument("--output", "-o", default=None, help="JSON çıktı dosyası")
    parser.add_argument("--limit", type=int, default=10000, help="Maksimum belge sayısı")
    args = parser.parse_args()

    filters = {}
    if args.category:
        filters["category"] = args.category
    if args.doc_kind:
        filters["doc_kind"] = args.doc_kind
    if args.department:
        filters["department"] = args.department

    checker = QualityChecker()
    report = checker.check_from_db(filters=filters or None, limit=args.limit)
    checker.print_report(report)

    if args.output:
        checker.save_report(report, args.output)


if __name__ == "__main__":
    main()
