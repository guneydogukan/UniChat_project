"""
UniChat Backend — Güvenli Yemekhane Menü Scraper

Bu modül genel crawler değildir. Yalnızca sabit GİBTÜ yemek listesi
sayfasını indirir ve tarih bazlı menüleri parse eder.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ALLOWED_MENU_URL = "https://www.gibtu.edu.tr/yemeklistesi"
ALLOWED_HOST = "www.gibtu.edu.tr"
ALLOWED_PATHS = {"/yemeklistesi", "/yemeklistesi.aspx"}
REQUEST_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 2
USER_AGENT = "UniChatBot/1.0 (+https://www.gibtu.edu.tr)"

TURKISH_MONTHS = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}

DATE_PATTERNS = [
    re.compile(r"\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})\b"),
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(
        r"\b(?P<day>\d{1,2})\s+"
        r"(?P<month>ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|"
        r"ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
        r"\s+(?P<year>\d{4})\b",
        re.IGNORECASE,
    ),
]

BOILERPLATE_LINES = {
    "image",
    "yemek listesi",
    "aylık yemek listesi",
    "yemek menüsü",
    "yemekhane rezervasyon",
    "yemekhane rezervasyon yap",
    "gibtü toplantı",
    "ana sayfa",
    "homepage",
    "menü",
    "menu",
}

FOOTER_START_TERMS = {
    "iletişim bilgileri",
    "beştepe mah",
    "mustafa bencan",
    "info@gibtu.edu.tr",
    "gibtuni@hs01.kep.tr",
    "gaziantep islam bilim ve teknoloji üniversitesi",
}


@dataclass
class ParsedFoodMenu:
    """Tek bir güne ait parse edilmiş menü."""

    date: date
    menu_items: list[str]
    source_url: str = ALLOWED_MENU_URL
    raw_text: str = ""
    raw_data: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "menu_items": self.menu_items,
            "source_url": self.source_url,
            "raw_text": self.raw_text,
            "raw_data": self.raw_data,
        }


@dataclass
class FoodMenuScrapeResult:
    """Sayfa scrape sonucu."""

    success: bool
    menus: list[ParsedFoodMenu] = field(default_factory=list)
    source_url: str = ALLOWED_MENU_URL
    raw_text: str = ""
    error: str | None = None


def parse_menu_date(text: str) -> date | None:
    """Desteklenen tarih formatlarından date nesnesi üretir."""
    if not text:
        return None

    normalized = " ".join(text.replace("\xa0", " ").split())
    for pattern in DATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue

        parts = match.groupdict()
        month_value = parts["month"]
        if month_value.isdigit():
            month = int(month_value)
        else:
            month = TURKISH_MONTHS.get(month_value.casefold())
            if month is None:
                continue

        try:
            return date(int(parts["year"]), month, int(parts["day"]))
        except ValueError:
            logger.debug("Geçersiz menü tarihi atlandı: %s", text)
            return None

    return None


def _collapse_spaces(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _is_footer_start(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in FOOTER_START_TERMS)


def _clean_menu_item(text: str) -> str | None:
    """Sayfa metninden gerçek yemek adını ayıklar."""
    cleaned = _collapse_spaces(text)
    if not cleaned:
        return None

    cleaned = re.sub(
        r"\s*[-–]\s*\d+(?:[,.]\d+)?\s*(?:kkal|kcal|kalori)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s+\d+(?:[,.]\d+)?\s*(?:kkal|kcal)\b.*$", "", cleaned, flags=re.IGNORECASE).strip()

    lowered = cleaned.casefold()
    if lowered in BOILERPLATE_LINES:
        return None
    if parse_menu_date(cleaned):
        return None
    if _is_footer_start(cleaned):
        return None
    if lowered.startswith(("http://", "https://", "www.")):
        return None
    if "keyboard_arrow" in lowered:
        return None
    if "rezervasyon" in lowered:
        return None
    if len(cleaned) < 2:
        return None

    return cleaned


def _dedupe_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


class FoodMenuScraper:
    """Sadece izinli yemek listesi sayfasını kullanan scraper."""

    def __init__(
        self,
        session: requests.Session | None = None,
        retry_delay_seconds: float = 0.5,
    ):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._retry_delay_seconds = retry_delay_seconds

    @staticmethod
    def _validate_final_url(url: str) -> None:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or parsed.path
        if parsed.scheme != "https" or parsed.netloc.casefold() != ALLOWED_HOST:
            raise ValueError(f"Yemek listesi izinli host dışına yönlendi: {url}")
        if path not in ALLOWED_PATHS:
            raise ValueError(f"Yemek listesi izinli path dışına yönlendi: {url}")

    def fetch_menu_page(self) -> str:
        """Sabit yemek listesi sayfasını indirir."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(
                    ALLOWED_MENU_URL,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )
                response.raise_for_status()
                self._validate_final_url(getattr(response, "url", ALLOWED_MENU_URL) or ALLOWED_MENU_URL)
                if not response.encoding or response.encoding == "ISO-8859-1":
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            except Exception as exc:
                last_error = exc
                logger.warning("Yemek listesi fetch hatası (%d/%d): %s", attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self._retry_delay_seconds)

        raise RuntimeError(f"Yemek listesi sayfası alınamadı: {last_error}")

    def parse_menu_html(self, html: str) -> list[ParsedFoodMenu]:
        """HTML içinden tarih bazlı menüleri çıkarır."""
        soup = BeautifulSoup(html, "html.parser")
        for selector in ["nav", "footer", "header", "script", "style", "noscript", "svg"]:
            for element in soup.select(selector):
                element.decompose()

        menus = self._parse_cards(soup)
        if not menus:
            menus = self._parse_text_fallback(soup)

        menus_by_date: dict[date, ParsedFoodMenu] = {}
        for menu in menus:
            if not menu.menu_items:
                continue
            menus_by_date[menu.date] = menu

        return [menus_by_date[d] for d in sorted(menus_by_date)]

    def fetch_menus(self) -> FoodMenuScrapeResult:
        """Sayfayı indirir, parse eder ve tüm tarihleri döndürür."""
        try:
            html = self.fetch_menu_page()
            menus = self.parse_menu_html(html)
            raw_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            if not menus:
                return FoodMenuScrapeResult(
                    success=False,
                    raw_text=raw_text,
                    error="Yemek listesi sayfasında parse edilebilir menü bulunamadı.",
                )
            return FoodMenuScrapeResult(success=True, menus=menus, raw_text=raw_text)
        except Exception as exc:
            logger.error("Yemek listesi scrape hatası: %s", exc, exc_info=True)
            return FoodMenuScrapeResult(success=False, error=str(exc))

    def extract_menu_for_date(self, target_date: date) -> ParsedFoodMenu | None:
        """Canlı sayfadan tek tarih için menü çıkarır."""
        result = self.fetch_menus()
        if not result.success:
            return None
        return next((menu for menu in result.menus if menu.date == target_date), None)

    def extract_menus_for_date_range(self, start_date: date, end_date: date) -> list[ParsedFoodMenu]:
        """Canlı sayfadan tarih aralığındaki menüleri çıkarır."""
        result = self.fetch_menus()
        if not result.success:
            return []
        return [menu for menu in result.menus if start_date <= menu.date <= end_date]

    def _parse_cards(self, soup: BeautifulSoup) -> list[ParsedFoodMenu]:
        menus: list[ParsedFoodMenu] = []
        for card in soup.select("div.card"):
            date_el = card.select_one(".card-title")
            date_text = date_el.get_text(" ", strip=True) if date_el else card.get_text(" ", strip=True)
            menu_date = parse_menu_date(date_text)
            if menu_date is None:
                continue

            content = card.select_one(".card-content") or card
            items: list[str] = []
            candidate_nodes = content.select("div.col, li, p, span")
            if candidate_nodes:
                for node in candidate_nodes:
                    item = _clean_menu_item(node.get_text(" ", strip=True))
                    if item:
                        items.append(item)

            if not items:
                for line in content.get_text("\n", strip=True).splitlines():
                    item = _clean_menu_item(line)
                    if item:
                        items.append(item)

            items = _dedupe_items(items)
            if items:
                raw_text = card.get_text("\n", strip=True)
                menus.append(
                    ParsedFoodMenu(
                        date=menu_date,
                        menu_items=items,
                        raw_text=raw_text,
                        raw_data={
                            "parser": "card",
                            "date_text": date_text,
                            "item_count": len(items),
                        },
                    )
                )
        return menus

    def _parse_text_fallback(self, soup: BeautifulSoup) -> list[ParsedFoodMenu]:
        body = soup.find("body") or soup
        lines = [_collapse_spaces(line) for line in body.get_text("\n", strip=True).splitlines()]

        menus: list[ParsedFoodMenu] = []
        current_date: date | None = None
        current_items: list[str] = []
        current_raw: list[str] = []

        def flush_current() -> None:
            nonlocal current_date, current_items, current_raw
            if current_date and current_items:
                items = _dedupe_items(current_items)
                menus.append(
                    ParsedFoodMenu(
                        date=current_date,
                        menu_items=items,
                        raw_text="\n".join(current_raw),
                        raw_data={
                            "parser": "text_fallback",
                            "item_count": len(items),
                        },
                    )
                )
            current_date = None
            current_items = []
            current_raw = []

        for line in lines:
            if not line:
                continue

            detected_date = parse_menu_date(line)
            if detected_date:
                flush_current()
                current_date = detected_date
                current_raw = [line]
                continue

            if current_date is None:
                continue

            if _is_footer_start(line):
                flush_current()
                continue

            current_raw.append(line)
            item = _clean_menu_item(line)
            if item:
                current_items.append(item)

        flush_current()
        return menus
