from __future__ import annotations

import re
from urllib.parse import quote_plus

from .base import MarketplaceClient, MarketplaceError
from ..models import Marketplace, Offer
from ..query_profiles import build_page_url, clean_marketplace_url, deduplicate_offers, get_overridden_url, title_matches_query

_PRICE_RE = re.compile(r'(\d[\d\s\u2009]{2,12})\s?[₽р]')


class WildberriesClient(MarketplaceClient):
    marketplace = Marketplace.WB
    unavailable_markers = MarketplaceClient.unavailable_markers + (
        "скоро закончится",
    )

    async def search(self, query: str) -> list[Offer]:
        base_url = get_overridden_url(query, self.marketplace.value) or (
            f"https://www.wildberries.ru/catalog/0/search.aspx?search={quote_plus(query)}"
        )
        offers: list[Offer] = []
        for page_num in range(1, self._max_pages + 1):
            url = build_page_url(base_url, page_num)
            page, context = await self._load_page(url)
            try:
                await self._safe_scroll(page)
                cards = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('article, .product-card, .j-card-item'))
                      .slice(0, 120)
                      .map((card) => {
                        const anchor = card.querySelector("a[href*='/catalog/'][href*='detail.aspx']");
                        const img = card.querySelector('img');
                        return {
                          href: anchor?.href || null,
                          title: (anchor?.getAttribute('aria-label') || img?.getAttribute('alt') || '').trim(),
                          text: (card.innerText || '').trim(),
                        };
                      })
                    """
                )
                page_offers = self._extract_cards(cards, query) if cards else []
                if not cards:
                    await self._capture_debug_page(
                        page,
                        query=query,
                        page_num=page_num,
                        reason='empty_page',
                        raw_items=cards,
                        parsed_offers=0,
                    )
                elif page_num == 1 or not page_offers:
                    await self._capture_debug_page(
                        page,
                        query=query,
                        page_num=page_num,
                        reason='first_page' if page_num == 1 else 'no_offers',
                        raw_items=cards,
                        parsed_offers=len(page_offers),
                    )
            finally:
                await self._browser.close_context(context)

            if not cards:
                break
            offers.extend(page_offers)

        offers = deduplicate_offers(offers)
        if not offers:
            raise MarketplaceError("нет доступных предложений")
        return offers

    def _extract_cards(self, cards: list[dict], query: str) -> list[Offer]:
        offers: list[Offer] = []
        for card in cards:
            href = self._clean_text(card.get('href'))
            title = self._clean_text(card.get('title'))
            text = self._clean_text(card.get('text'))
            if not href or not title or not title_matches_query(title, query):
                continue
            if self._looks_unavailable(text):
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
                    is_available=True,
                )
            )
        return offers

    def _extract_price(self, text: str) -> float | None:
        candidates: list[float] = []
        for line in text.splitlines():
            normalized = self._clean_text(line).replace('\u2009', ' ')
            lowered = normalized.lower()
            if not normalized or '₽' not in normalized:
                continue
            if normalized.startswith('+') or 'отзыв' in lowered or 'оцен' in lowered:
                continue
            for match in _PRICE_RE.finditer(normalized):
                value = match.group(1).replace(' ', '').replace('\u2009', '')
                try:
                    price = float(value)
                except ValueError:
                    continue
                if price >= 500:
                    candidates.append(price)
        return min(candidates) if candidates else None
