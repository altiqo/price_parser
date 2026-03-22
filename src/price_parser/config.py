from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_poll_interval_seconds(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    value = int(raw)
    if value < 3600:
        raise RuntimeError(f"{name} must be at least 3600 seconds")
    return value


def _get_time(name: str, default: str) -> time:
    raw = os.getenv(name, default).strip()
    try:
        hour_text, minute_text = raw.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be in HH:MM format") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RuntimeError(f"{name} must be in HH:MM format")
    return time(hour=hour, minute=minute)


def _get_timezone(name: str, default: str) -> ZoneInfo:
    raw = os.getenv(name, default).strip() or default
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"{name} contains an unknown timezone: {raw}") from exc


@dataclass(slots=True)
class Settings:
    bot_token: str
    db_path: Path
    poll_interval_seconds: int = 10800
    request_timeout_seconds: int = 20
    default_currency: str = "RUB"
    wb_enabled: bool = True
    ozon_enabled: bool = True
    yandex_market_enabled: bool = True
    marketplace_max_pages: int = 8
    playwright_headless: bool = True
    daily_report_enabled: bool = True
    daily_report_time: time = time(hour=9, minute=0)
    schedule_timezone: ZoneInfo = ZoneInfo("Europe/Moscow")

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is required")

        db_path = Path(os.getenv("DB_PATH", "data/price_parser.db"))
        return cls(
            bot_token=bot_token,
            db_path=db_path,
            poll_interval_seconds=_get_poll_interval_seconds("POLL_INTERVAL_SECONDS", 10800),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            default_currency=os.getenv("DEFAULT_CURRENCY", "RUB").strip() or "RUB",
            wb_enabled=_get_bool("WB_ENABLED", True),
            ozon_enabled=_get_bool("OZON_ENABLED", True),
            yandex_market_enabled=_get_bool("YANDEX_MARKET_ENABLED", True),
            marketplace_max_pages=int(os.getenv("MARKETPLACE_MAX_PAGES", "8")),
            playwright_headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
            daily_report_enabled=_get_bool("DAILY_REPORT_ENABLED", True),
            daily_report_time=_get_time("DAILY_REPORT_TIME", "09:00"),
            schedule_timezone=_get_timezone("SCHEDULE_TIMEZONE", "Europe/Moscow"),
        )
