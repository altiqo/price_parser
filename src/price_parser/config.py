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


def _normalize_proxy_server(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


def _get_proxy_servers() -> tuple[str, ...]:
    values: list[str] = []

    raw_inline = os.getenv("MARKETPLACE_PROXY_SERVERS", "")
    if raw_inline.strip():
        for chunk in raw_inline.replace(",", "\n").splitlines():
            normalized = _normalize_proxy_server(chunk)
            if normalized and normalized not in values:
                values.append(normalized)

    raw_file = os.getenv("MARKETPLACE_PROXY_SERVERS_FILE", "").strip()
    if raw_file:
        path = Path(raw_file)
        if not path.exists():
            raise RuntimeError(f"MARKETPLACE_PROXY_SERVERS_FILE not found: {path}")
        for chunk in path.read_text(encoding="utf-8").splitlines():
            normalized = _normalize_proxy_server(chunk)
            if normalized and normalized not in values:
                values.append(normalized)

    legacy_single = _normalize_proxy_server(os.getenv("MARKETPLACE_PROXY_SERVER", ""))
    if legacy_single and legacy_single not in values:
        values.append(legacy_single)

    return tuple(values)


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
    debug_capture_enabled: bool = False
    debug_capture_dir: Path = Path("data/debug")
    debug_capture_html: bool = True
    debug_capture_screenshot: bool = True
    marketplace_proxy_servers: tuple[str, ...] = ()
    marketplace_proxy_server: str | None = None
    marketplace_proxy_username: str | None = None
    marketplace_proxy_password: str | None = None

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
            debug_capture_enabled=_get_bool("DEBUG_CAPTURE_ENABLED", False),
            debug_capture_dir=Path(os.getenv("DEBUG_CAPTURE_DIR", "data/debug").strip() or "data/debug"),
            debug_capture_html=_get_bool("DEBUG_CAPTURE_HTML", True),
            debug_capture_screenshot=_get_bool("DEBUG_CAPTURE_SCREENSHOT", True),
            marketplace_proxy_servers=_get_proxy_servers(),
            marketplace_proxy_server=os.getenv("MARKETPLACE_PROXY_SERVER", "").strip() or None,
            marketplace_proxy_username=os.getenv("MARKETPLACE_PROXY_USERNAME", "").strip() or None,
            marketplace_proxy_password=os.getenv("MARKETPLACE_PROXY_PASSWORD", "").strip() or None,
        )
