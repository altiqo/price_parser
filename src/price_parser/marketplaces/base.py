from __future__ import annotations

from abc import ABC, abstractmethod

from playwright.async_api import Page

from ..browser import BrowserManager
from ..models import Marketplace, Offer


class MarketplaceError(RuntimeError):
    """Raised when marketplace response cannot be parsed."""


class MarketplaceClient(ABC):
    marketplace: Marketplace

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
