from __future__ import annotations

import re
from urllib.parse import quote_plus

from .base import MarketplaceClient, MarketplaceError
from ..models import Marketplace, Offer
from ..query_profiles import build_page_url, clean_marketplace_url, deduplicate_offers, get_overridden_url, title_matches_query

_PRICE_RE = re.compile(r'(\d[\d\s\u2009]{2,12})\s?[₽р]')


class OzonClient(MarketplaceClient):
    marketplace = Marketplace.OZON

    async def search(self, query: str) -> list[Offer]:
        base_url = get_overridden_url(query, self.marketplace.value) or f"https://www.ozon.ru/search/?text={quote_plus(query)}"
        offers: list[Offer] = []
        for page_num in range(1, self._max_pages + 1):
            url = build_page_url(base_url, page_num)
            page, context = await self._load_page(url)
            try:
                await self._safe_scroll(page)
                if 'captcha' in page.url.lower() or '/api/composer-api.bx/page/json/' in page.url.lower():
                    raise MarketplaceError('Ozon blocked the browser session')
                items = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll("a[href*='/product/']"))
                      .filter((anchor) => anchor.offsetParent !== null)
                      .map((anchor) => {
                        const container = anchor.closest('article, div, li') || anchor.parentElement || anchor;
                        return {
                          href: anchor.href,
                          title: (anchor.getAttribute('title') || anchor.textContent || '').trim(),
                          text: (container.innerText || '').trim(),
                        };
                      })
                    """
                )
            finally:
                await self._browser.close_context(context)

            page_offers = self._extract_items(items, query)
            if not page_offers:
                break
            offers.extend(page_offers)

        offers = deduplicate_offers(offers)
        if not offers:
            raise MarketplaceError('Ozon returned no parsable offers')
        return offers

    def _extract_items(self, items: list[dict], query: str) -> list[Offer]:
        grouped = self._group_items(items)
        offers: list[Offer] = []
        for href, payload in grouped.items():
            title = payload['title']
            text = payload['text']
            if not href or not title or not title_matches_query(title, query):
                continue
            price = self._extract_price(text)
            if price is None:
                continue
            offers.append(
                Offer(
                    marketplace=self.marketplace,
                    title=title,
                    price=price,
                    currency='RUB',
                    url=clean_marketplace_url(href, self.marketplace.value),
                )
            )
        return offers

    def _group_items(self, items: list[dict]) -> dict[str, dict[str, str]]:
        grouped: dict[str, dict[str, str]] = {}
        for item in items:
            href = self._clean_text(item.get('href'))
            if not href:
                continue
            title = self._clean_text(item.get('title'))
            text = self._clean_text(item.get('text'))
            bucket = grouped.setdefault(href, {'title': '', 'text': ''})
            if title and (not bucket['title'] or len(title) > len(bucket['title'])):
                bucket['title'] = title
            if text:
                bucket['text'] = f"{bucket['text']}\n{text}".strip()
        return grouped

    def _extract_price(self, text: str) -> float | None:
        candidates: list[float] = []
        for line in text.splitlines():
            normalized = self._clean_text(line).replace('\u2009', ' ')
            lowered = normalized.lower()
            if not normalized or '₽' not in normalized:
                continue
            if normalized.startswith('+') or 'за ' in lowered or 'отзыв' in lowered or 'балл' in lowered:
                continue
            for match in _PRICE_RE.finditer(normalized):
                value = match.group(1).replace(' ', '').replace('\u2009', '')
                try:
                    price = float(value)
                except ValueError:
                    continue
                if price >= 1000:
                    candidates.append(price)
        return min(candidates) if candidates else None
