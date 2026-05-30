"""
UniChat Backend — Yemekhane Menü Intent ve Tarih Çıkarımı
Chat mesajındaki yemek menüsü sorgularını deterministik olarak yakalar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

ISTANBUL_WEEKDAY_NAMES = {
    0: "Pazartesi",
    1: "Salı",
    2: "Çarşamba",
    3: "Perşembe",
    4: "Cuma",
    5: "Cumartesi",
    6: "Pazar",
}

TURKISH_WEEKDAYS = {
    "pazartesi": 0,
    "salı": 1,
    "sali": 1,
    "çarşamba": 2,
    "carsamba": 2,
    "perşembe": 3,
    "persembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}

MENU_EXCLUSION_PHRASES = (
    "yemek tarifi",
    "tarif",
    "diyet",
    "kalori hesapla",
)

NON_MENU_INFO_PATTERNS = (
    re.compile(r"\byemekhane(?:de|si|nin|ye|den)?\s+var\s+m[ıi]\b", re.IGNORECASE),
    re.compile(
        r"\b("
        r"kapasite|kaç\s+kişilik|kac\s+kisilik|"
        r"ücret|ucret|fiyat|kart|bakiye|rezervasyon|"
        r"kural|hijyen|çalışma\s+saat|calisma\s+saat|"
        r"açık\s+m[ıi]|acik\s+m[ıi]|nerede|konum"
        r")\w*",
        re.IGNORECASE,
    ),
)

FOOD_MENU_PHRASES = (
    "yemekte ne var",
    "yemek listesi",
    "yemekhane menüsü",
    "yemekhane menu",
    "yemekhanede ne var",
    "bugünkü menü",
    "bugunku menu",
    "yarınki menü",
    "yarinki menu",
    "haftalık menü",
    "haftalik menu",
)

QUESTION_SIGNAL_PATTERNS = (
    re.compile(r"\bne\s+(?:var|çıkıyor|cikiyor|çıkacak|cikacak)\b", re.IGNORECASE),
    re.compile(r"\b(?:çıkan|cikan|çıkacak|cikacak)\b", re.IGNORECASE),
)

DATE_ISO_RE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
DATE_DMY_RE = re.compile(r"\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})\b")


@dataclass(frozen=True)
class FoodMenuRequest:
    """Yemek menüsü sorgusundan çıkarılan tarih/range bilgisi."""

    is_food_menu: bool
    is_range: bool = False
    target_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    label: str = "today"


def _normalize_query(query: str) -> str:
    return " ".join((query or "").casefold().replace("\xa0", " ").split())


def is_food_menu_query(query: str) -> bool:
    """Kullanıcı mesajı yemekhane yemek menüsü sorgusu mu?"""
    q = _normalize_query(query)
    if not q:
        return False
    if any(phrase in q for phrase in MENU_EXCLUSION_PHRASES):
        return False
    if any(pattern.search(q) for pattern in NON_MENU_INFO_PATTERNS):
        return False
    if any(phrase in q for phrase in FOOD_MENU_PHRASES):
        return True

    has_food_word = "yemek" in q or "yemekte" in q or "yemekhan" in q
    has_menu_word = "menü" in q or "menu" in q or "liste" in q
    has_time_word = any(
        token in q
        for token in [
            "bugün",
            "bugun",
            "yarın",
            "yarin",
            "dün",
            "dun",
            "hafta",
            *TURKISH_WEEKDAYS.keys(),
        ]
    )
    has_question_signal = any(pattern.search(q) for pattern in QUESTION_SIGNAL_PATTERNS)

    if has_food_word and (has_menu_word or has_time_word or has_question_signal):
        return True
    if has_menu_word and has_time_word and ("yemek" in q or "yemekhane" in q):
        return True
    return False


def _parse_explicit_date(query: str) -> date | None:
    for pattern in [DATE_ISO_RE, DATE_DMY_RE]:
        match = pattern.search(query)
        if not match:
            continue
        parts = match.groupdict()
        try:
            return date(int(parts["year"]), int(parts["month"]), int(parts["day"]))
        except ValueError:
            return None
    return None


def _next_weekday(base_date: date, weekday: int) -> date:
    days_ahead = (weekday - base_date.weekday()) % 7
    return base_date + timedelta(days=days_ahead)


def extract_food_menu_request(query: str, base_date: date) -> FoodMenuRequest:
    """Mesajdan yemek menüsü tarihi veya tarih aralığı çıkarır."""
    q = _normalize_query(query)
    if not is_food_menu_query(q):
        return FoodMenuRequest(is_food_menu=False)

    if "bu hafta" in q or "haftalık" in q or "haftalik" in q:
        week_start = base_date - timedelta(days=base_date.weekday())
        return FoodMenuRequest(
            is_food_menu=True,
            is_range=True,
            start_date=week_start,
            end_date=week_start + timedelta(days=6),
            label="this_week",
        )

    if "hafta sonu" in q:
        week_start = base_date - timedelta(days=base_date.weekday())
        return FoodMenuRequest(
            is_food_menu=True,
            is_range=True,
            start_date=week_start + timedelta(days=5),
            end_date=week_start + timedelta(days=6),
            label="weekend",
        )

    explicit_date = _parse_explicit_date(q)
    if explicit_date:
        return FoodMenuRequest(is_food_menu=True, target_date=explicit_date, label="explicit")

    if "yarın" in q or "yarin" in q:
        return FoodMenuRequest(is_food_menu=True, target_date=base_date + timedelta(days=1), label="tomorrow")
    if "dün" in q or "dun" in q:
        return FoodMenuRequest(is_food_menu=True, target_date=base_date - timedelta(days=1), label="yesterday")
    if "bugün" in q or "bugun" in q or "bugünkü" in q:
        return FoodMenuRequest(is_food_menu=True, target_date=base_date, label="today")

    for day_name, weekday in TURKISH_WEEKDAYS.items():
        if day_name in q:
            return FoodMenuRequest(
                is_food_menu=True,
                target_date=_next_weekday(base_date, weekday),
                label="weekday",
            )

    return FoodMenuRequest(is_food_menu=True, target_date=base_date, label="today")


def display_date(menu_date: date) -> str:
    """Kullanıcıya gösterilecek kısa tarih üretir."""
    weekday = ISTANBUL_WEEKDAY_NAMES[menu_date.weekday()]
    return f"{menu_date.strftime('%d.%m.%Y')} {weekday}"
