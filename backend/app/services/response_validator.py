"""
UniChat Backend — Response Validator
LLM çıktısındaki URL, telefon ve e-posta bilgilerini kaynak belgelerle çapraz doğrular.

Tasarım felsefesi:
    Bu proje yalnızca GİBTÜ içindir. Bu nedenle:
    1. Yalnızca gibtu.edu.tr ve alt domain'leri güvenilir kabul edilir.
    2. gantep.edu.tr dahil diğer tüm üniversite domain'leri GİBTÜ DIŞI sayılır.
    3. Bir gibtu.edu.tr URL'si bile, retrieved source_docs içinde birebir geçmiyorsa
       cevapta bırakılmaz.
    4. Kurumsal referanslar (e-Devlet, YÖK) yalnızca source_docs içinde geçerse kabul edilir.

Neden gerekli:
    gemma3:4b-it-qat belgede olmayan URL (gibtu.edu.tr/Engelsiz/Musaitlik/...),
    telefon ((032) 2523 4000), ve domain (gantep.edu.tr) ürettiği QA testlerinde
    kanıtlanmıştır. Prompt kuralı LLM halüsinasyonunu %100 önleyemez.
    Deterministik post-generation validator gereklidir.
"""

import logging
import re
from typing import Any, Iterable, Optional
from datetime import date

logger = logging.getLogger(__name__)

# ── GİBTÜ resmi base domain ──
# Yalnızca bu domain ve alt domain'leri "GİBTÜ kaynağı" kabul edilir.
# Ama yine de source_docs içinde birebir geçmesi zorunludur.
GIBTU_BASE_DOMAIN = "gibtu.edu.tr"

# ── Açıkça reddedilen domain'ler ──
# DB'de source_url olarak mevcut olsa bile bunlar GİBTÜ'ye ait DEĞİLDİR.
# LLM bu URL'leri üretirse kaldırılır.
BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "gantep.edu.tr",
    "www.gantep.edu.tr",
    "sks.gantep.edu.tr",
    "bm.gantep.edu.tr",
})

# ── Bilinen GİBTÜ e-posta domain'leri ──
# Yalnızca bu domain'lerden gelen e-postalar source_docs kontrolü ile kabul edilir.
# gantep.edu.tr e-postaları her zaman reddedilir.
GIBTU_EMAIL_DOMAIN = "gibtu.edu.tr"
BLOCKED_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gantep.edu.tr",
})

# ── Regex pattern'ler ──
URL_PATTERN = re.compile(r'https?://[^\s\)\]\}>\"\']+'  )
PHONE_PATTERN = re.compile(r'[\+]?\(?\d[\d\s\(\)\-]{8,}\d')
EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w.-]+\.\w{2,}')
LOCAL_PATH_PATTERN = re.compile(r'[A-Z]:\\[^\s\"]+', re.IGNORECASE)
WORD_PATTERN = re.compile(r"\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{2,}\b")
ACADEMIC_YEAR_PATTERN = re.compile(r"\b20\d{2}\s*[-–/]\s*20\d{2}\b")
ACADEMIC_DATE_PATTERN = re.compile(
    r"\b\d{1,2}\s*(?:[-–—]\s*\d{1,2})?\s+"
    r"(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)"
    r"\s+\d{2,4}\b"
    r"|"
    r"\b\d{1,2}\s+"
    r"(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)"
    r"\s*[-–—]\s*\d{1,2}\s+"
    r"(?:Ocak|Şubat|Subat|Mart|Nisan|Mayıs|Mayis|Haziran|Temmuz|Ağustos|Agustos|Eylül|Eylul|Ekim|Kasım|Kasim|Aralık|Aralik)"
    r"\s+\d{2,4}\b"
    r"|"
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}(?:\s*[-–—]\s*\d{1,2}[./]\d{1,2}[./]\d{2,4})?\b",
    re.IGNORECASE,
)

# ── Placeholder sabitler ──
PLACEHOLDER_URL = "**www.gibtu.edu.tr** (resmi web sitesini ziyaret ediniz)"
PLACEHOLDER_URL_BLOCKED = "[GİBTÜ dışı kaynak kaldırıldı]"
PLACEHOLDER_PHONE = "[iletişim bilgisi için ilgili birime başvurunuz]"
PLACEHOLDER_EMAIL = "[e-posta bilgisi için ilgili birime başvurunuz]"
PLACEHOLDER_PATH = "[kurum içi belge]"
PLACEHOLDER_ACADEMIC_DATE = "[kaynakta doğrulanamayan akademik takvim tarihi]"
LANGUAGE_FALLBACK_RESPONSE = (
    "Bu konuda elimdeki belgelerden Türkçe ve güvenilir bir cevap oluşturamadım. "
    "Detaylı bilgi için ilgili birime başvurmanızı öneriyorum."
)
ACADEMIC_STAFF_RAG_FALLBACK_RESPONSE = (
    "Akademik kadro soruları ÜniChat DB'deki YÖK Akademik kaynaklı bölüm/program "
    "kadro kayıtlarından yanıtlanmalıdır. Bu konuda güvenilir DB-first akademik kadro "
    "cevabı oluşturulamadığı için RAG metniyle tahmini yanıt verilmedi."
)

ENGLISH_TO_TURKISH_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbased on (?:the )?(?:provided )?documents[:,]?", re.IGNORECASE), "Belgelerdeki bilgilere göre:"),
    (re.compile(r"\baccording to (?:the )?(?:provided )?documents[:,]?", re.IGNORECASE), "Belgelerdeki bilgilere göre:"),
    (re.compile(r"\bthe documents (?:do not|don't) provide enough information\b", re.IGNORECASE), "Belgelerde yeterli bilgi bulunmuyor"),
    (re.compile(r"\bi (?:do not|don't) have enough information\b", re.IGNORECASE), "Bu konuda elimde yeterli bilgi bulunmuyor"),
    (re.compile(r"\bfor more information[:,]?", re.IGNORECASE), "Detaylı bilgi için"),
    (re.compile(r"\bplease contact\b", re.IGNORECASE), "lütfen başvurun"),
    (re.compile(r"\bcontact\b", re.IGNORECASE), "İletişim"),
    (re.compile(r"\bsource\b", re.IGNORECASE), "Kaynak"),
    (re.compile(r"\bsources\b", re.IGNORECASE), "Kaynaklar"),
    (re.compile(r"\bdepartment\b", re.IGNORECASE), "Birim"),
    (re.compile(r"\bdepartments\b", re.IGNORECASE), "Birimler"),
)

ENGLISH_SIGNAL_WORDS: frozenset[str] = frozenset({
    "the", "and", "or", "is", "are", "was", "were", "this", "that",
    "student", "students", "university", "department", "departments",
    "contact", "please", "information", "available", "provided", "according",
    "based", "documents", "source", "sources", "application", "apply",
    "program", "programs", "campus", "library", "dormitory", "international",
})

PORTUGUESE_SIGNAL_WORDS: frozenset[str] = frozenset({
    "os", "as", "um", "uma", "para", "com", "sobre", "segundo",
    "documentos", "universidade", "departamento", "professores",
    "professor", "informacao", "informacoes", "contato", "fonte",
    "fontes", "alunos", "programa", "programas", "academico",
})

TURKISH_SIGNAL_WORDS: frozenset[str] = frozenset({
    "ve", "veya", "ile", "için", "icin", "bu", "şu", "su", "öğrenci",
    "ogrenci", "üniversite", "universite", "bölüm", "bolum", "birim",
    "başvuru", "basvuru", "kayıt", "kayit", "bilgi", "belge", "belgeler",
    "kaynak", "iletişim", "iletisim", "detaylı", "detayli", "bulunuyor",
    "bulunmuyor", "başvur", "basvur", "öneriyorum", "oneriyorum",
})

ACADEMIC_STAFF_PUBLICATION_OR_THESIS_RE = re.compile(
    r"\b("
    r"tez\w*|thesis|yayın\w*|yayin\w*|publication\w*|makale\w*|article\w*|journal\w*|"
    r"doi|abstract|anahtar\s+kelime\w*|temel\s+alan|bilim\s+alan|öğrenim\s+bilg\w*|ogrenim\s+bilg\w*|"
    r"dekan\w*|bölüm\s+başkan\w*|bolum\s+baskan\w*|rektör\w*|rektor\w*"
    r")\b",
    re.IGNORECASE,
)

MONTH_NAMES_TR = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}


def _extract_domain(url: str) -> Optional[str]:
    """URL'den domain'i çıkarır."""
    try:
        after_scheme = url.split("//", 1)[1] if "//" in url else url
        domain = after_scheme.split("/")[0].split(":")[0].split("?")[0]
        return domain.lower()
    except (IndexError, AttributeError):
        return None


def _is_blocked_domain(domain: str) -> bool:
    """Domain'in açıkça engellenmiş listede olup olmadığını kontrol eder."""
    if not domain:
        return False
    for blocked in BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return True
    return False


def _is_gibtu_domain(domain: str) -> bool:
    """Domain'in GİBTÜ'ye ait olup olmadığını kontrol eder."""
    if not domain:
        return False
    return domain == GIBTU_BASE_DOMAIN or domain.endswith("." + GIBTU_BASE_DOMAIN)


def _url_exists_in_sources(url: str, source_docs: list[dict]) -> bool:
    """URL'nin kaynak belgelerde birebir geçip geçmediğini kontrol eder.

    URL'nin tam hali veya domain+path kısmı aranır.
    """
    url_clean = url.strip().rstrip("/")
    for doc in source_docs:
        source_text = _source_text(doc)
        # Birebir eşleşme
        if url_clean in source_text:
            return True
        # http/https farkını tolere et
        alt_url = url_clean.replace("https://", "http://") if "https://" in url_clean else url_clean.replace("http://", "https://")
        if alt_url in source_text:
            return True
    return False


def _info_exists_in_sources(info: str, source_docs: list[dict]) -> bool:
    """Bilgi parçasının kaynak belgelerde geçip geçmediğini kontrol eder."""
    info_clean = info.strip()
    for doc in source_docs:
        if info_clean in _source_text(doc):
            return True
    return False


def _iter_source_values(value: Any) -> Iterable[str]:
    """Kaynak doküman sözlüğündeki metinsel alanları recursive biçimde dolaşır."""
    if isinstance(value, str):
        yield value
        return

    if isinstance(value, dict):
        for nested_value in value.values():
            yield from _iter_source_values(nested_value)
        return

    if isinstance(value, (list, tuple, set)):
        for nested_value in value:
            yield from _iter_source_values(nested_value)


def _source_text(source_doc: dict) -> str:
    """Whitelist ve kaynak doğrulama için kaynak dokümanı tek metin haline getirir."""
    return "\n".join(_iter_source_values(source_doc))


def _normalize_calendar_fragment(text: str) -> str:
    value = " ".join((text or "").strip().split()).casefold()
    value = value.replace("–", "-").replace("—", "-")
    return value


def _is_academic_calendar_source(source_doc: dict) -> bool:
    meta = source_doc.get("meta") or {}
    return (
        meta.get("doc_kind") == "academic_calendar_event"
        or meta.get("category") == "academic_calendar"
        or source_doc.get("category") == "academic_calendar"
    )


def _is_academic_staff_source(source_doc: dict) -> bool:
    meta = source_doc.get("meta") or {}
    category = meta.get("category") or source_doc.get("category")
    doc_kind = meta.get("doc_kind") or source_doc.get("doc_kind")
    return (
        category == "akademik_kadro"
        or doc_kind in {
            "yok_akademik_staff",
            "yok_akademik_profile",
            "academic_unit_clarification",
            "akademik_birim",
            "personel",
        }
    )


def _validate_academic_staff_rag_response(response: str, source_docs: list[dict]) -> tuple[str, list[str]]:
    """Akademik kadro RAG çıktısında yayın/tez/yönetim tahmini sinyallerini keser."""
    if not any(_is_academic_staff_source(doc) for doc in source_docs):
        return response, []

    if not ACADEMIC_STAFF_PUBLICATION_OR_THESIS_RE.search(response):
        return response, []

    return (
        ACADEMIC_STAFF_RAG_FALLBACK_RESPONSE,
        ["Akademik kadro RAG yanıtında yayın/tez/yönetim tahmini sinyali engellendi"],
    )


def _format_iso_date(iso_value: str | None) -> str | None:
    if not iso_value:
        return None
    try:
        parsed = date.fromisoformat(str(iso_value))
    except ValueError:
        return str(iso_value)
    return f"{parsed.day} {MONTH_NAMES_TR[parsed.month]} {parsed.year}"


def _calendar_allowed_fragments(source_docs: list[dict]) -> set[str]:
    """Akademik takvim kaynaklarından cevapta geçmesine izin verilen tarih parçalarını çıkarır."""
    allowed: set[str] = set()

    for doc in source_docs:
        if not _is_academic_calendar_source(doc):
            continue

        source_text = _source_text(doc)
        for match in ACADEMIC_DATE_PATTERN.findall(source_text):
            allowed.add(_normalize_calendar_fragment(match))
        for match in ACADEMIC_YEAR_PATTERN.findall(source_text):
            allowed.add(_normalize_calendar_fragment(match))

        meta = doc.get("meta") or {}
        for field_name in ("academic_year", "original_date_text", "start_date", "end_date"):
            value = meta.get(field_name)
            if value:
                allowed.add(_normalize_calendar_fragment(str(value)))

        start_text = _format_iso_date(meta.get("start_date"))
        end_text = _format_iso_date(meta.get("end_date"))
        if start_text:
            allowed.add(_normalize_calendar_fragment(start_text))
        if end_text:
            allowed.add(_normalize_calendar_fragment(end_text))
        if start_text and end_text and start_text != end_text:
            allowed.add(_normalize_calendar_fragment(f"{start_text} - {end_text}"))

    return allowed


def _academic_fragment_allowed(fragment: str, allowed_fragments: set[str], source_docs: list[dict]) -> bool:
    normalized = _normalize_calendar_fragment(fragment)
    if normalized in allowed_fragments:
        return True

    for doc in source_docs:
        if not _is_academic_calendar_source(doc):
            continue
        if normalized and normalized in _normalize_calendar_fragment(_source_text(doc)):
            return True
    return False


def _validate_academic_calendar_dates(response: str, source_docs: list[dict]) -> tuple[str, list[str]]:
    """Akademik takvim cevaplarında kaynak dışı tarih/akademik yılı kaldırır."""
    if not any(_is_academic_calendar_source(doc) for doc in source_docs):
        return response, []

    allowed_fragments = _calendar_allowed_fragments(source_docs)
    if not allowed_fragments:
        return response, []

    cleaned = response
    changes: list[str] = []

    for pattern in (ACADEMIC_DATE_PATTERN, ACADEMIC_YEAR_PATTERN):
        for match in list(pattern.finditer(cleaned)):
            fragment = match.group(0)
            if _academic_fragment_allowed(fragment, allowed_fragments, source_docs):
                continue
            cleaned = cleaned.replace(fragment, PLACEHOLDER_ACADEMIC_DATE, 1)
            changes.append(f"Kaynak dışı akademik takvim tarihi kaldırıldı: {fragment}")

    return cleaned, changes


def _normalize_email(email: str) -> str:
    """E-posta karşılaştırmaları için küçük harfli ve noktalama temizlenmiş değer döndürür."""
    return email.strip().strip(".,;:)]}>").lower()


def _email_whitelist(source_docs: list[dict]) -> set[str]:
    """Kaynaklardan birebir izinli e-posta listesini çıkarır."""
    whitelist: set[str] = set()
    for doc in source_docs:
        for email in EMAIL_PATTERN.findall(_source_text(doc)):
            whitelist.add(_normalize_email(email))
    return whitelist


def _normalize_phone_digits(phone: str) -> str:
    """Telefonu yalnızca rakamlardan oluşan karşılaştırma biçimine çevirir."""
    return re.sub(r"\D", "", phone)


def _phone_variants(phone: str) -> set[str]:
    """0/90 ülke kodu farklarını tolere eden telefon varyantları üretir."""
    digits = _normalize_phone_digits(phone)
    if len(digits) < 10:
        return set()

    variants = {digits}
    local = digits
    if local.startswith("90") and len(local) > 10:
        local = local[2:]
        variants.add(local)

    if local.startswith("0") and len(local) > 10:
        without_zero = local[1:]
        variants.add(without_zero)
        variants.add("90" + without_zero)
    elif len(local) == 10:
        variants.add("0" + local)
        variants.add("90" + local)

    return variants


def _phone_whitelist(source_docs: list[dict]) -> set[str]:
    """Kaynaklardan izinli telefon numarası varyantlarını çıkarır."""
    whitelist: set[str] = set()
    for doc in source_docs:
        for phone in PHONE_PATTERN.findall(_source_text(doc)):
            whitelist.update(_phone_variants(phone))
    return whitelist


def _is_email_allowed(email: str, whitelist: set[str]) -> bool:
    """E-postanın domain ve kaynak whitelist kurallarına göre güvenli olup olmadığını döndürür."""
    normalized = _normalize_email(email)
    email_domain = normalized.split("@")[1] if "@" in normalized else ""

    if any(email_domain.endswith(blocked_domain) for blocked_domain in BLOCKED_EMAIL_DOMAINS):
        return False

    return normalized in whitelist


def _is_phone_allowed(phone: str, whitelist: set[str]) -> bool:
    """Telefon numarasını kaynak whitelist'indeki normalize edilmiş varyantlarla eşleştirir."""
    variants = _phone_variants(phone)
    if not variants:
        return False
    return bool(variants & whitelist)


def _apply_turkish_phrase_fixes(response: str) -> str:
    """LLM'in sık ürettiği İngilizce kalıpları deterministik Türkçe karşılıklarla değiştirir."""
    fixed = response
    for pattern, replacement in ENGLISH_TO_TURKISH_PHRASES:
        fixed = pattern.sub(replacement, fixed)
    return fixed


def _language_signal_counts(response: str) -> tuple[int, int]:
    """Basit kelime sinyalleriyle yabancı dil/Türkçe ağırlığı ölçer."""
    words = [word.lower() for word in WORD_PATTERN.findall(response)]
    english_count = sum(
        1 for word in words
        if word in ENGLISH_SIGNAL_WORDS or word in PORTUGUESE_SIGNAL_WORDS
    )
    turkish_count = sum(1 for word in words if word in TURKISH_SIGNAL_WORDS)
    turkish_count += sum(1 for char in response if char in "çğıöşüÇĞİÖŞÜ")
    return english_count, turkish_count


def enforce_turkish_response(response: str) -> str:
    """Cevabın Türkçe kalmasını sağlayan response-level dil tutarlılığı kontrolü."""
    if not response:
        return response

    fixed = _apply_turkish_phrase_fixes(response)
    english_count, turkish_count = _language_signal_counts(fixed)

    # Güçlü Türkçe dışı baskınlık varsa içerik uydurarak çevrilmez; güvenli Türkçe fallback döner.
    if english_count >= 5 and english_count > turkish_count:
        logger.warning(
            "🌐 Dil tutarlılığı kontrolü Türkçe dışı baskın yanıtı güvenli Türkçe fallback ile değiştirdi "
            "(foreign=%d, turkish=%d).",
            english_count,
            turkish_count,
        )
        return LANGUAGE_FALLBACK_RESPONSE

    if fixed != response:
        logger.warning("🌐 Dil tutarlılığı kontrolü İngilizce kalıpları Türkçeleştirdi.")

    return fixed


def validate_response(response: str, source_docs: list[dict]) -> str:
    """LLM yanıtındaki iletişim bilgilerini kaynak belgelerle çapraz doğrular.

    Doğrulama kuralları:
        1. URL'ler:
           - Blocked domain (gantep.edu.tr vb.) → her zaman kaldırılır
           - GİBTÜ domain → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
           - Diğer domain → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
        2. E-postalar:
           - gantep.edu.tr → her zaman kaldırılır
           - Kaynaklardan çıkarılan e-posta whitelist'inde geçiyorsa kalır, yoksa kaldırılır
        3. Telefonlar:
           - Kaynaklardan çıkarılan telefon whitelist'inde geçiyorsa kalır, yoksa kaldırılır
        4. Lokal dosya yolları:
           - Her zaman kaldırılır
        5. Dil tutarlılığı:
           - İngilizce kalıplar Türkçeleştirilir
           - İngilizce baskın cevap güvenli Türkçe fallback ile değiştirilir

    Args:
        response: LLM'in ürettiği yanıt metni.
        source_docs: Pipeline'dan dönen kaynak belgeler listesi.

    Returns:
        Doğrulanmış/temizlenmiş yanıt metni.
    """
    if not response:
        return response

    cleaned = response
    changes = []
    allowed_emails = _email_whitelist(source_docs)
    allowed_phones = _phone_whitelist(source_docs)

    # 1. URL doğrulama — en kritik katman
    for url_match in URL_PATTERN.finditer(cleaned):
        url = url_match.group()
        domain = _extract_domain(url)

        # 1a. Blocked domain → koşulsuz kaldır
        if _is_blocked_domain(domain):
            cleaned = cleaned.replace(url, PLACEHOLDER_URL_BLOCKED, 1)
            changes.append(f"Engelli domain kaldırıldı: {url}")
            continue

        # 1b. GİBTÜ domain → source_docs'ta birebir geçmeli
        if _is_gibtu_domain(domain):
            if not _url_exists_in_sources(url, source_docs):
                cleaned = cleaned.replace(url, PLACEHOLDER_URL, 1)
                changes.append(f"Doğrulanamayan GİBTÜ URL kaldırıldı: {url}")
            continue

        # 1c. Diğer domain'ler → source_docs'ta geçmeli
        if not _url_exists_in_sources(url, source_docs):
            cleaned = cleaned.replace(url, PLACEHOLDER_URL, 1)
            changes.append(f"Doğrulanamayan URL kaldırıldı: {url}")

    # 2. Lokal dosya yolları → koşulsuz kaldır
    for path_match in LOCAL_PATH_PATTERN.finditer(cleaned):
        path = path_match.group()
        cleaned = cleaned.replace(path, PLACEHOLDER_PATH, 1)
        changes.append(f"Dosya yolu kaldırıldı: {path}")

    # 3. Telefon doğrulama → source_docs kontrolü
    for phone_match in PHONE_PATTERN.finditer(cleaned):
        phone = phone_match.group()
        phone_digits = _normalize_phone_digits(phone)

        # Çok kısa numaraları atla (yıl, madde numarası olabilir)
        if len(phone_digits) < 10:
            continue

        if not _is_phone_allowed(phone, allowed_phones):
            cleaned = cleaned.replace(phone, PLACEHOLDER_PHONE, 1)
            changes.append(f"Whitelist dışı telefon kaldırıldı: {phone}")

    # 4. E-posta doğrulama
    for email_match in EMAIL_PATTERN.finditer(cleaned):
        email = email_match.group()
        normalized_email = _normalize_email(email)
        email_domain = normalized_email.split("@")[1] if "@" in normalized_email else ""

        # 4a. Blocked e-posta domain → koşulsuz kaldır
        if any(email_domain.endswith(bd) for bd in BLOCKED_EMAIL_DOMAINS):
            cleaned = cleaned.replace(email, PLACEHOLDER_EMAIL, 1)
            changes.append(f"GİBTÜ dışı e-posta kaldırıldı: {email}")
            continue

        # 4b. Tüm e-postalar kaynaklardan çıkarılan whitelist'te birebir geçmeli
        if not _is_email_allowed(email, allowed_emails):
            cleaned = cleaned.replace(email, PLACEHOLDER_EMAIL, 1)
            if email_domain.endswith(GIBTU_EMAIL_DOMAIN):
                changes.append(f"Whitelist dışı GİBTÜ e-posta kaldırıldı: {email}")
            else:
                changes.append(f"Whitelist dışı e-posta kaldırıldı: {email}")

    # 5. Akademik takvim tarih doğrulama
    cleaned, academic_changes = _validate_academic_calendar_dates(cleaned, source_docs)
    changes.extend(academic_changes)

    # 6. Akademik kadro RAG güvenlik kontrolü
    cleaned, staff_changes = _validate_academic_staff_rag_response(cleaned, source_docs)
    changes.extend(staff_changes)

    # 7. Dil tutarlılığı kontrolü
    language_checked = enforce_turkish_response(cleaned)
    if language_checked != cleaned:
        changes.append("Dil tutarlılığı düzeltildi")
        cleaned = language_checked

    if changes:
        logger.warning(
            "🔒 Response validator %d düzeltme yaptı: %s",
            len(changes), "; ".join(changes),
        )

    return cleaned
