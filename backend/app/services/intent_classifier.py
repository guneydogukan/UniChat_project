"""
UniChat Backend — Intent Classifier
Kapsam dışı sorguları pipeline'a ulaşmadan deterministik olarak reddeder.

Neden gerekli:
    gemma3:4b-it-qat prompt kurallarını güvenilir takip edemiyor.
    QA testlerinde Python kodu yazdığı (G7-02) ve genel kültür sorusuna
    cevap verdiği (G7-01) kanıtlanmıştır. Rule-based pre-filter
    %100 deterministik çalışır.

Kullanım:
    from app.services.intent_classifier import classify_intent

    intent = classify_intent("Bana Python kodu yaz")
    if intent == "OUT_OF_SCOPE":
        return REJECTION_RESPONSE
"""

import re
import logging

logger = logging.getLogger(__name__)

# ── Kapsam dışı pattern'ler ──
# Her pattern (regex, açıklama) ikilisi
OUT_OF_SCOPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Programlama kodu talepleri
    # NOT: Türkçe aglutinative dil — "kod" → "kodu/kodunu/kodları".
    # Trailing \b kaldırıldı, \w* ile suffix toleransı sağlandı.
    (re.compile(
        r"\b(python|javascript|java|c\+\+|html|css|sql|php|ruby|swift|kotlin|rust|go|typescript)\w*"
        r".*\b(kod|code|yaz|script|program|fonksiyon|function|class|sınıf)\w*",
        re.IGNORECASE,
    ), "programlama_kodu"),

    (re.compile(
        r"\b(kod|code|script|program|fonksiyon|function)\w*"
        r".*\b(yaz|oluştur|üret|generate|create)\w*",
        re.IGNORECASE,
    ), "programlama_kodu"),

    # Genel kültür / coğrafya
    (re.compile(
        r"\b(başkent|başbakan|cumhurbaşkan|nüfus|yüzölçüm)\w*"
        r".*\b(nere|ne\s?dir|kim|kaç)\w*",
        re.IGNORECASE,
    ), "genel_kultur"),

    (re.compile(
        r"\b(nere|ne\s?dir|kim)\w*"
        r".*\b(başkent|başbakan|cumhurbaşkan|nüfus)\w*",
        re.IGNORECASE,
    ), "genel_kultur"),

    # Hava durumu / finans / spor
    (re.compile(
        r"\b(hava\s+durumu|döviz|borsa|kripto|bitcoin|maç\s+skor|lig\s+puan)\w*",
        re.IGNORECASE,
    ), "guncel_bilgi"),

    # Yemek tarifi / diyet
    (re.compile(
        r"\b(yemek\s+tarif|diyet\s+liste|kalori\s+hesapla)\w*",
        re.IGNORECASE,
    ), "yasam_tarzi"),

    # Yaratıcı yazım
    (re.compile(
        r"\b(şiir\s+yaz|hikaye\s+yaz|roman\s+yaz|mektup\s+yaz|söz\s+yaz)\w*",
        re.IGNORECASE,
    ), "yaratici_yazim"),

    # Çeviri talebi (üniversite bağlamı dışı)
    (re.compile(
        r"\b(çevir|translate|tercüme\s+et)\w*"
        r".*\b(ingilizce|almanca|fransızca|arapça|japonca)\w*",
        re.IGNORECASE,
    ), "ceviri"),

    # Matematik / fizik hesaplama
    (re.compile(
        r"\b(hesapla|kaç\s+eder|karekök|integral|türev|faktöriyel)\w*"
        r"(?!.*\b(harç|ücret|kredi|ders|akts)\w*)",  # harç hesaplama gibi üniversite bağlamını dışla
        re.IGNORECASE,
    ), "matematik"),
]

# ── Üniversite bağlamı sinyal kelimeleri ──
UNIVERSITY_SIGNALS: frozenset[str] = frozenset({
    # Kurum
    "gibtu", "gibtü", "gıbtu", "üniversite", "universite",
    "gaziantep islam", "gaziantep İslam",
    # Akademik birimler
    "fakülte", "fakulte", "bölüm", "bolum", "enstitü", "myo",
    "yüksekokul", "rektör", "dekan", "dekanlık",
    # Eğitim
    "ders", "sınav", "sinav", "transkript", "diploma", "mezuniyet",
    "kayıt", "devamsızlık", "müfredat", "akts", "kredi",
    "kontenjan", "başarı", "not", "dönem",
    # Öğrenci yaşam
    "erasmus", "staj", "burs", "yurt", "yemekhane", "kütüphane",
    "kulüp", "topluluk", "öğrenci",
    # İdari
    "öğrenci işleri", "obs", "ubys", "lms", "harç",
    "duyuru", "akademik takvim", "yönetmelik", "yönerge",
    # Birimler
    "mdbf", "sbf", "shmyo", "tbmyo", "ydyo", "gsmf", "sks",
    "ilahiyat", "tıp",
})

# ── Sabit reddetme yanıtı ──
REJECTION_RESPONSE = (
    "Bu soru GİBTÜ (Gaziantep İslam Bilim ve Teknoloji Üniversitesi) ile ilgili değil. "
    "Ben yalnızca GİBTÜ'nün akademik programları, öğrenci hizmetleri, idari süreçler "
    "ve kampüs yaşamı hakkında yardımcı olabilirim. 😊\n\n"
    "**Örnek sorular:**\n"
    "- GİBTÜ'de hangi bölümler var?\n"
    "- Erasmus başvurusu nasıl yapılır?\n"
    "- Sınav takvimi ne zaman açıklanır?\n"
    "- Kütüphane çalışma saatleri nedir?"
)


def classify_intent(query: str) -> str:
    """Sorgunun GİBTÜ kapsamında olup olmadığını belirler.

    Returns:
        "OUT_OF_SCOPE"  — Kapsam dışı, sabit yanıt dön
        "IN_SCOPE"      — Üniversite sinyal kelimesi var, pipeline'a gönder
        "NEEDS_CHECK"   — Belirsiz, pipeline'a gönder (LLM karar versin)
    """
    q_lower = query.lower().strip()
    q_words = set(q_lower.split())

    # 1. Kapsam dışı pattern kontrolü
    for pattern, category in OUT_OF_SCOPE_PATTERNS:
        if pattern.search(q_lower):
            # Üniversite bağlamı var mı? (ör: "üniversitede Python dersi var mı?")
            has_university_context = bool(q_words & UNIVERSITY_SIGNALS)
            if has_university_context:
                logger.info(
                    "🔍 Intent: '%s' kapsam dışı pattern (%s) eşleşti AMA üniversite bağlamı var → IN_SCOPE",
                    query[:60], category,
                )
                return "IN_SCOPE"

            logger.info(
                "🚫 Intent: '%s' → OUT_OF_SCOPE (kategori: %s)",
                query[:60], category,
            )
            return "OUT_OF_SCOPE"

    # 2. Üniversite sinyal kelimesi varsa kesin kapsam içi
    if q_words & UNIVERSITY_SIGNALS:
        logger.debug("✅ Intent: '%s' → IN_SCOPE (sinyal kelimesi)", query[:60])
        return "IN_SCOPE"

    # 3. Belirsiz — pipeline'a gönder, LLM güçlendirilmiş prompt ile karar versin
    logger.debug("❓ Intent: '%s' → NEEDS_CHECK", query[:60])
    return "NEEDS_CHECK"
