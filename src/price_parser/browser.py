from __future__ import annotations

import contextlib

from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError, async_playwright


class BrowserManager:
    def __init__(self, timeout_seconds: int, headless: bool = True) -> None:
        self._timeout_ms = timeout_seconds * 1000
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ],
        )

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def load_page(self, url: str) -> tuple[Page, BrowserContext]:
        await self.start()
        assert self._browser is not None
        context = await self._browser.new_context(
            locale='ru-RU',
            viewport={'width': 1440, 'height': 2200},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/123.0.0.0 Safari/537.36'
            ),
        )
        page = await context.new_page()
        page.set_default_timeout(self._timeout_ms)
        await page.goto(url, wait_until='domcontentloaded')
        with contextlib.suppress(TimeoutError):
            await page.wait_for_load_state('networkidle', timeout=self._timeout_ms)
        await page.wait_for_timeout(1200)
        return page, context

    async def close_context(self, context: BrowserContext) -> None:
        await context.close()
