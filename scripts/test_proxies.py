from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from price_parser.browser import BrowserManager


async def probe_proxy(
    proxy_server: str,
    *,
    url: str,
    timeout_seconds: int,
    headless: bool,
    proxy_username: str | None,
    proxy_password: str | None,
) -> tuple[bool, float, str]:
    browser = BrowserManager(
        timeout_seconds=timeout_seconds,
        headless=headless,
        proxy_servers=(proxy_server,),
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )
    started = time.perf_counter()
    try:
        page, context = await browser.load_page(url)
        try:
            elapsed = time.perf_counter() - started
            final_url = page.url
            title = (await page.title()).strip()
            details = f"{elapsed:.1f}s | {final_url}"
            if title:
                details += f" | {title}"
            return True, elapsed, details
        finally:
            await browser.close_context(context)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return False, elapsed, f"{type(exc).__name__}: {exc}"
    finally:
        await browser.stop()


def load_proxy_list(proxy_file: Path | None) -> list[str]:
    values: list[str] = []

    if proxy_file is not None:
        for line in proxy_file.read_text(encoding="utf-8").splitlines():
            proxy = line.strip()
            if not proxy:
                continue
            if "://" not in proxy:
                proxy = f"http://{proxy}"
            if proxy not in values:
                values.append(proxy)
        return values

    raw_inline = os.getenv("MARKETPLACE_PROXY_SERVERS", "")
    if raw_inline.strip():
        for chunk in raw_inline.replace(",", "\n").splitlines():
            proxy = chunk.strip()
            if not proxy:
                continue
            if "://" not in proxy:
                proxy = f"http://{proxy}"
            if proxy not in values:
                values.append(proxy)

    raw_single = os.getenv("MARKETPLACE_PROXY_SERVER", "").strip()
    if raw_single:
        if "://" not in raw_single:
            raw_single = f"http://{raw_single}"
        if raw_single not in values:
            values.append(raw_single)

    return values


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test marketplace proxies with Playwright")
    parser.add_argument("--file", type=Path, help="Path to proxy list file")
    parser.add_argument("--url", default="https://www.wildberries.ru/catalog/0/search.aspx?search=cudy%20wr3000s")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Only test first N proxies")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode")
    args = parser.parse_args()

    load_dotenv()
    proxies = load_proxy_list(args.file)
    if args.limit > 0:
        proxies = proxies[: args.limit]

    if not proxies:
        raise SystemExit("No proxies found. Configure MARKETPLACE_PROXY_SERVERS_FILE or pass --file.")

    print(f"Testing {len(proxies)} proxies against {args.url}")
    print()

    ok_count = 0
    fail_count = 0
    proxy_username = os.getenv("MARKETPLACE_PROXY_USERNAME", "").strip() or None
    proxy_password = os.getenv("MARKETPLACE_PROXY_PASSWORD", "").strip() or None

    for index, proxy in enumerate(proxies, start=1):
        ok, elapsed, details = await probe_proxy(
            proxy,
            url=args.url,
            timeout_seconds=args.timeout,
            headless=not args.headful,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
        )
        status = "OK  " if ok else "FAIL"
        print(f"{index:03d}. {status} {proxy} | {details}")
        if ok:
            ok_count += 1
        else:
            fail_count += 1

    print()
    print(f"Done. OK: {ok_count}, FAIL: {fail_count}")


if __name__ == "__main__":
    asyncio.run(main())
