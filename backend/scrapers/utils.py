"""
UniChat Backend — Scraper Utilities
HTML temizleme ve URL normalleştirme yardımcı fonksiyonları.
"""

import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup


# ── HTML Temizleme ──

# İçerik dışı kabul edilen etiketler (çıkarılacak)
_REMOVE_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"}


def clean_html(raw_html: str) -> str:
    """
    Ham HTML'den temiz düz metin çıkarır.

    İşlem adımları:
    1. script, style, nav, footer, header vb. etiketleri tamamen kaldır
    2. Kalan HTML'den düz metni çıkar
    3. Ardışık boşluk ve satır sonlarını normalleştir

    Args:
        raw_html: Ham HTML string.

    Returns:
        Temizlenmiş düz metin.
    """
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "lxml")

    # İçerik dışı etiketleri tamamen kaldır
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    # Düz metin çıkar
    text = soup.get_text(separator="\n")

    # Ardışık boşluk / satır sonlarını normalleştir
    text = re.sub(r"[ \t]+", " ", text)           # ardışık yatay boşluk → tek boşluk
    text = re.sub(r"\n\s*\n+", "\n\n", text)      # ardışık boş satırlar → tek boş satır
    text = text.strip()

    return text


def extract_title(html: str) -> str:
    """
    HTML'den sayfa başlığını çıkarır.

    Öncelik: <h1> > <title> > boş string.

    Args:
        html: Ham HTML string.

    Returns:
        Sayfa başlığı.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")

    # Önce h1 dene
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    # Sonra title dene
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)

    return ""


# ── URL Normalleştirme ──

def normalize_url(url: str, base_url: str = "") -> str:
    """
    URL'yi normalleştirir.

    İşlem adımları:
    1. Relative URL ise base_url ile absolute'a dönüştür
    2. Fragment (#...) kaldır
    3. Trailing slash normalleştir
    4. Scheme ve netloc küçük harfe çevir

    Args:
        url: Normalleştirilecek URL (relative veya absolute).
        base_url: Relative URL'ler için baz URL.

    Returns:
        Normalleştirilmiş absolute URL.
    """
    if not url:
        return ""

    # Relative → absolute dönüşüm
    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url)

    # Fragment kaldır
    parsed = parsed._replace(fragment="")

    # Scheme ve netloc küçük harf
    parsed = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
    )

    # Trailing slash normalleştirme (path'te yalnızca "/" varsa koru)
    path = parsed.path
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    parsed = parsed._replace(path=path)

    return urlunparse(parsed)


def is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    """
    URL'nin izin verilen alan adlarından birine ait olup olmadığını kontrol eder.

    Args:
        url: Kontrol edilecek URL.
        allowed_domains: İzin verilen alan adları listesi.

    Returns:
        True ise izin verilen.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    for domain in allowed_domains:
        domain = domain.lower()
        if netloc == domain or netloc.endswith("." + domain):
            return True

    return False
