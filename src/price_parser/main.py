from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot

from .bot import build_dispatcher
from .browser import BrowserManager
from .charting import ChartService
from .config import Settings
from .db import Database
from .marketplaces import OzonClient, WildberriesClient, YandexMarketClient
from .monitoring import MonitoringService


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.load()
    db = Database(settings.db_path)
    await db.init()

    bot = Bot(settings.bot_token)
    browser = BrowserManager(
        timeout_seconds=settings.request_timeout_seconds,
        headless=settings.playwright_headless,
        debug_capture_enabled=settings.debug_capture_enabled,
        debug_capture_dir=settings.debug_capture_dir,
        debug_capture_html=settings.debug_capture_html,
        debug_capture_screenshot=settings.debug_capture_screenshot,
        proxy_servers=settings.marketplace_proxy_servers,
        proxy_server=settings.marketplace_proxy_server,
        proxy_username=settings.marketplace_proxy_username,
        proxy_password=settings.marketplace_proxy_password,
    )
    charts_dir = Path("data/charts")
    clients = []
    if settings.wb_enabled:
        clients.append(WildberriesClient(browser, settings.request_timeout_seconds, settings.marketplace_max_pages))
    if settings.ozon_enabled:
        clients.append(OzonClient(browser, settings.request_timeout_seconds, settings.marketplace_max_pages))
    if settings.yandex_market_enabled:
        clients.append(YandexMarketClient(browser, settings.request_timeout_seconds, settings.marketplace_max_pages))

    monitoring = MonitoringService(
        db=db,
        bot=bot,
        marketplace_clients=clients,
        poll_interval_seconds=settings.poll_interval_seconds,
        daily_report_enabled=settings.daily_report_enabled,
        daily_report_time=settings.daily_report_time,
        schedule_timezone=settings.schedule_timezone,
    )
    await monitoring.load_schedule_settings()
    dp = build_dispatcher(
        db=db,
        monitoring=monitoring,
        chart_service=ChartService(charts_dir),
        charts_dir=charts_dir,
    )

    monitoring.start()
    try:
        await dp.start_polling(bot)
    finally:
        await monitoring.stop()
        await browser.stop()
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
