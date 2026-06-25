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

import logging
import re
import unicodedata
from difflib import SequenceMatcher

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

    # Siyaset / uluslararası gündem
    (re.compile(
        r"\b("
        r"israil|filistin|birleşmiş\s+milletler|birlesmis\s+milletler|"
        r"nato|savaş|savas|ateşkes|ateskes|seçim|secim|siyasi|siyaset|"
        r"politik|hükümet|hukumet|meclis|bakanlar|abd|rusya|ukrayna|suriye"
        r")\b",
        re.IGNORECASE,
    ), "siyaset_uluslararasi"),

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

ACADEMIC_CALENDAR_SCOPE_PATTERN = re.compile(
    r"\b(akademik\s*takvim|okul\s+ne\s+zaman\s+açılıyor|okul\s+ne\s+zaman\s+aciliyor|"
    r"ders\s+başlangıcı|ders\s+baslangici|ders\s+kayıt|ders\s+kayit|kayıt\s+yenileme|"
    r"kayit\s+yenileme|vize|ara\s+sınav|ara\s+sinav|final|bütünleme|butunleme|büt|"
    r"tek\s+ders|güz\s+dönemi|guz\s+donemi|bahar\s+dönemi|bahar\s+donemi|"
    r"kaç\s+gün\s+kaldı|kac\s+gun\s+kaldi|geçti\s+mi|gecti\s+mi)\b",
    re.IGNORECASE,
)

FAQ_SCOPE_PATTERN = re.compile(
    r"\b(sikca\s+sorulan|sik\s+sorulan|sss|faq)\b",
    re.IGNORECASE,
)

CLASSROOM_SCOPE_PATTERN = re.compile(
    r"\b("
    r"derslik\w*|sınıf\w*|sinif\w*|amfi\w*|laboratuvar\w*|lab\b|"
    r"konferans\s+salon\w*|hangi\s+kat\w*|katta|nolu|numaralı|numarali|"
    r"idari\s+ofis\w*|öğrenci\s+iş\w*|ogrenci\s+is\w*|"
    r"fakülte\s+sekreterliğ\w*|fakulte\s+sekreterlig\w*|"
    r"dekanlık\w*|dekanlik\w*|bölüm\s+başkanlığ\w*|bolum\s+baskanlig\w*|"
    r"mdbf|mühendislik\s+fakülte\w*|muhendislik\s+fakulte\w*|"
    r"mühendislik\s+bina\w*|muhendislik\s+bina\w*"
    r")\b",
    re.IGNORECASE,
)

PROGRAM_CATALOG_METRIC_PATTERN = re.compile(
    r"\b("
    r"taban\s+puan\w*|kaç\s+puan\w*|kac\s+puan\w*|puan\s+tür\w*|puan\s+tur\w*|"
    r"başarı\s+sıra\w*|basari\s+sira\w*|sıralama\w*|siralama\w*|"
    r"kontenjan\w*|kontejan\w*|yerleş\w*|yerles\w*|ösym|osym|"
    r"özel\s+koşul\w*|ozel\s+kosul\w*|netleri"
    r")\b",
    re.IGNORECASE,
)

PROGRAM_CATALOG_SCOPE_PATTERN = re.compile(
    r"\b("
    r"akademik\s+birim|fakülte\w*|fakulte\w*|yüksekokul\w*|yuksekokul\w*|"
    r"meslek\s+yüksekokul\w*|meslek\s+yuksekokul\w*|myo|enstitü\w*|enstitu\w*|"
    r"bölüm\w*|bolum\w*|program\w*|lisans|ön\s*lisans|on\s*lisans|onlisans|"
    r"hangi\s+birim|hangi\s+fakülte|hangi\s+fakulte|bünyesinde|bunyesinde|"
    r"var\s+mi|var\s+mı|varmi|mevcut\s+mu|mevcutmu|"
    r"açıldı\s+mı|acildi\s+mi|açıldımı|acildimi|açık\s+mı|acik\s+mi|aktif\s+mi|aktifmi"
    r")\b",
    re.IGNORECASE,
)

# ── Üniversite bağlamı sinyal kelimeleri ──
UNIVERSITY_SIGNALS: frozenset[str] = frozenset({
    # Kurum
    "gibtu", "gibtü", "gıbtu", "üniversite", "universite",
    "gaziantep islam", "gaziantep İslam",
    "aday", "aday öğrenci", "aday ogrenci", "tercih", "başvuru", "basvuru",
    "sık sorulan", "sıkça sorulan", "sik sorulan", "sikca sorulan", "sss", "faq",
    # Akademik birimler
    "fakülte", "fakulte", "bölüm", "bolum", "enstitü", "myo",
    "yüksekokul", "rektör", "dekan", "dekanlık",
    # Eğitim
    "ders", "sınav", "sinav", "transkript", "diploma", "mezuniyet",
    "derslik", "sınıf", "sinif", "amfi", "laboratuvar", "lab",
    "kayıt", "devamsızlık", "müfredat", "akts", "kredi",
    "kontenjan", "başarı", "not", "dönem",
    "akademik takvim", "takvim", "vize", "final", "bütünleme", "büt",
    "ara sınav", "yarıyıl", "güz", "bahar", "tek ders", "ders kaydı",
    "kayıt yenileme", "okul açılıyor", "ders başlangıcı",
    "okul",
    # Öğrenci yaşam
    "erasmus", "staj", "burs", "yurt", "yemekhane", "kütüphane",
    "kulüp", "topluluk", "öğrenci",
    # İdari
    "öğrenci işleri", "idari ofis", "idari personel", "idari birim", "sekreterlik",
    "fakülte sekreteri", "yüksekokul sekreteri", "memur",
    "obs", "ubys", "lms", "harç",
    "duyuru", "akademik takvim", "yönetmelik", "yönerge",
    # Birimler
    "mdbf", "sbf", "shmyo", "tbmyo", "ydyo", "gsmf", "iibf", "iisbf", "sks",
    "ilahiyat", "tıp", "tip",
})


def _normalize_for_intent(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    for src, dst in {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}.items():
        normalized = normalized.replace(src, dst)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


UNIVERSITY_SIGNALS_NORMALIZED: frozenset[str] = frozenset(
    _normalize_for_intent(signal) for signal in UNIVERSITY_SIGNALS
)

UNIVERSITY_FUZZY_ROOTS: frozenset[str] = frozenset({
    "gibtu",
    "universite",
    "fakulte",
    "bolum",
    "enstitu",
    "yuksekokul",
    "ogrenci",
    "aday",
    "basvuru",
    "kayit",
    "kontenjan",
    "kampus",
    "derslik",
    "sinif",
    "amfi",
    "laboratuvar",
    "kutuphane",
    "yemekhane",
    "erasmus",
    "transkript",
    "diploma",
    "mezuniyet",
    "akademik",
})


def _has_university_context(normalized_query: str) -> bool:
    tokens = set(normalized_query.split())
    for signal in UNIVERSITY_SIGNALS_NORMALIZED:
        if not signal:
            continue
        if " " in signal and signal in normalized_query:
            return True
        if signal in tokens:
            return True

    for token in tokens:
        if len(token) < 4:
            continue
        for root in UNIVERSITY_FUZZY_ROOTS:
            if token.startswith(root) or root.startswith(token):
                return True
            if SequenceMatcher(None, token, root).ratio() >= 0.86:
                return True
    return False

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
    q_norm = _normalize_for_intent(query)

    if ACADEMIC_CALENDAR_SCOPE_PATTERN.search(q_lower) or ACADEMIC_CALENDAR_SCOPE_PATTERN.search(q_norm):
        logger.debug("✅ Intent: '%s' → IN_SCOPE (akademik takvim)", query[:60])
        return "IN_SCOPE"

    if FAQ_SCOPE_PATTERN.search(q_norm):
        logger.debug("✅ Intent: '%s' → IN_SCOPE (SSS/FAQ)", query[:60])
        return "IN_SCOPE"

    if CLASSROOM_SCOPE_PATTERN.search(q_lower) or CLASSROOM_SCOPE_PATTERN.search(q_norm):
        logger.debug("✅ Intent: '%s' → IN_SCOPE (derslik konumu)", query[:60])
        return "IN_SCOPE"

    # 1. Kapsam dışı pattern kontrolü
    for pattern, category in OUT_OF_SCOPE_PATTERNS:
        if pattern.search(q_lower) or pattern.search(q_norm):
            # Üniversite bağlamı var mı? (ör: "üniversitede Python dersi var mı?")
            has_university_context = _has_university_context(q_norm)
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
    if _has_university_context(q_norm):
        logger.debug("✅ Intent: '%s' → IN_SCOPE (sinyal kelimesi)", query[:60])
        return "IN_SCOPE"

    # 3. Belirsiz — pipeline'a gönder, LLM güçlendirilmiş prompt ile karar versin
    logger.debug("❓ Intent: '%s' → NEEDS_CHECK", query[:60])
    return "NEEDS_CHECK"


def classify_program_catalog_intent(query: str) -> str | None:
    """Bölüm/program katalog sorguları için dar intent sınıflandırması.

    YÖK Atlas metrik sorguları bu yardımcı tarafından bilinçli olarak
    sınıflandırılmaz; mevcut YokatlasQueryService akışında kalır.
    """
    if PROGRAM_CATALOG_METRIC_PATTERN.search(query):
        return None

    q_lower = query.lower()
    q_norm = (
        q_lower
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    has_list_word = bool(re.search(r"\b(hangi|neler|nelerdir|liste|listesi|goster|göster)\b", q_lower))

    if "meslek yuksekokul" in q_norm or "myo" in q_norm:
        return "vocational_school_programs_query" if "program" in q_norm else "vocational_school_list_query"
    if "yuksekokul" in q_norm and "meslek" not in q_norm:
        return "school_list_query"
    if "fakulte" in q_norm and "bolum" in q_norm:
        return "faculty_departments_query"
    if "fakulte" in q_norm:
        return "faculty_list_query"
    if "enstitu" in q_norm:
        return "institute_list_query"
    if "akademik birim" in q_norm:
        return "academic_unit_list_query"
    if ("on lisans" in q_norm or "onlisans" in q_norm) and has_list_word:
        return "associate_degree_programs_query"
    if "lisans" in q_norm and "onlisans" not in q_norm and "on lisans" not in q_norm and has_list_word:
        return "undergraduate_programs_query"
    if "program" in q_norm and has_list_word:
        return "program_list_query"
    if "bolum" in q_norm and has_list_word:
        return "department_list_query"
    if re.search(
        r"\b("
        r"var\s+mi|var\s+mı|varmi|mevcut\s+mu|mevcutmu|"
        r"bulunuyor\s+mu|bulunur\s+mu|yok\s+mu|yokmu|"
        r"açıldı\s+mı|acildi\s+mi|açıldımı|acildimi|açık\s+mı|acik\s+mi|aktif\s+mi|aktifmi"
        r")\b",
        q_lower,
    ):
        return "program_exists_query"
    if re.search(r"\b(hangi\s+fakulte|hangi\s+fakülte|hangi\s+birim|nerede|bunyesinde|bünyesinde)\b", q_lower):
        return "program_faculty_query"
    if PROGRAM_CATALOG_SCOPE_PATTERN.search(query):
        return "ambiguous_program_query"
    return None
