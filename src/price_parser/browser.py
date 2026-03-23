from __future__ import annotations

import contextlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, TimeoutError, async_playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(
        self,
        timeout_seconds: int,
        headless: bool = True,
        debug_capture_enabled: bool = False,
        debug_capture_dir: Path | None = None,
        debug_capture_html: bool = True,
        debug_capture_screenshot: bool = True,
        proxy_servers: tuple[str, ...] = (),
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
        self._proxy_servers = list(proxy_servers)
        if proxy_server and proxy_server not in self._proxy_servers:
            self._proxy_servers.append(proxy_server)
        self._proxy_username = proxy_username
        self._proxy_password = proxy_password
        self._proxy_index = 0
        self._active_proxy_server: str | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._browser is not None:
            return
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        candidates = self._proxy_servers or [None]
        last_error: Exception | None = None
        for offset in range(len(candidates)):
            server = candidates[(self._proxy_index + offset) % len(candidates)]
            try:
                self._browser = await self._launch_browser(server)
                self._active_proxy_server = server
                self._proxy_index = (self._proxy_index + offset) % len(candidates)
                if server:
                    logger.info("Browser started with proxy %s", server)
                else:
                    logger.info("Browser started without proxy")
                return
            except Exception as exc:
                last_error = exc
                if server:
                    logger.warning("Failed to start browser with proxy %s: %s", server, exc)
                else:
                    logger.warning("Failed to start browser without proxy: %s", exc)

        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        assert last_error is not None
        raise last_error

    async def _launch_browser(self, proxy_server: str | None) -> Browser:
        assert self._playwright is not None
        launch_options: dict = {
            "headless": self._headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        if proxy_server:
            proxy = {"server": proxy_server}
            if self._proxy_username:
                proxy["username"] = self._proxy_username
            if self._proxy_password:
                proxy["password"] = self._proxy_password
            launch_options["proxy"] = proxy
        return await self._playwright.chromium.launch(**launch_options)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._active_proxy_server = None

    async def rotate_proxy(self) -> None:
        if not self._proxy_servers:
            return
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        self._proxy_index = (self._proxy_index + 1) % len(self._proxy_servers)
        self._active_proxy_server = None
        await self.start()

    async def load_page(self, url: str) -> tuple[Page, BrowserContext]:
        attempts = len(self._proxy_servers) if self._proxy_servers else 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            await self.start()
            assert self._browser is not None
            context = await self._browser.new_context(
                locale="ru-RU",
                viewport={"width": 1440, "height": 2200},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(self._timeout_ms)
            try:
                await page.goto(url, wait_until="domcontentloaded")
                with contextlib.suppress(TimeoutError):
                    await page.wait_for_load_state("networkidle", timeout=self._timeout_ms)
                await page.wait_for_timeout(1200)
                return page, context
            except Exception as exc:
                last_error = exc
                with contextlib.suppress(Exception):
                    await context.close()
                if self._proxy_servers and attempt + 1 < attempts:
                    logger.warning(
                        "Page load failed via proxy %s, rotating to next proxy: %s",
                        self._active_proxy_server,
                        exc,
                    )
                    await self.rotate_proxy()
                    continue
                raise
        assert last_error is not None
        raise last_error

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
            "proxy_server": self._active_proxy_server,
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
        normalized = re.sub(r"[^a-zA-Z0-9?-??-?_-]+", "_", value.strip())
        return normalized.strip("_").lower() or "debug"
