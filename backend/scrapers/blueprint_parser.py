"""
UniChat — Görev 3.2.7.1: Blueprint Parser Modülü

Lokal HTML dosyalarından (doc/gibtu/) sidebar menü ağacını yapısal olarak
çıkarır. Bu modül, tüm Harita Güdümlü Canlı Scraper modüllerinin (3.2.7.2+)
temel bağımlılığıdır.

3 aşamalı döngünün ilk halkası:
  🗺️ **Harita Okuma** → Bu modül
  🌐  Canlı Deep Scrape → map_guided_scraper.py (3.2.7.2)
  ✅  Doğrula + Yükle   → ingestion pipeline

Kullanım:
    from scrapers.blueprint_parser import parse_blueprint

    tree = parse_blueprint("doc/gibtu/FAKÜLTELER/.../MDBF.html")
    urls = tree.to_url_list()                 # canlı scrape hedef URL'leri
    text = tree.to_structured_text()          # menü haritası belge metni
    pdfs = tree.get_pdf_links()               # tespit edilen PDF linkleri

Doğrudan çalıştırma (test/debug):
    python -m scrapers.blueprint_parser <html_dosya_yolu>
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────

BASE_URL = "https://www.gibtu.edu.tr"

# GİBTÜ alan adı ailesine ait domainler
GIBTU_DOMAINS = {"gibtu.edu.tr", "www.gibtu.edu.tr"}

# Harici kabul edilen alt domainler (scrape edilmez, ama raporlanır)
EXTERNAL_SUBDOMAINS = {"ubys.gibtu.edu.tr", "mail.gibtu.edu.tr", "adayogrenci.gibtu.edu.tr"}

# Dosya uzantıları
_PDF_EXTENSIONS = {".pdf"}
_DOC_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


# ── Enum & Dataclass'lar ──────────────────────────────────────────────────────

class LinkType(str, Enum):
    """Menü bağlantı türleri."""
    PAGE = "page"           # GİBTÜ ana sitesinde normal sayfa
    PDF = "pdf"             # PDF belgesi bağlantısı
    DOC = "doc"             # Diğer belge türleri (doc, xls, ppt)
    EXTERNAL = "external"   # GİBTÜ dışı alan adı
    ANCHOR = "anchor"       # Aynı sayfa içi bağlantı (#fragment)
    PARENT = "parent"       # Alt menü açan üst öğe (href yok)
    SUBDOMAIN = "subdomain" # GİBTÜ alt domain'i (ubys, mail vb.)


@dataclass
class MenuLink:
    """Tek bir menü bağlantısının tam bilgisi."""
    href: str               # Orijinal href değeri
    url: str                # Tam (absolute) URL
    text: str               # Bağlantı metni
    link_type: LinkType     # Sınıflandırılmış tür
    target: str = "_self"   # target özniteliği (_self, _blank)

    @property
    def is_scrapable(self) -> bool:
        """Bu bağlantı canlı scrape edilebilir mi?"""
        return self.link_type == LinkType.PAGE

    @property
    def is_document(self) -> bool:
        """Bu bağlantı indirilebilir bir belge mi? (PDF/DOC)"""
        return self.link_type in (LinkType.PDF, LinkType.DOC)


@dataclass
class MenuItem:
    """
    Sidebar menüsündeki tek bir üst düzey öğe.

    Leaf öğeler (alt menüsü olmayan): link dolu, children boş.
    Parent öğeler (alt menülü): link varsa üst başlık, children dolu.
    """
    title: str                               # Menü başlığı (collapsible-header metni)
    link: MenuLink | None = None             # Ana başlıktaki bağlantı (leaf'lerde dolu)
    children: list[MenuLink] = field(default_factory=list)  # Alt menü bağlantıları
    is_parent: bool = False                  # Alt menüsü var mı?

    @property
    def all_links(self) -> list[MenuLink]:
        """Bu öğedeki tüm bağlantılar (başlık + çocuklar)."""
        links = []
        if self.link:
            links.append(self.link)
        links.extend(self.children)
        return links


@dataclass
class MenuTree:
    """
    Bir birim sayfasının tam sidebar menü ağacı.

    Bu yapı parse_blueprint() fonksiyonunun çıktısıdır ve
    MapGuidedScraper (3.2.7.2) tarafından kullanılır.
    """
    items: list[MenuItem] = field(default_factory=list)
    source_file: str = ""           # Kaynak blueprint dosyası
    birim_id: int | None = None     # Tespit edilen BirimID (varsa)
    birim_title: str = ""           # Menü başlığı veya birim adı

    # ── URL Üretim ──

    def to_url_list(self, include_types: set[LinkType] | None = None) -> list[str]:
        """
        Canlı scrape için hedef URL listesi üretir.

        Varsayılan olarak yalnızca PAGE türündeki linkler döndürülür.
        Anchor ve parent türleri her zaman hariç tutulur.

        Args:
            include_types: Dahil edilecek link türleri. None ise sadece PAGE.

        Returns:
            Deduplicate edilmiş, sıralı URL listesi.
        """
        if include_types is None:
            include_types = {LinkType.PAGE}

        seen: set[str] = set()
        urls: list[str] = []

        for item in self.items:
            for link in item.all_links:
                if link.link_type not in include_types:
                    continue
                # Fragment kaldır
                clean_url = link.url.split("#")[0]
                if clean_url and clean_url not in seen:
                    seen.add(clean_url)
                    urls.append(clean_url)

        return urls

    def get_pdf_links(self) -> list[MenuLink]:
        """Menüde tespit edilen tüm PDF bağlantılarını döndürür."""
        pdfs: list[MenuLink] = []
        seen: set[str] = set()
        for item in self.items:
            for link in item.all_links:
                if link.link_type == LinkType.PDF and link.url not in seen:
                    seen.add(link.url)
                    pdfs.append(link)
        return pdfs

    def get_doc_links(self) -> list[MenuLink]:
        """Menüde tespit edilen tüm belge bağlantılarını döndürür (PDF + DOC)."""
        docs: list[MenuLink] = []
        seen: set[str] = set()
        for item in self.items:
            for link in item.all_links:
                if link.is_document and link.url not in seen:
                    seen.add(link.url)
                    docs.append(link)
        return docs

    def get_external_links(self) -> list[MenuLink]:
        """Menüde tespit edilen tüm harici ve subdomain bağlantılarını döndürür."""
        externals: list[MenuLink] = []
        seen: set[str] = set()
        for item in self.items:
            for link in item.all_links:
                if link.link_type in (LinkType.EXTERNAL, LinkType.SUBDOMAIN):
                    if link.url not in seen:
                        seen.add(link.url)
                        externals.append(link)
        return externals

    # ── Metin Üretimi ──

    def to_structured_text(self) -> str:
        """
        Menü ağacını insan-okunabilir yapısal metin haritasına dönüştürür.

        Bu metin, RAG pipeline'ında navigasyon/yönlendirme sorularına
        yanıt verilmesi için `doc_kind: menu_haritasi` olarak saklanır.

        Örnek çıktı:
            ## MDBF — Menü Haritası
            ├── Anasayfa → https://...Birim.aspx?id=15
            ├── Yönetim → https://...BirimYonetim.aspx?id=15
            ├── Hakkımızda
            │   ├── Misyon → https://...BirimMisyon.aspx?id=15
            │   ├── Vizyon → https://...BirimVizyon.aspx?id=15
            │   └── Tarihçe → https://...BirimTarihce.aspx?id=15
            ...
        """
        lines: list[str] = []

        header = self.birim_title or "Birim"
        lines.append(f"## {header} — Menü Haritası")
        if self.birim_id:
            lines.append(f"BirimID: {self.birim_id}")
        lines.append("")

        for i, item in enumerate(self.items):
            is_last_item = i == len(self.items) - 1
            prefix = "└──" if is_last_item else "├──"

            if item.link and item.link.url:
                type_tag = f" [{item.link.link_type.value}]" if item.link.link_type != LinkType.PAGE else ""
                lines.append(f"{prefix} {item.title} → {item.link.url}{type_tag}")
            else:
                lines.append(f"{prefix} {item.title}")

            if item.children:
                child_prefix = "    " if is_last_item else "│   "
                for j, child in enumerate(item.children):
                    is_last_child = j == len(item.children) - 1
                    child_connector = "└──" if is_last_child else "├──"
                    type_tag = f" [{child.link_type.value}]" if child.link_type != LinkType.PAGE else ""
                    lines.append(f"{child_prefix}{child_connector} {child.text} → {child.url}{type_tag}")

        return "\n".join(lines)

    # ── İstatistikler ──

    @property
    def stats(self) -> dict:
        """Menü ağacı istatistikleri."""
        all_links: list[MenuLink] = []
        for item in self.items:
            all_links.extend(item.all_links)

        type_counts: dict[str, int] = {}
        for link in all_links:
            t = link.link_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "menu_item_count": len(self.items),
            "total_link_count": len(all_links),
            "scrapable_url_count": len(self.to_url_list()),
            "pdf_count": len(self.get_pdf_links()),
            "external_count": len(self.get_external_links()),
            "link_type_distribution": type_counts,
            "birim_id": self.birim_id,
        }


# ── Link Sınıflandırma ───────────────────────────────────────────────────────

def classify_menu_link(href: str, text: str = "", target: str = "_self") -> MenuLink:
    """
    Bir menü bağlantısını sınıflandırır.

    Sınıflandırma öncelik sırası:
      1. href boş/yok → PARENT (alt menü üst başlığı)
      2. # ile başlıyor → ANCHOR
      3. .pdf uzantısı veya Medya/Dosya + .pdf → PDF
      4. .doc/.xls/.ppt uzantısı → DOC
      5. GİBTÜ alt domaini (ubys, mail vb.) → SUBDOMAIN
      6. GİBTÜ dışı alan adı → EXTERNAL
      7. Aksi halde → PAGE

    Args:
        href: Orijinal href değeri.
        text: Bağlantı metni.
        target: target özniteliği.

    Returns:
        Sınıflandırılmış MenuLink nesnesi.
    """
    # href temizle
    href = (href or "").strip()

    # ── Boş href → parent ──
    if not href:
        return MenuLink(
            href="", url="", text=text,
            link_type=LinkType.PARENT, target=target,
        )

    # ── Anchor ──
    if href.startswith("#"):
        return MenuLink(
            href=href, url=href, text=text,
            link_type=LinkType.ANCHOR, target=target,
        )

    # ── Tam URL'ye dönüştür ──
    if href.startswith("http://") or href.startswith("https://"):
        full_url = href
    elif href.startswith("/"):
        full_url = f"{BASE_URL}{href}"
    else:
        full_url = f"{BASE_URL}/{href}"

    # URL temizle: &amp; → &
    full_url = full_url.replace("&amp;", "&")

    # ── Uzantı tabanlı tespit ──
    parsed = urlparse(full_url)
    path_lower = parsed.path.lower()

    for ext in _PDF_EXTENSIONS:
        if path_lower.endswith(ext):
            return MenuLink(
                href=href, url=full_url, text=text,
                link_type=LinkType.PDF, target=target,
            )

    for ext in _DOC_EXTENSIONS:
        if path_lower.endswith(ext):
            return MenuLink(
                href=href, url=full_url, text=text,
                link_type=LinkType.DOC, target=target,
            )

    # Medya/Dosya kalıbındaki PDF'ler (uzantı URL'de olmayabilir)
    if "GibtuDosya" in href or "birim/dosya" in path_lower.lower():
        # Bu kalıp GİBTÜ'de neredeyse her zaman PDF'ye işaret eder
        if ".pdf" in href.lower():
            return MenuLink(
                href=href, url=full_url, text=text,
                link_type=LinkType.PDF, target=target,
            )

    # ── Domain tabanlı tespit ──
    netloc = parsed.netloc.lower()

    # GİBTÜ alt domain'leri (ubys, mail vb.)
    if netloc in EXTERNAL_SUBDOMAINS:
        return MenuLink(
            href=href, url=full_url, text=text,
            link_type=LinkType.SUBDOMAIN, target=target,
        )

    # GİBTÜ dışı alan adı
    if netloc and not netloc.endswith("gibtu.edu.tr"):
        return MenuLink(
            href=href, url=full_url, text=text,
            link_type=LinkType.EXTERNAL, target=target,
        )

    # ── Geri kalan: normal sayfa ──
    # Fragment'lı URL'ler de PAGE olarak sınıflandırılır,
    # ama kendi içinde anchor bilgisi korunur (BirimIletisim.aspx?id=15#Harita gibi)
    return MenuLink(
        href=href, url=full_url, text=text,
        link_type=LinkType.PAGE, target=target,
    )


# ── BirimID Çıkarma ──────────────────────────────────────────────────────────

def _extract_birim_id(url: str) -> int | None:
    """URL'den BirimID değerini çıkarır. Bulamazsa None döndürür."""
    parsed = urlparse(url.replace("&amp;", "&"))
    qs = parse_qs(parsed.query)
    id_val = qs.get("id", [None])[0]
    if id_val and id_val.isdigit():
        return int(id_val)
    return None


def _detect_birim_id_from_tree(items: list[MenuItem]) -> int | None:
    """Menü ağacından BirimID tahmin eder (ilk geçerli Birim URL'sinden)."""
    for item in items:
        for link in item.all_links:
            if link.link_type == LinkType.PAGE and "Birim" in link.href:
                bid = _extract_birim_id(link.url)
                if bid:
                    return bid
    return None


# ── Sidebar Menü Parse ────────────────────────────────────────────────────────

def extract_sidebar_menu(html: str) -> MenuTree:
    """
    GİBTÜ birim sayfası HTML'inden sidebar menü ağacını çıkarır.

    DOM yapısı (keşif raporundan doğrulanmış):
        span.birim-menu / #birim-menu-slide
          └── ul.collapsible[data-collapsible="accordion"]
                └── li
                      ├── div.collapsible-header
                      │     ├── a (başlık bağlantısı — href varsa leaf/parent)
                      │     └── i.material-icons (keyboard_arrow_right) → parent işareti
                      └── div.collapsible-body (opsiyonel — alt menü)
                            └── ul > li > a (alt menü bağlantıları)

    Ayrıca Fakülteler.html gibi kök harita dosyalarını da destekler:
        li > a.collapsible-header + div.collapsible-body > ul > li > a

    Args:
        html: Ham HTML string (lokal dosyadan okunmuş).

    Returns:
        MenuTree yapısı.
    """
    if not html:
        logger.warning("Boş HTML, boş MenuTree döndürülüyor.")
        return MenuTree()

    soup = BeautifulSoup(html, "lxml")

    # ── Sidebar konteynerini bul ──
    # Öncelik 1: span#birim-menu-slide veya span.birim-menu
    sidebar = soup.find("span", id="birim-menu-slide")
    if not sidebar:
        sidebar = soup.find("span", class_="birim-menu")

    # Öncelik 2: doğrudan ul.collapsible (Fakülteler.html gibi snippet dosyalar)
    if not sidebar:
        sidebar = soup.find("ul", class_="collapsible")
        if sidebar:
            # ul'nin kendisini değil, ebeveyn li'yi kullan
            sidebar = sidebar.parent or sidebar

    if not sidebar:
        # Son çare: a.collapsible-header olan en üstteki konteyner
        first_header = soup.find("a", class_="collapsible-header")
        if first_header:
            sidebar = first_header.find_parent("li")
            if sidebar:
                sidebar = sidebar.parent  # ul'yi al

    if not sidebar:
        logger.warning("Sidebar menü bulunamadı (span.birim-menu / ul.collapsible yok).")
        return MenuTree()

    # ── Menü başlığını çıkar ──
    menu_title = ""
    header_span = soup.find("span", class_="birim-menu-header")
    if header_span:
        menu_title = header_span.get_text(strip=True)

    # ── ul.collapsible bul ──
    collapsible_ul = sidebar.find("ul", class_="collapsible")
    if not collapsible_ul:
        # Snippet dosyalarda sidebar'ın kendisi li olabilir
        # Doğrudan collapsible-header/body aramak gerekebilir
        collapsible_ul = sidebar

    # ── Her <li> bir MenuItem ──
    items: list[MenuItem] = []

    # li öğelerini bul — doğrudan çocuk li'ler
    li_elements = collapsible_ul.find_all("li", recursive=False)
    if not li_elements:
        # collapsible_ul ul ise altındaki li'leri al
        inner_ul = collapsible_ul.find("ul", class_="collapsible")
        if inner_ul:
            li_elements = inner_ul.find_all("li", recursive=False)

    if not li_elements:
        # Belki doğrudan li (tek li snippet dosyası — Fakülteler.html)
        if collapsible_ul.name == "li":
            li_elements = [collapsible_ul]

    for li in li_elements:
        item = _parse_menu_item(li)
        if item:
            items.append(item)

    # ── BirimID tespiti ──
    birim_id = _detect_birim_id_from_tree(items)

    # ── Birim adı tespiti ──
    birim_title = ""
    page_title = soup.find("span", class_="sayfa_baslik")
    if page_title:
        inner = page_title.find("span")
        if inner:
            birim_title = inner.get_text(strip=True)
        else:
            birim_title = page_title.get_text(strip=True)

    if not birim_title:
        # collapsible-header'dan ilk parent olan öğenin metnini kullan
        for item in items:
            if item.is_parent and item.title:
                birim_title = item.title
                break

    tree = MenuTree(
        items=items,
        birim_id=birim_id,
        birim_title=birim_title,
    )

    logger.info(
        "Sidebar parse tamamlandı: %d menü öğesi, %d toplam link, BirimID=%s",
        len(items), sum(len(item.all_links) for item in items), birim_id,
    )

    return tree


def _parse_menu_item(li: Tag) -> MenuItem | None:
    """Tek bir <li> öğesini MenuItem'a dönüştürür."""
    # collapsible-header bul
    header_div = li.find("div", class_="collapsible-header")

    if not header_div:
        # Bazı snippet dosyalarda header doğrudan a etiketi olabilir
        header_a = li.find("a", class_="collapsible-header")
        if header_a:
            # Snippet format: a.collapsible-header + div.collapsible-body
            return _parse_snippet_item(li, header_a)

        # Basit li > a yapısı (collapsible-body alt öğesi olarak çağrılmaz,
        # ama Fakülteler.html'de kök li yapısı olabilir)
        simple_a = li.find("a", recursive=False)
        if simple_a:
            href = simple_a.get("href", "")
            text = simple_a.get_text(strip=True)
            target = simple_a.get("target", "_self")
            link = classify_menu_link(href, text, target)
            return MenuItem(title=text, link=link, is_parent=False)

        return None

    # ── Header'daki <a> ──
    header_a = header_div.find("a")
    if not header_a:
        return None

    title = header_a.get_text(strip=True)
    href = header_a.get("href", "")
    target = header_a.get("target", "_self")

    # ── Parent tespiti: keyboard_arrow_right ikonu ──
    arrow_icon = header_div.find("i", class_="material-icons")
    has_arrow = False
    if arrow_icon and "keyboard_arrow_right" in arrow_icon.get_text():
        has_arrow = True

    # ── collapsible-body (alt menü) ──
    body_div = li.find("div", class_="collapsible-body")
    children: list[MenuLink] = []

    if body_div:
        child_links = body_div.find_all("a", href=True)
        for child_a in child_links:
            child_href = child_a.get("href", "")
            child_text = child_a.get_text(strip=True)
            child_target = child_a.get("target", "_self")
            child_link = classify_menu_link(child_href, child_text, child_target)
            children.append(child_link)

    is_parent = has_arrow or len(children) > 0

    # ── Header link sınıflandırma ──
    if href:
        header_link = classify_menu_link(href, title, target)
    elif is_parent:
        header_link = MenuLink(
            href="", url="", text=title,
            link_type=LinkType.PARENT, target=target,
        )
    else:
        header_link = None

    return MenuItem(
        title=title,
        link=header_link,
        children=children,
        is_parent=is_parent,
    )


def _parse_snippet_item(li: Tag, header_a: Tag) -> MenuItem:
    """Snippet format: a.collapsible-header + div.collapsible-body."""
    title = header_a.get_text(strip=True)
    href = header_a.get("href", "")
    target = header_a.get("target", "_self")

    # Arrow icon
    arrow = header_a.find("i", class_="material-icons")
    has_arrow = arrow is not None and "keyboard_arrow_right" in (arrow.get_text() or "")

    # Alt menü
    body_div = li.find("div", class_="collapsible-body")
    children: list[MenuLink] = []
    if body_div:
        for child_a in body_div.find_all("a", href=True):
            child_link = classify_menu_link(
                child_a.get("href", ""),
                child_a.get_text(strip=True),
                child_a.get("target", "_self"),
            )
            children.append(child_link)

    is_parent = has_arrow or len(children) > 0

    if href:
        header_link = classify_menu_link(href, title, target)
    else:
        header_link = MenuLink(
            href="", url="", text=title,
            link_type=LinkType.PARENT, target=target,
        )

    return MenuItem(
        title=title, link=header_link,
        children=children, is_parent=is_parent,
    )


# ── Body İçerik Çıkarma ──────────────────────────────────────────────────────

def extract_body_content(html: str) -> str:
    """
    Ana içerik bölgesini (`birim_safya_body_detay`) saf metin olarak çıkarır.

    Bu, sidebar menüsünden bağımsız olarak sayfanın gövde metnini alır.
    Boş döndürülürse sayfa yalnızca navigasyon içeriyor demektir.

    3.2.7.4-C uyumu: DOM seviyesinde tam boilerplate temizliği uygular.

    Args:
        html: Ham HTML string.

    Returns:
        Temizlenmiş düz metin.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")

    # 3.2.7.4-C: DOM seviyesinde boilerplate elementlerini kaldır
    _BOILERPLATE_SELECTORS = [
        "footer", "div.page-footer", "div.footer-copyright",
        "ul.collapsible", "ul.side-nav", "nav", "div.navbar",
        "div.navbar-fixed", "span.birim-menu", "span#birim-menu-slide",
        ".fixed-action-btn", "div#header", "div#footer",
        "div.ust-menu", "div.arama-kutusu",
    ]
    for selector in _BOILERPLATE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    # Script, style vb. kaldır
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    # Öncelik 1: birim_safya_body_detay (GİBTÜ standart gövde alanı)
    body_div = soup.find("div", class_="birim_safya_body_detay")

    # Öncelik 2: birim_safya_body
    if not body_div:
        section = soup.find("section", class_="birim_safya_body")
        if section:
            body_div = section.find("aside")
            if not body_div:
                body_div = section

    if not body_div:
        return ""

    text = body_div.get_text(separator="\n")

    # Normalleştir
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    return text


# ── Üst Düzey API ────────────────────────────────────────────────────────────

def parse_blueprint(filepath: str | Path) -> MenuTree:
    """
    Lokal HTML dosyasından tam blueprint parse işlemi yapar.

    Bu, modülün birincil giriş noktasıdır. MapGuidedScraper (3.2.7.2)
    bu fonksiyonu çağırır.

    Args:
        filepath: Blueprint HTML dosyasının yolu.

    Returns:
        MenuTree yapısı.

    Raises:
        FileNotFoundError: Dosya bulunamazsa.
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Blueprint dosyası bulunamadı: {filepath}")

    logger.info("Blueprint parse ediliyor: %s", filepath.name)

    html = filepath.read_text(encoding="utf-8")
    tree = extract_sidebar_menu(html)
    tree.source_file = str(filepath)

    # Body content'i de kontrol et (istatistik için)
    body = extract_body_content(html)
    if body:
        logger.info("  Body içerik tespit edildi: %d karakter", len(body))

    return tree


# ── CLI / Test ────────────────────────────────────────────────────────────────

def _print_tree_report(tree: MenuTree):
    """Menü ağacını terminal'e detaylı rapor olarak yazdırır."""
    print("=" * 70)
    print(f"BLUEPRINT PARSE RAPORU")
    print(f"  Kaynak: {tree.source_file}")
    print(f"  BirimID: {tree.birim_id}")
    print(f"  Başlık: {tree.birim_title}")
    print("=" * 70)

    # İstatistikler
    stats = tree.stats
    print(f"\n📊 İSTATİSTİKLER:")
    print(f"  Menü öğesi sayısı:    {stats['menu_item_count']}")
    print(f"  Toplam link sayısı:   {stats['total_link_count']}")
    print(f"  Scrape edilecek URL:  {stats['scrapable_url_count']}")
    print(f"  PDF bağlantı sayısı:  {stats['pdf_count']}")
    print(f"  Harici link sayısı:   {stats['external_count']}")
    print(f"  Link türü dağılımı:   {stats['link_type_distribution']}")

    # Yapısal harita
    print(f"\n🗺️ MENÜ HARİTASI:")
    print(tree.to_structured_text())

    # Scrape hedef URL'leri
    urls = tree.to_url_list()
    print(f"\n🌐 SCRAPE HEDEF URL'LERİ ({len(urls)} adet):")
    for i, url in enumerate(urls, 1):
        print(f"  {i:3d}. {url}")

    # PDF linkleri
    pdfs = tree.get_pdf_links()
    if pdfs:
        print(f"\n📄 PDF BAĞLANTILARI ({len(pdfs)} adet):")
        for pdf in pdfs:
            print(f"  • {pdf.text[:60]} → {pdf.url}")

    # Harici linkler
    externals = tree.get_external_links()
    if externals:
        print(f"\n🔗 HARİCİ BAĞLANTILAR ({len(externals)} adet):")
        for ext in externals:
            print(f"  • [{ext.link_type.value}] {ext.text} → {ext.url}")

    print("=" * 70)


def main():
    """CLI giriş noktası — blueprint dosyasını parse edip rapor yazdırır."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if len(sys.argv) < 2:
        print("Kullanım: python -m scrapers.blueprint_parser <html_dosya_yolu>")
        print("")
        print("Örnekler:")
        print("  python -m scrapers.blueprint_parser \"doc/gibtu/FAKÜLTELER/Fakülteler.html\"")
        print("  python -m scrapers.blueprint_parser \"doc/gibtu/FAKÜLTELER/Mühendislik ve Doğa Bilimleri Fakültesi/Mühendislik_ve_Doğa_Bilimleri _Fakültesi.html\"")
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        tree = parse_blueprint(filepath)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    _print_tree_report(tree)


if __name__ == "__main__":
    main()
