"""
UniChat Backend — Yemekhane Menü Servisi
DB-first yemek menüsü akışını, cache'i ve chat/API yanıt formatını yönetir.
"""

from __future__ import annotations

import copy
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.repositories.food_menu_repository import FoodMenuRepository
from app.services.food_menu_intent import (
    FoodMenuRequest,
    display_date,
    extract_food_menu_request,
)
from scrapers.food_menu_scraper import (
    ALLOWED_MENU_URL,
    FoodMenuScrapeResult,
    FoodMenuScraper,
    ParsedFoodMenu,
)

logger = logging.getLogger(__name__)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
DEFAULT_CACHE_TTL_SECONDS = 2 * 60 * 60


def today_in_istanbul() -> date:
    """Europe/Istanbul saat dilimine göre bugünün tarihini döndürür."""
    return datetime.now(ISTANBUL_TZ).date()


def _parse_date_input(value: date | datetime | str | None) -> date:
    if value is None:
        return today_in_istanbul()
    if isinstance(value, datetime):
        return value.astimezone(ISTANBUL_TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _date_range(start_date: date, end_date: date) -> list[date]:
    days = (end_date - start_date).days
    if days < 0:
        raise ValueError("startDate endDate değerinden büyük olamaz.")
    return [start_date + timedelta(days=i) for i in range(days + 1)]


def _normalize_menu_items(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    normalized: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("name") or item.get("title") or item.get("text")
            if isinstance(text, str) and text.strip():
                normalized.append(text.strip())
    return normalized


class FoodMenuService:
    """Yemekhane menüsü için DB ana kaynaklı servis."""

    def __init__(
        self,
        repository: FoodMenuRepository | None = None,
        scraper: FoodMenuScraper | None = None,
        now_provider: Callable[[], date] | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ):
        self._repository = repository or FoodMenuRepository()
        self._scraper = scraper or FoodMenuScraper()
        self._now_provider = now_provider or today_in_istanbul
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def get_menu_by_date(self, menu_date: date | datetime | str | None = None) -> dict[str, Any]:
        """Tek tarih için DB-first menü sorgular."""
        normalized_date = _parse_date_input(menu_date)
        cache_key = self._cache_key(normalized_date)
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        try:
            db_record = self._repository.find_menu_by_date(normalized_date)
        except Exception as exc:
            logger.error("Yemekhane menüsü DB okuma hatası: %s", exc, exc_info=True)
            return self._system_error_response(normalized_date)

        if db_record:
            response = self._record_to_response(db_record, source="database")
            self._cache_set(cache_key, response)
            return response

        scrape_result = self._scraper.fetch_menus()
        if not scrape_result.success:
            logger.warning("Yemekhane menüsü scraper başarısız: %s", scrape_result.error)
            return self._system_error_response(normalized_date)

        target_menu = self._upsert_scraped_menus(scrape_result, normalized_date)
        if target_menu:
            response = self._parsed_menu_to_response(target_menu, source="scraper")
            self._cache_set(cache_key, response)
            return response

        return self._not_found_response(normalized_date)

    def get_menus_by_date_range(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> dict[str, Any]:
        """Tarih aralığı için menüleri DB-first sorgular; gerekirse scraper bir kez çalışır."""
        normalized_start = _parse_date_input(start_date)
        normalized_end = _parse_date_input(end_date)
        wanted_dates = _date_range(normalized_start, normalized_end)

        menus_by_date: dict[date, dict[str, Any]] = {}
        missing_dates: set[date] = set()
        for wanted_date in wanted_dates:
            cached = self._cache_get(self._cache_key(wanted_date))
            if cached and cached.get("success"):
                menus_by_date[wanted_date] = cached
            else:
                missing_dates.add(wanted_date)

        if missing_dates:
            try:
                db_records = self._repository.get_menus_by_date_range(normalized_start, normalized_end)
            except Exception as exc:
                logger.error("Yemekhane menüsü DB aralık okuma hatası: %s", exc, exc_info=True)
                return self._range_system_error_response(normalized_start, normalized_end)

            for record in db_records:
                record_date = _parse_date_input(record["date"])
                response = self._record_to_response(record, source="database")
                menus_by_date[record_date] = response
                self._cache_set(self._cache_key(record_date), response)
                missing_dates.discard(record_date)

        if missing_dates:
            scrape_result = self._scraper.fetch_menus()
            if not scrape_result.success:
                logger.warning("Yemekhane menüsü aralık scraper başarısız: %s", scrape_result.error)
                if menus_by_date:
                    return self._range_response(normalized_start, normalized_end, menus_by_date)
                return self._range_system_error_response(normalized_start, normalized_end)

            self._upsert_scraped_menus(scrape_result)
            for parsed_menu in scrape_result.menus:
                if parsed_menu.date in missing_dates:
                    response = self._parsed_menu_to_response(parsed_menu, source="scraper")
                    menus_by_date[parsed_menu.date] = response
                    self._cache_set(self._cache_key(parsed_menu.date), response)

        if not menus_by_date:
            return {
                "success": False,
                "startDate": normalized_start.isoformat(),
                "endDate": normalized_end.isoformat(),
                "source_url": ALLOWED_MENU_URL,
                "menus": [],
                "message": "Bu tarih aralığı için yemek menüsü bulunamadı.",
                "error_type": "not_found",
            }

        return self._range_response(normalized_start, normalized_end, menus_by_date)

    def refresh_from_source(self) -> dict[str, Any]:
        """Scheduler/CLI için canlı sayfadaki tüm menüleri DB'ye upsert eder."""
        scrape_result = self._scraper.fetch_menus()
        if not scrape_result.success:
            return {
                "success": False,
                "source_url": ALLOWED_MENU_URL,
                "menus_written": 0,
                "error": scrape_result.error,
            }

        self._upsert_scraped_menus(scrape_result)
        return {
            "success": True,
            "source_url": ALLOWED_MENU_URL,
            "menus_written": len(scrape_result.menus),
            "dates": [menu.date.isoformat() for menu in scrape_result.menus],
        }

    def answer_chat_query(self, question: str) -> dict[str, Any] | None:
        """Yemekhane menü sorusunu doğal dille yanıtlar; değilse None döner."""
        request = extract_food_menu_request(question, self._now_provider())
        if not request.is_food_menu:
            return None

        try:
            if request.is_range and request.start_date and request.end_date:
                result = self.get_menus_by_date_range(request.start_date, request.end_date)
                response_text = self._format_range_chat_response(result, request)
            else:
                result = self.get_menu_by_date(request.target_date)
                response_text = self._format_single_chat_response(result, request)
        except Exception as exc:
            logger.error("Yemekhane menüsü chat yanıt hatası: %s", exc, exc_info=True)
            response_text = "Yemek menüsüne şu anda ulaşılamıyor. Lütfen daha sonra tekrar dene."
            result = {"success": False, "source_url": ALLOWED_MENU_URL}

        return {
            "response": response_text,
            "sources": self._chat_sources(result),
        }

    def _upsert_scraped_menus(
        self,
        scrape_result: FoodMenuScrapeResult,
        target_date: date | None = None,
    ) -> ParsedFoodMenu | None:
        target_menu: ParsedFoodMenu | None = None
        for parsed_menu in scrape_result.menus:
            if parsed_menu.date == target_date:
                target_menu = parsed_menu
            try:
                record = self._repository.upsert_menu(
                    menu_date=parsed_menu.date,
                    menu_items=parsed_menu.menu_items,
                    source_url=parsed_menu.source_url,
                    raw_data=parsed_menu.raw_data,
                    raw_text=parsed_menu.raw_text,
                )
                response = self._record_to_response(record, source="database")
                self._cache_set(self._cache_key(parsed_menu.date), response)
            except Exception as exc:
                logger.error(
                    "Yemekhane menüsü upsert hatası (%s): %s",
                    parsed_menu.date.isoformat(),
                    exc,
                    exc_info=True,
                )
        return target_menu

    def _record_to_response(self, record: dict[str, Any], source: str) -> dict[str, Any]:
        menu_date = _parse_date_input(record["date"])
        items = _normalize_menu_items(record.get("menu_items"))
        if not items:
            return self._not_found_response(menu_date)
        return {
            "success": True,
            "date": menu_date.isoformat(),
            "source": source,
            "source_url": record.get("source_url") or ALLOWED_MENU_URL,
            "menu": items,
        }

    def _parsed_menu_to_response(self, menu: ParsedFoodMenu, source: str) -> dict[str, Any]:
        return {
            "success": True,
            "date": menu.date.isoformat(),
            "source": source,
            "source_url": menu.source_url,
            "menu": menu.menu_items,
        }

    @staticmethod
    def _not_found_response(menu_date: date) -> dict[str, Any]:
        return {
            "success": False,
            "date": menu_date.isoformat(),
            "message": "Bu tarih için yemek menüsü bulunamadı.",
            "error_type": "not_found",
        }

    @staticmethod
    def _system_error_response(menu_date: date) -> dict[str, Any]:
        return {
            "success": False,
            "date": menu_date.isoformat(),
            "message": "Yemek menüsüne şu anda ulaşılamıyor.",
            "error_type": "system",
        }

    @staticmethod
    def _range_system_error_response(start_date: date, end_date: date) -> dict[str, Any]:
        return {
            "success": False,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "source_url": ALLOWED_MENU_URL,
            "menus": [],
            "message": "Yemek menüsüne şu anda ulaşılamıyor.",
            "error_type": "system",
        }

    @staticmethod
    def _range_response(
        start_date: date,
        end_date: date,
        menus_by_date: dict[date, dict[str, Any]],
    ) -> dict[str, Any]:
        menus = []
        for menu_date in sorted(menus_by_date):
            item = menus_by_date[menu_date]
            menus.append(
                {
                    "date": item["date"],
                    "source": item.get("source"),
                    "source_url": item.get("source_url") or ALLOWED_MENU_URL,
                    "menu": item.get("menu") or [],
                }
            )
        return {
            "success": bool(menus),
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "source_url": ALLOWED_MENU_URL,
            "menus": menus,
        }

    def _cache_key(self, menu_date: date) -> str:
        return f"food_menu:{menu_date.isoformat()}"

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return copy.deepcopy(value)

    def _cache_set(self, key: str, value: dict[str, Any]) -> None:
        self._cache[key] = (time.time() + self._cache_ttl_seconds, copy.deepcopy(value))

    def _format_single_chat_response(self, result: dict[str, Any], request: FoodMenuRequest) -> str:
        if not result.get("success"):
            if result.get("error_type") == "system":
                return "Yemek menüsüne şu anda ulaşılamıyor. Lütfen daha sonra tekrar dene."
            return self._not_found_chat_message(result.get("date"), request)

        heading = self._single_heading(_parse_date_input(result["date"]), request)
        items = "\n".join(f"- {item}" for item in result.get("menu", []))
        return f"{heading}\n\n{items}"

    def _format_range_chat_response(self, result: dict[str, Any], request: FoodMenuRequest) -> str:
        if not result.get("success"):
            if result.get("error_type") == "system":
                return "Yemek menüsüne şu anda ulaşılamıyor. Lütfen daha sonra tekrar dene."
            if request.label == "this_week":
                return "Bu hafta için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."
            return "Bu tarih aralığı için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."

        heading = "Bu haftanın yemek menüsü:" if request.label == "this_week" else "Yemekhane yemek menüsü:"
        sections = [heading]
        for menu in result.get("menus", []):
            menu_date = _parse_date_input(menu["date"])
            items = "\n".join(f"- {item}" for item in menu.get("menu", []))
            sections.append(f"**{display_date(menu_date)}**\n{items}")
        return "\n\n".join(sections)

    @staticmethod
    def _single_heading(menu_date: date, request: FoodMenuRequest) -> str:
        if request.label == "today":
            return "Bugünkü yemek menüsü:"
        if request.label == "tomorrow":
            return "Yarınki yemek menüsü:"
        if request.label == "yesterday":
            return "Dünkü yemek menüsü:"
        if request.label == "weekday":
            return f"{display_date(menu_date)} yemek menüsü:"
        return f"{display_date(menu_date)} tarihli yemek menüsü:"

    @staticmethod
    def _not_found_chat_message(date_value: str | None, request: FoodMenuRequest) -> str:
        if request.label == "today":
            return "Bugün için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."
        if request.label == "tomorrow":
            return "Yarın için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."
        if request.label == "yesterday":
            return "Dün için yemek menüsü bulunamadı. Liste yayınlanmamış veya kaldırılmış olabilir."
        if date_value:
            menu_date = _parse_date_input(date_value)
            return f"{display_date(menu_date)} için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."
        return "Bu tarih için yemek menüsü bulunamadı. Liste henüz yayınlanmamış olabilir."

    @staticmethod
    def _chat_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
        source_url = result.get("source_url") or ALLOWED_MENU_URL
        return [
            {
                "content": "GİBTÜ yemekhane yemek listesi kaynağı.",
                "source_url": source_url,
                "source_public_url": source_url,
                "category": "yemekhane",
                "title": "GİBTÜ Yemek Listesi",
                "doc_kind": "genel",
            }
        ]


_food_menu_service: FoodMenuService | None = None


def get_food_menu_service() -> FoodMenuService:
    """Singleton yemek menüsü servisini döndürür."""
    global _food_menu_service
    if _food_menu_service is None:
        _food_menu_service = FoodMenuService()
    return _food_menu_service
