"""
UniChat Backend — Query Preprocessor
Yazım hatası düzeltme, kısaltma çözümleme ve karşılaştırmalı sorgu genişletme.

Neden gerekli:
    - BM25 exact match arar: "bilgiyasar" → "bilgisayar" eşleşmez (G2-01)
    - "MDBF" kısaltması veritabanında açık adıyla geçer (G4-03)
    - Karşılaştırmalı sorgularda top_k yetersizliği (G3-02)

Kullanım:
    from app.services.query_preprocessor import preprocess_query

    result = preprocess_query("gibtüde bilgiyasar mühendsligi var mı?")
    # result.corrected_query → "gibtüde bilgisayar mühendisliği var mı?"
    # result.expanded_query  → None (kısaltma yoksa)
    # result.is_comparison   → False
    # result.boost_top_k     → 0 (karşılaştırma yoksa)
"""

import re
import logging
from dataclasses import dataclass, field
from difflib import get_close_matches

logger = logging.getLogger(__name__)


# ── GİBTÜ Domain Sözlüğü ──
# Yazım hatası düzeltme için kullanılır. Yalnızca üniversite terimleri.
DOMAIN_TERMS: list[str] = [
    # Bölüm / program adları
    "bilgisayar", "mühendislik", "mühendisliği", "endüstri", "elektrik", "elektronik",
    "hemşirelik", "ebelik", "fizyoterapi", "rehabilitasyon", "gastronomi",
    "ilahiyat", "mimarlık", "tasarım", "mütercim", "tercümanlık",
    "ameliyathane", "laboratuvar", "radyo", "televizyon", "makine",
    "bilgisayarcılık", "programcılık",
    # Genel terimler
    "üniversite", "fakülte", "yüksekokul", "enstitü", "bölüm",
    "kütüphane", "yemekhane", "müfredat", "transkript",
    "erasmus", "akreditasyon", "devamsızlık", "yönetmelik",
    "koordinatörlük", "dekanlık", "rektörlük",
    "kontenjan", "başvuru", "kayıt", "mezuniyet",
    # Yerleşke
    "kampüs", "yurt", "spor",
]

# ── Kısaltma Sözlüğü ──
ABBREVIATION_MAP: dict[str, str] = {
    "mdbf": "mühendislik ve doğa bilimleri fakültesi",
    "sbf": "sağlık bilimleri fakültesi",
    "shmyo": "sağlık hizmetleri meslek yüksekokulu",
    "tbmyo": "teknik bilimler meslek yüksekokulu",
    "iisbf": "iktisadi idari ve sosyal bilimler fakültesi",
    "iii": "iktisadi idari ve sosyal bilimler fakültesi",
    "gsmf": "güzel sanatlar tasarım ve mimarlık fakültesi",
    "ydyo": "yabancı diller yüksekokulu",
    "sks": "sağlık kültür ve spor daire başkanlığı",
    "obs": "öğrenci bilgi sistemi",
    "ubys": "üniversite bilgi yönetim sistemi",
    "lms": "öğrenme yönetim sistemi",
    "kyk": "kredi ve yurtlar kurumu",
    "yök": "yükseköğretim kurulu",
    "tömer": "türkçe öğretimi merkezi",
    "bap": "bilimsel araştırma projeleri",
}

# ── Konu → Birim Yönlendirme Haritası ──
# Belirli konulardaki sorguları doğru birime yönlendirmek için
# keyword query'ye birim adı eklenir.
TOPIC_ROUTING_HINTS: list[tuple[re.Pattern, str, str]] = [
    # (pattern, birim_adı, log_açıklama)
    (re.compile(
        r"\b(transkript|not\s+belgesi|öğrenci\s+belgesi|ilişik\s+kes|kayıt\s+dondur|kayıt\s+sil|harç|katkı\s+payı)\w*",
        re.IGNORECASE,
    ), "öğrenci işleri daire başkanlığı", "Öğrenci İşleri yönlendirmesi"),

    (re.compile(
        r"\b(burs|kyk|yurt|barınma)\w*",
        re.IGNORECASE,
    ), "sağlık kültür ve spor daire başkanlığı", "SKS yönlendirmesi"),

    (re.compile(
        r"\b(erasmus|mevlana|farabi|değişim\s+program)\w*",
        re.IGNORECASE,
    ), "uluslararası ilişkiler koordinatörlüğü", "Erasmus/Değişim yönlendirmesi"),

    (re.compile(
        r"\b(staj|zorunlu\s+staj|staj\s+defteri)\w*",
        re.IGNORECASE,
    ), "bölüm başkanlığı staj koordinatörlüğü", "Staj yönlendirmesi"),
]

# ── Karşılaştırma Pattern'leri ──
COMPARISON_PATTERNS: list[re.Pattern] = [
    # "X mi Y mi" formu — Türkçe soru eki varyasyonları
    re.compile(
        r"(.+?)\s+m[iıuü]\s+(.+?)\s+m[iıuü](?:\s|$|\?)",
        re.IGNORECASE,
    ),
    # "X ile Y arasındaki fark"
    re.compile(
        r"(.+?)\s+(?:ile|ve)\s+(.+?)\s+(?:arasındaki?\s+fark|karşılaştır|kıyasla)",
        re.IGNORECASE,
    ),
    # "X vs Y" veya "X versus Y"
    re.compile(
        r"(.+?)\s+(?:vs\.?|versus)\s+(.+)",
        re.IGNORECASE,
    ),
]

# Türkçe yaygın ekler — basit suffix stripping
TURKISH_SUFFIXES: list[str] = [
    "ları", "leri", "ler", "lar",
    "ını", "ini", "unu", "ünü",
    "nın", "nin", "nun", "nün",
    "dan", "den", "tan", "ten",
    "ya", "ye", "na", "ne",
    "da", "de", "ta", "te",
    "ı", "i", "u", "ü",
]


def _stem_turkish(word: str) -> str:
    """Basit Türkçe suffix stripping (NLP kütüphanesi gerektirmez)."""
    w = word.lower()
    for suffix in TURKISH_SUFFIXES:
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


@dataclass
class PreprocessResult:
    """Sorgu ön-işleme sonucu."""
    original_query: str
    corrected_query: str                   # Yazım hatası düzeltilmiş
    keyword_query: str                     # BM25 için genişletilmiş
    vector_query: str                      # Vektör araması için
    is_comparison: bool = False            # Karşılaştırmalı sorgu mu?
    comparison_terms: list[str] = field(default_factory=list)
    boost_top_k: int = 0                   # Ek top_k (karşılaştırma sorgularında)
    routing_hint: str | None = None        # Yönlendirme ipucu (birim adı)
    corrections: list[str] = field(default_factory=list)  # Yapılan düzeltme logları


def _correct_typos(query: str) -> tuple[str, list[str]]:
    """Domain-specific fuzzy matching ile yazım hatalarını düzeltir."""
    words = query.split()
    corrected = []
    corrections = []

    for word in words:
        w_lower = word.lower()

        # Kısa kelimeleri atla (edatlar, ekler)
        if len(w_lower) < 4:
            corrected.append(word)
            continue

        # Zaten sözlükte var mı? (exact match)
        if w_lower in {t.lower() for t in DOMAIN_TERMS}:
            corrected.append(word)
            continue

        # Stem versiyonunu da dene
        stemmed = _stem_turkish(w_lower)

        # Fuzzy match — threshold 0.6 (Türkçe suffix toleransı)
        matches = get_close_matches(w_lower, DOMAIN_TERMS, n=1, cutoff=0.6)
        if not matches:
            # Stem ile de dene
            matches = get_close_matches(stemmed, DOMAIN_TERMS, n=1, cutoff=0.65)

        if matches and matches[0].lower() != w_lower:
            corrected.append(matches[0])
            corrections.append(f"'{word}' → '{matches[0]}'")
        else:
            corrected.append(word)

    return " ".join(corrected), corrections


def _expand_abbreviations(query: str) -> tuple[str, list[str]]:
    """Kısaltmaları açık adlarıyla genişletir."""
    words = query.lower().split()
    expanded_parts = []
    expansions = []

    for w in words:
        if w in ABBREVIATION_MAP:
            full_name = ABBREVIATION_MAP[w]
            expanded_parts.append(f"{w} {full_name}")
            expansions.append(f"'{w}' → '{full_name}'")
        else:
            expanded_parts.append(w)

    return " ".join(expanded_parts), expansions


def _detect_comparison(query: str) -> tuple[bool, list[str]]:
    """Karşılaştırmalı sorgu tespit eder ve terimleri çıkarır."""
    for pattern in COMPARISON_PATTERNS:
        m = pattern.search(query)
        if m:
            term1 = m.group(1).strip()
            term2 = m.group(2).strip()
            # Çok kısa terimleri filtrele
            if len(term1) > 2 and len(term2) > 2:
                return True, [term1, term2]
    return False, []


def preprocess_query(query: str) -> PreprocessResult:
    """Sorguyu typo correction, abbreviation expansion ve comparison detection ile ön-işler.

    Args:
        query: Kullanıcının orijinal sorgusu.

    Returns:
        PreprocessResult: Düzeltilmiş/genişletilmiş sorgular ve metadata.
    """
    result = PreprocessResult(
        original_query=query,
        corrected_query=query,
        keyword_query=query,
        vector_query=query,
    )

    # 1. Yazım hatası düzeltme
    corrected, typo_corrections = _correct_typos(query)
    if typo_corrections:
        result.corrected_query = corrected
        result.corrections.extend(typo_corrections)
        logger.info("✏️ Typo düzeltme: %s", ", ".join(typo_corrections))

    # 2. Kısaltma genişletme (BM25 keyword query'si için)
    expanded, abbreviation_expansions = _expand_abbreviations(result.corrected_query)
    if abbreviation_expansions:
        result.keyword_query = expanded
        result.corrections.extend(abbreviation_expansions)
        logger.info("📖 Kısaltma genişletme: %s", ", ".join(abbreviation_expansions))
    else:
        result.keyword_query = result.corrected_query

    # 3. Karşılaştırmalı sorgu tespiti
    is_comparison, terms = _detect_comparison(query)
    if is_comparison:
        result.is_comparison = True
        result.comparison_terms = terms
        result.boost_top_k = 3  # Her iki terim için ek top_k
        # Vektör sorgusunu her iki terimi içerecek şekilde genişlet
        result.vector_query = f"{result.corrected_query} {' '.join(terms)}"
        logger.info("⚖️ Karşılaştırmalı sorgu: %s", terms)
    else:
        result.vector_query = result.corrected_query

    # 4. Konu → birim yönlendirme ipucu
    for pattern, unit_name, desc in TOPIC_ROUTING_HINTS:
        if pattern.search(query):
            result.routing_hint = unit_name
            # Keyword query'ye birim adını ekle → BM25 doğru belgeleri bulsun
            result.keyword_query = f"{result.keyword_query} {unit_name}"
            result.corrections.append(f"🏢 {desc}")
            logger.info("🏢 Yönlendirme ipucu: %s → %s", query[:50], unit_name)
            break

    return result
