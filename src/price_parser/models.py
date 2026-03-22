from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"
    YANDEX_MARKET = "yandex_market"


@dataclass(slots=True)
class Offer:
    marketplace: Marketplace
    title: str
    price: float
    currency: str
    url: str
    seller: str | None = None
    image_url: str | None = None
    is_available: bool = True


@dataclass(slots=True)
class CheckResult:
    cheapest: Offer
    per_marketplace: dict[Marketplace, Offer]
    errors: dict[Marketplace, str]


@dataclass(slots=True)
class TrackTarget:
    id: int
    chat_id: int
    query: str
    marketplaces: list[Marketplace]
    created_at: datetime
    last_notified_price: float | None = None
    is_active: bool = True


@dataclass(slots=True)
class PriceSnapshot:
    id: int
    target_id: int
    price: float
    currency: str
    title: str
    url: str
    marketplace: Marketplace
    seller: str | None
    captured_at: datetime
