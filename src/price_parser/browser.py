from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError, async_playwright


class BrowserManager:
    def __init__(
        self,
        timeout_seconds: int,
        headless: bool = True,
        debug_capture_enabled: bool = False,
        debug_capture_dir: Path | None = None,
        debug_capture_html: bool = True,
        debug_capture_screenshot: bool = True,
        proxy_server: str | None = None,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> None:
        self._timeout_ms = timeout_seconds * 1000
        self._headless = headless
        self._debug_capture_enabled = debug_capture_enabled
        self._debug_capture_dir = debug_capture_dir or Path("data/debug")
        self._debug_capture_html = debug_capture_html
        self._debug_capture_screenshot = debug_capture_screenshot
        self._proxy_server = proxy_server
        self._proxy_username = proxy_username
        self._proxy_password = proxy_password
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        launch_options: dict = {
            "headless": self._headless,
            "args": [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ],
        }
        if self._proxy_server:
            proxy = {"server": self._proxy_server}
            if self._proxy_username:
                proxy["username"] = self._proxy_username
            if self._proxy_password:
                proxy["password"] = self._proxy_password
            launch_options["proxy"] = proxy
        self._browser = await self._playwright.chromium.launch(
            **launch_options,
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

    async def capture_debug_artifacts(
        self,
        page: Page,
        *,
        marketplace: str,
        query: str,
        page_num: int,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        if not self._debug_capture_enabled:
            return

        target_dir = self._debug_capture_dir / self._slugify(marketplace)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        query_slug = self._slugify(query)[:80] or "query"
        reason_slug = self._slugify(reason)[:40] or "capture"
        basename = f"{stamp}_p{page_num:02d}_{reason_slug}_{query_slug}"

        payload = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "marketplace": marketplace,
            "query": query,
            "page_num": page_num,
            "reason": reason,
            "url": page.url,
        }
        if metadata:
            payload.update(metadata)

        metadata_path = target_dir / f"{basename}.json"
        metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self._debug_capture_html:
            html_path = target_dir / f"{basename}.html"
            html_path.write_text(await page.content(), encoding="utf-8")

        if self._debug_capture_screenshot:
            screenshot_path = target_dir / f"{basename}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", value.strip())
        return normalized.strip("_").lower() or "debug"
