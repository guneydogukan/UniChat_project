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

import re
import logging
from typing import Optional

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

# ── Placeholder sabitler ──
PLACEHOLDER_URL = "**www.gibtu.edu.tr** (resmi web sitesini ziyaret ediniz)"
PLACEHOLDER_URL_BLOCKED = "[GİBTÜ dışı kaynak kaldırıldı]"
PLACEHOLDER_PHONE = "[iletişim bilgisi için ilgili birime başvurunuz]"
PLACEHOLDER_EMAIL = "[e-posta bilgisi için ilgili birime başvurunuz]"
PLACEHOLDER_PATH = "[kurum içi belge]"


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
        content = doc.get("content", "") or ""
        source_url = doc.get("source_url", "") or ""
        # Birebir eşleşme
        if url_clean in content or url_clean in source_url:
            return True
        # http/https farkını tolere et
        alt_url = url_clean.replace("https://", "http://") if "https://" in url_clean else url_clean.replace("http://", "https://")
        if alt_url in content or alt_url in source_url:
            return True
    return False


def _info_exists_in_sources(info: str, source_docs: list[dict]) -> bool:
    """Bilgi parçasının kaynak belgelerde geçip geçmediğini kontrol eder."""
    info_clean = info.strip()
    for doc in source_docs:
        content = doc.get("content", "") or ""
        if info_clean in content:
            return True
        source_url = doc.get("source_url", "") or ""
        if source_url and info_clean in source_url:
            return True
    return False


def validate_response(response: str, source_docs: list[dict]) -> str:
    """LLM yanıtındaki iletişim bilgilerini kaynak belgelerle çapraz doğrular.

    Doğrulama kuralları:
        1. URL'ler:
           - Blocked domain (gantep.edu.tr vb.) → her zaman kaldırılır
           - GİBTÜ domain → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
           - Diğer domain → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
        2. E-postalar:
           - gantep.edu.tr → her zaman kaldırılır
           - gibtu.edu.tr → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
           - Diğer → source_docs'ta geçiyorsa kalır, yoksa kaldırılır
        3. Telefonlar:
           - source_docs'ta geçiyorsa kalır, yoksa kaldırılır
        4. Lokal dosya yolları:
           - Her zaman kaldırılır

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
        phone_digits = re.sub(r'[\s\(\)\-\+]', '', phone)

        # Çok kısa numaraları atla (yıl, madde numarası olabilir)
        if len(phone_digits) < 10:
            continue

        # Kaynak belgelerde var mı?
        if not _info_exists_in_sources(phone, source_docs):
            # Rakam dizisi olarak da kontrol et
            digit_in_source = any(
                phone_digits in re.sub(r'[\s\(\)\-\+]', '', doc.get("content", "") or "")
                for doc in source_docs
            )
            if not digit_in_source:
                cleaned = cleaned.replace(phone, PLACEHOLDER_PHONE, 1)
                changes.append(f"Telefon kaldırıldı: {phone}")

    # 4. E-posta doğrulama
    for email_match in EMAIL_PATTERN.finditer(cleaned):
        email = email_match.group()
        email_domain = email.split("@")[1] if "@" in email else ""

        # 4a. Blocked e-posta domain → koşulsuz kaldır
        if any(email_domain.endswith(bd) for bd in BLOCKED_EMAIL_DOMAINS):
            cleaned = cleaned.replace(email, PLACEHOLDER_EMAIL, 1)
            changes.append(f"GİBTÜ dışı e-posta kaldırıldı: {email}")
            continue

        # 4b. GİBTÜ e-posta → source_docs'ta geçmeli
        if email_domain.endswith(GIBTU_EMAIL_DOMAIN):
            if not _info_exists_in_sources(email, source_docs):
                cleaned = cleaned.replace(email, PLACEHOLDER_EMAIL, 1)
                changes.append(f"Doğrulanamayan GİBTÜ e-posta kaldırıldı: {email}")
            continue

        # 4c. Diğer e-postalar → source_docs'ta geçmeli
        if not _info_exists_in_sources(email, source_docs):
            cleaned = cleaned.replace(email, PLACEHOLDER_EMAIL, 1)
            changes.append(f"E-posta kaldırıldı: {email}")

    if changes:
        logger.warning(
            "🔒 Response validator %d düzeltme yaptı: %s",
            len(changes), "; ".join(changes),
        )

    return cleaned
