"""
Yemekhane menüsü özelliği birim testleri.
Canlı DB veya dış site bağımlılığı yoktur.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.food_menu_intent import extract_food_menu_request, is_food_menu_query
from app.services.food_menu_service import FoodMenuService
from scrapers.food_menu_scraper import (
    ALLOWED_MENU_URL,
    FoodMenuScrapeResult,
    FoodMenuScraper,
    ParsedFoodMenu,
)


BASE_DATE = date(2026, 5, 28)  # Perşembe


class FakeRepository:
    def __init__(self, records: dict[str, dict] | None = None):
        self.records = records or {}
        self.find_calls = 0
        self.range_calls = 0
        self.upsert_calls = 0

    def find_menu_by_date(self, menu_date):
        self.find_calls += 1
        return self.records.get(_date_key(menu_date))

    def get_menus_by_date_range(self, start_date, end_date):
        self.range_calls += 1
        start = _as_date(start_date)
        end = _as_date(end_date)
        return [
            self.records[key]
            for key in sorted(self.records)
            if start <= date.fromisoformat(key) <= end
        ]

    def upsert_menu(self, menu_date, menu_items, source_url, raw_data=None, raw_text=None):
        self.upsert_calls += 1
        key = _date_key(menu_date)
        self.records[key] = {
            "id": key,
            "date": key,
            "menu_items": list(menu_items),
            "source_url": source_url,
            "raw_text": raw_text,
            "raw_data": raw_data or {},
        }
        return self.records[key]


class FakeScraper:
    def __init__(self, result: FoodMenuScrapeResult):
        self.result = result
        self.calls = 0

    def fetch_menus(self):
        self.calls += 1
        return self.result


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _date_key(value) -> str:
    return _as_date(value).isoformat()


def _record(menu_date: date, items: list[str] | None = None) -> dict:
    return {
        "id": menu_date.isoformat(),
        "date": menu_date.isoformat(),
        "menu_items": items or ["Mercimek Çorba", "Tavuk Sote", "Pirinç Pilavı", "Ayran"],
        "source_url": ALLOWED_MENU_URL,
        "raw_text": "",
        "raw_data": {},
    }


def _parsed(menu_date: date, items: list[str] | None = None) -> ParsedFoodMenu:
    return ParsedFoodMenu(
        date=menu_date,
        menu_items=items or ["Ezogelin Çorbası", "Etli Nohut", "Bulgur Pilavı", "Yoğurt"],
        raw_text="raw",
        raw_data={"test": True},
    )


class FoodMenuIntentTests(unittest.TestCase):
    def test_tarih_cikarimi_bugun_yarin_acik_tarih_hafta_gunu(self):
        today = extract_food_menu_request("Bugün yemekte ne var?", BASE_DATE)
        tomorrow = extract_food_menu_request("Yarın yemekte ne var?", BASE_DATE)
        explicit = extract_food_menu_request("2026-06-01 yemek listesi ne?", BASE_DATE)
        explicit_dmy = extract_food_menu_request("01.06.2026 yemekte ne var?", BASE_DATE)
        monday = extract_food_menu_request("Pazartesi yemekte ne var?", BASE_DATE)
        week = extract_food_menu_request("Bu hafta yemek listesi ne?", BASE_DATE)

        self.assertEqual(today.target_date, BASE_DATE)
        self.assertEqual(tomorrow.target_date, BASE_DATE + timedelta(days=1))
        self.assertEqual(explicit.target_date, date(2026, 6, 1))
        self.assertEqual(explicit_dmy.target_date, date(2026, 6, 1))
        self.assertEqual(monday.target_date, date(2026, 6, 1))
        self.assertTrue(week.is_range)
        self.assertEqual(week.start_date, date(2026, 5, 25))
        self.assertEqual(week.end_date, date(2026, 5, 31))

    def test_yemek_tarifi_yemekhane_intenti_sayilmaz(self):
        self.assertFalse(is_food_menu_query("Bana yemek tarifi verir misin?"))
        self.assertFalse(is_food_menu_query("Yemekhane kuralları nelerdir?"))
        self.assertTrue(is_food_menu_query("Öğrenci yemekhanesinde bugün ne çıkıyor?"))


class FoodMenuServiceTests(unittest.TestCase):
    def test_db_kaydi_varsa_scraper_calismaz(self):
        repo = FakeRepository({BASE_DATE.isoformat(): _record(BASE_DATE)})
        scraper = FakeScraper(FoodMenuScrapeResult(success=True, menus=[_parsed(BASE_DATE)]))
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        result = service.get_menu_by_date(BASE_DATE)

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "database")
        self.assertEqual(scraper.calls, 0)

    def test_db_kaydi_yoksa_scraper_calisir_ve_upsert_yapilir(self):
        target_date = BASE_DATE + timedelta(days=1)
        repo = FakeRepository()
        scraper = FakeScraper(FoodMenuScrapeResult(success=True, menus=[_parsed(target_date)]))
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        result = service.get_menu_by_date(target_date)

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "scraper")
        self.assertEqual(scraper.calls, 1)
        self.assertEqual(repo.upsert_calls, 1)
        self.assertIn(target_date.isoformat(), repo.records)

    def test_ayni_tarih_icin_duplicate_olusturulmaz(self):
        repo = FakeRepository()
        scraper = FakeScraper(FoodMenuScrapeResult(success=True, menus=[_parsed(BASE_DATE)]))
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        service.get_menu_by_date(BASE_DATE)
        service.get_menu_by_date(BASE_DATE)

        self.assertEqual(len(repo.records), 1)
        self.assertEqual(repo.upsert_calls, 1)

    def test_menu_bulunamazsa_fallback_response_doner(self):
        repo = FakeRepository()
        scraper = FakeScraper(
            FoodMenuScrapeResult(success=True, menus=[_parsed(BASE_DATE + timedelta(days=5))])
        )
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        result = service.get_menu_by_date(BASE_DATE)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "not_found")
        self.assertIn("bulunamadı", result["message"])

    def test_site_erisim_hatasinda_chat_cokmez(self):
        repo = FakeRepository()
        scraper = FakeScraper(FoodMenuScrapeResult(success=False, error="timeout"))
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        result = service.answer_chat_query("Bugün yemekte ne var?")

        self.assertIsNotNone(result)
        self.assertIn("şu anda ulaşılamıyor", result["response"])

    def test_cache_hit_db_ve_scraper_yukunu_azaltir(self):
        repo = FakeRepository({BASE_DATE.isoformat(): _record(BASE_DATE)})
        scraper = FakeScraper(FoodMenuScrapeResult(success=True, menus=[_parsed(BASE_DATE)]))
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        service.get_menu_by_date(BASE_DATE)
        service.get_menu_by_date(BASE_DATE)

        self.assertEqual(repo.find_calls, 1)
        self.assertEqual(scraper.calls, 0)

    def test_range_sorgusu_scraperi_bir_kez_cagirir(self):
        repo = FakeRepository()
        scraper = FakeScraper(
            FoodMenuScrapeResult(
                success=True,
                menus=[
                    _parsed(BASE_DATE),
                    _parsed(BASE_DATE + timedelta(days=1)),
                ],
            )
        )
        service = FoodMenuService(repo, scraper, now_provider=lambda: BASE_DATE)

        result = service.get_menus_by_date_range(BASE_DATE, BASE_DATE + timedelta(days=2))

        self.assertTrue(result["success"])
        self.assertEqual(scraper.calls, 1)
        self.assertEqual(repo.upsert_calls, 2)
        self.assertEqual(len(result["menus"]), 2)


class FoodMenuScraperTests(unittest.TestCase):
    def test_scraper_card_html_parse_eder_ve_gereksiz_metinleri_temizler(self):
        html = """
        <html><body>
          <div class="card">
            <div class="card-title">17.05.2026</div>
            <div class="card-content">
              <div class="col">Image</div>
              <div class="col">Ezogelin Çorba - 137 Kkal</div>
              <div class="col">Tavuk Sote</div>
              <div class="col">Pirinç Pilavı</div>
              <div class="col">Ayran</div>
            </div>
          </div>
        </body></html>
        """
        menus = FoodMenuScraper(retry_delay_seconds=0).parse_menu_html(html)

        self.assertEqual(len(menus), 1)
        self.assertEqual(menus[0].date, date(2026, 5, 17))
        self.assertEqual(menus[0].menu_items, ["Ezogelin Çorba", "Tavuk Sote", "Pirinç Pilavı", "Ayran"])

    def test_scraper_sadece_izinli_url_ile_istek_atabilir(self):
        class FakeResponse:
            url = ALLOWED_MENU_URL
            text = "<html></html>"
            encoding = "utf-8"
            apparent_encoding = "utf-8"

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.headers = {}
                self.calls = []

            def get(self, url, timeout, allow_redirects):
                self.calls.append((url, timeout, allow_redirects))
                return FakeResponse()

        session = FakeSession()
        scraper = FoodMenuScraper(session=session, retry_delay_seconds=0)
        scraper.fetch_menu_page()

        self.assertEqual(session.calls, [(ALLOWED_MENU_URL, 10, True)])

    def test_scraper_izinli_path_disina_redirect_kabul_etmez(self):
        with self.assertRaises(ValueError):
            FoodMenuScraper._validate_final_url("https://www.gibtu.edu.tr/siteharitasi")


class FoodMenuApiAndSchemaTests(unittest.TestCase):
    def test_food_menus_sql_unique_date_icerir(self):
        backend_init = Path(__file__).resolve().parent / "database" / "init_db.py"
        root_init = Path(__file__).resolve().parents[1] / "database" / "init.sql"

        backend_sql = backend_init.read_text(encoding="utf-8")
        root_sql = root_init.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS food_menus", backend_sql)
        self.assertIn("date DATE NOT NULL UNIQUE", backend_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS food_menus", root_sql)
        self.assertIn("date DATE NOT NULL UNIQUE", root_sql)

    def test_api_range_parametreleri_birlikte_gonderilmeli(self):
        from fastapi.testclient import TestClient
        from main import create_app

        client = TestClient(create_app())
        response = client.get("/api/yemek-menu?startDate=2026-05-28")

        self.assertEqual(response.status_code, 400)
        self.assertIn("startDate ve endDate", response.json()["detail"])

    def test_rag_pipeline_yemek_sorusunda_llm_oncesi_fast_path_kullanir(self):
        from app.services.rag_service import RagService

        class FakeFoodMenuService:
            def answer_chat_query(self, question):
                return {"response": "Bugünkü yemek menüsü:\n\n- Çorba", "sources": []}

        with patch("app.services.rag_service.get_food_menu_service", return_value=FakeFoodMenuService()):
            service = RagService()
            result = service.query("Bugün yemekte ne var?")

        self.assertIn("Bugünkü yemek menüsü", result["response"])


if __name__ == "__main__":
    unittest.main()
