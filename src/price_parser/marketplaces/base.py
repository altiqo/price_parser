from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sized

from playwright.async_api import Page

from ..browser import BrowserManager
from ..models import Marketplace, Offer


class MarketplaceError(RuntimeError):
    """Raised when marketplace response cannot be parsed."""


class MarketplaceClient(ABC):
    marketplace: Marketplace
    unavailable_markers: tuple[str, ...] = (
        "нет в наличии",
        "нет в продаже",
        "нет доставки",
        "не доставляется",
        "временно нет",
        "распродан",
        "закончился",
        "уведомить о поступлении",
        "sold out",
        "out of stock",
    )

    def __init__(
        self,
        browser: BrowserManager,
        timeout_seconds: int,
        max_pages: int = 8,
    ) -> None:
        self._browser = browser
        self._timeout_seconds = timeout_seconds
        self._max_pages = max_pages

    @abstractmethod
    async def search(self, query: str) -> list[Offer]:
        raise NotImplementedError

    async def _load_page(self, url: str):
        return await self._browser.load_page(url)

    async def _capture_debug_page(
        self,
        page: Page,
        *,
        query: str,
        page_num: int,
        reason: str,
        raw_items: Sized | None = None,
        parsed_offers: int | None = None,
    ) -> None:
        await self._browser.capture_debug_artifacts(
            page,
            marketplace=self.marketplace.value,
            query=query,
            page_num=page_num,
            reason=reason,
            metadata={
                "raw_items_count": len(raw_items) if raw_items is not None else None,
                "parsed_offers_count": parsed_offers,
            },
        )

    @staticmethod
    def _clean_text(value: str | None) -> str:
        return (value or '').replace('\xa0', ' ').strip()

    @staticmethod
    async def _safe_scroll(page: Page) -> None:
        await page.evaluate(
            """
            async () => {
              window.scrollTo(0, document.body.scrollHeight * 0.6);
              await new Promise(resolve => setTimeout(resolve, 500));
              window.scrollTo(0, document.body.scrollHeight);
              await new Promise(resolve => setTimeout(resolve, 700));
            }
            """
        )

    def _looks_unavailable(self, text: str) -> bool:
        lowered = self._clean_text(text).lower()
        return any(marker in lowered for marker in self.unavailable_markers)
