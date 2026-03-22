from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    bot_token: str
    db_path: Path
    poll_interval_seconds: int = 1800
    request_timeout_seconds: int = 20
    default_currency: str = "RUB"
    wb_enabled: bool = True
    ozon_enabled: bool = True
    yandex_market_enabled: bool = True
    marketplace_max_pages: int = 8
    playwright_headless: bool = True

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
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "1800")),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            default_currency=os.getenv("DEFAULT_CURRENCY", "RUB").strip() or "RUB",
            wb_enabled=_get_bool("WB_ENABLED", True),
            ozon_enabled=_get_bool("OZON_ENABLED", True),
            yandex_market_enabled=_get_bool("YANDEX_MARKET_ENABLED", True),
            marketplace_max_pages=int(os.getenv("MARKETPLACE_MAX_PAGES", "8")),
            playwright_headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
        )
