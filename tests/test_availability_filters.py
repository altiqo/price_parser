from __future__ import annotations

import unittest
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from price_parser.marketplaces.ozon import OzonClient
from price_parser.marketplaces.wb import WildberriesClient
from price_parser.marketplaces.yandex_market import YandexMarketClient
from price_parser.models import Marketplace, Offer, TrackTarget
from price_parser.monitoring import MonitoringService


class AvailabilityFiltersTest(unittest.TestCase):
    def test_wildberries_skips_unavailable_card(self) -> None:
        client = WildberriesClient(None, 10, 1)

        offers = client._extract_cards(
            [
                {
                    "href": "https://www.wildberries.ru/catalog/123/detail.aspx",
                    "title": "Cudy WR3000S роутер",
                    "text": "Cudy WR3000S\n2 999 ₽\nНет в наличии",
                },
                {
                    "href": "https://www.wildberries.ru/catalog/456/detail.aspx",
                    "title": "Cudy WR3000S роутер",
                    "text": "Cudy WR3000S\n3 499 ₽\nДоставка завтра",
                },
            ],
            "cudy wr3000s",
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 3499.0)

    def test_ozon_skips_unavailable_item(self) -> None:
        client = OzonClient(None, 10, 1)

        offers = client._extract_items(
            [
                {
                    "href": "https://www.ozon.ru/product/cudy-wr3000s-1/",
                    "title": "Роутер Cudy WR3000S",
                    "text": "Роутер Cudy WR3000S\n4 199 ₽\nНет в наличии",
                },
                {
                    "href": "https://www.ozon.ru/product/cudy-wr3000s-2/",
                    "title": "Роутер Cudy WR3000S",
                    "text": "Роутер Cudy WR3000S\n4 990 ₽\nДоставка курьером",
                },
            ],
            "cudy wr3000s",
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 4990.0)

    def test_yandex_market_skips_unavailable_item(self) -> None:
        client = YandexMarketClient(None, 10, 1)

        offers = client._extract_items(
            [
                {
                    "href": "https://market.yandex.ru/product--cudy-wr3000s/111",
                    "title": "Роутер Cudy WR3000S",
                    "text": "Роутер Cudy WR3000S\n5 100 ₽\nНет в продаже",
                },
                {
                    "href": "https://market.yandex.ru/product--cudy-wr3000s/222",
                    "title": "Роутер Cudy WR3000S",
                    "text": "Роутер Cudy WR3000S\n5 490 ₽\nЗабрать сегодня",
                },
            ],
            "cudy wr3000s",
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 5490.0)


class MonitoringAvailabilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_monitoring_picks_next_available_offer(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.saved_snapshot: dict | None = None
                self.chat_values: dict[tuple[int, str], str] = {}

            async def save_snapshot(self, **kwargs) -> None:
                self.saved_snapshot = kwargs

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

        class FakeClient:
            marketplace = Marketplace.OZON

            async def search(self, query: str) -> list[Offer]:
                return [
                    Offer(
                        marketplace=Marketplace.OZON,
                        title="Cudy WR3000S",
                        price=3990.0,
                        currency="RUB",
                        url="https://example.com/unavailable",
                        is_available=False,
                    ),
                    Offer(
                        marketplace=Marketplace.OZON,
                        title="Cudy WR3000S",
                        price=4490.0,
                        currency="RUB",
                        url="https://example.com/available",
                        is_available=True,
                    ),
                ]

        db = FakeDb()
        service = MonitoringService(
            db=db,
            bot=None,
            marketplace_clients=[FakeClient()],
            poll_interval_seconds=60,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )
        target = TrackTarget(
            id=1,
            chat_id=1,
            query="cudy wr3000s",
            marketplaces=[Marketplace.OZON],
            created_at=datetime.now(timezone.utc),
        )

        result = await service.check_target(target)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.cheapest.price, 4490.0)
        self.assertEqual(result.cheapest.url, "https://example.com/available")
        self.assertEqual(db.saved_snapshot["price"], 4490.0)

    async def test_monitoring_notifies_only_when_price_drops_vs_previous_check(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.saved_snapshot: dict | None = None
                self.updated_prices: list[tuple[int, float]] = []
                self.targets = [
                    TrackTarget(
                        id=1,
                        chat_id=100,
                        query="cudy wr3000s",
                        marketplaces=[Marketplace.OZON],
                        created_at=datetime.now(timezone.utc),
                        last_notified_price=5000.0,
                    )
                ]
                self.chat_values: dict[tuple[int, str], str] = {}

            async def save_snapshot(self, **kwargs) -> None:
                self.saved_snapshot = kwargs

            async def list_active_targets(self) -> list[TrackTarget]:
                return self.targets

            async def update_last_notified_price(self, target_id: int, price: float) -> None:
                self.updated_prices.append((target_id, price))

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

        class FakeBot:
            def __init__(self) -> None:
                self.messages: list[dict] = []

            async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
                self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})

        class FakeClient:
            marketplace = Marketplace.OZON

            async def search(self, query: str) -> list[Offer]:
                return [
                    Offer(
                        marketplace=Marketplace.OZON,
                        title="Cudy WR3000S",
                        price=4500.0,
                        currency="RUB",
                        url="https://example.com/available",
                    )
                ]

        db = FakeDb()
        bot = FakeBot()
        service = MonitoringService(
            db=db,
            bot=bot,
            marketplace_clients=[FakeClient()],
            poll_interval_seconds=3600,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )

        await service._run_iteration()

        self.assertEqual(db.updated_prices, [(1, 4500.0)])
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("Новая минимальная цена", bot.messages[0]["text"])
        self.assertIn("500.00", bot.messages[0]["text"])

    async def test_monitoring_updates_baseline_without_notification_when_price_grows(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.saved_snapshot: dict | None = None
                self.updated_prices: list[tuple[int, float]] = []
                self.targets = [
                    TrackTarget(
                        id=1,
                        chat_id=100,
                        query="cudy wr3000s",
                        marketplaces=[Marketplace.OZON],
                        created_at=datetime.now(timezone.utc),
                        last_notified_price=4000.0,
                    )
                ]
                self.chat_values: dict[tuple[int, str], str] = {}

            async def save_snapshot(self, **kwargs) -> None:
                self.saved_snapshot = kwargs

            async def list_active_targets(self) -> list[TrackTarget]:
                return self.targets

            async def update_last_notified_price(self, target_id: int, price: float) -> None:
                self.updated_prices.append((target_id, price))

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

        class FakeBot:
            def __init__(self) -> None:
                self.messages: list[dict] = []

            async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
                self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})

        class FakeClient:
            marketplace = Marketplace.OZON

            async def search(self, query: str) -> list[Offer]:
                return [
                    Offer(
                        marketplace=Marketplace.OZON,
                        title="Cudy WR3000S",
                        price=4500.0,
                        currency="RUB",
                        url="https://example.com/available",
                    )
                ]

        db = FakeDb()
        bot = FakeBot()
        service = MonitoringService(
            db=db,
            bot=bot,
            marketplace_clients=[FakeClient()],
            poll_interval_seconds=3600,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )

        await service._run_iteration()

        self.assertEqual(db.updated_prices, [(1, 4500.0)])
        self.assertEqual(bot.messages, [])

    async def test_daily_report_contains_current_prices(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.saved_snapshot: dict | None = None
                self.updated_prices: list[tuple[int, float]] = []
                self.chat_values: dict[tuple[int, str], str] = {}

            async def save_snapshot(self, **kwargs) -> None:
                self.saved_snapshot = kwargs

            async def update_last_notified_price(self, target_id: int, price: float) -> None:
                self.updated_prices.append((target_id, price))

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

        class FakeClient:
            marketplace = Marketplace.OZON

            async def search(self, query: str) -> list[Offer]:
                return [
                    Offer(
                        marketplace=Marketplace.OZON,
                        title="Cudy WR3000S",
                        price=4300.0,
                        currency="RUB",
                        url="https://example.com/available",
                    )
                ]

        db = FakeDb()
        service = MonitoringService(
            db=db,
            bot=None,
            marketplace_clients=[FakeClient()],
            poll_interval_seconds=3600,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )
        target = TrackTarget(
            id=1,
            chat_id=1,
            query="cudy wr3000s",
            marketplaces=[Marketplace.OZON],
            created_at=datetime.now(timezone.utc),
            last_notified_price=4500.0,
        )

        report = await service._build_daily_report([target])

        self.assertIn("Ежедневная сводка", report)
        self.assertIn("цена снизилась", report)
        self.assertIn("https://example.com/available", report)
        self.assertEqual(db.updated_prices, [(1, 4300.0)])

    async def test_load_schedule_settings_uses_persisted_values(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.values = {
                    "schedule.poll_interval_seconds": "14400",
                    "schedule.daily_report_enabled": "false",
                    "schedule.daily_report_time": "10:45",
                }
                self.chat_values: dict[tuple[int, str], str] = {}

            async def get_app_setting(self, key: str) -> str | None:
                return self.values.get(key)

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

        db = FakeDb()
        service = MonitoringService(
            db=db,
            bot=None,
            marketplace_clients=[],
            poll_interval_seconds=3600,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )

        await service.load_schedule_settings()
        schedule = await service.get_schedule(1)

        self.assertEqual(schedule.poll_interval_seconds, 14400)
        self.assertFalse(schedule.daily_report_enabled)
        self.assertEqual(schedule.daily_report_time, time(hour=10, minute=45))

    async def test_schedule_is_isolated_per_chat(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.app_values: dict[str, str] = {}
                self.chat_values: dict[tuple[int, str], str] = {}

            async def get_app_setting(self, key: str) -> str | None:
                return self.app_values.get(key)

            async def get_chat_setting(self, chat_id: int, key: str) -> str | None:
                return self.chat_values.get((chat_id, key))

            async def set_chat_setting(self, chat_id: int, key: str, value: str) -> None:
                self.chat_values[(chat_id, key)] = value

        db = FakeDb()
        service = MonitoringService(
            db=db,
            bot=None,
            marketplace_clients=[],
            poll_interval_seconds=10800,
            daily_report_enabled=True,
            daily_report_time=time(hour=9, minute=0),
            schedule_timezone=ZoneInfo("Europe/Moscow"),
        )

        await service.set_poll_interval_seconds(100, 14400)
        await service.set_daily_report_enabled(100, False)
        schedule_chat_100 = await service.get_schedule(100)
        schedule_chat_200 = await service.get_schedule(200)

        self.assertEqual(schedule_chat_100.poll_interval_seconds, 14400)
        self.assertFalse(schedule_chat_100.daily_report_enabled)
        self.assertEqual(schedule_chat_200.poll_interval_seconds, 10800)
        self.assertTrue(schedule_chat_200.daily_report_enabled)


if __name__ == "__main__":
    unittest.main()
